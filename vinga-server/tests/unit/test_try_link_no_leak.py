"""What a try link's token may reach (#613, D7a).

The token is a secret. It appears in exactly two places this server
handles: the issuance response to the operator's authenticated request,
and the inbound body of `POST /try/redeem`. (The third, the operator's
own terminal, is `vinga info`'s stdout, held in the CLI's suite.) It
reaches no log record in either format and no record's fields, no event
a server tap is handed, no other response body or header, no exception,
and nothing after it is spent.

The sentinel is planted where a real token comes from: the operating
system's randomness, read by the server's own store of links, so what is
hunted for is the token this server really issued. Thirty-two bytes
whose urlsafe base64 cannot occur by accident.

The browser's identity minted by a redemption is device metadata, which
a board's events already carry in their own fields once it checks in.
The redemption itself is not a device event, so the MAC it mints reaches
no record either: the first record to name it is the check-in's, exactly
as for a board.
"""

import base64
import json
import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_API_SECRET
from tests.support.apps import entered_app
from tests.support.leaks import renderings
from tests.support.registry import booted, store_at
from vinga_server.browser import REDEEM_PATH
from vinga_server.config.loader import StorageError
from vinga_server.config.store import ConfigStore
from vinga_server.events import Emission, attach_server_tap, detach_server_tap

PLANTED = b"try-sentinel-never-a-real-token!"
assert len(PLANTED) == 32
SENTINEL = base64.urlsafe_b64encode(PLANTED).rstrip(b"=").decode()

ISSUE = "/api/runtime/try-links"
BEARER = {"Authorization": f"Bearer {TEST_API_SECRET}"}
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


class Tap:
    """Everything a server-scope consumer is handed, rendered."""

    def __init__(self) -> None:
        self.seen: list[Emission] = []

    def emit(self, emission: Emission) -> None:
        self.seen.append(emission)

    def rendered(self) -> str:
        return "\n".join(f"{one.payload!r}\n{one.message}\n{one.args!r}" for one in self.seen)


@pytest.fixture
def tap() -> Iterator[Tap]:
    consumer = Tap()
    attach_server_tap(consumer)
    try:
        yield consumer
    finally:
        detach_server_tap(consumer)


@pytest.fixture(autouse=True)
def planted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token's thirty-two bytes are the sentinel; every other draw
    (a minted MAC's six) is the operating system's."""
    real = secrets.token_bytes

    def draw(length: int | None = None) -> bytes:
        return PLANTED if length == 32 else real(length)

    monkeypatch.setattr(secrets, "token_bytes", draw)


def everywhere(caplog: pytest.LogCaptureFixture, tap: Tap) -> str:
    return "\n".join(renderings(caplog)) + "\n" + tap.rendered()


def answered(response: httpx.Response) -> str:
    return response.text + "\n" + json.dumps(dict(response.headers))


@contextmanager
def deployment() -> Iterator[tuple[object, TestClient]]:
    with entered_app(booted(default_agent="assistant"), from_store=True) as entered:
        yield entered


def test_the_token_is_answered_by_the_issuance_alone(
    caplog: pytest.LogCaptureFixture, tap: Tap
) -> None:
    """Issued, redeemed, checked in with, connected with, and read back
    through every API read an operator might make afterwards: the token
    is in the issuance response and nowhere else."""
    with caplog.at_level(logging.DEBUG), deployment() as (_, client):
        issued = client.post(ISSUE, headers=BEARER)
        assert SENTINEL in issued.text, "the plant did not take"

        redeemed = client.post(REDEEM_PATH, json={"token": SENTINEL}, headers=SAME_ORIGIN)
        assert redeemed.status_code == 200
        body = redeemed.json()
        checked = client.post(
            "/" + body["onboarding_path"],
            json={"board": {"type": "vinga-browser"}},
            headers={"Device-Id": body["mac"], "Client-Id": body["client_id"]},
        )
        again = client.post(REDEEM_PATH, json={"token": SENTINEL}, headers=SAME_ORIGIN)
        reads = [
            client.get(path, headers=BEARER)
            for path in ("/api/runtime/info", "/api/devices", "/api/config")
        ]
        page = client.get("/try/")

    assert again.status_code == 403
    for response in (redeemed, checked, again, page, *reads):
        assert SENTINEL not in answered(response), response.request.url
    assert SENTINEL not in everywhere(caplog, tap)


@pytest.mark.parametrize(
    "headers",
    [SAME_ORIGIN, {"Sec-Fetch-Site": "cross-site"}, {}],
    ids=["unknown", "cross-origin", "no-origin"],
)
def test_a_refused_redemption_reaches_nothing(
    headers: dict[str, str], caplog: pytest.LogCaptureFixture, tap: Tap
) -> None:
    """Never issued here, so whatever the route does with it is the
    whole of where it could go."""
    with caplog.at_level(logging.DEBUG), deployment() as (_, client):
        refused = client.post(REDEEM_PATH, json={"token": SENTINEL}, headers=headers)

    assert refused.status_code == 403
    assert SENTINEL not in answered(refused)
    assert SENTINEL not in everywhere(caplog, tap)


def test_a_body_that_does_not_parse_reaches_nothing(
    caplog: pytest.LogCaptureFixture, tap: Tap
) -> None:
    """A parser's own sentence quotes what it could not read. The token
    is inside a body that is not JSON, so a route that let the parser's
    words out would carry it."""
    with caplog.at_level(logging.DEBUG), deployment() as (_, client):
        refused = client.post(
            REDEEM_PATH,
            content=f'{{"token": "{SENTINEL}", oops'.encode(),
            headers={**SAME_ORIGIN, "Content-Type": "application/json"},
        )

    assert refused.status_code == 403
    assert SENTINEL not in answered(refused)
    assert SENTINEL not in everywhere(caplog, tap)


def test_a_redemption_the_store_fails_reaches_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tap: Tap
) -> None:
    """The store refusing the write, with a sentence of its own: the
    token was claimed by then and is in the handler's hands, and the
    refusal still carries none of it."""

    def failing(self: ConfigStore, mac: str, name: str) -> None:
        raise StorageError("the configuration database could not be written")

    with caplog.at_level(logging.DEBUG), deployment() as (_, client):
        issued = client.post(ISSUE, headers=BEARER)
        assert SENTINEL in issued.text
        monkeypatch.setattr(ConfigStore, "enroll_device", failing)
        refused = client.post(REDEEM_PATH, json={"token": SENTINEL}, headers=SAME_ORIGIN)

    assert refused.status_code == 403
    assert SENTINEL not in answered(refused)
    assert SENTINEL not in everywhere(caplog, tap)


def test_a_refused_issuance_mints_nothing_to_leak(
    caplog: pytest.LogCaptureFixture, tap: Tap
) -> None:
    with caplog.at_level(logging.DEBUG):
        with entered_app(booted(), from_store=True) as (app, client):
            refused = client.post(ISSUE, headers=BEARER)
            held = app.state.composition.try_links.held

    assert refused.status_code == 409
    assert held == 0
    assert SENTINEL not in answered(refused)
    assert SENTINEL not in everywhere(caplog, tap)


def test_the_redemption_names_the_browser_in_no_record(
    caplog: pytest.LogCaptureFixture, tap: Tap
) -> None:
    """The identity a redemption mints is device metadata, and the
    redemption is not a device event: the MAC first appears in a record
    when the browser checks in, in the fields a board's check-in uses
    (held by `test_browser_no_leak.py`)."""
    with caplog.at_level(logging.DEBUG), deployment() as (_, client):
        token = client.post(ISSUE, headers=BEARER).json()["page"].removeprefix("/try/#")
        body = client.post(REDEEM_PATH, json={"token": token}, headers=SAME_ORIGIN).json()

    with store_at() as store:
        assert store.read_device(body["mac"]).entry.name == f"Browser {body['mac']}"
    rendered = everywhere(caplog, tap)
    assert body["mac"] not in rendered
    assert body["mac"].replace(":", "") not in rendered
    assert body["client_id"] not in rendered
