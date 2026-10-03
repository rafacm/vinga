"""A tool span carries what its call was asked and answered (#533).

With `server.telemetry.export_llm_input` on, the `tool` span a call ran
under carries the conventions' `gen_ai.tool.call.arguments` and
`gen_ai.tool.call.result`: the arguments the model asked with, encoded
as the round's `tool_call` part encodes them, and the result exactly as
the model was handed it. Off, it carries neither, and nothing about the
call's content reaches a span or a log line.

Driven through a real session, the real tool execution and the real
exporter writing into the SDK's in-memory exporter, so the handoff
these cases prove is the production one: staged by the call just
before its `tool_call` event, taken by that event's fold.
"""

import functools
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from tests.support.configs import POET_MAC
from tests.support.events import both_formats
from tests.support.events import events as logged_events
from tests.support.llm_input import Unnameable, traced
from tests.support.providers import ScriptedLlm
from tests.support.sessions import call, run_reply
from tests.support.telemetry import (
    SESSION,
    Clock,
    call_tool,
    close_session,
    exporting,
    finish_reply,
    finished,
    open_session,
    released,
    session_events,
    start_turn,
)
from vinga_server.config.models import ServerConfig
from vinga_server.llm_input_export import LlmInputExport, build_llm_input_export
from vinga_server.providers.base import ToolCall
from vinga_server.runtime.tool_execution import ToolExecution
from vinga_server.runtime.turns import TurnUnderway
from vinga_server.session_conversations import SessionConversations
from vinga_server.telemetry import (
    _QUIETING,
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_RESULT,
    LLM_SPAN,
    OBSERVATION_INPUT,
    OBSERVATION_OUTPUT,
    TOOL_SPAN,
)

CONTENT = {GEN_AI_TOOL_CALL_ARGUMENTS, GEN_AI_TOOL_CALL_RESULT}

# Shaped like a live credential, so a leak of it would pass any syntax
# check a reader might apply.
CREDENTIAL_SHAPED = "sk_live_" + "9xToolArgSentinel0Kq7Wd2"


@pytest.fixture(autouse=True)
def _release() -> Iterator[None]:
    yield
    released()
    assert _QUIETING.held() == 0


async def _spans(rounds: list[Any], *, export: bool) -> list[Any]:
    telemetry, memory = exporting()
    llm_input = LlmInputExport(telemetry=telemetry) if export else None
    session, events = traced(telemetry, ScriptedLlm(rounds), llm_input)
    await run_reply(session, "what do I drink")
    finish_reply(events)
    close_session(events)
    return finished(telemetry, memory)


def _tools(spans: list[Any]) -> dict[int, dict[str, Any]]:
    return {
        span.attributes["vinga.tool.call.position"]: dict(span.attributes)
        for span in spans
        if span.name == TOOL_SPAN
    }


def _parts(attributes: dict[str, Any], key: str, kind: str) -> list[dict[str, Any]]:
    return [
        part
        for message in json.loads(attributes[key])
        for part in message["parts"]
        if part["type"] == kind
    ]


async def test_each_tool_span_carries_its_own_call_s_arguments_and_result() -> None:
    """Two calls of one round, run out of the model's order (`set_state`
    is a memory write and runs first): the span at position n carries the
    n-th call's arguments as the asking round's output rendered them, and
    the n-th result the next round's input handed the model."""
    spans = await _spans(
        [
            [call("recall", query="tea"), call("set_state", key="drink", value="tea")],
            "Done.",
        ],
        export=True,
    )

    asking, answering = (dict(span.attributes) for span in spans if span.name == LLM_SPAN)
    asked = _parts(asking, GEN_AI_OUTPUT_MESSAGES, "tool_call")
    handed = _parts(answering, GEN_AI_INPUT_MESSAGES, "tool_call_response")
    tools = _tools(spans)
    assert sorted(tools) == [0, 1]
    for position, tool in tools.items():
        assert json.loads(tool[GEN_AI_TOOL_CALL_ARGUMENTS]) == asked[position]["arguments"]
        assert tool[GEN_AI_TOOL_CALL_RESULT] == handed[position]["response"]
        assert OBSERVATION_INPUT not in tool
        assert OBSERVATION_OUTPUT not in tool
    assert json.loads(tools[1][GEN_AI_TOOL_CALL_ARGUMENTS]) == {"key": "drink", "value": "tea"}


async def test_a_coerced_call_exports_the_model_s_arguments() -> None:
    """The far side is handed `7`, the integer its schema declares; the
    model sent `"7"`, and that is what the export promises."""
    spans = await _spans(
        [[call("update_memory", id="7", text="a fact")], "Done."], export=True
    )

    (tool,) = _tools(spans).values()
    assert json.loads(tool[GEN_AI_TOOL_CALL_ARGUMENTS]) == {"id": "7", "text": "a fact"}


async def test_a_malformed_call_exports_its_raw_argument_text() -> None:
    raw = '{"fact": "the kettle'
    spans = await _spans(
        [
            [ToolCall(id="c-1", name="remember", arguments={}, malformed_arguments=raw)],
            "Done.",
        ],
        export=True,
    )

    (tool,) = _tools(spans).values()
    assert tool[GEN_AI_TOOL_CALL_ARGUMENTS] == raw
    assert tool[GEN_AI_TOOL_CALL_RESULT] == (
        "the arguments were not a JSON object; call again with valid ones"
    )


async def test_two_rounds_and_three_calls_are_counted_by_kind(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The exported ledger, exactly: the asking round, its three tool
    pairs, the answering round, each counted under its own kind."""
    with caplog.at_level(logging.INFO):
        await _spans(
            [
                [
                    call("recall", query="tea"),
                    call("recall", query="milk"),
                    call("recall", query="sugar"),
                ],
                "Done.",
            ],
            export=True,
        )

    exported = [
        (record.rounds, record.tool_calls)
        for record in caplog.records
        if getattr(record, "event", None) == "llm_input_exported"
    ]
    assert exported == [(1, 0), (0, 1), (0, 1), (0, 1), (1, 0)]
    assert not [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "llm_input_export_failed"
    ]


async def test_with_the_setting_off_a_call_s_content_reaches_no_span_or_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The no-leak sentinel, with the export built the way the
    composition builds it from a configuration that leaves it off."""
    telemetry, memory = exporting()
    off = ServerConfig.model_validate(
        {"telemetry": {"enabled": True, "export_llm_input": False}}
    )
    llm_input = build_llm_input_export(off, telemetry=telemetry)
    session, events = traced(
        telemetry,
        ScriptedLlm([[call("recall", query=CREDENTIAL_SHAPED)], "Done."]),
        llm_input,
    )

    with caplog.at_level(logging.DEBUG):
        await run_reply(session, "what do I drink")
        finish_reply(events)
        close_session(events)

    assert logged_events(caplog, "tool_call")
    assert CREDENTIAL_SHAPED not in both_formats(caplog)
    spans = finished(telemetry, memory)
    (tool,) = _tools(spans).values()
    assert not CONTENT & set(tool)
    for span in spans:
        assert CREDENTIAL_SHAPED not in repr(dict(span.attributes)), span.name


# --- a refused `tool_call` keeps nothing and claims nothing ------------

INVOCATION = "0123456789abcdef0123456789abcdef"


class Raising:
    """A source that owns every call and fails each one unnameably."""

    def snapshot(self, agent: str) -> list:
        return []

    def owns(self, claim: object) -> bool:
        return True

    async def dispatch(self, claim: object, agent: str) -> tuple[str, bool]:
        raise Unnameable()

    def timeout_for(self, claim: object) -> float:
        return 5.0


@pytest.mark.usefixtures("refusals_are_expected")
async def test_a_refused_tool_call_event_reports_failure_and_keeps_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The handoff is settled after the emission rather than assumed:
    the pair the refused event never consumed is reported as dropped,
    counted nowhere as exported, and gone, so a later span under the
    same join keys carries none of it."""
    telemetry, memory = exporting()
    exporter = LlmInputExport(telemetry=telemetry)
    events = session_events(Clock(), telemetry)
    open_session(events)
    start_turn(events)
    conversations = SessionConversations(POET_MAC)
    active = conversations.activate("poet")
    execution = ToolExecution(
        sources=(Raising(),),  # type: ignore[arg-type]
        device_tools=lambda: [],
        owner_of=lambda name: None,
        events=events,
        conversations=conversations,
        remembering=lambda: True,
        stage_content=functools.partial(exporter.stage_tool, SESSION),
    )
    turn = TurnUnderway(active.conversation, active.agent, None)
    asked = ToolCall(id="c-1", name="lamp", arguments={"secret": CREDENTIAL_SHAPED})
    (slot,) = execution.reserve(turn, [asked])

    with caplog.at_level(logging.INFO):
        (result,) = await execution.run(
            turn, [(slot, asked)], invocation=INVOCATION, refetchable=frozenset()
        )

    assert result.is_error
    assert not logged_events(caplog, "tool_call")
    assert [
        (record.kind, record.reason)
        for record in caplog.records
        if getattr(record, "event", None) == "llm_input_export_failed"
    ] == [("tool_call", "dropped")]
    assert not [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "llm_input_exported"
    ]

    call_tool(events, invocation=INVOCATION, position=0)
    finish_reply(events)
    spans = finished(telemetry, memory)
    (tool,) = _tools(spans).values()
    assert not CONTENT & set(tool)
    for span in spans:
        assert CREDENTIAL_SHAPED not in repr(dict(span.attributes)), span.name
