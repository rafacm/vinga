"""The two reads a served conversation makes about its device.

`read_live_binding` answers whether a board is served at all and is
pinned byte for byte (`test_live_binding_pin.py`). Beside it, #449 adds
the two this file is about:

- **`read_live_attachment`**, what a connect asks: the binding, the
  default agent behind it and the record the conversation will attach
  to, from one snapshot. Its first two statements are the ones
  `read_live_binding` sends, character for character, which is asserted
  here by capturing both rather than by transcribing either.
- **`read_live_device_by_id`**, what a reply asks on every round: that
  record as it stands now, addressed by the identity it attached to.

The addressing is the subject. A MAC says where a board is standing and
an id says which record it is, and the two part company the moment an
operator deletes a device and binds the same board again. The last
section drives exactly that and asserts the attached conversation is
told nothing rather than told the new record's name.
"""

from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import Engine, event, update

from vinga_server.config.models import DatabaseConfig
from vinga_server.config.secrets import generate_key
from vinga_server.config.store import (
    ConfigStore,
    LiveBinding,
    LiveDevice,
    read_live_attachment,
    read_live_binding,
    read_live_device_by_id,
)
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


def attached(engine: Engine, mac: str = MAC) -> LiveDevice:
    """The record a connect would attach to, asserted present."""
    record = read_live_attachment(engine, mac).device
    assert record is not None
    return record


def statements(engine: Engine, work) -> tuple[list[str], object]:  # type: ignore[no-untyped-def]
    """One read, with everything the cursor was given recorded beside
    what the caller was answered."""
    sent: list[str] = []

    def record(connection, cursor, statement, params, context, executemany) -> None:  # type: ignore[no-untyped-def]
        sent.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        answered = work()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return sent, answered


# What a connect resolves


def test_the_attachment_answers_the_binding_and_the_record_together(
    store: ConfigStore, lookup: Engine
) -> None:
    bound(store)

    resolved = read_live_attachment(lookup, MAC)

    assert resolved.binding == LiveBinding(agents=("sam",), default_agent=None)
    assert resolved.device is not None
    assert resolved.device.mac == MAC
    assert resolved.device.name == f"Device {MAC}"
    assert resolved.device.location is None
    assert resolved.device.id == store.read_device(MAC).entry.id


def test_the_attachment_sends_the_pinned_statements_and_one_more(
    store: ConfigStore, lookup: Engine
) -> None:
    """The binding is not widened to carry the record and the record is
    not widened into the binding: what a board depends on to be served
    at all keeps the statement it was pinned with, and the record is a
    statement of its own in the same transaction.

    The two are compared against what `read_live_binding` itself sends,
    captured here rather than transcribed. `test_live_binding_pin.py`
    is what pins those two to their exact text, byte for byte, and this
    asserts the attachment sends THOSE, so the pin covers both entry
    points and neither file restates the other.
    """
    bound(store)

    pinned, _ = statements(lookup, lambda: read_live_binding(lookup, MAC))
    sent, _ = statements(lookup, lambda: read_live_attachment(lookup, MAC))

    assert len(pinned) == 2
    assert sent[:2] == pinned
    assert len(sent) == 3
    assert "domain.devices.id" in sent[2] and "domain.devices.mac = " in sent[2]


def test_a_board_with_no_row_attaches_to_nothing(
    store: ConfigStore, lookup: Engine
) -> None:
    """A MAC a default agent stands behind is served and has no record,
    and a conversation on it says nothing about its device."""
    bound(store, OTHER_MAC)
    store.set_default_agent("sam")

    resolved = read_live_attachment(lookup, MAC)

    assert resolved.binding.default_agent == "sam"
    assert resolved.device is None


def test_a_shouted_mac_attaches_to_the_canonical_row(
    store: ConfigStore, lookup: Engine
) -> None:
    bound(store)

    resolved = read_live_attachment(lookup, SHOUTED)

    assert resolved.device is not None and resolved.device.mac == MAC


# What a round re-reads


def test_the_record_reads_back_by_the_identity_it_attached_to(
    store: ConfigStore, lookup: Engine
) -> None:
    bound(store)
    record = attached(lookup)

    store.rename_device(MAC, "Kitchen Speaker")
    store.relocate_device(MAC, "the kitchen")

    assert read_live_device_by_id(lookup, record.id or "") == LiveDevice(
        id=record.id,
        mac=MAC,
        name="Kitchen Speaker",
        location="the kitchen",
        named=True,
    )


def test_a_cleared_location_reads_back_as_nowhere_in_particular(
    store: ConfigStore, lookup: Engine
) -> None:
    bound(store)
    store.relocate_device(MAC, "the kitchen")
    record = attached(lookup)

    store.clear_device_location(MAC)

    answered = read_live_device_by_id(lookup, record.id or "")
    assert answered is not None and answered.location is None


def test_the_re_read_costs_one_statement(store: ConfigStore, lookup: Engine) -> None:
    """A reply pays for this on every round, inside the turnaround a
    person is listening through. The record is one row on the primary
    key, so one statement is what it can cost, and a second would be a
    second round trip per round of every reply in the process."""
    bound(store)
    record = attached(lookup)

    sent, answered = statements(
        lookup, lambda: read_live_device_by_id(lookup, record.id or "")
    )

    assert answered is not None
    assert len(sent) == 1


def test_a_deleted_record_answers_nothing(store: ConfigStore, lookup: Engine) -> None:
    bound(store)
    record = attached(lookup)

    store.delete_device(MAC)

    assert read_live_device_by_id(lookup, record.id or "") is None


def test_a_name_that_names_nothing_is_answered_as_no_record(
    store: ConfigStore, lookup: Engine
) -> None:
    """The column is NOT NULL and every writer holds the fold's refusal
    in front of it, so this row is one nothing in this server wrote.
    Read as "this device has no name", because the alternative is
    telling a model it is speaking through a device called nothing.
    """
    bound(store)
    record = attached(lookup)
    engine = open_database(DatabaseConfig())
    try:
        with engine.begin() as connection:
            connection.execute(
                update(schema.devices)
                .where(schema.devices.c.mac == MAC)
                .values(name="  \t")
            )
    finally:
        engine.dispose()

    assert read_live_device_by_id(lookup, record.id or "") is None
    assert read_live_attachment(lookup, MAC).device is None


# The address a conversation must not be re-read by


def test_a_deleted_and_re_bound_board_is_a_record_the_old_one_cannot_reach(
    store: ConfigStore, lookup: Engine
) -> None:
    """The failure the stable identity exists to prevent, driven.

    A conversation attaches to the record standing at its MAC. The
    operator then deletes that device and binds the same board again,
    which mints a second record at the same address, and names it. A
    re-read by MAC would hand the conversation already in flight the new
    record's name; the re-read by id hands it nothing, which is what a
    conversation whose device is gone is entitled to.
    """
    bound(store)
    first = attached(lookup)

    store.delete_device(MAC)
    store.bind_device(MAC, ["sam"])
    store.rename_device(MAC, "Kitchen Speaker")

    second = attached(lookup)
    # Two records, one address: the id is what tells them apart.
    assert second.id != first.id
    assert second.name == "Kitchen Speaker"
    assert read_live_device_by_id(lookup, first.id or "") is None


def test_a_record_whose_mac_moved_is_still_the_same_record(
    store: ConfigStore, lookup: Engine
) -> None:
    """The converse, which is #449's M4: a board is replaced and its
    MAC is written onto the record that keeps the name, the place and
    the memory. A conversation attached to that record follows it,
    because it is addressed by what did not change.

    Written here through the columns rather than through the operation,
    which M4 adds: what this pins is that the id-addressed read follows
    a MAC change at all, so the milestone that performs one inherits a
    reader that already does the right thing.
    """
    bound(store)
    record = attached(lookup)
    engine = open_database(DatabaseConfig())
    try:
        with engine.begin() as connection:
            connection.execute(
                update(schema.devices)
                .where(schema.devices.c.id == record.id)
                .values(mac=OTHER_MAC)
            )
    finally:
        engine.dispose()

    followed = read_live_device_by_id(lookup, record.id or "")
    assert followed is not None
    assert followed.id == record.id and followed.mac == OTHER_MAC
    # And the old address answers nothing, which is what a board that
    # was taken away is.
    assert read_live_attachment(lookup, MAC).device is None
