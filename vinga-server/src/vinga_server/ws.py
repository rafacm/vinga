"""The device websocket endpoint.

The path devices are sent to by the OTA reply; each accepted upgrade
becomes one `DeviceSession`, served with a conversation built by the
runtime factory the composition root assembled at startup.

Before any of that, the handshake is gated on the device token the OTA
reply issued. A connection that fails the gate is closed without ever
being accepted, which uvicorn answers as an HTTP 403 on the upgrade
rather than as a websocket close: that is what upstream does, and what
stock firmware handles by retrying and refreshing its token at its next
OTA check. The rejections that come after the accept (a malformed MAC,
a device bound to no agent) stay where M5 put them, inside the session,
because by then the device has proved who it is and the useful thing to
tell it is what is wrong with its configuration.

A device presents its identity and its token in one of two places. A
board sets the `Authorization`, `Device-Id` and `Client-Id` headers. A
browser's `WebSocket` cannot set a header, so it offers the same three
facts as `Sec-WebSocket-Protocol` values instead (#613, Q3): the
versioned protocol, `vinga.mac.<12 hex>`, `vinga.client.<uuid>` and,
when the deployment issues tokens, `vinga.token.<token>`. Every
character of a MAC's hex, a UUID and a token (urlsafe base64 and a
dot) is legal in a subprotocol. The headers win whenever any of the
three is present, so nothing a board sends is ever read another way.
Either reading becomes one `Credential`, checked by the same
`refusal_reason`, and the session is handed its identity half, which
carries no token, and accepts selecting the protocol constant, never an
offered value: the one that carries the token is read here and dropped.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from fastapi import APIRouter
from starlette.websockets import WebSocket

from vinga_server.auth import DeviceAuth
from vinga_server.composition import Composition
from vinga_server.config.models import normalize_mac
from vinga_server.device.boundary import WEBSOCKET_PATH
from vinga_server.device.handshake import BROWSER_SUBPROTOCOL, Handshake
from vinga_server.device.recording import recordings
from vinga_server.device.session import DeviceSession
from vinga_server.events import ServerEvents
from vinga_server.events.catalog import (
    AuthRejected,
    RejectedAtCapacity,
    RejectedWhileDraining,
)
from vinga_server.events.values import (
    AuthRejection,
    DeviceId,
    DeviceOrUnidentified,
    SessionId,
)

events = ServerEvents(__name__)

# `WEBSOCKET_PATH` is imported above rather than defined here: the path
# is a term of the device boundary now, since the module that assembles
# the URL a device is handed needs it too and must not reach this one,
# and everything this one holds, for it (issue #143). It stays readable
# off this module, which is where the suites and `tests/support/wire.py`
# have always named it.

# The scheme both the firmware and xiaozhi-sdk send the token under.
BEARER = "bearer "

# The three headers a board's identity and token arrive in. Any one of
# them present makes the request a board's, read off its headers alone.
CREDENTIAL_HEADERS = ("authorization", "device-id", "client-id")

# The prefixes of a browser's offered subprotocols, one per fact.
MAC_SUBPROTOCOL = "vinga.mac."
CLIENT_SUBPROTOCOL = "vinga.client."
TOKEN_SUBPROTOCOL = "vinga.token."

# What a MAC is in a subprotocol: twelve hex digits and no separators,
# since a colon is not a legal subprotocol character.
_BARE_MAC = re.compile(r"[0-9a-fA-F]{12}")

router = APIRouter()


def _known_device(device_id: str) -> str | None:
    """The normalized MAC behind a Device-Id header, or None when the
    header does not hold one.

    The narrow sibling of `signed_device_id`, which passes an unusable
    header through on purpose so the session can answer about it. Here
    there is no session to answer and nothing to diagnose, so an
    unrecognized header becomes no device at all rather than a value a
    stranger chose on a line an operator keeps.
    """
    try:
        return normalize_mac(device_id)
    except ValueError:
        return None


def bearer_token(header: str) -> str | None:
    """The token out of an Authorization header, or None when the header
    is missing or is not a bearer one. An empty token, which is what the
    firmware sends when its NVS holds none, is not a token."""
    value = header.strip()
    if not value.lower().startswith(BEARER):
        return None
    return value[len(BEARER) :].strip() or None


def signed_device_id(device_id: str) -> str:
    """The form of the device id a token was signed for: the normalized
    MAC, since that is what the OTA endpoint signs. Anything that is not
    a MAC is passed through as it arrived, so that a device with a
    malformed Device-Id is turned away by the session with an answer
    about its Device-Id rather than silently by the token check."""
    try:
        return normalize_mac(device_id)
    except ValueError:
        return device_id.strip().lower()


@dataclass(frozen=True)
class Credential:
    """What one upgrade presented: the identity the session will serve,
    and the token that identity is checked with.

    The token is kept out of the representation, so a credential that
    reaches a traceback or a debugger's print says who, never with what.
    """

    handshake: Handshake
    token: str | None = field(default=None, repr=False)


def credential_of(websocket: WebSocket) -> Credential:
    """The identity and token this upgrade presented, from a board's
    headers or a browser's subprotocols."""
    return presented(websocket.headers, websocket.scope.get("subprotocols", ()))


def presented(headers: Mapping[str, str], offered: Sequence[str]) -> Credential:
    """The credential in a set of upgrade headers and offered
    subprotocols.

    A board's when any of the three credential headers is present, or
    when the browser protocol is not offered at all: the headers alone,
    exactly as the gate always read them, so a request that carries
    neither still meets the refusal it always met. A browser's otherwise.

    In a browser's list each fact is read only when exactly one value
    offers it. None or two is the fact missing, which the checks that
    follow answer as they answer a board missing it: no token is
    `no_token`, an identity that is not one fails the token check, and
    with device authentication off the session answers an unusable MAC
    after the accept as it answers a board's header. So a malformed list
    meets the existing reasons and needs none of its own.
    """
    if any(name in headers for name in CREDENTIAL_HEADERS) or (
        BROWSER_SUBPROTOCOL not in offered
    ):
        return Credential(
            Handshake.of_headers(headers),
            bearer_token(headers.get("authorization", "")),
        )
    mac = _only(offered, MAC_SUBPROTOCOL)
    return Credential(
        Handshake(
            device_id=_colon_form(mac),
            client_id=_only(offered, CLIENT_SUBPROTOCOL),
            subprotocol=BROWSER_SUBPROTOCOL,
        ),
        _only(offered, TOKEN_SUBPROTOCOL) or None,
    )


def _only(offered: Sequence[str], prefix: str) -> str:
    """What follows `prefix` in the one offered value that starts with
    it, or the empty string when none or more than one does."""
    matching = [value[len(prefix) :] for value in offered if value.startswith(prefix)]
    return matching[0].strip() if len(matching) == 1 else ""


def _colon_form(mac: str) -> str:
    """A subprotocol's twelve hex digits in the colon form a board sends
    in `Device-Id`. Anything else passes through as it arrived, to be
    answered as an unusable `Device-Id` is."""
    if not _BARE_MAC.fullmatch(mac):
        return mac
    return ":".join(mac[at : at + 2] for at in range(0, 12, 2)).lower()


def refusal_reason(
    device_auth: DeviceAuth | None, credential: Credential
) -> AuthRejection | None:
    """Why this handshake is refused, or None when it may proceed.

    The identity a token is checked against is the pair the OTA reply
    signed for, as the credential carries it: the MAC and the device
    UUID, from a board's `Device-Id` and `Client-Id` headers or from a
    browser's subprotocols, checked the same way whichever it was.

    A member rather than a string, because the answer IS the closed set
    the event declares: a spelling this returned that the set does not
    hold would be a refusal the surface cannot report, and the type is
    what makes that unwritable rather than caught at emit.
    """
    if device_auth is None:
        return None
    token = credential.token
    if token is None:
        return AuthRejection.NO_TOKEN
    device_id = signed_device_id(credential.handshake.device_id)
    client_id = credential.handshake.client_id
    if not device_auth.verify(token, client_id, device_id):
        return AuthRejection.BAD_TOKEN
    return None


@router.websocket(WEBSOCKET_PATH)
async def conversation(websocket: WebSocket) -> None:
    comp: Composition = websocket.app.state.composition

    credential = credential_of(websocket)
    refusal = refusal_reason(comp.device_auth, credential)
    if refusal is not None:
        # A fixed sentence and a null device, deliberately (the PR #153
        # review). Nothing is authenticated at this point: the Device-Id
        # header is a string whoever opened the socket chose, and naming
        # it here let an unauthenticated caller write a value of their
        # choosing into the retained log surface, one record per attempt
        # and as fast as they could connect. The reason token is what a
        # reader can act on, and it is this server's own word.
        events.emit(lambda: AuthRejected(device=None, reason=refusal))
        # Closed before the accept, so the upgrade is answered 403 and no
        # websocket is ever established.
        await websocket.close()
        return

    # Read only now. Past the refusal above the token verified against
    # this identity, so from here it is a device this server established
    # rather than a name a stranger sent.
    handshake = credential.handshake
    device_id = handshake.device_id.lower()

    session = DeviceSession(
        websocket,
        comp.generations,
        comp.runtime_factory,
        recordings(comp.capture, comp.conversations, comp.transcripts, comp.llm_input),
        comp.device_facts,
        comp.bindings,
        comp.sessions,
        comp.live,
        comp.telemetry,
        handshake=handshake,
    )
    # Admission is decided after the token, so a full server still answers
    # a bad token with a refusal about the token.
    admission = comp.sessions.admit(session)
    if admission != "admitting":
        # The MAC this server recognizes, or nothing.
        #
        # "Past the refusal above the token verified against this
        # header" holds only where there is a token to verify: with
        # device auth off, `refusal_reason` returns None before reading
        # anything, so this header is an unauthenticated string a
        # stranger chose, and a full server would otherwise write one
        # per attempt into the retained log. Normalizing is what
        # separates the two cases without a flag: a real Device-Id
        # normalizes to its MAC and reads exactly as it did before, and
        # anything else becomes a null field beside the fixed phrase the
        # empty header already used.
        known = _known_device(device_id)
        device = None if known is None else DeviceId(known)
        rejected = SessionId(session.session_id)
        shown = DeviceOrUnidentified.of(known)
        # The two refusals are said apart, because they send whoever
        # reads them somewhere else: a full server is a sizing question
        # and a draining one is a redeploy in progress. The registry
        # decided which it was in the same step as the refusal, so this
        # reports its word rather than guessing at one.
        if admission == "draining":
            events.emit(
                lambda: RejectedWhileDraining(
                    device=device, session=rejected, shown=shown
                )
            )
        else:
            events.emit(
                lambda: RejectedAtCapacity(device=device, session=rejected, shown=shown)
            )
        # The one path where a session that was built never runs, so the
        # `finally` inside `run` never fires for it. The taps it
        # attached at construction come off here instead, after the
        # rejection above, which is an event a tail wants precisely
        # because it is the one that explains a device that keeps
        # reconnecting (#342).
        session.detach_observers()
        await websocket.close()
        return

    try:
        await session.run()
    finally:
        comp.sessions.remove(session)
