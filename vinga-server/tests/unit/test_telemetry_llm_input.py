"""Canonical content is folded onto the actual LLM or tool span."""

from collections.abc import Iterator

import pytest

from tests.support.telemetry import (
    SESSION,
    Clock,
    call_tool,
    close_session,
    exporting,
    finish_reply,
    finished,
    named,
    open_session,
    provider_failed,
    released,
    round_done,
    session_events,
    start_turn,
)
from vinga_server.telemetry import (
    _QUIETING,
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_SYSTEM_INSTRUCTIONS,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_RESULT,
    LLM_TOOL_CHOICE,
    LLM_TOOLS,
    OBSERVATION_INPUT,
    OBSERVATION_OUTPUT,
)


@pytest.fixture(autouse=True)
def _release() -> Iterator[None]:
    yield
    released()
    assert _QUIETING.held() == 0


def _open(invocation: str) -> tuple[object, object, object]:
    telemetry, memory = exporting()
    clock = Clock()
    emitted = session_events(clock, telemetry)
    open_session(emitted)
    start_turn(emitted, utterance="a" * 32)
    attributes = {
        GEN_AI_SYSTEM_INSTRUCTIONS: '[{"content":"system","type":"text"}]',
        GEN_AI_INPUT_MESSAGES: '[{"parts":[],"role":"user"}]',
        GEN_AI_OUTPUT_MESSAGES: '[{"parts":[],"role":"assistant"}]',
        LLM_TOOLS: "[]",
        LLM_TOOL_CHOICE: "none",
    }
    assert telemetry.stage_llm_content(SESSION, invocation, attributes)
    return telemetry, memory, emitted


def test_content_enriches_the_actual_generation_span() -> None:
    invocation = "1" * 32
    telemetry, memory, emitted = _open(invocation)
    round_done(emitted, invocation=invocation)
    finish_reply(emitted)

    spans = finished(telemetry, memory)
    llm = named(spans, "llm")
    assert llm.attributes[GEN_AI_SYSTEM_INSTRUCTIONS]
    assert llm.attributes[GEN_AI_INPUT_MESSAGES]
    assert llm.attributes[GEN_AI_OUTPUT_MESSAGES]
    # The fold adds no backend alias of its own: Langfuse maps the
    # conventions above, and an input alias would outrank that mapping.
    assert OBSERVATION_INPUT not in llm.attributes
    assert OBSERVATION_OUTPUT not in llm.attributes
    assert not any(span.name == "llm_input" for span in spans)


def test_failed_generation_consumes_its_partial_pair() -> None:
    invocation = "2" * 32
    telemetry, memory, emitted = _open(invocation)
    provider_failed(emitted, stage="llm", invocation=invocation)
    finish_reply(emitted)

    llm = named(finished(telemetry, memory), "llm")
    assert llm.status.status_code.name == "ERROR"
    assert llm.attributes[GEN_AI_INPUT_MESSAGES]
    assert llm.attributes[GEN_AI_OUTPUT_MESSAGES]


def test_missing_content_changes_only_the_content() -> None:
    telemetry, memory = exporting()
    clock = Clock()
    emitted = session_events(clock, telemetry)
    open_session(emitted)
    start_turn(emitted)
    round_done(emitted, invocation="3" * 32)
    finish_reply(emitted)

    llm = named(finished(telemetry, memory), "llm")
    assert GEN_AI_INPUT_MESSAGES not in llm.attributes
    assert GEN_AI_OUTPUT_MESSAGES not in llm.attributes
    assert OBSERVATION_INPUT not in llm.attributes


def test_invocation_is_the_only_join_key() -> None:
    telemetry, memory = exporting()
    clock = Clock()
    emitted = session_events(clock, telemetry)
    open_session(emitted)
    start_turn(emitted)
    telemetry.stage_llm_content(
        SESSION,
        "kept",
        {
            GEN_AI_INPUT_MESSAGES: "right",
            GEN_AI_OUTPUT_MESSAGES: "answer",
        },
    )
    telemetry.stage_llm_content(
        SESSION,
        "dropped",
        {
            GEN_AI_INPUT_MESSAGES: "wrong",
            GEN_AI_OUTPUT_MESSAGES: "wrong",
        },
    )
    telemetry.discard_llm_content("dropped")
    round_done(emitted, invocation="kept", round_=1)
    finish_reply(emitted)

    llm = named(finished(telemetry, memory), "llm")
    assert llm.attributes[GEN_AI_INPUT_MESSAGES] == "right"


def test_content_is_refused_without_a_live_session_trace() -> None:
    invocation = "4" * 32
    attributes = {GEN_AI_INPUT_MESSAGES: "must not survive"}
    telemetry, memory = exporting()

    assert not telemetry.stage_llm_content(SESSION, invocation, attributes)

    clock = Clock()
    emitted = session_events(clock, telemetry)
    open_session(emitted)
    start_turn(emitted)
    round_done(emitted, invocation=invocation)
    finish_reply(emitted)
    llm = named(finished(telemetry, memory), "llm")
    assert GEN_AI_INPUT_MESSAGES not in llm.attributes

    close_session(emitted)
    assert not telemetry.stage_llm_content(SESSION, "closed", attributes)


@pytest.mark.parametrize("failed", [False, True], ids=["success", "failure"])
def test_a_late_generation_event_discards_its_orphaned_snapshot(
    failed: bool,
) -> None:
    invocation = "5" * 32
    telemetry, memory, emitted = _open(invocation)
    close_session(emitted)

    if failed:
        provider_failed(emitted, stage="llm", invocation=invocation)
    else:
        round_done(emitted, invocation=invocation)

    open_session(emitted)
    start_turn(emitted)
    round_done(emitted, invocation=invocation)
    finish_reply(emitted)
    llm = named(finished(telemetry, memory), "llm")
    assert GEN_AI_INPUT_MESSAGES not in llm.attributes


@pytest.mark.parametrize("failed", [False, True], ids=["llm_round", "provider_failed"])
def test_a_settle_answers_true_only_for_a_pair_its_fold_attached(failed: bool) -> None:
    """The fold that wrote the pair onto its span is what the settle
    reports, once: a second settle of the same invocation finds nothing,
    because the first released it (#588)."""
    invocation = "a" * 32
    telemetry, _, emitted = _open(invocation)

    if failed:
        provider_failed(emitted, stage="llm", invocation=invocation)
    else:
        round_done(emitted, invocation=invocation)

    assert telemetry.settle_llm_content(invocation)
    assert not telemetry.settle_llm_content(invocation)


def test_a_settle_releases_a_pair_no_event_consumed() -> None:
    """Staged, and the round's event never reached the fold: the settle
    answers False and discards the slot there and then, so the same
    invocation on a later span finds nothing."""
    invocation = "b" * 32
    telemetry, memory, emitted = _open(invocation)

    assert not telemetry.settle_llm_content(invocation)

    round_done(emitted, invocation=invocation)
    finish_reply(emitted)
    llm = named(finished(telemetry, memory), "llm")
    assert GEN_AI_INPUT_MESSAGES not in llm.attributes
    assert not telemetry.settle_llm_content(invocation)


@pytest.mark.parametrize("failed", [False, True], ids=["llm_round", "provider_failed"])
def test_a_pair_folded_with_no_trace_settles_as_not_attached(failed: bool) -> None:
    """The fold took the slot after the trace closed and wrote it
    nowhere, so the settle may not count it."""
    invocation = "c" * 32
    telemetry, _, emitted = _open(invocation)
    close_session(emitted)

    if failed:
        provider_failed(emitted, stage="llm", invocation=invocation)
    else:
        round_done(emitted, invocation=invocation)

    assert not telemetry.settle_llm_content(invocation)


def test_a_round_without_staged_content_settles_as_not_attached() -> None:
    """An `llm` span the fold wrote with no pair on it is not an
    attachment: nothing was taken, so nothing is recorded."""
    invocation = "d" * 32
    telemetry, _ = exporting()
    emitted = session_events(Clock(), telemetry)
    open_session(emitted)
    start_turn(emitted)
    round_done(emitted, invocation=invocation)

    assert not telemetry.settle_llm_content(invocation)


# --- a tool call's content, on the tool span that ran it (#533) --------


def _tool_content(arguments: str, result: str) -> dict[str, str]:
    return {GEN_AI_TOOL_CALL_ARGUMENTS: arguments, GEN_AI_TOOL_CALL_RESULT: result}


def _tool_spans(spans: list) -> dict[int, dict]:
    return {
        span.attributes["vinga.tool.call.position"]: dict(span.attributes)
        for span in spans
        if span.name == "tool"
    }


def test_tool_content_rides_the_span_at_its_own_position() -> None:
    """Two calls of one round, staged out of order: each span takes the
    pair staged under its own invocation and position, and a third key
    nobody emits is never read."""
    invocation = "6" * 32
    telemetry, memory = exporting()
    emitted = session_events(Clock(), telemetry)
    open_session(emitted)
    start_turn(emitted)
    assert telemetry.stage_tool_content(
        SESSION, invocation, 1, _tool_content('{"query":"coffee"}', "second")
    )
    assert telemetry.stage_tool_content(
        SESSION, invocation, 0, _tool_content('{"query":"tea"}', "first")
    )
    call_tool(emitted, name="recall", invocation=invocation, position=0)
    call_tool(emitted, name="recall", invocation=invocation, position=1)
    finish_reply(emitted)

    tools = _tool_spans(finished(telemetry, memory))
    assert tools[0][GEN_AI_TOOL_CALL_ARGUMENTS] == '{"query":"tea"}'
    assert tools[0][GEN_AI_TOOL_CALL_RESULT] == "first"
    assert tools[1][GEN_AI_TOOL_CALL_ARGUMENTS] == '{"query":"coffee"}'
    assert tools[1][GEN_AI_TOOL_CALL_RESULT] == "second"
    # The conventions' keys alone: Langfuse maps them to the tool
    # observation's input and output, and an alias would outrank that.
    assert all(OBSERVATION_INPUT not in tool for tool in tools.values())
    assert all(OBSERVATION_OUTPUT not in tool for tool in tools.values())


def test_a_tool_span_without_staged_content_carries_none() -> None:
    telemetry, memory = exporting()
    emitted = session_events(Clock(), telemetry)
    open_session(emitted)
    start_turn(emitted)
    call_tool(emitted, invocation="7" * 32, position=0)
    finish_reply(emitted)

    (tool,) = _tool_spans(finished(telemetry, memory)).values()
    assert GEN_AI_TOOL_CALL_ARGUMENTS not in tool
    assert GEN_AI_TOOL_CALL_RESULT not in tool


def test_tool_content_is_refused_without_a_live_session_trace() -> None:
    telemetry, _ = exporting()

    assert not telemetry.stage_tool_content(
        SESSION, "8" * 32, 0, _tool_content("{}", "must not survive")
    )


def test_a_tool_call_with_no_trace_discards_its_staged_content() -> None:
    """Staged while the trace was live, folded after it closed: the fold
    takes the slot on its no-trace path too, so the same join keys on a
    later span find nothing."""
    invocation = "9" * 32
    telemetry, memory = exporting()
    emitted = session_events(Clock(), telemetry)
    open_session(emitted)
    start_turn(emitted)
    assert telemetry.stage_tool_content(
        SESSION, invocation, 0, _tool_content("{}", "must not survive")
    )
    close_session(emitted)
    call_tool(emitted, invocation=invocation, position=0)

    open_session(emitted)
    start_turn(emitted)
    call_tool(emitted, invocation=invocation, position=0)
    finish_reply(emitted)

    (tool,) = _tool_spans(finished(telemetry, memory)).values()
    assert GEN_AI_TOOL_CALL_RESULT not in tool
