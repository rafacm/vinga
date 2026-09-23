"""What a consumer sees of every record a round's tool calls produce.

Pins, written before tool execution moved out of the runtime (#482) and
held byte-unchanged across the move. Each one asserts a record whole in
the dimensions a consumer reads: its channel and level, the unrendered
sentence, the arguments as typed values, and the structured payload's
keys and values. A time is pinned by its type and its presence rather
than by a value, since it is a measurement of the run.

What the neighbouring suites already hold is not repeated. The driver
suite (`test_event_baseline.py`) holds each path to its variant and its
key set, `test_event_surface_pins.py` and the no-leak cases in
`test_session_tools.py` hunt sentinels, and `test_session_record.py`
holds the reservation and the executed row for every branch there is.
This file adds the values: which sentence, which arguments in which
order, and what each field says.

Four sites, each in every shape it has: `tool_call` for a builtin, a
server tool and a name it may not print; `sentence_withheld` for the
same three; `tool_arguments_coerced`; and the plain warning about
arguments that were not an object, whose name fragment follows the
same policy. The last case is the attribution: what those records say
about the agent and the thread after a handover, which is the agent
that made the call and not the one the session opened with.
"""

import json
import logging
import sys
from typing import Any

import pytest

from tests.support.configs import BOTH_MAC, POET_MAC, STDIO_SERVER, base_config
from tests.support.events import events, fields_of
from tests.support.providers import ScriptedLlm
from tests.support.sessions import (
    call,
    events_of,
    run_reply,
    session_for,
    talking_thread,
)
from vinga_server.config import Config
from vinga_server.providers import ToolCall
from vinga_server.tools.mcp import McpServers

CHANNEL = "vinga_server.session"

TOOL_CALL = "session %s: %s tool%s took %.2f s%s"
WITHHELD = (
    "session %s: a sentence shaped like a call to a %s tool%s was not spoken "
    "(%d characters)"
)
COERCED = (
    "session %s: %s tool%s was called with %d argument(s) whose types the "
    "schema declares otherwise, converted for the call"
)
UNPARSEABLE = "session %s: %s tool%s got %d characters of unparseable arguments"

# A leaked call to a builtin every agent here is offered, one naming the
# server tool below, and one naming no tool whose keys fit two offered
# builtins (`remember` and `update_memory` both declare `text`), which
# is the leak that is withheld as `unknown`.
LEAK_BUILTIN = json.dumps({"name": "remember", "arguments": {"text": "I like tea"}})
LEAK_MCP = json.dumps({"name": "tools__secret_word", "arguments": {}})
LEAK_AMBIGUOUS = json.dumps({"text": "I like tea"})


def server_config() -> Config:
    """One MCP entry, `tools`, granted to the poet."""
    return base_config(
        mcp_servers={
            "tools": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(STDIO_SERVER)],
            }
        },
        agents={
            "poet": {"prompt": "POET", "tts": "tenor", "mcp": ["tools"]},
            "tutor": {"prompt": "TUTOR", "tts": "alto"},
        },
    )


def assert_timed(record: logging.LogRecord, sentence: tuple[Any, ...]) -> None:
    """A `tool_call` record's arguments, with the one measured value
    held to its type: the seconds the call took, which the sentence
    renders, sit fourth."""
    assert record.args is not None
    said = tuple(record.args)
    assert len(said) == 5
    assert type(said[3]) is float and said[3] >= 0
    assert said[:3] + said[4:] == sentence


def payload(record: logging.LogRecord) -> dict[str, object]:
    """The structured half, with the measured duration held to its type
    and then set aside, so the rest compares by equality."""
    fields = dict(fields_of(record))
    took = fields.pop("duration_ms", None)
    if took is not None:
        assert type(took) is int and took >= 0
    return fields


def emitted(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    """One event's records, each held to the session channel and INFO."""
    found = events(caplog, name)
    assert found, f"no {name} record, so this proves nothing"
    for record in found:
        assert (record.name, record.levelno) == (CHANNEL, logging.INFO)
    return found


def unparseable(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The plain warnings about arguments that were not an object, in the
    order they were written."""
    found = [record for record in caplog.records if record.msg == UNPARSEABLE]
    for record in found:
        assert (record.name, record.levelno) == (CHANNEL, logging.WARNING)
        # A plain line and not an event: nothing structured rides it.
        assert fields_of(record) == {}
    return found


async def test_a_builtin_and_a_name_nobody_publishes_are_reported_as_they_are(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`tool_call` in the shape that names its tool and the shape that
    names nothing, beside the warning for a builtin's and an unknown
    name's unparseable arguments."""
    script = ScriptedLlm(
        [
            [
                call("remember", text="a fact"),
                call("ghost_tool"),
                ToolCall(id="c-b", name="remember", malformed_arguments="{oops"),
                ToolCall(id="c-g", name="ghost_tool", malformed_arguments="{o"),
            ],
            "Done.",
        ]
    )
    session = session_for(base_config(), POET_MAC, {"poet": script})
    said = events_of(session).session_id
    thread = talking_thread(session)
    with caplog.at_level("DEBUG"):
        await run_reply(session, "do it")

    # In the order they finished, which for these four is the order the
    # ordered write and then the concurrent rest complete in; matched by
    # what they say rather than by that order.
    called = emitted(caplog, "tool_call")
    assert len(called) == 4
    base = {
        "event": "tool_call",
        "session": said,
        "device": POET_MAC,
        "agent": "poet",
        "conversation": thread,
    }
    remembered = [one for one in called if fields_of(one).get("is_error") is False]
    (ran,) = remembered
    assert ran.msg == TOOL_CALL
    assert_timed(ran, (said, "builtin", ' "remember"', ""))
    assert payload(ran) == base | {"source": "builtin", "tool": "remember", "is_error": False}

    refused_builtin = [
        one for one in called if one not in remembered and fields_of(one)["source"] == "builtin"
    ]
    (malformed,) = refused_builtin
    assert malformed.msg == TOOL_CALL
    assert_timed(malformed, (said, "builtin", ' "remember"', " and failed"))
    assert payload(malformed) == base | {
        "source": "builtin",
        "tool": "remember",
        "is_error": True,
        "error": "tool_error",
    }

    nobody = [one for one in called if fields_of(one)["source"] == "unknown"]
    assert len(nobody) == 2
    for one in nobody:
        assert one.msg == TOOL_CALL
        assert_timed(one, (said, "unknown", "", " and failed"))
        assert payload(one) == base | {
            "source": "unknown",
            "is_error": True,
            "error": "tool_error",
        }

    builtin_line, unknown_line = unparseable(caplog)
    assert builtin_line.args == (said, "builtin", ' "remember"', 5)
    assert unknown_line.args == (said, "unknown", "", 2)


async def test_a_server_tool_is_reported_by_its_entry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The shape that names the configured entry and never the far
    side's own name, on all three records that can carry it."""
    servers = McpServers.build(server_config())
    await servers.start_all()
    script = ScriptedLlm(
        [
            [
                call("tools__secret_word"),
                ToolCall(id="c-m", name="tools__secret_word", malformed_arguments="{x"),
            ],
            f"{LEAK_MCP}\nDone.",
        ]
    )
    session = session_for(base_config(), POET_MAC, {"poet": script}, mcp_servers=servers)
    said = events_of(session).session_id
    thread = talking_thread(session)
    try:
        with caplog.at_level("DEBUG"):
            await run_reply(session, "ask the server")
    finally:
        await servers.stop_all()

    base = {"session": said, "device": POET_MAC, "agent": "poet", "conversation": thread}
    called = emitted(caplog, "tool_call")
    (ran,) = [one for one in called if fields_of(one)["is_error"] is False]
    assert ran.msg == TOOL_CALL
    assert_timed(ran, (said, "mcp", ' from entry "tools"', ""))
    assert payload(ran) == base | {
        "event": "tool_call",
        "source": "mcp",
        "entry": "tools",
        "is_error": False,
    }
    (refused,) = [one for one in called if fields_of(one)["is_error"] is True]
    assert_timed(refused, (said, "mcp", ' from entry "tools"', " and failed"))
    assert payload(refused) == base | {
        "event": "tool_call",
        "source": "mcp",
        "entry": "tools",
        "is_error": True,
        "error": "tool_error",
    }

    (line,) = unparseable(caplog)
    assert line.args == (said, "mcp", ' from entry "tools"', 2)

    (withheld,) = emitted(caplog, "sentence_withheld")
    assert withheld.msg == WITHHELD
    assert withheld.args == (said, "mcp", ' from entry "tools"', len(LEAK_MCP))
    assert fields_of(withheld) == base | {
        "event": "sentence_withheld",
        "source": "mcp",
        "entry": "tools",
        "characters": len(LEAK_MCP),
    }


async def test_a_withheld_builtin_and_an_ambiguous_leak_are_reported_as_they_are(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`sentence_withheld` in the shape that names a builtin and the
    shape that names nothing, one sentence each, in the order spoken."""
    script = ScriptedLlm([f"{LEAK_BUILTIN}\n{LEAK_AMBIGUOUS}\nDone."])
    session = session_for(base_config(), POET_MAC, {"poet": script})
    said = events_of(session).session_id
    thread = talking_thread(session)
    with caplog.at_level("DEBUG"):
        assert await run_reply(session, "remember that I like tea") == ["Done."]

    base = {
        "event": "sentence_withheld",
        "session": said,
        "device": POET_MAC,
        "agent": "poet",
        "conversation": thread,
    }
    named, unnamed = emitted(caplog, "sentence_withheld")
    assert named.msg == unnamed.msg == WITHHELD
    assert named.args == (said, "builtin", ' "remember"', len(LEAK_BUILTIN))
    assert fields_of(named) == base | {
        "source": "builtin",
        "tool": "remember",
        "characters": len(LEAK_BUILTIN),
    }
    assert unnamed.args == (said, "unknown", "", len(LEAK_AMBIGUOUS))
    assert fields_of(unnamed) == base | {
        "source": "unknown",
        "characters": len(LEAK_AMBIGUOUS),
    }


async def test_a_corrected_call_is_reported_with_its_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`tool_arguments_coerced` in the shape that names its tool, which
    is a builtin's: `forget` declares `id` an integer and the model
    quoted it."""
    script = ScriptedLlm([[call("forget", id="3")], "Done."])
    session = session_for(base_config(), POET_MAC, {"poet": script})
    said = events_of(session).session_id
    thread = talking_thread(session)
    with caplog.at_level("DEBUG"):
        await run_reply(session, "forget the third")

    (coerced,) = emitted(caplog, "tool_arguments_coerced")
    assert coerced.msg == COERCED
    assert coerced.args == (said, "builtin", ' "forget"', 1)
    assert fields_of(coerced) == {
        "event": "tool_arguments_coerced",
        "session": said,
        "device": POET_MAC,
        "agent": "poet",
        "conversation": thread,
        "source": "builtin",
        "tool": "forget",
        "coerced": 1,
    }


async def test_after_a_handover_every_record_names_the_agent_that_called(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The pair is read when each record is made, so the tutor's calls,
    corrections and leaks are the tutor's, on the tutor's thread. A
    record that took the pair when the session opened, or when the
    first agent's round began, would name the poet on all three."""
    poet = ScriptedLlm([[call("switch_agent", agent="tutor")]])
    tutor = ScriptedLlm(
        [
            [call("forget", id="3")],
            f"{LEAK_BUILTIN}\nDone.",
        ]
    )
    session = session_for(base_config(), BOTH_MAC, {"poet": poet, "tutor": tutor})
    first = talking_thread(session)
    with caplog.at_level("DEBUG"):
        await run_reply(session, "the tutor please")
    tutors = talking_thread(session)
    assert tutors is not None and tutors != first

    records = [
        *emitted(caplog, "tool_call"),
        *emitted(caplog, "tool_arguments_coerced"),
        *emitted(caplog, "sentence_withheld"),
    ]
    # The switch itself is a move and emits no `tool_call`; the one
    # `tool_call` here is the tutor's `forget`.
    assert [fields_of(one)["event"] for one in records] == [
        "tool_call",
        "tool_arguments_coerced",
        "sentence_withheld",
    ]
    for one in records:
        assert (fields_of(one)["agent"], fields_of(one)["conversation"]) == (
            "tutor",
            tutors,
        )
