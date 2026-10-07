"""`vinga info` says whether the built-in agent is served, live (#612,
D6).

`GET /api/runtime/info` is composed once at startup but for one field:
whether the installed world serves vinga is read per request, so an
apply that changes it is reflected at once. Driven across applies on
one running server, through the mount a deployment gets: served, then
displaced by a legacy agent of that name, served again after the
rename, and unprovided once the providers are cleared.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from tests.support.apps import entered_client
from tests.support.stores import body, planted
from vinga_server.config import Config
from vinga_server.config.api import MOUNT_PATH
from vinga_server.config.models import (
    BUILTIN_AGENT,
    PROVIDER_STAGES,
    AgentConfig,
    BuiltinStatus,
    DatabaseConfig,
)
from vinga_server.config.responses import BUILTIN_STATUSES, BuiltinAgentStatus
from vinga_server.config.store import ConfigStore
from vinga_server.db import open_database, schema

TOKEN = "test-api-token-" + "0123456789abcdef" * 2
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# What the stored agents name for themselves, so they are still served
# once the defaults are cleared and only the built-in agent wants them.
OWN_STAGES: dict[str, str] = dict.fromkeys(PROVIDER_STAGES, "mock")


def deployment_config() -> Config:
    return Config(
        providers={stage: {"mock": {"type": "mock"}} for stage in PROVIDER_STAGES},
        agent_defaults=dict.fromkeys(PROVIDER_STAGES, "mock"),
        agents={"sam": {"prompt": "SAM"} | OWN_STAGES},
    )


def seeded(store: ConfigStore) -> None:
    for stage in PROVIDER_STAGES:
        store.set_provider(stage, "mock", {"type": "mock"})
    store.set_agent_defaults(dict.fromkeys(PROVIDER_STAGES, "mock"))
    store.set_agent("sam", {"prompt": "SAM"} | OWN_STAGES)


def info(client: TestClient) -> dict[str, Any]:
    answered = client.get(f"{MOUNT_PATH}/runtime/info", headers=HEADERS)
    assert answered.status_code == 200, answered.text
    return answered.json()["builtin_agent"]


def applied(client: TestClient) -> None:
    answered = client.post(f"{MOUNT_PATH}/runtime/config/reload", headers=HEADERS)
    assert answered.status_code == 200, answered.text


def test_info_follows_the_built_in_agent_across_applies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VINGA_API_SECRET", TOKEN)
    engine = open_database(DatabaseConfig())
    store = ConfigStore(engine)
    seeded(store)
    try:
        with entered_client(deployment_config(), from_store=True) as client:
            first = info(client)

            planted(
                store,
                insert(schema.agents).values(
                    name=BUILTIN_AGENT, body=body(AgentConfig(**OWN_STAGES))
                ),
            )
            applied(client)
            displaced = info(client)

            renamed = client.post(
                f"{MOUNT_PATH}/agents/{BUILTIN_AGENT}/rename",
                headers=HEADERS,
                json={"to": "old-vinga"},
            )
            assert renamed.status_code == 200, renamed.text
            applied(client)
            again = info(client)

            cleared = client.put(f"{MOUNT_PATH}/agent-defaults", headers=HEADERS, json={})
            assert cleared.status_code == 200, cleared.text
            applied(client)
            unprovided = info(client)
    finally:
        engine.dispose()

    assert first == {"status": "served", "stages": []}
    assert displaced == {"status": "displaced", "stages": []}
    assert again == {"status": "served", "stages": []}
    assert unprovided == {"status": "unprovided", "stages": list(PROVIDER_STAGES)}


def test_the_wire_s_statuses_are_the_configuration_s() -> None:
    """Two spellings of one closed set, held to one: the response module
    imports nothing of the server, so it cannot read the enum."""
    assert BUILTIN_STATUSES == tuple(status.value for status in BuiltinStatus)
    assert BuiltinAgentStatus.model_fields["status"].annotation.__args__ == BUILTIN_STATUSES
