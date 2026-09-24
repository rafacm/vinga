"""The order a session's recording opens and closes in, pinned at the
session.

What the capture and conversation suites already pin is mostly end
state: the manifest is marked complete, no tap is left attached, the
row is closed. What they do not pin is the sequence those states are
reached by, and a sequence is exactly what a move of the recording's
lifecycle could change without any end state noticing. So every
collaborator a session's recording answers to (the capture store and
the capture it opens, the conversation store, the transcript export,
the LLM-input export, the codecs, the events object's attachments, and
the socket) is a double that appends to one shared log, and each test
asserts that log as a list.

Characterization: these were written against the session as it stood
before its recording had an owner, green there, and they are the proof
that the move changed nothing.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from tests.support.configs import base_config, capped_config, config_with_agent
from tests.support.sessions import (
    attached_capture,
    drive_reply,
    events_of,
    handshaken,
    recording_session,
)
from tests.support.sockets import LoopingSocket
from vinga_server.capture import CaptureStore
from vinga_server.conversations import SessionSink
from vinga_server.device import recording as recording_home
from vinga_server.device.boundary import DeviceGone, PlayableAudio
from vinga_server.device.capture_audio import CaptureAudio
from vinga_server.events import SESSION_LOGGER, CaptureTap
from vinga_server.protocol import framing

# One frame of silence, which the mock ASR answers with its transcript.
UTTERANCE = b"\x00\x00" * 320

# Long enough that a wedged session fails the assertion rather than the
# suite's scheduling, and never reached when the code is correct.
TIMEOUT_S = 10.0


class Witness:
    """The one log every double below appends to, and the session they
    are watching, which two of them ask about at the instant they run."""

    def __init__(self) -> None:
        self.log: list[tuple[Any, ...]] = []
        self.session: Any = None


class Capture:
    """A real capture, with its close on the log.

    The close records whether the events object had already let go of
    this capture when it ran, which is the order the close tail and the
    codec-failure release both promise: detached, then closed."""

    def __init__(self, capture: Any, witness: Witness) -> None:
        self.capture = capture
        self.witness = witness

    def __getattr__(self, name: str) -> Any:
        return getattr(self.capture, name)

    def close(self) -> None:
        detached = attached_capture(self.witness.session) is None
        self.witness.log.append(("capture.close", detached))
        self.capture.close()


class Captures:
    """A capture store that writes real files and logs its two calls.

    `declines` is the store answering None, which is what it does when
    its budget or its free-space floor says no."""

    def __init__(self, directory: Path, witness: Witness, declines: bool = False) -> None:
        self.store = CaptureStore(directory, 900.0, 2000.0, 0.0)
        self.witness = witness
        self.declines = declines

    def open(self, session_id: str, opened_at: float, manifest: dict[str, Any]) -> Any:
        self.witness.log.append(("captures.open", session_id))
        if self.declines:
            return None
        capture = self.store.open(session_id, opened_at, manifest)
        return None if capture is None else Capture(capture, self.witness)

    def session_closed(self, session_id: str) -> None:
        self.witness.log.append(("captures.session_closed", session_id))
        self.store.session_closed(session_id)


class Record:
    """A conversation store that keeps nothing and logs its two calls.

    Its close records whether the session's sink was still attached at
    that instant, and answers a barrier of its own making so the
    transcript export can be checked for being handed that very object.
    `refuses` makes the open raise, the way a store that cannot take a
    session does."""

    def __init__(self, witness: Witness, refuses: bool = False) -> None:
        self.witness = witness
        self.refuses = refuses
        self.barrier = object()
        self.duration_s: float | None = None

    def open_session(
        self,
        session_id: str,
        opened_at: float,
        manifest: dict[str, Any],
        renames: Any = None,
        device_name: str | None = None,
    ) -> None:
        self.witness.log.append(("open_session", session_id))
        if self.refuses:
            raise RuntimeError("the store would not open this session")

    def record_event(self, *args: object) -> None:
        return None

    def close_session(
        self, session_id: str, duration_s: float | None = None, reason: str | None = None
    ) -> object:
        taps = events_of(self.witness.session).taps()
        attached = any(isinstance(tap, SessionSink) for tap in taps)
        self.witness.log.append(("close_session", session_id, attached, reason))
        self.duration_s = duration_s
        return self.barrier


class Transcripts:
    """The transcript export's one call from a session, logged, with the
    barrier it was handed kept for an identity check."""

    def __init__(self, witness: Witness) -> None:
        self.witness = witness
        self.handed: object = "never called"

    def session_closed(self, session: str, recorded: object = None) -> None:
        self.witness.log.append(("transcripts.session_closed", session))
        self.handed = recorded


class LlmInput:
    """The LLM-input export's one call from a session, logged."""

    def __init__(self, witness: Witness) -> None:
        self.witness = witness

    def session_closed(self, session: str) -> None:
        self.witness.log.append(("llm_input.session_closed", session))


def logged_codecs(witness: Witness) -> type[CaptureAudio]:
    """The real `CaptureAudio`, with its construction and its reply feed
    on the log."""

    class LoggedCaptureAudio(CaptureAudio):
        def __init__(
            self, capture: Any, protocol_version: int, reply_sample_rate: int
        ) -> None:
            witness.log.append(("CaptureAudio", protocol_version, reply_sample_rate))
            super().__init__(capture, protocol_version, reply_sample_rate)

        def reply(self, packet: bytes) -> None:
            witness.log.append(("recorded", packet))
            super().reply(packet)

    return LoggedCaptureAudio


def watch_attachments(session: Any, witness: Witness, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the events object's capture attachment and detachment and the
    store sink's attach and detach on the log. Observer taps are attached
    at construction, before this, and the capture's own tap goes through
    `attach_capture`, so the sink is the one plain tap logged.

    A capture's detachment is logged only when a capture is attached:
    `attach_capture` clears whatever was there before attaching, through
    the same method, and that clearing detaches nothing."""
    events = events_of(session)
    attach, detach = events.attach, events.detach
    attach_capture, detach_capture = events.attach_capture, events.detach_capture

    def logged_attach(tap: Any) -> None:
        if isinstance(tap, SessionSink):
            witness.log.append(("attach", "SessionSink"))
        attach(tap)

    def logged_detach(tap: Any) -> None:
        if isinstance(tap, SessionSink):
            witness.log.append(("detach", "SessionSink"))
        detach(tap)

    def logged_attach_capture(capture: Any) -> None:
        witness.log.append(("attach_capture",))
        attach_capture(capture)

    def logged_detach_capture() -> None:
        if attached_capture(session) is not None:
            witness.log.append(("detach_capture",))
        detach_capture()

    monkeypatch.setattr(events, "attach", logged_attach)
    monkeypatch.setattr(events, "detach_capture", logged_detach_capture)
    monkeypatch.setattr(events, "detach", logged_detach)
    monkeypatch.setattr(events, "attach_capture", logged_attach_capture)


class Recorded:
    """One watched session and the doubles it was built with."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        config: Any = None,
        websocket: Any = None,
        declines: bool = False,
        refuses: bool = False,
    ) -> None:
        self.witness = Witness()
        self.directory = tmp_path / "captures"
        self.captures = Captures(self.directory, self.witness, declines=declines)
        self.record = Record(self.witness, refuses=refuses)
        self.transcripts = Transcripts(self.witness)
        self.llm_input = LlmInput(self.witness)
        self.websocket = websocket if websocket is not None else LoopingSocket()
        self.session = recording_session(
            config if config is not None else config_with_agent(),
            self.websocket,
            captures=self.captures,
            conversations=self.record,
            transcripts=self.transcripts,
            llm_input=self.llm_input,
        )
        self.witness.session = self.session
        monkeypatch.setattr(recording_home, "CaptureAudio", logged_codecs(self.witness))
        watch_attachments(self.session, self.witness, monkeypatch)

    @property
    def log(self) -> list[tuple[Any, ...]]:
        return self.witness.log

    @property
    def sid(self) -> str:
        return self.session.session_id

    def files(self) -> list[Path]:
        return sorted(self.directory.glob("*")) if self.directory.exists() else []

    def jsonl(self) -> list[dict[str, Any]]:
        (track,) = self.directory.glob("*.jsonl")
        return [json.loads(line) for line in track.read_text().splitlines()]

    def manifest(self) -> dict[str, Any]:
        (found,) = self.directory.glob("*.json")
        return json.loads(found.read_text())

    def opening(self) -> list[tuple[Any, ...]]:
        """The whole opening sequence, as today's session runs it."""
        return [
            ("captures.open", self.sid),
            ("attach_capture",),
            ("CaptureAudio", 1, 24000),
            ("open_session", self.sid),
            ("attach", "SessionSink"),
        ]

    def closing(self, reason: str) -> list[tuple[Any, ...]]:
        """The whole close sequence, as today's session runs it."""
        return [
            ("detach", "SessionSink"),
            ("close_session", self.sid, False, reason),
            ("detach_capture",),
            ("capture.close", True),
            ("captures.session_closed", self.sid),
            ("transcripts.session_closed", self.sid),
            ("llm_input.session_closed", self.sid),
        ]


async def ended_by_the_device(recorded: Recorded) -> None:
    """Serve the session until its hello is exchanged, then have the
    device close the socket and wait the session out."""
    task = asyncio.create_task(recorded.session.run())
    await handshaken(recorded.session, recorded.websocket)
    await recorded.websocket.close(1000, "goodbye")
    await asyncio.wait_for(task, timeout=TIMEOUT_S)


# The open


async def test_the_open_runs_capture_first_then_the_store_then_its_sink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capture first, store second, log last, as a sequence rather than
    as a final tap list: the capture store opens, the capture attaches,
    its codecs are built, and only then does the store open the row and
    its sink attach. A row opened before the capture, with the taps
    still attached in this order, would change what a failure at either
    opening leaves behind."""
    recorded = Recorded(tmp_path, monkeypatch)
    task = asyncio.create_task(recorded.session.run())
    await handshaken(recorded.session, recorded.websocket)

    assert recorded.log == recorded.opening()
    # And the consequence a reader checks first: the capture's tap
    # precedes the sink's, whatever observers sit around them.
    taps = [
        type(tap)
        for tap in events_of(recorded.session).taps()
        if isinstance(tap, CaptureTap | SessionSink)
    ]
    assert taps == [CaptureTap, SessionSink]

    await recorded.websocket.close(1000, "goodbye")
    await asyncio.wait_for(task, timeout=TIMEOUT_S)


async def test_a_capture_store_that_declines_leaves_the_row_opening_normally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = Recorded(tmp_path, monkeypatch, declines=True)
    task = asyncio.create_task(recorded.session.run())
    await handshaken(recorded.session, recorded.websocket)
    # The session converses: a whole reply, audio and all.
    await drive_reply(recorded.session, UTTERANCE)
    await recorded.websocket.close(1000, "goodbye")
    await asyncio.wait_for(task, timeout=TIMEOUT_S)

    sid = recorded.sid
    assert recorded.log == [
        ("captures.open", sid),
        ("open_session", sid),
        ("attach", "SessionSink"),
        ("detach", "SessionSink"),
        ("close_session", sid, False, "client"),
        ("captures.session_closed", sid),
        ("transcripts.session_closed", sid),
        ("llm_input.session_closed", sid),
    ]
    assert recorded.transcripts.handed is recorded.record.barrier
    assert recorded.files() == [], "a declined capture still wrote files"


async def test_a_store_that_will_not_open_still_leaves_the_capture_released(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The row's open raising, after the capture opened and attached:
    the session ends through its error arm, and its close still detaches
    and closes the capture and makes all three handoffs in the close's
    order, the transcript export handed no barrier because no row was
    ever closed."""
    recorded = Recorded(tmp_path, monkeypatch, refuses=True)
    with caplog.at_level("INFO"), pytest.raises(RuntimeError):
        await asyncio.wait_for(recorded.session.run(), timeout=TIMEOUT_S)

    sid = recorded.sid
    assert recorded.log == [
        ("captures.open", sid),
        ("attach_capture",),
        ("CaptureAudio", 1, 24000),
        ("open_session", sid),
        ("detach_capture",),
        ("capture.close", True),
        ("captures.session_closed", sid),
        ("transcripts.session_closed", sid),
        ("llm_input.session_closed", sid),
    ]
    assert recorded.transcripts.handed is None
    (closed,) = [r for r in caplog.records if getattr(r, "event", None) == "session_closed"]
    assert closed.reason == "error"
    assert recorded.manifest()["capture"]["complete"] is True
    assert attached_capture(recorded.session) is None


# The close


async def test_the_close_runs_in_its_order_and_hands_on_the_barrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sink detached before the row is closed, so nothing reaches the
    row after its close record is queued; the row closed; the capture
    detached, then closed; then the three post-close handoffs, narrow to
    wide, the transcript export handed the very barrier the row's close
    answered."""
    recorded = Recorded(tmp_path, monkeypatch)
    await ended_by_the_device(recorded)

    assert recorded.log == recorded.opening() + recorded.closing("client")
    assert recorded.transcripts.handed is recorded.record.barrier
    # And `session_closed` is the last line of the decision track.
    assert recorded.jsonl()[-1]["event"] == "session_closed"
    assert recorded.manifest()["capture"]["complete"] is True


async def test_the_row_is_closed_with_the_reason_and_duration_the_session_ended_with(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One non-default reason, the duration cap, and the duration read no
    earlier than the one `session_closed` carries."""
    recorded = Recorded(tmp_path, monkeypatch, config=capped_config(0.3))
    with caplog.at_level("INFO"):
        await asyncio.wait_for(recorded.session.run(), timeout=TIMEOUT_S)

    assert recorded.log == recorded.opening() + recorded.closing("limit")
    (closed,) = [r for r in caplog.records if getattr(r, "event", None) == "session_closed"]
    assert closed.reason == "limit"
    assert isinstance(recorded.record.duration_s, float)
    assert recorded.record.duration_s >= closed.duration_s


# The reply feed


class SendingSocket(LoopingSocket):
    """A socket whose binary sends go on the shared log, and whose
    `fails_at`th send raises the way a vanished device's does."""

    def __init__(self, witness: Witness, fails_at: int) -> None:
        super().__init__()
        self.witness = witness
        self.fails_at = fails_at
        self.sent = 0

    async def send_bytes(self, data: bytes) -> None:
        self.witness.log.append(("wire", data))
        self.sent += 1
        if self.sent == self.fails_at:
            raise RuntimeError("the device went away")


async def test_a_reply_frame_is_recorded_after_it_is_sent_and_never_if_it_was_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    witness_socket = SendingSocket(Witness(), fails_at=3)
    recorded = Recorded(tmp_path, monkeypatch, websocket=witness_socket)
    witness_socket.witness = recorded.witness
    task = asyncio.create_task(recorded.session.run())
    await handshaken(recorded.session, recorded.websocket)

    packets = [b"first", b"second", b"third"]
    del recorded.log[:]
    with pytest.raises(DeviceGone):
        await recorded.session.send_audio(PlayableAudio(packets))

    version = recorded.session.protocol_version
    assert recorded.log == [
        ("wire", framing.wrap(version, b"first")),
        ("recorded", b"first"),
        ("wire", framing.wrap(version, b"second")),
        ("recorded", b"second"),
        ("wire", framing.wrap(version, b"third")),
    ]

    await recorded.websocket.close(1000, "goodbye")
    await asyncio.wait_for(task, timeout=TIMEOUT_S)


# The refusals


class RefusedDeviceId(LoopingSocket):
    def __init__(self) -> None:
        super().__init__()
        self.headers = {"device-id": "not-a-mac", "client-id": "unused"}


class NoHello(LoopingSocket):
    def __init__(self) -> None:
        super().__init__()
        self.inbox.get_nowait()
        self.inbox.put_nowait(
            {"type": "websocket.receive", "text": json.dumps({"type": "listen"})}
        )


@pytest.mark.parametrize(
    ("config", "socket"),
    [
        (config_with_agent, RefusedDeviceId),
        (lambda: base_config(default_agent=None), LoopingSocket),
        (config_with_agent, NoHello),
    ],
    ids=["a bad Device-Id", "no agent", "no hello"],
)
async def test_a_session_refused_before_its_hello_records_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    config: Any,
    socket: Any,
) -> None:
    recorded = Recorded(tmp_path, monkeypatch, config=config(), websocket=socket())
    with caplog.at_level(logging.INFO):
        await asyncio.wait_for(recorded.session.run(), timeout=TIMEOUT_S)

    assert recorded.websocket.closed is not None, "the session was not refused"
    assert recorded.log == []
    assert recorded.files() == []
    assert [r for r in caplog.records if getattr(r, "event", None) == "session_open"] == []


# A close step that fails
#
# Not characterization, unlike everything above: the session's close
# path promises it always reaches its end, and a recording step that
# raised used to leave it through the `finally`, skipping the handoffs
# behind it and the re-raise of a cancellation the close was holding.

STOPPED = "session %s: %s did not stop cleanly"


class BrokenFilter(logging.Filter):
    """A filter on the session channel that raises on the recording's
    report, where `Logger.handle` calls it unwrapped."""

    def __init__(self) -> None:
        super().__init__()
        self.raised = 0

    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg == STOPPED:
            self.raised += 1
            raise RuntimeError("the session channel's filter is broken")
        return True


class UploadWouldNotStart(Exception):
    """What a capture store's handoff raises when its uploader cannot
    start a worker thread."""


@pytest.mark.parametrize("broken", [False, True], ids=["a working channel", "a broken channel"])
async def test_a_failing_handoff_skips_no_later_one_and_loses_no_held_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    broken: bool,
) -> None:
    """A cleanup step cancelled, which the close holds, and then the
    capture store's handoff raising. The transcript and LLM-input
    handoffs are still made, and the task still ends cancelled, with the
    session channel working and with it broken on the report."""
    recorded = Recorded(tmp_path, monkeypatch)
    task = asyncio.create_task(recorded.session.run())
    await handshaken(recorded.session, recorded.websocket)

    async def cancelled() -> None:
        raise asyncio.CancelledError

    assert recorded.session.runtime is not None
    monkeypatch.setattr(recorded.session.runtime, "close", cancelled)

    def would_not_start(session_id: str) -> None:
        recorded.log.append(("captures.session_closed", session_id))
        raise UploadWouldNotStart("can't start new thread")

    monkeypatch.setattr(recorded.captures, "session_closed", would_not_start)

    channel = logging.getLogger(SESSION_LOGGER)
    installed = BrokenFilter()
    if broken:
        channel.addFilter(installed)
    try:
        with caplog.at_level("INFO"):
            await recorded.websocket.close(1000, "goodbye")
            await asyncio.wait([task], timeout=TIMEOUT_S)
    finally:
        channel.removeFilter(installed)

    assert task.done(), "the session never ended"
    assert task.cancelled(), "the held cancellation did not reach the caller"
    assert recorded.log == recorded.opening() + recorded.closing("client")
    assert recorded.transcripts.handed is recorded.record.barrier
    reports = [r for r in caplog.records if r.msg == STOPPED]
    if broken:
        assert installed.raised == 1, "the report never reached the broken filter"
        assert reports == []
    else:
        (report,) = reports
        assert report.args == (recorded.sid, "the capture upload")
