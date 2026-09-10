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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vinga_server.config.models import TelemetryConfig
from vinga_server.events import ServerEvents, SessionEvents, assembly
from vinga_server.events.catalog import (
    CAPTURE_CHANNEL,
    BargeIn,
    BargeInInRefractory,
    BargeInUnderFloor,
    BargeInWithoutTranscript,
    CaptureStarted,
    FramesDropped,
    Handover,
    Heard,
    NothingHeard,
    PromptAssembled,
    ReplyFinished,
    SentenceSynthesized,
    SessionClosed,
    SessionIdle,
    SessionOpen,
    SpeakingFinished,
    SpeakingStarted,
    TranscriptionAbandoned,
    TurnStarted,
)
from vinga_server.events.values import (
    ABSENT,
    AgentNames,
    AlsoBoundTo,
    ClientId,
    CloseReason,
    ConfiguredPath,
    ConversationId,
    Count,
    DeviceId,
    DroppedFrames,
    Flag,
    Identifier,
    LanguageTag,
    PromptSources,
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
OTHER_AGENT = "helper"

# What two bound agents opened against, in the shape
# `session_open.providers` carries: agent, then pipeline stage, then the
# four sanitized names off the built provider. Non-empty and
# multi-agent, because an empty one would make every assertion about
# provider context vacuous and a single-agent one could not tell a
# handover from a constant.
PROVIDERS: dict[str, dict[str, dict[str, str]]] = {
    AGENT: {
        "llm": {"name": "claude", "type": "anthropic", "host": "api.anthropic.com",
                "model": "claude-sonnet-4-5"},
        "asr": {"name": "ears", "type": "faster_whisper", "model": "small"},
        "tts": {"name": "voice", "type": "piper", "model": "en_GB-alba-medium"},
        "vad": {"name": "floor", "type": "silero"},
    },
    OTHER_AGENT: {
        "llm": {"name": "local", "type": "openai_compatible",
                "host": "127.0.0.1", "model": "qwen3"},
        "asr": {"name": "ears", "type": "faster_whisper", "model": "small"},
        "tts": {"name": "voice", "type": "piper", "model": "en_GB-alba-medium"},
        "vad": {"name": "floor", "type": "silero"},
    },
}


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


# Every exporter these helpers built and nobody released.
#
# The SDK's logging is quieted for as long as any exporter holds a lease
# on it, process-wide and reference counted, so a suite that builds
# thirty and releases none leaves the count high and the namespace
# silent for everything after it. `released()` below is what the
# telemetry suites drain it with, once per test.
BUILT: list[Telemetry] = []


def released() -> None:
    """Give back everything `exporting` built, in reverse."""
    while BUILT:
        BUILT.pop().release()


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
    BUILT.append(telemetry)
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


def open_session(
    events: SessionEvents,
    providers: dict[str, Any] | None = None,
    keep_identities: bool = False,
) -> float:
    """The session's own open. `providers` is what it says the
    conversation opened against, defaulting to the two-agent world
    above: an empty one is a session nothing can be asserted about, and
    the suites that are not about provider context ignore what they get.

    `keep_identities` is for an emitter that belongs to a REAL session:
    the fixed ids below are this module's, and writing them onto a
    running session renames the agent it is talking as, which the
    pipeline then cannot find. So a caller with a live session asks for
    its own identities to be kept and gets a `session_open` about the
    session it actually has.
    """
    entries = PROVIDERS if providers is None else providers
    if not keep_identities:
        events.device = DEVICE
        events.agent = AGENT
        events.conversation = CONVERSATION
    agent = events.agent or AGENT
    conversation = events.conversation or CONVERSATION
    device = events.device or DEVICE
    return events.emit(
        lambda: SessionOpen(
            client=ClientId("a-device-uuid"),
            agent=Identifier(agent),
            conversation=ConversationId(conversation),
            agents=AgentNames(tuple(entries) or (agent,)),
            providers=ProviderEntries(entries),
            protocol=Whole(1),
            revision=Identifier("abc1234"),
            mac=DeviceId(device),
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


def abandon_transcription(events: SessionEvents) -> float:
    """The fourth way an ASR stage ends, which arrives inside a turn:
    the reply was cancelled with the transcription still running."""
    return events.emit(
        lambda: TranscriptionAbandoned(
            agent=Identifier(AGENT),
            conversation=ConversationId(CONVERSATION),
            duration_s=Real(0.9),
            asr_ms=Whole(140),
        )
    )


def assemble_prompt(events: SessionEvents, sources: dict[str, int]) -> float:
    """One of the two events whose payload carries a mapping."""
    return events.emit(
        lambda: PromptAssembled(
            agent=Identifier(AGENT),
            conversation=ConversationId(CONVERSATION),
            characters=Count(sum(sources.values())),
            sources=PromptSources(dict(sources)),
        )
    )


def hear(
    events: SessionEvents,
    duration_s: float = 0.9,
    asr_ms: int | None = 300,
    language: str | None = "en",
) -> float:
    """The ASR outcome that answered."""
    return events.emit(
        lambda: Heard(
            agent=Identifier(AGENT),
            conversation=ConversationId(CONVERSATION),
            duration_s=Real(duration_s),
            asr_ms=Whole(asr_ms) if asr_ms is not None else ABSENT,
            language=LanguageTag(language) if language is not None else ABSENT,
            language_confidence=Real(0.98) if language is not None else ABSENT,
        )
    )


def drop_frames(events: SessionEvents, reasons: dict[str, int], second: int = 3) -> float:
    """And the other. Emitted directly rather than through `dropped()`,
    because what the exporter is being asked about is the payload rather
    than the counting."""
    return events.emit(
        lambda: FramesDropped(
            second=Whole(second),
            reasons=DroppedFrames(dict(reasons)),
        )
    )


def hear_nothing(
    events: SessionEvents, duration_s: float = 0.9, asr_ms: int = 220
) -> float:
    """The ASR outcome that answered nothing at all, which is the issue's
    motivating gap: 0.9 s of speech transcribed to an empty string."""
    return events.emit(
        lambda: NothingHeard(
            agent=Identifier(AGENT),
            conversation=ConversationId(CONVERSATION),
            duration_s=Real(duration_s),
            asr_ms=Whole(asr_ms),
        )
    )


@dataclass
class Identity:
    """A provider's identity as the events read it, which is four names
    off a built entry and nothing else.

    A stand-in rather than the real `ProviderIdentity` because the
    events' own assembly reads it by attribute (`_entry_of`), and what
    these cases are about is which of the four reaches which span
    attribute.
    """

    name: str = "openai-main"
    type: str = "openai"
    host: str | None = "api.openai.com"
    model: str | None = "gpt-4o-mini"


@dataclass
class FakeProvider:
    """One provider object, as far as `events/assembly.py` looks."""

    identity: Identity | None = None


def round_done(
    events: SessionEvents,
    duration_ms: int = 800,
    first_token_ms: int | None = 250,
    input_tokens: int | None = 420,
    output_tokens: int | None = 37,
    round_: int = 1,
    turns: int = 4,
    unbuilt: bool = False,
    agent: str = AGENT,
) -> float:
    """One `llm_round`, built through the events' own assembly so the
    quartet's absence rules are the real ones.

    `unbuilt` is a provider the registry never stamped (a test's, a
    fixture's), which the catalog answers with four absences rather than
    with a half quartet.
    """
    provider = FakeProvider(identity=None if unbuilt else Identity())
    return events.emit(
        lambda: assembly.llm_rounded(
            agent,
            CONVERSATION,
            "llm",
            provider,
            round_,
            turns,
            duration_ms / 1000,
            input_tokens,
            output_tokens,
            first_token_ms,
        )
    )


def retry_round(events: SessionEvents, round_: int = 1, duration_ms: int = 10000) -> float:
    """The first-token watchdog giving up on a round and asking again."""
    provider = FakeProvider(identity=Identity())
    return events.emit(
        lambda: assembly.llm_retried(
            AGENT, CONVERSATION, "llm", provider, round_, duration_ms / 1000
        )
    )


def provider_failed(
    events: SessionEvents,
    stage: str = "asr",
    duration_ms: int = 1500,
    failure: BaseException | None = None,
) -> float:
    """A provider call that failed, at whichever stage."""
    provider = FakeProvider(identity=Identity())
    raised = TimeoutError() if failure is None else failure
    return events.emit(
        lambda: assembly.provider_failure(
            AGENT, CONVERSATION, stage, provider, raised, duration_ms / 1000
        )
    )


def synthesize(
    events: SessionEvents,
    index: int = 0,
    stream_ms: int = 900,
    first_chunk_ms: int | None = 120,
    agent: str = AGENT,
) -> float:
    """One sentence's synthesis stream ending."""
    return events.emit(
        lambda: SentenceSynthesized(
            agent=Identifier(agent),
            conversation=ConversationId(CONVERSATION),
            index=Count(index),
            stream_ms=Whole(stream_ms),
            first_chunk_ms=(
                Whole(first_chunk_ms) if first_chunk_ms is not None else ABSENT
            ),
        )
    )


def start_speaking(events: SessionEvents) -> float:
    """The first frame of the reply reaching the device."""
    return events.emit(
        lambda: SpeakingStarted(
            agent=Identifier(AGENT), conversation=ConversationId(CONVERSATION)
        )
    )


def finish_speaking(
    events: SessionEvents, frames: int = 42, at: float | None = None
) -> float:
    """The last frame of the reply reaching the device.

    `at` is the last delivery's own stamp, which is how the edge emits
    it: the record is made in the reply's `finally`, after the turn has
    already been closed, and stamped back at the frame it is about.
    """
    return events.emit(
        lambda: SpeakingFinished(
            agent=Identifier(AGENT),
            conversation=ConversationId(CONVERSATION),
            frames=Count(frames),
        ),
        at=at,
    )


def barge_in(events: SessionEvents, speech_ms: int = 700) -> float:
    """Speech cutting a reply short, which opens and closes nothing and
    is therefore what the default fold is for."""
    return events.emit(lambda: BargeIn(speech_ms=Whole(speech_ms)))


def suppress_barge_in(events: SessionEvents, which: str = "floor") -> float:
    """One of the three suppression variants, each with the fixed reason
    its own decision site chose.

    Three variants rather than one with a reason argument, because that
    is what the catalog declares: the closed reason set lives at the
    decision sites, and a span event is named after the variant that was
    emitted.
    """
    built = {
        "floor": lambda: BargeInUnderFloor(speech_ms=Whole(120), floor_ms=Real(200.0)),
        "refractory": lambda: BargeInInRefractory(speech_ms=Whole(300)),
        "no_transcript": lambda: BargeInWithoutTranscript(speech_ms=Whole(400)),
    }[which]
    return events.emit(built)


def go_idle(events: SessionEvents) -> float:
    return events.emit(lambda: SessionIdle(idle_s=Real(120.0), duration_s=Real(200.0)))


def hand_over(events: SessionEvents, to: str = OTHER_AGENT) -> float:
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
