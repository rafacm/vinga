"""Redeeming an invite link from the page (#613, D5, D5b, D5d, D5e).

The link is `<origin>/try/#<token>`. A fragment never reaches a server,
so `GET /try/` is the same inert page for everybody and spends nothing:
a link preview, a prefetch or a scanner fetching it learns nothing and
uses nothing up. The page's script reads the fragment, clears it, and
redeems the token with a same-origin `POST /try/redeem`, which spends
it, mints an identity, writes the device bound to the default agent and
named in one transaction, and answers the identity and the onboarding
path the browser checks in at.

Every way of not redeeming answers one fixed refusal, byte for byte: a
token never issued, one expired, one spent, one presented from another
origin, a body that is not one. A refusal from another origin, or of a
body that is not one, spends nothing.

The deployments are real: a store written through the repository, a
server composed from it with bindings read live, the link issued
through the configuration API as `vinga info` issues it.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

import vinga_server.onboarding as onboarding
from tests.conftest import TEST_API_SECRET
from tests.support.apps import entered_app
from tests.support.checkin import SYSTEM_INFO
from tests.support.deployment import served
from tests.support.leaks import renderings
from tests.support.registry import booted, store_at
from vinga_server.app import create_app
from vinga_server.browser import REDEEM_PATH, REDEEM_REFUSED
from vinga_server.config.loader import StorageError
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.store import ConfigStore, read_live_attachment
from vinga_server.db import read_engine
from vinga_server.memory.store import PromptMemory
from vinga_server.onboarding import onboarding_key, onboarding_path
from vinga_server.onboarding.browser import CLIENT_ID_NAMESPACE
from vinga_server.onboarding.invites import (
    SPENT_ALL_TAKEN,
    SPENT_UNENROLLED,
    Invites,
    redeem,
)
from vinga_server.runtime import prompt

ISSUE = "/api/runtime/invites"
BEARER = {"Authorization": f"Bearer {TEST_API_SECRET}"}

# What a browser sends with a fetch from its own page, which is the one
# fact the redeem route asks of the request's provenance.
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


def token_of(client: TestClient, agents: list[str] | None = None) -> str:
    """One link, issued the way `vinga device invite` issues it, naming
    these agents or none, and its token read out of the fragment the way
    the page reads it."""
    issued = client.post(ISSUE, json={} if agents is None else {"agents": agents}, headers=BEARER)
    assert issued.status_code == 200, issued.text
    page = issued.json()["page"]
    assert page.startswith("/try/#")
    return page.removeprefix("/try/#")


def redeemed(client: TestClient, token: object, headers: dict[str, str] = SAME_ORIGIN):
    return client.post(REDEEM_PATH, json={"token": token}, headers=headers)


def browsers() -> dict[str, list[str]]:
    """Every device named as an invite link names one, by MAC, with what
    it is bound to, read from the store underneath the server."""
    with store_at() as store:
        devices = store.load().domain.devices
    return {
        mac: list(record.agents)
        for mac, record in devices.items()
        if (record.name or "").startswith("Browser ")
    }


@contextmanager
def deployment(
    default_agent: str | None = "assistant", agents: tuple[str, ...] = ("assistant",)
) -> Iterator[tuple[object, TestClient]]:
    config = booted(agents=agents, default_agent=default_agent)
    with entered_app(config, from_store=True) as entered:
        yield entered


# --- the redemption -------------------------------------------------------


def test_redeeming_binds_and_names_a_new_browser_before_its_first_word() -> None:
    with deployment() as (app, client):
        answer = redeemed(client, token_of(client))

        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert set(body) == {"mac", "client_id", "onboarding_path"}
        first = int(body["mac"].split(":")[0], 16)
        assert first & 0x02 and not first & 0x01
        assert body["client_id"] == str(uuid.uuid5(CLIENT_ID_NAMESPACE, body["mac"]))
        # Relative to the deployment's root, which for a deployment with
        # no prefix in front of it is the server's own.
        assert "/" + body["onboarding_path"] == onboarding_path(
            onboarding_key(app.state.composition.server)
        )
        assert browsers() == {body["mac"]: ["assistant"]}
        with store_at() as store:
            assert store.read_device(body["mac"]).entry.name == f"Browser {body['mac']}"

        # And its first check-in, at the path it was handed, is a bound
        # device's: a token, and no code to claim.
        reply = client.post(
            "/" + body["onboarding_path"],
            json={**SYSTEM_INFO, "board": {"type": "vinga-browser"}},
            headers={"Device-Id": body["mac"], "Client-Id": body["client_id"]},
        )
        assert reply.status_code == 200
        assert reply.json()["websocket"]["token"]
        assert "activation" not in reply.json()


# --- the agents an invite named (#612, Q11) ---------------------------------


def test_redeeming_binds_exactly_the_agents_the_invite_named() -> None:
    """Not the default agent, which is set and is another agent: the
    names rode with the token from the issuance that checked them."""
    with deployment(agents=("assistant", "kids", "guest")) as (_, client):
        kids = redeemed(client, token_of(client, ["kids", "guest"])).json()
        default = redeemed(client, token_of(client)).json()

        assert browsers() == {kids["mac"]: ["kids", "guest"], default["mac"]: ["assistant"]}


def test_named_agents_are_bound_though_the_default_was_cleared_since() -> None:
    with deployment(agents=("assistant", "kids")) as (_, client):
        token = token_of(client, ["kids"])
        with store_at() as store:
            store.clear_default_agent()

        answer = redeemed(client, token)

        assert answer.status_code == 200
        assert browsers() == {answer.json()["mac"]: ["kids"]}


def test_a_named_agent_deleted_since_issuance_binds_nothing() -> None:
    """The names are re-read inside the redemption's one transaction, so
    an agent deleted between the two is the one race issuance cannot
    rule out: the same refusal, the link spent, and nothing written."""
    with deployment(agents=("assistant", "kids")) as (app, client):
        token = token_of(client, ["kids"])
        with store_at() as store:
            store.delete_agent("kids")

        answer = redeemed(client, token)

        assert answer.status_code == 403
        assert answer.json() == {"error": REDEEM_REFUSED}
        assert browsers() == {}
        assert app.state.composition.invites.held == 0


def test_the_answer_is_kept_by_nobody_but_the_page() -> None:
    with deployment() as (_, client):
        answer = redeemed(client, token_of(client))

    assert answer.headers["cache-control"] == "no-store"
    assert answer.headers["referrer-policy"] == "no-referrer"
    assert answer.headers["x-content-type-options"] == "nosniff"


def test_the_answer_does_not_echo_the_token() -> None:
    with deployment() as (_, client):
        token = token_of(client)
        answer = redeemed(client, token)

    assert token not in answer.text
    assert token not in json.dumps(dict(answer.headers))


def test_a_link_binds_once() -> None:
    with deployment() as (_, client):
        token = token_of(client)
        first = redeemed(client, token)
        second = redeemed(client, token)

    assert first.status_code == 200
    assert second.status_code == 403
    assert second.json() == {"error": REDEEM_REFUSED}
    assert list(browsers()) == [first.json()["mac"]]


def refusal(answer: httpx.Response) -> tuple[int, bytes, str | None, str | None]:
    return (
        answer.status_code,
        answer.content,
        answer.headers.get("content-type"),
        answer.headers.get("cache-control"),
    )


def test_unknown_expired_and_spent_tokens_are_one_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with deployment() as (_, client):
        spent = token_of(client)
        assert redeemed(client, spent).status_code == 200
        monkeypatch.setattr(onboarding, "INVITE_TTL_S", 0.0)
        expired = token_of(client)

        answers = [
            refusal(redeemed(client, "A" * 43)),
            refusal(redeemed(client, expired)),
            refusal(redeemed(client, spent)),
        ]

    assert answers[0][0] == 403
    assert json.loads(answers[0][1]) == {"error": REDEEM_REFUSED}
    assert answers[0] == answers[1] == answers[2]


def test_fetching_the_page_spends_nothing() -> None:
    """What a link preview, a prefetch or a scanner does with the link:
    a GET of the page, which is all a fragment-bearing URL ever sends.
    The token is still there for the person who opens it."""
    with deployment() as (app, client):
        token = token_of(client)
        for path in ("/try/", "/try"):
            page = client.get(path, headers={"Purpose": "prefetch"})
            assert page.status_code == 200
            assert token not in page.text
        assert app.state.composition.invites.held == 1

        assert redeemed(client, token).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Sec-Fetch-Site": "none"},
        # No fetch metadata at all, whatever `Origin` says: not a
        # browser on this page.
        {"Origin": "https://somebody-else.example"},
        {"Origin": "http://testserver.example"},
        {},
        # The metadata decides, and an `Origin` beside it changes
        # nothing.
        {"Sec-Fetch-Site": "cross-site", "Origin": "http://testserver"},
        {"Origin": "null"},
    ],
)
def test_a_redemption_from_anywhere_but_the_page_s_origin_spends_nothing(
    headers: dict[str, str],
) -> None:
    with deployment() as (_, client):
        token = token_of(client)
        refused = redeemed(client, token, headers)

        assert refused.status_code == 403
        assert refused.json() == {"error": REDEEM_REFUSED}
        assert browsers() == {}
        assert redeemed(client, token).status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        # The host the request reached, on the scheme it reached it on.
        "http://testserver",
        # The same host on another scheme: a page on `http://host`
        # posting to `https://host` is another origin, and an authority
        # comparison cannot tell, which is why `Origin` decides nothing.
        "https://testserver",
    ],
)
def test_an_origin_header_without_fetch_metadata_is_not_enough(origin: str) -> None:
    """Only the browser's own `Sec-Fetch-Site: same-origin` admits a
    redemption. Every engine that can run the client (WebCodecs Opus:
    Chromium 94+, Firefox 130+, Safari 26) sends fetch metadata, so a
    request without it is not this page, whatever `Origin` it names. It
    spends nothing."""
    with deployment() as (_, client):
        token = token_of(client)
        refused = redeemed(client, token, {"Origin": origin})

        assert refused.status_code == 403
        assert refused.json() == {"error": REDEEM_REFUSED}
        assert browsers() == {}
        assert redeemed(client, token).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b'"a bare string"',
        b"{}",
        b'{"token": 42}',
        b'{"token": null}',
        b'{"code": "123456"}',
        b"{" + b'"token": "' + b"x" * 5000 + b'"}',
    ],
    ids=[
        "empty",
        "not-json",
        "a-list",
        "a-string",
        "no-token",
        "a-number",
        "null",
        "another-member",
        "too-long",
    ],
)
def test_a_body_that_is_not_a_token_is_the_same_refusal_and_spends_nothing(
    body: bytes,
) -> None:
    with deployment() as (app, client):
        token_of(client)
        refused = client.post(
            REDEEM_PATH,
            content=body,
            headers={**SAME_ORIGIN, "Content-Type": "application/json"},
        )

        assert refused.status_code == 403
        assert refused.json() == {"error": REDEEM_REFUSED}
        assert app.state.composition.invites.held == 1
        assert browsers() == {}


def test_a_long_body_is_not_read_to_its_end() -> None:
    """A redemption is a few dozen bytes, so the route stops reading at
    a bound and refuses: a client streaming megabytes at an
    unauthenticated route costs this server a kilobyte. Driven at the
    application's own ASGI interface, with a body that counts how much
    of it was asked for."""
    chunk = b"x" * 1024
    offered = 100
    pulled: list[int] = []
    sent: list[dict] = []

    async def receive() -> dict:
        pulled.append(1)
        more = len(pulled) < offered
        return {"type": "http.request", "body": chunk, "more_body": more}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": REDEEM_PATH,
        "raw_path": REDEEM_PATH.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"sec-fetch-site", b"same-origin"),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    with deployment() as (app, _):
        asyncio.run(app(scope, receive, send))

    start = next(message for message in sent if message["type"] == "http.response.start")
    assert start["status"] == 403
    assert len(pulled) <= 2


def test_a_default_agent_cleared_since_issuance_binds_nothing() -> None:
    """The one race issuance cannot rule out (D5a): the link was issued
    against a default agent that is gone by the time it is opened. The
    same refusal, the link spent, and nothing written."""
    with deployment() as (app, client):
        token = token_of(client)
        with store_at() as store:
            store.clear_default_agent()

        answer = redeemed(client, token)

        assert answer.status_code == 403
        assert answer.json() == {"error": REDEEM_REFUSED}
        assert browsers() == {}
        assert app.state.composition.invites.held == 0


def test_a_restart_ends_every_unredeemed_link() -> None:
    """The links live in the process, so a second server on the same
    store, which is what a restart or an upgrade is, has never heard of
    one the first issued (D5e)."""
    config = booted(default_agent="assistant")
    with TestClient(create_app(config, from_store=True)) as before:
        token = token_of(before)

    with TestClient(create_app(config, from_store=True)) as after:
        answer = redeemed(after, token)

    assert answer.status_code == 403
    assert answer.json() == {"error": REDEEM_REFUSED}
    assert browsers() == {}


def test_nothing_is_redeemed_with_onboarding_off() -> None:
    config = booted(default_agent="assistant")
    config.server.onboarding.enabled = False
    with entered_app(config, from_store=True) as (_, client):
        answer = redeemed(client, "A" * 43)
        unserved = client.post("/never-served-by-anything")

    assert answer.status_code == 404
    assert answer.content == unserved.content


@pytest.mark.parametrize("path", [REDEEM_PATH, REDEEM_PATH + "/"])
def test_both_spellings_redeem(path: str) -> None:
    with deployment() as (_, client):
        answer = client.post(path, json={"token": token_of(client)}, headers=SAME_ORIGIN)

    assert answer.status_code == 200


def test_redeeming_is_a_post() -> None:
    with deployment() as (_, client):
        assert client.get(REDEEM_PATH).status_code == 405


# --- a MAC that is already taken (D5b) -------------------------------------


def repeating(*octets: bytes):
    """Randomness that answers these six-byte draws in order, the last
    one forever."""
    draws = list(octets)

    def draw(length: int) -> bytes:
        assert length == 6
        return draws.pop(0) if len(draws) > 1 else draws[0]

    return draw


TAKEN = bytes([0x02, 0x11, 0x22, 0x33, 0x44, 0x55])
FREE = bytes([0x02, 0x66, 0x77, 0x88, 0x99, 0xAA])


def test_a_minted_mac_that_is_taken_is_drawn_again() -> None:
    booted(default_agent="assistant")
    with store_at() as store:
        store.bind_device("02:11:22:33:44:55", ["assistant"])
        links = Invites()
        token = links.issue()

        identity = asyncio.run(redeem(links, token, store, repeating(TAKEN, FREE)))

        assert identity is not None
        assert identity.mac == "02:66:77:88:99:aa"
        assert store.read_device(identity.mac).entry.name == f"Browser {identity.mac}"
        # The taken device is as it was: refused rather than merged.
        assert store.read_device("02:11:22:33:44:55").entry.name == "Device 02:11:22:33:44:55"


def test_a_redemption_that_never_draws_a_free_mac_writes_nothing() -> None:
    booted(default_agent="assistant")
    with store_at() as store:
        store.bind_device("02:11:22:33:44:55", ["assistant"])
        before = store.load().domain.devices
        links = Invites()
        token = links.issue()

        identity = asyncio.run(redeem(links, token, store, repeating(TAKEN)))

        assert identity is None
        assert store.load().domain.devices == before
        assert links.held == 0


def test_the_draws_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onboarding, "INVITE_MINTS", 2)
    booted(default_agent="assistant")
    drawn: list[int] = []

    def taken(length: int) -> bytes:
        drawn.append(length)
        return TAKEN

    with store_at() as store:
        store.bind_device("02:11:22:33:44:55", ["assistant"])
        links = Invites()
        assert asyncio.run(redeem(links, links.issue(), store, taken)) is None

    assert drawn == [6, 6]


def test_a_redeemed_browser_is_not_introduced_by_its_mac() -> None:
    """The name a link gives a browser is a placeholder the server
    minted, exactly as `Device <mac>` is for a board, and the agent is
    told the name of the device it speaks through. Read the way a
    connect reads it and put in a prompt the way a reply builds one, it
    has to say nothing, or a model asked which speaker it is reads a MAC
    address aloud."""
    booted(default_agent="assistant")
    with store_at() as store:
        links = Invites()
        identity = asyncio.run(redeem(links, links.issue(), store, repeating(FREE)))
    assert identity is not None
    engine = read_engine(DatabaseConfig())
    try:
        device = read_live_attachment(engine, identity.mac).device
    finally:
        engine.dispose()
    assert device is not None and device.name == f"Browser {identity.mac}"

    sent = prompt.with_scopes(
        prompt.know_how("POET"),
        PromptMemory(state="", agent="", device=""),
        device,
        remembering=False,
    )

    assert identity.mac not in sent.text
    assert device.named is False


def test_a_refusal_that_is_not_a_collision_is_not_drawn_again() -> None:
    """Only a taken MAC is worth another draw: a default agent cleared
    since the link was issued refuses every MAC alike, so the first
    refusal is the answer."""
    booted()
    drawn: list[int] = []

    def counted(length: int) -> bytes:
        drawn.append(length)
        return FREE

    with store_at() as store:
        links = Invites()
        assert asyncio.run(redeem(links, links.issue(), store, counted)) is None

    assert drawn == [6]


# --- one redemption wins (D5d) -------------------------------------------


CONTENDERS = 8


async def _contend(origin: str, token: str) -> list[int]:
    async with httpx.AsyncClient(base_url=origin) as client:
        answers = await asyncio.gather(
            *(
                client.post(REDEEM_PATH, json={"token": token}, headers=SAME_ORIGIN)
                for _ in range(CONTENDERS)
            )
        )
    return sorted(answer.status_code for answer in answers)


async def _redeemed_together(links: Invites, token: str, store) -> list[object]:
    return await asyncio.gather(*(redeem(links, token, store) for _ in range(CONTENDERS)))


def test_of_redemptions_started_together_exactly_one_binds() -> None:
    """The claim's atomicity, driven where it is decided, and driven
    every time: `gather` starts every redemption before any of them
    resumes from its first await, so each has made its claim before the
    first winner's write returns. A claim that checked, awaited, and
    only then marked would let every one of them through, and this is
    the case that would say so on every run rather than on the runs
    whose requests happened to overlap."""
    booted(default_agent="assistant")
    with store_at() as store:
        links = Invites()
        token = links.issue()

        outcomes = asyncio.run(_redeemed_together(links, token, store))

    assert sum(outcome is not None for outcome in outcomes) == 1
    assert len(browsers()) == 1


def test_of_concurrent_redemptions_exactly_one_binds() -> None:
    """Several redemptions of one token in flight at once, on a real
    server on a real port, so they interleave wherever the handler
    awaits. Exactly one is answered with an identity and binds; every
    other is the refusal and writes nothing. Whether they overlap is up
    to the network, which is why the case above drives the same claim
    deterministically."""
    app = create_app(booted(default_agent="assistant"), from_store=True)
    with served(app) as live:
        issued = httpx.post(f"{live.origin}{ISSUE}", json={}, headers=BEARER)
        token = issued.json()["page"].removeprefix("/try/#")

        statuses = asyncio.run(_contend(live.origin, token))

    assert statuses == [200] + [403] * (CONTENDERS - 1)
    assert len(browsers()) == 1


# --- a spent link that bound nothing is said, by its class only ------------

PLANTED_TOKEN = "aW52LXNlbnRpbmVsLW5ldmVyLWEtcmVhbC10b2tlbiE"
MINTED_MAC = "02:66:77:88:99:aa"
INVITES_LOGGER = "vinga_server.onboarding.invites"


def warnings_of(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == INVITES_LOGGER and record.levelno == logging.WARNING
    ]


@pytest.mark.parametrize(
    "failure",
    [
        StorageError("the configuration database could not be written"),
        RuntimeError(f"the layer below said {PLANTED_TOKEN} about {MINTED_MAC}"),
    ],
    ids=["StorageError", "RuntimeError-carrying-the-token"],
)
def test_a_spent_link_that_bound_nothing_is_logged_by_its_failure_class(
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The token is spent and nothing was written, which the browser is
    told and the operator would otherwise not be. One WARNING, a fixed
    sentence and the failure's class as its one argument: never its
    message, the token or the MAC."""

    def failing(self: ConfigStore, mac: str, name: str, agents: object = ()) -> None:
        raise failure

    booted(default_agent="assistant")
    monkeypatch.setattr(ConfigStore, "enroll_device", failing)
    with store_at() as store, caplog.at_level(logging.DEBUG):
        links = Invites(randomness=lambda length: b"inv-sentinel-never-a-real-token!")
        token = links.issue()
        assert token == PLANTED_TOKEN
        identity = asyncio.run(redeem(links, token, store, repeating(FREE)))

    assert identity is None
    (record,) = warnings_of(caplog)
    assert record.msg == SPENT_UNENROLLED
    assert record.args == (type(failure).__name__,)
    assert record.exc_info is None
    rendered = "\n".join(renderings(caplog))
    assert token not in rendered
    assert MINTED_MAC not in rendered
    assert MINTED_MAC.replace(":", "") not in rendered
    assert "the layer below said" not in rendered


def test_a_spent_link_whose_every_draw_was_taken_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    booted(default_agent="assistant")
    with store_at() as store, caplog.at_level(logging.DEBUG):
        store.bind_device("02:11:22:33:44:55", ["assistant"])
        links = Invites()
        assert asyncio.run(redeem(links, links.issue(), store, repeating(TAKEN))) is None

    (record,) = warnings_of(caplog)
    assert record.msg == SPENT_ALL_TAKEN
    assert record.args == ()
    assert "02:11:22:33:44:55" not in "\n".join(renderings(caplog))


def test_a_redraw_that_then_binds_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    booted(default_agent="assistant")
    with store_at() as store, caplog.at_level(logging.DEBUG):
        store.bind_device("02:11:22:33:44:55", ["assistant"])
        links = Invites()
        assert asyncio.run(redeem(links, links.issue(), store, repeating(TAKEN, FREE)))

    assert warnings_of(caplog) == []


def test_a_link_that_was_never_live_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """An unknown, expired or spent token is a refusal a browser is
    told; nothing was spent by it, so there is nothing to say."""
    booted(default_agent="assistant")
    with store_at() as store, caplog.at_level(logging.DEBUG):
        assert asyncio.run(redeem(Invites(), "A" * 43, store)) is None

    assert warnings_of(caplog) == []
