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

import contextlib
from collections.abc import Iterator
from typing import Any, cast

from tests.support.configs import POET_MAC, base_config, world
from tests.support.providers import RecordingLlm, ScriptedLlm
from tests.support.registry import AGENT, STAGES, store_at
from tests.support.sessions import agent_providers, call, run_reply, session_for
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.store import ConfigStore
from vinga_server.db import open_database, read_engine
from vinga_server.device.bindings import DeviceBindings
from vinga_server.device.placement import DevicePlacements
from vinga_server.device.session import DeviceSession
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
def a_session(script: Any, relocations: Any = None) -> Iterator[DeviceSession]:
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
            relocations=relocations,
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

    with placements() as writing, a_session(script, relocations=writing) as session:
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
