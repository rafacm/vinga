"""Creating a device bound to the default agent and named, in one write
(#613, D5b).

A try link binds the browser that redeems it, and the link is spent by
then: whatever the write leaves behind is all there is. So the device
row is created, bound to the default agent and named in one
transaction, or not at all. Before this method a binding and a name
were two writes (`bind_device`, then `rename_device`), and a failure
between them left a device that was bound and wrongly named; the case
below that plants a name conflict is that failure, injected where the
second write used to be.

A MAC that already has a row is refused rather than merged, with its
own refusal type, because what the caller does about it (draw another
MAC) differs from what it does about every other refusal.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select

from tests.support.stores import stored_rows
from vinga_server.config import ConfigError
from vinga_server.config.loader import DeviceAlreadyBoundError, UnknownEntityError
from vinga_server.config.models import DatabaseConfig, is_device_id
from vinga_server.config.secrets import MASTER_KEY_ENV, generate_key, load_keys
from vinga_server.config.store import ConfigStore
from vinga_server.db import open_database, schema

MAC = "02:6e:5d:4c:3b:2a"
OTHER_MAC = "11:22:33:44:55:66"
NAME = f"Browser {MAC}"


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[ConfigStore]:
    monkeypatch.setenv(MASTER_KEY_ENV, generate_key())
    engine = open_database(DatabaseConfig())
    try:
        yield ConfigStore(engine, load_keys())
    finally:
        engine.dispose()


def _agents(store: ConfigStore, default: str | None = "sam") -> None:
    store.set_agent("sam", {"prompt": "You are Sam."})
    store.set_agent("nadia", {"prompt": "You are Nadia."})
    if default is not None:
        store.set_default_agent(default)


def _row(store: ConfigStore, mac: str) -> dict[str, Any] | None:
    """The row as the database holds it, read underneath the
    repository, or None where there is none."""
    rows = stored_rows(store, select(schema.devices).where(schema.devices.c.mac == mac))
    assert len(rows) <= 1
    return rows[0] if rows else None


def test_the_device_is_created_bound_to_the_default_agent_and_named(
    store: ConfigStore,
) -> None:
    _agents(store, default="nadia")

    enrolled = store.enroll_device(MAC, NAME)

    assert enrolled.mac == MAC
    assert enrolled.agents == ("nadia",)
    assert enrolled.name == NAME
    assert enrolled.location is None
    assert is_device_id(enrolled.id)
    row = _row(store, MAC)
    assert row is not None
    assert row["agents"] == ["nadia"]
    assert row["name"] == NAME
    assert row["id"] == enrolled.id


def test_the_binding_is_to_the_agent_not_to_whatever_the_default_becomes(
    store: ConfigStore,
) -> None:
    """Bound by name, the way an operator's bind is: a default agent
    changed afterwards moves unbound devices, and this one is bound."""
    _agents(store, default="sam")
    store.enroll_device(MAC, NAME)

    store.set_default_agent("nadia")

    assert store.read_device(MAC).entry.agents == ["sam"]


def test_a_mac_that_already_has_a_row_is_refused_and_left_alone(store: ConfigStore) -> None:
    _agents(store)
    before = store.bind_device(MAC, ["nadia"])

    with pytest.raises(DeviceAlreadyBoundError):
        store.enroll_device(MAC, NAME)

    after = store.read_device(MAC).entry
    assert after.agents == ["nadia"]
    assert after.name == before.name
    assert after.id == before.id


def test_with_no_default_agent_nothing_is_created(store: ConfigStore) -> None:
    _agents(store, default=None)

    with pytest.raises(ConfigError) as refused:
        store.enroll_device(MAC, NAME)

    assert not isinstance(refused.value, DeviceAlreadyBoundError)
    with pytest.raises(UnknownEntityError):
        store.read_device(MAC)


def test_a_name_that_cannot_be_given_leaves_no_device_behind(store: ConfigStore) -> None:
    """The failure between what used to be two writes, injected: the
    name the device is to be given is already another device's. With a
    bind followed by a rename, the bind would have committed and left
    a device bound to the default agent under the wrong name, with the
    link that made it already spent. One transaction leaves nothing.

    Planted with a name a person chose, because the browser's own
    `Browser <mac>` is reserved to the device whose MAC it is and no
    writer can put it on another one."""
    _agents(store)
    store.bind_device(OTHER_MAC, ["sam"])
    store.rename_device(OTHER_MAC, "Hall Speaker")

    with pytest.raises(ConfigError) as refused:
        store.enroll_device(MAC, "hall  speaker")

    assert not isinstance(refused.value, DeviceAlreadyBoundError)
    with pytest.raises(UnknownEntityError):
        store.read_device(MAC)
    assert _row(store, MAC) is None


def test_the_mac_is_stored_in_its_canonical_spelling(store: ConfigStore) -> None:
    _agents(store)

    enrolled = store.enroll_device(MAC.upper().replace(":", "-"), NAME)

    assert enrolled.mac == MAC
    assert _row(store, MAC) is not None
