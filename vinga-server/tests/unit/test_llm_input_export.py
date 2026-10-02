"""Bounded neutral-seam rendering for canonical generation spans."""

import json
import logging

import pytest

from tests.support.llm_input import a_tool, a_turn, exporting, outcomes
from vinga_server import llm_input_export as export_module
from vinga_server.boundary import Reach
from vinga_server.config import ConfigError
from vinga_server.config.models import ServerConfig
from vinga_server.events.values import LlmInputExportFailure, LlmInputExportKind
from vinga_server.llm_input_export import LlmInputExport, build_llm_input_export
from vinga_server.providers.base import TextDelta, ToolCall, ToolResult
from vinga_server.telemetry import (
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_SYSTEM_INSTRUCTIONS,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_RESULT,
    LLM_TOOL_CHOICE,
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


# What a round stages is the GenAI conventions' content and nothing
# else: no backend-specific alias beside it. Langfuse maps the
# conventions itself, system instructions first, and an alias for the
# input outranks that mapping and leaves the system prompt out.
CONVENTIONS = {
    GEN_AI_SYSTEM_INSTRUCTIONS,
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OUTPUT_MESSAGES,
    LLM_TOOLS,
    LLM_TOOL_CHOICE,
}


def _one_round(stage: str) -> dict[str, str]:
    staged, recorded = exporter()
    getattr(staged, stage)(
        "session",
        invocation="round",
        agent="poet",
        system="be concise",
        turns=[a_turn()],
        tools=[],
        choice="none",
    )
    staged.observe("round", TextDelta("hi"))
    staged.finish("round")
    [(_, attributes)] = recorded.snapshots
    return attributes


@pytest.mark.parametrize("stage", ["stage_reply", "stage_recap"])
def test_a_round_stages_the_conventions_and_no_alias(stage: str) -> None:
    attributes = _one_round(stage)

    assert set(attributes) == CONVENTIONS
    assert not any(name.startswith("langfuse.") for name in attributes)
    # Byte for byte what the conventions carried before the aliases went.
    assert attributes[GEN_AI_SYSTEM_INSTRUCTIONS] == (
        '[{"content":"be concise","type":"text"}]'
    )
    assert attributes[GEN_AI_INPUT_MESSAGES] == (
        '[{"parts":[{"content":"turn the light on","type":"text"}],"role":"user"}]'
    )
    assert attributes[GEN_AI_OUTPUT_MESSAGES] == (
        '[{"parts":[{"content":"hi","type":"text"}],"role":"assistant"}]'
    )


def _streamed(ceiling: int, reply: str) -> list[tuple[str, dict[str, str]]]:
    """Stream one reply in pieces under a ceiling; what was exported."""
    staged, recorded = exporter(max_request_bytes=ceiling)
    staged.stage_reply(
        "session",
        invocation="streamed",
        agent=None,
        system="be concise",
        turns=[a_turn()],
        tools=[a_tool()],
        choice="auto",
    )
    for start in range(0, len(reply), 100):
        staged.observe("streamed", TextDelta(reply[start : start + 100]))
    staged.finish("streamed")
    return recorded.snapshots


def _conventions_size(attributes: dict[str, str]) -> int:
    return sum(len(attributes[name].encode("utf-8")) for name in CONVENTIONS)


def _dropped(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.reason
        for record in caplog.records
        if getattr(record, "event", None) == "llm_input_export_failed"
    ]


# A reply long enough that charging its streamed bytes twice, as the
# preflight did while an output alias existed, overshoots a ceiling the
# final canonical pair fits exactly.
LONG_REPLY = "y" * 1000


def test_a_streamed_pair_that_fits_the_ceiling_exactly_is_exported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    [(_, measured)] = _streamed(10 * 1024 * 1024, LONG_REPLY)
    ceiling = _conventions_size(measured)

    with caplog.at_level(logging.WARNING):
        [(_, attributes)] = _streamed(ceiling, LONG_REPLY)

    assert _dropped(caplog) == []
    assert _conventions_size(attributes) == ceiling


def test_a_streamed_pair_one_byte_over_the_ceiling_is_dropped_and_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    [(_, measured)] = _streamed(10 * 1024 * 1024, LONG_REPLY)
    ceiling = _conventions_size(measured)

    with caplog.at_level(logging.WARNING):
        snapshots = _streamed(ceiling, LONG_REPLY + "y")

    assert snapshots == []
    assert _dropped(caplog) == [LlmInputExportFailure.DROPPED.value]


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
    assert [(failure.kind, failure.reason) for failure in failures] == [
        (LlmInputExportKind.GENERATION.value, LlmInputExportFailure.DROPPED.value)
    ]


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
    assert [(failure.kind, failure.reason) for failure in failures] == [
        (LlmInputExportKind.GENERATION.value, LlmInputExportFailure.DROPPED.value)
    ]


def test_output_growth_drops_the_pair_while_it_streams(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The preflight, not `finish`, drops a stream that outgrew the ceiling.

    The delta's raw bytes alone exceed the ceiling, so the drop is due
    the moment it is observed. Asserting before `finish` is what makes
    this the preflight's test: `finish` would refuse the pair too, so a
    case that only looked afterwards would pass with no preflight at
    all, holding an arbitrarily long stream until it ended.
    """
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
    with caplog.at_level(logging.WARNING):
        staged.observe("grows", TextDelta("x" * 513))

        assert _dropped(caplog) == [LlmInputExportFailure.DROPPED.value]
        assert recorded.discarded == ["grows"]

        staged.observe("grows", TextDelta("more"))
        staged.finish("grows")

    assert recorded.snapshots == []
    assert _dropped(caplog) == [LlmInputExportFailure.DROPPED.value]


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


# --- a tool call's pair, for its tool span (#533) ----------------------


def _emitted() -> None:
    """The `tool_call` emission a unit case has no event for."""


TOOL_DROPPED = ("failed", LlmInputExportKind.TOOL_CALL.value, LlmInputExportFailure.DROPPED.value)
TOOL_EXPORTED = ("exported", 0, 1)


def test_a_tool_pair_uses_the_conventions_keys_and_the_part_encoding(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The arguments are encoded exactly as the round's `tool_call` part
    encodes them, so the two copies of one call read alike, and the
    result is the string the model was handed, unencoded."""
    staged, recorded = exporter()
    arguments = {"text": "the kettle is new", "id": 7, "nested": {"b": 1, "a": "ä"}}

    with caplog.at_level(logging.INFO):
        staged.stage_tool("session", "round", 2, arguments, 'saved "fact" 7', _emitted)

    [(invocation, position, attributes)] = recorded.tool_snapshots
    assert (invocation, position) == ("round", 2)
    assert set(attributes) == {GEN_AI_TOOL_CALL_ARGUMENTS, GEN_AI_TOOL_CALL_RESULT}
    staged.stage_reply(
        "session",
        invocation="asking",
        agent=None,
        system="s",
        turns=[],
        tools=[],
        choice="auto",
    )
    staged.observe("asking", ToolCall(id="c", name="remember", arguments=arguments))
    staged.finish("asking")
    rendered = recorded.snapshots[0][1][GEN_AI_OUTPUT_MESSAGES]
    assert f'"arguments":{attributes[GEN_AI_TOOL_CALL_ARGUMENTS]},' in rendered
    assert json.loads(attributes[GEN_AI_TOOL_CALL_ARGUMENTS]) == arguments
    assert attributes[GEN_AI_TOOL_CALL_RESULT] == 'saved "fact" 7'
    assert outcomes(caplog)[0] == TOOL_EXPORTED


def test_a_malformed_tool_call_exports_its_raw_argument_text() -> None:
    staged, recorded = exporter()

    staged.stage_tool("session", "round", 0, '{"fact": "tea', "not a JSON object", _emitted)

    [(_, _, attributes)] = recorded.tool_snapshots
    assert attributes[GEN_AI_TOOL_CALL_ARGUMENTS] == '{"fact": "tea'


def test_a_tool_pair_over_the_ceiling_is_dropped_and_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    staged, recorded = exporter(max_request_bytes=64)

    with caplog.at_level(logging.INFO):
        staged.stage_tool("session", "round", 0, {"fact": "tea"}, "x" * 64, _emitted)

    assert recorded.tool_snapshots == []
    assert outcomes(caplog) == [TOOL_DROPPED]


def test_a_tool_pair_telemetry_refuses_is_reported_as_a_tool_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    telemetry, recorded = exporting(accepts=False)
    staged = LlmInputExport(telemetry=telemetry)

    with caplog.at_level(logging.INFO):
        staged.stage_tool("session", "round", 0, {"fact": "tea"}, "saved", _emitted)

    assert recorded.tool_snapshots == []
    assert outcomes(caplog) == [TOOL_DROPPED]


def test_one_round_s_tool_pairs_share_one_ceiling(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Round 3's admission budget: each pair fits alone, and the round's
    calls together may not pass the per-request ceiling, so the earlier
    pairs attach and the rest are dropped whole and reported. The next
    round starts from nothing."""
    result = "r" * 90
    one = len(b"{}") + len(result.encode())
    staged, recorded = exporter(max_request_bytes=3 * one + one // 2)

    with caplog.at_level(logging.INFO):
        for position in range(5):
            staged.stage_tool("session", "busy", position, {}, result, _emitted)
        staged.stage_tool("session", "next", 0, {}, result, _emitted)

    assert [(i, p) for i, p, _ in recorded.tool_snapshots] == [
        ("busy", 0),
        ("busy", 1),
        ("busy", 2),
        ("next", 0),
    ]
    assert outcomes(caplog) == [
        TOOL_EXPORTED,
        TOOL_EXPORTED,
        TOOL_EXPORTED,
        TOOL_DROPPED,
        TOOL_DROPPED,
        TOOL_EXPORTED,
    ]


def test_a_session_close_forgets_its_round_budget() -> None:
    result = "r" * 90
    one = len(b"{}") + len(result.encode())
    staged, recorded = exporter(max_request_bytes=one)

    staged.stage_tool("session", "busy", 0, {}, result, _emitted)
    staged.session_closed("session")
    staged.stage_tool("session", "busy", 1, {}, result, _emitted)

    assert [p for _, p, _ in recorded.tool_snapshots] == [0, 1]


@pytest.mark.parametrize(
    "bounds, accepts",
    [({}, True), ({"max_request_bytes": 8}, True), ({}, False)],
    ids=["attached", "over-ceiling", "refused"],
)
def test_the_tool_call_event_is_emitted_once_whatever_becomes_of_the_pair(
    bounds: dict[str, int], accepts: bool
) -> None:
    """The stager owns the emission, so a pair dropped at staging must
    not take its `tool_call` event with it."""
    telemetry, _ = exporting(accepts=accepts)
    staged = LlmInputExport(telemetry=telemetry, **bounds)
    emitted: list[str] = []

    staged.stage_tool(
        "session", "round", 0, {"fact": "tea"}, "saved", lambda: emitted.append("tool_call")
    )

    assert emitted == ["tool_call"]
