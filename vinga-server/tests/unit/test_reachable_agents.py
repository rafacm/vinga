"""Which agents a bound device reaches, at the three edges that ask
(#612, M6).

A device's binding is resolved by `DeviceBindings` and classified
against one world by `BoundNames.against`, and three callers act on the
answer: the OTA check-in (`ota/reply.py`, the token and its `ota_check`
line), the activation poll (`ota/poll.py`, `activation_complete`) and
the websocket session (`device/session.py`, `session_open`). Each test
here drives all three through the running app and reads what each said,
in both homes of the rule: a server reading the store live, and one
serving a configuration composed in Python.

The first half pins what a world that does not serve the built-in agent
answers: unprovided, as on a fresh deployment, and displaced by an
operator's own agent named vinga. Neither moves when vinga becomes
reachable from every bound device, and the displaced one is an access
boundary: a device bound to `kids` must never reach an operator's agent
named `vinga` that it was not bound to.
"""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from tests.support.configs import DEVICE_UUID, world
from tests.support.events import fields_of, only
from tests.support.registry import AGENT, STAGES, booted, check_in, store_at
from tests.support.registry import BINDINGS_DEVICE_MAC as KIDS_MAC
from tests.support.stores import body, planted
from vinga_server.app import create_app
from vinga_server.config import Config
from vinga_server.config.models import BUILTIN_AGENT, AgentConfig
from vinga_server.db import schema
from vinga_server.device.bindings import DeviceBindings
from vinga_server.ota import ACTIVATE_SEGMENT, OTA_PATH
from vinga_server.ws import WEBSOCKET_PATH

# A second board, bound to whatever is named vinga in the world under
# test.
VINGA_MAC = "aa:bb:cc:dd:ee:31"

HOMES = ["database", "snapshot"]

HELLO = {
    "type": "hello",
    "version": 1,
    "features": {"mcp": True},
    "transport": "websocket",
    "audio_params": {
        "format": "opus",
        "sample_rate": 16000,
        "channels": 1,
        "frame_duration": 60,
    },
}


def a_world(
    home: str,
    *,
    devices: dict[str, list[str]],
    serves_defaults: bool,
    legacy_vinga: bool = False,
    agents: tuple[str, ...] = ("kids",),
) -> tuple[Config, bool]:
    """One world, in the home the test names, and whether a server
    should read it from the store.

    `serves_defaults` writes every provider stage under `agent_defaults`,
    which is what serves the built-in agent; `legacy_vinga` stores an
    operator's agent named vinga, as a build from before the built-in
    wrote it, which displaces it.
    """
    defaults = AGENT if serves_defaults else None
    if home == "database":
        if legacy_vinga:
            with store_at() as store:
                planted(
                    store,
                    insert(schema.agents).values(name=BUILTIN_AGENT, body=body(AgentConfig())),
                )
        config = booted(agents=agents, devices=devices, agent_defaults=defaults)
        return config, True
    entries: dict[str, object] = {name: AGENT for name in agents}
    if legacy_vinga:
        entries[BUILTIN_AGENT] = {}
    config = Config(
        providers={stage: {"mock": {"type": "mock"}} for stage in STAGES},
        agent_defaults=defaults or {},
        agents=entries,
        devices=devices,
    )
    return config, False


@contextmanager
def running(config: Config, from_store: bool) -> Iterator[TestClient]:
    with TestClient(create_app(config, from_store=from_store)) as client:
        yield client


def reached(client: TestClient, caplog: pytest.LogCaptureFixture, mac: str) -> dict[str, object]:
    """What each of the three edges said this device reaches: the
    check-in's `ota_check` agents and unloaded names, the activation
    poll's `activation_complete` agents (None when it said the device
    is still waiting), and the session's `session_open` agents (None
    when the connection was refused), and the agent that session opened
    on."""
    caplog.set_level(logging.INFO)
    caplog.clear()
    token = check_in(client, mac)["websocket"]["token"]
    checked = fields_of(only(caplog, "ota_check"))

    caplog.clear()
    polled = client.post(f"{OTA_PATH}{ACTIVATE_SEGMENT}", json={}, headers={"Device-Id": mac})
    completes = [
        fields_of(record)
        for record in caplog.records
        if getattr(record, "event", None) == "activation_complete"
    ]

    session_agents = opened = None
    if token:
        caplog.clear()
        headers = {
            "Authorization": f"Bearer {token}",
            "Protocol-Version": "1",
            "Device-Id": mac,
            "Client-Id": DEVICE_UUID,
        }
        with client.websocket_connect(WEBSOCKET_PATH, headers=headers) as websocket:
            websocket.send_text(json.dumps(HELLO))
            assert json.loads(websocket.receive_text())["type"] == "hello"
        opening = fields_of(only(caplog, "session_open"))
        session_agents, opened = opening["agents"], opening["agent"]

    return {
        "token": bool(token),
        "ota_check": (checked["agents"], checked["unloaded"]),
        "poll": (polled.status_code, completes[0]["agents"] if completes else None),
        "session": session_agents,
        "opened": opened,
    }


# A world that does not serve the built-in agent


@pytest.mark.parametrize("home", HOMES)
def test_an_unprovided_built_in_adds_nothing_to_a_bound_device(
    home: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A fresh deployment's world: no stage named under the defaults, so
    vinga is not served and a device reaches exactly its binding."""
    config, from_store = a_world(home, devices={KIDS_MAC: ["kids"]}, serves_defaults=False)
    assert config.builtin_state.status == "unprovided"

    with running(config, from_store) as client:
        assert reached(client, caplog, KIDS_MAC) == {
            "token": True,
            "ota_check": (["kids"], []),
            "poll": (200, ["kids"]),
            "session": ["kids"],
            "opened": "kids",
        }


@pytest.mark.parametrize("home", HOMES)
def test_an_operator_s_agent_named_vinga_is_reached_only_where_it_is_bound(
    home: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The access boundary. An operator's agent named vinga displaces the
    built-in, and it is that operator's agent, with its own persona and
    its own grants: a device bound to `kids` must not reach it through
    the built-in's name, and the device bound to it reaches it alone."""
    config, from_store = a_world(
        home,
        devices={KIDS_MAC: ["kids"], VINGA_MAC: [BUILTIN_AGENT]},
        serves_defaults=True,
        legacy_vinga=True,
    )
    assert config.builtin_state.status == "displaced"
    assert BUILTIN_AGENT in config.agents

    with running(config, from_store) as client:
        assert reached(client, caplog, KIDS_MAC) == {
            "token": True,
            "ota_check": (["kids"], []),
            "poll": (200, ["kids"]),
            "session": ["kids"],
            "opened": "kids",
        }
        assert reached(client, caplog, VINGA_MAC) == {
            "token": True,
            "ota_check": ([BUILTIN_AGENT], []),
            "poll": (200, [BUILTIN_AGENT]),
            "session": [BUILTIN_AGENT],
            "opened": BUILTIN_AGENT,
        }


@pytest.mark.parametrize("home", HOMES)
def test_a_displaced_world_reaches_nothing_from_an_unbound_device(
    home: str, caplog: pytest.LogCaptureFixture
) -> None:
    config, from_store = a_world(
        home, devices={KIDS_MAC: ["kids"]}, serves_defaults=True, legacy_vinga=True
    )

    with running(config, from_store) as client:
        assert reached(client, caplog, VINGA_MAC) == {
            "token": False,
            "ota_check": ([], []),
            "poll": (202, None),
            "session": None,
            "opened": None,
        }


@pytest.mark.parametrize("serves_defaults", [False, True], ids=["unprovided", "displaced"])
def test_the_configuration_s_answer_is_the_binding_where_vinga_is_not_served(
    serves_defaults: bool,
) -> None:
    """The snapshot home on its own, `Config.agents_for_device`, in the
    same two worlds."""
    config, _ = a_world(
        "snapshot",
        devices={KIDS_MAC: ["kids"], VINGA_MAC: [BUILTIN_AGENT]},
        serves_defaults=serves_defaults,
        legacy_vinga=serves_defaults,
    )

    assert config.agents_for_device(KIDS_MAC) == ["kids"]
    assert config.agents_for_device("aa:bb:cc:dd:ee:99") == []


# A world that serves the built-in agent


@pytest.mark.parametrize("home", HOMES)
def test_a_bound_device_also_reaches_vinga_after_its_binding(
    home: str, caplog: pytest.LogCaptureFixture
) -> None:
    """vinga is reachable from every bound device (#612, Q3): the
    binding first, so a conversation still opens on the agent the
    operator bound, and vinga behind it, at every edge that asks."""
    config, from_store = a_world(home, devices={KIDS_MAC: ["kids"]}, serves_defaults=True)
    assert config.builtin_state.status == "served"

    with running(config, from_store) as client:
        assert reached(client, caplog, KIDS_MAC) == {
            "token": True,
            "ota_check": (["kids", BUILTIN_AGENT], []),
            "poll": (200, ["kids", BUILTIN_AGENT]),
            "session": ["kids", BUILTIN_AGENT],
            "opened": "kids",
        }


@pytest.mark.parametrize("home", HOMES)
def test_an_unbound_device_still_reaches_nothing_where_vinga_is_served(
    home: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The append is to a binding: an unbound device only pairs."""
    config, from_store = a_world(home, devices={KIDS_MAC: ["kids"]}, serves_defaults=True)

    with running(config, from_store) as client:
        assert reached(client, caplog, VINGA_MAC) == {
            "token": False,
            "ota_check": ([], []),
            "poll": (202, None),
            "session": None,
            "opened": None,
        }


def test_a_device_bound_only_to_an_agent_not_yet_served_reaches_vinga(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Any binding at all is a binding vinga is appended to, so a board
    bound to an agent written but not yet applied talks to vinga while
    it waits: its session opens on vinga, the first agent it reaches,
    and the agent it waits for is still named as unloaded."""
    config, from_store = a_world("database", devices={KIDS_MAC: ["kids"]}, serves_defaults=True)

    with running(config, from_store) as client:
        with store_at() as store:
            store.set_agent("poet", dict(AGENT))
            store.bind_device(VINGA_MAC, ["poet"])

        assert reached(client, caplog, VINGA_MAC) == {
            "token": True,
            "ota_check": ([BUILTIN_AGENT], ["poet"]),
            "poll": (200, [BUILTIN_AGENT]),
            "session": [BUILTIN_AGENT],
            "opened": BUILTIN_AGENT,
        }


# Both homes of the rule, one test


ALSO_MAC = "aa:bb:cc:dd:ee:32"
AFTER_MAC = "aa:bb:cc:dd:ee:33"
UNBOUND_MAC = "aa:bb:cc:dd:ee:34"


def answered(home: str, config: Config, mac: str) -> tuple[str, ...]:
    """What one home of the rule says a device reaches: the live view
    over the database, the view with no database behind it, or the
    configuration's own `agents_for_device`."""
    if home == "config":
        return tuple(config.agents_for_device(mac))
    generations = world(config)
    view = (
        DeviceBindings.open(generations)
        if home == "database"
        else DeviceBindings.snapshot_only(generations)
    )
    try:
        return view.names_for(mac).against(config).agents
    finally:
        view.dispose()


@pytest.mark.parametrize("home", ["database", "snapshot", "config"])
def test_every_home_of_the_rule_appends_vinga_the_same_way(home: str) -> None:
    """The append asserted through `DeviceBindings` with a database,
    through `DeviceBindings.snapshot_only`, and through
    `Config.agents_for_device`, so breaking the rule in any of them
    fails here. vinga goes last unless the binding already names it,
    and then it stays where the operator put it, once."""
    devices = {
        KIDS_MAC: ["kids"],
        ALSO_MAC: [BUILTIN_AGENT, "kids"],
        AFTER_MAC: ["kids", BUILTIN_AGENT],
    }
    config, _ = a_world(
        "database" if home == "database" else "snapshot",
        devices=devices,
        serves_defaults=True,
    )

    assert answered(home, config, KIDS_MAC) == ("kids", BUILTIN_AGENT)
    assert answered(home, config, ALSO_MAC) == (BUILTIN_AGENT, "kids")
    assert answered(home, config, AFTER_MAC) == ("kids", BUILTIN_AGENT)
    assert answered(home, config, UNBOUND_MAC) == ()


@pytest.mark.parametrize("home", ["database", "snapshot", "config"])
def test_no_home_of_the_rule_appends_a_displacing_agent(home: str) -> None:
    """The displaced case in every home: the world serves an agent named
    vinga, and it is the operator's, so it is reached where it is bound
    and nowhere else."""
    config, _ = a_world(
        "database" if home == "database" else "snapshot",
        devices={KIDS_MAC: ["kids"], VINGA_MAC: [BUILTIN_AGENT]},
        serves_defaults=True,
        legacy_vinga=True,
    )

    assert answered(home, config, KIDS_MAC) == ("kids",)
    assert answered(home, config, VINGA_MAC) == (BUILTIN_AGENT,)


@pytest.mark.parametrize("home", ["database", "snapshot", "config"])
def test_no_home_of_the_rule_appends_an_unprovided_built_in(home: str) -> None:
    """A world that cannot serve vinga reaches nothing by its name, and a
    device bound to it alone waits, named as unloaded, as a device bound
    to any agent not yet served waits."""
    config, _ = a_world(
        "database" if home == "database" else "snapshot",
        devices={KIDS_MAC: ["kids"], VINGA_MAC: [BUILTIN_AGENT]},
        serves_defaults=False,
    )

    assert answered(home, config, KIDS_MAC) == ("kids",)
    assert answered(home, config, VINGA_MAC) == ()
