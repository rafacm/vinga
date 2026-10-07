"""A browser identity that cannot be minted, on both routes that mint one.

Minting draws six bytes from the operating system's generator. Whatever
that draw raises, on `POST /talk/redeem` and on
`POST /x/<key>/browser-identity`, is contained: the browser gets a fixed
answer, the operator one WARNING carrying the failure's class and
nothing else of it, and nothing escapes the handler, since the parent
application has no sanitized boundary that would turn an escaping
exception into anything but a traceback (#612, M1b review round).

The failure here quotes a sentinel, the worst a library under the
minter could do, and the sentinel is hunted in the answer, in both log
formats, and in the chain of anything that escaped.
"""

import asyncio
import logging
import secrets

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_API_SECRET
from tests.support.leaks import chain, renderings
from tests.support.registry import booted, store_at
from vinga_server.app import create_app
from vinga_server.browser import IDENTITY_UNAVAILABLE, REDEEM_PATH, REDEEM_REFUSED
from vinga_server.events.catalog import GENERATION_CHANNEL
from vinga_server.onboarding import onboarding_key, onboarding_path
from vinga_server.onboarding.invites import SPENT_UNENROLLED, Invites, redeem

SENTINEL = "sk-live-MINT-FAILURE-SENTINEL-0000"
BEARER = {"Authorization": f"Bearer {TEST_API_SECRET}"}
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
MAC_BYTES = 6


def failing(length: int) -> bytes:
    raise RuntimeError(f"the generator said {SENTINEL}")


@pytest.fixture
def broken_mac_draw(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operating system's generator failing for a MAC's six bytes
    alone, so an invite's token, thirty-two of them, is still drawn."""
    real = secrets.token_bytes

    def draw(length: int | None = None) -> bytes:
        if length == MAC_BYTES:
            failing(length)
        return real(length)

    monkeypatch.setattr(secrets, "token_bytes", draw)


def browsers() -> list[str]:
    with store_at() as store:
        devices = store.load().domain.devices
    return [mac for mac, record in devices.items() if (record.name or "").startswith("Browser ")]


def warnings_of(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The warnings the mint's failure produced, which leaves out the one
    the server's boot says about the world it installed (#612): this
    world does not serve the built-in agent, and that is about the world
    rather than about the mint."""
    return [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and record.name != GENERATION_CHANNEL
    ]


def answered(response: httpx.Response) -> str:
    return response.text + "\n" + repr(dict(response.headers))


def posted(client: TestClient, path: str, **kwargs) -> tuple[httpx.Response | None, list[str]]:
    """The request, and the chain of whatever escaped the application."""
    try:
        return client.post(path, **kwargs), []
    except Exception as failure:
        return None, [chain(failure)]


def test_the_redemption_contains_a_mint_that_fails(caplog: pytest.LogCaptureFixture) -> None:
    """Driven where the redemption decides: the link is spent, nothing
    is bound, nothing is raised, and the one WARNING carries the class."""
    booted(default_agent="assistant")
    with store_at() as store, caplog.at_level(logging.DEBUG):
        links = Invites()
        token = links.issue()

        identity = asyncio.run(redeem(links, token, store, failing))

        assert identity is None
        assert links.held == 0
    assert browsers() == []
    (record,) = warnings_of(caplog)
    assert record.msg == SPENT_UNENROLLED
    assert record.args == ("RuntimeError",)
    assert record.exc_info is None
    assert SENTINEL not in "\n".join(renderings(caplog))


@pytest.mark.usefixtures("broken_mac_draw")
def test_the_redeem_route_answers_its_refusal_when_the_mint_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        app = create_app(booted(default_agent="assistant"), from_store=True)
        with TestClient(app) as client:
            issued = client.post("/api/runtime/invites", json={}, headers=BEARER)
            token = issued.json()["page"].partition("#")[2]
            answer, escaped = posted(
                client, REDEEM_PATH, json={"token": token}, headers=SAME_ORIGIN
            )
            held = app.state.composition.invites.held

    assert escaped == [], escaped
    assert answer is not None and answer.status_code == 403
    assert answer.json() == {"error": REDEEM_REFUSED}
    assert SENTINEL not in answered(answer)
    assert SENTINEL not in "\n".join(renderings(caplog))
    assert held == 0
    assert browsers() == []
    assert [record.args for record in warnings_of(caplog)] == [("RuntimeError",)]


@pytest.mark.usefixtures("broken_mac_draw")
def test_the_identity_route_answers_a_fixed_refusal_when_the_mint_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        with TestClient(create_app(booted(), from_store=True)) as client:
            alias = onboarding_path(onboarding_key(client.app.state.composition.server))
            answer, escaped = posted(client, f"{alias}browser-identity")

    assert escaped == [], escaped
    assert answer is not None and answer.status_code == 503
    assert answer.json() == {"error": IDENTITY_UNAVAILABLE}
    assert answer.headers["cache-control"] == "no-store"
    assert SENTINEL not in answered(answer)
    assert SENTINEL not in "\n".join(renderings(caplog))
    (record,) = warnings_of(caplog)
    assert record.args == ("RuntimeError",)
    assert record.exc_info is None
    assert browsers() == []
