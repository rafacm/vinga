"""Canonical generation content is folded onto the actual LLM span."""

from collections.abc import Iterator

import pytest

from tests.support.telemetry import (
    SESSION,
    Clock,
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
        OBSERVATION_INPUT: '[{"parts":[],"role":"user"}]',
        OBSERVATION_OUTPUT: '[{"parts":[],"role":"assistant"}]',
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
    assert llm.attributes[OBSERVATION_INPUT]
    assert llm.attributes[OBSERVATION_OUTPUT]
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
