"""Issuing a try link from the configuration API (#613, D5, D5a, D5c, D6b).

`POST /api/runtime/try-links` mints a token behind the operator's bearer
token and answers it inside the page's path, `/try/#<token>`, with the
origin the link should name when this server's configuration states one
that opens a secure context. It refuses, with nothing minted, in each
state where opening the link could not do what it promises: onboarding
off, no store behind the served world, no default agent to bind to, and
a store already holding as many links as it will.

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
from vinga_server.onboarding.try_links import (
    CAPACITY_REACHED,
    NO_DEFAULT_AGENT,
    ONBOARDING_OFF,
    SNAPSHOT_ONLY,
    link_origin,
)

PATH = "/runtime/try-links"
ISSUE = f"/api{PATH}"
BEARER = {"Authorization": f"Bearer {TEST_API_SECRET}"}

PAGE = re.compile(r"^/try/#([A-Za-z0-9_-]{43})$")


def held(app) -> int:
    return app.state.composition.try_links.held


def test_a_link_is_issued_into_the_page_s_fragment() -> None:
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        answer = client.post(ISSUE, headers=BEARER)

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
        answer = client.post(ISSUE, headers=BEARER)

    assert answer.headers["cache-control"] == "no-store"


def test_each_request_is_a_new_link() -> None:
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        first = client.post(ISSUE, headers=BEARER).json()["page"]
        second = client.post(ISSUE, headers=BEARER).json()["page"]

        assert first != second
        assert held(app) == 2


def test_with_no_default_agent_nothing_is_issued_and_the_state_is_named() -> None:
    with entered_app(booted(), from_store=True) as (app, client):
        answer = client.post(ISSUE, headers=BEARER)

        assert answer.status_code == 409
        assert answer.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
        problem = answer.json()
        assert problem["detail"] == NO_DEFAULT_AGENT
        assert problem["reason"] == "no-default-agent"
        assert held(app) == 0


def test_the_default_agent_is_read_as_it_stands_now() -> None:
    """Set while the server runs, with no restart and no apply: the
    issuance asks the store, as a check-in asks the bindings."""
    with entered_app(booted(), from_store=True) as (app, client):
        assert client.post(ISSUE, headers=BEARER).status_code == 409

        with store_at() as store:
            store.set_default_agent("assistant")

        assert client.post(ISSUE, headers=BEARER).status_code == 200
        assert held(app) == 1


def test_with_onboarding_off_nothing_is_issued() -> None:
    config = booted(default_agent="assistant")
    config.server.onboarding.enabled = False
    with entered_app(config, from_store=True) as (app, client):
        answer = client.post(ISSUE, headers=BEARER)

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
        answer = client.post(ISSUE, headers=BEARER)

        assert answer.status_code == 409
        assert answer.json()["detail"] == SNAPSHOT_ONLY
        assert held(app) == 0


def test_a_full_store_refuses_until_one_is_spent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onboarding, "TRY_LINK_CAPACITY", 1)
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        assert client.post(ISSUE, headers=BEARER).status_code == 200
        refused = client.post(ISSUE, headers=BEARER)

        assert refused.status_code == 409
        assert refused.json()["detail"] == CAPACITY_REACHED
        assert held(app) == 1


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_issuing_needs_the_bearer_token(headers: dict[str, str]) -> None:
    with entered_app(booted(default_agent="assistant"), from_store=True) as (app, client):
        answer = client.post(ISSUE, headers=headers)

        assert answer.status_code == 401
        assert held(app) == 0


def test_an_application_without_a_server_issues_nothing() -> None:
    from fastapi.testclient import TestClient

    with TestClient(build_api(TEST_API_SECRET, DatabaseConfig())) as client:
        answer = client.post(PATH, headers=BEARER)

    assert answer.status_code == 503
    assert "no running server around it" in answer.json()["detail"]


def test_it_is_an_action_and_not_a_read() -> None:
    with entered_app(booted(default_agent="assistant"), from_store=True) as (_, client):
        assert client.get(ISSUE, headers=BEARER).status_code == 405


def test_the_document_states_the_route_and_its_refusals() -> None:
    operation = document()["paths"][PATH]["post"]
    responses = operation["responses"]

    assert set(responses) >= {"200", "401", "409", "503"}
    assert "no-default-agent" in responses["409"]["description"]
    assert "server.onboarding.enabled" in responses["409"]["description"]
    assert "credential" in operation["description"]
    assert responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TryLink"
    }


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
        body = client.post(ISSUE, headers=BEARER).json()

    assert body["origin"] == "https://vinga.test.invalid"
