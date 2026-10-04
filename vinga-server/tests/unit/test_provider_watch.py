"""Provider watching, through its own interface and with no session.

The session-level suites drive the watch through whole replies
(`test_session_watchdog.py`, `test_provider_watch_pins.py`); what they
cannot do cheaply is script a stream's timing exactly, which is what the
first-token bound is about. So here the watch is built over an events
object and a device session's conversations and nothing else, and handed
streams written down per attempt: one that stalls, one that answers, and
one whose own timeout fires before the watchdog's does.

What a watched call says is read off an attached tap, as the typed
payloads a consumer receives.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from tests.support.llm_sdk import FakeBlock, FakeMessage, FakeMessages, FakeStream, FakeUsage
from vinga_server.events import Emission, SessionEvents
from vinga_server.events.values import LlmPurpose
from vinga_server.memory.store import PromptMemory
from vinga_server.providers import LlmEvent, StreamStarted, TextDelta, Turn, Usage
from vinga_server.providers.anthropic_llm import AnthropicLlm
from vinga_server.runtime import prompt
from vinga_server.runtime.history import NOTHING_LOST, HistorySent
from vinga_server.runtime.provider_watch import FirstTokenTimeout, ProviderWatch
from vinga_server.runtime.turns import TurnUnderway
from vinga_server.session_conversations import SessionConversations

# The bound, at test scale, and a stall that the bound always cuts
# short rather than waits out.
BOUND_S = 0.02
STALL_S = 30.0

# A reply round's prompt, with a scope block and one fact in it: the
# accounting every reply round hands the watch (#533).
SENT = prompt.RoundPrompt(
    prompt.with_scopes(
        prompt.know_how("POET"),
        PromptMemory(state="", agent="- a fact", device="", agent_ids=(4,)),
    ),
    facts=(4,),
)
ACCOUNTING = ("system_characters", "memory_characters", "memory_sources", "memory_facts")


class Heard:
    """A tap keeping every payload it was handed."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def emit(self, emission: Emission) -> None:
        self.payloads.append(emission.payload)

    def of(self, name: str) -> list[dict[str, Any]]:
        return [one for one in self.payloads if one["event"] == name]


def a_watch() -> tuple[ProviderWatch, Heard, SessionConversations]:
    events = SessionEvents("watch")
    heard = Heard()
    events.attach(heard)
    conversations = SessionConversations("aa:bb:cc:dd:ee:01")
    conversations.activate("poet")
    return ProviderWatch(events, conversations, BOUND_S, None), heard, conversations


class Scripted:
    """A provider whose every attempt is one scripted stream. Each entry
    is what that attempt does before its first event: a delay, or an
    exception to raise; the last entry repeats."""

    def __init__(self, attempts: list[float | BaseException]) -> None:
        self._attempts = attempts
        self.calls = 0

    def stream(self) -> Callable[[], AsyncIterator[LlmEvent]]:
        def make() -> AsyncIterator[LlmEvent]:
            step = self._attempts[min(self.calls, len(self._attempts) - 1)]
            self.calls += 1
            return self._one(step)

        return make

    async def _one(self, step: float | BaseException) -> AsyncIterator[LlmEvent]:
        if isinstance(step, BaseException):
            raise step
        await asyncio.sleep(step)
        yield StreamStarted()
        yield TextDelta("Here.")


async def drained(stream: AsyncIterator[LlmEvent]) -> list[LlmEvent]:
    return [event async for event in stream]


# --- the first-token bound -----------------------------------------------


async def test_a_stalled_first_token_is_retried_once_and_the_retry_answers() -> None:
    watch, heard, _ = a_watch()
    provider = Scripted([STALL_S, 0.0])

    said = await drained(
        watch.reply_stream(
            provider, provider.stream(), invocation="a" * 32, round_=3, prompt=SENT,
            history=NOTHING_LOST,
        )
    )

    # The announcement is evidence and never content.
    assert said == [TextDelta("Here.")]
    assert provider.calls == 2
    (retried,) = heard.of("llm_retry")
    assert (retried["round"], retried["agent"]) == (3, "poet")
    assert heard.of("provider_failed") == []


async def test_a_second_stall_gives_up_as_first_token_timeout_and_retries_no_more() -> None:
    watch, heard, _ = a_watch()
    provider = Scripted([STALL_S])

    with pytest.raises(FirstTokenTimeout):
        await drained(
            watch.reply_stream(
                provider, provider.stream(), invocation="b" * 32, round_=1, prompt=SENT,
                history=NOTHING_LOST,
            )
        )

    assert provider.calls == 2
    assert len(heard.of("llm_retry")) == 1
    (failed,) = heard.of("provider_failed")
    assert failed["error"] == "FirstTokenTimeout"
    assert (failed["invocation"], failed["purpose"]) == ("b" * 32, "reply")


async def test_a_round_given_up_carries_no_chain_behind_it() -> None:
    """What gives a round up is the watchdog's own expiry, and the
    `TimeoutError` asyncio raised for it, with the cancellation behind
    that, is library machinery rather than anything the provider said.
    `FirstTokenTimeout` leaves with neither as its cause or its context,
    so nothing that walks the chain (a traceback, an exception exporter)
    is handed frames and messages this server did not write."""
    watch, _, _ = a_watch()
    provider = Scripted([STALL_S])

    with pytest.raises(FirstTokenTimeout) as raised:
        await drained(
            watch.reply_stream(
                provider, provider.stream(), invocation="b" * 32, round_=1, prompt=SENT,
                history=NOTHING_LOST,
            )
        )

    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


async def test_a_providers_own_timeout_before_the_deadline_passes_through() -> None:
    """The `expired()` check: an SDK timeout raised inside the window is
    the provider's failure, reported as its own class and raised as
    itself, and never retried as though the watchdog had fired."""
    watch, heard, _ = a_watch()
    provider = Scripted([TimeoutError("the SDK gave up")])

    with pytest.raises(TimeoutError) as raised:
        await drained(
            watch.reply_stream(
                provider, provider.stream(), invocation="c" * 32, round_=1, prompt=SENT,
                history=NOTHING_LOST,
            )
        )

    assert type(raised.value) is TimeoutError
    assert provider.calls == 1
    assert heard.of("llm_retry") == []
    (failed,) = heard.of("provider_failed")
    assert failed["error"] == "TimeoutError"


# --- a failure, told apart from its consumer's ---------------------------


async def test_watching_reports_a_failure_and_raises_it_on() -> None:
    watch, heard, _ = a_watch()

    with pytest.raises(ConnectionRefusedError):
        async with watch.watching("asr", object()):
            raise ConnectionRefusedError("no route")

    (failed,) = heard.of("provider_failed")
    assert (failed["stage"], failed["error"]) == ("asr", "ConnectionRefusedError")


async def test_a_consumers_failure_is_not_blamed_on_the_stream() -> None:
    watch, heard, _ = a_watch()
    provider = Scripted([0.0])
    stream = watch.watched(
        provider, provider.stream()(), invocation="d" * 32, purpose=LlmPurpose.REPLY
    )

    with pytest.raises(RuntimeError):
        async for _ in stream:
            raise RuntimeError("the voice refused")

    assert heard.of("provider_failed") == []


async def test_a_failure_names_the_pair_standing_when_it_is_said() -> None:
    watch, heard, conversations = a_watch()

    with pytest.raises(ConnectionRefusedError):
        async with watch.watching("asr", object()):
            conversations.activate("tutor")
            raise ConnectionRefusedError("no route")

    (failed,) = heard.of("provider_failed")
    assert failed["agent"] == "tutor"


# --- a round that finished -----------------------------------------------


async def test_a_reply_round_is_filed_on_its_turn_and_a_recap_round_is_not() -> None:
    watch, heard, conversations = a_watch()
    active = conversations.active
    assert active is not None
    turn = TurnUnderway(active.conversation, active.agent, "e" * 32)
    began = asyncio.get_running_loop().time()
    usage = Usage(prompt_tokens=12, completion_tokens=4)

    watch.reply_round_done(
        turn, 2, object(), [], began, None, usage, invocation="f" * 32, prompt=SENT,
        history=NOTHING_LOST,
    )
    watch.recap_round_done(
        object(), [], began, None, usage, invocation="0" * 32, history=NOTHING_LOST
    )

    assert turn.rounds == 1
    assert (turn.input_tokens, turn.output_tokens) == (12, 4)
    reply, recap = heard.of("llm_round")
    assert (reply["round"], reply["purpose"]) == (2, "reply")
    assert "round" not in recap and recap["purpose"] == "recap"


async def test_a_round_reports_the_cached_share_and_files_the_whole_input() -> None:
    """The cached count rides the event beside the input it is part of,
    and the turn's input total is the provider's `prompt_tokens` as
    given: the cached share is neither added to it a second time nor
    subtracted from it (#536)."""
    watch, heard, conversations = a_watch()
    active = conversations.active
    assert active is not None
    turn = TurnUnderway(active.conversation, active.agent, "e" * 32)
    began = asyncio.get_running_loop().time()
    usage = Usage(prompt_tokens=2000, completion_tokens=4, cached_prompt_tokens=1536)

    watch.reply_round_done(
        turn, 1, object(), [], began, None, usage, invocation="f" * 32, prompt=SENT,
        history=NOTHING_LOST,
    )
    watch.recap_round_done(
        object(), [], began, None, usage, invocation="0" * 32, history=NOTHING_LOST
    )

    assert (turn.input_tokens, turn.output_tokens) == (2000, 4)
    reply, recap = heard.of("llm_round")
    assert (reply["input_tokens"], reply["cache_read_input_tokens"]) == (2000, 1536)
    assert (recap["input_tokens"], recap["cache_read_input_tokens"]) == (2000, 1536)


async def test_a_round_that_reported_no_usage_reports_no_cached_share() -> None:
    watch, heard, conversations = a_watch()
    active = conversations.active
    assert active is not None
    turn = TurnUnderway(active.conversation, active.agent, "e" * 32)
    began = asyncio.get_running_loop().time()

    watch.reply_round_done(
        turn, 1, object(), [], began, None, None, invocation="f" * 32, prompt=SENT,
        history=NOTHING_LOST,
    )

    (reply,) = heard.of("llm_round")
    assert "input_tokens" not in reply
    assert "cache_read_input_tokens" not in reply


async def test_an_anthropic_round_files_its_cache_reads_on_the_turn() -> None:
    """The one place the Anthropic fold reaches stored accounting.

    That API's `input_tokens` excludes what it read from and wrote to its
    prompt cache; the adapter folds both back in, and the turn's input
    total, which is stored and summed by the metrics views, is that
    normalized count. Driven from the adapter's own stream so the pin is
    on what a real round files, not on a `Usage` written by hand."""
    messages = FakeMessages(
        FakeStream(
            ["Said."],
            FakeMessage(
                [FakeBlock(type="text")],
                FakeUsage(
                    input_tokens=10,
                    output_tokens=7,
                    cache_read_input_tokens=1800,
                    cache_creation_input_tokens=200,
                ),
            ),
        )
    )
    llm = AnthropicLlm(
        model="claude-sonnet-5",
        max_tokens=64,
        api_key="sk-test",
        client=type("Client", (), {"messages": messages})(),  # type: ignore[arg-type]
    )
    (usage,) = [
        event async for event in llm.stream("", [Turn("user", "hi")]) if isinstance(event, Usage)
    ]
    watch, heard, conversations = a_watch()
    active = conversations.active
    assert active is not None
    turn = TurnUnderway(active.conversation, active.agent, "e" * 32)
    began = asyncio.get_running_loop().time()

    watch.reply_round_done(
        turn, 1, object(), [], began, None, usage, invocation="f" * 32, prompt=SENT,
        history=NOTHING_LOST,
    )

    assert turn.input_tokens == 2010
    (reply,) = heard.of("llm_round")
    assert (reply["input_tokens"], reply["cache_read_input_tokens"]) == (2010, 1800)


# --- a reply round's prompt accounting (#533) ----------------------------


def accounted(payload: dict[str, Any]) -> dict[str, Any]:
    return {field: payload[field] for field in ACCOUNTING if field in payload}


SENT_ACCOUNTING = {
    "system_characters": len(SENT.text),
    "memory_characters": SENT.memory_characters,
    "memory_sources": SENT.memory_sources,
    "memory_facts": [4],
}


async def test_a_finished_reply_round_carries_the_prompt_it_sent_and_a_recap_none() -> None:
    watch, heard, conversations = a_watch()
    active = conversations.active
    assert active is not None
    turn = TurnUnderway(active.conversation, active.agent, "e" * 32)
    began = asyncio.get_running_loop().time()

    watch.reply_round_done(
        turn, 1, object(), [], began, None, None, invocation="f" * 32, prompt=SENT,
        history=NOTHING_LOST,
    )
    watch.recap_round_done(
        object(), [], began, None, None, invocation="0" * 32, history=NOTHING_LOST
    )

    reply, recap = heard.of("llm_round")
    assert accounted(reply) == SENT_ACCOUNTING
    assert accounted(recap) == {}


async def test_a_round_with_memory_off_carries_its_sizes_and_no_fact_list() -> None:
    watch, heard, conversations = a_watch()
    active = conversations.active
    assert active is not None
    turn = TurnUnderway(active.conversation, active.agent, "e" * 32)
    began = asyncio.get_running_loop().time()
    unread = prompt.RoundPrompt(SENT.sent, facts=None)

    watch.reply_round_done(
        turn, 1, object(), [], began, None, None, invocation="f" * 32, prompt=unread,
        history=NOTHING_LOST,
    )

    (reply,) = heard.of("llm_round")
    assert accounted(reply) == {
        field: held for field, held in SENT_ACCOUNTING.items() if field != "memory_facts"
    }


async def test_a_reply_stream_that_fails_carries_the_prompt_it_was_sending() -> None:
    """The route through `watched`: a failure the stream itself raised."""
    watch, heard, _ = a_watch()
    provider = Scripted([ConnectionRefusedError("no route")])

    with pytest.raises(ConnectionRefusedError):
        await drained(
            watch.reply_stream(
                provider, provider.stream(), invocation="b" * 32, round_=1, prompt=SENT,
                history=NOTHING_LOST,
            )
        )

    (failed,) = heard.of("provider_failed")
    assert failed["error"] == "ConnectionRefusedError"
    assert accounted(failed) == SENT_ACCOUNTING


async def test_a_round_given_up_by_the_watchdog_carries_the_prompt_it_was_sending() -> None:
    """The route that is not `watched`: `reply_stream`'s own report of
    the second stall, which `FirstTokenTimeout` in `error` proves is
    the one that fired. The retry re-sent the same prompt, so the
    accounting is the first attempt's."""
    watch, heard, _ = a_watch()
    provider = Scripted([STALL_S])

    with pytest.raises(FirstTokenTimeout):
        await drained(
            watch.reply_stream(
                provider, provider.stream(), invocation="b" * 32, round_=1, prompt=SENT,
                history=NOTHING_LOST,
            )
        )

    (failed,) = heard.of("provider_failed")
    assert failed["error"] == "FirstTokenTimeout"
    assert accounted(failed) == SENT_ACCOUNTING


@pytest.mark.parametrize("stage", ["asr", "tts"])
async def test_a_failure_of_another_stage_carries_no_prompt_accounting(stage: str) -> None:
    watch, heard, _ = a_watch()

    with pytest.raises(ConnectionRefusedError):
        async with watch.watching(stage, object()):
            raise ConnectionRefusedError("no route")

    (failed,) = heard.of("provider_failed")
    assert accounted(failed) == {}


# --- what a request's history lost on the way out (#599) -----------------

# A request that cleared two earlier results and degraded one call: the
# accounting every event about that request hands on unchanged.
LOST = HistorySent(
    cleared_results=2,
    cleared_bytes=5100,
    cleared_largest=3000,
    cleared_tools={"device": 1, "mcp.tools": 1},
    degraded_calls=1,
)
LOST_FIELDS = {
    "cleared_results": 2,
    "cleared_bytes": 5100,
    "cleared_largest": 3000,
    "cleared_tools": {"device": 1, "mcp.tools": 1},
    "degraded_calls": 1,
}
NOTHING_LOST_FIELDS = {"cleared_results": 0, "cleared_bytes": 0, "degraded_calls": 0}
HISTORY = tuple(LOST_FIELDS)


def lost(payload: dict[str, Any]) -> dict[str, Any]:
    return {field: payload[field] for field in HISTORY if field in payload}


class MidStream:
    """A provider that starts answering and then fails, which is the
    route a failure takes once the first event has been handed on."""

    def stream(self) -> Callable[[], AsyncIterator[LlmEvent]]:
        async def make() -> AsyncIterator[LlmEvent]:
            yield StreamStarted()
            yield TextDelta("Let me")
            raise ConnectionResetError("cut")

        return make


async def test_a_finished_reply_round_carries_what_its_history_lost() -> None:
    watch, heard, conversations = a_watch()
    active = conversations.active
    assert active is not None
    turn = TurnUnderway(active.conversation, active.agent, "e" * 32)
    began = asyncio.get_running_loop().time()

    watch.reply_round_done(
        turn,
        1,
        object(),
        [],
        began,
        None,
        None,
        invocation="f" * 32,
        prompt=SENT,
        history=LOST,
    )

    (reply,) = heard.of("llm_round")
    assert lost(reply) == LOST_FIELDS


@pytest.mark.parametrize(
    ("provider", "raised"),
    [
        pytest.param(
            Scripted([ConnectionRefusedError("no route")]),
            ConnectionRefusedError,
            id="as-the-stream-opens",
        ),
        pytest.param(MidStream(), ConnectionResetError, id="mid-stream"),
        pytest.param(Scripted([STALL_S]), FirstTokenTimeout, id="the-watchdog"),
    ],
)
async def test_a_reply_round_that_fails_carries_what_its_history_lost(
    provider: Any, raised: type[BaseException]
) -> None:
    """Every route a round's failure is reported by: the two the stream
    raises through `watched`, before and after its first event, and
    `reply_stream`'s own report of the second stall."""
    watch, heard, _ = a_watch()

    with pytest.raises(raised):
        await drained(
            watch.reply_stream(
                provider,
                provider.stream(),
                invocation="b" * 32,
                round_=1,
                prompt=SENT,
                history=LOST,
            )
        )

    (failed,) = heard.of("provider_failed")
    assert failed["error"] == raised.__name__
    assert lost(failed) == LOST_FIELDS


async def test_a_recap_carries_what_its_history_lost_zeros_included() -> None:
    """A recap whose history lost nothing says so in zeros; one that
    cleared and degraded says how much."""
    watch, heard, _ = a_watch()
    began = asyncio.get_running_loop().time()

    watch.recap_round_done(
        object(), [], began, None, None, invocation="0" * 32, history=NOTHING_LOST
    )
    watch.recap_round_done(
        object(), [], began, None, None, invocation="1" * 32, history=LOST
    )

    unhanded, handed = heard.of("llm_round")
    assert unhanded["purpose"] == handed["purpose"] == "recap"
    assert lost(unhanded) == NOTHING_LOST_FIELDS
    assert lost(handed) == LOST_FIELDS


async def test_a_recap_that_fails_carries_what_its_history_lost() -> None:
    watch, heard, _ = a_watch()
    provider = Scripted([ConnectionRefusedError("no route")])

    with pytest.raises(ConnectionRefusedError):
        await drained(
            watch.watched(
                provider,
                provider.stream()(),
                invocation="d" * 32,
                purpose=LlmPurpose.RECAP,
                history=LOST,
            )
        )

    (failed,) = heard.of("provider_failed")
    assert failed["purpose"] == "recap"
    assert lost(failed) == LOST_FIELDS
    assert accounted(failed) == {}


@pytest.mark.parametrize("stage", ["asr", "tts"])
async def test_a_failure_of_another_stage_carries_no_history(stage: str) -> None:
    watch, heard, _ = a_watch()

    with pytest.raises(ConnectionRefusedError):
        async with watch.watching(stage, object()):
            raise ConnectionRefusedError("no route")

    (failed,) = heard.of("provider_failed")
    assert lost(failed) == {}
