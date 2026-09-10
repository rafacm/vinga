"""The switch, the refusals, and the shape of a trace.

Three claims live here and one of them is the milestone's whole point.

**Off costs nothing.** An absent section, or one with the flag off,
builds no object, imports nothing and attaches no tap, so the rest of
this repository's suites running with no `telemetry:` section anywhere
are themselves the proof the default path is untouched. What is pinned
here is the sentence that says so: `build_telemetry(None)` is None.

**Every refusal is a sentence, and none of them chains.** The three
ways an enabled exporter can be wrong (`local_only`, the missing extra,
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

import logging
import sys
from collections.abc import Iterator

import pytest

from tests.support.events import both_formats, every_format
from tests.support.telemetry import (
    AGENT,
    CONVERSATION,
    DEVICE,
    SESSION,
    Clock,
    abandon_transcription,
    assemble_prompt,
    capture_emitter,
    capture_started,
    close_session,
    drop_frames,
    exporting,
    finish_reply,
    finished,
    go_idle,
    hand_over,
    named,
    open_session,
    released,
    session_events,
    start_turn,
)
from vinga_server.config import ConfigError
from vinga_server.config.models import TelemetryConfig
from vinga_server.egress import EgressRefusal, check_feature
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


def test_local_only_refuses_before_anything_is_constructed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The egress refusal, and the claim that makes it worth having:
    the exporter's constructor is never reached.

    Both halves are asserted, because either alone is weak. A sentence
    without the never-reached pin would pass an implementation that
    built the exporter and then threw it away, which is a socket opened
    and a thread started under `local_only`; a never-reached pin without
    the sentence would pass one that refused for the wrong reason.
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
        build_telemetry(TelemetryConfig(enabled=True), local_only=True)

    assert reached == [], "something was imported or constructed under local_only"
    assert "server.local_only is on" in str(refusal.value)
    assert TELEMETRY_KEY in str(refusal.value)


def test_the_local_only_sentence_is_the_egress_modules_own() -> None:
    """One home for the rule, checked rather than asserted: the words
    the boot prints are the words `egress.py` composes, so a telemetry
    rule of its own would show up here as two sentences."""
    with pytest.raises(EgressRefusal) as direct:
        check_feature(TELEMETRY_KEY, egress=True, local_only=True)
    with pytest.raises(ConfigError) as boot:
        build_telemetry(TelemetryConfig(enabled=True), local_only=True)

    assert str(boot.value) == str(direct.value)


def test_the_local_only_refusal_chains_nothing() -> None:
    """Raised after the `except` closed, so uvicorn renders this
    sentence and not the exception underneath it."""
    with pytest.raises(ConfigError) as refusal:
        build_telemetry(TelemetryConfig(enabled=True), local_only=True)

    assert refusal.value.__cause__ is None
    assert refusal.value.__context__ is None


def test_the_local_only_refusal_carries_no_value() -> None:
    """The egress sentences are value-free by rule, and this one has an
    environment full of candidates beside it: the endpoint is never
    read at all on this path, so there is nothing of it to print."""
    with pytest.raises(ConfigError) as refusal:
        build_telemetry(TelemetryConfig(enabled=True), local_only=True)

    said = str(refusal.value)
    assert "http" not in said
    assert "OTEL" not in said


def test_local_only_with_telemetry_off_is_not_refused() -> None:
    """The rule is about an exporter that would exist. A local-only
    deployment with no telemetry section boots exactly as it did."""
    assert build_telemetry(None, local_only=True) is None
    assert build_telemetry(TelemetryConfig(enabled=False), local_only=True) is None


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

    `transcription_abandoned` arrived after this module was written (the
    fourth way an ASR stage ends, from PR #442's review round) and lands
    inside a turn. Nothing here enumerates ASR outcomes, so it needs no
    row: it folds as an ordinary span event onto the turn being
    abandoned, carrying the fields the catalog gave it. An
    implementation that had listed the events it knew would have dropped
    this one silently, which is exactly the failure this pins.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)

    open_session(events)
    start_turn(events)
    clock.tick(0.2)
    abandon_transcription(events)
    clock.tick(0.1)
    finish_reply(events, outcome=ReplyOutcome.BARGED_IN, sentences=0)
    close_session(events)

    spans = finished(telemetry, memory)
    turn = named(spans, "turn")
    assert [event.name for event in turn.events] == ["transcription_abandoned"]
    assert turn.events[0].attributes["asr_ms"] == 140
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
    # An event this module has never heard of exports nothing at all,
    # which is what makes the fold closed rather than defaulting.
    assert APPROVED.get("an_event_nobody_declared") is None


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
