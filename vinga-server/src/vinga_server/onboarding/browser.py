"""A browser's identity, minted by this server and nowhere else.

A browser has no MAC and cannot read the machine's, and a device here
is its MAC: the binding, the pending table, the device record and the
token are all keyed by it. So a browser is handed one, once, and keeps
it in its own storage; minting happens only server side, in the two
requests that start a browser (#613, D1), and no page script ever
invents an address.

The address is random, locally administered and unicast: the first
octet has the `0x02` bit set and the `0x01` bit clear. Every board's
burned-in address is universally administered, so a minted one can
never be a real board's, and a unicast one is a legal value for every
place that stores a MAC. Forty-six random bits, which makes a collision
between two minted browsers a question for whoever binds one, not for
this module: it promises fresh randomness per call, nothing more.

The client id is the simulator's rule (`simulator.board.Identity.of`),
UUIDv5 over the normalized MAC, applied under a namespace of its own.
Derived rather than drawn, because the OTA reply signs its token for
the MAC and the client id together and the page has to present the
same pair at every request; distinct from the simulator's namespace, so
a browser and a simulated board that happened to share a MAC would
still present two client ids.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

# The namespace a browser's client id is derived under. Not the
# simulator's (`simulator.board.CLIENT_ID_NAMESPACE`), on purpose.
CLIENT_ID_NAMESPACE = uuid5(NAMESPACE_URL, "https://github.com/rafacm/vinga/browser")

# A MAC is six octets.
_OCTETS = 6

# The two bits of the first octet that say what kind of address it is.
_LOCALLY_ADMINISTERED = 0x02
_MULTICAST = 0x01

Randomness = Callable[[int], bytes]


@dataclass(frozen=True)
class BrowserIdentity:
    """The pair a browser presents at every request: its MAC, in the
    normalized form the server stores, and the client id derived from
    it."""

    mac: str
    client_id: str


def mint(randomness: Randomness | None = None) -> BrowserIdentity:
    """A fresh browser identity.

    `randomness` answers a number of bytes, and is injected so a test
    can name the octets it is about; None is the operating system's
    generator, read at the call rather than bound at import, so the
    default is the one thing a test can pin it to.
    """
    draw = randomness if randomness is not None else secrets.token_bytes
    octets = bytearray(draw(_OCTETS))
    octets[0] = (octets[0] | _LOCALLY_ADMINISTERED) & ~_MULTICAST & 0xFF
    mac = ":".join(f"{octet:02x}" for octet in octets)
    return BrowserIdentity(mac=mac, client_id=str(uuid5(CLIENT_ID_NAMESPACE, mac)))
