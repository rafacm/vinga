"""Held turn roots receive acknowledged content exactly once."""

import logging
import threading
from collections.abc import Iterator

import pytest

from tests.support.events import fields_of
from tests.support.telemetry import (
    SESSION,
    Clock,
    exporting,
    finish_reply,
    finished,
    named,
    open_session,
    released,
    session_events,
    start_turn,
)
from tests.support.transcripts import pending
from vinga_server import telemetry as telemetry_module
from vinga_server.conversations.records import TurnRecord
from vinga_server.events.values import TranscriptExportFailure
from vinga_server.telemetry import (
    _QUIETING,
    TURN_INPUT,
    TURN_LEGS,
    TURN_OUTPUT,
    Telemetry,
    TurnSettlement,
)
from vinga_server.transcript_export import MAX_CONTENT_BYTES, TranscriptExport


@pytest.fixture(autouse=True)
def _release() -> Iterator[None]:
    yield
    released()
    assert _QUIETING.held() == 0


def _held(utterance: str = "a" * 32):
    telemetry, memory = exporting()
    telemetry.register_transcript_exporter()
    clock = Clock()
    emitted = session_events(clock, telemetry)
    open_session(emitted)
    start_turn(emitted, utterance=utterance)
    clock.tick(1)
    finish_reply(emitted)
    return telemetry, memory


def test_a_registered_exporter_holds_then_enriches_the_root() -> None:
    utterance = "a" * 32
    telemetry, memory = _held(utterance)
    assert not any(span.name == "turn" for span in finished(telemetry, memory))

    assert telemetry.settle_turn(
        SESSION,
        utterance,
        {
            "input": "heard words",
            "output": "spoken reply",
            "legs": [
                {
                    "agent": "household",
                    "text": "spoken reply",
                    "input_tokens": 5,
                    "output_tokens": 2,
                }
            ],
        },
    ) is TurnSettlement.SETTLED
    turn = named(finished(telemetry, memory), "turn")
    assert turn.attributes[TURN_INPUT] == "heard words"
    assert turn.attributes[TURN_OUTPUT] == "spoken reply"
    assert '"input_tokens":5' in turn.attributes[TURN_LEGS]
    assert not any(span.name == "transcript" for span in finished(telemetry, memory))


def test_no_built_exporter_never_delays_a_root() -> None:
    telemetry, memory = exporting()
    clock = Clock()
    emitted = session_events(clock, telemetry)
    open_session(emitted)
    start_turn(emitted)
    finish_reply(emitted)
    named(finished(telemetry, memory), "turn")


def test_blocking_release_ends_a_held_root_metadata_only() -> None:
    telemetry, memory = _held()

    telemetry.release()

    turn = named(finished(telemetry, memory), "turn")
    assert TURN_INPUT not in turn.attributes
    assert TURN_OUTPUT not in turn.attributes


def test_worker_and_metadata_release_contenders_end_once() -> None:
    session = SESSION
    for index in range(100):
        utterance = f"{index:032x}"
        telemetry, memory = _held(utterance)
        barrier = threading.Barrier(3)
        answers: list[TurnSettlement] = []

        def settle(
            gate: threading.Barrier = barrier,
            results: list[TurnSettlement] = answers,
            exporter: Telemetry = telemetry,
            identity: str = utterance,
        ) -> None:
            gate.wait()
            results.append(exporter.settle_turn(session, identity, {"input": "x"}))

        def release(
            gate: threading.Barrier = barrier,
            results: list[TurnSettlement] = answers,
            exporter: Telemetry = telemetry,
            identity: str = utterance,
        ) -> None:
            gate.wait()
            results.append(exporter.release_turn(session, identity))

        first = threading.Thread(target=settle)
        second = threading.Thread(target=release)
        first.start()
        second.start()
        barrier.wait()
        first.join()
        second.join()

        assert answers.count(TurnSettlement.SETTLED) == 1
        assert answers.count(TurnSettlement.MISSING) == 1
        assert len([span for span in finished(telemetry, memory) if span.name == "turn"]) == 1
        telemetry.release()


def test_worker_and_provider_release_contenders_end_once() -> None:
    for index in range(100):
        utterance = f"{index:032x}"
        telemetry, memory = _held(utterance)
        barrier = threading.Barrier(3)
        answer: list[TurnSettlement] = []

        def settle(
            gate: threading.Barrier = barrier,
            results: list[TurnSettlement] = answer,
            exporter: Telemetry = telemetry,
            identity: str = utterance,
        ) -> None:
            gate.wait()
            results.append(
                exporter.settle_turn(SESSION, identity, {"input": "heard"})
            )

        def release_provider(
            gate: threading.Barrier = barrier,
            exporter: Telemetry = telemetry,
        ) -> None:
            gate.wait()
            exporter.release()

        worker = threading.Thread(target=settle)
        shutdown = threading.Thread(target=release_provider)
        worker.start()
        shutdown.start()
        barrier.wait()
        worker.join()
        shutdown.join()

        assert answer[0] in {TurnSettlement.SETTLED, TurnSettlement.MISSING}
        turns = [span for span in memory.get_finished_spans() if span.name == "turn"]
        assert len(turns) == 1


def test_the_4097th_policy_evicts_the_oldest_finished_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telemetry_module, "DEFERRED_TURNS", 2)
    omitted: list[tuple[str, str]] = []
    telemetry, memory = exporting()
    telemetry.register_transcript_exporter(
        lambda session, utterance: omitted.append((session, utterance))
    )
    clock = Clock()
    emitted = session_events(clock, telemetry)
    open_session(emitted)
    for index in range(3):
        start_turn(emitted, utterance=f"{index:032x}")
        finish_reply(emitted)

    turns = [span for span in finished(telemetry, memory) if span.name == "turn"]
    assert len(turns) == 1
    assert len(omitted) == 1
    assert (
        telemetry.release_turn(SESSION, f"{0:032x}")
        is TurnSettlement.OMITTED
    )


@pytest.mark.asyncio
async def test_ledger_overflow_and_pending_job_report_one_terminal_outcome(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(telemetry_module, "DEFERRED_TURNS", 1)
    caplog.set_level(logging.WARNING)
    telemetry, memory = exporting()
    exporter = TranscriptExport(
        telemetry=telemetry,
        backlog=2,
        acknowledgement_timeout_s=30.0,
        shutdown_timeout_s=2.0,
    )
    telemetry.register_transcript_exporter(exporter.omitted)
    clock = Clock()
    emitted = session_events(clock, telemetry)
    open_session(emitted)
    first = "1" * 32
    second = "2" * 32
    start_turn(emitted, utterance=first)
    finish_reply(emitted)
    acknowledgement = pending()
    exporter.turn_recorded(
        SESSION,
        TurnRecord(
            at=1.0,
            conversation="a" * 32,
            agent="household",
            utterance=first,
            heard="hello",
            reply="hi",
        ),
        acknowledgement,
        final=True,
    )

    start_turn(emitted, utterance=second)
    finish_reply(emitted)
    acknowledgement.settle(True)
    await exporter.shutdown()
    assert telemetry.release_turn(SESSION, second) is TurnSettlement.SETTLED

    failures = [
        fields_of(record)["reason"]
        for record in caplog.records
        if getattr(record, "event", None) == "transcript_export_failed"
    ]
    assert failures == [TranscriptExportFailure.DROPPED]
    turns = [span for span in finished(telemetry, memory) if span.name == "turn"]
    assert len([span for span in turns if span.attributes["vinga.utterance.id"] == first]) == 1


def test_eight_maximal_content_spans_encode_below_three_mib() -> None:
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans

    telemetry, memory = exporting()
    telemetry.register_transcript_exporter()
    clock = Clock()
    emitted = session_events(clock, telemetry)
    open_session(emitted)
    content = "x" * (MAX_CONTENT_BYTES // 2)
    for index in range(8):
        utterance = f"{index:032x}"
        start_turn(emitted, utterance=utterance)
        finish_reply(emitted)
        assert (
            telemetry.settle_turn(SESSION, utterance, {"input": content})
            is TurnSettlement.SETTLED
        )

    turns = [span for span in finished(telemetry, memory) if span.name == "turn"]
    assert len(turns) == 8
    request = encode_spans(turns)
    assert len(request.SerializeToString()) < 3 * 1024 * 1024
