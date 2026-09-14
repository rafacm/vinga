"""Acknowledged transcript content on canonical turn roots over OTLP."""

import asyncio
import json
import logging
import time
from collections.abc import Iterator
from typing import Any

import pytest

from tests.support.events import both_formats
from tests.support.sessions import Gate
from tests.support.stores import CONVERSATIONS_MANIFEST
from tests.support.telemetry import (
    Clock,
    Receiver,
    attributes,
    close_session,
    finish_reply,
    open_session,
    session_events,
    start_turn,
)
from tests.support.transcripts import observed_pending, settled
from vinga_server.config import Config
from vinga_server.config.models import (
    ConversationsConfig,
    DatabaseConfig,
    ServerConfig,
    TelemetryConfig,
)
from vinga_server.conversations.records import TurnLeg, TurnRecord
from vinga_server.conversations.store import ConversationStore
from vinga_server.telemetry import (
    OBSERVATION_INPUT,
    OBSERVATION_OUTPUT,
    TRANSCRIPT_LEGS,
    TURN_INPUT,
    TURN_LEGS,
    TURN_OUTPUT,
    Telemetry,
    build_telemetry,
)
from vinga_server.transcript_export import TranscriptExport

pytestmark = pytest.mark.asyncio

MAX_OTLP_BODY_BYTES = 3 * 1024 * 1024

SWITCHER_MAC = "aa:bb:cc:dd:ee:95"
SESSION = "0123456789abcdef0123456789abcdef"
UTTERANCE = "0f1e2d3c4b5a69780f1e2d3c4b5a6978"
CONVERSATION = "9f0c1d2e3a4b5c6d7e8f90a1b2c3d4e5"
HEARD = "tell me the secret 0TRANSCRIPT-WIRE-SENTINEL"

POET_TONE = 440
TUTOR_TONE = 660


def exporting_config() -> Config:
    """A real device reply split by a handover with transcript export on."""
    return Config(
        providers={
            "llm": {
                "handover": {
                    "type": "mock",
                    "reply": "I cannot: {tool_result}",
                    "tool_when": "secret",
                    "tool_name": "switch_agent",
                    "tool_arguments": {"agent": "tutor"},
                },
                "plain": {"type": "mock", "reply": "{system} here, hello."},
            },
            "asr": {"mock": {"type": "mock", "text": HEARD}},
            "tts": {
                "tenor": {"type": "mock", "tone_hz": POET_TONE},
                "alto": {"type": "mock", "tone_hz": TUTOR_TONE},
            },
            "vad": {"mock": {"type": "mock"}},
        },
        agent_defaults={"asr": "mock", "vad": "mock"},
        agents={
            "poet": {"prompt": "POET", "llm": "handover", "tts": "tenor"},
            "tutor": {"prompt": "TUTOR", "llm": "plain", "tts": "alto"},
        },
        devices={SWITCHER_MAC: ["poet", "tutor"]},
        default_agent="poet",
        server=ServerConfig(
            conversations=ConversationsConfig(enabled=True, text=True),
            telemetry=TelemetryConfig(enabled=True, export_transcripts=True),
        ),
    )


async def exported(caplog: pytest.LogCaptureFixture, timeout_s: float = 20.0) -> None:
    """Wait until the live worker reports attachment or omission."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if any(
            getattr(record, "event", None)
            in ("transcripts_exported", "transcript_export_failed")
            for record in caplog.records
        ):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the transcript worker said nothing within the bound")


def one(spans: list[Any], name: str) -> Any:
    matching = [span for span in spans if span.name == name]
    assert len(matching) == 1, f"expected one {name}, got {len(matching)}"
    return matching[0]


def a_turn(
    *,
    utterance: str = UTTERANCE,
    heard: str | None = HEARD,
    reply: str | None = "Done.",
    agent: str = "poet",
    legs: tuple[TurnLeg, ...] = (),
) -> TurnRecord:
    return TurnRecord(
        at=101.0,
        conversation=CONVERSATION,
        agent=agent,
        utterance=utterance,
        heard=heard,
        reply=reply,
        legs=legs,
    )


def held_turn(telemetry: Telemetry, session: str = SESSION) -> Any:
    """Open and logically finish one root registered for settlement."""
    telemetry.register_transcript_exporter()
    clock = Clock()
    emitted = session_events(clock, telemetry, session=session)
    open_session(emitted)
    start_turn(emitted, utterance=UTTERANCE)
    clock.tick(1.0)
    finish_reply(emitted)
    return emitted


async def test_live_handover_composes_onto_one_original_turn_root(
    serve, simulate, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The complete runtime, store and OTLP wire agree on one turn."""
    caplog.set_level(logging.DEBUG)
    collector = Receiver(MAX_OTLP_BODY_BYTES)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.endpoint)

    try:
        async with serve(exporting_config()) as port:
            await simulate(port, SWITCHER_MAC)
            await exported(caplog)
        spans = collector.spans()
        bodies = list(collector.bodies)
    finally:
        collector.close()

    assert spans, "nothing reached the collector"
    assert not any(span.name == "transcript" for span in spans)
    turn = one(spans, "turn")
    turn_attributes = attributes(turn)
    assert turn_attributes[TURN_INPUT] == HEARD
    assert turn_attributes[TURN_OUTPUT] == "TUTOR here, hello."
    assert turn_attributes[OBSERVATION_INPUT] == turn_attributes[TURN_INPUT]
    assert turn_attributes[OBSERVATION_OUTPUT] == turn_attributes[TURN_OUTPUT]
    legs = json.loads(turn_attributes[TURN_LEGS])
    assert legs == [
        {"agent": "poet"},
        {"agent": "tutor", "text": "TUTOR here, hello."},
    ]
    assert turn_attributes[TRANSCRIPT_LEGS] == turn_attributes[TURN_LEGS]

    session = one(spans, "session")
    assert turn.trace_id != session.trace_id
    assert turn.parent_span_id == b""
    assert any(
        link.trace_id == session.trace_id and link.span_id == session.span_id
        for link in turn.links
    )
    assert turn_attributes["session.id"] == attributes(session)["session.id"]
    assert turn_attributes["vinga.session.id"] == attributes(session)[
        "vinga.session.id"
    ]

    carrying = [span for span in spans if HEARD in repr(attributes(span))]
    assert carrying == [turn]
    assert sum(body.count(HEARD.encode()) for body in bodies) == 2
    assert HEARD not in both_formats(caplog)


async def test_flag_off_keeps_the_turn_root_content_free(
    serve, simulate, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector = Receiver(MAX_OTLP_BODY_BYTES)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.endpoint)
    config = exporting_config()
    config.server.telemetry = TelemetryConfig(enabled=True)

    try:
        async with serve(config) as port:
            await simulate(port, SWITCHER_MAC)
        spans = collector.spans()
        bodies = list(collector.bodies)
    finally:
        collector.close()

    turn_attributes = attributes(one(spans, "turn"))
    for key in (
        TURN_INPUT,
        TURN_OUTPUT,
        TURN_LEGS,
        OBSERVATION_INPUT,
        OBSERVATION_OUTPUT,
        TRANSCRIPT_LEGS,
    ):
        assert key not in turn_attributes
    assert not any(span.name == "transcript" for span in spans)
    assert not any(HEARD.encode() in body for body in bodies)


async def test_all_handover_acknowledgements_precede_one_wire_root(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two live rows become one ordered root with complete leg attribution."""
    caplog.set_level(logging.INFO)
    collector = Receiver(MAX_OTLP_BODY_BYTES)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.endpoint)
    telemetry = build_telemetry(TelemetryConfig(enabled=True))
    assert telemetry is not None
    emitted = held_turn(telemetry)
    exporter = TranscriptExport(
        telemetry=telemetry,
        backlog=4,
        acknowledgement_timeout_s=2.0,
        shutdown_timeout_s=2.0,
    )
    first = settled()
    second = observed_pending()

    try:
        exporter.turn_recorded(
            SESSION,
            a_turn(
                reply="Let me ask.",
                legs=(
                    TurnLeg(
                        agent="poet",
                        text="Let me ask.",
                        input_tokens=11,
                        output_tokens=5,
                    ),
                ),
            ),
            first,
            final=False,
        )
        exporter.turn_recorded(
            SESSION,
            a_turn(
                heard=None,
                reply="Tutor here.",
                agent="tutor",
                legs=(
                    TurnLeg(
                        agent="tutor",
                        text="Tutor here.",
                        input_tokens=7,
                        output_tokens=3,
                    ),
                ),
            ),
            second,
            final=True,
        )
        assert await asyncio.to_thread(second.wait_entered.wait, 5.0), (
            "the transcript worker did not enter the final acknowledgement wait"
        )
        assert not any(
            getattr(record, "event", None) == "transcripts_exported"
            for record in caplog.records
        )

        second.settle(True)
        await exported(caplog)
        close_session(emitted)
        await exporter.shutdown()
        telemetry.release()
        spans = collector.spans()
    finally:
        await exporter.shutdown()
        telemetry.release()
        collector.close()

    turn = one(spans, "turn")
    projected = attributes(turn)
    assert projected[TURN_INPUT] == HEARD
    assert projected[TURN_OUTPUT] == "Let me ask. Tutor here."
    assert json.loads(projected[TURN_LEGS]) == [
        {
            "agent": "poet",
            "input_tokens": 11,
            "output_tokens": 5,
            "text": "Let me ask.",
        },
        {
            "agent": "tutor",
            "input_tokens": 7,
            "output_tokens": 3,
            "text": "Tutor here.",
        },
    ]
    assert projected[TRANSCRIPT_LEGS] == projected[TURN_LEGS]
    assert not any(span.name == "transcript" for span in spans)


def failure_reasons(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        str(getattr(record, "reason", ""))
        for record in caplog.records
        if getattr(record, "event", None) == "transcript_export_failed"
    ]


async def test_a_real_wedged_writer_releases_the_root_metadata_only(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real unanswered row acknowledgement never leaks partial content."""
    caplog.set_level(logging.DEBUG)
    collector = Receiver(MAX_OTLP_BODY_BYTES)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.endpoint)
    gate = Gate()
    store = ConversationStore(DatabaseConfig(), gate=gate)
    telemetry = build_telemetry(TelemetryConfig(enabled=True))
    assert telemetry is not None
    emitted = held_turn(telemetry)
    exporter = TranscriptExport(
        telemetry=telemetry,
        backlog=4,
        acknowledgement_timeout_s=0.25,
        shutdown_timeout_s=2.0,
    )
    record = a_turn()

    try:
        store.start()
        store.open_session(SESSION, 100.0, dict(CONVERSATIONS_MANIFEST))
        gate.wait()
        acknowledgement = store.record_turn(SESSION, record)

        began = time.monotonic()
        exporter.turn_recorded(
            SESSION, record, acknowledgement, final=True
        )
        assert time.monotonic() - began < 0.5
        await exported(caplog)
        assert failure_reasons(caplog) == ["unrecorded"]

        close_session(emitted)
        await exporter.shutdown()
        telemetry.release()
        spans = collector.spans()
    finally:
        gate.open_forever()
        await exporter.shutdown()
        store.stop()
        telemetry.release()
        collector.close()

    turn_attributes = attributes(one(spans, "turn"))
    for key in (TURN_INPUT, TURN_OUTPUT, TURN_LEGS):
        assert key not in turn_attributes
    assert not any(span.name == "transcript" for span in spans)
    assert HEARD not in both_formats(caplog)


@pytest.fixture(autouse=True)
def _no_lease_outlives_its_case() -> Iterator[None]:
    yield
    assert logging.getLogger("opentelemetry").propagate is not False
