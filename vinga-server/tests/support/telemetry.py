"""Driving the OTLP exporter without a collector, and without a
pipeline.

What the telemetry suites need is a `Telemetry` whose spans can be read
back, a clock whose readings a test chooses, and the handful of catalog
variants the trace's shape is built out of. Building those by hand at
the top of every case would be the same forty lines four times over, so
they live here.

Nothing here knows what a span means. It provokes emissions and hands
back what the exporter kept; every assertion about the shape is the
suite's.
"""

import time
from pathlib import Path
from typing import Any

from vinga_server.config.models import TelemetryConfig
from vinga_server.events import ServerEvents, SessionEvents
from vinga_server.events.catalog import (
    CAPTURE_CHANNEL,
    CaptureStarted,
    Handover,
    ReplyFinished,
    SessionClosed,
    SessionIdle,
    SessionOpen,
    TurnStarted,
)
from vinga_server.events.values import (
    AgentNames,
    AlsoBoundTo,
    ClientId,
    CloseReason,
    ConfiguredPath,
    ConversationId,
    Count,
    DeviceId,
    Flag,
    Identifier,
    ProviderEntries,
    Real,
    ReplyOutcome,
    SessionId,
    Whole,
)
from vinga_server.telemetry import Telemetry, build_telemetry

# Two ids of the shapes their value types admit, fixed so a suite can
# assert against them without minting one per case.
SESSION = "0123456789abcdef0123456789abcdef"
CONVERSATION = "9f0c1d2e3a4b5c6d7e8f90a1b2c3d4e5"
DEVICE = "aa:bb:cc:dd:ee:ff"
AGENT = "household"


class Clock:
    """A monotonic clock a test moves by hand.

    Anchored on the real one at construction, so the epoch stamps the
    exporter derives are the ones a session running now would produce:
    an arbitrary origin would still be internally consistent, and would
    make every failure harder to read.
    """

    def __init__(self) -> None:
        self.at = time.monotonic()

    def __call__(self) -> float:
        return self.at

    def tick(self, seconds: float) -> float:
        self.at += seconds
        return self.at


def exporting(**built: Any) -> tuple[Telemetry, Any]:
    """A `Telemetry` writing into the SDK's in-memory exporter, and the
    exporter to read back.

    The in-memory one deliberately: it has no thread and no transport,
    so a unit case reads finished spans without waiting on anything. The
    saturation and lifecycle cases, which are about the thread, use the
    real processor with an exporter of their own.
    """
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    memory = InMemorySpanExporter()
    telemetry = build_telemetry(
        TelemetryConfig(enabled=True),
        exporter=memory,
        # One span per batch and no delay, so a finished span is
        # readable in the statement after the one that ended it.
        queue_size=built.pop("queue_size", 2048),
        batch_size=built.pop("batch_size", 1),
        schedule_delay_ms=built.pop("schedule_delay_ms", 1),
        **built,
    )
    assert telemetry is not None
    return telemetry, memory


def finished(telemetry: Telemetry, memory: Any) -> list[Any]:
    """Every span the exporter has been handed, flushed first.

    The flush is what makes this deterministic: the processor batches on
    a timer, and a case that read without flushing would pass or fail on
    how long its assertions took.
    """
    telemetry.flush()
    return list(memory.get_finished_spans())


def named(spans: list[Any], name: str) -> Any:
    """The one span of a name, insisted on."""
    matching = [span for span in spans if span.name == name]
    assert len(matching) == 1, f"expected one {name} span, got {len(matching)}"
    return matching[0]


# --- the emissions a trace is built out of ----------------------------


def session_events(clock: Clock, telemetry: Telemetry) -> SessionEvents:
    """One session's emitter with the exporter's tap on it, and nothing
    else attached: the log tap is always there, and a suite that wants
    the records reads `caplog`."""
    events = SessionEvents(SESSION, clock=clock)
    events.opened_at = clock()
    events.attach(telemetry.session_tap())
    return events


def open_session(events: SessionEvents) -> float:
    events.device = DEVICE
    events.agent = AGENT
    events.conversation = CONVERSATION
    return events.emit(
        lambda: SessionOpen(
            client=ClientId("a-device-uuid"),
            agent=Identifier(AGENT),
            conversation=ConversationId(CONVERSATION),
            agents=AgentNames((AGENT,)),
            providers=ProviderEntries({}),
            protocol=Whole(1),
            revision=Identifier("abc1234"),
            mac=DeviceId(DEVICE),
            said_client=ClientId("a-device-uuid"),
            bound_tail=AlsoBoundTo.of(()),
            sample_rate=Whole(16000),
            frame_ms=Whole(60),
        )
    )


def close_session(
    events: SessionEvents, reason: CloseReason = CloseReason.CLIENT, duration_s: float = 12.0
) -> float:
    return events.emit(
        lambda: SessionClosed(
            duration_s=Real(duration_s),
            reason=reason,
            mac=DeviceId(DEVICE),
        )
    )


def start_turn(
    events: SessionEvents, speech_ms: int = 900, barge_in: bool = False, at: float | None = None
) -> float:
    return events.emit(
        lambda: TurnStarted(
            agent=Identifier(AGENT),
            conversation=ConversationId(CONVERSATION),
            speech_ms=Whole(speech_ms),
            barge_in=Flag(barge_in),
        ),
        at=at,
    )


def finish_reply(
    events: SessionEvents,
    outcome: ReplyOutcome = ReplyOutcome.COMPLETED,
    sentences: int = 2,
) -> float:
    return events.emit(
        lambda: ReplyFinished(
            agent=Identifier(AGENT),
            conversation=ConversationId(CONVERSATION),
            outcome=outcome,
            sentences_spoken=Count(sentences),
        )
    )


def go_idle(events: SessionEvents) -> float:
    return events.emit(lambda: SessionIdle(idle_s=Real(120.0), duration_s=Real(200.0)))


def hand_over(events: SessionEvents, to: str = "helper") -> float:
    return events.emit(
        lambda: Handover(
            from_agent=Identifier(AGENT),
            to_agent=Identifier(to),
            from_conversation=ConversationId(CONVERSATION),
            to_conversation=ConversationId("11112222333344445555666677778888"),
        )
    )


def capture_emitter() -> ServerEvents:
    """An emitter on the capture's own channel, which is the channel
    `capture_started` declares: a variant handed to an emitter on
    another one is refused at emit, so the channel is part of driving
    this event rather than an incidental."""
    return ServerEvents(CAPTURE_CHANNEL)


def capture_started(emitter: ServerEvents, path: str = "/data/captures") -> None:
    """The one server-channel event with a session in it, emitted the
    way the capture emits it."""
    emitter.emit(
        lambda: CaptureStarted(session=SessionId(SESSION), path=ConfiguredPath(Path(path)))
    )
