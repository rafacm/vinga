"""Where an assembled request is staged, and where the stage is let go
(#502, M5).

The exporter's own bound, accounting and delivery are next door in
`test_llm_input_export.py`; what is here is the wiring, which is the
half that cannot be proved anywhere else: which call shapes stage, how
many observations one logical round becomes, and whether the flag off
costs a reply anything at all.

Driven through real replies against a real runtime rather than by
calling the exporter, because every claim in this file is about where a
call sits in the reply path. Two of them could not be stated any other
way:

- **A watchdog retry is ONE observation.** The retry calls a partial
  over arguments fixed before the first attempt, so the only thing that
  decides one observation or two is which side of that partial the
  staging sits on, and that is a fact about the pipeline.
- **The flag off stages nothing.** Not stages and discards: a runtime
  with no exporter renders nothing, which is what makes the default
  cost a reply no work rather than work nobody reads.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

import pytest

from tests.support.configs import POET_MAC, TIMEOUT_S, base_config, watchdog_config
from tests.support.events import both_formats
from tests.support.llm_input import A_CONTEXT, exporting
from tests.support.providers import ScriptedLlm, StallingLlm
from tests.support.sessions import (
    call,
    drive_reply,
    run_reply,
    session_for,
    start_reply,
    wait_for_reply,
)
from tests.support.sockets import RecordingSocket
from vinga_server.events.values import ReplyOutcome
from vinga_server.llm_input_export import LlmInputExport
from vinga_server.providers.base import (
    LlmEvent,
    LlmProvider,
    TextDelta,
    ToolChoice,
    ToolDef,
    Turn,
    Usage,
)

UTTERANCE = b"\x00\x00" * 320

# Well past the test-scale watchdog and never actually waited out: the
# watchdog cancels the sleep.
STALL_S = 30.0

# Planted in the tool's own result, which is the half a transcript
# deliberately never carries and the half that makes this class the
# widest one here.
RESULT_SENTINEL = "tool-result-sk-live-0LLMINPUT-SENTINEL"

# What a far side can put into a round that UTF-8 will not encode.
# Python's JSON decoder accepts the escape, so an MCP server's tool
# result can carry one and a tool result is staged content.
LONE_SURROGATE = json.loads(r'"tell me \ud800 about it"')


def staging(**bounds: Any) -> tuple[LlmInputExport, Any]:
    """A real exporter over a recorded telemetry seam, ready to be
    handed to a session.

    The real exporter rather than a stub of it, because what these cases
    drive is the staging call and the real object is what decides what
    one call does.
    """
    telemetry, recorded = exporting({})
    exporter = LlmInputExport(
        telemetry=telemetry, backlog=8, shutdown_timeout_s=10.0, **bounds
    )
    return exporter, recorded


def held(exporter: LlmInputExport, session: str) -> list[Any]:
    """What one session is holding right now.

    White-box, and the only reach of its kind in this file. The stage is
    private and the module's whole promise about it is that it is
    bounded and let go at the close, which the exporter's own suite
    drives through the close. What is asked HERE is a question about the
    reply path, mid-conversation and before any close: how many rounds
    this reply staged, and what they say. There is no close to read it
    through, because the claim is about what happened during the reply.
    """
    stage = exporter._staged.get(session)  # noqa: SLF001
    return [] if stage is None else [one.round for one in stage.rounds]


async def delivered(exporter: LlmInputExport, telemetry: Any) -> None:
    """Wait out the worker this close handed a job to, then stop it.

    A shutdown INTERRUPTS this exporter, so a case that stopped it
    without waiting would be driving the drop path whatever it meant to
    drive.
    """
    deadline = time.monotonic() + 10.0
    while not telemetry.jobs:
        assert time.monotonic() < deadline, "the worker never took the job"
        await asyncio.sleep(0.01)
    await exporter.shutdown()


class Streaming(LlmProvider):
    """A model that reaches its first token and then waits to be let go.

    What a barge-in case needs and nothing the shared doubles give: the
    reply has to be genuinely mid-round when the cancel lands, so that
    the claim is about a staged round being interrupted rather than
    about a reply that never got as far as assembling one.
    """

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(
        self,
        system: str,
        turns: "Sequence[Turn]",
        tools: "Sequence[ToolDef]" = (),
        tool_choice: ToolChoice = "auto",
    ) -> "AsyncIterator[LlmEvent]":
        self.started.set()
        yield TextDelta("Thinking.")
        await self.release.wait()
        yield TextDelta(" Done.")


def speaking(session: Any) -> Any:
    """A socket for the cases that drive a whole reply, which the two
    that run the audio path need and the stubbed ones do not."""
    session.websocket = cast(Any, RecordingSocket())
    return session


async def test_an_ordinary_reply_stages_one_round() -> None:
    """The unit this whole surface counts in, driven through the reply
    path that produces it."""
    exporter, _ = staging()
    session = session_for(
        base_config(), POET_MAC, {"poet": ScriptedLlm(["All done."])}, llm_input=exporter
    )

    await run_reply(session, "are you there")

    rounds = held(exporter, session.session_id)
    assert [one.purpose for one in rounds] == ["reply"]
    assert rounds[0].index == 1
    assert rounds[0].agent == "poet"


async def test_a_reply_with_tool_follow_up_stages_a_round_each() -> None:
    """A tool loop is several requests inside one turn, and every one of
    them is a thing the model was given: the second carries what the
    first asked for and what it was answered, which is exactly what a
    reader comes to this surface for."""
    exporter, _ = staging()
    session = session_for(
        base_config(),
        POET_MAC,
        {"poet": ScriptedLlm([[call("remember", fact="the kettle is new")], "Noted."])},
        llm_input=exporter,
    )

    await run_reply(session, "remember the kettle is new")

    rounds = held(exporter, session.session_id)
    assert len(rounds) == 2
    assert [one.index for one in rounds] == [1, 2]
    assert "tool_calls" in rounds[1].request
    assert "tool_results" in rounds[1].request
    assert "tool_calls" not in rounds[0].request, (
        "the first round already carried a call only the second could have"
    )


async def test_a_watchdog_retry_is_one_observation_and_not_two(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The finding this milestone turns into a rule, driven against the
    real watchdog.

    The retry calls a partial over `system`, `working`, `tools` and
    `choice`, all fixed before the first attempt, so it re-sends
    byte-identical content: two observations would be the same bytes
    twice and would claim the model was given two things. Staging
    therefore sits where the round is ASSEMBLED, outside the partial,
    and a mutation that moves it inside is what this case exists to
    catch.

    The retry is asserted to have really happened, so a case that passed
    because nothing was retried is a failure rather than a pass.
    """
    exporter, _ = staging()
    llm = StallingLlm(delays=[STALL_S, 0.0])
    session = session_for(
        watchdog_config(), POET_MAC, {"poet": cast(Any, llm)}, llm_input=exporter
    )

    with caplog.at_level(logging.INFO):
        spoken = await run_reply(session, "are you there")

    assert spoken == ["Recovered now."]
    assert llm.calls == 2, "the watchdog never retried, so this proves nothing"
    retried = [
        record for record in caplog.records if getattr(record, "event", None) == "llm_retry"
    ]
    assert len(retried) == 1
    assert retried[0].duration_ms >= TIMEOUT_S * 1000
    assert len(held(exporter, session.session_id)) == 1


async def test_a_round_whose_provider_failed_is_still_staged() -> None:
    """The model was given it whatever came back. Both attempts stall,
    the round is given up as the provider's failure, and the request is
    on the stage: an operator diagnosing a failed round is exactly the
    reader who needs to see what was sent.
    """
    exporter, _ = staging()
    llm = StallingLlm(delays=[STALL_S])
    session = speaking(
        session_for(
            watchdog_config(), POET_MAC, {"poet": cast(Any, llm)}, llm_input=exporter
        )
    )

    start_reply(session, UTTERANCE)
    await wait_for_reply(session)

    assert llm.calls == 2
    assert len(held(exporter, session.session_id)) == 1


async def test_a_barge_in_cancelling_a_reply_leaves_its_round_staged() -> None:
    """A reply the user spoke over is still a reply the model was given,
    and the round is staged before anything can cancel it: what a reader
    asking "what did it see" wants about an interrupted turn is the same
    thing they want about a finished one.
    """
    exporter, _ = staging()
    llm = Streaming()
    session = speaking(
        session_for(base_config(), POET_MAC, {"poet": cast(Any, llm)}, llm_input=exporter)
    )

    start_reply(session, UTTERANCE)
    await asyncio.wait_for(llm.started.wait(), 5.0)
    await session.runtime.cancel_reply(ReplyOutcome.BARGED_IN)
    llm.release.set()

    assert len(held(exporter, session.session_id)) == 1


async def test_the_usage_a_round_reported_is_not_in_what_was_staged() -> None:
    """The boundary in the other direction: what the model ANSWERED is
    not part of what it was given, and this surface carries the input
    only. The generation span already holds the usage."""
    exporter, _ = staging()
    session = session_for(
        base_config(),
        POET_MAC,
        {"poet": ScriptedLlm([["All done.", Usage(prompt_tokens=4242, completion_tokens=17)]])},
        llm_input=exporter,
    )

    await run_reply(session, "are you there")

    (one,) = held(exporter, session.session_id)
    assert "4242" not in one.request
    assert "All done." not in one.request


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
    exporter, _ = staging()
    session = session_for(
        base_config(), POET_MAC, {"poet": ScriptedLlm(["All done."])}, llm_input=exporter
    )

    spoken = await run_reply(session, LONE_SURROGATE)

    assert spoken == ["All done."], "the reply was lost to a telemetry surface"
    assert len(held(exporter, session.session_id)) == 1


async def test_the_flag_off_stages_nothing_at_all() -> None:
    """Not stages and discards: a runtime with no exporter renders
    nothing, which is what makes the default cost a reply no work rather
    than work nobody reads.

    The exporter is built and then NOT handed over, which is what a
    deployment with the flag off has: the composition answers None and
    the runtime holds nothing. A whole reply runs, its close is handed
    to the exporter anyway, and the exporter has never heard of the
    session, so there is nothing to stage, nothing to export and nothing
    to report.
    """
    exporter, telemetry = staging()
    session = session_for(
        base_config(), POET_MAC, {"poet": ScriptedLlm(["All done."])}, llm_input=None
    )

    await run_reply(session, "are you there")
    exporter.session_closed(session.session_id)

    assert held(exporter, session.session_id) == []
    assert telemetry.jobs == []


async def test_the_close_hands_the_stage_over_and_drops_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The device session's own half: the stage is handed over at the
    close, beside the transcript export's hand-over, and is gone
    afterwards whatever became of it."""
    caplog.set_level(logging.DEBUG)
    exporter, telemetry = staging()
    telemetry.contexts[""] = A_CONTEXT
    session = session_for(
        base_config(), POET_MAC, {"poet": ScriptedLlm(["All done."])}, llm_input=exporter
    )
    telemetry.contexts[session.session_id] = A_CONTEXT

    await run_reply(session, "are you there")
    assert held(exporter, session.session_id)
    exporter.session_closed(session.session_id)
    await delivered(exporter, telemetry)

    assert held(exporter, session.session_id) == []
    assert [one.index for _, _, rounds in telemetry.jobs for one in rounds] == [1]


async def test_what_a_tool_answered_reaches_the_stage_and_no_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The sentinel claim at the wiring level, and the inverse of the
    usual one: a tool's result is part of what the model was given, so
    it HAS to be on the stage, and it must not be anywhere this reply
    wrote down on its way there.
    """
    caplog.set_level(logging.DEBUG)
    exporter, _ = staging()
    session = speaking(
        session_for(
            base_config(),
            POET_MAC,
            {"poet": ScriptedLlm([[call("remember", fact=RESULT_SENTINEL)], "Noted."])},
            llm_input=exporter,
        )
    )

    await drive_reply(session, UTTERANCE)

    rounds = held(exporter, session.session_id)
    assert any(RESULT_SENTINEL in one.request for one in rounds), (
        "what the tool was asked never reached the stage"
    )
    assert RESULT_SENTINEL not in both_formats(caplog)
