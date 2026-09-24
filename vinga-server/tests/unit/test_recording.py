"""A device session's recording, through its own interface.

Every collaborator is a double appending to one shared log, so each
ordering the owner promises is asserted as a list: the opening, the
close, the release after a codec failure. No database, no files, no
codecs: what is under test is the order, and what each collaborator is
handed.
"""

import logging
from typing import Any, cast

import pytest

from tests.support.events import both_formats
from vinga_server.conversations import SessionSink
from vinga_server.device import recording as recording_module
from vinga_server.device.recording import Recording, recordings
from vinga_server.events import SESSION_LOGGER

SID = "0f3c-recording"
OPENED_AT = 12.5
MANIFEST: dict[str, Any] = {"session": SID}
PROTOCOL = 2
REPLY_RATE = 24000
DEVICE_NAME = "Kitchen"

# Shaped like something an operator would be horrified to find in a
# log, and planted in a failing codec's message.
SENTINEL = "sk-live-0a7e33b1-never-a-real-credential"


def renames() -> list[tuple[str, str]]:
    return []


class Log(list[tuple[Any, ...]]):
    """The one log every double appends to."""


class Events:
    """The four calls the owner makes on a session's events object, and
    the one read its doubles make back."""

    def __init__(self, log: Log) -> None:
        self.log = log
        self.capture: Any = None
        self.attached: list[Any] = []

    def attach_capture(self, capture: Any) -> None:
        self.log.append(("attach_capture", capture))
        self.capture = capture

    def detach_capture(self) -> None:
        self.log.append(("detach_capture",))
        self.capture = None

    def attach(self, tap: Any) -> None:
        self.log.append(("attach", type(tap).__name__))
        self.attached.append(tap)

    def detach(self, tap: Any) -> None:
        self.log.append(("detach", type(tap).__name__))
        self.attached.remove(tap)

    def taps(self) -> tuple[Any, ...]:
        return tuple(self.attached)


class Capture:
    """An open capture; its close records whether the events object had
    already let go of it."""

    def __init__(self, log: Log, events: Events) -> None:
        self.log = log
        self.events = events
        self.closes = 0

    def close(self) -> None:
        self.closes += 1
        self.log.append(("capture.close", self.events.capture is None))


class Captures:
    def __init__(self, log: Log, capture: Capture | None) -> None:
        self.log = log
        self.capture = capture

    def open(self, session_id: str, opened_at: float, manifest: dict[str, Any]) -> Any:
        self.log.append(("captures.open", session_id, opened_at, manifest is MANIFEST))
        return self.capture

    def session_closed(self, session_id: str) -> None:
        self.log.append(("captures.session_closed", session_id))


class Store:
    """A conversation store: its open is logged with what it was handed,
    by identity where identity is the claim, and its close records
    whether the owner's sink was still attached at that instant."""

    def __init__(self, log: Log, events: Events, refuses: bool = False) -> None:
        self.log = log
        self.events = events
        self.refuses = refuses
        self.barrier = object()
        self.renames: Any = None

    def open_session(
        self,
        session_id: str,
        opened_at: float,
        manifest: dict[str, Any],
        renames: Any = None,
        device_name: str | None = None,
    ) -> None:
        self.renames = renames
        self.log.append(
            ("open_session", session_id, opened_at, manifest is MANIFEST, device_name)
        )
        if self.refuses:
            raise RuntimeError("the store would not open this session")

    def record_event(self, *args: object) -> None:
        return None

    def close_session(self, session_id: str, duration_s: float, reason: str) -> object:
        attached = any(isinstance(tap, SessionSink) for tap in self.events.taps())
        self.log.append(("close_session", session_id, duration_s, reason, attached))
        return self.barrier


class Transcripts:
    def __init__(self, log: Log) -> None:
        self.log = log
        self.handed: object = "never called"

    def session_closed(self, session: str, recorded: object = None) -> None:
        self.log.append(("transcripts.session_closed", session))
        self.handed = recorded


class LlmInput:
    def __init__(self, log: Log) -> None:
        self.log = log

    def session_closed(self, session: str) -> None:
        self.log.append(("llm_input.session_closed", session))


class Codecs:
    """`CaptureAudio`'s stand-in: its construction and both feeds on the
    log, its close closing the capture it was handed, as the real one's
    does."""

    def __init__(self, capture: Any, protocol_version: int, reply_sample_rate: int) -> None:
        self.capture = capture
        self.log = capture.log
        self.log.append(("CaptureAudio", capture is not None, protocol_version, reply_sample_rate))

    def microphone(self, data: bytes) -> None:
        self.log.append(("microphone", data))

    def reply(self, packet: bytes) -> None:
        self.log.append(("reply", packet))

    def close(self) -> None:
        self.capture.close()


class CodecUnavailable(RuntimeError):
    """What a media library raises when it cannot open a codec."""


def unopenable(*args: object, **kwargs: object) -> Any:
    raise CodecUnavailable(f"could not build the capture codecs for {SENTINEL}")


class Built:
    """One owner and every double it was built with, all on one log."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        declines: bool = False,
        refuses: bool = False,
        codecs: Any = Codecs,
        absent: str | None = None,
    ) -> None:
        self.log = Log()
        self.events = Events(self.log)
        self.capture = Capture(self.log, self.events)
        self.captures = Captures(self.log, None if declines else self.capture)
        self.store = Store(self.log, self.events, refuses=refuses)
        self.transcripts = Transcripts(self.log)
        self.llm_input = LlmInput(self.log)
        monkeypatch.setattr(recording_module, "CaptureAudio", codecs)
        present: dict[str, Any] = {
            "captures": self.captures,
            "conversations": self.store,
            "transcripts": self.transcripts,
            "llm_input": self.llm_input,
        }
        if absent is not None:
            present[absent] = None
        self.recording = Recording(SID, cast(Any, self.events), **present)

    def open(self) -> None:
        self.recording.open(
            OPENED_AT,
            MANIFEST,
            protocol_version=PROTOCOL,
            reply_sample_rate=REPLY_RATE,
            renames=renames,
            device_name=DEVICE_NAME,
        )


OPENING = [
    ("captures.open", SID, OPENED_AT, True),
    ("attach_capture", "the capture"),
    ("CaptureAudio", True, PROTOCOL, REPLY_RATE),
    ("open_session", SID, OPENED_AT, True, DEVICE_NAME),
    ("attach", "SessionSink"),
]

HANDOFFS = [
    ("captures.session_closed", SID),
    ("transcripts.session_closed", SID),
    ("llm_input.session_closed", SID),
]


def readable(log: Log, capture: Capture) -> list[tuple[Any, ...]]:
    """The log with the capture object named, so a list of tuples can be
    compared with a list written down."""
    return [
        tuple("the capture" if value is capture else value for value in entry)
        for entry in log
    ]


# open


def test_open_runs_the_opening_sequence_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    built = Built(monkeypatch)
    built.open()

    assert readable(built.log, built.capture) == OPENING
    # The store is handed the renames callable the owner was given, the
    # very one, so the window the session's thunk closes stays closed.
    assert built.store.renames is renames


def test_a_row_that_will_not_open_leaves_the_capture_for_the_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = Built(monkeypatch, refuses=True)
    with pytest.raises(RuntimeError):
        built.open()

    assert readable(built.log, built.capture) == OPENING[:4]
    assert built.events.capture is built.capture, "the capture was not left attached"

    del built.log[:]
    built.recording.close(1.0, "error")
    assert built.log == [("detach_capture",), ("capture.close", True), *HANDOFFS]
    assert built.transcripts.handed is None


def test_a_capture_store_that_declines_still_opens_the_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = Built(monkeypatch, declines=True)
    built.open()

    assert built.log == [
        ("captures.open", SID, OPENED_AT, True),
        ("open_session", SID, OPENED_AT, True, DEVICE_NAME),
        ("attach", "SessionSink"),
    ]


def test_codecs_that_will_not_open_release_the_capture_and_say_so_by_class(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    built = Built(monkeypatch, codecs=unopenable)
    with caplog.at_level(logging.INFO):
        built.open()

    assert readable(built.log, built.capture) == [
        ("captures.open", SID, OPENED_AT, True),
        ("attach_capture", "the capture"),
        ("detach_capture",),
        ("capture.close", True),
        ("open_session", SID, OPENED_AT, True, DEVICE_NAME),
        ("attach", "SessionSink"),
    ]

    (warning,) = [r for r in caplog.records if "could not start" in r.getMessage()]
    assert warning.name == SESSION_LOGGER
    assert warning.levelno == logging.WARNING
    assert warning.msg == "session %s: recording could not start (%s)"
    assert warning.args == (SID, "CodecUnavailable")
    assert SENTINEL not in both_formats(caplog)

    # Nothing is left to feed, and the close neither closes the capture
    # a second time nor skips a handoff.
    del built.log[:]
    built.recording.microphone(b"mic")
    built.recording.reply(b"reply")
    built.recording.close(1.0, "client")
    assert built.log == [
        ("detach", "SessionSink"),
        ("close_session", SID, 1.0, "client", False),
        *HANDOFFS,
    ]
    assert built.capture.closes == 1


# close


def test_close_detaches_before_it_closes_and_then_hands_the_session_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = Built(monkeypatch)
    built.open()
    del built.log[:]

    built.recording.close(3.5, "limit")

    assert built.log == [
        ("detach", "SessionSink"),
        ("close_session", SID, 3.5, "limit", False),
        ("detach_capture",),
        ("capture.close", True),
        *HANDOFFS,
    ]
    assert built.transcripts.handed is built.store.barrier
    assert built.events.taps() == ()
    assert built.events.capture is None


def test_a_close_without_an_open_still_makes_the_three_handoffs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = Built(monkeypatch)
    built.recording.close(0.0, "error")

    assert built.log == HANDOFFS
    assert built.transcripts.handed is None
    assert built.capture.closes == 0


@pytest.mark.parametrize("absent", ["captures", "conversations", "transcripts", "llm_input"])
def test_each_absent_collaborator_is_skipped(
    monkeypatch: pytest.MonkeyPatch, absent: str
) -> None:
    built = Built(monkeypatch, absent=absent)
    built.open()
    built.recording.microphone(b"mic")
    built.recording.reply(b"reply")
    built.recording.close(2.0, "client")

    names = [entry[0] for entry in built.log]
    gone = {
        "captures": {"captures.open", "captures.session_closed", "CaptureAudio"},
        "conversations": {"open_session", "close_session"},
        "transcripts": {"transcripts.session_closed"},
        "llm_input": {"llm_input.session_closed"},
    }
    assert not gone[absent] & set(names)
    for other, calls in gone.items():
        if other != absent:
            assert calls <= set(names), other


def test_an_owner_with_nothing_records_nothing() -> None:
    log = Log()
    events = Events(log)
    recording = recordings()(SID, cast(Any, events))
    recording.open(
        OPENED_AT,
        MANIFEST,
        protocol_version=PROTOCOL,
        reply_sample_rate=REPLY_RATE,
        renames=None,
        device_name=None,
    )
    recording.microphone(b"mic")
    recording.reply(b"reply")
    recording.close(1.0, "client")
    assert log == []


# the feeds


def test_the_feeds_reach_the_codecs_only_while_a_capture_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = Built(monkeypatch)
    built.recording.microphone(b"before")
    built.recording.reply(b"before")
    built.open()
    built.recording.microphone(b"during")
    built.recording.reply(b"during")
    built.recording.close(1.0, "client")
    built.recording.microphone(b"after")
    built.recording.reply(b"after")

    fed = [entry for entry in built.log if entry[0] in {"microphone", "reply"}]
    assert fed == [("microphone", b"during"), ("reply", b"during")]


def test_the_feeds_do_nothing_without_a_capture_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = Built(monkeypatch, absent="captures")
    built.open()
    built.recording.microphone(b"mic")
    built.recording.reply(b"reply")
    assert [entry for entry in built.log if entry[0] in {"microphone", "reply"}] == []


# the factory


def test_the_factory_builds_each_session_an_owner_over_the_shared_collaborators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = Built(monkeypatch)
    factory = recordings(
        cast(Any, built.captures),
        cast(Any, built.store),
        cast(Any, built.transcripts),
        cast(Any, built.llm_input),
    )
    first = factory(SID, cast(Any, built.events))
    second = factory("another", cast(Any, built.events))
    assert first is not second

    first.close(1.0, "client")
    second.close(1.0, "client")
    assert built.log == [
        *HANDOFFS,
        ("captures.session_closed", "another"),
        ("transcripts.session_closed", "another"),
        ("llm_input.session_closed", "another"),
    ]


# a close step that fails
#
# The close always reaches its end: each of its five steps is guarded on
# its own, a step that raises is reported and the next one runs, and the
# report is made of the session id and the step's own name and nothing
# the exception carried. The exception planted here carries a
# credential-shaped string twice over, once in its message and once as
# its CLASS NAME, which `type` accepts for any string: the correction
# `events/__init__.py` records beside `_offer`. Either one reaching a
# retained rendering is a leak.

CLASS_SENTINEL = "sk-live-5d2e91c4-planted-as-a-class-name"
MESSAGE_SENTINEL = "sk-live-7b40f6a8-planted-in-a-message"
Planted: type[Exception] = type(CLASS_SENTINEL, (Exception,), {})

STOPPED = "session %s: %s did not stop cleanly"


def plant(built: Built, where: str, raised: BaseException | None = None) -> None:
    """Make one of the close's calls fail after it has been logged, so
    the log shows the call was reached and everything after it shows
    what the failure cost."""
    owner, name = {
        "detach": (built.events, "detach"),
        "close_session": (built.store, "close_session"),
        "capture.close": (built.capture, "close"),
        "captures.session_closed": (built.captures, "session_closed"),
        "transcripts.session_closed": (built.transcripts, "session_closed"),
        "llm_input.session_closed": (built.llm_input, "session_closed"),
    }[where]
    original = getattr(owner, name)

    def failing(*args: Any, **kwargs: Any) -> Any:
        original(*args, **kwargs)
        raise raised if raised is not None else Planted(f"the far side said {MESSAGE_SENTINEL}")

    setattr(owner, name, failing)


CLOSING = [
    ("detach", "SessionSink"),
    ("close_session", SID, 2.0, "client", False),
    ("detach_capture",),
    ("capture.close", True),
    *HANDOFFS,
]

# Each close step, by the call planted to fail inside it and the name the
# owner reports it by. The row's step fails at either of its two calls.
FAILURES = [
    pytest.param("detach", "the conversation record", id="the sink's detachment"),
    pytest.param("close_session", "the conversation record", id="the row's close"),
    pytest.param("capture.close", "the capture", id="the capture"),
    pytest.param("captures.session_closed", "the capture upload", id="the capture upload"),
    pytest.param("transcripts.session_closed", "the transcript export", id="the transcript export"),
    pytest.param("llm_input.session_closed", "the LLM-input export", id="the LLM-input export"),
]


def closing_after(where: str) -> list[tuple[Any, ...]]:
    """The close as it runs with `where` failing: every call, since each
    step's failure leaves the steps after it to run, except the row's
    close when its sink's detachment is what failed."""
    if where == "detach":
        return [entry for entry in CLOSING if entry[0] != "close_session"]
    return CLOSING


class BrokenFilter(logging.Filter):
    """A filter somebody else installed on the session channel, which
    raises on the owner's report. `Logger.handle` calls a filter
    unwrapped, so this raises out of the logging call itself."""

    def __init__(self) -> None:
        super().__init__()
        self.raised = 0

    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg == STOPPED:
            self.raised += 1
            raise RuntimeError("the session channel's filter is broken")
        return True


@pytest.fixture
def broken_filter() -> Any:
    channel = logging.getLogger(SESSION_LOGGER)
    installed = BrokenFilter()
    channel.addFilter(installed)
    try:
        yield installed
    finally:
        channel.removeFilter(installed)


@pytest.mark.parametrize(("where", "step"), FAILURES)
def test_a_close_step_that_raises_is_reported_and_every_later_step_still_runs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    where: str,
    step: str,
) -> None:
    built = Built(monkeypatch)
    built.open()
    del built.log[:]
    plant(built, where)

    with caplog.at_level(logging.INFO):
        built.recording.close(2.0, "client")

    assert readable(built.log, built.capture) == closing_after(where)
    # A row whose close did not finish answered no barrier, and the
    # transcript export is handed what a session with no row hands it.
    if where in {"detach", "close_session"}:
        assert built.transcripts.handed is None
    else:
        assert built.transcripts.handed is built.store.barrier

    (warning,) = [r for r in caplog.records if r.msg == STOPPED]
    assert warning.name == SESSION_LOGGER
    assert warning.levelno == logging.WARNING
    assert warning.args == (SID, step)
    assert warning.exc_info is None
    rendered = both_formats(caplog)
    assert CLASS_SENTINEL not in rendered
    assert MESSAGE_SENTINEL not in rendered

    # Nothing is left held: no tap, no capture, no codecs to feed, and a
    # second close finds only the three handoffs to make.
    assert built.events.taps() == ()
    assert built.events.capture is None
    del built.log[:]
    built.recording.microphone(b"after")
    built.recording.reply(b"after")
    built.recording.close(2.0, "client")
    assert built.log == HANDOFFS
    assert built.capture.closes == 1


@pytest.mark.parametrize(("where", "step"), FAILURES)
def test_a_report_that_raises_costs_no_later_step(
    monkeypatch: pytest.MonkeyPatch,
    broken_filter: BrokenFilter,
    where: str,
    step: str,
) -> None:
    built = Built(monkeypatch)
    built.open()
    del built.log[:]
    plant(built, where)

    built.recording.close(2.0, "client")

    assert broken_filter.raised == 1, "the report never reached the broken filter"
    assert readable(built.log, built.capture) == closing_after(where)


class Interrupted(BaseException):
    """Not an `Exception`: what a `KeyboardInterrupt` or a `SystemExit`
    is to the guard."""


def test_what_is_not_an_exception_still_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    built = Built(monkeypatch)
    built.open()
    del built.log[:]
    plant(built, "captures.session_closed", Interrupted())

    with pytest.raises(Interrupted):
        built.recording.close(2.0, "client")

    assert readable(built.log, built.capture) == CLOSING[:5]
