"""Logging setup: the human format, and the JSON one.

Two formats, one handler on the root logger. `text` is what a terminal
wants and what the server has always printed. `json` is one object per
line, which is what a log collector wants, and it is the container
default: the conversation events carry structured fields a collector
can group by session, so a deployment measures its own pipeline from
what it retains. They carry metadata only; the record of what was said
is the conversation store (#120).

One thing is filtered rather than formatted: the libraries that carry
somebody else's bytes are held below the server's level, because their
debug records carry response headers, request lines, frame payloads and
tracebacks nothing here has sanitized. See `quiet_vendor_libraries`
below, which is called from here and, without a level, from the two
places a deployment starts at, because one of them never reaches this
function and the other reaches it after the boot configuration has
already been read out of a database. `quieted` beside it is the same
mechanism for the length of one call, which is what a command whose
argument is a secret needs of the library that would narrate it.

Call sites need no wrapper. Anything passed as `extra=` on an ordinary
logging call becomes a top-level field of the JSON object, found by
comparing the record's attributes against the ones `logging` itself
sets. The message text stays a plain human sentence in both formats,
so nothing is only readable as JSON.

Stdlib only, deliberately: the formatter is short enough that a
structured-logging dependency would cost more than it saves.
"""

import datetime as dt
import json
import logging
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from vinga_server.config.models import ServerConfig

TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

# Attributes `logging` puts on every record. Whatever a record carries
# beyond these came from an `extra=`, and is ours to emit. Built from a
# throwaway record rather than hardcoded, so a new stdlib attribute
# never leaks into the output as if it were an event field.
_STANDARD_ATTRIBUTES = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", None, None))
) | {"taskName", "message", "asctime"}

# The libraries that render somebody else's bytes into a record of their
# own, and the level below which each of them reaches this handler.
#
# Their debug records are the one surface the taxonomies cannot reach. A
# provider sanitizes what it raises (providers/kit.py) and this server's
# own lines say only what their call site decided to say, but a library
# in the middle narrates the wire, and `server.log_level: DEBUG` is a
# reasonable thing to turn on while diagnosing one: that is all it would
# take to put the lot into the logs the observability ADR makes the
# retained surface.
#
# What each of them narrates:
#
# - The far side of a provider call. The openai and anthropic clients
#   log the request options, the response headers verbatim and the
#   traceback of anything they caught, with httpx and httpcore tracing
#   the connection underneath. A response header is written by the far
#   end, so a compatible endpoint can echo a credential or the request's
#   own content into one.
# - The near side of every request served. `uvicorn.error` carries the
#   HTTP server's trace, which at debug is the request line and every
#   request header: the OTA path holds the deployment's secret segment
#   and a device's handshake carries its bearer token, which is why the
#   access log is off in the first place (`serving.uvicorn_config` says
#   so). uvicorn hands that same logger to the websockets protocol, so
#   those records also render every device frame's payload, text
#   decoded.
#
# The MCP SDK narrates its wire the same way, and is deliberately not
# here: `tools/mcp/transport.py` takes its whole namespace off this
# handler entirely (`quiet_sdk_loggers`), which is stronger than a
# floor and is owned by the module that connects with it. A floor here
# as well would be a second rule to keep in agreement with that one.
#
# INFO for the SDKs, because what they say at that level is worth
# keeping and carries none of it: the notice that a request is being
# retried, which names the endpoint's path and not its query.
#
# The HTTP clients, uvicorn and the database are at WARNING, because
# INFO is where a payload of somebody else's composing starts.
#
# httpx writes one line per request at INFO: the method, the full URL
# with its query string, and the status. Nothing in it is secret today,
# since every provider this server speaks to authenticates in a header
# and a header is not on that line. But the line is composed by the
# library rather than by code anyone here audited, it sits outside the
# closed event vocabulary the rest of the log is held to, and a provider
# that one day carries a key or a session id in a query string would
# have it logged verbatim. What holding it back loses is a line per
# request, and with it a failed call's status code. What it keeps is
# `provider_failed`, whose fields are closed (the stage, the provider
# entry with its type and model, the host, the duration and the
# exception's class name), and whose `host` is the one part of the URL
# worth retaining. httpcore writes nothing above DEBUG today and is held
# with httpx, so that whatever it ever starts saying at INFO about the
# same connection is held to the same rule.
#
# uvicorn writes one line per websocket handshake at INFO, accepted or
# refused: the client's address and port, and the request path with its
# query string verbatim, as `<address>:<port> - "WebSocket <path>?<query>"
# [accepted]` or `... 403`. No client of this server puts anything in
# that query, since the firmware and the simulator authenticate in a
# header. But upstream's convention carries the bearer token there, a
# browser client has to, because a browser cannot set the header, and a
# refused handshake prints it as readily as an accepted one, before any
# code here has run. The address goes with it, which is metadata the
# access log was turned off for alongside the rest.
#
# What holding uvicorn at WARNING loses is the rest of its INFO: the
# process id at start and at finish, the lifespan's start and
# completion, `Uvicorn running on <scheme>://<host>:<port>`, the
# shutdown notices, and the `connection open` and `connection rejected`
# the websockets library writes through the same logger. A refusal is
# the events' to say (`auth_rejected`, `session_rejected`), and so is a
# session once its hello is valid (`session_open`); the onboarding
# banner names the origin a device reaches, which is the listen address
# unless `server.public_url` or `server.websocket_url` names a better
# one; and the drain announces the shutdown. What no line says any more
# is the process id, which is the runtime's to report, the bind address
# of a deployment that names its public origin, which is in its own
# configuration, and that a connection was accepted at all when it ends
# before a valid hello: `DeviceSession._receive_hello` closes a
# disconnect, a timeout and every first frame it refuses without an
# event, save a text frame the message parser rejects, which it logs,
# and `connection open` was the only trace the rest left. No event
# replaces it here; that is a decision of its own. What the floor keeps
# is everything at WARNING and above: a bind that failed, a
# lifespan that failed, an exception in the application with its
# traceback, a request that would not parse.
#
# What the floor does not cover is what those kept records carry. An
# ERROR record with a traceback renders the exception's message and its
# chain as they were raised, and nothing here sanitizes them: the floor
# is about which levels reach the handler, not about what a record that
# reaches it says. This server's own code renders no traceback (it names
# a failure by its class, see `serving._report_drain`), so uvicorn's
# is the exception to that rule rather than an instance of it. It was
# the same under the INFO floor, and this floor does not change it.
#
# A filter cutting the query and the address out of the handshake line
# and keeping the rest was priced against this and rejected. It reads
# uvicorn's message template and argument order, which three websocket
# implementations each spell out for themselves, and it needs a pin
# that fails when an upgrade moves them, all to keep lines no code here
# reads. It would also have kept `connection open`, the one trace of a
# connection that fails its hello, which the floor gives up as said
# above.
#
# sqlalchemy, because an engine whose logger is enabled for INFO echoes
# every statement with the parameters bound to it, and those parameters
# are the stored configuration and, once #120 lands, what was said. The
# library pins its own logger at WARNING when it is imported, and this
# is deliberately not a reliance on that.
#
# There is no configuration key to lift these, and deliberately so. A
# diagnosis that genuinely needs one raises it by name in the process
# that needs it, after this has run
# (`logging.getLogger("httpx").setLevel(logging.INFO)` brings the request
# line back), which is a deliberate act rather than a side effect of the
# server's own level. A request that carries a secret in its URL holds
# these two loggers quiet around itself as well (`quieted` below), so
# lifting the floor does not lift that.
VENDOR_LOG_FLOORS: Mapping[str, int] = {
    "anthropic": logging.INFO,
    "httpcore": logging.WARNING,
    "httpx": logging.WARNING,
    "openai": logging.INFO,
    "sqlalchemy": logging.WARNING,
    "uvicorn.error": logging.WARNING,
}


def quiet_vendor_libraries(level: int | None = None) -> None:
    """Hold each of those libraries at its floor, or at the level the
    caller names when that is higher.

    The maximum rather than the floor alone, so this only ever quietens:
    an operator running at WARNING keeps the silence they asked for, and
    one running at DEBUG gets their own modules' debug lines without the
    libraries' wire traces.

    `level` is the server's own, which only `configure` below knows.
    Without it each library is held against what it is already
    effectively set to, which is what a caller that is not this server's
    logging configuration can honestly say: leave every one of them as
    loud as it is and no louder, and never below its floor. That is the
    call the two places a deployment starts from make before anything
    opens a database or a socket, since one of them (an external ASGI
    runner reaching `app.py:app`) never reaches `configure` at all and
    the other reaches it only after the boot configuration has been
    read. Idempotent, and cheap enough to call on every path that could
    be the first.
    """
    for name, floor in VENDOR_LOG_FLOORS.items():
        logger = logging.getLogger(name)
        against = logger.getEffectiveLevel() if level is None else level
        logger.setLevel(max(against, floor))


# The one lock every quieting is taken under.
#
# A logger's level is process state, and this raises one and puts it
# back. Two threads doing that over the same names, unserialized, undo
# each other in the direction that matters: the first to enter saved the
# loud level, the second saved the quiet one, and the first to LEAVE
# restores the loud level underneath a request the second is still
# making, so the library narrates that request's URL into a record after
# all. The pair then finishes with the level the second saved, which is
# the wrong one in the other direction.
#
# Held across the whole block rather than around each mutation, because
# what has to be atomic is the span from raising the level to putting it
# back, not the setLevel calls at its ends. Reentrant, so a caller
# already inside one boundary may open another; the callers here do not
# nest today, and a lock that deadlocked if they ever did would be a
# trap left for somebody else to find.
#
# What this costs is that two threads quieting the same loggers take
# their turns rather than overlapping. Both callers are command-line
# tools making one request, which is the shape this was always for; a
# server that wanted concurrent quieting would want a different
# mechanism entirely, since the level it is changing is global to the
# process whatever guards it.
_QUIETING = threading.RLock()


@contextmanager
def quieted(names: Iterable[str], level: int) -> Iterator[None]:
    """Hold these loggers at `level` or above for the length of a block,
    and put back exactly what each of them had.

    The scoped sibling of `quiet_vendor_libraries`, and the same
    mechanism for the same reason: a level on a named logger, raised and
    never lowered, so a deployment that had already silenced one keeps
    the silence it asked for.

    What differs is the span rather than the kind. The floors above are
    standing, and are about how loud an operator turned a library up.
    This is about one call whose arguments are a secret, where the
    library's ordinary INFO line is precisely the record that must not
    exist: `doctor.py` names the loggers and says which call.

    What is restored is each logger's own level rather than its
    effective one, so a logger that was inheriting goes back to
    inheriting.

    One block at a time, under `_QUIETING` above, which says why: the
    state being held is the process's, so two threads holding it at once
    restore each other's levels, and the one that loses is the one whose
    request is still in flight.
    """
    with _QUIETING:
        held = [(logging.getLogger(name), logging.getLogger(name).level) for name in names]
        for logger, _ in held:
            logger.setLevel(max(logger.getEffectiveLevel(), level))
        try:
            yield
        finally:
            for logger, was in held:
                logger.setLevel(was)


class JsonFormatter(logging.Formatter):
    """One JSON object per line: the timestamp, level, logger, and
    message every record has, the traceback when there is one, and every
    `extra=` field the call site attached."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRIBUTES:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        # default=str so an extra that is not JSON-serializable degrades to
        # its repr instead of losing the whole record.
        return json.dumps(payload, default=str)


def configure(server: ServerConfig) -> None:
    """Install the root handler in the configured format and level.

    Replaces any handler already on the root logger, so calling this
    twice (a reload, a test) does not double every line. Uvicorn's own
    loggers propagate into this one, which is what `log_config=None` at
    the call site arranges.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter() if server.log_format == "json" else logging.Formatter(TEXT_FORMAT)
    )
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(server.log_level)
    quiet_vendor_libraries(root.level)
