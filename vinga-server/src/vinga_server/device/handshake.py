"""Who a websocket upgrade says it is, as one value.

Two kinds of client present the same identity in two places. A board
sets `Device-Id` and `Client-Id` headers on its upgrade; a browser's
`WebSocket` cannot set a header, so it offers its identity as
`Sec-WebSocket-Protocol` values instead (#613, Q3). Which of the two a
request used is `ws.py`'s to read, and it is read once there, beside
the token check. What the session is handed is this: the pair the
token was (or, with device authentication off, would have been) checked
against, and the subprotocol the accept has to select, which is none
for a board and the versioned browser protocol for a browser.

A value rather than the socket's headers, because the session used to
read the headers itself, and a browser that passed the token check on
its subprotocols would then have been turned away for a missing MAC
(the plan review's first finding). The token is not in it: the session
has no use for one, and a value that cannot carry it cannot print it.

Raw rather than normalized, on purpose. A `Device-Id` that is not a MAC
is answered by the session after the accept, with a close reason about
the header, which is what a board with a misconfigured identity is told
today; normalizing here would turn that answer into a refusal at the
upgrade. A board's path builds this from its headers exactly as the
session used to read them, so nothing a board sees moves.
"""

from collections.abc import Mapping
from dataclasses import dataclass

# The subprotocol a browser offers to say which protocol it speaks, and
# the one the accept selects for it. Versioned, so a page built against a
# later wire can be told apart from this one by the server it reaches.
# Never anything that carries the token: the accept echoes what it
# selects back in the upgrade's response, and this constant is the only
# value it is ever handed.
BROWSER_SUBPROTOCOL = "vinga.device.v1"


@dataclass(frozen=True)
class Handshake:
    """The identity an upgrade presented, and how to accept it.

    `device_id` is the MAC as presented and `client_id` the device UUID
    as presented, both stripped and otherwise untouched. `subprotocol` is
    what the accept selects: None for a board, `BROWSER_SUBPROTOCOL` for
    a browser.
    """

    device_id: str
    client_id: str
    subprotocol: str | None = None

    @classmethod
    def of_headers(cls, headers: Mapping[str, str]) -> "Handshake":
        """A board's reading: the two headers the firmware sets, and no
        subprotocol.

        The one place a board's identity is read off its headers, which
        `ws.py` and a session constructed without a handshake (a suite
        driving one directly) both reach.
        """
        return cls(
            device_id=headers.get("device-id", "").strip(),
            client_id=headers.get("client-id", "").strip(),
        )
