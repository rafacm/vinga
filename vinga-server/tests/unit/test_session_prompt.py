"""What the running session sends as the system prompt, and when.

The assembler itself is `test_runtime_prompt.py`; what this file is
about is the two clocks. The know-how half (the persona, the fragments
the agent includes and the guidance of the entries it is granted) is
assembled once per
activation and cached, so a reply never rebuilds it and an agent switch
always does. The memory section has the same clock since #536: read
once per agent activation on a conversation, off the event loop, and
kept while its key holds, so what the model writes reaches it as its
tool results and what anything else writes reaches the next
conversation. The key, the note and the failures are
`test_session_memory_snapshot.py`.
"""

import asyncio
import hashlib
import threading

import pytest

from tests.support.configs import BOTH_MAC, POET_MAC, base_config
from tests.support.events import events
from tests.support.prompts import EMPTY_SECTION, FRAMED, nothing_saved
from tests.support.providers import CountingServers, RecordingLlm, ScriptedLlm
from tests.support.sessions import call, hand_over_to, run_reply, session_with, talking_thread
from tests.support.stores import memory as lane_memory
from tests.support.stores import memory_that_cannot_read
from vinga_server.config import Config
from vinga_server.events.catalog import MEMORY_FACTS_NOTE
from vinga_server.memory.store import (
    CORE_LINES,
    DEVICE_LINES,
    NOTHING_REMEMBERED,
    MemoryScope,
    MemoryStore,
    PromptMemory,
)
from vinga_server.runtime.prompt import (
    JOIN,
    MEMORY_HEADING,
    STATE_HEADING,
    Guidance,
    ServerInstructions,
    ServerPrompt,
    guidance_heading,
    know_how,
    server_instructions_heading,
    server_prompt_heading,
    with_scopes,
)

GUIDANCE = "Ask before unlocking the door."

FRAGMENT = "The bins go out on Tuesday."


# The activation cache


async def test_the_know_how_half_is_assembled_once_per_activation() -> None:
    servers = CountingServers((Guidance("home", GUIDANCE),))
    session = session_with(servers, {"poet": ScriptedLlm(["One.", "Two."])})
    assert servers.asked == ["poet"]

    await run_reply(session, "hello")
    await run_reply(session, "again")

    # Neither reply asked a second time. Assembling the half is what
    # asks, so one question is one assembly.
    assert servers.asked == ["poet"]


async def test_an_agent_switch_re_assembles_the_half() -> None:
    servers = CountingServers((Guidance("home", GUIDANCE),))
    tutor = RecordingLlm(["Hi."])
    session = session_with(
        servers,
        {
            "poet": ScriptedLlm([[call("switch_agent", agent="tutor")]]),
            "tutor": tutor,
        },
        mac=BOTH_MAC,
    )

    await run_reply(session, "get me the tutor")

    # Asked again, and what the new agent was sent is the new agent's
    # half rather than the one the activation cached for the poet.
    assert servers.asked == ["poet", "tutor"]
    (system,) = tutor.systems
    assert system.startswith("TUTOR")


async def test_the_granted_guidance_reaches_the_model() -> None:
    llm = RecordingLlm()
    session = session_with(CountingServers((Guidance("home", GUIDANCE),)), {"poet": llm})

    await run_reply(session, "hello")

    (system,) = llm.systems
    assert system.startswith("POET")
    assert "home__" in system
    assert GUIDANCE in system


async def test_the_model_receives_exactly_the_blocks_that_are_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The session's side of the surface's one promise, over the inputs
    that make a lazy assembler lie: a persona written with leading
    whitespace, and guidance whose author left blank lines at the end of
    it. What the provider was handed is the blocks joined, character for
    character, so what the surface reports is what the model read."""
    config = base_config(
        agents={
            "poet": {"prompt": "  POET  \n", "tts": "tenor"},
            "tutor": {"prompt": "TUTOR", "tts": "alto"},
        }
    )
    guidance = (Guidance("home", "  Ask first.\n\n"),)
    llm = RecordingLlm()
    with caplog.at_level("INFO"):
        session = session_with(CountingServers(guidance), {"poet": llm}, config=config)
        await run_reply(session, "hello")

    (system,) = llm.systems
    (assembled,) = prompt_events(caplog)
    # What this agent's half is, asked of the assembler that owns the
    # question rather than restated here: the session's claim is that
    # what it sent and what it reported are exactly that, and a rule
    # written out a second time would be the drift it is meant to catch.
    expected = know_how(
        config.prompt_for_agent("poet"), config.fragments_for_agent("poet"), guidance
    )
    # The round adds the memory section an agent that may remember is
    # always sent (#536), assembled by the same module.
    assert system == with_scopes(expected, NOTHING_REMEMBERED, remembering=True).text
    assert system.startswith(expected.text)
    assert assembled.characters == expected.characters
    assert assembled.sources == expected.sizes()
    # And these really are the inputs that make a lazy assembler lie:
    # the persona's own padding is gone from both ends of the prompt and
    # the guidance's interior is what its author wrote.
    assert system.startswith("POET")
    assert "Ask first." in system
    assert not system.endswith("\n")


async def test_an_agent_granted_nothing_is_sent_its_persona_alone() -> None:
    """The byte-equality case, seen from the session: with no guidance
    and nothing saved, the prompt is the agent's prompt field and the
    memory section saying nothing is saved (#536), and nothing else."""
    llm = RecordingLlm()
    session = session_with(CountingServers(), {"poet": llm})

    await run_reply(session, "hello")

    assert llm.systems == [nothing_saved("POET")]


# The fragments an agent includes


def config_with_fragment(includes: list[str] | None = None) -> Config:
    """The two agents, with a shared fragment the poet includes."""
    return base_config(
        prompt_fragments={"household": {"text": FRAGMENT}},
        agents={
            "poet": {
                "prompt": "POET",
                "tts": "tenor",
                "prompt_includes": ["household"] if includes is None else includes,
            },
            "tutor": {"prompt": "TUTOR", "tts": "alto"},
        },
    )


async def test_an_included_fragment_reaches_the_model() -> None:
    llm = RecordingLlm()
    session = session_with(
        CountingServers(), {"poet": llm}, config=config_with_fragment()
    )

    await run_reply(session, "hello")

    assert llm.systems == [nothing_saved(f"POET\n\n{FRAGMENT}")]


async def test_an_agent_that_includes_nothing_is_sent_its_persona_alone() -> None:
    """The other half of the opt-out: the fragment exists and this agent
    does not carry it."""
    llm = RecordingLlm()
    session = session_with(
        CountingServers(), {"poet": llm}, config=config_with_fragment([])
    )

    await run_reply(session, "hello")

    assert llm.systems == [nothing_saved("POET")]


async def test_activation_logs_the_fragment_beside_the_persona(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The event grows a source per injected block, so what a prompt
    held is answerable from the retained logs without the session."""
    llm = RecordingLlm()
    with caplog.at_level("INFO"):
        session = session_with(
            CountingServers((Guidance("home", GUIDANCE),)),
            {"poet": llm},
            config=config_with_fragment(),
        )
        await run_reply(session, "hello")

    (system,) = llm.systems

    (assembled,) = prompt_events(caplog)
    assert assembled.sources == {
        "persona": len("POET"),
        "fragment:household": len(FRAGMENT),
        "instructions:home": len(guidance_heading("home")) + len(f"\n{GUIDANCE}"),
    }
    assert assembled.characters == len(system) - len(JOIN + EMPTY_SECTION)


# The memory clock, which is the conversation's since #536


async def test_a_fact_another_session_saves_is_seen_from_the_next_conversation() -> None:
    """The stated cost of keeping a conversation's prompt (#536,
    decision 4): a fact saved by anything but this session's own model,
    here a concurrent session writing to the same agent's memory, is not
    in the next reply of the conversation in flight, and is in the first
    reply of the next one."""
    store = lane_memory()
    llm = RecordingLlm()
    servers = CountingServers()
    session = session_with(servers, {"poet": llm}, memory=store)

    await run_reply(session, "hello")
    await store.add(MemoryScope.AGENT, "poet", "the user is vegetarian", agent="poet")
    await run_reply(session, "again")
    later = RecordingLlm()
    await run_reply(session_with(CountingServers(), {"poet": later}, memory=store), "hi")

    assert "the user is vegetarian" not in llm.systems[0]
    assert llm.systems[1] == llm.systems[0]
    (opened,) = later.systems
    assert "the user is vegetarian" in opened
    # And the half was not rebuilt either: rebuilding is what asks the
    # registry, and it was asked once.
    assert servers.asked == ["poet"]


async def test_the_memory_read_happens_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """`MemoryStore.read_for_prompt` is a synchronous database round
    trip reached from the loop every live conversation shares, so it runs
    in a worker thread. Proven by which thread it ran on rather than by
    reading the call site.

    One read for all three scopes, and therefore one hop per round: the
    count is asserted as well as the thread, because three reads off the
    loop would cost a reply three round trips where it used to pay
    one."""
    store = lane_memory()
    await store.add(MemoryScope.AGENT, "poet", "the user is vegetarian", agent="poet")
    reads: list[int] = []
    real = MemoryStore.read_for_prompt

    def read(
        self: MemoryStore, agent: str, device: str | None, conversation: str | None
    ) -> PromptMemory:
        reads.append(threading.get_ident())
        return real(self, agent, device, conversation)

    monkeypatch.setattr(MemoryStore, "read_for_prompt", read)
    session = session_with(CountingServers(), {"poet": ScriptedLlm(["Said."])}, memory=store)

    await run_reply(session, "hello")

    assert len(reads) == 1, "the round's memory was not read exactly once"
    assert all(where != threading.get_ident() for where in reads)


async def test_two_rounds_of_one_reply_are_sent_the_memory_read_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pin of what two rounds sent before #536, inverted with it:
    memory is read once, at the leg's first round, and the round after a
    `remember` is sent the same system prompt byte for byte, so the
    provider's prompt cache survives the write. The new fact reaches
    that round as the result the `remember` answered, in its history."""
    store = lane_memory()
    reads: list[str] = []
    real = MemoryStore.read_for_prompt

    def read(
        self: MemoryStore, agent: str, device: str | None, conversation: str | None
    ) -> PromptMemory:
        reads.append(agent)
        return real(self, agent, device, conversation)

    monkeypatch.setattr(MemoryStore, "read_for_prompt", read)
    script = ScriptedLlm([[call("remember", text="the user is vegetarian")], "Noted."])
    session = session_with(CountingServers(), {"poet": script}, memory=store)

    await run_reply(session, "remember that I am vegetarian")

    first, second = script.systems
    assert "the user is vegetarian" not in first
    assert second == first
    assert len(reads) == 1
    (result,) = [
        one.content for one in script.seen[1][0][-1].tool_results
    ]
    assert "the user is vegetarian" in result


async def test_a_lookup_happens_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`recall` is the other synchronous database read a reply can make,
    and the only one a model decides to make: it runs in a worker thread
    for the same reason the prompt's read does, and the thread it ran on
    is what says so.

    A lookup on the loop would stop every other conversation in this
    process for the length of a query, which is exactly the failure a
    tool nobody predicted the timing of should not be able to cause.
    """
    store = lane_memory()
    await store.add(MemoryScope.AGENT, "poet", "the user likes cheese", agent="poet")
    lookups: list[int] = []
    real = MemoryStore.recall

    def looked_up(self: MemoryStore, agent: str, device: str, query: str) -> str:
        lookups.append(threading.get_ident())
        return real(self, agent, device, query)

    monkeypatch.setattr(MemoryStore, "recall", looked_up)
    script = ScriptedLlm([[call("recall", query="cheese")], "You like cheese."])
    session = session_with(CountingServers(), {"poet": script}, memory=store)

    assert await run_reply(session, "what do you know?") == ["You like cheese."]

    assert len(lookups) == 1
    assert all(where != threading.get_ident() for where in lookups)


async def test_an_agent_that_remembers_nothing_is_told_nothing_is_saved() -> None:
    """There is no session without a store any more (#314), and an empty
    store is what a deployment that has stored nothing has: the half the
    activation assembled, then the memory section saying nothing is saved
    yet, framing first, so the model knows what its memory tools'
    results are newer than (#536, plan review round 1, finding 4)."""
    config = base_config()
    llm = RecordingLlm()
    servers = CountingServers()
    session = session_with(servers, {"poet": llm}, config=config)

    await run_reply(session, "hello")

    # Nothing was appended to the half, and the half was assembled once:
    # a rebuild is what asks the registry, and it was asked at the
    # activation and not again.
    assert llm.systems == [
        nothing_saved(
            know_how(config.prompt_for_agent("poet"), config.fragments_for_agent("poet")).text
        )
    ]
    assert servers.asked == ["poet"]


# The ledger's clock, which is the memory section's


async def test_a_fresh_activation_starts_with_an_empty_ledger() -> None:
    """State is the thread's, and a new session mints a new thread. So
    the second conversation on the same device with the same agent
    begins with nothing written down, which is what "it dies with its
    conversation" means from the user's side."""
    store = lane_memory()
    first = session_with(CountingServers(), {"poet": RecordingLlm()}, memory=store)
    thread = talking_thread(first)
    assert thread is not None
    await store.set_state(thread, "scene", "the tavern", agent="poet")

    llm = RecordingLlm()
    second = session_with(CountingServers(), {"poet": llm}, memory=store)
    assert talking_thread(second) != thread
    await run_reply(second, "hello")

    (system,) = llm.systems
    assert STATE_HEADING not in system
    assert "the tavern" not in system


# The event


def prompt_events(caplog: pytest.LogCaptureFixture) -> list:
    return [
        record for record in caplog.records if getattr(record, "event", None) == "prompt_assembled"
    ]


async def test_activation_logs_what_the_know_how_half_holds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = lane_memory()
    await store.add(MemoryScope.AGENT, "poet", "the user is vegetarian", agent="poet")
    config = base_config()
    guidance = (Guidance("home", GUIDANCE),)
    llm = RecordingLlm()
    with caplog.at_level("INFO"):
        session = session_with(
            CountingServers(guidance), {"poet": llm}, memory=store, config=config
        )
        await run_reply(session, "hello")

    (system,) = llm.systems
    (assembled,) = prompt_events(caplog)
    assert assembled.agent == "poet"
    # The event reports this agent's half exactly, sizes and total.
    expected = know_how(
        config.prompt_for_agent("poet"), config.fragments_for_agent("poet"), guidance
    )
    assert assembled.characters == expected.characters
    assert assembled.sources == expected.sizes()
    # The half is the prompt's opening and the memory block follows it:
    # in what the model read, and outside what the event counts.
    assert system.startswith(expected.text)
    assert "vegetarian" not in expected.text
    assert "vegetarian" in system[expected.characters :]
    # Memory is deliberately absent, every scope of it: this fires once
    # per activation and memory is read per round, and the event carries
    # neither a size nor a word of what any of them holds.
    assert not {"memory", "state", "device"} & set(assembled.sources)
    assert "vegetarian" not in str(assembled.__dict__)


async def test_the_event_counts_the_server_shipped_blocks_without_quoting_them(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The two provenances a server's own guidance arrives under, sized
    in the event the way every other block is, and the bytes nowhere
    near it: this record lands in the JSON log a deployment collects."""
    shipped = "Call list_devices before anything else."
    published = "Answer in short sentences."
    with caplog.at_level("INFO"):
        session = session_with(
            CountingServers(
                (
                    ServerInstructions("home", shipped),
                    ServerPrompt("home", 1, "house_style", published),
                )
            ),
            {"poet": ScriptedLlm(["Said."])},
        )
        await run_reply(session, "hello")

    (assembled,) = prompt_events(caplog)
    assert set(assembled.sources) == {
        "persona",
        "server_instructions:home",
        "server_prompt:home:1",
    }
    assert assembled.sources["server_prompt:home:1"] == len(
        server_prompt_heading("home")
    ) + len(f"\n{published}")
    written = "".join(record.getMessage() for record in caplog.records) + str(
        assembled.__dict__
    )
    assert shipped not in written and published not in written
    assert "house_style" not in written


# The fingerprint (#533): the SHA-256 of the know-how half exactly as
# sent, so two sessions on one prompt compare equal, and an edit that
# keeps the length still shows.


def digest_of(text: str) -> str:
    """What a reader computes from the text, with the standard library
    and nothing of this server's."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def persona_config(persona: str) -> Config:
    return base_config(
        agents={
            "poet": {"prompt": persona, "tts": "tenor"},
            "tutor": {"prompt": "TUTOR", "tts": "alto"},
        }
    )


def assembled_digest(
    caplog: pytest.LogCaptureFixture,
    config: Config | None = None,
    servers: object = None,
) -> str:
    """The digest one fresh activation's `prompt_assembled` carries."""
    caplog.clear()
    with caplog.at_level("INFO"):
        session_with(
            servers if servers is not None else CountingServers(),  # type: ignore[arg-type]
            {"poet": ScriptedLlm(["Said."])},
            config=config,
        )
    (assembled,) = prompt_events(caplog)
    return assembled.sha256


async def test_activation_logs_the_digest_of_exactly_the_know_how_half(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The whole half, the server-shipped guidance included, as the
    model received it at the head of its system prompt."""
    config = base_config()
    guidance = (Guidance("home", GUIDANCE), ServerInstructions("home", "Call list_devices first."))
    llm = RecordingLlm()
    with caplog.at_level("INFO"):
        session = session_with(CountingServers(guidance), {"poet": llm}, config=config)
        await run_reply(session, "hello")

    (system,) = llm.systems
    (assembled,) = prompt_events(caplog)
    expected = know_how(
        config.prompt_for_agent("poet"), config.fragments_for_agent("poet"), guidance
    )
    assert system.startswith(expected.text)
    assert "server_instructions:home" in assembled.sources
    assert assembled.sha256 == digest_of(expected.text)


async def test_a_persona_edit_that_keeps_the_length_changes_the_digest(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The case the size alone cannot see."""
    before = assembled_digest(caplog, persona_config("Be brief."))
    after = assembled_digest(caplog, persona_config("Be fierce"))

    assert len("Be brief.") == len("Be fierce")
    assert before != after


async def test_two_activations_on_one_prompt_carry_one_digest(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two sessions, two threads, one prompt: one value, which is what
    makes the digest a thing to group sessions by."""
    assert assembled_digest(caplog) == assembled_digest(caplog)


async def test_a_change_to_server_shipped_text_changes_the_digest(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """MCP-supplied blocks are in the half the model reads, so they are
    in what the digest covers, and a server that changes its
    instructions changes the prompt even where the length holds."""
    early = assembled_digest(
        caplog, servers=CountingServers((ServerInstructions("home", "Call list_devices early."),))
    )
    first = assembled_digest(
        caplog, servers=CountingServers((ServerInstructions("home", "Call list_devices first."),))
    )

    assert len("early") == len("first")
    assert early != first


async def test_the_shipped_guidance_reaches_the_model() -> None:
    """Under a heading that says the server is the one talking, which is
    the trust boundary made legible to the one reader that cannot see a
    provenance."""
    llm = RecordingLlm()
    session = session_with(
        CountingServers((ServerInstructions("home", "Call list_devices first."),)),
        {"poet": llm},
    )

    await run_reply(session, "hello")

    (system,) = llm.systems
    assert server_instructions_heading("home") in system
    assert "Call list_devices first." in system


async def test_a_switch_logs_the_half_it_assembled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO"):
        session = session_with(
            CountingServers(),
            {
                "poet": ScriptedLlm([[call("switch_agent", agent="tutor")]]),
                "tutor": ScriptedLlm(["Hi."]),
            },
            mac=BOTH_MAC,
        )
        await run_reply(session, "get me the tutor")

    assert [record.agent for record in prompt_events(caplog)] == ["poet", "tutor"]


async def test_one_reply_logs_no_second_assembly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The event fires where the assembly happens, so a reply of several
    rounds is one activation and one record."""
    script = ScriptedLlm([[call("ghost_tool")], "Answered anyway."])
    session = session_with(CountingServers(), {"poet": script})
    with caplog.at_level("INFO"):
        await run_reply(session, "hello")

    assert len(script.seen) > 1
    assert prompt_events(caplog) == []


async def test_the_event_survives_a_session_built_off_the_loop() -> None:
    """A runtime is built inside the connect handler today, and the
    event fires from a synchronous method: nothing about it may need a
    running loop, or a change of call site would turn an activation into
    a traceback."""
    config = base_config()
    await asyncio.to_thread(session_with, CountingServers(), None, None, POET_MAC, config)


# What a round says about the prompt it sent (#533)


def with_poet(poet: dict[str, object]) -> Config:
    """The lane's two agents, with the poet's entry replaced by the one
    the case is about."""
    return base_config(
        agents={
            "poet": {"tts": "tenor", **poet},
            "tutor": {"prompt": "TUTOR", "tts": "alto"},
        }
    )


async def test_every_round_repeats_the_snapshot_s_accounting_until_it_is_read_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """#536, decision 8: a round reports the prompt it actually sent,
    so with the snapshot kept the round after a `remember` repeats the
    first round's fact ids and sizes, the new fact being in its history
    rather than its prompt. The sizes are asserted against the string
    the model was handed, two scope blocks and the framing included. A
    read the key asks for (here an activation) is where the new fact's
    id joins the list."""
    store = lane_memory()
    known = await store.add(MemoryScope.AGENT, "poet", "the user likes tea", agent="poet")
    script = ScriptedLlm(
        [[call("remember", text="the user is vegetarian")], "Noted.", "Hello again."]
    )
    session = session_with(CountingServers(), {"poet": script}, memory=store)
    thread = talking_thread(session)
    assert thread is not None
    await store.set_state(thread, "scene", "the tavern", agent="poet")

    with caplog.at_level("INFO"):
        await run_reply(session, "remember that I am vegetarian")
        hand_over_to(session, "poet")
        await run_reply(session, "hello")

    remembered = next(
        one for one in store.read_for_prompt("poet", None, None).agent_ids if one != known
    )
    before, after, reread = events(caplog, "llm_round")
    assert before.memory_facts == after.memory_facts == [known]
    assert reread.memory_facts == [known, remembered]
    for rounded, system in zip((before, after, reread), script.systems, strict=True):
        assert rounded.system_characters == len(system)
        assert system.startswith("POET\n\n")
        assert rounded.memory_characters == len(system) - len("POET")
    assert script.systems[1] == script.systems[0]
    assert (after.memory_characters, after.memory_sources) == (
        before.memory_characters,
        before.memory_sources,
    )
    assert set(after.memory_sources) == {"state", "memory"}
    assert after.memory_characters == sum(after.memory_sources.values()) + 2 * len("\n\n")


async def test_a_round_with_memory_off_carries_its_sizes_and_no_fact_list(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = lane_memory()
    await store.add(MemoryScope.AGENT, "poet", "the user is vegetarian", agent="poet")
    llm = RecordingLlm()
    config = with_poet({"prompt": "POET", "memory": {"enabled": False}})
    session = session_with(CountingServers(), {"poet": llm}, memory=store, config=config)

    with caplog.at_level("INFO"):
        await run_reply(session, "hello")

    (rounded,) = events(caplog, "llm_round")
    assert llm.systems == ["POET"]
    assert rounded.system_characters == len("POET")
    assert rounded.memory_characters == 0
    assert rounded.memory_sources == {}
    assert not hasattr(rounded, "memory_facts")


async def test_a_round_whose_memory_read_failed_names_no_fact(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The model saw no fact, so the list is empty rather than absent:
    the read was attempted, and its failure is `memory_unreadable`'s to
    report."""
    llm = RecordingLlm()
    session = session_with(CountingServers(), {"poet": llm}, memory=memory_that_cannot_read())

    with caplog.at_level("INFO"):
        await run_reply(session, "hello")

    (rounded,) = events(caplog, "llm_round")
    assert rounded.memory_facts == []
    assert rounded.system_characters == len(llm.systems[0])
    assert events(caplog, "memory_unreadable")


async def test_the_scopes_are_counted_as_sent_after_a_persona_that_was_trimmed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Plan review round 4's regression: a persona with leading
    whitespace is sent untouched alone and trimmed once a block follows
    it, so the know-how half is not a prefix of this round's prompt.
    What the scopes added is still exactly the tail the model got."""
    store = lane_memory()
    await store.add(MemoryScope.AGENT, "poet", "the user is vegetarian", agent="poet")
    llm = RecordingLlm()
    config = with_poet({"prompt": "   POET"})
    session = session_with(CountingServers(), {"poet": llm}, memory=store, config=config)

    with caplog.at_level("INFO"):
        await run_reply(session, "hello")

    (system,) = llm.systems
    (rounded,) = events(caplog, "llm_round")
    tail = f"\n\n{FRAMED}{MEMORY_HEADING}\n- the user is vegetarian"
    assert system == "POET" + tail
    assert rounded.memory_characters == len(tail)
    assert rounded.system_characters == len(system)


async def test_the_digest_is_of_the_half_as_sent_ahead_of_a_scope(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The external review's regression on #533's digest. A lone
    persona is sent untrimmed, and once a scope block follows it loses
    its leading whitespace, so `"   POET"` and `"POET"` send the model
    byte-identical prompts in every round that reads memory. The digest
    is of the half's canonical rendering, the bytes it contributes
    whenever another block follows it: here exactly the know-how prefix
    of the system string the provider received, and the same for both
    spellings."""
    store = lane_memory()
    await store.add(MemoryScope.AGENT, "poet", "the user is vegetarian", agent="poet")
    tail = f"\n\n{FRAMED}{MEMORY_HEADING}\n- the user is vegetarian"
    digests: list[str] = []
    systems: list[str] = []
    for persona in ("   POET", "POET"):
        llm = RecordingLlm()
        caplog.clear()
        with caplog.at_level("INFO"):
            session = session_with(
                CountingServers(),
                {"poet": llm},
                memory=store,
                config=with_poet({"prompt": persona}),
            )
            await run_reply(session, "hello")
        (assembled,) = prompt_events(caplog)
        (system,) = llm.systems
        assert system.endswith(tail)
        digests.append(assembled.sha256)
        systems.append(system)

    assert systems[0] == systems[1]
    assert digests[0] == digest_of(systems[0][: -len(tail)])
    assert digests[0] == digests[1]


async def test_a_round_with_every_scope_at_its_cap_is_still_accepted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decision 9's bound, through the production path: an agent block
    at `CORE_LINES` and a device scope at `DEVICE_LINES` give a round
    whose id list is the whole of both, and nothing on the event's way
    refuses a list that long."""
    store = lane_memory()
    for index in range(CORE_LINES):
        await store.add(MemoryScope.AGENT, "poet", f"fact {index}", agent="poet")
    for index in range(DEVICE_LINES):
        await store.add(MemoryScope.DEVICE, POET_MAC, f"note {index}", agent="poet")
    session = session_with(CountingServers(), {"poet": RecordingLlm()}, memory=store)

    with caplog.at_level("INFO"):
        await run_reply(session, "hello")

    (rounded,) = events(caplog, "llm_round")
    assert len(rounded.memory_facts) == CORE_LINES + DEVICE_LINES
    assert events(caplog, "construction_failed") == []


def test_the_fact_list_s_bound_is_stated_as_the_store_sets_it() -> None:
    """The catalog cannot import the store's constants (the store emits
    events), so its note states the numbers, and this holds them to the
    constants they come from."""
    assert f"at most {CORE_LINES + DEVICE_LINES}" in MEMORY_FACTS_NOTE
    assert f"newest {CORE_LINES}" in MEMORY_FACTS_NOTE
    assert f"cap of {DEVICE_LINES}" in MEMORY_FACTS_NOTE
