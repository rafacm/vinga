"""Bounded neutral-seam rendering for canonical generation spans."""

import json
import logging

import pytest

from tests.support.llm_input import a_tool, a_turn, exporting
from vinga_server import llm_input_export as export_module
from vinga_server.boundary import Reach
from vinga_server.config import ConfigError
from vinga_server.config.models import ServerConfig
from vinga_server.events.values import LlmInputExportFailure
from vinga_server.llm_input_export import LlmInputExport, build_llm_input_export
from vinga_server.providers.base import TextDelta, ToolCall, ToolResult
from vinga_server.telemetry import (
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_SYSTEM_INSTRUCTIONS,
    LLM_TOOLS,
)


def config(**telemetry: object) -> ServerConfig:
    return ServerConfig.model_validate(
        {
            "telemetry": {
                "enabled": True,
                "export_llm_input": True,
                **telemetry,
            }
        }
    )


def exporter(**bounds: object):
    telemetry, recorded = exporting()
    return LlmInputExport(telemetry=telemetry, **bounds), recorded


def test_builder_is_off_by_default() -> None:
    assert (
        build_llm_input_export(ServerConfig.model_validate({}), telemetry=None)
        is None
    )


def test_builder_refuses_the_flag_without_telemetry() -> None:
    broken = ServerConfig.model_validate(
        {"telemetry": {"enabled": False, "export_llm_input": True}}
    )
    with pytest.raises(ConfigError):
        build_llm_input_export(broken, telemetry=None)


def test_builder_honors_the_data_boundary() -> None:
    held, _ = exporting()
    with pytest.raises(ConfigError):
        build_llm_input_export(
            config(reach="internet"), telemetry=held, boundary=Reach.NETWORK
        )


def test_one_pair_uses_the_standard_message_attributes() -> None:
    staged, recorded = exporter()
    call = ToolCall(id="call-1", name="remember", arguments={"fact": "tea"})
    staged.stage_reply(
        "session",
        invocation="invocation",
        agent="poet",
        system="be concise",
        turns=[
            a_turn(),
            a_turn("assistant", "", calls=(call,)),
            a_turn(
                "tool",
                "",
                results=(ToolResult("call-1", "stored", False),),
            ),
        ],
        tools=[a_tool()],
        choice="auto",
    )
    staged.observe("invocation", TextDelta("withheld raw output"))
    staged.observe("invocation", call)
    staged.finish("invocation")

    [(identity, attributes)] = recorded.snapshots
    assert identity == "invocation"
    assert json.loads(attributes[GEN_AI_SYSTEM_INSTRUCTIONS]) == [
        {"content": "be concise", "type": "text"}
    ]
    messages = json.loads(attributes[GEN_AI_INPUT_MESSAGES])
    assert messages[1]["parts"][0]["type"] == "tool_call"
    assert messages[2]["parts"][0]["type"] == "tool_call_response"
    output = json.loads(attributes[GEN_AI_OUTPUT_MESSAGES])
    assert output[0]["parts"][0]["content"] == "withheld raw output"
    assert output[0]["parts"][1]["arguments"] == {"fact": "tea"}
    assert json.loads(attributes[LLM_TOOLS])[0]["input_schema"]["type"] == "object"


def test_malformed_tool_arguments_remain_in_both_message_sides() -> None:
    staged, recorded = exporter()
    malformed = ToolCall(
        id="call-broken",
        name="remember",
        malformed_arguments="{fact: tea",
    )
    staged.stage_reply(
        "session",
        invocation="malformed",
        agent=None,
        system="be concise",
        turns=[a_turn("assistant", "", calls=(malformed,))],
        tools=[a_tool()],
        choice="auto",
    )
    staged.observe("malformed", malformed)
    staged.finish("malformed")

    [(_, attributes)] = recorded.snapshots
    input_call = json.loads(attributes[GEN_AI_INPUT_MESSAGES])[0]["parts"][0]
    output_call = json.loads(attributes[GEN_AI_OUTPUT_MESSAGES])[0]["parts"][0]
    assert input_call["arguments"] == "{fact: tea"
    assert output_call["arguments"] == "{fact: tea"


def test_a_pair_over_the_operation_ceiling_is_dropped_whole(
    caplog: pytest.LogCaptureFixture,
) -> None:
    staged, recorded = exporter(max_request_bytes=128)
    with caplog.at_level(logging.WARNING):
        staged.stage_reply(
            "session",
            invocation="too-large",
            agent=None,
            system="x" * 500,
            turns=[],
            tools=[],
            choice="none",
        )
    assert recorded.snapshots == []
    failures = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "llm_input_export_failed"
    ]
    assert failures[0].reason == LlmInputExportFailure.DROPPED.value


def test_a_live_trace_refusal_drops_the_pair_truthfully(
    caplog: pytest.LogCaptureFixture,
) -> None:
    telemetry, recorded = exporting(accepts=False)
    staged = LlmInputExport(telemetry=telemetry)
    staged.stage_reply(
        "missing-session",
        invocation="not-staged",
        agent=None,
        system="be concise",
        turns=[],
        tools=[],
        choice="none",
    )

    with caplog.at_level(logging.WARNING):
        staged.finish("not-staged")

    assert recorded.snapshots == []
    failures = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "llm_input_export_failed"
    ]
    assert [failure.reason for failure in failures] == [
        LlmInputExportFailure.DROPPED.value
    ]


def test_output_growth_can_drop_the_whole_pair() -> None:
    staged, recorded = exporter(max_request_bytes=512)
    staged.stage_reply(
        "session",
        invocation="grows",
        agent=None,
        system="small",
        turns=[],
        tools=[],
        choice="none",
    )
    staged.observe("grows", TextDelta("x" * 1000))
    staged.finish("grows")
    assert recorded.snapshots == []


def test_streaming_output_is_rendered_once_at_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged, recorded = exporter()
    staged.stage_reply(
        "session",
        invocation="streamed",
        agent=None,
        system="small",
        turns=[],
        tools=[],
        choice="none",
    )
    original = export_module._output
    renders = 0

    def counting_output(text: list[str], calls: list[ToolCall]) -> str:
        nonlocal renders
        renders += 1
        return original(text, calls)

    monkeypatch.setattr(export_module, "_output", counting_output)
    for _ in range(100):
        staged.observe("streamed", TextDelta("two UTF-8 bytes: é"))

    assert renders == 0
    staged.finish("streamed")
    assert renders == 1
    assert len(recorded.snapshots) == 1


def test_session_budget_evicts_the_oldest_unfinished_round() -> None:
    staged, recorded = exporter(session_budget_bytes=300, max_request_bytes=500)
    for identity in ("first", "second"):
        staged.stage_reply(
            "session",
            invocation=identity,
            agent=None,
            system="x" * 180,
            turns=[],
            tools=[],
            choice="none",
        )
    staged.finish("first")
    staged.finish("second")
    assert [identity for identity, _ in recorded.snapshots] == ["second"]


def test_a_duplicate_invocation_is_rejected_without_replacing_the_first(
    caplog: pytest.LogCaptureFixture,
) -> None:
    staged, recorded = exporter()
    staged.stage_reply(
        "first-session",
        invocation="same",
        agent=None,
        system="original",
        turns=[],
        tools=[],
        choice="none",
    )

    with caplog.at_level(logging.WARNING):
        staged.stage_reply(
            "second-session",
            invocation="same",
            agent=None,
            system="replacement",
            turns=[],
            tools=[],
            choice="none",
        )

    failures = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "llm_input_export_failed"
    ]
    assert [(failure.session, failure.reason) for failure in failures] == [
        ("second-session", LlmInputExportFailure.DROPPED.value)
    ]
    staged.finish("same")
    [(_, attributes)] = recorded.snapshots
    assert "original" in attributes[GEN_AI_SYSTEM_INSTRUCTIONS]
    assert "replacement" not in attributes[GEN_AI_SYSTEM_INSTRUCTIONS]


def test_a_lone_surrogate_is_escaped_without_escaping_the_reply() -> None:
    staged, recorded = exporter()
    awkward = json.loads(r'"\ud800"')
    staged.stage_reply(
        "session",
        invocation="awkward",
        agent=None,
        system=awkward,
        turns=[],
        tools=[],
        choice="none",
    )
    staged.finish("awkward")
    assert len(recorded.snapshots) == 1
