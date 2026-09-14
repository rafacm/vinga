"""Small seams for driving live transcript settlement.

The exporter now asks telemetry only to settle or release one original turn
root. ``Exported`` records those calls while the unit suite drives the real
queue, worker, acknowledgement waits, and content projection.

The row reader helpers remain here for integration fixtures that plant stored
conversation rows. The live exporter does not read them.
"""

import threading
from typing import Any

from vinga_server.conversations.records import Acknowledgement
from vinga_server.conversations.threads import Reads, Unreadable
from vinga_server.telemetry import Telemetry, TurnSettlement

A_CONTEXT = "a-retained-context"


def settled(landed: bool = True) -> Acknowledgement:
    """An acknowledgement the writer has already answered."""
    answered = Acknowledgement()
    answered.settle(landed)
    return answered


def pending() -> Acknowledgement:
    """An acknowledgement the writer has not answered."""
    return Acknowledgement()


class Exported:
    """Record the two turn-root operations used by ``TranscriptExport``."""

    def __init__(
        self,
        contexts: dict[str, Any] | None = None,
        *,
        answer: bool = True,
        answers: list[bool] | None = None,
        settlement: TurnSettlement | None = None,
        acknowledges_omission: bool = True,
    ) -> None:
        del contexts
        self.settled: list[tuple[str, str, dict[str, Any]]] = []
        self.released: list[tuple[str, str]] = []
        self._answer = answer
        self._answers = list(answers or [])
        self._settlement = settlement
        self._acknowledges_omission = acknowledges_omission
        self._lock = threading.Lock()

    def settle_turn(
        self, session: str, utterance: str, attributes: dict[str, Any]
    ) -> TurnSettlement:
        with self._lock:
            self.settled.append((session, utterance, attributes))
            if self._answers:
                accepted = self._answers.pop(0)
            else:
                accepted = self._answer
            return self._settlement or (
                TurnSettlement.SETTLED if accepted else TurnSettlement.MISSING
            )

    def release_turn(self, session: str, utterance: str) -> TurnSettlement:
        with self._lock:
            self.released.append((session, utterance))
        return TurnSettlement.SETTLED

    def acknowledge_turn_omission(self, session: str, utterance: str) -> bool:
        del session, utterance
        return self._acknowledges_omission


def exporting(
    contexts: dict[str, Any] | None = None, **answers: Any
) -> tuple[Telemetry, Exported]:
    """Return the recorder under the production interface and its own type."""
    held = Exported(contexts, **answers)
    return held, held  # type: ignore[return-value]


class Reading:
    """Page planted rows like the conversation store read projection."""

    def __init__(
        self,
        rows: dict[str, list[dict[str, Any]]] | None = None,
        *,
        unreadable: bool = False,
        unreadable_after: int | None = None,
    ) -> None:
        self.rows = dict(rows or {})
        self.calls: list[tuple[str, int | None, int]] = []
        self._unreadable = unreadable
        self._unreadable_after = unreadable_after
        self._lock = threading.Lock()

    def transcript_rows(
        self, session: str, after: int | None = None, limit: int = 256
    ) -> "list[dict[str, Any]] | Unreadable":
        with self._lock:
            self.calls.append((session, after, limit))
            reads = len(self.calls)
        if self._unreadable:
            return Unreadable()
        if self._unreadable_after is not None and reads > self._unreadable_after:
            return Unreadable()
        held = self.rows.get(session, [])
        page = [row for row in held if after is None or row["id"] > after]
        return page[:limit]


def reading(
    rows: dict[str, list[dict[str, Any]]] | None = None, **failing: Any
) -> tuple[Reads, Reading]:
    """Return the row reader under its production interface and its own type."""
    held = Reading(rows, **failing)
    return held, held  # type: ignore[return-value]


def a_row(
    id: int,  # noqa: A002 - the column's own name
    heard: str | None = "turn the light on",
    reply: str | None = "Done.",
    agent: str | None = "alpha",
    legs: Any = None,
    t_ms: int | None = None,
    utterance: str | None = "0f1e2d3c4b5a69780f1e2d3c4b5a6978",
) -> dict[str, Any]:
    """One stored-row projection for integration fixtures."""
    return {
        "id": id,
        "t_ms": id * 100 if t_ms is None else t_ms,
        "agent": agent,
        "heard": heard,
        "reply": reply,
        "legs": legs,
        "utterance": utterance,
    }
