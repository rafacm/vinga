"""What a recorded session says its device was called.

`record.sessions.device_name` is the one column in this schema that is
a copy of something in another, and the grant is what makes it
necessary rather than redundant: `deploy/postgres-init.sql` gives
`vinga_ro` USAGE and SELECT on `record` and explicitly REVOKES both on
`domain`, so an analyst, or a dashboard reading as that role, can never
join to `domain.devices`. Without a name on this side, a board is a MAC
address forever.

Two properties decide every test here, and they pull in opposite
directions:

- **It is written at the open, from the record the session attached
  to.** So the name a session carries is the name that was on the
  device when somebody started talking to it.
- **Nothing ever rewrites it.** It is a dated value, the rule
  `rename_agent`'s docstring states and `sessions.agent` beside it
  already follows. A rename therefore splits a per-device series here,
  and a board swap does not touch it at all. That is intended, and the
  tests below are how it stays intended.

The sessions are driven over the wire against a booted server, because
the column is written by `_start_recording` on the real open path and
nothing shorter reaches it. The domain half is written through the
repository, which is what makes a rename between two sessions a real
rename rather than a second configuration.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.support.configs import DEVICE_MAC
from tests.support.registry import AGENT, STAGES, store_at
from tests.support.stores import rows
from tests.support.wire import connect, shake_hands
from vinga_server.app import create_app
from vinga_server.config import Config, FileConfig, compose_config
from vinga_server.config.models import domain_fields, normalize_mac
from vinga_server.config.store import ConfigStore

MAC = normalize_mac(DEVICE_MAC)

# The board a swap moves this device onto.
OTHER_MAC = "11:22:33:44:55:66"

NAME = "Kitchen Speaker"


@pytest.fixture
def store() -> Iterator[ConfigStore]:
    """The repository, held open across a test so a rename can land
    between two sessions of one server."""
    with store_at() as opened:
        yield opened


def recording_server(store: ConfigStore, *, bind: str | None = MAC) -> Config:
    """A server that records, whose domain half really is in the
    database.

    `bind` is the board to bind, or None for the case a default agent
    covers: a MAC that reaches an agent with no device record behind it
    at all.
    """
    for stage in STAGES:
        store.set_provider(stage, "mock", {"type": "mock"})
    store.set_agent("assistant", dict(AGENT))
    if bind is not None:
        store.bind_device(bind, ["assistant"])
    else:
        store.set_default_agent("assistant")
    return compose_config(
        FileConfig(server={"conversations": {"enabled": True}}),
        domain_fields(store.load().domain),
        "the test's database",
    )


def opened(client: TestClient, device_id: str = DEVICE_MAC) -> None:
    """One session, opened and closed. A handshake is the whole of what
    this file needs: the session row is written at the open, which is
    its own marker."""
    with connect(client, device_id=device_id) as websocket:
        shake_hands(websocket)


def recorded() -> list[dict[str, Any]]:
    return sorted(rows("sessions"), key=lambda row: row["id"])


def test_a_session_records_the_name_its_device_had(store: ConfigStore) -> None:
    """The milestone in one line: an analyst reading `record` alone can
    say which speaker a session happened on."""
    config = recording_server(store)
    store.rename_device(MAC, NAME)

    with TestClient(create_app(config, from_store=True)) as client:
        opened(client)

    (row,) = recorded()
    assert (row["device"], row["device_name"]) == (MAC, NAME)


def test_a_rename_splits_the_series_rather_than_retitling_it(
    store: ConfigStore,
) -> None:
    """The consequence a dashboard author meets, pinned so nobody
    discovers it in a graph: the sessions a device already had keep the
    name they were written with, and the ones after a rename carry the
    new one.

    Both sessions are on one server, so the second row's new name is
    also the proof that the rename really landed and that the read is a
    live one.
    """
    config = recording_server(store)
    store.rename_device(MAC, NAME)

    with TestClient(create_app(config, from_store=True)) as client:
        opened(client)
        store.rename_device(MAC, "Hallway Speaker")
        opened(client)

    before, after = recorded()
    assert before["device_name"] == NAME
    assert after["device_name"] == "Hallway Speaker"
    # And the device is one device throughout, which is what makes the
    # split a naming decision rather than two boards.
    assert before["device"] == after["device"] == MAC


def test_a_board_swap_leaves_the_sessions_the_device_already_had(
    store: ConfigStore,
) -> None:
    """The other write that could have reached back. Replacing the
    hardware moves the record to a new address and keeps the name a
    person chose; the sessions the old board recorded keep both the
    address they were spoken at and the name of the moment, because a
    dated row says what was true rather than what is true."""
    config = recording_server(store)
    store.rename_device(MAC, NAME)

    with TestClient(create_app(config, from_store=True)) as client:
        opened(client)
        store.replace_device(MAC, OTHER_MAC)
        opened(client, device_id=OTHER_MAC)

    before, after = recorded()
    assert (before["device"], before["device_name"]) == (MAC, NAME)
    assert (after["device"], after["device_name"]) == (OTHER_MAC, NAME)


def test_a_device_with_no_record_records_no_name(store: ConfigStore) -> None:
    """A default agent admits a board nothing bound, which is a MAC with
    no name anywhere to copy. The column is null, and the MAC beside it
    is what a reader has, exactly as before this column existed."""
    config = recording_server(store, bind=None)

    with TestClient(create_app(config, from_store=True)) as client:
        opened(client)

    (row,) = recorded()
    assert row["device"] == MAC
    assert row["device_name"] is None


def test_a_board_nobody_has_named_records_no_name(store: ConfigStore) -> None:
    """`Device <mac>` is what this server calls a board the moment it is
    bound, and it is a placeholder rather than a name: the prompt
    refuses to say it out loud (#449 M2) and a dashboard has no more use
    for it than for the MAC it repeats. So a record nobody has named
    records null, and the control beside it is that the record exists
    and really is holding that spelling.
    """
    config = recording_server(store)

    with TestClient(create_app(config, from_store=True)) as client:
        opened(client)

    assert store.read_device(MAC).entry.name == f"Device {MAC}"
    (row,) = recorded()
    assert row["device"] == MAC
    assert row["device_name"] is None
