"""Settle acknowledged live turn records onto their original turn roots."""

import asyncio
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from vinga_server.boundary import BoundaryRefusal, Reach, check_feature
from vinga_server.config import ConfigError
from vinga_server.config.models import DatabaseConfig, ServerConfig
from vinga_server.conversations.records import Acknowledgement, TurnRecord
from vinga_server.events import ServerEvents
from vinga_server.events.catalog import TranscriptExportFailed, TranscriptsExported
from vinga_server.events.values import Count, SessionId, TranscriptExportFailure, Whole
from vinga_server.telemetry import DEFERRED_TURNS, Telemetry, TurnSettlement

logger = logging.getLogger(__name__)
events = ServerEvents(__name__)

TRANSCRIPTS_KEY = "server.telemetry.export_transcripts"
RECORDING_KEY = "server.conversations.enabled"
TEXT_KEY = "server.conversations.text"
MAX_CONTENT_BYTES = 256 * 1024
ACKNOWLEDGEMENT_TIMEOUT_S = 30.0
SHUTDOWN_TIMEOUT_S = 5.0
POLL_S = 0.05

TRANSCRIPTS_NEED_TELEMETRY = (
    "telemetry.export_transcripts is on with telemetry.enabled off; acknowledged "
    "conversation text is attached to a trace this server exported, and there is "
    "no trace to attach it to, so switch telemetry.enabled on or "
    "telemetry.export_transcripts off"
)
TRANSCRIPTS_NEED_AN_EXPORTER = (
    f"{TRANSCRIPTS_KEY} is on and no exporter was built, so no turn root can "
    "receive acknowledged text; switch server.telemetry.enabled on"
)


def build_transcript_export(
    config: ServerConfig,
    *,
    telemetry: Telemetry | None,
    database: DatabaseConfig,
    boundary: Reach | None = None,
    batch_turns: int = DEFERRED_TURNS,
    acknowledgement_timeout_s: float = ACKNOWLEDGEMENT_TIMEOUT_S,
    shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
) -> "TranscriptExport | None":
    """Build the collaborator only when recorded text and its flag exist."""
    del database, batch_turns
    conversations = config.conversations
    section = config.telemetry
    exporting = section is not None and section.export_transcripts
    if conversations is None or not conversations.enabled or not conversations.text:
        if exporting:
            logger.info(
                "%s is on and no conversation text is being recorded, so no "
                "transcripts will be exported; switch %s and %s on to record what "
                "is said",
                TRANSCRIPTS_KEY,
                RECORDING_KEY,
                TEXT_KEY,
            )
        return None
    if not exporting:
        return None
    assert section is not None
    if not section.enabled:
        raise ConfigError(TRANSCRIPTS_NEED_TELEMETRY)
    if telemetry is None:
        raise ConfigError(TRANSCRIPTS_NEED_AN_EXPORTER)
    try:
        check_feature(TRANSCRIPTS_KEY, section.reach, boundary)
    except BoundaryRefusal as refusal:
        raise ConfigError(str(refusal)) from None
    return TranscriptExport(
        telemetry=telemetry,
        backlog=DEFERRED_TURNS,
        acknowledgement_timeout_s=acknowledgement_timeout_s,
        shutdown_timeout_s=shutdown_timeout_s,
    )


@dataclass(frozen=True)
class _Row:
    record: TurnRecord
    acknowledgement: Acknowledgement | None


@dataclass(frozen=True)
class _Job:
    session: str
    utterance: str
    rows: tuple[_Row, ...]


class TranscriptExport:
    """Wait for every handover row, then enrich or release one root."""

    def __init__(
        self,
        *,
        telemetry: Telemetry,
        backlog: int,
        acknowledgement_timeout_s: float = ACKNOWLEDGEMENT_TIMEOUT_S,
        shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
        reads: Any | None = None,
        batch_turns: int = DEFERRED_TURNS,
    ) -> None:
        del reads, batch_turns
        self._telemetry = telemetry
        self._groups: dict[tuple[str, str], list[_Row]] = {}
        self._omitted: set[tuple[str, str]] = set()
        self._queue: queue.Queue[_Job] = queue.Queue(maxsize=max(1, backlog))
        self._acknowledgement_timeout_s = acknowledgement_timeout_s
        self._shutdown_timeout_s = shutdown_timeout_s
        self._admission = threading.RLock()
        self._stopping = threading.Event()
        self._worker: threading.Thread | None = None

    def turn_recorded(
        self,
        session: str,
        record: TurnRecord,
        acknowledgement: Acknowledgement | None,
        *,
        final: bool,
    ) -> None:
        """Offer one live row and mark the utterance complete at reply end."""
        if record.utterance is None:
            return
        key = (session, record.utterance)
        reason: TranscriptExportFailure | None = None
        with self._admission:
            if self._stopping.is_set():
                reason = TranscriptExportFailure.DROPPED
            else:
                rows = self._groups.setdefault(key, [])
                rows.append(_Row(record, acknowledgement))
                if final:
                    job = _Job(
                        session, record.utterance, tuple(self._groups.pop(key))
                    )
                    reason = self._admit(job)
        if reason is not None:
            self._omit(session, record.utterance, reason)

    def session_closed(
        self, session: str, recorded: Acknowledgement | None = None
    ) -> None:
        """Release incomplete utterance groups metadata-only."""
        del recorded
        with self._admission:
            omitted = [key for key in self._groups if key[0] == session]
            for key in omitted:
                self._groups.pop(key)
        for key in omitted:
            self._omit(key[0], key[1], TranscriptExportFailure.DROPPED)

    def turn_missing(self, session: str, utterance: str) -> None:
        """Finish an earlier handover row, or release a wholly empty root."""
        key = (session, utterance)
        reason: TranscriptExportFailure | None = None
        with self._admission:
            rows = self._groups.pop(key, None)
            if rows is not None:
                reason = self._admit(_Job(session, utterance, tuple(rows)))
        if rows is None:
            settlement = self._telemetry.release_turn(session, utterance)
            if settlement is not TurnSettlement.SETTLED:
                self._was_omitted(session, utterance)
        elif reason is not None:
            self._omit(session, utterance, reason)

    def omitted(self, session: str, utterance: str) -> None:
        """Report telemetry-ledger overflow without receiving span ownership."""
        key = (session, utterance)
        with self._admission:
            self._omitted.add(key)
        if not self._telemetry.acknowledge_turn_omission(session, utterance):
            self._was_omitted(session, utterance)
        self._failed(session, TranscriptExportFailure.DROPPED)

    async def shutdown(self) -> None:
        with self._admission:
            self._stopping.set()
            worker = self._worker
            omitted = tuple(self._groups)
            self._groups.clear()
        for session, utterance in omitted:
            self._omit(session, utterance, TranscriptExportFailure.DROPPED)
        if worker is None:
            return
        await asyncio.to_thread(worker.join, self._shutdown_timeout_s)
        if worker.is_alive():
            logger.warning(
                "the transcript exporter did not finish within %.0f s and was "
                "left behind; unsettled roots will be released by telemetry",
                self._shutdown_timeout_s,
            )

    def _admit(self, job: _Job) -> TranscriptExportFailure | None:
        with self._admission:
            if self._stopping.is_set():
                return TranscriptExportFailure.DROPPED
            if self._worker is None:
                worker = threading.Thread(
                    target=self._run, name="vinga-transcript-export", daemon=True
                )
                try:
                    worker.start()
                except Exception:  # noqa: BLE001 - export never breaks a reply
                    return TranscriptExportFailure.DROPPED
                self._worker = worker
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                return TranscriptExportFailure.DROPPED
        return None

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                job = self._queue.get(timeout=POLL_S)
            except queue.Empty:
                continue
            self._attempt(job)
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                return
            self._omit(job.session, job.utterance, TranscriptExportFailure.DROPPED)

    def _attempt(self, job: _Job) -> None:
        began = time.monotonic()
        reason = self._wait(job)
        if reason is not None:
            self._omit(job.session, job.utterance, reason)
            return
        try:
            content = _content(job.rows)
            content_size = _content_size(content)
        except Exception:  # noqa: BLE001 - content export never strands a root
            self._omit(job.session, job.utterance, TranscriptExportFailure.UNREADABLE)
            return
        if content_size > MAX_CONTENT_BYTES:
            self._omit(job.session, job.utterance, TranscriptExportFailure.DROPPED)
            return
        settlement = self._telemetry.settle_turn(
            job.session, job.utterance, content
        )
        if settlement is TurnSettlement.OMITTED:
            self._was_omitted(job.session, job.utterance)
            return
        if settlement is TurnSettlement.MISSING:
            if self._was_omitted(job.session, job.utterance):
                return
            self._failed(job.session, TranscriptExportFailure.NO_TRACE)
            return
        elapsed = int((time.monotonic() - began) * 1000)
        events.emit(
            lambda: TranscriptsExported(
                session=SessionId(job.session), turns=Count(1), elapsed_ms=Whole(elapsed)
            )
        )

    def _wait(self, job: _Job) -> TranscriptExportFailure | None:
        deadline = time.monotonic() + self._acknowledgement_timeout_s
        for row in job.rows:
            if row.acknowledgement is None:
                return TranscriptExportFailure.UNRECORDED
            while not self._stopping.is_set():
                if row.acknowledgement.wait(POLL_S):
                    break
                if row.acknowledgement.settled() or time.monotonic() >= deadline:
                    return TranscriptExportFailure.UNRECORDED
            else:
                return TranscriptExportFailure.DROPPED
        return None

    def _omit(
        self, session: str, utterance: str, reason: TranscriptExportFailure
    ) -> None:
        settlement = self._telemetry.release_turn(session, utterance)
        if settlement is TurnSettlement.OMITTED:
            self._was_omitted(session, utterance)
            return
        if settlement is TurnSettlement.MISSING and self._was_omitted(
            session, utterance
        ):
            return
        self._failed(session, reason)

    def _was_omitted(self, session: str, utterance: str) -> bool:
        key = (session, utterance)
        with self._admission:
            if key not in self._omitted:
                return False
            self._omitted.remove(key)
        return True

    def _failed(self, session: str, reason: TranscriptExportFailure) -> None:
        events.emit(lambda: TranscriptExportFailed(session=SessionId(session), reason=reason))


def _content(rows: tuple[_Row, ...]) -> dict[str, Any]:
    heard = [row.record.heard for row in rows if row.record.heard]
    if len(set(heard)) > 1:
        raise ValueError("conflicting heard text")
    replies = [row.record.reply for row in rows if row.record.reply]
    legs: list[dict[str, Any]] = []
    for row in rows:
        if row.record.legs:
            for leg in row.record.legs:
                legs.append(
                    {
                        key: value
                        for key, value in {
                            "agent": leg.agent,
                            "text": leg.text,
                            "input_tokens": leg.input_tokens,
                            "output_tokens": leg.output_tokens,
                        }.items()
                        if value is not None
                    }
                )
        elif row.record.reply:
            legs.append({"agent": row.record.agent, "text": row.record.reply})
    content: dict[str, Any] = {}
    if heard:
        content["input"] = heard[0]
    if replies:
        content["output"] = " ".join(replies)
    if legs:
        content["legs"] = legs
    return content


def _content_size(content: dict[str, Any]) -> int:
    """Weigh canonical values plus the direct-Langfuse aliases."""
    total = 0
    for key in ("input", "output"):
        value = content.get(key)
        if isinstance(value, str):
            total += 2 * len(value.encode("utf-8"))
    legs = content.get("legs")
    if legs:
        encoded = json.dumps(
            legs, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        total += 2 * len(encoded.encode("utf-8"))
    return total
