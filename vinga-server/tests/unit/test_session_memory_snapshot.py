"""Memory read once per conversation, and kept by its key (#536).

The memory section and the device record are read when an agent starts
speaking on a conversation and kept for every later round and reply
while the snapshot's key holds. The key has five components, and each
has a test here in which only it changes; a sixth case changes nothing
and is not read again. Around them: what the model writes reaching it
as the tool results it already is, the note that marks a read with
history behind it, the hard deletion that reaches the next leg, the
reads that fail and are never kept, and what the LLM input export
carries of all of it.

Every claim is read where a caller would read it: what the provider
was handed (`systems`, `seen`), what the store answered, and how many
times it was asked, through a counting wrapper over the public read.
"""

import contextlib
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from tests.support.configs import BOTH_MAC, POET_MAC, base_config, world
from tests.support.llm_input import exporting
from tests.support.providers import ScriptedLlm
from tests.support.registry import AGENT, STAGES, store_at
from tests.support.sessions import (
    agent_providers,
    call,
    hand_over_to,
    run_reply,
    session_for,
    talking_thread,
)
from tests.support.stores import StoredThreads, memory_that_cannot_read
from tests.support.stores import memory as lane_memory
from vinga_server.config import Config
from vinga_server.config.api import build_api
from vinga_server.config.models import DatabaseConfig, normalize_mac
from vinga_server.config.store import ConfigStore, LiveDevice
from vinga_server.db import open_database, read_engine
from vinga_server.device import bindings as bindings_module
from vinga_server.device.bindings import DeviceBindings
from vinga_server.device.placement import DevicePlacements
from vinga_server.device.session import DeviceSession
from vinga_server.generation import Generation, Generations
from vinga_server.llm_input_export import LlmInputExport
from vinga_server.memory.store import MemoryScope, MemoryStore, PromptMemory
from vinga_server.providers import ToolCall, ToolDef, Turn
from vinga_server.providers.base import LlmEvent, LlmProvider, TextDelta, ToolChoice
from vinga_server.runtime.history import MAX_KEPT_RESULT_BYTES
from vinga_server.runtime.prompt import FRAMING_AT_NOTE, FRAMING_AT_START, REREAD_NOTE
from vinga_server.telemetry import GEN_AI_INPUT_MESSAGES, GEN_AI_SYSTEM_INSTRUCTIONS

FACT = "the user is vegetarian"

SECRET = "the door code is 4721"

NAME = "Kitchen Speaker"

TOKEN = "test-api-token-" + "7a3c1e9b5d2f4068" * 2

# Over the history's cap, measured as the history measures it: an
# answer quoting this is sent cleared on every later reply.
LARGE = "x" * (MAX_KEPT_RESULT_BYTES + 200)


# --- what the store was asked ---------------------------------------


def counted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every prompt read of memory, by the agent it was for, through
    the store's public read."""
    reads: list[str] = []
    real = MemoryStore.read_for_prompt

    def read(
        self: MemoryStore, agent: str, device: str | None, conversation: str | None
    ) -> PromptMemory:
        reads.append(agent)
        return real(self, agent, device, conversation)

    monkeypatch.setattr(MemoryStore, "read_for_prompt", read)
    return reads


def calls_in(turns: Sequence[Turn]) -> list[ToolCall]:
    return [one for turn in turns for one in turn.tool_calls]


def results_in(turns: Sequence[Turn]) -> list[str]:
    return [result.content for turn in turns for result in turn.tool_results]


def notes_in(turns: Sequence[Turn]) -> list[int]:
    """Where the re-read note stands in these turns."""
    return [index for index, turn in enumerate(turns) if turn.content == REREAD_NOTE]


def installed(generations: Generations, config: Config) -> None:
    """A world built from this configuration put in front of new work,
    the way an apply does."""
    current = generations.current()
    with generations.applying() as install:
        install(Generation(config, current.secrets, current.fillers, current.providers))


# --- a board the database knows -------------------------------------


def a_named_board() -> str:
    """A board bound and named in the lane's database, and its id."""
    with store_at() as store:
        for stage in STAGES:
            store.set_provider(stage, "mock", {"type": "mock"})
        store.set_agent("poet", dict(AGENT))
        store.bind_device(POET_MAC, ["poet"])
        store.rename_device(POET_MAC, NAME)
        return store.read_device(POET_MAC).entry.id or ""


@contextlib.contextmanager
def placements() -> Iterator[DevicePlacements]:
    engine = open_database(DatabaseConfig())
    try:
        yield DevicePlacements(ConfigStore(engine))
    finally:
        engine.dispose()


@contextlib.contextmanager
def on_a_stored_board(
    scripts: dict[str, Any],
    config: Config | None = None,
    device_access: Any = None,
) -> Iterator[DeviceSession]:
    """A session wired the way `app.py` wires one: a live view with a
    real engine over the device rows."""
    settings = config if config is not None else base_config()
    generations = world(settings, providers=agent_providers(settings, cast(Any, scripts)))
    view = DeviceBindings(generations, read_engine(DatabaseConfig()))
    try:
        yield session_for(
            settings,
            POET_MAC,
            cast(Any, scripts),
            generations=generations,
            devices=view,
            device_access=device_access,
        )
    finally:
        view.dispose()


# --- what the model writes reaches it as its results -----------------


async def test_the_model_s_own_writes_leave_the_prompt_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decisions 1 and 2, and plan review round 1's finding 1: a second
    round of the reply that wrote, and a second reply, are sent the
    system prompt the first round was, byte for byte, after a
    `remember`, a `forget`, a `set_state` and a `set_device_location` by
    the model. The later reply's request carries those four exchanges
    structured, which is how the model knows what changed, although
    neither its utterance nor the spoken answer repeats a value. Memory
    and the record are read once, and the erasure revision does not
    move: a soft forget and a relocation are not hard deletions."""
    a_named_board()
    store = lane_memory()
    forgotten = await store.add(MemoryScope.AGENT, "poet", FACT, agent="poet")
    reads = counted(monkeypatch)
    script = ScriptedLlm(
        [
            [
                call("remember", text="the user's sister is called Ana"),
                call("forget", id=forgotten),
                call("set_state", key="game", value="chess, white to move"),
                call("set_device_location", location="the office"),
            ],
            "Done.",
            "Sure.",
        ]
    )
    revision = store.erasures

    with placements() as written, on_a_stored_board(
        {"poet": script}, device_access=written
    ) as session:
        assert await run_reply(session, "a few things to note") == ["Done."]
        assert await run_reply(session, "what now?") == ["Sure."]

    first, second, later = script.systems
    assert FACT in first
    assert second == first
    assert later == first
    assert len(reads) == 1
    assert store.erasures == revision
    (turns, _, _) = script.seen[2]
    assert [one.name for one in calls_in(turns)] == [
        "remember",
        "forget",
        "set_state",
        "set_device_location",
    ]
    answered = results_in(turns)
    assert any("Ana" in one for one in answered)
    assert any(FACT in one for one in answered)
    assert any("chess" in one for one in answered)
    assert any("the office" in one for one in answered)
    # And nothing but those exchanges says so: the turns around them are
    # the two utterances and the reply that said "Done.".
    plain = [turn.content for turn in turns if not turn.tool_calls and not turn.tool_results]
    assert not any(word in " ".join(plain) for word in ("Ana", "chess", "office"))
    # And the snapshot is read at the start, so no note anywhere.
    assert notes_in(turns) == []
    assert FRAMING_AT_START in first


# --- each key component, alone ---------------------------------------


async def test_a_second_reply_that_changes_nothing_is_not_read_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The baseline the five cases below differ from by one value."""
    reads = counted(monkeypatch)
    script = ScriptedLlm(["One.", "Two.", "Three."])
    session = session_for(base_config(), POET_MAC, {"poet": script}, memory=lane_memory())

    for said in ("hello", "again", "and again"):
        await run_reply(session, said)

    assert len(reads) == 1
    assert script.systems[1] == script.systems[0] == script.systems[2]


async def test_a_handover_back_to_the_same_agent_reads_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The activation counter, alone: the same agent, activated again,
    on the same conversation, with the same policy and no erasure. It
    reads again, and since the thread holds turns, the note marks the
    read before the newest user turn and the framing names it (review
    round 2, finding 2: whether the note goes in is decided from the
    history, never from what moved the key)."""
    store = lane_memory()
    reads = counted(monkeypatch)
    script = ScriptedLlm(["One.", "Two.", "Three."])
    session = session_for(base_config(), POET_MAC, {"poet": script}, memory=store)
    thread = talking_thread(session)

    await run_reply(session, "hello")
    await store.add(MemoryScope.AGENT, "poet", FACT, agent="poet")
    hand_over_to(session, "poet")
    await run_reply(session, "again")
    hand_over_to(session, "poet")
    await run_reply(session, "and again")

    assert talking_thread(session) == thread
    assert len(reads) == 3
    assert FACT not in script.systems[0]
    assert FACT in script.systems[1]
    assert FRAMING_AT_NOTE in script.systems[1]
    (turns, _, _) = script.seen[1]
    assert notes_in(turns) == [len(turns) - 2]
    assert turns[-1] == Turn("user", "again")
    # One note at a time: the third read moves it rather than adding a
    # second, so the framing names one point.
    (turns, _, _) = script.seen[2]
    assert notes_in(turns) == [len(turns) - 2]
    assert turns[-1] == Turn("user", "and again")


async def test_a_rebind_to_another_conversation_reads_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The conversation, alone: the agent moves onto a new thread in
    the middle of a reply, with no activation, so only the key's thread
    changed. The leg on the new thread reads again and sees what was
    written before the move; the new thread holds only its seed, so the
    start is the read point and no note is placed."""
    store = lane_memory()
    reads = counted(monkeypatch)
    poet = ScriptedLlm(["Noted.", [call("new_conversation")], "New topic, then."])
    session = session_for(
        base_config(server={"conversations": {"enabled": True, "resumption": True}}),
        POET_MAC,
        {"poet": poet},
        threads=StoredThreads(),
        memory=store,
    )

    await run_reply(session, "we were talking about the galaxy")
    before = talking_thread(session)
    await store.add(MemoryScope.AGENT, "poet", FACT, agent="poet")
    await run_reply(session, "let us talk about something else")

    assert talking_thread(session) != before
    assert len(reads) == 2
    first, moving, landed = poet.systems
    assert moving == first
    assert FACT not in moving
    assert FACT in landed
    assert FRAMING_AT_START in landed
    assert notes_in(poet.seen[2][0]) == []


async def test_a_policy_apply_reads_again_and_marks_the_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The memory switch, alone (decision 5): an apply turning the
    agent's memory on between two replies. The next reply reads memory
    under the new policy, and the off-to-on read happens with the
    thread holding turns, so it is marked (review round 1, finding 4)."""
    store = lane_memory()
    await store.add(MemoryScope.AGENT, "poet", FACT, agent="poet")
    reads = counted(monkeypatch)
    off = base_config(
        agents={
            "poet": {"prompt": "POET", "tts": "tenor", "memory": {"enabled": False}},
            "tutor": {"prompt": "TUTOR", "tts": "alto"},
        }
    )
    script = ScriptedLlm(["One.", "Two."])
    generations = world(off, providers=agent_providers(off, {"poet": script}))
    session = session_for(off, POET_MAC, generations=generations, memory=store)

    await run_reply(session, "hello")
    installed(generations, base_config())
    await run_reply(session, "again")

    assert reads == ["poet"]
    assert script.systems[0] == "POET"
    assert FACT in script.systems[1]
    assert FRAMING_AT_NOTE in script.systems[1]
    (turns, _, _) = script.seen[1]
    assert notes_in(turns) == [len(turns) - 2]


async def test_a_hard_deletion_reads_again_and_drops_the_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The erasure revision, alone (decision 7): a fact hard-deleted
    between two replies by something other than this session. The next
    reply reads again, and the fact is no longer in its prompt; nothing
    else about the key moved."""
    store = lane_memory()
    doomed = await store.add(MemoryScope.AGENT, "poet", SECRET, agent="poet")
    reads = counted(monkeypatch)
    script = ScriptedLlm(["One.", "Two."])
    session = session_with_store(script, store)

    await run_reply(session, "hello")
    await store.forget(
        MemoryScope.AGENT, "poet", doomed, "0" * 32, agent="poet", permanently=True
    )
    await run_reply(session, "again")

    assert len(reads) == 2
    assert SECRET in script.systems[0]
    assert SECRET not in script.systems[1]


async def test_a_write_whose_answer_will_be_cleared_reads_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The oversized-write counter, alone (plan review round 3,
    amendment 2): a `set_state` whose answer is over the history's cap
    is sent cleared on the next reply, so the change would reach that
    reply neither as a result nor as the snapshot. The next reply reads
    again, and its prompt holds the ledger the write left."""
    store = lane_memory()
    reads = counted(monkeypatch)
    script = ScriptedLlm([[call("set_state", key="plan", value=LARGE)], "Noted.", "Yes."])
    session = session_with_store(script, store)

    await run_reply(session, "remember the plan")
    await run_reply(session, "what was it?")

    assert len(reads) == 2
    first, second, later = script.systems
    assert second == first
    assert LARGE not in first
    assert LARGE in later
    # And the request carried the result cleared, which is why the
    # snapshot had to carry the change.
    assert not any(LARGE in one for one in results_in(script.seen[2][0]))


def session_with_store(script: Any, store: MemoryStore) -> DeviceSession:
    return session_for(base_config(), POET_MAC, {"poet": script}, memory=store)


# --- the oversized writes the counter exists for ---------------------


async def test_a_large_forget_reaches_the_next_reply_through_the_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A soft forget publishes nothing, and a fact this large is
    quoted whole in its answer, which the next reply is sent cleared:
    the rebuilt snapshot is what tells that reply the fact is gone."""
    store = lane_memory()
    large = await store.add(MemoryScope.AGENT, "poet", LARGE, agent="poet")
    reads = counted(monkeypatch)
    script = ScriptedLlm([[call("forget", id=large)], "Forgotten.", "Yes."])
    session = session_with_store(script, store)

    await run_reply(session, "forget that")
    await run_reply(session, "is it gone?")

    assert len(reads) == 2
    assert LARGE in script.systems[0]
    assert LARGE not in script.systems[2]


async def test_a_large_restore_reaches_the_next_reply_through_the_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And the other way: a large fact brought back is quoted whole in
    `restore_memory`'s answer, so the reply after it reads again and is
    sent the fact as memory."""
    store = lane_memory()
    large = await store.add(MemoryScope.AGENT, "poet", LARGE, agent="poet")
    reads = counted(monkeypatch)
    script = ScriptedLlm(
        [
            [call("forget", id=large)],
            "Forgotten.",
            [call("restore_memory", id=large)],
            "Back.",
            "Yes.",
        ]
    )
    session = session_with_store(script, store)

    await run_reply(session, "forget that")
    await run_reply(session, "no, bring it back")
    await run_reply(session, "is it back?")

    assert len(reads) == 3
    assert LARGE not in script.systems[2]
    assert LARGE in script.systems[4]


async def test_a_small_write_does_not_read_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other side of the counter: an answer the next reply is sent
    whole moves nothing, and the reply after it is not read again."""
    reads = counted(monkeypatch)
    script = ScriptedLlm([[call("set_state", key="plan", value="a small one")], "Noted.", "Yes."])
    session = session_with_store(script, lane_memory())

    await run_reply(session, "remember the plan")
    await run_reply(session, "what was it?")

    assert len(reads) == 1
    assert script.systems[2] == script.systems[0]


# --- the read point --------------------------------------------------


async def test_a_conversation_that_starts_with_nothing_saved_is_framed_and_unmarked() -> None:
    """Plan review round 1, finding 4, from the session: the first
    reply of a fresh conversation carries the memory section with the
    framing that names the start, and no note is placed."""
    script = ScriptedLlm(["Hello."])
    session = session_with_store(script, lane_memory())

    await run_reply(session, "hello")

    (system,) = script.systems
    assert FRAMING_AT_START in system
    assert notes_in(script.seen[0][0]) == []


async def test_a_correction_between_two_activations_is_read_at_the_note() -> None:
    """The handover-back case of review round 2, finding 2, with a value
    corrected between the two activations: the poet's thread holds the
    `remember` that wrote the old value; the operator corrects it while
    the tutor is talking; the handover back reads again. The snapshot
    holds the correction, and the note stands after the old exchange,
    so the framing ranks the snapshot above it. Whether the model
    prefers the snapshot is the behavior gate's to measure."""
    store = lane_memory()
    poet = ScriptedLlm(
        [
            [call("remember", text="the meeting is on Monday")],
            [call("switch_agent", agent="tutor")],
            "It is on Tuesday.",
        ]
    )
    tutor = ScriptedLlm([[call("switch_agent", agent="poet")]])
    session = session_for(
        base_config(), BOTH_MAC, {"poet": poet, "tutor": tutor}, memory=store
    )

    await run_reply(session, "remember the meeting is on Monday and get the tutor")
    (number,) = store.read_for_prompt("poet", None, None).agent_ids
    await store.update(
        MemoryScope.AGENT, "poet", number, "the meeting is on Tuesday", agent="poet"
    )
    await run_reply(session, "back to the poet please")

    (turns, _, _) = poet.seen[-1]
    system = poet.systems[-1]
    assert "the meeting is on Tuesday" in system
    assert FRAMING_AT_NOTE in system
    exchange = next(
        index for index, turn in enumerate(turns) if any(
            "Monday" in one.content for one in turn.tool_results
        )
    )
    (note,) = notes_in(turns)
    assert exchange < note


async def test_a_deletion_between_a_result_and_its_continuation_waits_for_the_next_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 2, finding 1: a fact hard-deleted while a memory
    tool runs, between its result and the same reply's continuation
    round, changes nothing in that reply, since the leg keeps the
    snapshot it read at its first round. The next reply's first round
    reads again without the fact, and its note stands before that
    reply's user turn, after the earlier exchange."""
    store = lane_memory()
    doomed = await store.add(MemoryScope.AGENT, "poet", SECRET, agent="poet")
    real = MemoryStore.add

    async def adding_then_deleting(
        self: MemoryStore, scope: MemoryScope, owner: str, fact: str, *, agent: str
    ) -> int:
        added = await real(self, scope, owner, fact, agent=agent)
        await self.forget(
            MemoryScope.AGENT, "poet", doomed, "0" * 32, agent="poet", permanently=True
        )
        return added

    monkeypatch.setattr(MemoryStore, "add", adding_then_deleting)
    script = ScriptedLlm([[call("remember", text="the user likes tea")], "Noted.", "Yes."])
    session = session_with_store(script, store)

    await run_reply(session, "remember that I like tea")
    await run_reply(session, "anything else?")

    first, continuation, later = script.systems
    assert SECRET in first
    assert continuation == first
    assert SECRET not in later
    (turns, _, _) = script.seen[2]
    exchange = next(index for index, turn in enumerate(turns) if turn.tool_results)
    (note,) = notes_in(turns)
    assert exchange < note == len(turns) - 2


class DeletingWhenAsked(LlmProvider):
    """A model that, on the request named, has a fact hard-deleted
    while it is being asked, after its leg validated the snapshot key
    and before it answers, then asks for a tool so the leg runs a
    second round."""

    def __init__(self, delete: Callable[[], object], on_request: int) -> None:
        self._delete = delete
        self._on = on_request
        self.systems: list[str] = []

    async def stream(
        self,
        system: str,
        turns: Sequence[Turn],
        tools: Sequence[ToolDef] = (),
        tool_choice: ToolChoice = "auto",
    ) -> AsyncIterator[LlmEvent]:
        self.systems.append(system)
        if len(self.systems) == self._on:
            await cast(Any, self._delete())
            yield call("ghost_tool")
            return
        yield TextDelta("Said.")


async def test_a_deletion_after_a_cached_key_hit_is_sent_once_more_by_that_leg() -> None:
    """Plan review round 3, amendment 3, the narrowed guarantee: a leg
    whose key was validated (a cache hit) before an erasure was
    published may send the deleted fact in its remaining rounds; the
    next leg, validated after it, never does."""
    store = lane_memory()
    doomed = await store.add(MemoryScope.AGENT, "poet", SECRET, agent="poet")
    llm = DeletingWhenAsked(
        lambda: store.forget(
            MemoryScope.AGENT, "poet", doomed, "0" * 32, agent="poet", permanently=True
        ),
        on_request=2,
    )
    session = session_for(base_config(), POET_MAC, {"poet": llm}, memory=store)

    await run_reply(session, "hello")
    await run_reply(session, "again")
    await run_reply(session, "and again")

    first, hit, remaining, after = llm.systems
    assert SECRET in first
    assert hit == first
    assert remaining == first
    assert SECRET not in after


async def test_an_erasure_during_the_reads_leaves_the_key_behind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 2, finding 3: the revision is sampled before the
    reads begin and kept. An erasure published between the device read
    and the memory read (here by the memory read itself, before it
    runs) leaves the snapshot keyed with the older revision, so the next
    leg reads again; the one after that, with nothing published, does
    not."""
    store = lane_memory()
    reads: list[str] = []
    real = MemoryStore.read_for_prompt

    def read(
        self: MemoryStore, agent: str, device: str | None, conversation: str | None
    ) -> PromptMemory:
        if not reads:
            self.erased()
        reads.append(agent)
        return real(self, agent, device, conversation)

    monkeypatch.setattr(MemoryStore, "read_for_prompt", read)
    session = session_with_store(ScriptedLlm(["One.", "Two.", "Three."]), store)

    for said in ("hello", "again", "and again"):
        await run_reply(session, said)

    assert len(reads) == 2


# --- reads that did not answer ----------------------------------------


async def test_a_failed_memory_read_is_not_kept_and_the_recovery_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 6 and review round 1, finding 2: the first leg's read
    fails (a store whose reader cannot reach its database answers it),
    so that leg is sent the empty blocks with no memory section and
    nothing is kept. The next leg reads again, finds the fact, and keeps
    it: the leg after does not read."""
    store = lane_memory()
    await store.add(MemoryScope.AGENT, "poet", FACT, agent="poet")
    unreadable = memory_that_cannot_read()
    reads: list[bool] = []
    real = MemoryStore.read_for_prompt

    def read(
        self: MemoryStore, agent: str, device: str | None, conversation: str | None
    ) -> PromptMemory:
        reads.append(bool(reads))
        target = self if len(reads) > 1 else unreadable
        return real(target, agent, device, conversation)

    monkeypatch.setattr(MemoryStore, "read_for_prompt", read)
    script = ScriptedLlm(["One.", "Two.", "Three."])
    session = session_with_store(script, store)

    for said in ("hello", "again", "and again"):
        await run_reply(session, said)

    assert len(reads) == 2
    failed, recovered, kept = script.systems
    assert failed == "POET"
    assert FACT in recovered
    assert kept == recovered


async def test_an_empty_memory_that_was_read_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two empties told apart: nothing saved, read successfully, is
    a snapshot like any other and is not read again."""
    reads = counted(monkeypatch)
    script = ScriptedLlm(["One.", "Two."])
    session = session_with_store(script, lane_memory())

    await run_reply(session, "hello")
    await run_reply(session, "again")

    assert len(reads) == 1
    assert script.systems[1] == script.systems[0]


@pytest.mark.parametrize("remembering", [True, False])
async def test_a_device_read_that_fell_back_is_not_kept(
    monkeypatch: pytest.MonkeyPatch, remembering: bool
) -> None:
    """Review round 2, finding 5: the device read fails once and falls
    back to the served configuration's record, which that leg is sent;
    nothing is kept, the next leg reads again and keeps the stored
    record, whether or not the agent may remember."""
    minted = a_named_board()
    served = base_config(
        devices={
            POET_MAC: {"agents": ["poet"], "id": minted, "name": "Served Name"},
            BOTH_MAC: ["poet", "tutor"],
        },
        agents={
            "poet": {
                "prompt": "POET",
                "tts": "tenor",
                **({} if remembering else {"memory": {"enabled": False}}),
            },
            "tutor": {"prompt": "TUTOR", "tts": "alto"},
        },
    )
    failures = [RuntimeError("the database went away")]
    real = bindings_module.read_live_device_by_id
    asked: list[str] = []

    def read_by_id(engine: Any, identity: str) -> LiveDevice | None:
        asked.append(identity)
        if failures:
            raise failures.pop()
        return real(engine, identity)

    monkeypatch.setattr(bindings_module, "read_live_device_by_id", read_by_id)
    script = ScriptedLlm(["One.", "Two.", "Three."])

    with on_a_stored_board({"poet": script}, config=served) as session:
        for said in ("hello", "again", "and again"):
            await run_reply(session, said)

    fallen, recovered, kept = script.systems
    assert "Served Name" in fallen
    assert NAME in recovered
    assert kept == recovered
    assert len(asked) == 2


# --- what the LLM input export carries --------------------------------


def staging() -> tuple[LlmInputExport, Any]:
    telemetry, recorded = exporting()
    return LlmInputExport(telemetry=telemetry), recorded


def exported(recorded: Any, attribute: str) -> list[str]:
    return [attributes[attribute] for _, attributes in recorded.snapshots]


async def test_an_operator_deletion_leaves_the_export_and_the_history_keeps_its_copy(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Review round 1, finding 3, and round 2, finding 6: with
    `export_llm_input` on, an operator hard-deletes a fact through the
    memory API between two replies. The next round's exported system
    prompt no longer carries it and its id leaves the round's
    `memory_facts`; the model's own earlier `remember` exchange and a
    `recall` answer that listed it are still in the exported history,
    which is the documented behavior (the history is not memory)."""
    store = lane_memory()
    held = await store.add(MemoryScope.AGENT, "poet", SECRET, agent="poet")
    exporter, recorded = staging()
    script = ScriptedLlm(
        [
            [call("recall", query="door code")],
            "Noted.",
            "Nothing more.",
        ]
    )
    session = session_for(
        base_config(), POET_MAC, {"poet": script}, memory=store, llm_input=exporter
    )
    api = build_api(TOKEN, DatabaseConfig())
    api.state.api_runtime.memory_erased = store.erased

    with caplog.at_level("INFO"):
        await run_reply(session, "what is the door code?")
        client = TestClient(api, headers={"Authorization": f"Bearer {TOKEN}"})
        erased = client.delete(f"/memory/agents/poet/facts/{held}")
        assert erased.status_code == 200, erased.text
        await run_reply(session, "anything else?")

    systems = exported(recorded, GEN_AI_SYSTEM_INSTRUCTIONS)
    assert SECRET in systems[0]
    assert SECRET not in systems[-1]
    rounds = [one for one in caplog.records if getattr(one, "event", None) == "llm_round"]
    assert held in rounds[0].memory_facts
    assert held not in rounds[-1].memory_facts
    assert SECRET in exported(recorded, GEN_AI_INPUT_MESSAGES)[-1]


async def test_a_permanent_forget_leaves_both_live_conversations_prompts() -> None:
    """Plan review round 3, amendment 1: the model's permanent forget is
    a hard deletion, so the next leg of the session that made it, and of
    a concurrent live session holding the same fact, no longer sends or
    exports the fact in its system prompt."""
    store = lane_memory()
    doomed = await store.add(MemoryScope.AGENT, "poet", SECRET, agent="poet")
    exporter, recorded = staging()
    forgetting = ScriptedLlm(
        [[call("forget", id=doomed, permanently=True)], "Gone for good.", "Yes."]
    )
    other = ScriptedLlm(["Hello.", "Hello again."])
    originating = session_for(
        base_config(), POET_MAC, {"poet": forgetting}, memory=store, llm_input=exporter
    )
    concurrent = session_for(base_config(), POET_MAC, {"poet": other}, memory=store)

    await run_reply(concurrent, "hello")
    await run_reply(originating, "forget the door code for good")
    await run_reply(originating, "is it gone?")
    await run_reply(concurrent, "and now?")

    assert SECRET in other.systems[0]
    assert SECRET not in other.systems[1]
    assert SECRET in forgetting.systems[0]
    assert SECRET not in forgetting.systems[2]
    assert SECRET not in exported(recorded, GEN_AI_SYSTEM_INSTRUCTIONS)[-1]


async def test_the_device_scope_is_read_for_the_record_the_snapshot_holds() -> None:
    """The device scope is filed under the MAC the record stands at, so
    the snapshot is read under that address, which is the board this
    session dialled here."""
    store = lane_memory()
    await store.add(
        MemoryScope.DEVICE, normalize_mac(POET_MAC), "the kettle is loud", agent="poet"
    )
    script = ScriptedLlm(["Hello."])
    session = session_with_store(script, store)

    await run_reply(session, "hello")

    assert "the kettle is loud" in script.systems[0]
