"""What `Telemetry` does with a closed session's assembled requests
(#502, M5).

The exporter's one new method and nothing else: the bounded write that
puts a session's staged LLM rounds onto the trace that session was
exported under. The module that stages them, bounds them and emits the
outcome events is next door in `test_llm_input_export.py`; what is here
is the half that knows what a span may say.

Three properties this file exists for, and each is provable only here:

- **The request reaches exactly one attribute.** This is the widest
  content class in the repository, so the claim worth pinning is not
  that the request arrives but that it arrives in one field of one span
  and nowhere else, the logs included.
- **The spans do not ride the shared queue.** That queue drops on
  saturation and cannot answer for delivery, and this class has no
  local store behind it: an export that vanished would leave nothing
  anywhere to go back and read.
- **What a round's span carries is decided field by field.** An
  assembled request is not an event and does not come through the
  catalog's gate, so this function's own decisions are what stand
  between a session's working state and the wire.
"""

import logging
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from tests.support.events import both_formats
from tests.support.telemetry import (
    SESSION,
    Clock,
    Deliveries,
    close_session,
    exporting,
    finished,
    named,
    open_session,
    released,
    session_events,
)
from vinga_server import telemetry as telemetry_module
from vinga_server.telemetry import (
    _QUIETING,
    Delivery,
    LlmInputRound,
    Telemetry,
    TranscriptTurn,
)

# A credential-shaped value planted in the request, because this is the
# surface where the whole assembled prompt travels: if anything of it
# ever reached a second place, this is the shape of thing that would be
# in it.
REQUEST_SENTINEL = "sk-live-0LLMINPUT-SENTINEL"


@pytest.fixture(autouse=True)
def _no_lease_outlives_its_case() -> Iterator[None]:
    """Every exporter a case built is released at the end of it, the
    rule `test_telemetry.py` states: the SDK's silence is one
    process-wide lease, so one left held silences the namespace for
    everything after it."""
    yield
    released()
    assert _QUIETING.held() == 0, "a case left an exporter holding the SDK's silence"


def a_session(telemetry: Telemetry, session: str = SESSION) -> None:
    """One whole session, opened and closed, which is what puts a trace
    in the retention."""
    clock = Clock()
    events = session_events(clock, telemetry, session=session)
    open_session(events)
    clock.tick(1.0)
    close_session(events)


def a_round(index: int = 1, **overrides: Any) -> LlmInputRound:
    fields: dict[str, Any] = {
        "index": index,
        "purpose": "reply",
        "agent": "alpha",
        "request": f'{{"messages":[{{"content":"round {index}"}}]}}',
    }
    fields.update(overrides)
    return LlmInputRound(**fields)


def attributes(span: Any) -> dict[str, Any]:
    return dict(span.attributes)


def exported(rounds: list[LlmInputRound], **built: Any) -> tuple[Any, list[Any]]:
    """One session's staged rounds exported through the delivery seam,
    and what they carried.

    Through `build_telemetry(transcripts=...)` rather than by reaching
    into the exporter, because that seam is the interface: a case that
    substituted a private attribute would be pinning where the instance
    happens to be kept.
    """
    deliveries = Deliveries(**built)
    telemetry, memory = exporting(transcripts=deliveries)
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)
    assert context is not None
    answer = telemetry.export_llm_input(SESSION, context, rounds)
    assert answer is Delivery.DELIVERED, answer
    return (telemetry, memory), deliveries.spans()


# What a round's span carries


def test_one_round_becomes_one_span_with_the_request_as_its_input() -> None:
    """The acceptance, pinned attribute by attribute: the backend
    renders an observation's input from this name, which is what makes
    the assembled request readable as what the model was given rather
    than as a blob in a metadata field."""
    _, spans = exported([a_round()])

    (span,) = spans
    assert span.name == "llm_input"
    assert attributes(span) == {
        "vinga.session.id": SESSION,
        "session.id": SESSION,
        "vinga.llm.round": 1,
        "vinga.llm.purpose": "reply",
        "vinga.agent": "alpha",
        "langfuse.observation.input": '{"messages":[{"content":"round 1"}]}',
    }


def test_a_session_becomes_one_span_per_round_in_order() -> None:
    """The ordinal is what puts the observations back in the order the
    model saw them, whatever the two bounds dropped in between."""
    _, spans = exported([a_round(index) for index in (1, 2, 3)])

    assert [attributes(span)["vinga.llm.round"] for span in spans] == [1, 2, 3]


def test_the_purpose_tells_a_recap_round_from_a_reply_round() -> None:
    """Both call shapes are staged, so a reader asking what the model
    saw gets the summarization as well as the answer, and can tell which
    is which."""
    _, spans = exported([a_round(1), a_round(2, purpose="recap")])

    first, second = spans
    assert attributes(first)["vinga.llm.purpose"] == "reply"
    assert attributes(second)["vinga.llm.purpose"] == "recap"


def test_a_round_with_no_agent_contributes_no_attribute() -> None:
    """The absence rule every other optional half keeps: an attribute
    saying `None` would be a claim nothing made."""
    _, spans = exported([a_round(agent=None)])

    (span,) = spans
    assert "vinga.agent" not in attributes(span)


def test_the_spans_land_under_the_session_span_of_its_own_trace() -> None:
    """The addressing this class asks for: a recap round belongs to no
    turn at all and a reply round is several requests inside one, so
    what these answer to is the session, which is the trace a reader
    arrives with."""
    deliveries = Deliveries()
    telemetry, memory = exporting(transcripts=deliveries)
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)
    session_span = named(finished(telemetry, memory), "session")

    assert telemetry.export_llm_input(SESSION, context, [a_round()]) is Delivery.DELIVERED

    (span,) = deliveries.spans()
    assert span.context.trace_id == session_span.context.trace_id
    assert span.parent.span_id == session_span.context.span_id


def test_the_board_name_rides_the_span_the_way_every_post_close_span_does() -> None:
    """Off the pinned context rather than off a configuration read, so a
    board renamed since the session ran cannot rename what that
    session's spans say."""
    deliveries = Deliveries()
    telemetry, _ = exporting(transcripts=deliveries)
    clock = Clock()
    events = session_events(clock, telemetry)
    open_session(events, device_name="the kitchen")
    clock.tick(1.0)
    close_session(events)
    context = telemetry.retained_context(SESSION)

    telemetry.export_llm_input(SESSION, context, [a_round()])

    (span,) = deliveries.spans()
    assert attributes(span)["vinga.device.name"] == "the kitchen"


# Where they go, and what the call answers


def test_an_assembled_request_never_rides_the_shared_batch_queue() -> None:
    """The transport half of the design: that queue drops on saturation
    and swallows a collector failure, and this class has no local store
    behind it, so an export that vanished would leave nothing anywhere
    to go back and read."""
    (telemetry, memory), spans = exported([a_round()])

    assert len(spans) == 1
    assert [span.name for span in finished(telemetry, memory)] == ["session"]


def test_a_delivery_the_far_side_refuses_answers_undelivered() -> None:
    """Read off the exporter's own result rather than off an exception,
    because a batch the backend declined is not an error this process
    raised."""
    telemetry, _ = exporting(transcripts=Deliveries(answer=False))
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)

    assert (
        telemetry.export_llm_input(SESSION, context, [a_round()])
        is Delivery.UNDELIVERED
    )


def test_a_delivery_that_raises_answers_undelivered_too() -> None:
    """Contained and never looked at: what a failing export is holding
    is the endpoint, the credentials that reach it, and on this surface
    the whole of what a model was given."""
    telemetry, _ = exporting(
        transcripts=Deliveries(raises=RuntimeError("https://user:pw@host"))
    )
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)

    assert (
        telemetry.export_llm_input(SESSION, context, [a_round()])
        is Delivery.UNDELIVERED
    )


def test_an_exporter_that_has_stopped_accepting_attempts_nothing() -> None:
    """Shutdown territory rather than a delivery answer, which is what
    lets the worker report it as the job being dropped: nothing was
    tried, so nothing can be said about the backend."""
    deliveries = Deliveries()
    telemetry, _ = exporting(transcripts=deliveries)
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)
    telemetry.stop_accepting()

    assert (
        telemetry.export_llm_input(SESSION, context, [a_round()]) is Delivery.STOPPED
    )
    assert deliveries.batches == [], "a stopped exporter still asked the far side"


def test_no_staged_rounds_ask_the_far_side_for_nothing() -> None:
    """A request carrying no spans is a round trip bought for nothing,
    and the answer it would come back with says nothing either."""
    deliveries = Deliveries()
    telemetry, _ = exporting(transcripts=deliveries)
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)

    assert telemetry.export_llm_input(SESSION, context, []) is Delivery.DELIVERED
    assert deliveries.batches == []


def test_a_context_that_was_never_pinned_writes_nothing() -> None:
    """The caller decides `no_trace` at admission, so this is reached
    with a real pin or not at all; asserted rather than assumed, because
    a span written into no trace at all would be content sent somewhere
    nobody can find it."""
    deliveries = Deliveries()
    telemetry, _ = exporting(transcripts=deliveries)
    a_session(telemetry)

    assert (
        telemetry.export_llm_input(SESSION, "not-a-context", [a_round()])
        is Delivery.DELIVERED
    )
    assert deliveries.batches == []


# The one attribute, and nowhere else


def test_the_request_reaches_one_attribute_and_no_log_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The claim this file exists for, and the inverse of the usual
    one: the planted value MUST reach the span, because that is the
    surface the flag authorizes, and must reach nothing else this
    process writes down.
    """
    caplog.set_level(logging.DEBUG)

    _, spans = exported([a_round(request=f'{{"tool_result":"{REQUEST_SENTINEL}"}}')])

    (span,) = spans
    carried = attributes(span)
    assert REQUEST_SENTINEL in carried["langfuse.observation.input"]
    elsewhere = {
        name: value
        for name, value in carried.items()
        if name != "langfuse.observation.input"
    }
    assert REQUEST_SENTINEL not in repr(elsewhere), "the request reached a second field"
    assert REQUEST_SENTINEL not in both_formats(caplog), "the request reached a log record"


def test_a_failed_delivery_says_nothing_of_what_it_was_carrying(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The containment, driven: an exporter whose call raises with the
    request in the message must leave none of it behind, which is the
    reason every exception here is unbound and unread."""
    caplog.set_level(logging.DEBUG)
    telemetry, _ = exporting(
        transcripts=Deliveries(raises=RuntimeError(f"sent {REQUEST_SENTINEL}"))
    )
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)

    answer = telemetry.export_llm_input(
        SESSION, context, [a_round(request=REQUEST_SENTINEL)]
    )

    assert answer is Delivery.UNDELIVERED
    assert REQUEST_SENTINEL not in both_formats(caplog)


# --- the transport both content exporters share ------------------------
#
# The second caller is what made this a question. One worker delivering
# through a lazily built exporter was safe by having nobody to race;
# this module's worker is a second, on a thread of its own, and the two
# reach the same instance through the same path.

# How many times the concurrent case is run. A concurrency claim proved
# once is a claim about one interleaving, and the window here is the few
# microseconds between a `None` check and the assignment after it, so
# the case is repeated until a run that never widened it would be
# remarkable rather than likely.
CONCURRENT_RUNS = 50


# How long one export stays inside the transport. Long enough that the
# teardown, which runs behind the batch provider's own shutdown, is
# still arriving while a delivery is in flight: a case whose deliveries
# were over before the close began would drive the overlap it is named
# for exactly never, which is what the first draft of it did.
EXPORT_S = 0.02


class Shared:
    """The one OTLP exporter both workers reach, watching for the three
    things that can go wrong when two of them do.

    `built` catches the lost instance: two first calls that both see
    `None` build two, and one of them is assigned over and never shut
    down. `peak` catches the shared mutable client: the SDK's HTTP
    exporter holds a session that is not safe to call from two threads
    at once. `closed_while_exporting` catches the third, which is the
    teardown: a shutdown that lands inside an export is the same race
    wearing different clothes.

    `entered` is what makes the third observable rather than lucky. The
    teardown runs behind the batch provider's own shutdown, so a case
    that released it the moment the barrier opened would find every
    delivery already finished; the run waits for a delivery to be
    genuinely inside before it tears anything down.
    """

    built: "list[Shared]" = []

    def __init__(self) -> None:
        # Wide enough that two callers arriving together genuinely
        # overlap here, which is the window a lock has to close.
        time.sleep(0.002)
        self._lock = threading.Lock()
        self.inside = 0
        self.peak = 0
        self.closed_while_exporting = False
        self.entered = threading.Event()
        Shared.built.append(self)

    def export(self, spans: Any) -> Any:
        from opentelemetry.sdk.trace.export import SpanExportResult

        with self._lock:
            self.inside += 1
            self.peak = max(self.peak, self.inside)
        self.entered.set()
        time.sleep(EXPORT_S)
        with self._lock:
            self.inside -= 1
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        with self._lock:
            if self.inside:
                self.closed_while_exporting = True


def an_export_in_flight(timeout_s: float = 10.0) -> None:
    """Wait until a delivery is genuinely inside the transport.

    Bounded and never asserted on: a run where the teardown won the race
    outright is a legal interleaving and not a broken case, so this
    returns either way and the invariants below are what carry the
    claim.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if Shared.built:
            Shared.built[0].entered.wait(timeout_s)
            return
        time.sleep(0.001)


def a_turn_row(index: int = 1) -> TranscriptTurn:
    return TranscriptTurn(
        index=index, id=4000 + index, t_ms=1200, agent="alpha", heard="hi", reply="ho"
    )


def deliver_both(telemetry: Telemetry, context: Any) -> list[Delivery]:
    """Both content exporters delivering at once, with the teardown
    landing in the middle rather than politely behind them, and what
    each of them answered.

    A function of its own rather than a loop body, so the two threads
    close over arguments rather than over a loop variable, and so the
    one thing a run is about, the overlap, has a name.
    """
    together = threading.Barrier(3)
    answers: list[Delivery] = []
    answered = threading.Lock()

    def deliver(which: str) -> None:
        together.wait(10.0)
        answer = (
            telemetry.export_transcript(SESSION, context, [a_turn_row()])
            if which == "transcripts"
            else telemetry.export_llm_input(SESSION, context, [a_round()])
        )
        with answered:
            answers.append(answer)

    threads = [
        threading.Thread(target=deliver, args=(which,))
        for which in ("transcripts", "llm_input")
    ]
    for one in threads:
        one.start()
    together.wait(10.0)
    # The teardown lands while a delivery is inside the transport,
    # which is the overlap this case is named for.
    an_export_in_flight()
    telemetry.release()
    for one in threads:
        one.join(10.0)
    assert len(answers) == 2, "a delivery never came back at all"
    return answers


def test_two_workers_delivering_at_once_share_one_serialized_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transcript and LLM-input delivery concurrently, with the teardown
    overlapping them, run fifty times over.

    The claim is one transport with one owner: at most one is ever
    built, only one thread is ever inside it, and a shutdown never lands
    in the middle of an export. Before this module existed the seam had
    a single caller and none of that could be observed; the second
    worker is what turned a safe laziness into a race, which is the fact
    this case exists to keep true rather than to rediscover.

    Driven through `build_telemetry` with no exporter handed in, because
    the construction half of the claim is only reachable on the path
    that actually constructs one.

    **Which answer a delivery gets is deliberately not pinned.** A
    teardown racing two deliveries may legitimately reach the transport
    first, and a delivery that finds it closed says so: that is the
    shutdown answer both callers turn into a drop, and demanding a
    success would be pinning an interleaving rather than an invariant.
    What IS pinned is that every answer is one of the two legal ones and
    that the export path was genuinely exercised across the runs, so a
    case that silently stopped delivering anything fails rather than
    passes.
    """
    monkeypatch.setattr(telemetry_module, "_otlp_exporter", Shared)
    delivered = 0
    for run in range(CONCURRENT_RUNS):
        Shared.built.clear()
        telemetry, _ = exporting()
        a_session(telemetry)
        context = telemetry.retained_context(SESSION)
        assert context is not None

        answers = deliver_both(telemetry, context)

        assert all(
            answer in (Delivery.DELIVERED, Delivery.STOPPED) for answer in answers
        ), f"run {run}: {answers}"
        delivered += sum(answer is Delivery.DELIVERED for answer in answers)
        assert len(Shared.built) <= 1, (
            f"run {run}: {len(Shared.built)} transports were built, "
            "so one was assigned over and never shut down"
        )
        for transport in Shared.built:
            assert transport.peak <= 1, (
                f"run {run}: {transport.peak} threads were inside one HTTP exporter"
            )
            assert not transport.closed_while_exporting, (
                f"run {run}: the teardown shut the transport down mid-export"
            )
        released()

    assert delivered, (
        "no delivery in any run reached the transport, so the case proved nothing"
    )


def test_a_delivery_arriving_after_the_teardown_builds_no_second_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A closed transport stays closed.

    The case the concurrent one above cannot reach, because it is not a
    race at all: a worker left behind by its own bounded join arrives
    here long after the teardown has been and gone. Without a flag
    saying so it would find the field back at `None`, build a fresh HTTP
    exporter after the shutdown, and leave a socket nobody owns and
    nobody will ever close.

    Shutdown territory rather than a delivery answer, because nothing
    was attempted: both callers turn that into the drop it is.
    """
    monkeypatch.setattr(telemetry_module, "_otlp_exporter", Shared)
    Shared.built.clear()
    telemetry, _ = exporting()
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)
    assert telemetry.export_llm_input(SESSION, context, [a_round()]) is Delivery.DELIVERED
    assert len(Shared.built) == 1

    telemetry.release()

    assert telemetry.export_llm_input(SESSION, context, [a_round()]) is Delivery.STOPPED
    assert len(Shared.built) == 1, "a transport was built after the teardown"
