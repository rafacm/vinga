"""Issuing an invite link from the configuration API (#613, D5, D5a, D5c, D6b;
#612, Q11).

`POST /api/runtime/invites` mints a token behind the operator's bearer
token and answers it inside the page's path, `/talk/#<token>`, with the
origin the link should name when this server's configuration states one
that opens a secure context. Its body may name the agents the browser
is to be bound to; naming none means the default agent. It refuses,
with nothing minted, in each state where opening the link could not do
what it promises: onboarding off, no store behind the served world, a
named agent this deployment does not have or this server is not
serving, a default agent this server is not serving when none is named
(vinga, the built-in agent, when none is set; #612, D5), and a store
already holding as many links as it will.

The deployments here are real: a store written through the repository,
a server composed from it with the bindings read live, and the request
made through the whole application, gate included.
"""

import re

import pytest

import vinga_server.onboarding as onboarding
from tests.conftest import TEST_API_SECRET
from tests.support.apps import entered_app
from tests.support.configs import config_with_agent
from tests.support.registry import booted, store_at
from vinga_server.config.api import build_api, document
from vinga_server.config.models import DatabaseConfig, ServerConfig
from vinga_server.config.responses import PROBLEM_MEDIA_TYPE
from vinga_server.onboarding.invites import (
    AGENT_NOT_SERVED,
    AGENTS_UNKNOWN,
    CAPACITY_REACHED,
    DEFAULT_AGENT_NOT_SERVED,
    ONBOARDING_OFF,
    SNAPSHOT_ONLY,
    link_origin,
)

PATH = "/runtime/invites"
ISSUE = f"/api{PATH}"
BEARER = {"Authorization": f"Bearer {TEST_API_SECRET}"}

PAGE = re.compile(r"^/talk/#([A-Za-z0-9_-]{43})$")


def held(app) -> int:
    return app.state.composition.invites.held


def test_a_link_is_issued_into_the_page_s_fragment() -> None:
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        answer = client.post(ISSUE, json={}, headers=BEARER)

        assert answer.status_code == 200
        body = answer.json()
        assert set(body) == {"origin", "page", "lifetime_s"}
        assert PAGE.match(body["page"]), body["page"]
        assert body["lifetime_s"] == 600
        # No public URL is configured, so the origin is the client's to
        # derive: never the listen address.
        assert body["origin"] is None
        assert held(app) == 1


def test_the_answer_is_not_to_be_stored() -> None:
    with entered_app(booted(default_agent="assistant"), from_store=True) as (_, client):
        answer = client.post(ISSUE, json={}, headers=BEARER)

    assert answer.headers["cache-control"] == "no-store"


def test_each_request_is_a_new_link() -> None:
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        first = client.post(ISSUE, json={}, headers=BEARER).json()["page"]
        second = client.post(ISSUE, json={}, headers=BEARER).json()["page"]

        assert first != second
        assert held(app) == 2


def test_with_the_built_in_default_unserved_nothing_is_issued_and_the_state_is_named() -> (
    None
):
    """D5: no default agent is stored, so the default is vinga, and this
    world names no provider for it, so a browser bound to it would get
    no answer. Getting Started's state before its providers exist."""
    with entered_app(booted(), from_store=True) as (app, client):
        answer = client.post(ISSUE, json={}, headers=BEARER)

        assert answer.status_code == 409
        assert answer.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
        problem = answer.json()
        assert problem["detail"] == DEFAULT_AGENT_NOT_SERVED
        assert problem["reason"] == "default-agent-not-served"
        assert held(app) == 0


def test_with_no_default_agent_a_served_built_in_agent_is_the_default() -> None:
    """The other half of D5: once the defaults provide every stage, vinga
    is served, and an invite naming no agent is issued with no default
    agent set at all."""
    config = booted(agent_defaults=dict.fromkeys(("llm", "asr", "tts", "vad"), "mock"))
    with entered_app(config, from_store=True) as (app, client):
        assert client.post(ISSUE, json={}, headers=BEARER).status_code == 200
        assert held(app) == 1


def test_a_default_agent_written_since_the_boot_is_not_served_until_applied() -> None:
    """The comparison is with the world installed now: a default agent
    stored since the boot names an agent this server has not installed,
    and is refused until an apply installs it."""
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        with store_at() as store:
            store.set_agent("later", {"prompt": "LATER"})
            store.set_default_agent("later")

        refused = client.post(ISSUE, json={}, headers=BEARER)

        assert refused.status_code == 409
        assert refused.json()["reason"] == "default-agent-not-served"
        assert held(app) == 0


def test_the_default_agent_is_read_as_it_stands_now() -> None:
    """Set while the server runs, with no restart and no apply: the
    issuance asks the store, as a check-in asks the bindings."""
    with entered_app(booted(), from_store=True) as (app, client):
        assert client.post(ISSUE, json={}, headers=BEARER).status_code == 409

        with store_at() as store:
            store.set_default_agent("assistant")

        assert client.post(ISSUE, json={}, headers=BEARER).status_code == 200
        assert held(app) == 1


def test_with_onboarding_off_nothing_is_issued() -> None:
    config = booted(default_agent="assistant")
    config.server.onboarding.enabled = False
    with entered_app(config, from_store=True) as (app, client):
        answer = client.post(ISSUE, json={}, headers=BEARER)

        assert answer.status_code == 409
        problem = answer.json()
        assert problem["detail"] == ONBOARDING_OFF
        assert "reason" not in problem
        assert held(app) == 0


def test_a_server_with_no_store_behind_it_issues_nothing() -> None:
    """A world handed to the server rather than read from a store: a
    browser bound by a link would be written where this server does not
    read its devices from."""
    with entered_app(config_with_agent()) as (app, client):
        answer = client.post(ISSUE, json={}, headers=BEARER)

        assert answer.status_code == 409
        assert answer.json()["detail"] == SNAPSHOT_ONLY
        assert held(app) == 0


def test_a_full_store_refuses_until_one_is_spent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onboarding, "INVITE_CAPACITY", 1)
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        assert client.post(ISSUE, json={}, headers=BEARER).status_code == 200
        refused = client.post(ISSUE, json={}, headers=BEARER)

        assert refused.status_code == 409
        assert refused.json()["detail"] == CAPACITY_REACHED
        assert held(app) == 1


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_issuing_needs_the_bearer_token(headers: dict[str, str]) -> None:
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        answer = client.post(ISSUE, json={}, headers=headers)

        assert answer.status_code == 401
        assert held(app) == 0


def test_an_application_without_a_server_issues_nothing() -> None:
    from fastapi.testclient import TestClient

    with TestClient(build_api(TEST_API_SECRET, DatabaseConfig())) as client:
        answer = client.post(PATH, json={}, headers=BEARER)

    assert answer.status_code == 503
    assert "no running server around it" in answer.json()["detail"]


def test_it_is_an_action_and_not_a_read() -> None:
    with entered_app(booted(default_agent="assistant"), from_store=True) as (_, client):
        assert client.get(ISSUE, headers=BEARER).status_code == 405


def test_the_document_states_the_route_and_its_refusals() -> None:
    operation = document()["paths"][PATH]["post"]
    responses = operation["responses"]

    assert set(responses) >= {"200", "401", "409", "422", "503"}
    assert "default-agent-not-served" in responses["409"]["description"]
    assert "agent-not-serving" in responses["409"]["description"]
    assert "server.onboarding.enabled" in responses["409"]["description"]
    assert "credential" in operation["description"]
    assert responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Invite"
    }
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/InviteRequest"
    }
    assert operation["requestBody"]["required"] is True


def test_the_old_route_is_not_served() -> None:
    """Renamed, not aliased (#612, Q11): the old path answers what any
    path nobody serves answers under the API's gate."""
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        old = client.post("/api/runtime/try-links", json={}, headers=BEARER)
        unserved = client.post("/api/runtime/never-served-by-anything", json={}, headers=BEARER)

        assert old.status_code == 404
        assert old.content == unserved.content
        assert held(app) == 0
    assert "/runtime/try-links" not in document()["paths"]


# --- the agents an invite names (#612, Q11) ----------------------------------


def invite(client, agents: list[str] | None = None):
    body = {} if agents is None else {"agents": agents}
    return client.post(ISSUE, json=body, headers=BEARER)


def test_an_invite_may_name_the_agents_it_binds() -> None:
    config = booted(agents=("assistant", "kids"), default_agent="assistant")
    with entered_app(config, from_store=True) as (app, client):
        answer = invite(client, ["kids"])

        assert answer.status_code == 200, answer.text
        assert PAGE.match(answer.json()["page"])
        assert held(app) == 1


def test_an_invite_naming_its_agents_needs_no_default_agent() -> None:
    """What the default agent is for is an invite that names none, so
    one that names its agents is issued whether or not one is set."""
    with entered_app(booted(agents=("assistant", "kids")), from_store=True) as (app, client):
        assert invite(client, ["kids", "assistant"]).status_code == 200
        assert held(app) == 1


@pytest.mark.parametrize("body", [{}, {"agents": []}])
def test_naming_no_agent_is_the_default_agent(body: dict) -> None:
    with entered_app(booted(), from_store=True) as (app, client):
        refused = client.post(ISSUE, json=body, headers=BEARER)
        assert refused.status_code == 409
        assert refused.json()["reason"] == "default-agent-not-served"

    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        assert client.post(ISSUE, json=body, headers=BEARER).status_code == 200


@pytest.mark.parametrize(
    "agents",
    [["nobody"], ["kids", "nobody"], [""], ["   "], ["sk-live-SENTINEL-agent-name-0000"]],
    ids=["unknown", "one-of-two-unknown", "empty", "blank", "credential-shaped"],
)
def test_an_invite_naming_an_agent_that_does_not_exist_issues_nothing(
    agents: list[str],
) -> None:
    """The store's unknown-agent reason, and a sentence of its own that
    quotes nothing the request carried: an agent name is typed on a
    command line, where a paste can put something else."""
    config = booted(agents=("assistant", "kids"), default_agent="assistant")
    with entered_app(config, from_store=True) as (app, client):
        refused = invite(client, agents)

        assert refused.status_code == 422
        assert refused.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
        problem = refused.json()
        assert problem["detail"] == AGENTS_UNKNOWN
        assert problem["reason"] == "agents-unknown"
        for name in agents:
            if name.strip():
                assert name not in refused.text
        assert held(app) == 0


def test_an_invite_naming_an_agent_this_server_is_not_serving_issues_nothing() -> None:
    """Stored since the server booted and not applied: the agent exists,
    and a browser bound to it would reach an agent nothing answers for,
    so the invite is refused until the apply that installs it."""
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        with store_at() as store:
            store.set_agent("kids", {"prompt": "You are kind."})

        refused = invite(client, ["assistant", "kids"])

        assert refused.status_code == 409
        problem = refused.json()
        assert problem["detail"] == AGENT_NOT_SERVED
        assert problem["reason"] == "agent-not-serving"
        assert "kids" not in problem["detail"]
        assert held(app) == 0


def test_an_agent_served_but_deleted_from_the_store_since_issues_nothing() -> None:
    """Served by the world this server installed, gone from the store
    since: redemption writes the binding to the store, where the name
    would not resolve, so it is an agent this deployment does not
    have."""
    config = booted(agents=("assistant", "kids"), default_agent="assistant")
    with entered_app(config, from_store=True) as (app, client):
        with store_at() as store:
            store.delete_agent("kids")

        refused = invite(client, ["kids"])

        assert refused.status_code == 422
        assert refused.json()["reason"] == "agents-unknown"
        assert held(app) == 0


@pytest.mark.parametrize(
    "body",
    [
        {"agents": "kids"},
        {"agents": [1]},
        {"agents": None},
        {"agent": ["kids"]},
        {"agents": ["kids"], "more": True},
        ["kids"],
        "kids",
    ],
    ids=["a-string", "a-number", "null", "another-key", "an-extra-key", "a-list", "a-bare-string"],
)
def test_a_body_that_is_not_an_invite_issues_nothing(body: object) -> None:
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        refused = client.post(ISSUE, json=body, headers=BEARER)

        assert refused.status_code == 422
        assert "kids" not in refused.text
        assert held(app) == 0


def test_a_request_that_lost_its_body_issues_nothing() -> None:
    """Required rather than read as naming none: a body lost on the way
    would otherwise bind the browser to the default agent rather than to
    the agents it named."""
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        refused = client.post(ISSUE, headers=BEARER)

        assert refused.status_code == 422
        assert held(app) == 0


# --- which origin the link names (D5c, the server's half) ------------


@pytest.mark.parametrize(
    ("public_url", "named"),
    [
        ("https://voice.example", "https://voice.example"),
        ("https://voice.example/vinga", "https://voice.example/vinga"),
        ("http://localhost:8003", "http://localhost:8003"),
        ("http://127.0.0.1:8003", "http://127.0.0.1:8003"),
        ("http://[::1]:8003", "http://[::1]:8003"),
        ("http://192.168.1.10:8003", None),
        ("http://voice.example", None),
    ],
)
def test_the_configured_origin_is_named_only_when_it_is_a_secure_context(
    public_url: str, named: str | None
) -> None:
    assert link_origin(ServerConfig(public_url=public_url)) == named


def test_with_no_public_url_no_origin_is_named_whatever_the_server_listens_on() -> None:
    """Never the listen address, which is a guess, and never the origin
    a websocket URL implies, which is a key with another job."""
    assert link_origin(ServerConfig(host="0.0.0.0")) is None
    assert link_origin(ServerConfig(host="127.0.0.1")) is None
    assert link_origin(ServerConfig(websocket_url="wss://voice.example/xiaozhi/v1/")) is None


def test_the_answer_carries_the_configured_origin() -> None:
    config = booted(default_agent="assistant")
    config.server.public_url = "https://vinga.test.invalid"
    with entered_app(config, from_store=True) as (_, client):
        body = client.post(ISSUE, json={}, headers=BEARER).json()

    assert body["origin"] == "https://vinga.test.invalid"
