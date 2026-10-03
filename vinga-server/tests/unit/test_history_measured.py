"""What a request's history lost on the way out, measured (#599).

A thread keeps its agent's tool exchanges, and every request clears an
earlier reply's result over 2 KiB and degrades a call to a tool it does
not offer (`test_session_kept_tools.py`). What this suite pins is what
the events about a request say was done to it: five facts on
`llm_round` and on the LLM-stage `provider_failed`, by both of the
routes a round fails by, the same five on the `llm` span under
`vinga.llm.history.*`, and `refetch` on a `tool_call`, and on its tool
span, that asks again for what a cleared result held.

The pure half is asked of its two owners directly: the counting is
`runtime/history.py`'s and the key a cleared result is counted under is
`tool_execution.cleared_key`'s. Everything else is driven through the
scripted-session harness, so it is the pipeline's own wiring that has to
carry each fact, read off the records a consumer reads and the spans an
exporter exports. A recap is driven through the watch by hand instead,
because until a recap's history holds rebuilt exchanges nothing a
session does can hand it a cleared one; the watch's own routes are in
`test_provider_watch.py`.

Counts, sizes and naming-policy keys only: the last case plants
credential-shaped bytes where a far side chooses them, in a result that
is cleared and in a server's own tool name, and finds them in no record
and on no span.
"""

import asyncio
import logging
import sys
from collections.abc import Iterator
from typing import Any

import pytest

from tests.support.configs import POET_MAC, STDIO_SERVER, base_config
from tests.support.device_tools import STATUS, FakeDevice
from tests.support.events import events, fields_of, only
from tests.support.mcp_stdio_server import LONG_ANSWER_ENV
from tests.support.providers import ScriptedLlm
from tests.support.sessions import call, events_of, run_reply, session_for
from tests.support.telemetry import (
    Clock,
    close_session,
    exporting,
    finished,
    open_session,
    released,
    session_events,
    start_turn,
)
from tests.support.tools_mcp import Applying, reading
from vinga_server.config import Config
from vinga_server.providers import ToolResult, Turn
from vinga_server.runtime.history import (
    NOTHING_LOST,
    Cleared,
    HistorySent,
    Pair,
    as_sent,
    kept_round,
)
from vinga_server.runtime.provider_watch import ProviderWatch
from vinga_server.runtime.tool_execution import cleared_key
from vinga_server.session_conversations import SessionConversations
from vinga_server.telemetry import _QUIETING, LLM_INVOCATION_ID, LLM_SPAN
from vinga_server.tools.mcp import McpServers

# A board tool's published name, which is what the model calls it by.
DEVICE_STATUS = "self_get_device_status"

# The five facts, as the event names them.
FACTS = (
    "cleared_results",
    "cleared_bytes",
    "cleared_largest",
    "cleared_tools",
    "degraded_calls",
)

# What a request whose history lost nothing says: the three counts as
# zeros, and the two that describe cleared results absent.
NOTHING = {"cleared_results": 0, "cleared_bytes": 0, "degraded_calls": 0}

# The same, on the span.
HISTORY_PREFIX = "vinga.llm.history."
NOTHING_ON_THE_SPAN = {
    "vinga.llm.history.cleared.count": 0,
    "vinga.llm.history.cleared.bytes": 0,
    "vinga.llm.history.degraded.count": 0,
}


@pytest.fixture(autouse=True)
def _no_lease_outlives_its_case() -> Iterator[None]:
    """Every exporter a case built is released at the end of it, for
    the reason `test_telemetry_spans.py` gives: the SDK's silence is one
    process-wide lease."""
    yield
    released()
    assert _QUIETING.held() == 0, "a case left an exporter holding the SDK's silence"


def history_of(fields: dict[str, Any]) -> dict[str, Any]:
    """The five facts a record carries, absent ones left out."""
    return {name: fields[name] for name in FACTS if name in fields}


def on_the_span(attributes: Any) -> dict[str, Any]:
    """The history attributes one `llm` span carries."""
    return {
        key: held for key, held in dict(attributes).items() if key.startswith(HISTORY_PREFIX)
    }


def a_board(text: str) -> FakeDevice:
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


def traced(session: Any) -> tuple[Any, Any, Any]:
    """An exporter attached to this session, with the session opened on
    it and a turn open, which is what the stage spans hang inside."""
    telemetry, memory = exporting()
    tapped = events_of(session)
    tapped.attach(telemetry.session_tap())
    open_session(tapped, providers={}, conversations=session.session_conversations)
    start_turn(tapped)
    return telemetry, memory, tapped


def llm_spans(telemetry: Any, memory: Any, tapped: Any) -> dict[str, Any]:
    """Every `llm` span the session exported, by the invocation its
    event carried, after the session closed."""
    close_session(tapped)
    return {
        span.attributes[LLM_INVOCATION_ID]: span
        for span in finished(telemetry, memory)
        if span.name == LLM_SPAN
    }


def server_config(**env: str) -> Config:
    """One stdio entry, `tools`, granted to the poet, with `env` handed
    to the server the entry spawns."""
    return base_config(
        mcp_servers={
            "tools": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(STDIO_SERVER)],
                "env": env,
            }
        },
        agents={
            "poet": {"prompt": "POET", "tts": "tenor", "mcp": ["tools"]},
            "tutor": {"prompt": "TUTOR", "tts": "alto"},
        },
    )


# --- the accounting, asked of its owners --------------------------------


def a_thread(pairs: list[Pair]) -> list[Turn]:
    """A thread whose first reply kept `pairs` and whose second has just
    been asked, so every exchange in it is an earlier reply's."""
    opened = [Turn("user", "go")]
    kept = kept_round(opened, "", pairs)
    return [*opened, *kept, Turn("assistant", "Done."), Turn("user", "and?")]


def test_each_cleared_result_is_counted_under_the_origin_its_call_was_made_with() -> None:
    """Four results over the cap, one per namespace, and one under it.
    The MCP one is from an entry this request no longer offers anything
    of and the invented one was never offered, so both are degraded as
    well as cleared, and both keep the key their call was made with: a
    removed entry is still the entry the call reached. A board tool
    that publishes a builtin's name is keyed as the board's."""
    pairs = [
        Pair(call("remember", text="tea"), ToolResult("c", "r" * 3000), "builtin", None),
        Pair(call("remember"), ToolResult("c", "d" * 2500), "device", None),
        Pair(call("tools__long_answer"), ToolResult("c", "m" * 2049), "mcp", "tools"),
        Pair(call("ghost"), ToolResult("c", "g" * 4000, is_error=True), "unknown", None),
        Pair(call("status"), ToolResult("c", "s" * 2048), "device", None),
    ]
    thread = a_thread(pairs)

    sent = as_sent(thread, len(thread), frozenset({"remember", "status"}))

    assert sent.accounting(cleared_key) == HistorySent(
        cleared_results=4,
        cleared_bytes=3000 + 2500 + 2049 + 4000,
        cleared_largest=4000,
        cleared_tools={"builtin.remember": 1, "device": 1, "mcp.tools": 1, "unknown": 1},
        degraded_calls=2,
    )


def test_a_history_that_lost_nothing_says_nothing_was_lost() -> None:
    thread = a_thread([Pair(call("status"), ToolResult("c", "fine"), "device", None)])

    sent = as_sent(thread, len(thread), frozenset({"status"}))

    assert sent.accounting(cleared_key) == NOTHING_LOST
    assert NOTHING_LOST == HistorySent(0, 0, None, {}, 0)


@pytest.mark.parametrize(
    ("source", "entry", "name", "key"),
    [
        ("builtin", None, "remember", "builtin.remember"),
        ("mcp", "tools", "tools__secret_word", "mcp.tools"),
        # A board may publish a builtin's name, and its result is the
        # board's: the key is the namespace, never the name.
        ("device", None, "remember", "device"),
        ("unknown", None, "ghost", "unknown"),
        # Neither reachable from a classification, and both named by
        # nothing rather than guessed at.
        ("mcp", None, "tools__secret_word", "unknown"),
        (None, None, "remember", "unknown"),
    ],
)
def test_a_cleared_result_is_keyed_under_the_tool_call_naming_policy(
    source: str | None, entry: str | None, name: str, key: str
) -> None:
    assert cleared_key(Cleared(name, source, entry, 3000)) == key


# --- on the round's record and its span ---------------------------------


async def test_a_round_says_what_its_history_cleared(caplog: pytest.LogCaptureFixture) -> None:
    """A board result of 3 KiB: whole and uncounted inside the reply
    that made it, cleared and counted on the next reply's request, on
    the event and on the span alike."""
    script = ScriptedLlm([[call(DEVICE_STATUS)], "Your board is fine.", "Still fine."])
    session = session_for(base_config(), POET_MAC, {"poet": script})
    await with_board(session, a_board("s" * 3072))
    telemetry, memory, tapped = traced(session)

    with caplog.at_level(logging.INFO):
        await run_reply(session, "how is my board?")
        await run_reply(session, "and now?")

    rounds = [fields_of(record) for record in events(caplog, "llm_round")]
    cleared = {
        "cleared_results": 1,
        "cleared_bytes": 3072,
        "cleared_largest": 3072,
        "cleared_tools": {"device": 1},
        "degraded_calls": 0,
    }
    assert [history_of(one) for one in rounds] == [NOTHING, NOTHING, cleared]
    # The user, the turn that asked, the turn that answered, what was
    # said, and the user again: `turns` counts the kept tool turns.
    assert rounds[-1]["turns"] == 5

    spans = llm_spans(telemetry, memory, tapped)
    first, _, later = (spans[one["invocation"]] for one in rounds)
    assert on_the_span(first.attributes) == NOTHING_ON_THE_SPAN
    assert on_the_span(later.attributes) == {
        "vinga.llm.history.cleared.count": 1,
        "vinga.llm.history.cleared.bytes": 3072,
        "vinga.llm.history.cleared.largest": 3072,
        "vinga.llm.history.cleared.tools.device": 1,
        "vinga.llm.history.degraded.count": 0,
    }


async def test_a_cleared_server_result_keeps_its_entry_after_the_entry_is_removed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The entry is gone from the configuration by the second reply, so
    nothing this request offers knows it; the result is counted under
    the entry its call reached all the same, and the call is degraded."""
    running = server_config(**{LONG_ANSWER_ENV: "3000"})
    servers = McpServers.build(running)
    await servers.start_all()
    script = ScriptedLlm([[call("tools__long_answer")], "That was long.", "Gone now."])
    session = session_for(base_config(), POET_MAC, {"poet": script}, mcp_servers=servers)
    telemetry, memory, tapped = traced(session)
    try:
        with caplog.at_level(logging.INFO):
            await run_reply(session, "say something long")
            await Applying(servers, running).apply(reading(base_config()))
            await run_reply(session, "and again?")
    finally:
        await servers.stop_all()

    assert script.seen[1][0][-1].tool_results[0].content == "l" * 3000
    later = fields_of(events(caplog, "llm_round")[-1])
    assert history_of(later) == {
        "cleared_results": 1,
        "cleared_bytes": 3000,
        "cleared_largest": 3000,
        "cleared_tools": {"mcp.tools": 1},
        "degraded_calls": 1,
    }
    span = llm_spans(telemetry, memory, tapped)[later["invocation"]]
    assert on_the_span(span.attributes)["vinga.llm.history.cleared.tools.mcp.tools"] == 1
    assert on_the_span(span.attributes)["vinga.llm.history.degraded.count"] == 1


class ContextLengthExceeded(Exception):
    """What a provider refusing a request over its context window
    raises, by shape: the request was built and sent, and refused."""


@pytest.mark.parametrize(
    "refusal",
    [
        pytest.param([ContextLengthExceeded("too long")], id="as-the-stream-opens"),
        pytest.param(["Let me", ContextLengthExceeded("too long")], id="mid-stream"),
    ],
)
async def test_a_refused_round_carries_what_its_history_cleared(
    refusal: list[Any], caplog: pytest.LogCaptureFixture
) -> None:
    """A context-length refusal is about exactly the request that was
    built, so its failure says what that request's history lost, by the
    route that fails before the first event and the one that fails
    after it, on the record and on the failed span."""
    script = ScriptedLlm([[call(DEVICE_STATUS)], "Your board is fine.", refusal])
    session = session_for(base_config(), POET_MAC, {"poet": script})
    await with_board(session, a_board("s" * 3072))
    telemetry, memory, tapped = traced(session)

    with caplog.at_level(logging.INFO):
        await run_reply(session, "how is my board?")
        with pytest.raises(ContextLengthExceeded):
            await run_reply(session, "and now?")

    failed = fields_of(only(caplog, "provider_failed"))
    assert failed["error"] == "ContextLengthExceeded"
    assert history_of(failed) == {
        "cleared_results": 1,
        "cleared_bytes": 3072,
        "cleared_largest": 3072,
        "cleared_tools": {"device": 1},
        "degraded_calls": 0,
    }
    span = llm_spans(telemetry, memory, tapped)[failed["invocation"]]
    assert span.status.status_code.name == "ERROR"
    assert on_the_span(span.attributes) == {
        "vinga.llm.history.cleared.count": 1,
        "vinga.llm.history.cleared.bytes": 3072,
        "vinga.llm.history.cleared.largest": 3072,
        "vinga.llm.history.cleared.tools.device": 1,
        "vinga.llm.history.degraded.count": 0,
    }


async def test_a_recap_over_a_cleared_result_carries_it_on_its_record_and_its_span(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A recap's request is built the way the plan sends it, every
    exchange past and no tool offered, over a thread holding a board
    result of 3 KiB; what it lost reaches `llm_recap` and the recap's
    `llm` span through the watch. Driven by hand rather than through a
    session, because until hydration rebuilds exchanges no recap a
    session makes has one to clear."""
    telemetry, memory = exporting()
    tapped = session_events(Clock(), telemetry)
    open_session(tapped, providers={})
    start_turn(tapped)
    conversations = SessionConversations(POET_MAC)
    conversations.activate("poet")
    watch = ProviderWatch(tapped, conversations, 1.0, None)
    made = a_thread([Pair(call(DEVICE_STATUS), ToolResult("c", "s" * 3072), "device", None)])
    sent = as_sent(made, len(made), frozenset())

    with caplog.at_level(logging.INFO):
        watch.recap_round_done(
            object(),
            sent.turns,
            asyncio.get_running_loop().time(),
            None,
            None,
            invocation="ab" * 16,
            history=sent.accounting(cleared_key),
        )

    recap = fields_of(only(caplog, "llm_round"))
    assert recap["purpose"] == "recap"
    assert history_of(recap) == {
        "cleared_results": 1,
        "cleared_bytes": 3072,
        "cleared_largest": 3072,
        "cleared_tools": {"device": 1},
        "degraded_calls": 1,
    }
    span = llm_spans(telemetry, memory, tapped)["ab" * 16]
    assert on_the_span(span.attributes) == {
        "vinga.llm.history.cleared.count": 1,
        "vinga.llm.history.cleared.bytes": 3072,
        "vinga.llm.history.cleared.largest": 3072,
        "vinga.llm.history.cleared.tools.device": 1,
        "vinga.llm.history.degraded.count": 1,
    }
