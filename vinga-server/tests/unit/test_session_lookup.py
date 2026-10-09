"""vinga's lookup over the pages it knows, in a session (#612, M5).

The built-in agent is offered `search_docs`, and no other agent is: one
that asks for it anyway is answered as a name nobody publishes, however
it asks. The lookup weighs up the guide of the board the session speaks
through. The round after a lookup gets its own first-token allowance
and the agent's filler as a holding phrase, since that round is the
slow one on a small local model. The query is conversation content, so
the last section plants a credential-shaped one and hunts it.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

import pytest

from tests.support.configs import POET_MAC, POET_TONE, base_config
from tests.support.events import both_formats, events, only
from tests.support.llm_input import traced
from tests.support.providers import ScriptedLlm, errors_of, results_of
from tests.support.sessions import (
    call,
    drive_reply,
    masked_session,
    run_reply,
    session_for,
)
from tests.support.telemetry import close_session, exporting, finish_reply, finished, released
from vinga_server.capture import DeviceFacts
from vinga_server.config import Config
from vinga_server.config.models import BUILTIN_AGENT, ServerConfig
from vinga_server.knowledge import lookup
from vinga_server.llm_input_export import build_llm_input_export
from vinga_server.providers import (
    LlmEvent,
    LlmProvider,
    TextDelta,
    ToolCall,
    ToolChoice,
    ToolDef,
    Turn,
)
from vinga_server.runtime.provider_watch import FirstTokenTimeout
from vinga_server.tools import builtin, names

KITCHEN = "aa:bb:cc:dd:ee:41"
LCD_REPORTED = "esp32-s3-touch-lcd-1.54"
LCD_GUIDE = "Waveshare ESP32-S3-Touch-LCD-1.54"

UTTERANCE = b"\x00\x00" * 320


def world(server: dict[str, object] | None = None, **builtin_agent: Any) -> Config:
    """The lane's agents, with vinga served and one board bound to it
    alone, and the poet's board bound to the poet alone."""
    return base_config(
        **({"server": server} if server is not None else {}),
        builtin_agent={"tts": "tenor", **builtin_agent},
        devices={KITCHEN: [BUILTIN_AGENT], POET_MAC: ["poet"]},
    )


def lcd() -> DeviceFacts:
    facts = DeviceFacts()
    facts.record(KITCHEN, "2.4.0", LCD_REPORTED)
    return facts


def offered(script: ScriptedLlm) -> list[str]:
    return [tool.name for tool in script.seen[0][1]]


# The offer


async def test_vinga_is_offered_the_lookup() -> None:
    script = ScriptedLlm(["Hello."])
    session = session_for(world(), KITCHEN, {BUILTIN_AGENT: script})
    await run_reply(session, "hello")

    assert names.SEARCH_DOCS in offered(script)


async def test_an_operator_agent_is_not_offered_the_lookup() -> None:
    """The plan's mutation target: the lookup offered to every agent."""
    script = ScriptedLlm(["Hello."])
    session = session_for(world(), POET_MAC, {"poet": script})
    await run_reply(session, "hello")

    assert names.SEARCH_DOCS not in offered(script)


async def test_an_operator_agent_asking_for_it_anyway_is_told_there_is_no_such_tool() -> None:
    script = ScriptedLlm([[call(names.SEARCH_DOCS, query="wake word")], "Done."])
    session = session_for(world(), POET_MAC, {"poet": script})
    await run_reply(session, "hello")

    assert results_of(script) == [f'there is no tool called "{names.SEARCH_DOCS}"']
    assert errors_of(script) == [True]


async def test_a_mangled_call_from_an_operator_agent_is_told_the_same() -> None:
    """Not "the arguments were not a JSON object", which is what a tool
    that exists says: the runtime asks before it answers anything."""
    mangled = ToolCall(
        id="c-mangled", name=names.SEARCH_DOCS, arguments={}, malformed_arguments="{oops"
    )
    script = ScriptedLlm([[mangled], "Done."])
    session = session_for(world(), POET_MAC, {"poet": script})
    await run_reply(session, "hello")

    assert results_of(script) == [f'there is no tool called "{names.SEARCH_DOCS}"']


# What it answers


async def test_vinga_looks_up_the_board_it_speaks_through() -> None:
    script = ScriptedLlm([[call(names.SEARCH_DOCS, query="change wake word")], "Done."])
    session = session_for(world(), KITCHEN, {BUILTIN_AGENT: script}, device_facts=lcd())
    await run_reply(session, "can I change the wake word?")

    (answer,) = results_of(script)
    assert answer.startswith(f"[{LCD_GUIDE}: Wake word")
    assert "building the firmware with it" in " ".join(answer.split())
    assert errors_of(script) == [False]


async def test_a_lookup_with_no_query_is_asked_for_one() -> None:
    script = ScriptedLlm([[call(names.SEARCH_DOCS)], "Done."])
    session = session_for(world(), KITCHEN, {BUILTIN_AGENT: script})
    await run_reply(session, "hello")

    assert results_of(script) == [builtin.SEARCH_NEEDS_A_QUERY]


async def test_a_lookup_that_finds_nothing_says_so() -> None:
    script = ScriptedLlm([[call(names.SEARCH_DOCS, query="zzqx qqzz")], "Done."])
    session = session_for(world(), KITCHEN, {BUILTIN_AGENT: script})
    await run_reply(session, "hello")

    assert results_of(script) == [lookup.NOTHING_FOUND]


# The round after a lookup


class PacedLlm(LlmProvider):
    """A model whose rounds are written down with how long each takes to
    its first token: a list of `(delay, items)`, the last repeating."""

    def __init__(self, rounds: Sequence[tuple[float, list[Any]]]) -> None:
        self._rounds = list(rounds)
        self.calls = 0

    async def stream(
        self,
        system: str,
        turns: Sequence[Turn],
        tools: Sequence[ToolDef] = (),
        tool_choice: ToolChoice = "auto",
    ) -> AsyncIterator[LlmEvent]:
        delay, items = self._rounds[min(self.calls, len(self._rounds) - 1)]
        self.calls += 1
        await asyncio.sleep(delay)
        for item in items:
            yield TextDelta(item) if isinstance(item, str) else item


WATCHDOG_S = 0.05
ALLOWANCE_S = 0.5
SLOW_S = 0.2


def paced(first: ToolCall, after_s: float) -> PacedLlm:
    """A first round that asks for `first` at once, and a round after
    it that takes `after_s` to its first token, then answers."""
    return PacedLlm([(0.0, [first]), (after_s, ["Found it."])])


def timed(allowance_s: float = ALLOWANCE_S) -> Config:
    return world(
        server={
            "llm_first_token_timeout_s": WATCHDOG_S,
            "llm_lookup_first_token_timeout_s": allowance_s,
        }
    )


async def test_the_round_after_a_lookup_waits_out_its_allowance(
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm = paced(call(names.SEARCH_DOCS, query="wake word"), SLOW_S)
    session = session_for(timed(), KITCHEN, {BUILTIN_AGENT: cast(Any, llm)})
    with caplog.at_level("INFO"):
        spoken = await run_reply(session, "can I change the wake word?")

    assert spoken == ["Found it."]
    assert llm.calls == 2
    assert events(caplog, "llm_retry") == []


async def test_the_round_after_any_other_tool_keeps_the_session_s_bound(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The same wait after a call that is not the lookup is a stall,
    and the retry answers."""
    llm = PacedLlm(
        [(0.0, [call(names.RECALL, query="tea")]), (SLOW_S, ["Found it."]), (0.0, ["Found it."])]
    )
    session = session_for(timed(), KITCHEN, {BUILTIN_AGENT: cast(Any, llm)})
    with caplog.at_level("INFO"):
        await run_reply(session, "what do I drink?")

    assert only(caplog, "llm_retry").round == 2


async def test_a_round_after_a_lookup_that_passes_its_allowance_is_retried_then_given_up(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The allowance is a bound like the session's: past it, the round
    is retried once and then given up as `FirstTokenTimeout`."""
    llm = paced(call(names.SEARCH_DOCS, query="wake word"), 3 * ALLOWANCE_S)
    session = session_for(timed(), KITCHEN, {BUILTIN_AGENT: cast(Any, llm)})
    with caplog.at_level("INFO"), pytest.raises(FirstTokenTimeout):
        await run_reply(session, "can I change the wake word?")

    assert only(caplog, "llm_retry").round == 2
    assert only(caplog, "provider_failed").error == "FirstTokenTimeout"
    assert llm.calls == 3


async def test_an_allowance_shorter_than_the_session_s_bound_bounds_nothing_tighter(
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm = paced(call(names.SEARCH_DOCS, query="wake word"), WATCHDOG_S / 2)
    session = session_for(
        timed(allowance_s=WATCHDOG_S / 10), KITCHEN, {BUILTIN_AGENT: cast(Any, llm)}
    )
    with caplog.at_level("INFO"):
        spoken = await run_reply(session, "can I change the wake word?")

    assert spoken == ["Found it."]
    assert events(caplog, "llm_retry") == []


async def test_the_allowance_is_the_round_after_the_lookup_s_alone(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A lookup, a round that asks for another tool at once, and a slow
    round after that: the third round is bounded as the session bounds
    it, since the lookup was two rounds ago."""
    llm = PacedLlm(
        [
            (0.0, [call(names.SEARCH_DOCS, query="wake word")]),
            (0.0, [call(names.RECALL, query="tea")]),
            (SLOW_S, ["Found it."]),
            (0.0, ["Found it."]),
        ]
    )
    session = session_for(timed(), KITCHEN, {BUILTIN_AGENT: cast(Any, llm)})
    with caplog.at_level("INFO"):
        await run_reply(session, "hello")

    assert only(caplog, "llm_retry").round == 3


# The holding phrase


FILLER = {
    "enabled": True,
    # Far past the scripted rounds, so the turn's own timer never plays
    # and whatever plays is the hold.
    "delay_ms": 60_000.0,
    "phrases": ["Let me look that up.", "One moment."],
}


def masked(**filler: Any) -> Config:
    return base_config(
        providers={
            "llm": {"mock": {"type": "mock", "reply": "Said."}},
            "asr": {"mock": {"type": "mock", "text": "hello"}},
            "tts": {
                "tenor": {"type": "mock", "tone_hz": POET_TONE, "ms_per_char": 1, "min_ms": 60}
            },
            "vad": {"mock": {"type": "mock"}},
        },
        agents={"poet": {"prompt": "POET", "tts": "tenor", "filler": {**FILLER, **filler}}},
        builtin_agent={"tts": "tenor", "filler": {**FILLER, **filler}},
        devices={KITCHEN: [BUILTIN_AGENT], POET_MAC: ["poet"]},
    )


async def test_a_lookup_plays_the_agent_s_filler_while_the_next_round_is_read(
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm = paced(call(names.SEARCH_DOCS, query="wake word"), 0.3)
    session = await masked_session(masked(), KITCHEN, {BUILTIN_AGENT: llm})
    with caplog.at_level("INFO"):
        await drive_reply(session, UTTERANCE)

    played = only(caplog, "filler_played")
    assert played.agent == BUILTIN_AGENT
    assert played.phrase_index == 0
    replied = only(caplog, "replied")
    assert caplog.records.index(played) < caplog.records.index(replied)


async def test_another_tool_plays_no_holding_phrase(caplog: pytest.LogCaptureFixture) -> None:
    llm = paced(call(names.RECALL, query="tea"), 0.3)
    session = await masked_session(masked(), KITCHEN, {BUILTIN_AGENT: llm})
    with caplog.at_level("INFO"):
        await drive_reply(session, UTTERANCE)

    assert events(caplog, "filler_played") == []


async def test_a_turn_whose_timer_already_played_still_holds_the_lookup_round(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The one exception to one filler per turn: the timer's phrase
    covered the first wait, and the lookup starts a second one."""
    llm = PacedLlm(
        [(0.3, [call(names.SEARCH_DOCS, query="wake word")]), (0.3, ["Found it."])]
    )
    session = await masked_session(masked(delay_ms=60.0), KITCHEN, {BUILTIN_AGENT: llm})
    with caplog.at_level("INFO"):
        await drive_reply(session, UTTERANCE)

    assert [record.phrase_index for record in events(caplog, "filler_played")] == [0, 1]


# The query is conversation content

CREDENTIAL_SHAPED = "sk_live_" + "7qLookupQuerySentinel3Wd"


@pytest.fixture
def _telemetry_released() -> Any:
    yield
    released()


@pytest.mark.parametrize("export", [False, True])
async def test_a_lookup_query_reaches_no_log_line_or_event_field(
    export: bool, caplog: pytest.LogCaptureFixture, _telemetry_released: Any
) -> None:
    """With LLM input export off the query is on no span either; with it
    on, it is in the tool span's arguments, the content field the event
    catalog documents, and still in no log line or other event field.
    The conversation record is the other place it is meant to be, and
    is not hunted here."""
    telemetry, memory = exporting()
    setting = ServerConfig.model_validate(
        {"telemetry": {"enabled": True, "export_llm_input": export}}
    )
    llm_input = build_llm_input_export(setting, telemetry=telemetry)
    script = ScriptedLlm([[call(names.SEARCH_DOCS, query=CREDENTIAL_SHAPED)], "Done."])
    session, session_events = traced(
        telemetry, script, llm_input, config=world(), mac=KITCHEN, agent=BUILTIN_AGENT
    )

    with caplog.at_level(logging.DEBUG):
        await run_reply(session, "look it up")
        finish_reply(session_events)
        close_session(session_events)

    assert only(caplog, "tool_call").tool == names.SEARCH_DOCS
    assert CREDENTIAL_SHAPED not in both_formats(caplog)
    carrying = [
        (span.name, key)
        for span in finished(telemetry, memory)
        for key, value in dict(span.attributes).items()
        if CREDENTIAL_SHAPED in repr(value)
    ]
    if export:
        # The tool span's arguments, which the plan names, and the two
        # LLM spans' messages: the round that asked for the call carries
        # it in its output, and the round after it in its input, both
        # the same export's content fields.
        assert set(carrying) == {
            ("tool", "gen_ai.tool.call.arguments"),
            ("llm", "gen_ai.output.messages"),
            ("llm", "gen_ai.input.messages"),
        }
    else:
        assert carrying == []
