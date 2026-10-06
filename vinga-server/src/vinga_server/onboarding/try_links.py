"""The try link: a short-lived, single-use token that binds a browser.

`vinga info` prints `<origin>/try/#<token>`. The token travels in the
URL's fragment, which a browser sends to no server and puts in no
`Referer`, so no proxy or access log in front of this server can record
it; the page at `/try/` reads it, clears it from the address bar and
redeems it with a same-origin POST (#613, D5). Redeeming spends the
token, mints a browser identity and writes the device bound to the
default agent and named, in one transaction, before the browser's first
word.

What this module's callers stop having to know:

- **Expiry, reuse and growth.** A token lives ten minutes and is spent
  by its first claim, which removes it; every issue and every claim
  first removes the records past their expiry, and the store holds at
  most `TRY_LINK_CAPACITY` of them (D6, D6a). An unknown, an expired and
  a spent token are one answer, so a caller cannot tell them apart and
  neither can whoever is guessing.
- **The one winner.** `claim` checks and removes in one step, under a
  lock and with no await anywhere in it, so of any number of concurrent
  redemptions of one token exactly one is told yes, and only that one
  goes on to mint and write (D5d). The lock is there because the
  configuration API issues from a worker thread, like every route of
  its that reads the store; the claim itself is made on the event loop.
- **When a link may be issued at all.** Onboarding on, a store behind
  the server, a default agent to bind to, and room in the store, in
  that order; each refusal is a fixed sentence (D5a, D6b).
- **Which origin a link names.** The configured `server.public_url`
  when it opens a secure context (`https://`, or a loopback name), and
  nothing otherwise: never the listen address and never a guess (D5c).
  The CLI owns the other half of that rule, the loopback origin it
  derives from its own API target, because only it knows that target.
- **What a redemption writes.** One store write that creates the
  device, bound to the default agent and named `Browser <mac>`, or
  refuses with nothing written; a MAC that already has a row is minted
  again, a few times at most (D5b).

The store lives in this process's memory and nowhere else: one replica,
as the deployment contract says, so a restart or an upgrade ends every
unredeemed link, and a redemption afterwards meets the same refusal an
unknown token does (D5e).

Nothing here logs, emits or raises with a token in it. A token is a
bearer credential: it reaches the operator's authenticated issuance
response, the redeeming browser's request body, and nothing else (D7a).
"""

import base64
import secrets
import threading
import time
from collections.abc import Callable

# The bounds are read through the package at the moment a decision needs
# one, the rule `pending` states: a suite moves them on the name they
# live on, and a name imported from the package would be a snapshot.
import vinga_server.onboarding as onboarding
from vinga_server.config.loader import TryLinkRefusedError

from .browser import Randomness

# How many random bytes a token is. Thirty-two, the size `secrets`
# recommends for a token that has to resist guessing: the link is
# public-facing for ten minutes and answers anyone who holds it.
TOKEN_BYTES = 32

# The refusal at issuance a full store answers, fixed.
CAPACITY_REACHED = (
    f"as many try links as this server holds are already waiting to be opened, so no "
    f"more are issued until one is opened or expires; each lasts "
    f"{int(onboarding.TRY_LINK_TTL_S // 60)} minutes. Nothing was issued."
)

Clock = Callable[[], float]


class TryLinks:
    """The links issued and not yet redeemed, in this process's memory.

    `clock` answers seconds on a monotonic scale and `randomness` a
    number of bytes; both are injected so a test can move time and name
    a token, and both default, read at the call rather than bound at
    construction, to the operating system's: `time.monotonic` and
    `secrets.token_bytes`. Monotonic rather than wall time, because no
    instant here is published and a wall clock stepped backwards would
    lengthen every live link.
    """

    def __init__(self, clock: Clock | None = None, randomness: Randomness | None = None) -> None:
        self._clock = clock
        self._randomness = randomness
        # Token to the instant it stops being redeemable. A spent token
        # is not here, which is the whole of how it is spent.
        self._live: dict[str, float] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:
        return self._clock() if self._clock is not None else time.monotonic()

    def _draw(self) -> bytes:
        draw = self._randomness if self._randomness is not None else secrets.token_bytes
        return draw(TOKEN_BYTES)

    def _prune(self, now: float) -> None:
        """Remove every record past its expiry. Held under the lock by
        both callers, so a claim never meets a half-pruned table."""
        for token in [token for token, expires in self._live.items() if expires <= now]:
            del self._live[token]

    @property
    def held(self) -> int:
        """How many records the store holds right now, expired ones it
        has not yet removed included: the number a test reads to see
        that removal happened, rather than only refusal."""
        with self._lock:
            return len(self._live)

    def issue(self) -> str:
        """A fresh token, live for `TRY_LINK_TTL_S`, or the capacity
        refusal with nothing drawn and nothing held."""
        with self._lock:
            now = self._now()
            self._prune(now)
            if len(self._live) >= onboarding.TRY_LINK_CAPACITY:
                raise TryLinkRefusedError(CAPACITY_REACHED)
            token = base64.urlsafe_b64encode(self._draw()).rstrip(b"=").decode("ascii")
            self._live[token] = now + onboarding.TRY_LINK_TTL_S
            return token

    def claim(self, token: object) -> bool:
        """Whether `token` was live, spending it if so. True at most
        once per token, ever.

        The check and the removal are one step: one `pop`, under the
        lock, with nothing in this method that can yield. Expiry is the
        prune in front of it and nothing else, so an expired token is
        not refused by a second comparison but is simply no longer
        there. A redemption that is told False writes nothing, which is
        what makes the first True the only binding a link ever makes.
        Anything that is not a string is simply not a token.
        """
        with self._lock:
            self._prune(self._now())
            if not isinstance(token, str):
                return False
            return self._live.pop(token, None) is not None
