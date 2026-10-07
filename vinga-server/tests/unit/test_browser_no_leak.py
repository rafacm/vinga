"""What a browser's credential and identity may reach (#613, D7a).

Two classes, each held to the exact places it may appear.

The device token is a secret. A browser presents it as a
`vinga.token.<token>` subprotocol value, which is read and dropped: it
reaches no log record in either format, no record's fields, no event a
server tap is handed, no exception, and never the accepted subprotocol.
Its one other home is the OTA reply's body, which is how its owner gets
it, exactly as a board does.

The browser's MAC and client id are bounded device metadata, which a
board's events already carry. A browser's may appear in exactly the
(event, field) pairs a board's do for the same exchange, and in no
others: the run is made once as a board and once as a browser and the
two sets compared, so a field that carries a browser's identity and not
a board's is a failure rather than a silence.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.support.configs import DEVICE_HELLO, config_with_agent
from tests.support.events import fields_of
from tests.support.leaks import chain, renderings
from vinga_server.app import create_app
from vinga_server.config import Config
from vinga_server.config.models import DeviceRecord
from vinga_server.device.handshake import BROWSER_SUBPROTOCOL
from vinga_server.events import Emission, attach_server_tap, detach_server_tap
from vinga_server.ota import OTA_PATH
from vinga_server.ws import WEBSOCKET_PATH

# Credential-shaped and unmistakable: urlsafe base64, a dot and a
# timestamp, as a real token is, so a substring hunt cannot match by
# accident and a token parser would take it for one.
SENTINEL = "c2stYnJvd3Nlci1zZW50aW5lbC1uZXZlci1hLXJlYWw.1700000000"

BROWSER_MAC = "02:6e:5d:4c:3b:2a"
BROWSER_CLIENT = "7a3c1e9f-2b4d-5a6c-8e0f-1d3b5c7a9e2f"
BOARD_MAC = "aa:bb:cc:dd:ee:01"
BOARD_CLIENT = "5e2d8c1a-7f3b-4e6d-9a0c-2b4f6d8e1a3c"


def bound_config() -> Config:
    """`config_with_agent` with the browser and the board bound too: an
    unbound device only pairs (#612), and these tests follow devices that
    are admitted."""
    config = config_with_agent()
    for mac in (BROWSER_MAC, BOARD_MAC):
        config.devices[mac] = DeviceRecord(agents=["assistant"])
    return config


class Tap:
    """Everything a server-scope consumer is handed, rendered."""

    def __init__(self) -> None:
        self.seen: list[Emission] = []

    def emit(self, emission: Emission) -> None:
        self.seen.append(emission)

    def rendered(self) -> str:
        return "\n".join(
            f"{one.payload!r}\n{one.message}\n{one.args!r}" for one in self.seen
        )


@pytest.fixture
def tap():
    consumer = Tap()
    attach_server_tap(consumer)
    try:
        yield consumer
    finally:
        detach_server_tap(consumer)


def subprotocols(mac: str, client: str, token: str | None) -> list[str]:
    values = [BROWSER_SUBPROTOCOL, f"vinga.mac.{mac.replace(':', '')}", f"vinga.client.{client}"]
    if token is not None:
        values.append(f"vinga.token.{token}")
    return values


def everywhere(caplog: pytest.LogCaptureFixture, tap: Tap) -> str:
    return "\n".join(renderings(caplog)) + "\n" + tap.rendered()


def test_a_refused_token_reaches_nothing(
    caplog: pytest.LogCaptureFixture, tap: Tap
) -> None:
    with caplog.at_level(logging.DEBUG):
        with TestClient(create_app(bound_config())) as client:
            with pytest.raises(WebSocketDisconnect) as refused:
                with client.websocket_connect(
                    WEBSOCKET_PATH,
                    subprotocols=subprotocols(BROWSER_MAC, BROWSER_CLIENT, SENTINEL),
                ):
                    pass

    # The run really refused it, so there was a record to hunt in.
    assert any(fields_of(record).get("event") == "auth_rejected" for record in caplog.records)
    assert SENTINEL not in everywhere(caplog, tap)
    assert SENTINEL not in chain(refused.value)
    # Nor the identity offered beside it: nothing authenticated it, so
    # it is a string whoever opened the socket chose, and a board's
    # refused handshake names no device either.
    assert BROWSER_MAC not in everywhere(caplog, tap)
    assert BROWSER_MAC.replace(":", "") not in everywhere(caplog, tap)
    assert BROWSER_CLIENT not in everywhere(caplog, tap)


def test_an_accepted_token_reaches_only_the_reply_that_handed_it_over(
    caplog: pytest.LogCaptureFixture, tap: Tap
) -> None:
    with caplog.at_level(logging.DEBUG):
        with TestClient(create_app(bound_config())) as client:
            reply = client.post(
                OTA_PATH,
                headers={"Device-Id": BROWSER_MAC, "Client-Id": BROWSER_CLIENT},
                json={"board": {"type": "vinga-browser"}},
            )
            token = reply.json()["websocket"]["token"]
            with client.websocket_connect(
                WEBSOCKET_PATH, subprotocols=subprotocols(BROWSER_MAC, BROWSER_CLIENT, token)
            ) as websocket:
                accepted = websocket.accepted_subprotocol
                websocket.send_text(json.dumps(DEVICE_HELLO))
                assert json.loads(websocket.receive_text())["type"] == "hello"

    assert token
    assert accepted == BROWSER_SUBPROTOCOL
    assert any(fields_of(record).get("event") == "session_open" for record in caplog.records)
    assert token not in everywhere(caplog, tap)


def identity_fields(caplog: pytest.LogCaptureFixture, value: str) -> set[tuple[str, str]]:
    """Every (event, field) pair whose value holds `value`."""
    return {
        (str(fields.get("event")), key)
        for fields in (fields_of(record) for record in caplog.records)
        for key, held in fields.items()
        if isinstance(held, str) and value in held
    }


def converse(client: TestClient, mac: str, client_id: str, as_browser: bool) -> None:
    """One check-in and one hello, as a board or as a browser."""
    reply = client.post(
        OTA_PATH,
        headers={"Device-Id": mac, "Client-Id": client_id},
        json={"board": {"type": "vinga-browser" if as_browser else "a-board"}},
    )
    token = reply.json()["websocket"]["token"]
    if as_browser:
        opened = client.websocket_connect(
            WEBSOCKET_PATH, subprotocols=subprotocols(mac, client_id, token)
        )
    else:
        opened = client.websocket_connect(
            WEBSOCKET_PATH,
            headers={
                "Device-Id": mac,
                "Client-Id": client_id,
                "Authorization": f"Bearer {token}",
            },
        )
    with opened as websocket:
        websocket.send_text(json.dumps(DEVICE_HELLO))
        websocket.receive_text()


def test_a_browsers_identity_reaches_exactly_the_fields_a_boards_does(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        with TestClient(create_app(bound_config())) as client:
            converse(client, BOARD_MAC, BOARD_CLIENT, as_browser=False)
    board_mac = identity_fields(caplog, BOARD_MAC)
    board_client = identity_fields(caplog, BOARD_CLIENT)
    caplog.clear()

    with caplog.at_level(logging.DEBUG):
        with TestClient(create_app(bound_config())) as client:
            converse(client, BROWSER_MAC, BROWSER_CLIENT, as_browser=True)
    browser_mac = identity_fields(caplog, BROWSER_MAC)
    browser_client = identity_fields(caplog, BROWSER_CLIENT)

    # Non-empty, so the comparison is of two real sets: a board's events
    # do carry its MAC and its client id.
    assert ("ota_check", "device") in board_mac
    assert ("session_open", "device") in board_mac
    assert ("ota_check", "client") in board_client
    assert browser_mac == board_mac
    assert browser_client == board_client
