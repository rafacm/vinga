"""The optional OpenTelemetry exporter, and the whole of the OTel
surface (#66).

Its callers stop having to know that OpenTelemetry exists. The
composition asks `build_telemetry` for one object or for nothing, the
device session asks that object for a tap and attaches it beside
`LiveEvents`, and the lifespan release closes it. The SDK bootstrap, the
owned tracer provider, the clock conversion, the trace lifecycle and the
span map are implementation, and none of it is reachable from anywhere
else.

**It is a tap, not a second vocabulary.** Every span and every span
event is derived from the typed events the pipeline already emits, at
the one seam the events package documents for this issue: "the #66/#67
exporters attach as more, without touching a single emit site". No emit
site moves for this module, and nothing here can say a fact
`catalog.py` does not declare.

**It never blocks a reply.** A tap's `emit` runs on the reply path, so
what happens there is object assembly and nothing else: no lock the
export holds, no syscall, no wait. The SDK's `BatchSpanProcessor` owns
the bounded queue and the background thread, and a full queue drops
spans with a counter, which is the posture this issue chose out loud:
dropped spans are acceptable, a stalled reply is not.

**It owns its tracer provider.** The process-global provider is never
read and never set, so two sequential lifespans in one process each get
a fresh working exporter, and nothing installed here can be observed by
code that did not ask this module for it.

**The dangerous bytes enter below the catalog**, which is what the
no-leak rules here are about. The collector's credentials arrive in
`OTEL_EXPORTER_OTLP_HEADERS`, its address may carry userinfo, and the
SDK's own failure logging embeds the endpoint. So:

- endpoint, headers and timeouts are transport configuration only. This
  module never reads them: the exporter's constructor reads its own
  environment, and no value of theirs becomes a span attribute, a
  resource attribute, an event field or a line of log text;
- the resource is fixed and server-owned, the service name a constant
  and the build revision its version. `Resource.create()` is
  deliberately not used, because it merges `OTEL_RESOURCE_ATTRIBUTES`
  and `OTEL_SERVICE_NAME` into what every span carries, which is
  environment-derived content on the retained surface;
- the SDK's loggers are quieted before the exporter is constructed and
  restored when it shuts down.

The one environment variable this module does read is the protocol, and
it reads it to refuse: the supported transport is OTLP over
HTTP/protobuf exactly, because that is the one exporter the `[otel]`
extra declares. What is refused is named by the supported value rather
than by the rejected one, which is the same rule every refusal in this
repository follows.
"""

import asyncio
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from vinga_server.build_info import revision
from vinga_server.config import ConfigError
from vinga_server.config.models import TelemetryConfig
from vinga_server.egress import EgressRefusal, check_feature
from vinga_server.events import Emission, EventTap

logger = logging.getLogger(__name__)

# Where the switch is written, which is what both refusals below name.
# One spelling, because a sentence an operator is told to edit by has to
# be the path they will find.
TELEMETRY_KEY = "server.telemetry.enabled"

# The extra that carries the packages, and the command that installs it.
# The registry's sentence shape (`providers/registry.py`): the entry,
# the extra, and what to type.
OTEL_EXTRA = "otel"

NEEDS_THE_OTEL_EXTRA = (
    f"{TELEMETRY_KEY} is on, which needs the {OTEL_EXTRA} extra; "
    f"install it with: uv sync --extra {OTEL_EXTRA}"
)

# The transport the extra declares, spelled as the SDK spells it.
OTLP_PROTOCOL_ENV = "OTEL_EXPORTER_OTLP_PROTOCOL"
OTLP_TRACES_PROTOCOL_ENV = "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL"
SUPPORTED_PROTOCOL = "http/protobuf"

UNSUPPORTED_PROTOCOL = (
    f"{TELEMETRY_KEY} is on, and this server exports over {SUPPORTED_PROTOCOL} "
    f"only; set {OTLP_PROTOCOL_ENV} to {SUPPORTED_PROTOCOL} or leave it unset"
)

# The SDK's own namespace, quieted for as long as an exporter exists.
#
# Its records are the one surface below the catalog that carries an
# operator's endpoint: an export that fails logs what it could not
# reach, and a URL with userinfo in it is a credential in a retained
# log. `tools/mcp/transport.py` takes the MCP SDK's namespace off this
# server's handlers for the same reason and by the same mechanism; the
# difference is that this one is put back, because it is switched on by
# a configuration key rather than by importing a module.
OTEL_NAMESPACE = "opentelemetry"

# What the batch processor is given, written out rather than left to the
# SDK's defaults, because the bound on the queue is the whole reason a
# slow collector cannot reach a reply. A full queue drops.
QUEUE_SIZE = 2048
BATCH_SIZE = 512
SCHEDULE_DELAY_MS = 5000
EXPORT_TIMEOUT_MS = 30000

# How long the lifespan waits for the exporter to finish on the way out.
# Bounded because a collector that has stopped answering must not hold a
# redeploy open; what is lost when it expires is spans, which is the
# same trade the queue makes.
SHUTDOWN_TIMEOUT_S = 5.0

# The fixed service name. Not `OTEL_SERVICE_NAME`, deliberately: what
# this process is, is this repository's word.
SERVICE = "vinga-server"

# --- the span map -----------------------------------------------------
#
# M2 maps four events onto the trace's shape and folds everything else
# onto whichever span is open. M3 extends this table with the stage
# spans (ASR, each LLM round, per-sentence TTS, paced playback) and the
# rest of the fold; the four names below are what a stage span will hang
# between, so they are declared as names rather than compared inline.

SESSION_OPEN = "session_open"
SESSION_CLOSED = "session_closed"
TURN_STARTED = "turn_started"
REPLY_FINISHED = "reply_finished"
CAPTURE_STARTED = "capture_started"

# What a span is called in a backend's list. Deliberately short: the
# service name is beside them, and a backend groups by these.
SESSION_SPAN = "session"
TURN_SPAN = "turn"

# The payload keys the emitter itself contributes, which are the two
# identities every session event carries.
SESSION_FIELD = "session"
DEVICE_FIELD = "device"
EVENT_FIELD = "event"

# Which payload fields become attributes on which span, and under what
# name. Written out rather than derived from the payload, so an event
# that gains a field does not silently gain an attribute: what a span
# carries is a decision, and the events reference is where the field it
# came from is documented.
#
# The prefix is vinga's own. M3 adds the settled `gen_ai.*`
# correspondence beside it on the stage spans, where those attributes
# have a meaning; nothing on these two spans is a GenAI fact.
SESSION_ATTRIBUTES = {
    SESSION_FIELD: "vinga.session.id",
    DEVICE_FIELD: "vinga.device.id",
    "agent": "vinga.agent",
    "conversation": "vinga.conversation.id",
    "protocol": "vinga.device.protocol",
}

SESSION_CLOSE_ATTRIBUTES = {
    "reason": "vinga.session.close_reason",
    "duration_s": "vinga.session.duration_s",
}

TURN_ATTRIBUTES = {
    SESSION_FIELD: "vinga.session.id",
    DEVICE_FIELD: "vinga.device.id",
    "agent": "vinga.agent",
    "conversation": "vinga.conversation.id",
    "speech_ms": "vinga.turn.speech_ms",
    "barge_in": "vinga.turn.barge_in",
}

TURN_FINISHED_ATTRIBUTES = {
    "outcome": "vinga.turn.outcome",
    "sentences_spoken": "vinga.turn.sentences_spoken",
}

# How many sessions may have a `capture_started` waiting for their
# `session_open`. The capture's event is a server-channel one and beats
# the session's open by a handshake, so it is held and folded when the
# span exists; a session id that never opens would otherwise be a slow
# leak, so the hold is bounded and the oldest entry goes first.
PENDING_CAPTURES = 64


def build_telemetry(
    config: TelemetryConfig | None,
    *,
    local_only: bool = False,
    exporter: Any | None = None,
    queue_size: int = QUEUE_SIZE,
    batch_size: int = BATCH_SIZE,
    schedule_delay_ms: int = SCHEDULE_DELAY_MS,
) -> "Telemetry | None":
    """One server's exporter, or nothing at all.

    Nothing is the default and nothing is what an absent section, or a
    section with the flag off, answers: no import happens, no object is
    built, no thread starts, and no tap is ever attached, so a server
    with telemetry off is byte for byte the server it was.

    The three refusals are this function's, and they run in this order,
    which is the order that makes each of them honest:

    1. **Egress.** Asked of `egress.py` before any OpenTelemetry import,
       any construction and any thread, so under `server.local_only` the
       exporter's constructor is provably never reached. The sentence is
       the egress module's, value-free, and it arrives here as
       `EgressRefusal`; what leaves is `ConfigError`, raised after the
       handler has closed so nothing is chained to it.
    2. **The extra.** The packages are imported HERE rather than at
       module scope (the provider registry's `_resolved` pattern), which
       is what lets this module be imported by a server that has none of
       them. An install without the extra refuses with the sentence that
       names the section, the extra and the command.
    3. **The protocol.** Read before construction and compared against
       the one value the extra can serve.

    `exporter`, `queue_size`, `batch_size` and `schedule_delay_ms` are
    the test seam and nothing else: a lane drives the fold through the
    SDK's in-memory exporter, or fills a deliberately tiny queue behind
    a blocking one to prove a saturated exporter costs a reply nothing.
    A caller that passes none of them gets the real transport reading
    its own environment.
    """
    if config is None or not config.enabled:
        return None

    refusal = _egress_refusal(local_only)
    if refusal is not None:
        # Raised here rather than inside the handler that read it, so
        # nothing is chained to it: `app.lifespan` follows the same
        # discipline, and an exception chain from this depth is what
        # carries somebody else's message into an operator's terminal.
        raise ConfigError(refusal)

    sdk = _import_sdk()
    if sdk is None:
        # Outside the handler for the same reason: an ImportError
        # carries its module search path and a traceback through
        # somebody else's package, and this sentence is printed as it is.
        raise ConfigError(NEEDS_THE_OTEL_EXTRA)

    _check_protocol()

    quieted = _quiet_sdk_loggers()
    try:
        built = exporter if exporter is not None else _otlp_exporter()
        provider = sdk.provider(
            resource=sdk.resource(
                attributes={sdk.name_key: SERVICE, sdk.version_key: revision()}
            )
        )
        provider.add_span_processor(
            sdk.processor(
                built,
                max_queue_size=queue_size,
                max_export_batch_size=batch_size,
                schedule_delay_millis=schedule_delay_ms,
                export_timeout_millis=EXPORT_TIMEOUT_MS,
            )
        )
    except Exception:
        # A construction that got part way through leaves the process's
        # logging as it found it. What was raised here is a bug rather
        # than a refusal and propagates as itself, but the namespace
        # this quieted is not this module's to keep on the way past.
        quieted.restore()
        raise
    return Telemetry(provider=provider, quieted=quieted)


def _egress_refusal(local_only: bool) -> str | None:
    """What the egress rule says about an exporter, or nothing.

    Asked before any OpenTelemetry import, any construction and any
    thread, which is what lets the refusal claim the exporter's
    constructor was never reached. The sentence is the egress module's
    own, and only the sentence crosses back: the exception type belongs
    to whichever surface asked, which here is `ConfigError`.
    """
    try:
        check_feature(TELEMETRY_KEY, egress=True, local_only=local_only)
    except EgressRefusal as refusal:
        return str(refusal)
    return None


@dataclass(frozen=True)
class _Sdk:
    """The four names this module needs out of the SDK, resolved once.

    The registry's `_resolved` pattern: the import happens when an
    exporter is built and not before, so this module imports clean in an
    install that has none of it, and nothing outside this function ever
    sees an OpenTelemetry symbol.
    """

    provider: Any
    processor: Any
    resource: Any
    name_key: str
    version_key: str


def _import_sdk() -> _Sdk | None:
    """The SDK, or nothing where it is not installed.

    Nothing rather than a raise, so the sentence the caller prints is
    raised outside this function's `except` and chains no ImportError.
    """
    try:
        from opentelemetry.sdk.resources import (
            SERVICE_NAME,
            SERVICE_VERSION,
            Resource,
        )
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return None
    return _Sdk(
        provider=TracerProvider,
        processor=BatchSpanProcessor,
        resource=Resource,
        name_key=SERVICE_NAME,
        version_key=SERVICE_VERSION,
    )


def _otlp_exporter() -> Any:
    """The real transport, which reads its own environment.

    Constructed with no arguments on purpose. Every fact it needs (the
    endpoint, the headers, the certificate, the timeout) is one this
    module must not touch, and the way not to touch a value is not to
    read it: what is never bound here cannot become an attribute, a
    field or a sentence by accident later.
    """
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter()


def _check_protocol() -> None:
    """Refuse a protocol this distribution cannot serve.

    The traces-specific variable wins over the general one, which is the
    SDK's own precedence, and an unset variable is the supported value:
    an operator who wrote nothing gets what the extra installs.

    The rejected spelling is never quoted. It is an operator-supplied
    string like any other, and a refusal that echoed it would put
    whatever was in that variable into the retained log; naming the
    supported value says everything the operator has to do.
    """
    chosen = os.environ.get(OTLP_TRACES_PROTOCOL_ENV) or os.environ.get(
        OTLP_PROTOCOL_ENV
    )
    if chosen is None or chosen.strip() == SUPPORTED_PROTOCOL:
        return
    raise ConfigError(UNSUPPORTED_PROTOCOL)


@dataclass
class _Quieted:
    """What the SDK's namespace looked like before an exporter existed,
    so it can be put back exactly."""

    level: int
    propagate: bool
    restored: bool = False

    def restore(self) -> None:
        if self.restored:
            return
        self.restored = True
        namespace = logging.getLogger(OTEL_NAMESPACE)
        namespace.setLevel(self.level)
        namespace.propagate = self.propagate


def _quiet_sdk_loggers() -> _Quieted:
    """Take the SDK's whole namespace off this server's handlers, and
    answer what it was.

    Before the exporter is constructed, which is the ordering that
    matters: construction itself can log, and what it logs about is the
    endpoint it was given.

    Two mechanisms, because one of them alone has a hole. Propagation
    off at the namespace root means no record from any `opentelemetry.*`
    logger reaches a handler of ours, whichever module logged it. The
    level above CRITICAL means a child that has not set its own level
    does not build the record at all. An operator who wants the SDK's
    diagnostics can attach a handler to `opentelemetry` itself, which is
    a deliberate act rather than the default.
    """
    namespace = logging.getLogger(OTEL_NAMESPACE)
    was = _Quieted(level=namespace.level, propagate=namespace.propagate)
    namespace.setLevel(logging.CRITICAL + 1)
    namespace.propagate = False
    return was


def _epoch_ns(at: float, offset: float) -> int:
    """One monotonic reading as the epoch nanoseconds a span wants.

    The only conversion in this module, which is what keeps every span
    and every span event in one process on one mapping: two readings of
    the pair would put two spans of the same trace a clock drift apart,
    and the arithmetic between them is exactly what a trace is read for.
    """
    return int((at + offset) * 1_000_000_000)


def _attributes(
    payload: dict[str, Any], table: dict[str, str]
) -> dict[str, Any]:
    """The attributes one payload contributes, by the table's rules.

    A field the payload does not carry contributes nothing rather than a
    null: an `Absent` value is left out of a payload by the catalog, and
    an attribute that said `None` would be a claim the event did not
    make. Values arrive as the plain builtins `carried()` produced, all
    of which OTel accepts.
    """
    return {
        name: payload[key]
        for key, name in table.items()
        if payload.get(key) is not None
    }


@dataclass
class _SessionTrace:
    """One device session's place in the trace: its root span, and the
    turn span that is open inside it, if one is."""

    span: Any
    turn: Any | None = None


class Telemetry:
    """One server's exporter, as the thing its callers hold.

    Built by `build_telemetry` and released by the lifespan. What a
    caller may do with it is ask for a tap and close it; everything else
    it knows is what its callers stop having to.
    """

    def __init__(self, provider: Any, quieted: _Quieted) -> None:
        # The two API names a span needs, bound once here rather than
        # imported per turn: an empty context, which is what makes a
        # span the root of a trace of its own, and the link that puts
        # such a root beside the session it belongs to.
        from opentelemetry.context import Context
        from opentelemetry.trace import Link

        self._root = Context
        self._link = Link
        self._provider = provider
        self._tracer = provider.get_tracer(SERVICE)
        self._quieted = quieted
        # Both clocks, read back to back, once. Every stamp this
        # exporter ever converts goes through this one number.
        wall = time.time()
        monotonic = time.monotonic()
        self._offset = wall - monotonic
        self._sessions: dict[str, _SessionTrace] = {}
        # `capture_started` that arrived before its session opened, by
        # session id, oldest first and bounded.
        self._pending: dict[str, list[Emission]] = {}
        # Whether emissions are still accepted. Flipped by the lifespan
        # before it detaches anything, so a session still talking while
        # the server tears down cannot open a span nothing will close.
        self._accepting = True

    # --- what the composition and the device edge ask for -------------

    def session_tap(self) -> EventTap:
        """A consumer for one conversation's events, attached beside
        `LiveEvents` at the same point and detached with it."""
        return _Tap(self._session_event)

    def server_tap(self) -> EventTap:
        """A consumer for the session-independent events, attached once
        for the process by the composition.

        One event reaches the trace this way today: `capture_started`,
        which is emitted on the capture's own channel and carries the
        session id it is about.
        """
        return _Tap(self._server_event)

    def stop_accepting(self) -> None:
        """Take no more emissions.

        The first step of the teardown, ahead of the detach: a tap comes
        off one attachment point at a time, and a session mid-reply goes
        on emitting until it does.
        """
        self._accepting = False

    def flush(self) -> bool:
        """Hand whatever is queued to the exporter now, and answer
        whether it got there before the export timeout.

        Part of the interface rather than a hook a test reached in for:
        "has what I emitted actually left" is the one question about an
        exporter that cannot be answered from outside it, and the
        shutdown below asks it implicitly. It BLOCKS, which is why no
        path that serves a device calls it.
        """
        flushed: bool = self._provider.force_flush()
        return flushed

    async def shutdown(self) -> None:
        """Flush what is queued and let the SDK's thread go, bounded.

        Off the loop, because the SDK's shutdown joins a thread, and
        bounded, because a collector that has stopped answering must not
        hold a redeploy open. What a timeout costs is spans, which is
        the trade the bounded queue already makes.

        The loggers go back to what they were afterwards, whichever way
        this ended: the process's logging configuration is not this
        object's to keep once it has stopped exporting.
        """
        self._accepting = False
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._provider.shutdown), SHUTDOWN_TIMEOUT_S
            )
        except TimeoutError:
            # A plain sentence and nothing about the far side: what
            # could not be reached is the endpoint, which is the one
            # string this module never writes down.
            logger.warning(
                "the telemetry exporter did not finish within %.0f s and was left behind",
                SHUTDOWN_TIMEOUT_S,
            )
        finally:
            self._quieted.restore()

    # --- the fold -----------------------------------------------------

    def _session_event(self, emission: Emission) -> None:
        """One conversation event, folded onto the trace."""
        if not self._accepting:
            return
        payload = emission.payload
        name = payload.get(EVENT_FIELD)
        session = payload.get(SESSION_FIELD)
        if not isinstance(session, str):
            return
        if name == SESSION_OPEN:
            self._open_session(session, emission)
        elif name == SESSION_CLOSED:
            self._close_session(session, emission)
        elif name == TURN_STARTED:
            self._open_turn(session, emission)
        elif name == REPLY_FINISHED:
            self._close_turn(session, emission)
        else:
            # Everything else is a span event, on the turn being spoken
            # when one is open and on the session otherwise. This is the
            # row M3 replaces for the events that become stage spans.
            self._span_event(session, emission)

    def _server_event(self, emission: Emission) -> None:
        """One server-scoped event, folded where it belongs.

        Only the events that name a session have a destination in a
        trace, and `capture_started` is the one that does today. One
        that arrives before its session's span exists is held: the
        capture opens during the handshake, a handshake ahead of
        `session_open`, so the ordering is the ordinary case rather than
        a race.
        """
        if not self._accepting:
            return
        payload = emission.payload
        if payload.get(EVENT_FIELD) != CAPTURE_STARTED:
            return
        session = payload.get(SESSION_FIELD)
        if not isinstance(session, str):
            return
        if session in self._sessions:
            self._span_event(session, emission)
            return
        held = self._pending.setdefault(session, [])
        held.append(emission)
        while len(self._pending) > PENDING_CAPTURES:
            # Oldest first: a held event whose session never opened is a
            # session that was refused after its capture started, and
            # the hold is a buffer rather than a record.
            self._pending.pop(next(iter(self._pending)))

    def _open_session(self, session: str, emission: Emission) -> None:
        if session in self._sessions:
            return
        span = self._tracer.start_span(
            SESSION_SPAN,
            context=self._root(),
            attributes=_attributes(emission.payload, SESSION_ATTRIBUTES),
            start_time=self._at(emission),
        )
        self._sessions[session] = _SessionTrace(span=span)
        for held in self._pending.pop(session, []):
            self._span_event(session, held)

    def _close_session(self, session: str, emission: Emission) -> None:
        trace = self._sessions.pop(session, None)
        if trace is None:
            return
        if trace.turn is not None:
            # A session that ended with a reply still in flight. The
            # turn's own `reply_finished` is emitted from the reply's
            # `finally` and lands before this, so reaching here means the
            # process is losing the turn rather than closing it: it is
            # left unended and never exported, which is the same posture
            # a lost batch queue takes.
            trace.turn = None
        trace.span.set_attributes(
            _attributes(emission.payload, SESSION_CLOSE_ATTRIBUTES)
        )
        trace.span.end(end_time=self._at(emission))

    def _open_turn(self, session: str, emission: Emission) -> None:
        trace = self._sessions.get(session)
        if trace is None or trace.turn is not None:
            return
        trace.turn = self._tracer.start_span(
            TURN_SPAN,
            # An empty context, which is what gives the turn a trace id
            # of its own rather than making it a child. Linked instead,
            # so a backend can list a session's turns without every turn
            # hiding inside one enormous trace.
            context=self._root(),
            links=[self._link(trace.span.get_span_context())],
            attributes=_attributes(emission.payload, TURN_ATTRIBUTES),
            # The stamp the emission carries, which for `turn_started`
            # is the instant the user stopped speaking rather than the
            # instant the event was said.
            start_time=self._at(emission),
        )

    def _close_turn(self, session: str, emission: Emission) -> None:
        trace = self._sessions.get(session)
        if trace is None or trace.turn is None:
            return
        turn, trace.turn = trace.turn, None
        turn.set_attributes(_attributes(emission.payload, TURN_FINISHED_ATTRIBUTES))
        turn.end(end_time=self._at(emission))

    def _span_event(self, session: str, emission: Emission) -> None:
        """One event that opens and closes nothing, on whichever span is
        open.

        The turn where there is one, so a barge-in suppression lands on
        the turn it interrupted; the session otherwise, which is where
        `session_idle`, `capture_started`, `handover` and any
        turn-scoped straggler that arrives between turns belong.
        """
        trace = self._sessions.get(session)
        if trace is None:
            return
        name = emission.payload.get(EVENT_FIELD)
        if not isinstance(name, str):
            return
        span = trace.turn if trace.turn is not None else trace.span
        span.add_event(
            name,
            attributes=_event_attributes(emission.payload),
            timestamp=self._at(emission),
        )

    def _at(self, emission: Emission) -> int:
        return _epoch_ns(emission.at, self._offset)


def _event_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    """One span event's attributes: the event's own fields, keeping the
    names the catalog gave them.

    The identities the emitter contributes are left out, because they
    are already on the span this is being added to, and the event name
    is left out because it IS the span event's name.
    """
    return {
        key: held
        for key, held in payload.items()
        if key not in (EVENT_FIELD, SESSION_FIELD, DEVICE_FIELD) and held is not None
    }


@dataclass
class _Tap:
    """One attachment point, as the events package's `EventTap`.

    A thin object over a bound method rather than two tap classes: what
    differs between the session and the server attachment is which fold
    an emission goes to, and nothing else. It exists at all because the
    protocol asks for an `emit`, and because the class NAME is what the
    events package reports when a tap raises, which is the one thing
    about a consumer that report is allowed to say.
    """

    fold: Callable[[Emission], None] = field(repr=False)

    def emit(self, emission: Emission) -> None:
        self.fold(emission)
