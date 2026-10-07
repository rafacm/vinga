"""A browser's credential on the websocket upgrade (#613, Q3, Q3a, Q3b).

A browser's `WebSocket` cannot set a header, so it offers its identity
and token as subprotocols: `vinga.device.v1`, `vinga.mac.<12 hex>`,
`vinga.client.<uuid>` and, when the deployment issues tokens,
`vinga.token.<token>`. The gate reads them only when none of a board's
three credential headers is present, checks the token exactly as it
checks a board's, and the session accepts selecting `vinga.device.v1`,
never an offered value. A board's path is pinned by `test_ws_auth.py`,
unchanged; these are the browser's.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.support.configs import DEVICE_HELLO, DEVICE_MAC, DEVICE_UUID, config_with_agent
from tests.support.events import events, fields_of, only
from tests.support.wire import device_headers, shake_hands
from vinga_server.app import create_app
from vinga_server.config import Config
from vinga_server.config.models import DeviceRecord
from vinga_server.device.handshake import BROWSER_SUBPROTOCOL, Handshake
from vinga_server.ota import OTA_PATH
from vinga_server.ws import WEBSOCKET_PATH, Credential, presented

BROWSER_MAC = "02:5a:3c:7e:91:0b"
BROWSER_HEX = "025a3c7e910b"
BROWSER_CLIENT = "0f6c3d2e-8a41-5b7c-9e10-4d2f6a8b1c3e"


def offered(token: str | None, mac: str = BROWSER_HEX, client: str = BROWSER_CLIENT) -> list[str]:
    """What the page offers: the protocol, its identity, and its token
    when the OTA reply handed it one."""
    values = [BROWSER_SUBPROTOCOL, f"vinga.mac.{mac}", f"vinga.client.{client}"]
    if token is not None:
        values.append(f"vinga.token.{token}")
    return values


def issued(client: TestClient, mac: str = BROWSER_MAC, client_id: str = BROWSER_CLIENT) -> str:
    auth = client.app.state.composition.device_auth
    assert auth is not None, "these cases are about the authenticated handshake"
    return auth.issue(client_id, mac)


def connect(client: TestClient, subprotocols: list[str], headers: dict[str, str] | None = None):
    return client.websocket_connect(
        WEBSOCKET_PATH, subprotocols=subprotocols, headers=dict(headers or {})
    )


def bound_browser() -> Config:
    """`config_with_agent` with the browser bound as well, the way a
    redeemed try link binds it: an unbound browser only pairs (#612), and
    what these tests are about is a browser that is admitted."""
    config = config_with_agent()
    config.devices[BROWSER_MAC] = DeviceRecord(agents=["assistant"])
    return config


def auth_off() -> Config:
    config = bound_browser()
    config.server.auth.enabled = False
    return config


# --- the reading, as a value ------------------------------------------


def test_a_browsers_list_reads_as_its_identity_its_token_and_the_protocol() -> None:
    credential = presented({}, offered("sig.123"))

    assert credential == Credential(
        Handshake(BROWSER_MAC, BROWSER_CLIENT, BROWSER_SUBPROTOCOL), "sig.123"
    )


def test_a_boards_headers_read_as_they_always_did() -> None:
    credential = presented(
        {"authorization": "Bearer sig.123", "device-id": DEVICE_MAC, "client-id": DEVICE_UUID},
        (),
    )

    assert credential == Credential(Handshake(DEVICE_MAC, DEVICE_UUID, None), "sig.123")


@pytest.mark.parametrize("header", ["authorization", "device-id", "client-id"])
def test_any_one_credential_header_makes_the_request_a_boards(header: str) -> None:
    """Headers win: one of the three is enough, and then nothing in the
    offered list is read, identity or token."""
    value = "Bearer x" if header == "authorization" else "x"
    credential = presented({header: value}, offered("sig.1"))

    assert credential.handshake.subprotocol is None
    assert credential.token != "sig.1"
    assert credential.handshake.device_id != BROWSER_MAC
    assert credential.handshake.client_id != BROWSER_CLIENT


def test_without_the_protocol_the_list_is_not_read() -> None:
    credential = presented({}, offered("sig.1")[1:])

    assert credential == Credential(Handshake("", "", None), None)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        # Twice is as good as not at all: which one would be meant?
        (
            [BROWSER_SUBPROTOCOL, "vinga.mac.025a3c7e910b", "vinga.mac.025a3c7e910c"],
            Credential(Handshake("", "", BROWSER_SUBPROTOCOL), None),
        ),
        (
            [BROWSER_SUBPROTOCOL, "vinga.token.a.1", "vinga.token.b.2"],
            Credential(Handshake("", "", BROWSER_SUBPROTOCOL), None),
        ),
        # An empty value is no value.
        (
            [BROWSER_SUBPROTOCOL, "vinga.token."],
            Credential(Handshake("", "", BROWSER_SUBPROTOCOL), None),
        ),
        # A MAC that is not twelve hex digits passes through as it came,
        # to be answered as an unusable Device-Id is.
        (
            [BROWSER_SUBPROTOCOL, "vinga.mac.025a3c7e91"],
            Credential(Handshake("025a3c7e91", "", BROWSER_SUBPROTOCOL), None),
        ),
        # Upper case hex is a MAC, normalized as a header's would be.
        (
            [BROWSER_SUBPROTOCOL, "vinga.mac.025A3C7E910B"],
            Credential(Handshake(BROWSER_MAC, "", BROWSER_SUBPROTOCOL), None),
        ),
    ],
)
def test_a_malformed_list_reads_as_the_fact_missing(
    values: list[str], expected: Credential
) -> None:
    assert presented({}, values) == expected


def test_the_token_is_not_in_a_credentials_representation() -> None:
    sentinel = "c2stYnJvd3Nlci1yZXByLW5ldmVyLWEtcmVhbA.1700000000"

    assert sentinel not in repr(presented({}, offered(sentinel)))
    assert sentinel not in str(presented({}, offered(sentinel)))


# --- through the app, device authentication on -------------------------


def test_a_browser_with_a_valid_token_is_accepted_selecting_the_protocol() -> None:
    with TestClient(create_app(bound_browser())) as client:
        token = issued(client)
        with connect(client, offered(token)) as websocket:
            assert websocket.accepted_subprotocol == BROWSER_SUBPROTOCOL
            assert shake_hands(websocket)["type"] == "hello"


def test_the_session_serves_the_identity_the_subprotocols_presented(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Not only the upgrade: the session reads the MAC the gate checked,
    so the conversation opens for the browser rather than being turned
    away for a missing Device-Id (the plan review's first finding)."""
    with caplog.at_level(logging.INFO):
        with TestClient(create_app(bound_browser())) as client:
            with connect(client, offered(issued(client))) as websocket:
                shake_hands(websocket)

    opened = only(caplog, "session_open")
    assert fields_of(opened)["device"] == BROWSER_MAC
    assert events(caplog, "session_rejected") == []


def test_the_whole_start_a_browser_makes_check_in_then_upgrade() -> None:
    """The OTA check-in with the headers a same-origin `fetch` may set,
    then the upgrade with the token that reply handed over, offered as a
    subprotocol."""
    with TestClient(create_app(bound_browser())) as client:
        reply = client.post(
            OTA_PATH,
            headers={"Device-Id": BROWSER_MAC, "Client-Id": BROWSER_CLIENT},
            json={"board": {"type": "vinga-browser"}},
        )
        assert reply.status_code == 200
        body = reply.json()
        assert body["access"] == "token"
        with connect(client, offered(body["websocket"]["token"])) as websocket:
            assert websocket.accepted_subprotocol == BROWSER_SUBPROTOCOL
            assert shake_hands(websocket)["type"] == "hello"


@pytest.mark.parametrize(
    ("values", "reason"),
    [
        (offered(None), "no_token"),
        (offered("not-a-token"), "bad_token"),
        (offered("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA.1700000000"), "bad_token"),
        # Two tokens are no token.
        (offered("a.1") + ["vinga.token.b.2"], "no_token"),
    ],
)
def test_a_missing_or_bad_token_never_reaches_the_accept(
    values: list[str], reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        with TestClient(create_app(bound_browser())) as client:
            with pytest.raises(WebSocketDisconnect) as excinfo:
                with connect(client, values):
                    pass
    assert excinfo.value.code == 1000
    rejected = only(caplog, "auth_rejected")
    assert rejected.reason == reason
    assert rejected.device is None


@pytest.mark.parametrize(
    "values",
    [
        # Signed for another MAC.
        "other mac",
        # Signed for another client id.
        "other client",
        # Two MACs, so no MAC: the token was signed for one of them.
        "two macs",
    ],
)
def test_a_token_for_another_identity_is_refused(values: str) -> None:
    with TestClient(create_app(bound_browser())) as client:
        token = issued(client)
        if values == "other mac":
            subprotocols = offered(token, mac="025a3c7e910c")
        elif values == "other client":
            subprotocols = offered(token, client="0f6c3d2e-8a41-5b7c-9e10-4d2f6a8b1c3f")
        else:
            subprotocols = offered(token) + ["vinga.mac.025a3c7e910c"]
        with pytest.raises(WebSocketDisconnect):
            with connect(client, subprotocols):
                pass


def test_headers_win_over_a_valid_subprotocol_credential() -> None:
    """A valid browser credential beside one board header is read as a
    board, which has no token: refused. The precedence, from the side
    where reading the subprotocols would have let it in."""
    with TestClient(create_app(bound_browser())) as client:
        with pytest.raises(WebSocketDisconnect):
            with connect(client, offered(issued(client)), headers={"Device-Id": BROWSER_MAC}):
                pass


def test_a_board_offering_subprotocols_is_still_a_board() -> None:
    """And from the other side: a board's valid headers are what is read,
    and the accept selects nothing, whatever was offered beside them."""
    with TestClient(create_app(bound_browser())) as client:
        auth = client.app.state.composition.device_auth
        headers = device_headers(auth.issue(DEVICE_UUID, DEVICE_MAC.lower()))
        with connect(client, offered("bogus.1"), headers=headers) as websocket:
            assert websocket.accepted_subprotocol is None
            assert shake_hands(websocket)["type"] == "hello"


def test_the_token_value_is_never_the_selected_protocol() -> None:
    """Offered first, so an accept that echoed the first offered value
    would echo the token."""
    with TestClient(create_app(bound_browser())) as client:
        token = issued(client)
        values = [f"vinga.token.{token}", *offered(None)]
        with connect(client, values) as websocket:
            assert websocket.accepted_subprotocol == BROWSER_SUBPROTOCOL
            assert token not in (websocket.accepted_subprotocol or "")


# --- device authentication off -----------------------------------------


def test_with_auth_off_a_browser_offers_no_token_and_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VINGA_AUTH_SECRET", raising=False)
    with TestClient(create_app(auth_off())) as client:
        reply = client.post(
            OTA_PATH, headers={"Device-Id": BROWSER_MAC, "Client-Id": BROWSER_CLIENT}, json={}
        )
        assert reply.json()["access"] == "open"
        assert reply.json()["websocket"]["token"] == ""
        with connect(client, offered(None)) as websocket:
            assert websocket.accepted_subprotocol == BROWSER_SUBPROTOCOL
            assert shake_hands(websocket)["type"] == "hello"


def test_with_auth_off_an_unusable_mac_is_answered_after_the_accept(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """As a board's unusable Device-Id is: on an accepted socket, with a
    close reason about the identity and a record that names none."""
    monkeypatch.delenv("VINGA_AUTH_SECRET", raising=False)
    with caplog.at_level(logging.INFO):
        with TestClient(create_app(auth_off())) as client:
            with connect(client, offered(None, mac="zz5a3c7e910b")) as websocket:
                with pytest.raises(WebSocketDisconnect) as excinfo:
                    websocket.send_text(json.dumps(DEVICE_HELLO))
                    websocket.receive_text()
    assert excinfo.value.code == 1008
    assert excinfo.value.reason == "Device-Id must be the device MAC"
    assert fields_of(only(caplog, "session_rejected"))["device"] is None
    assert "zz5a3c7e910b" not in caplog.text
