"""vinga, the built-in agent, in a running conversation (#612).

What a session gives the built-in that it gives no other agent: the
build's persona, no MCP grants however the defaults grant, and a memory
that is its device's alone, so what is said to vinga on one board is
neither in the prompt nor in a lookup on another. And the other side of
the same boundary: every other agent keeps both of its fact scopes and
the grants it inherits.
"""

from typing import Any

from tests.support.configs import BOTH_MAC, POET_MAC, STDIO_SERVER, base_config, world
from tests.support.providers import RecordingLlm, ScriptedLlm, results_of
from tests.support.sessions import agent_providers, call, run_reply, session_for
from tests.support.stores import StoredThreads, a_backlog, a_candidate, memory_rows
from tests.support.stores import memory as lane_memory
from vinga_server import knowledge
from vinga_server.config import Config
from vinga_server.config.models import BUILTIN_AGENT, BuiltinStatus
from vinga_server.config.secrets import SecretStore
from vinga_server.conversations import threads
from vinga_server.generation import Generation
from vinga_server.memory.store import MemoryScope
from vinga_server.tools import builtin, names
from vinga_server.tools.mcp import McpServers

KITCHEN = "aa:bb:cc:dd:ee:21"
HALL = "aa:bb:cc:dd:ee:22"

FACT = "the kettle whistles when it boils"

# A thread the hall board began, and what was said on it, which must not
# reach the kitchen.
ELSEWHERE = "9f0c1d2e3a4b5c6d7e8f90a1b2c3d4e5"
HISTORY = (("the hall alarm code is 4417", "Noted."),)


def vinga_world(**overrides: Any) -> Config:
    """The lane's two agents with the built-in served beside them: the
    defaults leave only the voice to name, and the override names it.
    Two boards are bound to vinga and the poet's board to the poet."""
    return base_config(
        **(
            {
                "builtin_agent": {"tts": "tenor"},
                "devices": {
                    KITCHEN: [BUILTIN_AGENT],
                    HALL: [BUILTIN_AGENT],
                    POET_MAC: ["poet"],
                },
            }
            | overrides
        )
    )


def granting_world() -> Config:
    """The same world with an MCP entry every agent inherits through the
    defaults."""
    return vinga_world(
        mcp_servers={
            "tools": {
                "transport": "stdio",
                "command": __import__("sys").executable,
                "args": [str(STDIO_SERVER)],
            }
        },
        agent_defaults={"llm": "mock", "asr": "mock", "vad": "mock", "mcp": ["tools"]},
    )


# The persona and the grants


async def test_vinga_replies_under_the_build_s_persona() -> None:
    llm = RecordingLlm()
    session = session_for(vinga_world(), KITCHEN, {BUILTIN_AGENT: llm})

    await run_reply(session, "what is this?")

    (system,) = llm.systems
    assert system.startswith(knowledge.persona())


async def test_vinga_is_offered_none_of_the_tools_the_defaults_grant() -> None:
    """The `mcp` pin, at the snapshot a reply is offered: the defaults
    grant the entry, the poet inherits it, and vinga is offered none of
    its tools."""
    config = granting_world()
    servers = McpServers.build(config)
    await servers.start_all()
    vinga = ScriptedLlm(["Hello."])
    poet = ScriptedLlm(["Hello."])
    try:
        await run_reply(
            session_for(config, KITCHEN, {BUILTIN_AGENT: vinga}, mcp_servers=servers), "hi"
        )
        await run_reply(session_for(config, POET_MAC, {"poet": poet}, mcp_servers=servers), "hi")
    finally:
        await servers.stop_all()

    (offered_to_vinga,) = [{tool.name for tool in seen[1]} for seen in vinga.seen]
    (offered_to_poet,) = [{tool.name for tool in seen[1]} for seen in poet.seen]
    assert any(name.startswith("tools__") for name in offered_to_poet)
    assert not any(name.startswith("tools__") for name in offered_to_vinga)


# The memory, its device's alone


async def test_vinga_s_remember_has_no_scope_to_choose() -> None:
    vinga = ScriptedLlm(["Hello."])
    poet = ScriptedLlm(["Hello."])

    await run_reply(session_for(vinga_world(), KITCHEN, {BUILTIN_AGENT: vinga}), "hi")
    await run_reply(session_for(vinga_world(), POET_MAC, {"poet": poet}), "hi")

    def remember(script: ScriptedLlm) -> dict[str, Any]:
        (tool,) = [one for one in script.seen[0][1] if one.name == names.REMEMBER]
        return tool.input_schema["properties"]

    assert "scope" not in remember(vinga)
    assert "scope" in remember(poet)


async def test_a_fact_told_to_vinga_on_one_board_stays_on_that_board() -> None:
    """Decision 8: told on the kitchen board, even with the agent scope
    asked for, the fact is filed under the kitchen's device scope. The
    kitchen's next conversation is sent it; the hall's is not, and the
    hall's lookup does not find it."""
    store = lane_memory()
    told = ScriptedLlm([[call("remember", text=FACT, scope="agent")], "Noted."])
    await run_reply(session_for(vinga_world(), KITCHEN, {BUILTIN_AGENT: told}, store), "note it")

    kitchen = RecordingLlm()
    hall = RecordingLlm()
    looked = ScriptedLlm([[call("recall", query="kettle")], "Nothing."])
    await run_reply(session_for(vinga_world(), KITCHEN, {BUILTIN_AGENT: kitchen}, store), "hi")
    await run_reply(session_for(vinga_world(), HALL, {BUILTIN_AGENT: hall}, store), "hi")
    await run_reply(session_for(vinga_world(), HALL, {BUILTIN_AGENT: looked}, store), "kettle?")

    (row,) = [one for one in memory_rows("facts") if one["fact"] == FACT]
    assert (row["scope"], row["owner"]) == (MemoryScope.DEVICE, KITCHEN)
    assert FACT in kitchen.systems[0]
    assert FACT not in hall.systems[0]
    assert results_of(looked) == [builtin.NOTHING_MATCHED]


async def test_vinga_reads_no_agent_memory_of_its_own() -> None:
    """A fact filed under the agent scope named vinga, as the operator's
    displaced agent of that name would have left behind, is not read by
    the built-in on any board: it has no agent scope."""
    store = lane_memory()
    await store.add(MemoryScope.AGENT, BUILTIN_AGENT, FACT, agent=BUILTIN_AGENT)
    llm = RecordingLlm()
    looked = ScriptedLlm([[call("recall", query="kettle")], "Nothing."])

    await run_reply(session_for(vinga_world(), KITCHEN, {BUILTIN_AGENT: llm}, store), "hi")
    await run_reply(session_for(vinga_world(), KITCHEN, {BUILTIN_AGENT: looked}, store), "?")

    assert FACT not in llm.systems[0]
    assert results_of(looked) == [builtin.NOTHING_MATCHED]


async def test_every_other_agent_keeps_its_own_memory() -> None:
    """The other side of the boundary: the poet's own facts follow it
    and its remember still files where it is told."""
    store = lane_memory()
    await store.add(MemoryScope.AGENT, "poet", FACT, agent="poet")
    llm = RecordingLlm()

    await run_reply(session_for(vinga_world(), POET_MAC, {"poet": llm}, store), "hi")

    assert FACT in llm.systems[0]


# The threads, its device's alone


async def test_vinga_s_search_is_held_to_the_board_it_talks_through() -> None:
    """Q5: the built-in agent's threads are the deployment's, so its
    search for one to resume asks for the threads begun on this board,
    while the poet's asks for its own wherever they began."""
    config = vinga_world(server={"conversations": {"enabled": True, "resumption": True}})
    store = StoredThreads()
    vinga = ScriptedLlm([[call("resume_conversation", description="the galaxy")], "None."])
    poet = ScriptedLlm([[call("resume_conversation", description="the galaxy")], "None."])

    await run_reply(session_for(config, KITCHEN, {BUILTIN_AGENT: vinga}, threads=store), "?")
    await run_reply(session_for(config, POET_MAC, {"poet": poet}, threads=store), "?")

    assert store.asked == [(BUILTIN_AGENT, "the galaxy"), ("poet", "the galaxy")]
    assert store.held_to == [KITCHEN, None]


async def test_vinga_cannot_reach_an_agent_fact_by_its_number() -> None:
    """The numbered tools search the memories a session may reach, and
    for vinga that is its device's alone: a fact under the agent scope
    named vinga is not its to correct or forget, whatever number the
    model sends."""
    store = lane_memory()
    fact_id = await store.add(MemoryScope.AGENT, BUILTIN_AGENT, FACT, agent=BUILTIN_AGENT)
    script = ScriptedLlm(
        [[call("forget", id=fact_id), call("update_memory", id=fact_id, text="moved")], "No."]
    )

    await run_reply(session_for(vinga_world(), KITCHEN, {BUILTIN_AGENT: script}, store), "?")

    (row,) = [one for one in memory_rows("facts") if one["id"] == fact_id]
    assert row["fact"] == FACT
    assert row["forgotten_at"] is None


async def test_an_offer_held_by_a_legacy_vinga_is_not_honoured_once_the_built_in_answers() -> (
    None
):
    """Review round 1, finding 1: a session opened as an operator's
    legacy agent named vinga searches unscoped, so its offer can hold
    another device's thread. Once that row is deleted and an apply
    installs the built-in agent, the same live session speaks as the
    built-in, whose threads are its device's alone: picking the held
    thread is refused, nothing of it is read, and the offer is gone."""
    resuming = {"conversations": {"enabled": True, "resumption": True}}
    legacy = base_config(
        server=resuming,
        agents={
            "poet": {"prompt": "POET", "tts": "tenor"},
            "tutor": {"prompt": "TUTOR", "tts": "alto"},
            BUILTIN_AGENT: {"prompt": "THE OLD VINGA", "tts": "tenor"},
        },
        devices={KITCHEN: [BUILTIN_AGENT], POET_MAC: ["poet"], BOTH_MAC: ["poet", "tutor"]},
    )
    installed = vinga_world(server=resuming)
    assert legacy.builtin_state.status is BuiltinStatus.DISPLACED
    assert installed.is_builtin(BUILTIN_AGENT)
    store = StoredThreads(
        found={
            BUILTIN_AGENT: threads.Candidates(matched=True, found=(a_candidate(ELSEWHERE),))
        },
        held={ELSEWHERE: a_backlog(ELSEWHERE, agent=BUILTIN_AGENT, said=HISTORY, device=HALL)},
    )
    script = ScriptedLlm(
        [
            [call("resume_conversation", description="the galaxy")],
            "I found one.",
            [call("resume_conversation", conversation=ELSEWHERE)],
            "Never mind.",
        ]
    )
    holder = world(legacy, providers=agent_providers(legacy, {BUILTIN_AGENT: script}))
    session = session_for(
        legacy, KITCHEN, {BUILTIN_AGENT: script}, threads=store, generations=holder
    )

    await run_reply(session, "find the galaxy one")
    with holder.applying() as install:
        install(Generation(installed, SecretStore()))
    await run_reply(session, "that one")

    assert store.held_to == [None]
    assert results_of(script)[-1] == builtin.NO_SUCH_CANDIDATE
    assert store.read == []
    assert all(HISTORY[0][0] not in system for system in script.systems)
