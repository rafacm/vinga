"""The switch, the refusals, and the shape of a trace.

Three claims live here and one of them is the milestone's whole point.

**Off costs nothing.** An absent section, or one with the flag off,
builds no object, imports nothing and attaches no tap, so the rest of
this repository's suites running with no `telemetry:` section anywhere
are themselves the proof the default path is untouched. What is pinned
here is the sentence that says so: `build_telemetry(None)` is None.

**Every refusal is a sentence, and none of them chains.** The three
ways an enabled exporter can be wrong (the data boundary, the missing
extra,
an unsupported protocol) are `ConfigError` with a message written to be
printed as it is, and each is raised outside the handler that decided
it, so nothing from the library underneath rides along.

**A trace is derived, not invented.** The fold is driven with real
emissions through a real `SessionEvents` into the SDK's in-memory
exporter, and the spans that come back are read exactly: one root span
per session, one linked root span per turn with a trace id of its own,
and everything else a span event on whichever of the two is open.

The saturation case, the two-lifespans case and the partial-startup
case are in `tests/integration/test_telemetry_hardening.py`: they are
about the background thread and the composition, which is the other
lane's business.
"""

import contextlib
import logging
import sys
import threading
import time
from collections.abc import Iterator

import pytest

from tests.support.events import both_formats, every_format
from tests.support.telemetry import (
    AGENT,
    CONVERSATION,
    DEVICE,
    SESSION,
    Clock,
    Deliveries,
    assemble_prompt,
    barge_in,
    capture_emitter,
    capture_started,
    capture_upload_failed,
    capture_uploaded,
    close_session,
    drop_frames,
    exporting,
    finish_reply,
    finish_speaking,
    finished,
    go_idle,
    hand_over,
    hear,
    named,
    open_session,
    released,
    round_done,
    session_events,
    start_speaking,
    start_turn,
    synthesize,
    upload_emitter,
)
from vinga_server.boundary import BoundaryRefusal, Reach, check_feature
from vinga_server.config import ConfigError
from vinga_server.config.models import TelemetryConfig
from vinga_server.events import Emission, attach_server_tap, detach_server_tap
from vinga_server.events.values import CloseReason, ReplyOutcome
from vinga_server.telemetry import (
    _QUIETING,
    APPROVED,
    NEEDS_THE_OTEL_EXTRA,
    OTEL_NAMESPACE,
    OTLP_PROTOCOL_ENV,
    OTLP_TRACES_PROTOCOL_ENV,
    SERVICE,
    SHAPES,
    SUPPORTED_PROTOCOL,
    TELEMETRY_KEY,
    UNSUPPORTED_PROTOCOL,
    Telemetry,
    TranscriptTurn,
    build_telemetry,
)

# The four modules `_import_sdk` imports from, which is what a fake
# import failure has to take away. Named here rather than guessed, so a
# module that moves fails this list rather than turning the fake into a
# test of nothing.
SDK_MODULES = (
    "opentelemetry.sdk.resources",
    "opentelemetry.sdk.trace",
    "opentelemetry.sdk.trace.export",
)


@pytest.fixture(autouse=True)
def _no_protocol_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer with a collector configured must not change what
    these cases mean, and the protocol variable is the one this module
    reads."""
    monkeypatch.delenv(OTLP_PROTOCOL_ENV, raising=False)
    monkeypatch.delenv(OTLP_TRACES_PROTOCOL_ENV, raising=False)


@pytest.fixture(autouse=True)
def _no_lease_outlives_its_case() -> Iterator[None]:
    """Every exporter a case built is released at the end of it.

    The SDK's silence is one process-wide lease now, so an exporter
    nobody released holds it for the rest of the run: the cases about
    the count below would read somebody else's, and every case after
    them would run against a silenced namespace. Asserted as well as
    drained, because a leak that this tidies away is a leak a server
    would have too.
    """
    yield
    released()
    assert _QUIETING.held() == 0, "a case left an exporter holding the SDK's silence"


# --- off ---------------------------------------------------------------


def test_no_section_builds_nothing() -> None:
    """The default, and the sentence the milestone claims: absent means
    never, and never means no object to attach."""
    assert build_telemetry(None) is None


def test_the_flag_off_builds_nothing() -> None:
    """A section left in a configuration file is not consent. It is the
    flag that switches this on, exactly as it is for `capture` and
    `conversations`."""
    assert build_telemetry(TelemetryConfig(enabled=False)) is None


def test_nothing_is_attached_when_nothing_is_built() -> None:
    """The other half of "costs nothing": no tap on the session, and no
    tap on the server hub either.

    Read through the emitter rather than asserted about the return
    value, because what would cost a reply is a consumer on the seam,
    and that is a thing an emitter has or does not.
    """
    from vinga_server.events import SessionEvents, server_taps

    assert build_telemetry(None) is None
    # An emitter built after the non-build has exactly the taps a server
    # without telemetry has, which is none of its own, and the server
    # hub is untouched.
    assert SessionEvents(SESSION, clock=Clock()).taps() == ()
    assert server_taps() == ()


# --- the refusals ------------------------------------------------------


@pytest.mark.parametrize("boundary", [Reach.HOST, Reach.NETWORK])
def test_a_narrow_boundary_refuses_before_anything_is_constructed(
    monkeypatch: pytest.MonkeyPatch, boundary: Reach
) -> None:
    """The boundary refusal, and the claim that makes it worth having:
    the exporter's constructor is never reached.

    Both halves are asserted, because either alone is weak. A sentence
    without the never-reached pin would pass an implementation that
    built the exporter and then threw it away, which is a socket opened
    and a thread started inside a declared boundary; a never-reached pin
    without the sentence would pass one that refused for the wrong
    reason.

    Driven at BOTH narrow boundaries, and `network` is the cell the old
    boolean had no way to express: an exporter reaches the internet as
    far as this server can tell, so a LAN-bounded deployment refuses it
    exactly as a host-bounded one does. An implementation that read the
    boundary as "not host" would pass the first and fail the second.
    """
    reached = []
    monkeypatch.setattr(
        "vinga_server.telemetry._otlp_exporter", lambda: reached.append(True)
    )
    monkeypatch.setattr(
        "vinga_server.telemetry._import_sdk",
        lambda: reached.append("imported"),
    )

    with pytest.raises(ConfigError) as refusal:
        build_telemetry(TelemetryConfig(enabled=True), boundary=boundary)

    assert reached == [], "something was imported or constructed inside the boundary"
    assert "data boundary" in str(refusal.value)
    assert TELEMETRY_KEY in str(refusal.value)


def test_the_boundary_sentence_is_the_boundary_modules_own() -> None:
    """One home for the rule, checked rather than asserted: the words
    the boot prints are the words `boundary.py` composes, so a telemetry
    rule of its own would show up here as two sentences."""
    with pytest.raises(BoundaryRefusal) as direct:
        check_feature(TELEMETRY_KEY, Reach.INTERNET, Reach.HOST)
    with pytest.raises(ConfigError) as boot:
        build_telemetry(TelemetryConfig(enabled=True), boundary=Reach.HOST)

    assert str(boot.value) == str(direct.value)


def test_the_boundary_refusal_chains_nothing() -> None:
    """Raised after the `except` closed, so uvicorn renders this
    sentence and not the exception underneath it."""
    with pytest.raises(ConfigError) as refusal:
        build_telemetry(TelemetryConfig(enabled=True), boundary=Reach.HOST)

    assert refusal.value.__cause__ is None
    assert refusal.value.__context__ is None


def test_the_boundary_refusal_carries_no_value() -> None:
    """The boundary sentences carry no value read from a configuration,
    and this one has an environment full of candidates beside it: the
    endpoint is never read at all on this path, so there is nothing of
    it to print."""
    with pytest.raises(ConfigError) as refusal:
        build_telemetry(TelemetryConfig(enabled=True), boundary=Reach.HOST)

    said = str(refusal.value)
    assert "http" not in said
    assert "OTEL" not in said


def test_an_internet_boundary_permits_the_exporter() -> None:
    """The widest declared boundary forbids nothing, which is the half
    of the rule a rank comparison has and a boolean cannot: an operator
    who declares `internet` is asking every entry to state its reach,
    not switching tracing off."""
    telemetry, _ = exporting(boundary=Reach.INTERNET)
    assert telemetry is not None


def test_a_boundary_with_telemetry_off_is_not_refused() -> None:
    """The rule is about an exporter that would exist. A bounded
    deployment with no telemetry section boots exactly as it did."""
    assert build_telemetry(None, boundary=Reach.HOST) is None
    assert build_telemetry(TelemetryConfig(enabled=False), boundary=Reach.HOST) is None


def test_the_missing_extra_refusal_names_the_extra_and_the_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal an install without the packages meets, faked here so
    the sentence is pinned in every lane.

    Faked by taking the SDK's modules out of `sys.modules`, which is a
    genuine `ImportError` raised by the real import statement in
    `_import_sdk` rather than a stub standing in for one: `None` in
    `sys.modules` is how the interpreter itself says a module is not
    importable. The other half of this claim is the tier lane, which
    boots a real `[serve]` install that never had them.
    """
    for module in SDK_MODULES:
        monkeypatch.setitem(sys.modules, module, None)

    with pytest.raises(ConfigError) as refusal:
        build_telemetry(TelemetryConfig(enabled=True))

    assert str(refusal.value) == NEEDS_THE_OTEL_EXTRA
    assert "server.telemetry" in NEEDS_THE_OTEL_EXTRA
    assert "uv sync --extra otel" in NEEDS_THE_OTEL_EXTRA
    # And no ImportError travels with it: it carries a module search
    # path and a traceback through somebody else's package.
    assert refusal.value.__cause__ is None
    assert refusal.value.__context__ is None


def test_an_unsupported_protocol_is_refused_by_naming_the_supported_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The distribution ships one transport, so a variable naming
    another is refused rather than half-honored.

    The rejected spelling is never quoted back: it is an
    operator-supplied string, and a refusal that echoed it would put
    whatever was in that variable into the retained log.
    """
    monkeypatch.setenv(OTLP_PROTOCOL_ENV, "grpc-with-a-secret-in-it")

    with pytest.raises(ConfigError) as refusal:
        build_telemetry(TelemetryConfig(enabled=True))

    assert str(refusal.value) == UNSUPPORTED_PROTOCOL
    assert SUPPORTED_PROTOCOL in UNSUPPORTED_PROTOCOL
    assert "grpc-with-a-secret-in-it" not in str(refusal.value)


def test_an_unsupported_traces_specific_protocol_is_refused_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The variable the SDK actually reads first.

    A deployment exporting metrics over gRPC writes the general variable
    and the traces-specific one, and it is the second that decides where
    the traces go. So it is refused on its own, and by a sentence that
    names it: a refusal naming only the general variable sends an
    operator to edit a value that was never going to be used, and
    following it changes nothing at all.
    """
    monkeypatch.setenv(OTLP_PROTOCOL_ENV, SUPPORTED_PROTOCOL)
    monkeypatch.setenv(OTLP_TRACES_PROTOCOL_ENV, "grpc")

    with pytest.raises(ConfigError) as refusal:
        build_telemetry(TelemetryConfig(enabled=True))

    said = str(refusal.value)
    assert said == UNSUPPORTED_PROTOCOL
    assert OTLP_TRACES_PROTOCOL_ENV in said
    assert OTLP_PROTOCOL_ENV in said
    # And the rejected spelling is still never quoted back.
    assert "grpc" not in said


def test_the_traces_protocol_variable_wins_over_the_general_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SDK's own precedence, so a deployment exporting metrics over
    gRPC and traces over HTTP is not refused for the metrics half."""
    monkeypatch.setenv(OTLP_PROTOCOL_ENV, "grpc")
    monkeypatch.setenv(OTLP_TRACES_PROTOCOL_ENV, SUPPORTED_PROTOCOL)
    telemetry, _ = exporting()

    assert telemetry is not None


def test_the_supported_protocol_written_out_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OTLP_PROTOCOL_ENV, SUPPORTED_PROTOCOL)
    telemetry, _ = exporting()

    assert telemetry is not None


# --- the trace's shape -------------------------------------------------


def test_a_session_becomes_one_root_span() -> None:
    """The session-lifecycle trace: opened at `session_open`, closed at
    `session_closed`, with the close reason on it."""
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    opened = open_session(events)
    clock.tick(12.0)
    closed = close_session(events, reason=CloseReason.IDLE)

    span = named(finished(telemetry, memory), "session")
    assert span.parent is None
    assert span.attributes["vinga.session.id"] == SESSION
    assert span.attributes["vinga.device.id"] == DEVICE
    assert span.attributes["vinga.agent"] == AGENT
    assert span.attributes["vinga.conversation.id"] == CONVERSATION
    assert span.attributes["vinga.session.close_reason"] == "idle"
    assert span.end_time - span.start_time == pytest.approx(
        int((closed - opened) * 1e9), abs=1000
    )


def test_a_turn_is_its_own_trace_linked_to_the_session() -> None:
    """Linked, not parented, which is the whole of the lifecycle
    decision: a backend can list a session's turns without every turn
    hiding inside one enormous trace."""
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    clock.tick(1.0)
    start_turn(events, speech_ms=900)
    clock.tick(2.0)
    finish_reply(events, outcome=ReplyOutcome.COMPLETED, sentences=3)
    clock.tick(1.0)
    close_session(events)

    spans = finished(telemetry, memory)
    session, turn = named(spans, "session"), named(spans, "turn")

    assert turn.parent is None, "a turn is linked to its session, never parented"
    assert turn.context.trace_id != session.context.trace_id
    assert [link.context.span_id for link in turn.links] == [
        session.context.span_id
    ]
    assert turn.attributes["vinga.turn.speech_ms"] == 900
    assert turn.attributes["vinga.turn.barge_in"] is False
    assert turn.attributes["vinga.turn.outcome"] == "completed"
    assert turn.attributes["vinga.turn.sentences_spoken"] == 3


def test_the_turn_span_opens_at_the_stamp_the_event_carries() -> None:
    """`turn_started` is stamped with the instant the user stopped
    speaking, which a confirmed barge-in decides several hundred
    milliseconds before the reply it starts. The span has to open there
    and not where the event was said."""
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    utterance_ended = clock.tick(1.0)
    clock.tick(0.4)
    said_at = start_turn(events, barge_in=True, at=utterance_ended)
    clock.tick(1.0)
    finish_reply(events)
    close_session(events)

    turn = named(finished(telemetry, memory), "turn")
    assert said_at == utterance_ended
    assert turn.attributes["vinga.turn.barge_in"] is True


def test_two_turns_in_one_session_are_two_traces() -> None:
    """Consecutive turns, each with its own trace id and each linked to
    the same session span."""
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    for _ in range(2):
        clock.tick(1.0)
        start_turn(events)
        clock.tick(1.0)
        finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    turns = [span for span in spans if span.name == "turn"]
    session = named(spans, "session")

    assert len(turns) == 2
    assert len({turn.context.trace_id for turn in turns}) == 2
    for turn in turns:
        assert [link.context.span_id for link in turn.links] == [session.context.span_id]


def test_an_event_between_turns_lands_on_the_session_span() -> None:
    """`session_idle` and `handover` have no turn to belong to, so they
    are span events on the session."""
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    clock.tick(1.0)
    go_idle(events)
    clock.tick(1.0)
    hand_over(events)
    close_session(events)

    session = named(finished(telemetry, memory), "session")
    assert [event.name for event in session.events] == ["session_idle", "handover"]
    idle = session.events[0]
    assert idle.attributes["idle_s"] == pytest.approx(120.0)
    # The identities are on the span already, so a span event does not
    # repeat them.
    assert "session" not in idle.attributes
    assert "device" not in idle.attributes


def test_an_event_inside_a_turn_lands_on_the_turn_span() -> None:
    """A straggler emitted while a reply is in flight belongs to the
    turn being spoken, which is what makes a turn trace readable on its
    own."""
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    start_turn(events)
    clock.tick(0.5)
    hand_over(events)
    clock.tick(0.5)
    finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    assert [event.name for event in named(spans, "turn").events] == ["handover"]
    assert named(spans, "session").events == ()


def test_the_session_span_carries_what_the_session_opened_against() -> None:
    """The resolved provider entries, which the issue asks for as
    session-level context and which no span carried at all.

    Flattened per stage rather than dumped as a blob: a backend filters
    on attributes, and a JSON string of a nested mapping would be
    present and unqueryable, which for this question is the same as
    absent. The four sanitized names off each built provider are the
    whole of what an entry may hold, so nothing off a provider
    configuration can reach a span this way.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    close_session(events)

    span = named(finished(telemetry, memory), "session")
    assert span.attributes["vinga.provider.llm.name"] == "claude"
    assert span.attributes["vinga.provider.llm.type"] == "anthropic"
    assert span.attributes["vinga.provider.llm.host"] == "api.anthropic.com"
    assert span.attributes["vinga.provider.llm.model"] == "claude-sonnet-4-5"
    assert span.attributes["vinga.provider.vad.type"] == "silero"
    # An engine running in this process names no host, and absence is
    # the answer the catalog gives rather than a null.
    assert "vinga.provider.vad.host" not in span.attributes
    # And the other bound agent's entries are not on this span: what a
    # span says is what it was talking through.
    assert "openai_compatible" not in str(dict(span.attributes))


def test_a_turn_after_a_handover_carries_the_new_agents_providers() -> None:
    """The context follows the agent, which is the whole reason
    `session_open` carries every bound agent's entries.

    Two turns, a handover between them, and each turn stamped with the
    providers the agent speaking it actually ran on. An exporter that
    kept only the opening agent's entries would put the first agent's
    model on the second agent's turn, which is worse than saying
    nothing.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    clock.tick(1.0)
    start_turn(events)
    clock.tick(1.0)
    finish_reply(events)
    clock.tick(0.5)
    hand_over(events)
    clock.tick(0.5)
    start_turn(events)
    clock.tick(1.0)
    finish_reply(events)
    close_session(events)

    turns = [span for span in finished(telemetry, memory) if span.name == "turn"]
    before, after = sorted(turns, key=lambda span: span.start_time)

    assert before.attributes["vinga.provider.llm.name"] == "claude"
    assert before.attributes["vinga.provider.llm.model"] == "claude-sonnet-4-5"
    assert after.attributes["vinga.provider.llm.name"] == "local"
    assert after.attributes["vinga.provider.llm.model"] == "qwen3"
    assert after.attributes["vinga.provider.llm.host"] == "127.0.0.1"


def test_a_session_that_opened_against_nothing_says_nothing() -> None:
    """The degenerate case, which has to be silence rather than an
    empty attribute: a session whose open carried no entries is a
    session this exporter knows nothing about, and inventing a null
    would be a claim the event did not make."""
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events, providers={})
    close_session(events)

    span = named(finished(telemetry, memory), "session")
    assert not [name for name in span.attributes if name.startswith("vinga.provider.")]


def test_a_variant_the_span_map_does_not_name_folds_onto_the_turn() -> None:
    """The fold is a default and not a list, and this is what says so.

    `barge_in` is a variant no row in the span map names and none ever
    will: it opens and closes nothing, so it belongs on the turn it
    interrupted with the fields the catalog gave it. An implementation
    that had enumerated the events it knew would drop every variant the
    catalog grew after it was written, in silence, and the catalog
    grows: `transcription_abandoned` arrived after this module was
    first written and was carried by this same default until M3 gave
    the ASR stage a span of its own (`test_telemetry_spans.py`).
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    start_turn(events)
    clock.tick(0.2)
    barge_in(events)
    clock.tick(0.1)
    finish_reply(events, outcome=ReplyOutcome.BARGED_IN, sentences=0)
    close_session(events)

    spans = finished(telemetry, memory)
    turn = named(spans, "turn")
    assert [event.name for event in turn.events] == ["barge_in"]
    assert turn.events[0].attributes["speech_ms"] == 700
    assert named(spans, "session").events == ()


def test_a_capture_that_precedes_the_open_is_folded_by_session_id() -> None:
    """`capture_started` is a server-channel event and beats
    `session_open` by a handshake, so it is held and folded when the
    span it belongs to exists."""
    clock = Clock()
    telemetry, memory = exporting()
    server = capture_emitter()
    tap = telemetry.server_tap()
    attach_server_tap(tap)
    try:
        capture_started(server)
        events = session_events(clock, telemetry)
        open_session(events)
        close_session(events)
    finally:
        detach_server_tap(tap)

    session = named(finished(telemetry, memory), "session")
    assert [event.name for event in session.events] == ["capture_started"]


def test_a_capture_for_a_session_that_never_opens_is_dropped() -> None:
    """The hold is a buffer, not a record. A session refused after its
    capture started leaves an entry nothing will claim, and the bound is
    what keeps that from being a slow leak."""
    from vinga_server.telemetry import PENDING_CAPTURES

    telemetry, _ = exporting()
    server = capture_emitter()
    tap = telemetry.server_tap()
    attach_server_tap(tap)
    try:
        for _ in range(PENDING_CAPTURES * 2):
            capture_started(server)
    finally:
        detach_server_tap(tap)

    assert len(telemetry._pending) <= PENDING_CAPTURES


def test_one_offset_converts_every_stamp() -> None:
    """The one-offset pin. Every span and every span event in a process
    goes through one monotonic-to-epoch mapping, so a span's converted
    end equals the converted stamp of the event that ended it, exactly
    rather than to within however long a second clock read would take.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    clock.tick(1.0)
    idle_at = go_idle(events)
    clock.tick(1.0)
    closed_at = close_session(events)

    session = named(finished(telemetry, memory), "session")
    offset = session.end_time - int((closed_at + telemetry._offset) * 1e9)

    assert offset == 0
    assert session.events[0].timestamp == int((idle_at + telemetry._offset) * 1e9)


def test_the_resource_is_server_owned_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """No environment pass-through, which is the restriction-at-the-
    source rule applied to the one place a resource could pick up an
    operator's words.

    `Resource.create()` would have merged both of these in.
    """
    monkeypatch.setenv("OTEL_SERVICE_NAME", "a-name-somebody-else-chose")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=leaked")
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)
    open_session(events)
    close_session(events)

    resource = named(finished(telemetry, memory), "session").resource
    assert resource.attributes["service.name"] == SERVICE
    assert set(resource.attributes) == {"service.name", "service.version"}


# --- the trace a closed session can still be named by ------------------
#
# The one read surface the exporter offers anything but the composition,
# and the whole of #67's correlation: a reader that has a session id and
# wants the trace its recording belongs beside. The media API takes the
# OTel trace id and nothing else (no session-id path exists), so what is
# retained is that id, spelled for the wire, and retained PAST the close
# that pops the span, because the capture triplet is only final after
# the session closed.


def a_session(telemetry: Telemetry, session: str) -> str:
    """One whole session, opened and closed, and the id it was given."""
    clock = Clock()
    events = session_events(clock, telemetry, session=session)
    open_session(events)
    clock.tick(1.0)
    close_session(events)
    return session


def test_a_trace_is_readable_after_the_close_that_popped_its_span() -> None:
    """The retention's point. The span map is popped at
    `session_closed`, and the uploader asks its question afterwards: the
    capture's WAV and manifest are only final after that close.

    The id is the exporter's own spelling for the wire, which is what
    the media API takes: thirty-two lowercase hex characters.
    """
    from opentelemetry.trace import format_trace_id

    telemetry, memory = exporting()
    a_session(telemetry, SESSION)

    span = named(finished(telemetry, memory), "session")
    trace = telemetry.trace_of(SESSION)

    assert trace == format_trace_id(span.context.trace_id)
    assert trace is not None
    assert len(trace) == 32 and trace == trace.lower()
    assert int(trace, 16) == span.context.trace_id


def test_a_session_that_is_still_open_is_already_answerable() -> None:
    """Recorded at the OPEN, which is where the id exists and which no
    case that closes first can tell apart from recording at the close.

    Two claims in one drive, because separating them would leave the
    join untested: an unclosed session already answers with a canonical
    id, and that same id is the one the span it belongs to goes out
    under once the session does close.
    """
    from opentelemetry.trace import INVALID_TRACE_ID, format_trace_id

    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry, session=SESSION)

    open_session(events)
    while_open = telemetry.trace_of(SESSION)

    assert while_open is not None, "an open session has no trace to be named by"
    assert len(while_open) == 32 and while_open == while_open.lower()
    assert int(while_open, 16) != INVALID_TRACE_ID

    clock.tick(1.0)
    close_session(events)
    span = named(finished(telemetry, memory), "session")

    assert while_open == format_trace_id(span.context.trace_id)
    assert telemetry.trace_of(SESSION) == while_open


def test_a_session_the_exporter_never_saw_has_no_trace() -> None:
    """Absent rather than invented, which is what makes the uploader's
    `no_trace` failure a real answer: telemetry that never saw a session
    has nothing to name it by."""
    telemetry, _ = exporting()
    a_session(telemetry, SESSION)

    assert telemetry.trace_of("ffffffffffffffffffffffffffffffff") is None


def test_the_retention_keeps_the_last_sessions_and_evicts_the_oldest() -> None:
    """Bounded and oldest-first, the `PENDING_CAPTURES` posture: a map
    that grew with every session a process ever ran would be a slow leak
    in the one object a server holds for its whole life.

    The boundary is asserted on both sides of itself, so a bound that
    kept one too few or one too many fails rather than passing on a
    range.
    """
    from vinga_server.telemetry import RETAINED_TRACES

    telemetry, _ = exporting()
    ids = [f"{index:032x}" for index in range(RETAINED_TRACES + 1)]
    for one in ids:
        a_session(telemetry, one)

    assert telemetry.trace_of(ids[0]) is None, "the oldest survived its eviction"
    assert telemetry.trace_of(ids[1]) is not None
    assert telemetry.trace_of(ids[-1]) is not None
    assert len({telemetry.trace_of(one) for one in ids[1:]}) == RETAINED_TRACES


# --- the outcomes that arrive after the close --------------------------
#
# A recording's trip to the backend runs on a worker of its own once the
# session is over, so its two outcome events reach the exporter with the
# span map already emptied. They used to be dropped there: the server
# fold answered `capture_started` and nothing else, so the vocabulary sat
# in APPROVED and never left the process, and the off-host trace the
# milestone is for had no record of whether a recording made it.


@contextlib.contextmanager
def watching_the_server(telemetry: Telemetry) -> Iterator[None]:
    """The server tap attached for the length of a block.

    The server channels are process-global, so a tap left on would
    deliver into an exporter the next case has finished with.
    """
    tap = telemetry.server_tap()
    attach_server_tap(tap)
    try:
        yield
    finally:
        detach_server_tap(tap)


def test_an_upload_outcome_lands_on_the_trace_its_session_closed_in() -> None:
    """The claim the milestone makes: a reader of the trace can see that
    a recording is there.

    A SPAN rather than a span event, which is a finding rather than a
    preference: the backend this surface exists for ingests no span
    events at all, so an outcome recorded as one would be invisible in
    the one place a reader goes looking for it.
    """
    from opentelemetry.trace import format_trace_id

    telemetry, memory = exporting()
    a_session(telemetry, SESSION)

    with watching_the_server(telemetry):
        capture_uploaded(upload_emitter())

    spans = finished(telemetry, memory)
    written = named(spans, "capture_uploaded")
    session_span = named(spans, "session")
    assert format_trace_id(written.context.trace_id) == telemetry.trace_of(SESSION)
    assert written.parent is not None
    assert written.parent.span_id == session_span.context.span_id


def test_an_upload_outcome_carries_what_its_declaration_declares() -> None:
    """The catalog's fields and no others, plus the session under both
    names so the query a reader makes finds it beside the turns."""
    telemetry, memory = exporting()
    a_session(telemetry, SESSION)

    with watching_the_server(telemetry):
        capture_uploaded(upload_emitter())

    held = dict(named(finished(telemetry, memory), "capture_uploaded").attributes or {})
    assert held["audio_bytes"] == 173464
    assert held["manifest_bytes"] == 1258
    assert held["elapsed_ms"] == 412
    assert held["vinga.session.id"] == SESSION
    assert held["session.id"] == SESSION
    # The sentence's own rendering is not a field, and neither is the
    # event name: it is the span's.
    assert "megabytes" not in held
    assert "event" not in held


def test_a_failed_upload_says_why_on_the_trace() -> None:
    """The other half of the trail, and the half a reader needs most:
    the reason from the closed set, on the trace with no audio in it."""
    telemetry, memory = exporting()
    a_session(telemetry, SESSION)

    with watching_the_server(telemetry):
        capture_upload_failed(upload_emitter())

    held = dict(
        named(finished(telemetry, memory), "capture_upload_failed").attributes or {}
    )
    assert held["reason"] == "unreachable"


def test_an_outcome_for_a_session_this_exporter_never_saw_writes_nothing() -> None:
    """The boot sweep's `abandoned` is about a session a PREVIOUS process
    ran, so there is no trace of this process's to put it on. Nothing is
    invented, and the JSON log is where that one stays."""
    telemetry, memory = exporting()
    a_session(telemetry, SESSION)

    with watching_the_server(telemetry):
        capture_upload_failed(upload_emitter(), session=f"{99:032x}")

    spans = finished(telemetry, memory)
    assert [span for span in spans if span.name == "capture_upload_failed"] == []


# --- the reference that makes an attachment playable -------------------
#
# The second half of `trace_of`'s reason to exist (#67 M3, the round's
# fifth finding). An upload associates a recording with a trace; what
# makes a backend render it is a reference token written back onto that
# trace, and the backend's own ingestion route refuses a trace upsert on
# a current self-hosted deployment and names the OTLP path as the
# supported one. So the reference is a span in that trace, written after
# the session closed and all its spans ended, which is the one thing the
# retention above makes possible.


A_REFERENCE = "@@@langfuseMedia:type=audio/wav|id=probe-media-1|source=bytes@@@"


def test_a_reference_lands_in_the_trace_the_session_was_exported_under() -> None:
    """One span, in that trace, as a child of the session span.

    The trace is the claim: a reference in a trace of its own would
    render a player nobody looking at the session would ever find, which
    is the gap the attachment exists to close rather than a fix for it.
    """
    from opentelemetry.trace import format_trace_id

    telemetry, memory = exporting()
    a_session(telemetry, SESSION)
    trace = telemetry.trace_of(SESSION)
    assert trace is not None

    assert telemetry.reference_media(SESSION, {"capture_audio": A_REFERENCE}) is True

    spans = finished(telemetry, memory)
    referencing = [span for span in spans if span.name == "capture"]
    assert len(referencing) == 1
    written = referencing[0]
    session_span = next(span for span in spans if span.name == "session")
    assert format_trace_id(written.context.trace_id) == trace
    assert written.parent is not None
    assert written.parent.span_id == session_span.context.span_id


def test_a_reference_is_written_under_both_names_a_reader_meets() -> None:
    """Two spellings for one token, because the backend resolves a
    reference wherever it finds one and the two render differently: the
    metadata key is what a reader filters and reads, and the output field
    is what puts a player in the trace view. Both were confirmed live."""
    telemetry, memory = exporting()
    a_session(telemetry, SESSION)

    telemetry.reference_media(
        SESSION, {"capture_audio": A_REFERENCE, "capture_manifest": "m"}
    )

    written = next(
        span for span in finished(telemetry, memory) if span.name == "capture"
    )
    held = dict(written.attributes or {})
    assert held["langfuse.observation.metadata.capture_audio"] == A_REFERENCE
    assert held["langfuse.observation.metadata.capture_manifest"] == "m"
    assert held["langfuse.observation.output"] == f"{A_REFERENCE}\nm"
    # And it groups with its session, so the query a reader makes finds
    # it beside the turns.
    assert held["vinga.session.id"] == SESSION
    assert held["session.id"] == SESSION


def test_a_session_with_no_retained_trace_cannot_be_referenced() -> None:
    """Nothing is invented. A session this exporter never saw, or one
    whose id has aged out, answers False, and what a caller does with a
    False is say so."""
    telemetry, memory = exporting()

    assert telemetry.reference_media("neverseen", {"capture_audio": A_REFERENCE}) is False
    assert [span for span in finished(telemetry, memory) if span.name == "capture"] == []


def test_a_shutting_down_exporter_writes_no_reference() -> None:
    """The real shape of the refusal an uploader has to report: a server
    tearing down stops accepting while the worker is still finishing, and
    a span started then would be one nothing will export."""
    telemetry, memory = exporting()
    a_session(telemetry, SESSION)
    telemetry.stop_accepting()

    assert telemetry.reference_media(SESSION, {"capture_audio": A_REFERENCE}) is False
    assert [span for span in finished(telemetry, memory) if span.name == "capture"] == []


def test_a_trace_is_readable_from_a_thread_that_is_not_the_session_loop() -> None:
    """The reader is the uploader's worker thread and the writer is the
    session loop, which is why the map has a lock of its own rather than
    riding the loop's single-threadedness the way the span map does.

    Driven as contention rather than as a sequence: sessions open while
    a thread of its own reads, and every answer it got has to be either
    nothing yet or exactly the id that session's span carries.
    """
    from opentelemetry.trace import format_trace_id

    telemetry, memory = exporting()
    driven = 40
    ids = [f"{index:032x}" for index in range(driven)]
    stop = threading.Event()
    read: list[tuple[str, str | None]] = []
    failed: list[BaseException] = []

    def reading() -> None:
        try:
            while not stop.is_set():
                for one in ids:
                    read.append((one, telemetry.trace_of(one)))
        except BaseException as raised:  # noqa: BLE001 - reported, not swallowed
            failed.append(raised)

    reader = threading.Thread(target=reading, name="a-reader", daemon=True)
    reader.start()
    try:
        for one in ids:
            a_session(telemetry, one)
    finally:
        stop.set()
        reader.join(10.0)

    assert not reader.is_alive()
    assert failed == []
    spans = {
        span.attributes["vinga.session.id"]: format_trace_id(span.context.trace_id)
        for span in finished(telemetry, memory)
    }
    assert len(spans) == driven
    wrong = [(one, answer) for one, answer in read if answer not in (None, spans[one])]
    assert wrong == []
    assert any(answer is not None for _, answer in read), "the reader read nothing at all"


def test_a_read_waits_for_the_write_it_overlaps() -> None:
    """The synchronization itself, stated as the property a reader
    depends on: while the session loop is recording, a reader on another
    thread waits rather than reading a map mid-move.

    The lock is reached for by name because that is the claim: a read
    that took no lock would answer instantly here and the case would
    fail, which is the only way to falsify a guard the GIL hides.
    """
    telemetry, _ = exporting()
    a_session(telemetry, SESSION)
    answered = threading.Event()
    answer: list[str | None] = []

    def reading() -> None:
        answer.append(telemetry.trace_of(SESSION))
        answered.set()

    with telemetry._retained_lock:
        reader = threading.Thread(target=reading, name="a-reader", daemon=True)
        reader.start()
        assert not answered.wait(0.2), "a read answered while the map was held"

    assert answered.wait(10.0), "a read never answered once the map was free"
    reader.join(10.0)
    assert answer == [telemetry.trace_of(SESSION)]


def test_an_open_at_the_bound_waits_for_the_map_it_has_to_move() -> None:
    """The other half of the same lock, and the half the reader's case
    cannot reach: the WRITE, at the one moment it is compound.

    A record under the bound is a single assignment and proves nothing
    about atomicity, so the map is filled to exactly `RETAINED_TRACES`
    first: the next open has to insert AND evict, which is the pair the
    lock is held across. Held from here, the open itself must not get
    through, and when it does the map has moved exactly once: the
    newcomer in, the oldest out, and everything between them untouched.

    A `_retain` that took no lock would finish the open while this
    thread still holds it, which is what makes this the writer-side
    falsification the reader's case is missing.
    """
    from vinga_server.telemetry import RETAINED_TRACES

    telemetry, _ = exporting()
    ids = [f"{index:032x}" for index in range(RETAINED_TRACES)]
    for one in ids:
        a_session(telemetry, one)
    newcomer = f"{RETAINED_TRACES:032x}"
    opened = threading.Event()
    failed: list[BaseException] = []

    def opening() -> None:
        try:
            clock = Clock()
            events = session_events(clock, telemetry, session=newcomer)
            open_session(events)
            clock.tick(1.0)
            close_session(events)
        except BaseException as raised:  # noqa: BLE001 - reported, not swallowed
            failed.append(raised)
        finally:
            opened.set()

    with telemetry._retained_lock:
        writer = threading.Thread(target=opening, name="a-session", daemon=True)
        writer.start()
        assert not opened.wait(0.2), "a session recorded its trace while the map was held"
        # And nothing of it landed, which is the other half of "the two
        # operations are one": the map is exactly as it was.
        assert telemetry._retained.get(newcomer) is None
        assert telemetry._retained.get(ids[0]) is not None

    assert opened.wait(10.0), "the open never finished once the map was free"
    writer.join(10.0)
    assert not writer.is_alive()
    assert failed == []
    assert telemetry.trace_of(newcomer) is not None, "the newcomer was not recorded"
    assert telemetry.trace_of(ids[0]) is None, "the oldest was not the one evicted"
    assert [one for one in ids[1:] if telemetry.trace_of(one) is None] == []


# --- the board's name, on every span -----------------------------------
#
# "Every span" is an enumeration and not a table entry, because spans
# are built in more places than the attribute tables reach: the session
# span reads its own table, the turn and the stage spans read the
# retained identity, and the three that run AFTER the close build their
# attributes by hand and hold no attributes at all to inherit. So the
# name joins two records, the live session's identity and the retained
# `_Exported`, and the enumeration is asserted constructor by
# constructor here rather than trusted.
#
# Read from the retained record and never from a configuration, which
# is the second reason as well as the first: a board renamed after a
# session ran must not change what that session's spans say.

BOARD = "kitchen speaker"


def a_named_session(telemetry: Telemetry, session: str = SESSION) -> None:
    """One whole session on a board somebody named, opened and closed,
    which is what puts a name in the retention."""
    clock = Clock()
    events = session_events(clock, telemetry, session=session)
    open_session(events, device_name=BOARD)
    clock.tick(1.0)
    close_session(events)


def test_the_session_span_carries_the_board_s_name() -> None:
    """The first constructor in the enumeration, and the only one that
    reads the name off the payload: `session_open` carries the bounded
    copy, and the session span's own table exports it."""
    telemetry, memory = exporting()
    a_named_session(telemetry)

    assert named(finished(telemetry, memory), "session").attributes[
        "vinga.device.name"
    ] == BOARD


def test_a_turn_and_its_stages_carry_the_board_s_name() -> None:
    """The constructors that read the retained identity. OTel inherits
    nothing, so a stage span with only its stage's fields is a span
    nobody looking for a board can find."""
    telemetry, memory = exporting()
    clock = Clock()
    events = session_events(clock, telemetry)
    open_session(events, device_name=BOARD)
    clock.tick(1.0)
    start_turn(events)
    clock.tick(0.3)
    hear(events)
    clock.tick(0.8)
    round_done(events, duration_ms=800)
    clock.tick(0.4)
    synthesize(events, stream_ms=400)
    start_speaking(events)
    clock.tick(0.5)
    finish_reply(events, sentences=1)
    finish_speaking(events, frames=12, at=clock())
    close_session(events)

    spans = finished(telemetry, memory)
    assert {span.name for span in spans} == {
        "session",
        "turn",
        "asr",
        "llm",
        "tts_stream",
        "playback",
    }
    for span in spans:
        assert span.attributes["vinga.device.name"] == BOARD, span.name


def test_a_media_reference_carries_the_board_s_name() -> None:
    """The first of the three post-close constructors, which builds its
    attributes by hand and therefore had nothing to inherit."""
    telemetry, memory = exporting()
    a_named_session(telemetry)

    telemetry.reference_media(SESSION, {"capture_audio": A_REFERENCE})

    written = named(finished(telemetry, memory), "capture")
    assert written.attributes["vinga.device.name"] == BOARD


def test_an_outcome_after_the_close_carries_the_board_s_name() -> None:
    """The second, whose attributes come off a payload that carries no
    device at all: an upload outcome names its session and nothing
    else, so the name can only come from the retained record."""
    telemetry, memory = exporting()
    a_named_session(telemetry)

    with watching_the_server(telemetry):
        capture_uploaded(upload_emitter())

    written = named(finished(telemetry, memory), "capture_uploaded")
    assert written.attributes["vinga.device.name"] == BOARD


def test_a_transcript_span_carries_the_board_s_name() -> None:
    """The third, which builds its attributes from a projection of the
    conversation store and reads the name from the context the job was
    admitted on."""
    deliveries = Deliveries()
    telemetry, _ = exporting(transcripts=deliveries)
    a_named_session(telemetry)
    context = telemetry.retained_context(SESSION)
    assert context is not None

    telemetry.export_transcript(
        SESSION,
        context,
        [TranscriptTurn(index=1, id=7, t_ms=120, agent=AGENT, heard="a", reply="b")],
    )

    written = deliveries.spans()
    assert len(written) == 1
    assert written[0].attributes["vinga.device.name"] == BOARD


def test_a_board_nobody_named_says_nothing_rather_than_null() -> None:
    """Which is the state every deployment's boards are in until an
    operator runs `device rename`, and the difference between "this
    board has no name" and "this span forgot to say".

    Every constructor in the enumeration in one case, because what is
    being pinned is the absence rule rather than one span's behavior.
    """
    deliveries = Deliveries()
    telemetry, memory = exporting(transcripts=deliveries)
    clock = Clock()
    events = session_events(clock, telemetry)
    open_session(events)
    clock.tick(1.0)
    start_turn(events)
    clock.tick(0.3)
    hear(events)
    clock.tick(0.5)
    finish_reply(events, sentences=1)
    close_session(events)
    context = telemetry.retained_context(SESSION)
    assert context is not None
    telemetry.reference_media(SESSION, {"capture_audio": A_REFERENCE})
    with watching_the_server(telemetry):
        capture_uploaded(upload_emitter())
    telemetry.export_transcript(
        SESSION,
        context,
        [TranscriptTurn(index=1, id=7, t_ms=120, agent=AGENT, heard="a", reply="b")],
    )

    spans = [*finished(telemetry, memory), *deliveries.spans()]
    assert {span.name for span in spans} == {
        "session",
        "turn",
        "asr",
        "capture",
        "capture_uploaded",
        "transcript",
    }
    for span in spans:
        assert "vinga.device.name" not in span.attributes, span.name


# --- no leak -----------------------------------------------------------

# A value shaped like a collector credential, planted in every place one
# genuinely arrives, and hunted everywhere anything is retained.
SENTINEL = "sk-live-0PENTELEMETRY-SENTINEL"


@pytest.fixture
def planted(monkeypatch: pytest.MonkeyPatch) -> str:
    """The sentinel in all four places the exporter's real inputs come
    from: the headers variable, which is where a collector's credential
    is written by design; the endpoint's userinfo, which is a URL an
    operator may have pasted a password into; the service name, which is
    the resource attribute the SDK reads from the environment; and a
    payload field, which is the catalog's own surface."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", f"authorization=Bearer {SENTINEL}")
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", f"http://user:{SENTINEL}@127.0.0.1:1/v1/traces"
    )
    monkeypatch.setenv("OTEL_SERVICE_NAME", SENTINEL)
    return SENTINEL


def test_the_exporters_inputs_never_reach_a_span(
    planted: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The sentinel battery, over what a backend and an operator keep.

    The endpoint and the headers are transport configuration: they reach
    the exporter's constructor, which reads them itself, and this module
    never binds either. So none of them can be in a span's attributes,
    in the resource, in a span event, or in a line of either log format.
    """
    caplog.set_level(logging.DEBUG)
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)
    open_session(events)
    go_idle(events)
    close_session(events)

    spans = finished(telemetry, memory)
    rendered = "\n".join(
        f"{span.name}{span.attributes}{span.resource.attributes}"
        f"{[(event.name, event.attributes) for event in span.events]}"
        for span in spans
    )

    assert spans, "nothing was exported, so this hunt reads nothing"
    assert planted not in rendered
    assert planted not in both_formats(caplog)


async def test_a_failed_export_leaks_nothing(
    planted: str, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same hunt where the leak would actually happen: an export
    against an endpoint nothing answers, whose failure the SDK logs with
    the URL it could not reach in it.

    Which is why the SDK's namespace is quieted before the exporter is
    constructed. Hunted in both log formats, in stderr, and in the
    exception chain of anything the shutdown raised, because a traceback
    is the other way a library's message reaches a terminal.
    """
    caplog.set_level(logging.DEBUG)
    clock = Clock()
    telemetry = build_telemetry(
        TelemetryConfig(enabled=True), batch_size=1, schedule_delay_ms=1
    )
    assert telemetry is not None
    events = session_events(clock, telemetry)
    open_session(events)
    close_session(events)
    telemetry.flush()
    await telemetry.shutdown()

    captured = capsys.readouterr()
    assert planted not in every_format(caplog)
    assert planted not in captured.err
    assert planted not in captured.out


def test_a_payload_field_the_catalog_never_declared_is_not_exported(
    planted: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The fourth sentinel the plan asked for, and the one the first
    round of this milestone did not actually plant.

    The fold used to copy a payload wholesale, taking every key but the
    three identities, so what reached a backend was whatever the dict
    happened to hold. It iterates the approved table now, so a key the
    catalog does not declare for this event cannot be exported whatever
    put it there.

    Planted through the tap's own interface rather than through the
    emitter, deliberately: the emitter builds payloads from the catalog
    and cannot produce this, which is exactly why the question is what
    the CONSUMER does when handed one. `EventTap.emit(Emission)` is the
    contract this module publishes, and this is that contract being
    exercised with a payload it did not build.
    """
    caplog.set_level(logging.DEBUG)
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)
    tap = telemetry.session_tap()

    open_session(events)
    start_turn(events)
    tap.emit(
        Emission(
            payload={
                "event": "session_idle",
                "session": SESSION,
                "idle_s": 120.0,
                # Nothing declares this, and it holds what an exporter
                # must never put on a span.
                "authorization": planted,
            },
            at=clock.tick(0.1),
            level=logging.INFO,
            message="session %s idle",
            args=(SESSION,),
        )
    )
    finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    turn = named(spans, "turn")
    assert [event.name for event in turn.events] == ["session_idle"]
    # The declared field arrived, so the fold did run and this is not
    # passing by exporting nothing at all.
    assert turn.events[0].attributes["idle_s"] == pytest.approx(120.0)
    assert "authorization" not in turn.events[0].attributes
    assert planted not in str(dict(turn.events[0].attributes))
    assert planted not in every_format(caplog)


def test_a_mapping_field_survives_as_deterministic_json() -> None:
    """The two payload fields OTel could not take, and what they become.

    An OTel attribute is a scalar or a sequence of scalars, so a mapping
    handed to `add_event` was discarded by the SDK with a warning this
    module had already silenced: `prompt_assembled` arrived on a span
    with no `sources` at all, and `frames_dropped` arrived with nothing
    but its second. Both are bounded, server-owned mappings of names to
    numbers, so one JSON string under the field's own name is an honest
    representation rather than a place for prose to hide.

    Asserted exactly, string for string: sorted keys and no spaces, so
    the same mapping is the same attribute in every process and a
    backend can group by it.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    clock.tick(0.1)
    assemble_prompt(events, {"persona": 210, "fragment:house-rules": 84})
    clock.tick(0.1)
    drop_frames(events, {"not_listening": 3, "barge_in_off": 1}, second=3)
    close_session(events)

    session = named(finished(telemetry, memory), "session")
    assembled, dropped = session.events

    assert assembled.name == "prompt_assembled"
    assert assembled.attributes["sources"] == (
        '{"fragment:house-rules":84,"persona":210}'
    )
    assert assembled.attributes["characters"] == 294
    assert dropped.name == "frames_dropped"
    assert dropped.attributes["reasons"] == '{"barge_in_off":1,"not_listening":3}'
    assert dropped.attributes["second"] == 3


def test_the_json_of_a_mapping_does_not_depend_on_insertion_order() -> None:
    """Deterministic means the same string, not merely a string.

    A mapping's iteration order is whatever built it, and two servers
    that counted the same drops in a different order would otherwise
    export two attributes a backend cannot group.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    drop_frames(events, {"not_listening": 3, "barge_in_off": 1})
    clock.tick(0.1)
    drop_frames(events, {"barge_in_off": 1, "not_listening": 3})
    close_session(events)

    session = named(finished(telemetry, memory), "session")
    first, second = (event.attributes["reasons"] for event in session.events)

    assert first == second


def test_a_hostile_providers_payload_puts_nothing_on_a_span(
    planted: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The other half of the approved-table claim, for the one field
    that is not an attribute.

    `providers` is retained as context and flattened into attribute
    NAMES, which is the one place a payload gets to choose part of the
    key rather than only the value. A fold that walked the mapping
    itself would take an agent nobody named, a stage outside the
    pipeline's own set, and a credential in `name`, and put them on a
    span as `vinga.provider.<whatever they sent>.name`. That defeats
    both promises this context makes: bounded cardinality, and
    sanitized by construction.

    So the value goes through `ProviderEntries` before it is retained,
    and this drives a payload the emitter could not have built: an
    arbitrary stage, a fifth key, and the sentinel in three places.
    Nothing of it reaches a span, and the session span is asserted to
    have opened at all, so this is not passing by exporting nothing.
    """
    caplog.set_level(logging.DEBUG)
    clock = Clock()
    telemetry, memory = exporting()
    tap = telemetry.session_tap()

    tap.emit(
        Emission(
            payload={
                "event": "session_open",
                "session": SESSION,
                "agent": AGENT,
                "conversation": CONVERSATION,
                "protocol": 1,
                "providers": {
                    AGENT: {
                        "../../etc/passwd": {"name": planted, "type": "anthropic"},
                        "llm": {
                            "name": "claude",
                            "type": "anthropic",
                            "authorization": planted,
                        },
                    }
                },
            },
            at=clock(),
            level=logging.INFO,
            message="session %s open",
            args=(SESSION,),
        )
    )
    clock.tick(1.0)
    tap.emit(
        Emission(
            payload={"event": "session_closed", "session": SESSION, "reason": "client"},
            at=clock(),
            level=logging.INFO,
            message="session %s closed",
            args=(SESSION,),
        )
    )

    span = named(finished(telemetry, memory), "session")
    rendered = str(dict(span.attributes))

    assert span.attributes["vinga.session.id"] == SESSION
    assert not [name for name in span.attributes if name.startswith("vinga.provider.")]
    assert "passwd" not in rendered
    assert planted not in rendered
    assert planted not in every_format(caplog)


def test_every_payload_kind_has_a_shape_decided_for_it() -> None:
    """The closed set at the decision site.

    What a payload field becomes on a span is decided by its catalog
    `Kind`, and a kind with no row would fall to whatever the lookup
    defaulted to, which is the permissive rule this replaced. So the
    table is held to the enumeration exactly, in both directions: a new
    kind fails here until somebody decides what it exports as, and a row
    for a kind that no longer exists fails here too.
    """
    from vinga_server.events.values import Kind

    assert set(SHAPES) == set(Kind)


def test_the_approved_table_covers_the_whole_catalog() -> None:
    """And the table derived from it, held to the catalog the same way,
    so an event added without a shape is a failure here rather than an
    event that exports nothing."""
    from vinga_server.events.catalog import catalog

    assert set(APPROVED) == set(catalog())
    assert APPROVED["session_idle"]["idle_s"] is not None
    assert APPROVED.get("an_event_nobody_declared") is None


# --- what a payload nobody declared cannot do -------------------------
#
# Everything below drives the FOLD with a payload the catalog would not
# have built, which is the only way these claims are worth making: a
# table read in a test proves what the table says, and what reaches a
# backend is decided by the code that reads it.


def test_an_undeclared_event_name_reaches_no_span(planted: str) -> None:
    """The name is exported content too.

    A span event is NAMED after its event, so a fold that dispatched any
    string through its default put whatever that string held onto a
    span, under no attribute table at all. The catalog decides which
    names exist, and a payload carrying another one is a payload this
    repository did not build.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)
    open_session(events)
    clock.tick(1.0)
    _fold(telemetry, {"event": f"an_event_named_{planted}", "session": SESSION})
    close_session(events)

    session = named(finished(telemetry, memory), "session")
    assert session.events == ()
    assert planted not in str(list(session.attributes.items()))


def test_a_declared_scalar_the_catalog_would_refuse_is_not_exported(
    planted: str,
) -> None:
    """The half a check on Python builtins cannot make.

    `session_idle.idle_s` is declared `Real`, and a credential-shaped
    string in that field is a `str`: every builtin check passes it, and
    what would reach the backend is the credential under the field's own
    honest-looking name. The value type is asked instead, by
    constructing it, which is where the constraint lives.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)
    open_session(events)
    clock.tick(1.0)
    _fold(
        telemetry,
        {
            "event": "session_idle",
            "session": SESSION,
            "idle_s": planted,
            "duration_s": 200.0,
        },
    )
    close_session(events)

    session = named(finished(telemetry, memory), "session")
    assert [event.name for event in session.events] == ["session_idle"]
    carried = session.events[0].attributes
    assert "idle_s" not in carried
    # The neighbouring field, which IS what it says it is, still goes:
    # one bad value is not a reason to drop the record.
    assert carried["duration_s"] == pytest.approx(200.0)
    assert planted not in str(list(carried.items()))


def test_a_declared_mapping_the_catalog_would_refuse_is_not_exported(
    planted: str,
) -> None:
    """And the same for the shape with the most room in it.

    `frames_dropped.reasons` is declared `DroppedFrames`, whose keys are
    the edge's own guards and whose values are frame counts. A mapping
    of somebody else's keys to somebody else's strings is still a
    mapping, and JSON would have carried it whole.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)
    open_session(events)
    clock.tick(1.0)
    _fold(
        telemetry,
        {
            "event": "frames_dropped",
            "session": SESSION,
            "second": 3,
            "reasons": {planted: planted},
        },
    )
    close_session(events)

    session = named(finished(telemetry, memory), "session")
    assert [event.name for event in session.events] == ["frames_dropped"]
    carried = session.events[0].attributes
    assert "reasons" not in carried
    assert carried["second"] == 3
    assert planted not in str(list(carried.items()))


def _fold(telemetry: object, payload: dict[str, object]) -> None:
    """One payload straight at the session tap, which is what a tap
    contract cannot stop a caller doing.

    Built by hand and not by the catalog, deliberately: every emission a
    real `SessionEvents` makes is a typed variant, so the payloads these
    cases are about cannot be produced through it. What they stand for
    is anything that reaches this consumer without having been built by
    the catalog, and the tap is where that would arrive.
    """
    from vinga_server.events import Emission

    tap = telemetry.session_tap()  # type: ignore[attr-defined]
    tap.emit(
        Emission(payload=dict(payload), at=time.monotonic(), level=20, message="", args=())
    )


def test_the_sdk_namespace_is_quieted_and_restored() -> None:
    """Installed before the exporter is constructed and put back when it
    shuts down, which is what makes a server that stopped exporting a
    server whose logging is its own again."""
    namespace = logging.getLogger(OTEL_NAMESPACE)
    was_level, was_propagate = namespace.level, namespace.propagate
    assert _QUIETING.held() == 0, "something else is still holding the namespace"

    telemetry, _ = exporting()
    assert namespace.level > logging.CRITICAL
    assert namespace.propagate is False

    telemetry.release()
    assert _QUIETING.held() == 0
    assert namespace.level == was_level
    assert namespace.propagate == was_propagate


def test_two_overlapping_exporters_share_one_lease_on_the_silence() -> None:
    """The exact sequence a wedged redeploy produces, which per-exporter
    snapshots got wrong in both directions.

    A wedged exporter's release outlives the bounded wait, so a server
    that builds the next one while the last is still finishing has two
    live claims on one process-wide logger. Snapshotting per exporter
    meant B recorded SILENCE as the state to restore, A's late release
    then un-silenced the SDK while B was still exporting (so B's next
    failure logged its credentialed endpoint), and B's own release
    finally restored A's quiet snapshot and left the namespace silent
    for the rest of the process with nothing holding it.

    Counted and locked instead: the snapshot is taken once and put back
    once, after the last release.
    """
    namespace = logging.getLogger(OTEL_NAMESPACE)
    was_level, was_propagate = namespace.level, namespace.propagate
    assert _QUIETING.held() == 0

    wedged, _ = exporting()
    live, _ = exporting()
    assert _QUIETING.held() == 2

    # A's abandoned release finishes while B is still exporting. The
    # namespace stays quiet, which is what stops B's next failure
    # reaching a handler.
    wedged.release()
    assert _QUIETING.held() == 1
    assert namespace.level > logging.CRITICAL
    assert namespace.propagate is False

    # And only the last release puts back what the PROCESS had, rather
    # than what the second exporter found.
    live.release()
    assert _QUIETING.held() == 0
    assert namespace.level == was_level
    assert namespace.propagate == was_propagate


def test_a_lease_given_back_twice_is_counted_once() -> None:
    """The build's failure path and the release worker both call it
    without either knowing whether the other did, so a second release
    must not drop somebody else's claim."""
    namespace = logging.getLogger(OTEL_NAMESPACE)
    assert _QUIETING.held() == 0

    first, _ = exporting()
    second, _ = exporting()
    first.release()
    first.release()

    assert _QUIETING.held() == 1, "a repeated release took another exporter's claim"
    assert namespace.propagate is False

    second.release()
    assert _QUIETING.held() == 0


# --- two clocks --------------------------------------------------------

# How far apart the two clocks can actually be. uvloop's loop clock is
# libuv's and shares no origin with `time.monotonic`; on one developer
# machine they read thirty-six hours apart, which is the number below,
# rounded to something a failure message can be read against.
A_UVLOOP_SHAPED_GAP_S = 131_249.0

# How close a span's epoch has to land to the instant it was emitted.
# Generous: what this is separating is "now" from "a day and a half from
# now", not one millisecond from the next.
NEAR_ENOUGH_S = 60.0


def test_a_session_clock_of_its_own_still_lands_the_span_on_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two-clock pin, and the bug it was written for.

    A session event is stamped with the SESSION LOOP's clock, which
    under uvloop is libuv's and shares no origin with `time.monotonic`.
    An exporter that converted session stamps through a
    `time.monotonic` offset therefore put every span tens of hours from
    when it happened: a collector accepts them, stores them, and no
    search window a person types ever contains them, which is exactly
    what the Jaeger walkthrough found and what no structural assertion
    could have.

    So the offset is read from the session's own clock, at the first
    session emission, which is a reading taken on the loop that stamps
    them.
    """
    clock = Clock()
    clock.at += A_UVLOOP_SHAPED_GAP_S
    monkeypatch.setattr("vinga_server.telemetry.session_clock", clock)
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    close_session(events)

    span = named(finished(telemetry, memory), "session")
    assert abs(span.end_time / 1e9 - time.time()) < NEAR_ENOUGH_S


def test_a_server_event_keeps_the_server_clock_it_was_stamped_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half: `capture_started` is a server event, stamped with
    `time.monotonic` because server events fire where no loop is
    running. It reaches the session's timeline through the offset for
    ITS clock, so the two land beside each other rather than a loop's
    origin apart."""
    clock = Clock()
    clock.at += A_UVLOOP_SHAPED_GAP_S
    monkeypatch.setattr("vinga_server.telemetry.session_clock", clock)
    telemetry, memory = exporting()
    server = capture_emitter()
    tap = telemetry.server_tap()
    attach_server_tap(tap)
    try:
        capture_started(server)
        events = session_events(clock, telemetry)
        open_session(events)
        close_session(events)
    finally:
        detach_server_tap(tap)

    session = named(finished(telemetry, memory), "session")
    held = session.events[0]
    assert held.name == "capture_started"
    assert abs(held.timestamp / 1e9 - time.time()) < NEAR_ENOUGH_S
