"""What `Telemetry` does with a closed session's transcript (#495).

The exporter's two new methods and nothing else: the narrow retained
context a job is admitted on, and the bounded write that puts one page
of turns onto the trace of the turn each one describes. The worker that
reads the store, bounds the queue and emits the outcome events is next
door in `test_transcript_export.py`; what is here is the half that knows
what a span may say.

Three properties this file exists for, and each is provable only here:

- **The context is a handle, captured at admission.** A job admitted
  while a session's trace was retained exports into that trace however
  far the retention has moved since, which is what makes `no_trace` an
  answer about the moment a session closed.
- **The spans do not ride the shared queue.** That queue drops on
  saturation and cannot answer for delivery, and a transcript that
  never arrived has to be distinguishable from one that did.
- **What a turn's span carries is decided field by field.** A
  transcript is not an event and does not come through the catalog's
  own gate, so the projection's columns and the allowlisted legs are
  what stand between the store's rows and the wire.
"""

import json
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from opentelemetry.trace import TraceFlags

from tests.support.telemetry import (
    SESSION,
    Clock,
    Deliveries,
    close_session,
    exporting,
    finish_reply,
    finished,
    named,
    open_session,
    released,
    session_events,
    start_turn,
)
from vinga_server.telemetry import (
    _QUIETING,
    RETAINED_TRACES,
    RETAINED_TURNS,
    Delivery,
    Telemetry,
    TranscriptTurn,
)

# The name one turn is addressed by, spelled the way the runtime mints
# them. A default rather than a per-case argument, because a row the
# store wrote normally carries one: the null is what a case about the
# un-nested path says out loud.
UTTERANCE = "0f1e2d3c4b5a69780f1e2d3c4b5a6978"


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


def a_turn(index: int = 1, **overrides: Any) -> TranscriptTurn:
    fields: dict[str, Any] = {
        "index": index,
        "id": 4000 + index,
        "t_ms": 1200 * index,
        "agent": "alpha",
        "heard": f"utterance {index}",
        "reply": f"answer {index}",
        "utterance": UTTERANCE,
    }
    fields.update(overrides)
    return TranscriptTurn(**fields)


def attributes(span: Any) -> dict[str, Any]:
    return dict(span.attributes)


# The context a job is admitted on


def test_the_retained_context_answers_after_the_session_closed() -> None:
    """Which is the whole point of it: a transcript export begins where
    the conversation ended, and the span map is popped at
    `session_closed`."""
    telemetry, _ = exporting()
    a_session(telemetry)

    assert telemetry.retained_context(SESSION) is not None


def test_a_session_this_exporter_never_saw_has_no_context() -> None:
    """Absent rather than invented, which is what makes the exporter's
    `no_trace` a real answer decided at admission."""
    telemetry, _ = exporting()
    a_session(telemetry)

    assert telemetry.retained_context("ffffffffffffffffffffffffffffffff") is None


def test_a_context_captured_at_admission_survives_its_own_eviction() -> None:
    """The finding this shape exists for: a job queued behind a slow
    worker used to watch its context age out between the close that made
    it and the worker that reached it, so a healthy export reported that
    the session had no trace.

    Captured at admission, later eviction cannot change the answer, and
    the spans still land against the session that was exported, which is
    where a turn nothing pinned belongs.
    """
    deliveries = Deliveries()
    telemetry, memory = exporting(transcripts=deliveries)
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)
    assert context is not None
    session_span = next(
        span for span in finished(telemetry, memory) if span.name == "session"
    )

    for index in range(RETAINED_TRACES + 4):
        a_session(telemetry, f"{index:032x}")
    assert telemetry.retained_context(SESSION) is None, "the retention never moved"

    assert (
        telemetry.export_transcript(SESSION, context, [a_turn()]) is Delivery.DELIVERED
    )

    (span,) = deliveries.spans()
    assert span.context.trace_id == session_span.context.trace_id
    assert span.parent.span_id == session_span.context.span_id


def test_the_retention_is_the_configured_capacity_plus_the_slack() -> None:
    """A deployment running more than sixty-four sessions at once used
    to evict a LIVE session's context, because the map is written at the
    open and the bound was a constant. It is the configured capacity
    plus the slack now, so every live session stays answerable and the
    after-close window keeps its depth.
    """
    capacity = RETAINED_TRACES + 40
    telemetry, _ = exporting(max_sessions=capacity)
    ids = [f"{index:032x}" for index in range(capacity)]
    for one in ids:
        a_session(telemetry, one)

    assert all(telemetry.retained_context(one) is not None for one in ids)


# What a turn's span carries


def exported(turns: list[TranscriptTurn], **built: Any) -> tuple[Any, list[Any]]:
    """One session's page exported through the delivery seam, and what
    it carried.

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
    answer = telemetry.export_transcript(SESSION, context, turns)
    assert answer is Delivery.DELIVERED, answer
    return (telemetry, memory), deliveries.spans()


def test_one_turn_becomes_one_span_with_its_text_in_the_rendered_fields() -> None:
    """The acceptance, pinned attribute by attribute: the backend
    renders an observation's input and output from these two names, and
    the gate that opened this milestone confirmed it live before the
    exporter was built around the shape."""
    _, spans = exported([a_turn()])

    (span,) = spans
    assert span.name == "transcript"
    assert attributes(span) == {
        "vinga.session.id": SESSION,
        "session.id": SESSION,
        "vinga.turn.index": 1,
        "vinga.turn.id": 4001,
        "vinga.turn.t_ms": 1200,
        "vinga.agent": "alpha",
        "vinga.utterance.id": UTTERANCE,
        "langfuse.observation.input": "utterance 1",
        "langfuse.observation.output": "answer 1",
    }


def test_the_row_id_and_the_ordinal_are_two_facts_on_one_span() -> None:
    """A database-wide row id is not a turn index: a later session's
    first turn begins at an arbitrary number, which is why the ordinal
    is carried separately and the id is kept beside it for correlating
    an observation back to the store."""
    _, spans = exported([a_turn(index=1, id=90210)])

    (span,) = spans
    assert attributes(span)["vinga.turn.index"] == 1
    assert attributes(span)["vinga.turn.id"] == 90210


def test_a_page_becomes_one_span_per_turn_in_order() -> None:
    _, spans = exported([a_turn(index) for index in (1, 2, 3)])

    assert [attributes(span)["vinga.turn.index"] for span in spans] == [1, 2, 3]
    assert [attributes(span)["langfuse.observation.input"] for span in spans] == [
        "utterance 1",
        "utterance 2",
        "utterance 3",
    ]


def test_an_absent_text_half_contributes_no_attribute() -> None:
    """Rather than a null, which would be a claim the store did not
    make: a turn recorded before the text switch went on has nothing to
    say on that half."""
    _, spans = exported([a_turn(heard=None)])

    (span,) = spans
    assert "langfuse.observation.input" not in attributes(span)
    assert attributes(span)["langfuse.observation.output"] == "answer 1"


def test_the_legs_ride_one_canonical_json_string_attribute() -> None:
    """The exact wire encoding, pinned as a string rather than as a
    parsed shape: span attributes take primitives and never mappings,
    and canonical means sorted keys with no extra whitespace so the same
    legs produce the same bytes on every run."""
    legs = [
        {"text": "Let me ask.", "agent": "alpha"},
        {"text": "Done.", "agent": "beta"},
    ]

    _, spans = exported([a_turn(legs=legs)])

    (span,) = spans
    assert attributes(span)["langfuse.observation.metadata.legs"] == (
        '[{"agent":"alpha","text":"Let me ask."},{"agent":"beta","text":"Done."}]'
    )


def test_the_legs_carry_their_agent_and_text_and_nothing_else() -> None:
    """Allowlisted rather than serialized, which is what keeps the token
    halves off the span even though the column holds them: those are
    metadata the generation spans already carry, and what this
    observation adds is content and its attribution."""
    legs = [
        {
            "agent": "alpha",
            "text": "Let me ask.",
            "input_tokens": 8675309,
            "output_tokens": 5551212,
        }
    ]

    _, spans = exported([a_turn(legs=legs)])

    (span,) = spans
    carried = attributes(span)["langfuse.observation.metadata.legs"]
    assert json.loads(carried) == [{"agent": "alpha", "text": "Let me ask."}]
    assert "8675309" not in carried
    assert "5551212" not in carried


def test_a_turn_no_handover_split_carries_no_legs_attribute() -> None:
    """Which is most turns: the reply column is the whole of them, and
    an empty array would be an attribute saying nothing."""
    _, spans = exported([a_turn(legs=None), a_turn(index=2, legs=[])])

    assert all(
        "langfuse.observation.metadata.legs" not in attributes(span) for span in spans
    )


# Which turn a transcript is filed under


def spoken(
    utterances: "list[str]", turns: list[TranscriptTurn]
) -> tuple[list[Any], list[Any]]:
    """One session that actually spoke, its page exported, and both
    halves of the comparison: the transcript spans that were delivered,
    and every span the session itself finished.

    A real session rather than a planted pin, because the claim is about
    the turn the RUNTIME opened: `turn_started` is what mints the
    utterance, opens the turn span and retains its context, and a case
    that stored a context by hand would prove the lookup and nothing
    about what it finds.
    """
    deliveries = Deliveries()
    telemetry, memory = exporting(transcripts=deliveries)
    clock = Clock()
    events = session_events(clock, telemetry, session=SESSION)
    open_session(events)
    for utterance in utterances:
        clock.tick(1.0)
        start_turn(events, utterance=utterance)
        finish_reply(events)
    clock.tick(1.0)
    close_session(events)
    context = telemetry.retained_context(SESSION)
    assert context is not None
    answer = telemetry.export_transcript(SESSION, context, turns)
    assert answer is Delivery.DELIVERED, answer
    return deliveries.spans(), finished(telemetry, memory)


def by_utterance(spans: list[Any]) -> dict[str, Any]:
    """The session's turn spans, each under the utterance it answers,
    which is how a reader with a stored row finds one."""
    return {
        attributes(span)["vinga.utterance.id"]: span
        for span in spans
        if span.name == "turn"
    }


def test_a_transcript_is_a_child_of_the_turn_span_it_describes() -> None:
    """The defect this milestone closes: the words were on the session's
    trace while the turn that spoke them was a wordless trace of its
    own, so a reader had the timings on one and the dialogue on another
    with no field on either naming the other.
    """
    written, spans = spoken(["u-one"], [a_turn(utterance="u-one")])

    (transcript,) = written
    turn = by_utterance(spans)["u-one"]
    assert transcript.context.trace_id == turn.context.trace_id
    assert transcript.parent.span_id == turn.context.span_id
    # And NOT where it used to go, which is what says the nesting moved
    # rather than was merely added: a turn span is a root trace of its
    # own, so its trace is not the session's.
    assert transcript.context.trace_id != named(spans, "session").context.trace_id


def test_two_turns_of_one_page_land_in_two_different_traces() -> None:
    """The case a single passed context used to make impossible. A page
    is a page of the STORE's rows and its turns are unrelated traces, so
    the parent is resolved per turn rather than once per call.
    """
    written, spans = spoken(
        ["u-one", "u-two"],
        [a_turn(1, utterance="u-one"), a_turn(2, utterance="u-two")],
    )

    first, second = written
    turns = by_utterance(spans)
    assert first.context.trace_id == turns["u-one"].context.trace_id
    assert second.context.trace_id == turns["u-two"].context.trace_id
    assert first.context.trace_id != second.context.trace_id


def test_a_handovers_two_rows_land_under_the_one_turn_span() -> None:
    """The many-to-one the join exists for: the store writes one row per
    turn AND conversation, so a reply that handed over is two rows
    answering one utterance, and one turn span is what both of them answer to."""
    written, spans = spoken(
        ["u-one"], [a_turn(1, utterance="u-one"), a_turn(2, utterance="u-one")]
    )

    turn = by_utterance(spans)["u-one"]
    assert len(written) == 2
    assert {span.context.trace_id for span in written} == {turn.context.trace_id}
    assert {span.parent.span_id for span in written} == {turn.context.span_id}


def test_a_row_with_no_utterance_stays_under_the_session_span() -> None:
    """A turn recorded before this correlation existed, or by a turn no
    span was opened for. It keeps the parent every transcript had
    before this change rather than being dropped: a reader who cannot be
    told which turn is better served by the words under the session than
    by no words at all."""
    written, spans = spoken(["u-one"], [a_turn(utterance=None)])

    (transcript,) = written
    session_span = named(spans, "session")
    assert transcript.context.trace_id == session_span.context.trace_id
    assert transcript.parent.span_id == session_span.context.span_id


def test_an_utterance_no_turn_was_opened_for_stays_under_the_session() -> None:
    """The store knows a name this exporter never saw, which is what a
    row written by another process, or by a session this exporter was
    not attached to, looks like from here."""
    written, spans = spoken(["u-one"], [a_turn(utterance="never-opened")])

    (transcript,) = written
    session_span = named(spans, "session")
    assert transcript.context.trace_id == session_span.context.trace_id
    assert transcript.parent.span_id == session_span.context.span_id


def test_a_turn_evicted_past_the_retention_stays_under_the_session() -> None:
    """The bound is per session and it is real: a conversation longer
    than `RETAINED_TURNS` drops its oldest turn pins, and the transcript
    of one of those is filed where it can honestly be filed rather than
    under a turn that is no longer addressable."""
    utterances = [f"u-{index}" for index in range(RETAINED_TURNS + 1)]

    written, spans = spoken(utterances, [a_turn(utterance=utterances[0])])

    (transcript,) = written
    session_span = named(spans, "session")
    assert transcript.context.trace_id == session_span.context.trace_id
    assert transcript.parent.span_id == session_span.context.span_id
    # The youngest turn is still addressable, so this is the eviction
    # and not the lookup failing for everything.
    assert utterances[-1] in by_utterance(spans)


def test_the_utterance_rides_the_span_as_well_as_deciding_its_parent() -> None:
    """One shared correlation key, on the turn span and on the
    transcript: the nesting is then readable as data rather than only as
    a parent pointer, and a reader holding a stored row names the same
    turn this observation does."""
    _, spans = exported([a_turn(utterance="u-one")])

    (span,) = spans
    assert attributes(span)["vinga.utterance.id"] == "u-one"


def test_a_row_with_no_utterance_contributes_no_attribute() -> None:
    """The absence rule every other optional half keeps: an attribute
    saying `None` would be a claim the store did not make."""
    _, spans = exported([a_turn(utterance=None)])

    (span,) = spans
    assert "vinga.utterance.id" not in attributes(span)


# Where they go, and what the call answers


def test_a_transcript_span_never_rides_the_shared_batch_queue() -> None:
    """The transport half of the design, and the review finding behind
    it: the shared queue drops on saturation and swallows a collector
    failure, so a transcript that never arrived would look exactly like
    one that did. These go out as a bounded call with an answer, and
    nothing of them reaches the queue the session's own spans use.
    """
    telemetry, memory = exporting()

    (telemetry, memory), spans = exported([a_turn()])

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
        telemetry.export_transcript(SESSION, context, [a_turn()])
        is Delivery.UNDELIVERED
    )


def test_a_delivery_that_raises_answers_undelivered_too() -> None:
    """Contained and never looked at: what a failing export is holding
    is the endpoint and the credentials that reach it."""
    telemetry, _ = exporting(
        transcripts=Deliveries(raises=RuntimeError("https://user:pw@host"))
    )
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)

    assert (
        telemetry.export_transcript(SESSION, context, [a_turn()])
        is Delivery.UNDELIVERED
    )


def test_an_unsampled_parent_is_no_trace_without_a_delivery_attempt() -> None:
    """Source sampling is an intentional omission, not a transport failure."""
    deliveries = Deliveries()
    telemetry, _ = exporting(transcripts=deliveries)
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)
    assert context is not None
    unsampled = replace(context, trace_flags=TraceFlags(TraceFlags.DEFAULT))

    assert (
        telemetry.export_transcript(SESSION, unsampled, [a_turn()])
        is Delivery.NO_TRACE
    )
    assert deliveries.batches == []


def test_an_unsampled_turn_parent_is_dropped_before_otlp_encoding() -> None:
    """Turn sampling is independent of the session root that retains it."""
    deliveries = Deliveries()
    telemetry, _ = exporting(transcripts=deliveries)
    clock = Clock()
    events = session_events(clock, telemetry)
    open_session(events)
    start_turn(events, utterance=UTTERANCE)
    finish_reply(events)
    close_session(events)
    context = telemetry.retained_context(SESSION)
    assert context is not None
    pinned = context.turns[UTTERANCE]
    context.turns[UTTERANCE] = replace(
        pinned,
        trace_flags=TraceFlags(TraceFlags.DEFAULT),
    )

    assert (
        telemetry.export_transcript(SESSION, context, [a_turn()])
        is Delivery.NO_TRACE
    )
    assert deliveries.batches == []


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
        telemetry.export_transcript(SESSION, context, [a_turn()]) is Delivery.STOPPED
    )
    assert deliveries.batches == [], "a stopped exporter still asked the far side"


def test_an_empty_page_asks_the_far_side_for_nothing() -> None:
    """A request carrying no spans is a round trip bought for nothing,
    and the answer it would come back with says nothing either."""
    deliveries = Deliveries()
    telemetry, _ = exporting(transcripts=deliveries)
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)

    assert telemetry.export_transcript(SESSION, context, []) is Delivery.DELIVERED
    assert deliveries.batches == []


def test_each_page_is_delivered_as_its_own_batch() -> None:
    """One page read, one bounded call, which is what keeps an
    arbitrarily long session inside bounded memory and bounded
    per-request work: the pages are not accumulated anywhere."""
    deliveries = Deliveries()
    telemetry, _ = exporting(transcripts=deliveries)
    a_session(telemetry)
    context = telemetry.retained_context(SESSION)

    telemetry.export_transcript(SESSION, context, [a_turn(1), a_turn(2)])
    telemetry.export_transcript(SESSION, context, [a_turn(3)])

    assert [len(batch) for batch in deliveries.batches] == [2, 1]
