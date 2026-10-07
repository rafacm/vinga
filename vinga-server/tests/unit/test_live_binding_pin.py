"""The device lookup, pinned before the device row is reshaped.

`read_live_binding` is the path a board depends on to be served at all:
it is what the OTA endpoint and the websocket handshake ask before a
device is issued a token, and it runs on the read-only connection that
never migrates and never takes the advisory lock. #449 turns the
`devices` row from a MAC and an agent list into a record with an id, a
name and a location, which moves the primary key off `mac`. Nothing
about this read is meant to move with it.

So this file pins the read from outside, before the schema changes, and
is expected to be byte-unchanged afterwards. Two things are pinned and
they are different kinds of promise:

- **The statements.** The exact SQL the read sends, captured off the
  cursor rather than read off the source, so a column added to the
  table, a relationship declared on it, or an index that changes the
  plan's shape cannot quietly widen what a lookup selects. A read that
  started selecting the whole row would still answer correctly and
  would still pass every test below, which is why the text is here.
- **The answers.** What the read says for a bound device, for a device
  with no row, for a device with no row while a default agent is set,
  and for a MAC spelled the other way. These are the behaviours the
  endpoint branches on.

Neither half reaches into the module. The statements are what the
database was asked, and the answers are what the caller got.

The pin moved once, deliberately, and as a behavior change rather than
a reshape (#612): the read used to send a second statement, for the
`default_agent` row, because an unbound device reached the default
agent. An unbound device only pairs now, so the default agent is no
input to whether a board is served, and the read stopped asking for it.
The commit that changed the read is the commit that changed this file,
and nothing else.
"""

from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import Engine, event

from vinga_server.config.models import DatabaseConfig
from vinga_server.config.secrets import generate_key
from vinga_server.config.store import ConfigStore, LiveBinding, read_live_binding
from vinga_server.db import open_database, read_engine

# The one statement a lookup sends, as the psycopg cursor is given it.
#
# Written out rather than built, which is the whole point of a pin: a
# statement derived from the same metadata the code derives it from
# would move with the code and pin nothing. The bound parameters are
# pinned beside them, because "which row" is as much a part of the read
# as "which columns".
BINDING_STATEMENT = (
    "SELECT domain.devices.agents \n"
    "FROM domain.devices \n"
    "WHERE domain.devices.mac = %(mac_1)s::VARCHAR"
)

MAC = "aa:bb:cc:dd:ee:ff"

# The same board, spelled the way a captive portal shows it. A lookup
# canonicalizes before it selects, so both spellings bind the same
# parameter.
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


def _sent(engine: Engine, mac: str) -> tuple[list[str], list[dict[str, object]], LiveBinding]:
    """One lookup, with everything the cursor was given recorded beside
    what the caller was answered."""
    statements: list[str] = []
    parameters: list[dict[str, object]] = []

    def record(connection, cursor, statement, params, context, executemany) -> None:  # type: ignore[no-untyped-def]
        statements.append(statement)
        parameters.append(dict(params))

    event.listen(engine, "before_cursor_execute", record)
    try:
        answered = read_live_binding(engine, mac)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return statements, parameters, answered


def _bootable(store: ConfigStore) -> None:
    """The least a device binding needs behind it: one agent that
    exists, so a bind resolves."""
    store.set_agent("sam", {"prompt": "You are Sam."})


def test_the_lookup_sends_exactly_this_statement(
    store: ConfigStore, lookup: Engine
) -> None:
    _bootable(store)
    store.bind_device(MAC, ["sam"])

    statements, parameters, _ = _sent(lookup, MAC)

    assert statements == [BINDING_STATEMENT]
    assert parameters == [{"mac_1": MAC}]


def test_the_statement_is_the_same_on_a_device_with_no_row(
    store: ConfigStore, lookup: Engine
) -> None:
    """A miss is not a different read. The statement and its parameters
    are what a device that was never bound produces too, so the pin
    covers the path an unknown board takes, a default agent set or not."""
    _bootable(store)
    store.set_default_agent("sam")

    statements, parameters, _ = _sent(lookup, MAC)

    assert statements == [BINDING_STATEMENT]
    assert parameters == [{"mac_1": MAC}]


def test_a_shouted_mac_binds_the_canonical_one(
    store: ConfigStore, lookup: Engine
) -> None:
    _bootable(store)
    store.bind_device(MAC, ["sam"])

    statements, parameters, answered = _sent(lookup, SHOUTED)

    assert statements == [BINDING_STATEMENT]
    assert parameters[0] == {"mac_1": MAC}
    assert answered == LiveBinding(agents=("sam",))


def test_a_bound_device_answers_with_its_agents(
    store: ConfigStore, lookup: Engine
) -> None:
    _bootable(store)
    store.set_agent("nadia", {"prompt": "You are Nadia."})
    store.bind_device(MAC, ["sam", "nadia"])

    _, _, answered = _sent(lookup, MAC)

    assert answered == LiveBinding(agents=("sam", "nadia"))


def test_a_device_with_no_row_answers_empty(store: ConfigStore, lookup: Engine) -> None:
    _bootable(store)
    store.bind_device(OTHER_MAC, ["sam"])

    _, _, answered = _sent(lookup, MAC)

    assert answered == LiveBinding(agents=())


def test_a_default_agent_answers_nothing_for_an_unbound_device(
    store: ConfigStore, lookup: Engine
) -> None:
    """What the second statement used to carry, and why it went: an
    unbound device reaches no agent, so a default agent standing behind
    it is not part of the answer."""
    _bootable(store)
    store.set_default_agent("sam")

    _, _, answered = _sent(lookup, MAC)

    assert answered == LiveBinding(agents=())


def test_a_bound_device_answers_its_own_agents_whatever_the_default(
    store: ConfigStore, lookup: Engine
) -> None:
    _bootable(store)
    store.set_agent("nadia", {"prompt": "You are Nadia."})
    store.bind_device(MAC, ["nadia"])
    store.set_default_agent("sam")

    _, _, answered = _sent(lookup, MAC)

    assert answered == LiveBinding(agents=("nadia",))
