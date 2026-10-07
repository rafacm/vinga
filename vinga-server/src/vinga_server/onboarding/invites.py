"""The invite link: a short-lived, single-use token that binds a browser.

`vinga device invite` prints `<origin>/talk/#<token>`. The token travels in the
URL's fragment, which a browser sends to no server and puts in no
`Referer`, so no proxy or access log in front of this server can record
it; the page at `/talk/` reads it, clears it from the address bar and
redeems it with a same-origin POST (#613, D5). Redeeming spends the
token, mints a browser identity and writes the device bound and named,
in one transaction, before the browser's first word.

An invite may name the agents its browser is bound to (#612, Q11). The
names are checked when the invite is issued and ride with the token in
this store, so a redemption binds exactly what the issuance checked;
naming none binds the browser to the default agent, read when it
redeems.

What this module's callers stop having to know:

- **Expiry, reuse and growth.** A token lives ten minutes and is spent
  by its first claim, which removes it; every issue and every claim
  first removes the records past their expiry, and the store holds at
  most `INVITE_CAPACITY` of them (D6, D6a). An unknown, an expired and
  a spent token are one answer, so a caller cannot tell them apart and
  neither can whoever is guessing.
- **The one winner.** `claim` checks and removes in one step, under a
  lock and with no await anywhere in it, so of any number of concurrent
  redemptions of one token exactly one is told yes, and only that one
  goes on to mint and write (D5d). The lock is there because the
  configuration API issues from a worker thread, like every route of
  its that reads the store; the claim itself is made on the event loop.
- **When a link may be issued at all.** Onboarding on, a store behind
  the server, then either every named agent stored and served by the
  world this server installed, or, naming none, a default agent to bind
  to; and room in the store, in that order. Each refusal is a fixed
  sentence, and none quotes a name it was sent (D5a, D6b).
- **Which origin a link names.** The configured `server.public_url`
  when it opens a secure context (`https://`, or a loopback name), and
  nothing otherwise: never the listen address and never a guess (D5c).
  The CLI owns the other half of that rule, the loopback origin it
  derives from its own API target, because only it knows that target.
- **What a redemption writes.** One store write that creates the
  device, bound to the agents the invite named (or the default agent)
  and named `Browser <mac>`, or refuses with nothing written; the names
  are re-read inside that write's transaction, and a MAC that already
  has a row is minted again, a few times at most (D5b).

The store lives in this process's memory and nowhere else: one replica,
as the deployment contract says, so a restart or an upgrade ends every
unredeemed link, and a redemption afterwards meets the same refusal an
unknown token does (D5e).

Nothing here logs, emits or raises with a token in it. A token is a
bearer credential: it reaches the operator's authenticated issuance
response, the redeeming browser's request body, and nothing else (D7a).
"""

import asyncio
import base64
import ipaddress
import logging
import secrets
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

# The bounds are read through the package at the moment a decision needs
# one, the rule `pending` states: a suite moves them on the name they
# live on, and a name imported from the package would be a snapshot.
import vinga_server.onboarding as onboarding
from vinga_server.class_names import failure_name
from vinga_server.config.loader import (
    ConfigError,
    DeviceAlreadyBoundError,
    InviteRefusedError,
    SnapshotOnlyError,
)
from vinga_server.config.models import BROWSER_MOUNT_PATH, ServerConfig, browser_device_name
from vinga_server.config.responses import Invite, RefusalReason

from .browser import BrowserIdentity, Randomness, mint

if TYPE_CHECKING:
    from vinga_server.config.store import ConfigStore

# How many random bytes a token is. Thirty-two, the size `secrets`
# recommends for a token that has to resist guessing: the link is
# public-facing for ten minutes and answers anyone who holds it.
TOKEN_BYTES = 32

# The refusals at issuance, each a state of the deployment rather than a
# fault in the request, and each fixed. None of them names a command:
# the client that prints one owns the grammar and names what to type,
# from the token the second one carries (`RefusalReason`).
ONBOARDING_OFF = (
    "device onboarding is off (server.onboarding.enabled is false), so this server "
    "serves no browser page and no short path for a browser to check in at, and an "
    "invite link would open nothing. Nothing was issued."
)

NO_DEFAULT_AGENT = (
    "no default agent is set, so a browser opening an invite link that names no agent "
    "would have no agent to be bound to. Nothing was issued."
)

# And the two about the agents an invite names (#612, Q11). Neither
# quotes a name: an agent name is typed on a command line, where a
# paste can put a credential, so the sentence names the field and the
# rule and leaves the caller to know what it sent. The first is the
# store's unknown-agent state, carrying its reason; the second is the
# served world's, the state D5 names for the default agent, carrying the
# reason a read of an agent this server has not installed carries.
AGENTS_UNKNOWN = (
    "the invite names at least one agent this deployment does not have, so a browser "
    "opening it could not be bound. Nothing was issued, and what was sent is not quoted "
    "back."
)

AGENT_NOT_SERVED = (
    "the invite names at least one agent this server is not serving, so a browser "
    "opening it would be bound to an agent that does not answer. Nothing was issued; an "
    "agent written since is served once the apply that installs it has run."
)

CAPACITY_REACHED = (
    f"as many invite links as this server holds are already waiting to be opened, so no "
    f"more are issued until one is opened or expires; each lasts "
    f"{int(onboarding.INVITE_TTL_S // 60)} minutes. Nothing was issued."
)

SNAPSHOT_ONLY = (
    "this server serves a configuration it was given rather than one it read from a "
    "store, so a browser bound by an invite link would be written to a store this server "
    "does not read its devices from. Nothing was issued, and making the request again "
    "will not help; a server started from a store issues them."
)

logger = logging.getLogger(__name__)

# What a redemption that spent its link and bound nothing says to the
# operator, who would otherwise not know: the browser was told, and the
# log is the one place the person running the server hears of it. A log
# line rather than an event, since the browser client adds no event
# type (D7). Fixed sentences: the one argument the first takes is the
# failure's class, through `failure_name`, and never its message, the
# token or the MAC that was drawn.
SPENT_UNENROLLED = (
    "an invite link was spent, but the browser that opened it could not be enrolled "
    "(%s), so nothing was written; a new link can be printed for it"
)

SPENT_ALL_TAKEN = (
    "an invite link was spent, but every identity drawn for the browser that opened it "
    "was already taken, so nothing was written; a new link can be printed for it"
)

# What an issuance that minted a token and then could not answer with
# it raises. Not a state of the deployment, so not a refusal: the API's
# last-resort handler answers it as the failure it is.
ISSUE_FAILED = "an invite link was minted and could not be answered, so it was withdrawn"

Clock = Callable[[], float]


@dataclass(frozen=True)
class Invitation:
    """What a spent invite binds its browser to: the agents it named, in
    the order they were named, or none, which is the default agent read
    when the browser redeems. Handed back by `Invites.claim` and nowhere
    else, so the names ride with the token and nothing beside it."""

    agents: tuple[str, ...] = ()


class Invites:
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
        # Token to the instant it stops being redeemable and what it
        # binds. A spent token is not here, which is the whole of how it
        # is spent.
        self._live: dict[str, tuple[float, Invitation]] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:
        return self._clock() if self._clock is not None else time.monotonic()

    def _draw(self) -> bytes:
        draw = self._randomness if self._randomness is not None else secrets.token_bytes
        return draw(TOKEN_BYTES)

    def _prune(self, now: float) -> None:
        """Remove every record past its expiry. Held under the lock by
        both callers, so a claim never meets a half-pruned table."""
        for token in [token for token, (expires, _) in self._live.items() if expires <= now]:
            del self._live[token]

    @property
    def held(self) -> int:
        """How many records the store holds right now, expired ones it
        has not yet removed included: the number a test reads to see
        that removal happened, rather than only refusal."""
        with self._lock:
            return len(self._live)

    def issue(self, agents: tuple[str, ...] = ()) -> str:
        """A fresh token, live for `INVITE_TTL_S` and binding `agents`
        (none: the default agent), or the capacity refusal with nothing
        drawn and nothing held. The names are the caller's to have
        checked; this store keeps them beside the token and hands them
        back to the one claim that spends it."""
        with self._lock:
            now = self._now()
            self._prune(now)
            if len(self._live) >= onboarding.INVITE_CAPACITY:
                raise InviteRefusedError(CAPACITY_REACHED)
            token = base64.urlsafe_b64encode(self._draw()).rstrip(b"=").decode("ascii")
            self._live[token] = (now + onboarding.INVITE_TTL_S, Invitation(tuple(agents)))
            return token

    def claim(self, token: object) -> Invitation | None:
        """What `token` binds, spending it, or None when it was not live.
        An answer at most once per token, ever.

        The check and the removal are one step: one `pop`, under the
        lock, with nothing in this method that can yield. Expiry is the
        prune in front of it and nothing else, so an expired token is
        not refused by a second comparison but is simply no longer
        there. A redemption that is told None writes nothing, which is
        what makes the first answer the only binding a link ever makes.
        Anything that is not a string is simply not a token.
        """
        with self._lock:
            self._prune(self._now())
            if not isinstance(token, str):
                return None
            live = self._live.pop(token, None)
            return None if live is None else live[1]


def link_origin(server: ServerConfig) -> str | None:
    """The origin an invite link names, when this server's configuration
    states one that opens a secure context, and None otherwise.

    `server.public_url` and nothing else: it is the name a deployment
    goes by, and a browser's microphone needs a secure context, which is
    `https://` or a loopback host. Not the origin `websocket_url` implies
    and never the listen address, which `public_origin` would fall back
    to and which is a guess (D5c). None leaves the origin to the client,
    which knows the one thing this server cannot: the address it reached
    the API on.
    """
    if server.public_url is None:
        return None
    parts = urlsplit(server.public_url)
    if parts.scheme == "https":
        return server.public_url
    return server.public_url if _loopback(parts.hostname) else None


def _loopback(host: str | None) -> bool:
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Issuer:
    """What the configuration API calls to issue a link, and everything
    it decides with: the store of live links, the server section this
    process booted with, and whether a store stands behind the world it
    serves. Composed by the composition root, so the API learns none of
    it."""

    links: Invites
    server: ServerConfig
    snapshot_only: bool

    def issue(
        self, agents: Sequence[str], store: "ConfigStore", served: frozenset[str]
    ) -> Invite:
        """A link binding `agents`, or the refusal of the first state
        that rules one out.

        `agents` are the names the request sent, none meaning the
        default agent; each is trimmed and a repeat is the one name it
        repeats, which is how a binding stores them. `store` is read for
        what it says now, in the request that asked: which agents exist,
        or, naming none, whether a default agent is set. `served` is the
        agents of the world this server installed, asked of it per
        request because an apply replaces it. A named agent has to be
        both: stored, or the redemption's write would not resolve it,
        and served, or the browser would be bound to an agent that does
        not answer.
        """
        if not self.server.onboarding.enabled:
            raise InviteRefusedError(ONBOARDING_OFF)
        if self.snapshot_only:
            raise SnapshotOnlyError(SNAPSHOT_ONLY)
        named = tuple(dict.fromkeys(name.strip() for name in agents))
        if named:
            if not set(named) <= store.read_agent_names():
                raise ConfigError(AGENTS_UNKNOWN, reason=RefusalReason.AGENTS_UNKNOWN)
            if not set(named) <= served:
                raise InviteRefusedError(
                    AGENT_NOT_SERVED, reason=RefusalReason.AGENT_NOT_SERVING
                )
        elif store.read_default_agent() is None:
            raise InviteRefusedError(NO_DEFAULT_AGENT, reason=RefusalReason.NO_DEFAULT_AGENT)
        origin = link_origin(self.server)
        token = self.links.issue(named)
        answer: Invite | None = None
        try:
            answer = Invite(
                origin=origin,
                page=f"{BROWSER_MOUNT_PATH}/#{token}",
                lifetime_s=int(onboarding.INVITE_TTL_S),
            )
        except Exception:
            # Building the one answer that carries the token failed, and
            # what failed may quote what it was given (a model's
            # validation error does), so nothing of it is kept: the
            # link nobody was told about is withdrawn, and the failure
            # raised below is a fixed sentence raised outside this
            # handler, carrying no chain.
            answer = None
        if answer is None:
            self.links.claim(token)
            raise RuntimeError(ISSUE_FAILED)
        return answer


async def redeem(
    links: Invites,
    token: object,
    store: "ConfigStore",
    randomness: Randomness | None = None,
) -> BrowserIdentity | None:
    """Spend `token` and bind a new browser with it, or None.

    The claim comes first and is synchronous, so a redemption that loses
    it awaits nothing and writes nothing (D5d). The winner mints an
    identity and has the store create the device, bound to the agents
    the invite named or else to the default agent, and named, in one
    transaction that re-reads them (D5b; #612, Q11); a MAC that already
    has a row is minted again, `INVITE_MINTS` times at most, and every
    other failure (a named agent deleted or the default agent cleared
    since the link was issued, a database that will not answer,
    anything a layer under the store raises) is None with nothing
    written and nothing raised. The token is spent either way: a link
    is one attempt.

    `randomness` is the minter's, injected so a test can make two draws
    collide; None is the operating system's.
    """
    invitation = links.claim(token)
    if invitation is None:
        return None
    for _ in range(onboarding.INVITE_MINTS):
        failed: str | None = None
        try:
            # Inside the arm, like the write: the draw is the operating
            # system's generator, and what it raises is not this
            # module's to vouch for either.
            identity = mint(randomness)
            await asyncio.to_thread(
                store.enroll_device,
                identity.mac,
                browser_device_name(identity.mac),
                invitation.agents,
            )
        except DeviceAlreadyBoundError:
            continue
        except Exception as exc:
            # Every other failure, the mint's, the store's own refusals
            # and anything a layer under it raised alike, is the one
            # answer: nothing bound. Contained rather than raised, because this frame
            # holds the token and what a lower layer says is not this
            # module's to vouch for, so nothing of it may escape; the
            # same belt `ota.reply` wears on its unauthenticated path.
            # Only its class is kept, and the line is written outside
            # the handler, so no record carries the exception.
            failed = failure_name(exc)
        if failed is not None:
            logger.warning(SPENT_UNENROLLED, failed)
            return None
        return identity
    logger.warning(SPENT_ALL_TAKEN)
    return None
