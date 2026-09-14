"""LLM content is paired with the generation event that closes its round."""

import json
import logging
from typing import Any, cast

import pytest

from tests.support.configs import POET_MAC, base_config, watchdog_config
from tests.support.events import both_formats, only
from tests.support.llm_input import exporting
from tests.support.providers import ScriptedLlm, StallingLlm
from tests.support.sessions import (
    call,
    drive_reply,
    run_reply,
    session_for,
)
from tests.support.sockets import RecordingSocket
from vinga_server.llm_input_export import LlmInputExport
from vinga_server.providers.base import Usage
from vinga_server.telemetry import GEN_AI_INPUT_MESSAGES, GEN_AI_OUTPUT_MESSAGES

UTTERANCE = b"\x00\x00" * 320

STALL_S = 30.0
RESULT_SENTINEL = "tool-result-sk-live-0LLMINPUT-SENTINEL"


def staging(**bounds: Any) -> tuple[LlmInputExport, Any]:
    telemetry, recorded = exporting()
    return LlmInputExport(telemetry=telemetry, **bounds), recorded


def speaking(session: Any) -> Any:
    session.websocket = cast(Any, RecordingSocket())
    return session


async def test_an_ordinary_reply_attaches_one_generation_snapshot() -> None:
    exporter, telemetry = staging()
    session = session_for(
        base_config(), POET_MAC, {"poet": ScriptedLlm(["All done."])}, llm_input=exporter
    )

    await run_reply(session, "are you there")

    [(invocation, attributes)] = telemetry.snapshots
    assert invocation
    assert "are you there" in attributes[GEN_AI_INPUT_MESSAGES]
    assert "All done." in attributes[GEN_AI_OUTPUT_MESSAGES]


async def test_a_tool_follow_up_attaches_one_snapshot_per_round() -> None:
    exporter, telemetry = staging()
    session = session_for(
        base_config(),
        POET_MAC,
        {"poet": ScriptedLlm([[call("remember", fact=RESULT_SENTINEL)], "Noted."])},
        llm_input=exporter,
    )

    await run_reply(session, "remember the kettle is new")

    assert len(telemetry.snapshots) == 2
    first = json.loads(telemetry.snapshots[0][1][GEN_AI_OUTPUT_MESSAGES])
    second = json.loads(telemetry.snapshots[1][1][GEN_AI_INPUT_MESSAGES])
    assert first[0]["parts"][0]["type"] == "tool_call"
    assert any(
        part.get("type") == "tool_call_response"
        for message in second
        for part in message["parts"]
    )


async def test_a_watchdog_retry_attaches_one_snapshot(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exporter, telemetry = staging()
    llm = StallingLlm(delays=[STALL_S, 0.0])
    session = session_for(
        watchdog_config(), POET_MAC, {"poet": cast(Any, llm)}, llm_input=exporter
    )

    with caplog.at_level(logging.INFO):
        spoken = await run_reply(session, "are you there")

    assert spoken == ["Recovered now."]
    assert llm.calls == 2
    [(invocation, _)] = telemetry.snapshots
    assert invocation == only(caplog, "llm_round").invocation


async def test_a_failed_round_attaches_its_input_and_partial_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exporter, telemetry = staging()
    llm = StallingLlm(delays=[STALL_S])
    session = speaking(
        session_for(
            watchdog_config(), POET_MAC, {"poet": cast(Any, llm)}, llm_input=exporter
        )
    )

    with caplog.at_level(logging.INFO):
        await drive_reply(session, UTTERANCE)

    assert llm.calls == 2
    [(invocation, attributes)] = telemetry.snapshots
    failed = only(caplog, "provider_failed")
    assert failed.invocation == invocation
    assert failed.purpose == "reply"
    assert GEN_AI_INPUT_MESSAGES in attributes
    assert GEN_AI_OUTPUT_MESSAGES in attributes


async def test_session_close_discards_an_unfinished_round() -> None:
    exporter, telemetry = staging()
    exporter.stage_reply(
        "session",
        invocation="unfinished",
        agent="poet",
        system="prompt",
        turns=[],
        tools=[],
        choice="none",
    )

    exporter.session_closed("session")

    assert telemetry.snapshots == []
    assert telemetry.discarded == ["unfinished"]


async def test_usage_is_not_copied_into_content_attributes() -> None:
    exporter, telemetry = staging()
    session = session_for(
        base_config(),
        POET_MAC,
        {"poet": ScriptedLlm([["All done.", Usage(prompt_tokens=4242, completion_tokens=17)]])},
        llm_input=exporter,
    )

    await run_reply(session, "are you there")

    [(_, attributes)] = telemetry.snapshots
    rendered = json.dumps(attributes)
    assert "4242" not in rendered
    assert "All done." in attributes[GEN_AI_OUTPUT_MESSAGES]


async def test_a_reply_carrying_a_lone_surrogate_still_answers() -> None:
    """The standing posture of this ladder, driven through a real reply:
    **no content export may fail a conversation.**

    Staging runs on the reply path and BEFORE the provider call, so a
    rendering that raised would not merely lose an observation, it would
    lose the answer the user is waiting for. A lone surrogate is the one
    hostile value that reaches the rendering from outside this process,
    since Python's JSON decoder accepts the escape and a tool result is
    staged content, and it is not encodable as UTF-8.

    The claim is the reply, which is why it is here and not beside the
    exporter's own cases: what is asserted is that the user was
    answered, and the round was staged anyway.
    """
    exporter, telemetry = staging()
    lone_surrogate = json.loads(r'"tell me \ud800 about it"')
    session = session_for(
        base_config(), POET_MAC, {"poet": ScriptedLlm(["All done."])}, llm_input=exporter
    )

    spoken = await run_reply(session, lone_surrogate)

    assert spoken == ["All done."], "the reply was lost to a telemetry surface"
    assert len(telemetry.snapshots) == 1


async def test_the_flag_off_does_no_content_work() -> None:
    exporter, telemetry = staging()
    session = session_for(
        base_config(), POET_MAC, {"poet": ScriptedLlm(["All done."])}, llm_input=None
    )

    await run_reply(session, "are you there")
    exporter.session_closed(session.session_id)

    assert telemetry.snapshots == []
    assert telemetry.discarded == []


async def test_tool_content_reaches_only_the_generation_snapshot(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The sentinel claim at the wiring level, and the inverse of the
    usual one: a tool's result is part of what the model was given, so
    it HAS to be on the stage, and it must not be anywhere this reply
    wrote down on its way there.
    """
    caplog.set_level(logging.DEBUG)
    exporter, telemetry = staging()
    session = speaking(
        session_for(
            base_config(),
            POET_MAC,
            {"poet": ScriptedLlm([[call("remember", fact=RESULT_SENTINEL)], "Noted."])},
            llm_input=exporter,
        )
    )

    await drive_reply(session, UTTERANCE)

    assert any(
        RESULT_SENTINEL in attributes[GEN_AI_OUTPUT_MESSAGES]
        for _, attributes in telemetry.snapshots
    )
    assert RESULT_SENTINEL not in both_formats(caplog)
