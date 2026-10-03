"""A reply's tool exchanges, kept in the history its thread is sent on
every later reply (#599).

Driven through the scripted-session harness the tool-loop suite uses:
what the model is handed is the only place the history is observable,
so each test reads it off what a later round's provider saw. The pure
rules (the cap, the ids, the degraded note) are pinned in
`test_runtime_history.py`; these are the same rules reached through a
reply, a barge-in, a failure and a reload.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from tests.support.configs import BOTH_MAC, POET_MAC, base_config, registry_config
from tests.support.device_tools import STATUS, FakeDevice
from tests.support.providers import ScriptedLlm
from tests.support.sessions import call, hand_over_to, history, run_reply, session_for
from tests.support.stores import memory as lane_memory
from tests.support.tools_mcp import Applying, reading
from vinga_server.providers import ToolCall, ToolDef, Turn
from vinga_server.providers.anthropic_llm import anthropic_messages
from vinga_server.providers.base import LlmEvent, LlmProvider, TextDelta, ToolChoice
from vinga_server.runtime.history import DEGRADED_END, DEGRADED_PREFIX
from vinga_server.tools.mcp import McpServers

# A board tool's published name, which is what the model calls it by.
DEVICE_STATUS = "self_get_device_status"


def calls_in(turns: Sequence[Turn]) -> list[ToolCall]:
    return [one for turn in turns for one in turn.tool_calls]


def results_in(turns: Sequence[Turn]) -> list[str]:
    return [result.content for turn in turns for result in turn.tool_results]


def paired(seen: Sequence[tuple[Sequence[Turn], Any, Any]]) -> None:
    """Every request this model was handed pairs each call id with
    exactly one result, which is what a provider refuses a request
    over."""
    for turns, _, _ in seen:
        asked = [one.id for one in calls_in(turns)]
        answered = [result.tool_call_id for turn in turns for result in turn.tool_results]
        assert sorted(asked) == sorted(answered), turns
        assert len(set(asked)) == len(asked), turns


def degraded_records(turns: Sequence[Turn]) -> list[dict[str, Any]]:
    """Every degraded note in these turns, as the JSON it quotes."""
    records = []
    for turn in turns:
        for part in turn.content.split(DEGRADED_PREFIX)[1:]:
            records.append(json.loads(part.removesuffix(DEGRADED_END)))
    return records


def a_board_with_status(text: str) -> FakeDevice:
    device = FakeDevice([{"tools": [STATUS]}])
    device.call_results[STATUS["name"]] = {
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }
    return device


async def with_board(session: Any, device: FakeDevice) -> None:
    """Give a session a board's tools. White-box, the way the tool-loop
    suite does it: a board's tools arrive from a discovery run over the
    wire after the hello, and these sessions have no socket to run one
    on."""
    await device.client.discover()
    session._device_tools = device.client


class ReadsItsHistory(LlmProvider):
    """A model that answers from what it was handed. Asked about the
    door code, it says the code it finds in an earlier `remember` call
    and its result, and only when it finds none does it ask `recall`;
    asked anything else, it remembers the code. So whether it re-read
    anything is decided by the turns, and a test reads the decision."""

    def __init__(self) -> None:
        self.seen: list[tuple[list[Turn], list[ToolDef], ToolChoice]] = []

    async def stream(
        self,
        system: str,
        turns: Sequence[Turn],
        tools: Sequence[ToolDef] = (),
        tool_choice: ToolChoice = "auto",
    ) -> AsyncIterator[LlmEvent]:
        self.seen.append((list(turns), list(tools), tool_choice))
        if turns[-1].role == "tool":
            yield TextDelta("Done.")
            return
        if "door code" not in turns[-1].content:
            yield call("remember", text="the door code is 4721")
            return
        remembered = {
            one.id: one.arguments.get("text", "")
            for one in calls_in(turns)
            if one.name == "remember"
        }
        saved = [
            remembered[result.tool_call_id]
            for turn in turns
            for result in turn.tool_results
            if result.tool_call_id in remembered and not result.is_error
        ]
        if saved:
            yield TextDelta(f"You told me: {saved[-1]}.")
        else:
            yield call("recall", query="door code")


async def test_a_later_reply_answers_from_a_remembered_exchange_without_a_reread() -> None:
    """The issue's first criterion: the second reply's request holds the
    first reply's `remember` call and its result, structured, and the
    model answering from them asks for nothing."""
    model = ReadsItsHistory()
    session = session_for(base_config(), POET_MAC, {"poet": model}, memory=lane_memory())

    await run_reply(session, "remember this for me")
    asking = len(model.seen)
    assert await run_reply(session, "what is the door code?") == [
        "You told me: the door code is 4721."
    ]

    # One round: the answer, and no `recall`.
    assert len(model.seen) == asking + 1
    (turns, _, _) = model.seen[-1]
    (remembered,) = calls_in(turns)
    assert (remembered.name, remembered.arguments) == (
        "remember",
        {"text": "the door code is 4721"},
    )
    paired(model.seen)


async def test_a_large_device_result_is_whole_in_its_reply_and_cleared_after() -> None:
    big = "s" * 3072
    script = ScriptedLlm([[call(DEVICE_STATUS)], "Your board is fine.", "Still fine."])
    session = session_for(base_config(), POET_MAC, {"poet": script})
    await with_board(session, a_board_with_status(big))

    await run_reply(session, "how is my board?")
    await run_reply(session, "and now?")

    # Whole in the round after the call, inside the reply that made it.
    assert results_in(script.seen[1][0]) == [big]
    # Cleared on the next reply's request, naming the tool and the size.
    assert results_in(script.seen[2][0]) == [f"(result of {DEVICE_STATUS} cleared: 3072 bytes)"]
    (kept,) = calls_in(script.seen[2][0])
    assert (kept.name, kept.source) == (DEVICE_STATUS, "device")
    paired(script.seen)


async def test_a_tool_an_mcp_reload_removed_arrives_as_the_degraded_note() -> None:
    servers = McpServers.build(registry_config(granted=True))
    await servers.start_all()
    script = ScriptedLlm([[call("tools__secret_word")], "Got it.", "Next."])
    session = session_for(base_config(), POET_MAC, {"poet": script}, mcp_servers=servers)
    try:
        await run_reply(session, "what is the word?")
        await Applying(servers, registry_config(granted=True)).apply(
            reading(registry_config(granted=False))
        )
        await run_reply(session, "and again?")
    finally:
        await servers.stop_all()

    # Structured in the reply that made it, while it was offered.
    assert [one.name for one in calls_in(script.seen[1][0])] == ["tools__secret_word"]
    (turns, offered, _) = script.seen[-1]
    assert "tools__secret_word" not in {tool.name for tool in offered}
    assert calls_in(turns) == []
    assert results_in(turns) == []
    (record,) = degraded_records(turns)
    assert record["tool"] == "tools__secret_word"
    assert record["result"] == results_in(script.seen[1][0])[0]


async def test_a_malformed_call_reaches_the_next_reply_with_no_arguments() -> None:
    broken = ToolCall(id="c1", name="remember", malformed_arguments="{text: oops")
    script = ScriptedLlm([[broken], "Let me try that again.", "Fine."])
    session = session_for(base_config(), POET_MAC, {"poet": script})
    await run_reply(session, "remember this")
    await run_reply(session, "anything else?")

    (turns, _, _) = script.seen[-1]
    (kept,) = calls_in(turns)
    assert (kept.name, kept.arguments, kept.malformed_arguments) == ("remember", {}, None)
    (result,) = [result for turn in turns for result in turn.tool_results]
    assert result.is_error and "not a JSON object" in result.content
    assert "oops" not in repr(turns)


async def test_an_invented_name_is_structured_in_its_reply_and_degraded_after() -> None:
    """A name the model made up is handed back structured within the
    reply that made it, which is what the round after it continues
    from, and is degraded from the next reply on."""
    script = ScriptedLlm([[call("ghost_tool")], "I could not do that.", "Right."])
    session = session_for(base_config(), POET_MAC, {"poet": script})
    await run_reply(session, "do it")
    await run_reply(session, "never mind")

    assert [one.name for one in calls_in(script.seen[1][0])] == ["ghost_tool"]
    (turns, _, _) = script.seen[-1]
    assert calls_in(turns) == []
    (record,) = degraded_records(turns)
    assert (record["tool"], record["error"]) == ("ghost_tool", True)
    assert "no tool called" in record["result"]


async def test_a_failed_round_after_a_kept_one_leaves_the_kept_one() -> None:
    """Round 1 ran `remember`; round 2's provider call failed and the
    reply spoke nothing. The remembered exchange is in the history all
    the same, which is the case the issue exists for."""
    script = ScriptedLlm(
        [[call("remember", text="the user likes tea")], [RuntimeError("down")], "Tea."]
    )
    session = session_for(base_config(), POET_MAC, {"poet": script}, memory=lane_memory())
    with pytest.raises(RuntimeError):
        await run_reply(session, "remember I like tea")
    await run_reply(session, "what do I like?")

    (turns, _, _) = script.seen[-1]
    assert [turn.role for turn in turns] == ["user", "assistant", "tool", "user"]
    assert [one.name for one in calls_in(turns)] == ["remember"]
    paired(script.seen)
    # The next utterance follows a tool turn, which Anthropic would read
    # as two user messages in a row: its translator joins them.
    messages = anthropic_messages(turns)
    assert [message["role"] for message in messages] == ["user", "assistant", "user"]
    assert [block["type"] for block in messages[-1]["content"]] == ["tool_result", "text"]
    assert messages[-1]["content"][-1]["text"] == "what do I like?"


class HoldsRound(ScriptedLlm):
    """A scripted model whose round at `held` never answers, so a test
    can cut the reply there; `asked` is set when it is reached."""

    def __init__(self, rounds: Sequence[Any], held: int) -> None:
        super().__init__(rounds)
        self._held = held
        self.asked = asyncio.Event()

    async def stream(
        self,
        system: str,
        turns: Sequence[Turn],
        tools: Sequence[ToolDef] = (),
        tool_choice: ToolChoice = "auto",
    ) -> AsyncIterator[LlmEvent]:
        if len(self.seen) == self._held:
            self.seen.append((list(turns), list(tools), tool_choice))
            self.asked.set()
            await asyncio.Event().wait()
        async for event in super().stream(system, turns, tools, tool_choice):
            yield event


async def cut(reply: asyncio.Task[Any]) -> None:
    reply.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reply


async def test_a_barge_in_before_any_speech_keeps_the_completed_round() -> None:
    script = HoldsRound([[call("remember", text="the user likes tea")], "x", "Tea."], held=1)
    session = session_for(base_config(), POET_MAC, {"poet": script}, memory=lane_memory())
    reply = asyncio.create_task(run_reply(session, "remember I like tea"))
    await asyncio.wait_for(script.asked.wait(), 10)
    await cut(reply)

    await run_reply(session, "what do I like?")
    (turns, _, _) = script.seen[-1]
    assert [turn.role for turn in turns] == ["user", "assistant", "tool", "user"]
    assert [one.name for one in calls_in(turns)] == ["remember"]
    paired(script.seen)


async def test_a_barge_in_mid_round_keeps_the_answered_call_and_not_the_other() -> None:
    """Cut after the first of two calls answered: that pair is kept, the
    call still running is not, and the request after it pairs every id
    it carries."""
    device = a_board_with_status("unused")
    device.silent_methods.add("tools/call")
    script = ScriptedLlm(
        [[call("remember", text="the user likes tea"), call(DEVICE_STATUS)], "Tea."]
    )
    session = session_for(base_config(), POET_MAC, {"poet": script}, memory=lane_memory())
    await with_board(session, device)
    reply = asyncio.create_task(run_reply(session, "remember and check"))

    async def dispatched() -> None:
        # `remember` runs first and alone, so the board being asked
        # means the first call has answered.
        while not any(one.get("method") == "tools/call" for one in device.sent):
            await asyncio.sleep(0.005)

    await asyncio.wait_for(dispatched(), 10)
    await cut(reply)

    await run_reply(session, "what do I like?")
    (turns, _, _) = script.seen[-1]
    assert [one.name for one in calls_in(turns)] == ["remember"]
    assert len(results_in(turns)) == 1
    paired(script.seen)


async def test_a_move_leg_keeps_its_plain_calls_and_not_the_move() -> None:
    poet = ScriptedLlm(
        [
            ["One moment.", call("remember", text="tea"), call("switch_agent", agent="tutor")],
            "Back again.",
        ]
    )
    tutor = ScriptedLlm(["Tutor here."])
    session = session_for(
        base_config(), BOTH_MAC, {"poet": poet, "tutor": tutor}, memory=lane_memory()
    )
    # What the last leg said: each leg's speech is its own.
    assert await run_reply(session, "remember tea and get the tutor") == ["Tutor here."]

    hand_over_to(session, "poet")
    kept = await history(session, poet)
    assert [turn.role for turn in kept] == ["user", "assistant", "tool"]
    assert kept[1].content == "One moment."
    assert [one.name for one in kept[1].tool_calls] == ["remember"]
    paired(poet.seen)


async def test_every_sentence_heard_is_in_the_history_once() -> None:
    """A preamble lives in its round's assistant turn and the closing
    turn carries only what was said after the last kept round, so the
    history holds the whole reply exactly once."""
    script = ScriptedLlm(
        [
            ["Let me look.", call("remember", text="a")],
            ["One more.", call("remember", text="b")],
            "All done. Both saved.",
            "Next.",
        ]
    )
    session = session_for(base_config(), POET_MAC, {"poet": script}, memory=lane_memory())
    spoken = await run_reply(session, "save two")

    kept = await history(session, script)
    said = [turn.content for turn in kept if turn.role == "assistant" and turn.content]
    assert " ".join(said) == " ".join(spoken)
    assert said == ["Let me look.", "One more.", "All done. Both saved."]
    paired(script.seen)


async def test_a_device_result_holding_a_lone_surrogate_does_not_break_the_next_reply() -> None:
    """JSON allows an escaped lone surrogate, the device channel keeps it
    as text, and text that cannot be encoded as UTF-8 cannot be measured
    against the cap. What is kept is the result with the surrogate
    replaced, so the next reply is sent, and sized, like any other."""
    script = ScriptedLlm([[call(DEVICE_STATUS)], "Fine.", "Still fine."])
    session = session_for(base_config(), POET_MAC, {"poet": script})
    await with_board(session, a_board_with_status(json.loads('"volume \\ud800 high"')))

    await run_reply(session, "how is my board?")
    await run_reply(session, "and now?")

    assert results_in(script.seen[-1][0]) == ["volume � high"]
