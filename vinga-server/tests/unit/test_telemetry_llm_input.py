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
from vinga_server.telemetry import (
    _QUIETING,
    Delivery,
    LlmInputRound,
    Telemetry,
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
