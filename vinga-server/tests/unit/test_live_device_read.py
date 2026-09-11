"""The record read a running reply makes, beside the binding's.

`read_live_binding` answers whether a board is served at all and is
pinned byte for byte (`test_live_binding_pin.py`). This is the other
read of the same rows, added by #449: what the device behind a MAC is
called and where it stands, asked once per round by a conversation that
is already talking.

Three things are asserted here and each is a promise to a different
reader. It costs one statement, because a reply pays for it inside the
turnaround a person is listening through. It answers the record as the
rows hold it NOW, which is what makes a device that was moved between
two replies moved for the second of them. And it answers None rather
than an invented value for every shape that is not a named device, so
nothing downstream has to decide what "a device called nothing" means.
"""

from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import Engine, event, update

from vinga_server.config.models import DatabaseConfig
from vinga_server.config.secrets import generate_key
from vinga_server.config.store import ConfigStore, LiveDevice, read_live_device
from vinga_server.db import open_database, read_engine, schema

MAC = "aa:bb:cc:dd:ee:ff"

# The same board as a captive portal shows it, which is what an
# operator pastes.
SHOUTED = "AA-BB-CC-DD-EE-FF"

OTHER_MAC = "11:22:33:44:55:66"


@pytest.fixture
def store() -> Iterator[ConfigStore]:
    engine = open_database(DatabaseConfig())
    try:
        yield ConfigStore(engine, MultiFernet([Fernet(generate_key())]))
    finally:
        engine.dispose()


@pytest.fixture
def lookup() -> Iterator[Engine]:
    """The engine a device path reads through: read-only, repeatable
    read, and never migrated."""
    engine = read_engine(DatabaseConfig())
    try:
        yield engine
    finally:
        engine.dispose()


def bound(store: ConfigStore, mac: str = MAC) -> None:
    store.set_agent("sam", {"prompt": "You are Sam."})
    store.bind_device(mac, ["sam"])


def statements(engine: Engine, mac: str) -> tuple[list[str], LiveDevice | None]:
    """One read, with everything the cursor was given recorded beside
    what the caller was answered."""
    sent: list[str] = []

    def record(connection, cursor, statement, params, context, executemany) -> None:  # type: ignore[no-untyped-def]
        sent.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        answered = read_live_device(engine, mac)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return sent, answered


def test_a_bound_device_answers_with_the_name_it_was_created_under(
    store: ConfigStore, lookup: Engine
) -> None:
    bound(store)

    answered = read_live_device(lookup, MAC)

    assert answered is not None
    assert answered.name == f"Device {MAC}"
    assert answered.location is None


def test_the_answer_carries_the_id_the_record_was_minted_with(
    store: ConfigStore, lookup: Engine
) -> None:
    """The two facts belong to a row rather than to a MAC, which is the
    whole reason the record has an identity: the same read that says
    what a device is called says which record said it, so a board swap
    is answerable about the device rather than about the hardware."""
    bound(store)

    answered = read_live_device(lookup, MAC)

    assert answered is not None
    assert answered.id == store.read_device(MAC).entry.id


def test_a_relocated_device_reads_back_where_it_was_put(
    store: ConfigStore, lookup: Engine
) -> None:
    bound(store)

    store.relocate_device(MAC, "the kitchen")

    assert read_live_device(lookup, MAC) == LiveDevice(
        id=store.read_device(MAC).entry.id,
        name=f"Device {MAC}",
        location="the kitchen",
    )


def test_a_cleared_location_reads_back_as_nowhere_in_particular(
    store: ConfigStore, lookup: Engine
) -> None:
    bound(store)
    store.relocate_device(MAC, "the kitchen")

    store.clear_device_location(MAC)

    answered = read_live_device(lookup, MAC)
    assert answered is not None and answered.location is None


def test_a_renamed_device_reads_back_under_its_new_name(
    store: ConfigStore, lookup: Engine
) -> None:
    bound(store)

    store.rename_device(MAC, "Kitchen Speaker")

    answered = read_live_device(lookup, MAC)
    assert answered is not None and answered.name == "Kitchen Speaker"


def test_a_device_with_no_row_answers_nothing(
    store: ConfigStore, lookup: Engine
) -> None:
    """Not an error and not an empty record: a MAC a default agent
    stands behind has no record, and a reply for it says nothing about
    the device at all."""
    bound(store, OTHER_MAC)

    assert read_live_device(lookup, MAC) is None


def test_a_shouted_mac_reads_the_canonical_row(
    store: ConfigStore, lookup: Engine
) -> None:
    bound(store)

    answered = read_live_device(lookup, SHOUTED)

    assert answered is not None and answered.name == f"Device {MAC}"


def test_the_read_costs_one_statement(store: ConfigStore, lookup: Engine) -> None:
    """A reply pays for this on every round, inside the turnaround a
    person is listening through. The record is three columns of one row,
    so one statement is what it can cost, and a second would be a second
    round trip per round of every reply in the process."""
    bound(store)

    sent, answered = statements(lookup, MAC)

    assert answered is not None
    assert len(sent) == 1


def test_a_miss_costs_one_statement_too(store: ConfigStore, lookup: Engine) -> None:
    bound(store, OTHER_MAC)

    sent, answered = statements(lookup, MAC)

    assert answered is None
    assert len(sent) == 1


def test_a_name_that_names_nothing_is_answered_as_no_record(
    store: ConfigStore, lookup: Engine
) -> None:
    """The column is NOT NULL and every writer holds the fold's refusal
    in front of it, so this row is one nothing in this server wrote.
    Read as "this device has no name", because the alternative is
    telling a model it is speaking through a device called nothing.
    """
    bound(store)
    engine = open_database(DatabaseConfig())
    try:
        with engine.begin() as connection:
            connection.execute(
                update(schema.devices)
                .where(schema.devices.c.mac == MAC)
                .values(name="  \t")
            )
    finally:
        engine.dispose()

    assert read_live_device(lookup, MAC) is None
