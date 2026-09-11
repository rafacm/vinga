"""One board replaced, one record kept.

`ConfigStore.replace_device` is what #449's stable id was minted for
(M4): the hardware in the corner of the room is swapped and everything
the household established about the thing standing there (what it is
called, where it stands, which agents it reaches, what it has been told)
stays on the record it was established on. This suite is about that
claim rather than about the SQL.

What it pins:

- **The swap itself**, which is the milestone's whole point: the id is
  unchanged and the name, the place, the bindings and the per-device
  memory all ride along to the new address.
- **The sentinel sweep**, the shape `test_agent_rename.py` uses one
  column across. One MAC nothing else in the fixture holds is swapped,
  then every row of every table of the three schemas is rendered as text
  and the `(table, column)` pairs still carrying it are compared with a
  recorded set. It fails in both directions: memory left behind at the
  old address puts a pair in the answer, and a dated row rewritten takes
  one out of it. The record is deliberately untouched, because a session
  row says which board was physically connected at the time and a swap
  made afterwards does not make that untrue.
- **The refusals**, one per state the transaction can be in before it
  writes: a source with no record, a destination another record already
  answers at, a destination the deployment already remembers a board at,
  an address that is the one the device already has, and a MAC that is
  not one. None of them quotes an address back.
- **Atomicity**, driven from the last statement: with the memory rewrite
  refused by the database, the device row is still at the address it
  started at.
- **Reversibility**, which is what the no-confirmation decision rests
  on: swap and swap back, and all three schemas are byte-identical, with
  a stranger present so a merge cannot pass as a round trip.
- **The placeholder name moves with the board**, because a name nobody
  chose is derived from the address and the address moved. The apply
  that would otherwise refuse the exported document is what makes it
  matter rather than tidy.

The live half of the same milestone, a conversation talking across a
swap, is `tests/unit/test_session_device_swap.py`.
"""

import contextlib
import datetime as dt
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from sqlalchemy import select

from tests.support.stores import (
    holding_the_write_lock,
    memory,
    memory_rows,
    rows,
    the_lock_held,
)
from vinga_server.config import entities
from vinga_server.config import store as store_module
from vinga_server.config.loader import (
    AgentRenameConflictError,
    ConfigError,
    DatabaseBusyError,
    DeviceNameConflictError,
    StorageError,
    UnknownEntityError,
)
from vinga_server.config.models import DatabaseConfig, default_device_name
from vinga_server.config.store import (
    DEVICE_MAC_TAKEN,
    SAME_MAC,
    ConfigStore,
)
from vinga_server.conversations import schema as record_schema
from vinga_server.conversations.records import TurnLeg, TurnRecord
from vinga_server.conversations.store import ConversationStore
from vinga_server.db import connection_url, open_database
from vinga_server.db import schema as domain_schema
from vinga_server.memory import schema as memory_schema
from vinga_server.memory import store as memory_store
from vinga_server.memory.store import MemoryScope

# The board being replaced, and the one replacing it. Both are ordinary
# MACs and neither is a substring of anything else this fixture writes,
# which is what makes the sweep below a sweep.
DYING = "aa:bb:cc:dd:ee:41"
FRESH = "aa:bb:cc:dd:ee:42"

# A third board, bound and left alone, so "the sentinel is gone" cannot
# be satisfied by a swap that lost rows rather than moving them, and so
# a round trip cannot pass by picking somebody else's memory up.
STRANGER = "aa:bb:cc:dd:ee:43"

NAME = "Kitchen Speaker"

LOCATION = "the kitchen, by the window"

AGENT = "poet"

BYSTANDER = "bard"

# How long a recorded turn is given to land before the suite decides it
# never will, which is the writer timeout every other suite waits under.
DONE_S = 15.0

AT = dt.datetime(2026, 9, 11, 12, 0, tzinfo=dt.UTC)

# The three schemas, in the order the census reads them.
SCHEMAS = (domain_schema, record_schema, memory_schema)

# What still says the old MAC after a board has been swapped, written
# down rather than derived, which is what makes the sweep an assertion
# instead of a tautology. Every pair is a row whose subject is a moment
# BEFORE the swap:
#
# - `sessions.device` is the board that was physically connected when
#   that session happened, and a board replaced afterwards does not make
#   it untrue. `rename_agent`'s docstring states the rule for the
#   analogous case: a dated row is evidence rather than a reference.
# - `conversations.device` is the one that had to be decided rather than
#   recognized, because the analogous column in an agent rename
#   (`conversations.agent`) is the one live column of the record and
#   does move. This one does not, and the column says why in its own
#   comment: it is "provenance rather than ownership", a thread is
#   agent-scoped, and a resume from any device bound to that agent
#   reaches it. Nothing filters on it, either: the two device-narrowed
#   reads in this server (`threads.selected` and the session listing)
#   both narrow on `sessions.device`, and this column is selected for
#   display and never compared. So a swap that moved it would rewrite
#   where a thread was begun, which is a fact about a board rather than
#   about a record.
# - `events.fields` is what was emitted at the time, and nothing
#   rewrites an emitted event.
#
# What is deliberately NOT here is `facts.owner`: per-device memory is
# the one thing that moves, because what a room told the speaker in the
# corner is about the room and not about the board that heard it.
#
# The bound on the claim, stated because a sweep is where an inventory
# claim would be tempting: this is a fact about values this fixture
# wrote, not about the schema. It catches any column this fixture
# populates, a column added later included, and it cannot see a column
# nothing here writes to.
DATED_RECORD = frozenset(
    {
        ("sessions", "device"),
        ("conversations", "device"),
        ("events", "fields"),
    }
)


@pytest.fixture
def store() -> Iterator[ConfigStore]:
    engine = open_database(DatabaseConfig())
    try:
        yield ConfigStore(engine)
    finally:
        engine.dispose()


@pytest.fixture
def thread() -> str:
    return uuid.uuid4().hex


# What the fixture writes


def a_working_configuration(store: ConfigStore) -> None:
    """Providers, defaults and the two agents a board here is bound to,
    in the natural order a store is built up in."""
    store.set_provider("llm", "claude", {"type": "anthropic", "model": "claude-sonnet-5"})
    store.set_provider("asr", "whisper", {"type": "faster_whisper", "model": "small"})
    store.set_provider("tts", "voice", {"type": "piper", "model": "es"})
    store.set_provider("vad", "silero", {"type": "silero"})
    store.set_agent_defaults(
        {"llm": "claude", "asr": "whisper", "tts": "voice", "vad": "silero"}
    )
    for name in (AGENT, BYSTANDER):
        store.set_agent(name, {"prompt": "You answer questions."})


def manifest(mac: str) -> dict[str, Any]:
    return {
        "started_at": AT.isoformat(),
        "server": {"version": "0.1.0", "revision": "abc1234"},
        "device": {"mac": mac, "client": "test"},
        "protocol": "1",
        "agent": AGENT,
        "agents": [AGENT],
        "providers": {"llm": {"name": "claude", "type": "anthropic"}},
    }


def a_recorded_thread(conversation: str, mac: str, session: str) -> None:
    """One thread with a turn and an event on it, written the way the
    server writes one and the writer let go of.

    What it puts in the record is the MAC, in the session row and inside
    an event's fields, which is the half of the sweep that has to stay
    exactly where it is.
    """
    store = ConversationStore(DatabaseConfig(), now=lambda: AT, retention_days=0)
    store.start()
    try:
        store.open_session(session, 100.0, manifest(mac))
        store.record_event(session, "heard", 20, {"device": mac}, 101.0)
        landed = store.record_turn(
            session,
            TurnRecord(
                at=101.2,
                conversation=conversation,
                agent=AGENT,
                heard="what time is it",
                reply="Just gone noon.",
                legs=(TurnLeg(agent=AGENT, text="Just gone noon."),),
            ),
        )
        assert landed.wait(DONE_S), "the turn never landed"
        store.close_session(session, duration_s=2.0, reason="client")
    finally:
        store.stop()


async def a_remembered_note(mac: str, fact: str, conversation: str | None = None) -> int:
    """One note filed under a board's MAC, held (softly forgotten) when a
    conversation is named, since a held row carries `owner` like any
    other and has to move with the board."""
    store = memory()
    kept = await store.add(MemoryScope.DEVICE, mac, fact, agent=AGENT)
    if conversation is not None:
        await store.forget(MemoryScope.DEVICE, mac, kept, conversation, agent=AGENT)
    return kept


async def a_board_that_has_been_lived_with(store: ConfigStore, thread: str) -> str:
    """The board this milestone is about: bound to two agents, named,
    placed, remembered about, and talked to, with a second board beside
    it that none of this happened to. Answers with the id its record was
    minted with."""
    a_working_configuration(store)
    store.bind_device(DYING, [AGENT, BYSTANDER])
    store.rename_device(DYING, NAME)
    store.relocate_device(DYING, LOCATION)
    store.bind_device(STRANGER, [AGENT])
    a_recorded_thread(thread, DYING, "alpha")
    await a_remembered_note(DYING, "the kettle is loud")
    await a_remembered_note(DYING, "the window is usually open", thread)
    await a_remembered_note(STRANGER, "a note about somebody else's board")
    return store.read_device(DYING).entry.id or ""


# What the database holds, read whole


def every_row() -> dict[str, list[dict[str, Any]]]:
    """Every row of every table of the three schemas, keyed by table,
    through one read engine: the tables carry their schema on their
    metadata, so one connection addresses all three."""
    engine = open_database(DatabaseConfig())
    held: dict[str, list[dict[str, Any]]] = {}
    try:
        with engine.connect() as connection:
            for module in SCHEMAS:
                for table in module.metadata.sorted_tables:
                    held[table.name] = [
                        dict(row)
                        for row in connection.execute(
                            select(table).order_by(*table.primary_key.columns)
                        ).mappings()
                    ]
    finally:
        engine.dispose()
    return held


def carrying(mac: str) -> set[tuple[str, str]]:
    """Which `(table, column)` pairs still hold this MAC anywhere in
    their value, rendered as text so an address inside a JSON object is
    found exactly as one in a text column is."""
    return {
        (table, column)
        for table, held in every_row().items()
        for row in held
        for column, value in row.items()
        if mac in str(value)
    }


# The swap


async def test_a_swap_keeps_the_record_and_moves_it_to_the_new_board(
    store: ConfigStore, thread: str
) -> None:
    """The milestone in one case, in the vocabulary an operator reads it
    in rather than as a set of column names.

    The id is what makes this one claim rather than four: a swap that
    had deleted the record and bound the new board would satisfy every
    other assertion here with a different device.
    """
    minted = await a_board_that_has_been_lived_with(store, thread)

    store.replace_device(DYING, FRESH)

    record = store.read_device(FRESH).entry
    assert record.id == minted
    assert record.name == NAME
    assert record.location == LOCATION
    assert record.agents == [AGENT, BYSTANDER]
    # And what the room told it, at the address the room's board now
    # answers at.
    assert [row["fact"] for row in memory_rows("facts", owner=FRESH)] == [
        "the kettle is loud",
        "the window is usually open",
    ]
    # The old address is a board nothing knows about, which is what a
    # board that has been taken away is.
    with pytest.raises(UnknownEntityError):
        store.read_device(DYING)
    assert memory_rows("facts", owner=DYING) == []


async def test_a_swap_moves_every_live_reference_and_no_dated_one(
    store: ConfigStore, thread: str
) -> None:
    """The sweep, as an equality against a recorded set.

    Both directions matter. Memory the swap forgot to move leaves a pair
    in the answer that is not in `DATED_RECORD`; a dated column the swap
    touched takes one out of it.
    """
    await a_board_that_has_been_lived_with(store, thread)

    store.replace_device(DYING, FRESH)

    assert carrying(DYING) == DATED_RECORD
    # And the other direction, so that "the old address is gone" cannot
    # be satisfied by a swap that dropped rows rather than moving them.
    assert carrying(FRESH) == {("devices", "mac"), ("facts", "owner")}


async def test_a_held_note_moves_with_the_board(
    store: ConfigStore, thread: str
) -> None:
    """A softly forgotten note carries `owner` like any other, so it
    moves and a restore after the swap still finds it. Its own case
    because the held area is the one part of memory no ordinary read
    walks."""
    await a_board_that_has_been_lived_with(store, thread)

    store.replace_device(DYING, FRESH)

    held = [row for row in memory_rows("facts") if row["forgotten_in"] is not None]
    assert [row["owner"] for row in held] == [FRESH]
    assert [row["forgotten_in"] for row in held] == [thread]


async def test_what_moved_is_answered_by_the_write_itself(
    store: ConfigStore, thread: str
) -> None:
    """The result type is the seam back: what the transaction did travels
    as fields rather than being recovered by re-reading a store the swap
    has already changed. How many notes moved is the one fact here that
    cannot be recovered at all, because after the commit the state it
    counted is gone."""
    minted = await a_board_that_has_been_lived_with(store, thread)

    # Spelled the other way in, which is what the canonical form is for.
    replaced = store.replace_device("AA-BB-CC-DD-EE-41", FRESH.upper())

    assert (replaced.old, replaced.mac) == (DYING, FRESH)
    assert replaced.id == minted
    assert replaced.name == NAME
    assert replaced.location == LOCATION
    assert replaced.agents == (AGENT, BYSTANDER)
    assert replaced.facts == 2


async def test_a_board_nobody_named_is_still_a_board_nobody_named(
    store: ConfigStore
) -> None:
    """The placeholder is derived from the address, so it moves with the
    address.

    Left behind it would be three things wrong at once: a name saying a
    board that is gone, a value no writer may write (the `Device <mac>`
    spelling is reserved to the device whose own MAC it is), and
    therefore an exported document its own store would refuse. The apply
    at the end is what makes this a property rather than a preference.
    """
    a_working_configuration(store)
    store.bind_device(DYING, [AGENT])

    replaced = store.replace_device(DYING, FRESH)

    assert replaced.name == default_device_name(FRESH)
    assert store.read_device(FRESH).entry.name == default_device_name(FRESH)
    # And the document that store now exports applies back onto it
    # unchanged, which is what the reserved spelling would otherwise
    # refuse.
    applied = store.apply(
        {"devices": {FRESH: dict(store.read_device(FRESH).entry.model_dump())}}
    )
    assert [entry.wrote for entry in applied] == [False]
    # And the name it would have kept really is one no writer may write,
    # which is what makes the move above a property rather than a
    # preference: the same document with the old board's placeholder in
    # it is refused whole.
    with pytest.raises(ConfigError) as refused:
        store.apply(
            {"devices": {FRESH: {"agents": [AGENT], "name": default_device_name(DYING)}}}
        )
    assert store_module.DEVICE_NAME_RESERVED in str(refused.value)


async def test_a_named_board_keeps_the_name_a_person_chose(
    store: ConfigStore
) -> None:
    """The converse, and the reason the rule above is about the
    placeholder alone: a name an operator typed is what the agent says
    out loud, and replacing the hardware does not change what the thing
    in the room is called."""
    a_working_configuration(store)
    store.bind_device(DYING, [AGENT])
    store.rename_device(DYING, NAME)

    assert store.replace_device(DYING, FRESH).name == NAME


# The refusals


async def test_a_board_with_no_record_is_refused(store: ConfigStore) -> None:
    """Swapping something that is not there addressed nothing, which is
    the refusal every device verb gives for a MAC with no row."""
    a_working_configuration(store)

    with pytest.raises(UnknownEntityError) as refused:
        store.replace_device(DYING, FRESH)

    assert str(refused.value) == entities.setting("devices").missing


async def test_an_address_another_record_answers_at_is_a_conflict(
    store: ConfigStore, thread: str
) -> None:
    """A conflict and not a merge. The two records say different things
    about a name, a place, a binding and what has been remembered, and
    only the person holding the boards knows which is meant; merged,
    nothing afterwards could tell them apart.

    Nothing is quoted back, and nothing is changed: both records are
    where they were, with what they had.
    """
    await a_board_that_has_been_lived_with(store, thread)
    before = every_row()

    with pytest.raises(DeviceNameConflictError) as refused:
        store.replace_device(DYING, STRANGER)

    assert str(refused.value) == DEVICE_MAC_TAKEN
    assert DYING not in str(refused.value)
    assert STRANGER not in str(refused.value)
    assert every_row() == before


async def test_an_address_the_deployment_already_remembers_is_refused(
    store: ConfigStore, thread: str
) -> None:
    """The second occupied destination, and the one that is easy to
    forget: a board can have no record and still have been remembered
    about, because a default agent covers a device nothing bound and a
    deleted record leaves its notes behind.

    Merging the two memories could not be undone, so it is refused whole,
    in the memory store's own sentence and in the board-swap wording of
    it rather than the agent rename's.
    """
    await a_board_that_has_been_lived_with(store, thread)
    await a_remembered_note(FRESH, "what the board at the new address was told")
    before = every_row()

    with pytest.raises(AgentRenameConflictError) as refused:
        store.replace_device(DYING, FRESH)

    assert str(refused.value) == memory_store.SWAP_OCCUPIED
    assert DYING not in str(refused.value)
    assert FRESH not in str(refused.value)
    # The domain half rolled back with it, which is the whole of what one
    # transaction over two schemas buys.
    assert every_row() == before


async def test_the_address_it_already_answers_at_is_nothing_to_swap(
    store: ConfigStore
) -> None:
    """Not an error about the world and not a no-op that reports a write:
    the request asked for something that does not exist, and the sentence
    says so without quoting the address. Compared canonically, which is
    what every path here stores."""
    a_working_configuration(store)
    store.bind_device(DYING, [AGENT])

    with pytest.raises(ConfigError) as refused:
        store.replace_device(DYING, "AA-BB-CC-DD-EE-41")

    assert str(refused.value) == SAME_MAC
    assert DYING not in str(refused.value)


async def test_an_address_that_is_not_a_mac_is_refused_before_the_lock(
    store: ConfigStore
) -> None:
    """Both arguments are addresses, so both are made canonical outside
    the transaction: nothing a caller got wrong costs a writer lock."""
    a_working_configuration(store)
    store.bind_device(DYING, [AGENT])

    for mac, to in ((DYING, "not-a-mac"), ("not-a-mac", FRESH)):
        with pytest.raises(ConfigError):
            store.replace_device(mac, to)

    assert store.read_device(DYING).entry.agents == [AGENT]


async def test_a_contended_database_is_answered_as_something_to_retry(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal every write here shares: another connection was
    holding the domain chain's lock, nothing was changed, and the same
    command may simply be run again."""
    with holding_the_write_lock(monkeypatch):
        engine = open_database(DatabaseConfig())
        try:
            store = ConfigStore(engine)
            a_working_configuration(store)
            store.bind_device(DYING, [AGENT])
            with the_lock_held():
                with pytest.raises(DatabaseBusyError):
                    store.replace_device(DYING, FRESH)
        finally:
            engine.dispose()


# Atomicity


@contextlib.contextmanager
def _the_facts_refusing_updates() -> Iterator[None]:
    """A test-only `BEFORE UPDATE` trigger on the facts table, which is
    the cheapest genuine failure the last statement of a swap can meet: a
    statement that runs and is refused."""
    url = connection_url(DatabaseConfig()).set(drivername="postgresql")
    holder = psycopg.connect(url.render_as_string(hide_password=False))
    try:
        holder.execute(
            "create function memory.refuse_fact_update() returns trigger "
            "language plpgsql as $$ begin raise exception 'no updates in this "
            "test'; end $$"
        )
        holder.execute(
            "create trigger refuse_fact_update before update on memory.facts "
            "for each row execute function memory.refuse_fact_update()"
        )
        holder.commit()
        yield
    finally:
        holder.execute("drop trigger if exists refuse_fact_update on memory.facts")
        holder.execute("drop function if exists memory.refuse_fact_update()")
        holder.commit()
        holder.close()


async def test_a_memory_move_that_fails_rolls_the_whole_swap_back(
    store: ConfigStore, thread: str
) -> None:
    """One connection, two schemas, one database, so failure atomicity is
    free: any refusal rolls the whole transaction back and there is no
    board half swapped.

    Driven from the LAST statement, which is the one that would leave the
    most behind if the two writes were two transactions: the record would
    be answering at the new address with its memory stranded at the old
    one, which is the exact outcome this milestone exists to prevent.
    """
    await a_board_that_has_been_lived_with(store, thread)
    before = every_row()

    with _the_facts_refusing_updates():
        with pytest.raises(StorageError) as refused:
            store.replace_device(DYING, FRESH)

    assert str(refused.value) == memory_store.RENAME_FAILED
    assert every_row() == before


# Reversibility, which is what the no-confirmation decision rests on


async def test_a_swap_and_a_swap_back_leave_the_database_as_it_was(
    store: ConfigStore, thread: str
) -> None:
    """The board that was put in comes out again, and the operator has
    both addresses in the shell history of the command they just typed.

    The stranger is what makes it an assertion about a swap rather than
    about two writes: it holds a binding and notes of its own throughout,
    and a swap that picked any of them up would be one no second swap
    could undo.
    """
    await a_board_that_has_been_lived_with(store, thread)
    before = every_row()

    store.replace_device(DYING, FRESH)
    store.replace_device(FRESH, DYING)

    assert every_row() == before
    assert [row["fact"] for row in memory_rows("facts", owner=STRANGER)] == [
        "a note about somebody else's board"
    ]
    assert [row["device"] for row in rows("sessions")] == [DYING]
