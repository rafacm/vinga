"""A conversation talking while the board under it is replaced.

The live half of #449's M4. The repository half is
`tests/unit/test_device_swap.py`; what is here is the property the
stable id was minted for, seen from inside a running session rather than
from the store: a conversation attaches to a RECORD at its connect and
goes on meaning that record, so a swap moves the record under it rather
than taking it away.

It is the exact converse of the failure M2's review round found. There,
a MAC deleted and bound again under a running conversation would have
handed that conversation the new record's name; here a record moved to
another MAC must not be lost by the conversation that is speaking
through it. Both are the same bug in opposite directions, and both are
closed by the same decision, which is that every read after the connect
is addressed by `id`.

Two claims, one per direction of the traffic:

- **The reply knows.** The round after a swap carries the same record's
  name and place, because the per-round read is by id and the id did not
  move.
- **The write lands.** `set_device_location` still writes the record the
  conversation attached to, which is now at another address, because
  `relocate_device_by_id` resolves the id to a MAC inside the
  transaction that then writes.

What is deliberately NOT claimed is anything about the hardware. A swap
is a write to a record and does not reach through the wire: the board on
the other end of this conversation goes on talking until it stops, and
the board that took its place reaches the record at its next check-in.
"""

import asyncio
import contextlib
import threading
from collections.abc import Iterator
from typing import Any, cast

import pytest
from sqlalchemy import select

from tests.support.configs import POET_MAC, base_config, world
from tests.support.providers import RecordingLlm, ScriptedLlm
from tests.support.registry import AGENT, STAGES, store_at
from tests.support.sessions import agent_providers, call, run_reply, session_for
from tests.support.stores import memory as lane_memory
from tests.support.stores import memory_rows
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.store import ConfigStore
from vinga_server.db import open_database, read_engine
from vinga_server.db import schema as domain_schema
from vinga_server.device.bindings import DeviceBindings
from vinga_server.device.placement import DevicePlacements
from vinga_server.device.session import DeviceSession
from vinga_server.memory.store import MemoryScope, MemoryStore
from vinga_server.runtime.prompt import device_introduction

NAME = "Kitchen Speaker"

LOCATION = "the kitchen"

OFFICE = "the office"

# The board the record is moved onto. Bound to nothing and remembered
# about by nobody, which is what a swap requires and what a board out of
# its box is.
FRESH_MAC = "aa:bb:cc:dd:ee:07"

# A board bound throughout and never spoken through, so a write that
# found a record rather than THE record lands somewhere visible.
BYSTANDER_MAC = "aa:bb:cc:dd:ee:08"


@contextlib.contextmanager
def placements() -> Iterator[DevicePlacements]:
    """What a server hands the runtime: the repository over the domain
    half, on an engine whoever built it disposes."""
    engine = open_database(DatabaseConfig())
    try:
        yield DevicePlacements(ConfigStore(engine))
    finally:
        engine.dispose()


def a_named_and_placed_board() -> str:
    """A board bound, named and placed in the lane's database, and the id
    its record was minted with.

    Written through the repository rather than composed in Python,
    because everything here is about a view with a real engine behind it,
    which is the shape a served deployment has.
    """
    with store_at() as store:
        for stage in STAGES:
            store.set_provider(stage, "mock", {"type": "mock"})
        store.set_agent("poet", dict(AGENT))
        store.bind_device(POET_MAC, ["poet"])
        store.rename_device(POET_MAC, NAME)
        store.relocate_device(POET_MAC, LOCATION)
        return store.read_device(POET_MAC).entry.id or ""


@contextlib.contextmanager
def a_session(script: Any, device_access: Any = None) -> Iterator[DeviceSession]:
    """A session wired the way `app.py` wires one: a live view with a
    real engine over the device rows, and, where the case is about the
    tool, the repository behind the write."""
    config = base_config()
    scripts = {"poet": script}
    generations = world(config, providers=agent_providers(config, cast(Any, scripts)))
    bindings = DeviceBindings(generations, read_engine(DatabaseConfig()))
    try:
        yield session_for(
            config,
            POET_MAC,
            cast(Any, scripts),
            generations=generations,
            devices=bindings,
            device_access=device_access,
        )
    finally:
        bindings.dispose()


async def test_a_board_swapped_mid_conversation_is_still_this_conversation_s_device(
    ) -> None:
    """The milestone from inside a reply: an operator replaces the board
    while somebody is talking to it, and the next thing the agent is told
    about its device is the same device.

    Addressed by MAC, the round after the swap would find nothing at the
    session's address and the agent would be told nothing about where it
    is; addressed by the id, it finds the record it has been speaking
    through since the connect. The prompt is what makes the difference
    observable from outside, because it is where the two facts arrive.
    """
    a_named_and_placed_board()
    llm = RecordingLlm()

    with a_session(llm) as session:
        await run_reply(session, "hello")
        with store_at() as store:
            store.replace_device(POET_MAC, FRESH_MAC)
        await run_reply(session, "where are you")

    assert llm.systems[0] == f"POET\n\n{device_introduction(NAME, LOCATION)}"
    assert llm.systems[1] == llm.systems[0]


async def test_a_swap_that_moves_a_record_away_does_not_hand_over_a_new_one() -> None:
    """The other half of the same rule, and the one a MAC-addressed read
    would get exactly backwards: the address a conversation connected on
    can be given to a DIFFERENT record while it talks.

    A swap frees the old address, an operator binds a new board there and
    names it, and the conversation in flight must go on being told about
    the record it attached to rather than about whichever record now
    answers at the address it dialled.
    """
    a_named_and_placed_board()
    llm = RecordingLlm()

    with a_session(llm) as session:
        await run_reply(session, "hello")
        with store_at() as store:
            store.replace_device(POET_MAC, FRESH_MAC)
            store.bind_device(POET_MAC, ["poet"])
            store.rename_device(POET_MAC, "Somebody Else's Speaker")
        await run_reply(session, "where are you")

    assert llm.systems[1] == f"POET\n\n{device_introduction(NAME, LOCATION)}"


async def test_the_tool_still_writes_the_record_after_its_board_was_swapped() -> None:
    """The write side of the same address. The tool relocates by the
    record's id, and the id survived the swap, so a room that says the
    speaker has moved moves the record it has been talking to, at
    whatever address that record now stands.

    Addressed by MAC this would refuse, because there is no record at the
    session's address any more, and the room would be told its device has
    to be added before it can be given a place. A second board is bound
    throughout and asserted untouched, which is what makes the claim
    about WHICH record rather than about some record: with one device in
    the store, a write that resolved the id sloppily would land on the
    right row by luck.
    """
    minted = a_named_and_placed_board()
    with store_at() as store:
        store.bind_device(BYSTANDER_MAC, ["poet"])
    script = ScriptedLlm(
        [[call("set_device_location", location=OFFICE)], "I have noted that."]
    )

    with placements() as writing, a_session(script, device_access=writing) as session:
        with store_at() as store:
            store.replace_device(POET_MAC, FRESH_MAC)
        assert await run_reply(session, "you are in the office now") == [
            "I have noted that."
        ]

    with store_at() as store:
        record = store.read_device(FRESH_MAC).entry
        bystander = store.read_device(BYSTANDER_MAC).entry
    assert record.id == minted
    assert record.location == OFFICE
    assert record.name == NAME
    assert bystander.location is None


# --- what the room told the board -------------------------------------
#
# The half a swap exists for and the half the first round of this
# milestone missed. A device's facts are filed under a MAC
# (`memory/scopes.py`), `replace_device` moves them with the record, and
# a conversation that goes on addressing the MAC it dialled would read
# an empty device scope for the rest of its life and write new notes at
# an address nothing will ever read again.


NOTE = "the kettle is loud"

OTHER_NOTE = "the window sticks in winter"

# What a room says to make the agent write one down, and what the model
# answers with afterwards. The words are the test's, not the model's:
# a scripted model says exactly what it is told to.
NOTED = "I will remember that."


def said(script: ScriptedLlm) -> list[str]:
    """What the model was handed back, in the order it asked. The shape
    `test_session_device_location.py` reads a tool result with."""
    return [
        result.content
        for turns, _, _ in script.seen
        for turn in turns
        for result in turn.tool_results
    ]

# How long a parked write is given to let a swap overtake it, which is
# the bound the M3 ordering proof uses and for the same reason: long
# enough that a swap really would get in front if nothing stopped it,
# short enough to pay once per case.
OVERTAKE_S = 0.25

# And how long anything here waits for something that should already be
# happening, which is the writer timeout every other suite waits under.
DONE_S = 15.0


async def a_note_about_the_board(mac: str = POET_MAC, fact: str = NOTE) -> int:
    """One fact filed under a board's address, the way a room's earlier
    conversation left it."""
    return await lane_memory().add(MemoryScope.DEVICE, mac, fact, agent="poet")


def notes_about(mac: str) -> list[str]:
    return [row["fact"] for row in memory_rows("facts", scope="device", owner=mac)]


async def test_what_the_board_was_told_is_still_in_the_next_prompt() -> None:
    """The read side, from inside a running reply: the notes move with
    the record, so the agent that was told them goes on being told them.

    Addressed by the session's own MAC, the second prompt would carry
    the device's name and place (those are read by id already) and an
    empty device scope, which is the shape of the bug this case exists
    to keep out: everything about the device looks right except what the
    household actually said.
    """
    a_named_and_placed_board()
    await a_note_about_the_board()
    llm = RecordingLlm()

    with a_session(llm) as session:
        await run_reply(session, "hello")
        with store_at() as configuration:
            configuration.replace_device(POET_MAC, FRESH_MAC)
        await run_reply(session, "what do you know about this room")

    assert NOTE in llm.systems[0]
    assert NOTE in llm.systems[1]


async def test_a_note_written_after_a_swap_is_filed_at_the_new_address() -> None:
    """The write side. A room says something worth keeping while the
    board under it has just been replaced, and the note has to land with
    the rest of what that device knows rather than at the address the
    swap emptied."""
    a_named_and_placed_board()
    await a_note_about_the_board()
    script = ScriptedLlm(
        [[call("remember", scope="device", text=OTHER_NOTE)], NOTED]
    )

    with placements() as writing, a_session(script, device_access=writing) as session:
        with store_at() as configuration:
            configuration.replace_device(POET_MAC, FRESH_MAC)
        assert await run_reply(session, "the window sticks in winter") == [NOTED]

    assert notes_about(FRESH_MAC) == [NOTE, OTHER_NOTE]
    assert notes_about(POET_MAC) == []


async def test_a_lookup_after_a_swap_finds_what_the_old_board_was_told() -> None:
    """`recall` reaches the moved rows, which is the one device-memory
    call that only reads: it takes the address the round resolved rather
    than holding it, because a read one round out of date is the
    staleness every per-round read here already has."""
    a_named_and_placed_board()
    await a_note_about_the_board()
    script = ScriptedLlm([[call("recall", query="kettle")], "It is loud."])

    with placements() as writing, a_session(script, device_access=writing) as session:
        with store_at() as configuration:
            configuration.replace_device(POET_MAC, FRESH_MAC)
        await run_reply(session, "what about the kettle")

    assert [NOTE in answer for answer in said(script)] == [True]


async def test_a_correction_after_a_swap_reaches_the_moved_note() -> None:
    """`update_memory` addresses a fact by the number the model read out
    of its own prompt, and looks for it in the two memories this session
    can reach. The device half of that pair has to be the record's
    address now, or the correction finds nothing and the model is told
    there is no such fact."""
    a_named_and_placed_board()
    numbered = await a_note_about_the_board()
    script = ScriptedLlm(
        [[call("update_memory", id=numbered, text=OTHER_NOTE)], NOTED]
    )

    with placements() as writing, a_session(script, device_access=writing) as session:
        with store_at() as configuration:
            configuration.replace_device(POET_MAC, FRESH_MAC)
        await run_reply(session, "no, the window sticks")

    assert notes_about(FRESH_MAC) == [OTHER_NOTE]
    assert said(script) == [f"Corrected [{numbered}]: {OTHER_NOTE}"]


async def test_forgetting_and_bringing_back_after_a_swap_reach_the_moved_note() -> None:
    """The other two, in the order a conversation makes them: a room
    asks the agent to forget something and then asks for it back.

    Both in one session across one swap, because what the pair proves is
    that the held row moved too: a soft removal leaves the fact under
    the same owner with the thread that forgot it, so a restore that
    resolved the wrong address would find nothing to bring back.
    """
    a_named_and_placed_board()
    numbered = await a_note_about_the_board()
    script = ScriptedLlm(
        [
            [call("forget", id=numbered)],
            "Forgotten.",
            [call("restore_memory")],
            "Here it is again.",
        ]
    )

    with placements() as writing, a_session(script, device_access=writing) as session:
        with store_at() as configuration:
            configuration.replace_device(POET_MAC, FRESH_MAC)
        await run_reply(session, "forget about the kettle")
        await run_reply(session, "actually, what was that about the kettle")

    assert said(script) == [f"Forgot [{numbered}]: {NOTE}", f"Brought back: {NOTE}"]
    assert notes_about(FRESH_MAC) == [NOTE]
    held = [row for row in memory_rows("facts") if row["forgotten_in"] is not None]
    assert held == []


# --- a note racing the swap -------------------------------------------


@contextlib.asynccontextmanager
async def the_note_parked(arrived: threading.Event, release: threading.Event) -> Any:
    """The device-memory write held open between its address being
    resolved and its row being written.

    The seam is `MemoryStore.add`, which is what the tool awaits INSIDE
    the block that holds the record's address still. Parking it there is
    what makes the race a scenario rather than a coincidence: the window
    this whole mechanism exists to close is exactly the one this context
    manager holds open.

    The agent scope goes through untouched, because a note about the
    agent is filed under a name no swap can move and parking one would
    be arranging a race that cannot happen.
    """
    real = MemoryStore.add

    async def add(
        self: MemoryStore, scope: MemoryScope, owner: str, fact: str, *, agent: str
    ) -> int:
        if scope is MemoryScope.DEVICE:
            arrived.set()
            await asyncio.to_thread(release.wait, OVERTAKE_S * 8)
        return await real(self, scope, owner, fact, agent=agent)

    with pytest.MonkeyPatch.context() as patching:
        patching.setattr(MemoryStore, "add", add)
        yield


async def test_a_note_racing_a_swap_is_carried_along_by_it() -> None:
    """The order that loses a fact, arranged on purpose.

    A room says something worth keeping at the moment an operator
    replaces the board. The tool resolves where this device's facts are
    filed, and the swap moves them a moment later: addressed by an
    answer that was merely READ, the note lands at the address the swap
    has just emptied and nothing ever reads it again.

    What closes it is that the answer is not merely read. The resolution
    happens inside the domain writer lock and the lock is held until the
    row is written, and a swap takes that same lock before it reads
    anything, so the two are totally ordered whichever way they arrive.
    This case pins the harder of the two orders: the note goes first,
    the swap waits for it, and the swap carries it along with everything
    else that was filed under the old address.

    The swap's failure to overtake is asserted before it is allowed to
    finish, which is what makes this a claim about the lock rather than
    about the final state: with the hold removed, the swap completes
    inside the window and the note lands under the abandoned address.
    """
    a_named_and_placed_board()
    await a_note_about_the_board()
    arrived = threading.Event()
    release = threading.Event()
    script = ScriptedLlm(
        [[call("remember", scope="device", text=OTHER_NOTE)], NOTED]
    )

    async with the_note_parked(arrived, release):
        with placements() as writing, a_session(script, device_access=writing) as session:
            reply = asyncio.create_task(run_reply(session, OTHER_NOTE))
            assert await asyncio.to_thread(arrived.wait, DONE_S), "the note never began"

            swapping = asyncio.create_task(asyncio.to_thread(a_swap))
            await asyncio.sleep(OVERTAKE_S)
            # The swap is queued on the lock this write is holding, which
            # is the whole mechanism: it has neither finished nor moved
            # the row.
            assert not swapping.done()
            assert standing_at(POET_MAC) is not None

            release.set()
            assert await reply == [NOTED]
            await swapping

    # Both notes at the new address, the older one because the swap moved
    # it and the newer one because the swap waited for it.
    assert notes_about(FRESH_MAC) == [NOTE, OTHER_NOTE]
    assert notes_about(POET_MAC) == []


def a_swap() -> None:
    """The replacement, on a worker thread and through its own engine,
    which is what an operator at a command line is while a conversation
    is happening."""
    with store_at() as configuration:
        configuration.replace_device(POET_MAC, FRESH_MAC)


def standing_at(mac: str) -> str | None:
    """The id of the record at this address, or None.

    Through the read-only, never-migrating connection rather than
    through the repository, and the difference is load-bearing HERE and
    nowhere else in this file: the repository's own read takes the
    domain writer lock, and this is asked while a parked write is
    holding it. Opening a store would also try to migrate, which is a
    lock the held transaction blocks outright.
    """
    engine = read_engine(DatabaseConfig())
    try:
        with engine.connect() as connection:
            return connection.execute(
                select(domain_schema.devices.c.id).where(
                    domain_schema.devices.c.mac == mac
                )
            ).scalar_one_or_none()
    finally:
        engine.dispose()
