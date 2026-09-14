"""Held turn roots receive acknowledged content exactly once."""

import threading
from collections.abc import Iterator

import pytest

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
from vinga_server import telemetry as telemetry_module
from vinga_server.telemetry import (
    _QUIETING,
    TURN_INPUT,
    TURN_LEGS,
    TURN_OUTPUT,
    Telemetry,
)
from vinga_server.transcript_export import MAX_CONTENT_BYTES


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
    )
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


def test_worker_and_shutdown_contenders_end_once() -> None:
    session = SESSION
    for index in range(100):
        utterance = f"{index:032x}"
        telemetry, memory = _held(utterance)
        barrier = threading.Barrier(3)
        answers: list[bool] = []

        def settle(
            gate: threading.Barrier = barrier,
            results: list[bool] = answers,
            exporter: Telemetry = telemetry,
            identity: str = utterance,
        ) -> None:
            gate.wait()
            results.append(exporter.settle_turn(session, identity, {"input": "x"}))

        def release(
            gate: threading.Barrier = barrier,
            results: list[bool] = answers,
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

        assert answers.count(True) == 1
        assert answers.count(False) == 1
        assert len([span for span in finished(telemetry, memory) if span.name == "turn"]) == 1
        telemetry.release()


def test_the_4097th_policy_evicts_the_oldest_finished_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telemetry_module, "DEFERRED_TURNS", 2)
    omitted: list[str] = []
    telemetry, memory = exporting()
    telemetry.register_transcript_exporter(omitted.append)
    clock = Clock()
    emitted = session_events(clock, telemetry)
    open_session(emitted)
    for index in range(3):
        start_turn(emitted, utterance=f"{index:032x}")
        finish_reply(emitted)

    turns = [span for span in finished(telemetry, memory) if span.name == "turn"]
    assert len(turns) == 1
    assert len(omitted) == 1
    assert telemetry.release_turn(
        SESSION, f"{0:032x}"
    ) is False


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
        assert telemetry.settle_turn(SESSION, utterance, {"input": content})

    turns = [span for span in finished(telemetry, memory) if span.name == "turn"]
    assert len(turns) == 8
    request = encode_spans(turns)
    assert len(request.SerializeToString()) < 3 * 1024 * 1024
