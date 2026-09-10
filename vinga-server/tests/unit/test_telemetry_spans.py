"""The stage spans, and the arithmetic that puts them where they were.

A turn trace is worth opening because of what is INSIDE it, and what is
inside it is four stages nobody watched while they ran: an ASR call, a
generation per round, a synthesis stream per sentence, and the paced
interval the frames actually went out over. Every one of them is
assembled retrospectively out of the event that ended it and the
duration the pipeline had already measured, so what these cases check is
three things at once.

**The shape.** Each stage is a child of its turn, not a link and not a
sibling: an ASR call is part of the turn it transcribed, where a turn is
only part of the session it was spoken in.

**The arithmetic.** A span's extent is the measurement, converted
through the one offset. Where the event measured nothing the span has no
extent, which says the stage ended here and declines to say when it
began, and that is a different claim from a duration of zero.

**The vocabulary.** The GenAI correspondence is pinned key by key,
because it is the one table in this module that a backend nobody here
controls reads by name: getting `gen_ai.provider.name` right is what
makes a round attributable in a tool that has never heard of vinga.
Everything else is `vinga.*`, and the four ASR ends spell their outcome
with the catalog's own event names rather than with a second set of
words.

The fold's DEFAULT is not re-proved here (`test_telemetry.py` owns it);
what is proved is that the twelve names with a shape of their own do not
also fold, and that the events beside them still do.
"""

from collections.abc import Iterator

import pytest

from tests.support.telemetry import (
    AGENT,
    CONVERSATION,
    DEVICE,
    OTHER_AGENT,
    SESSION,
    Clock,
    abandon_transcription,
    close_session,
    drop_frames,
    exporting,
    finish_reply,
    finish_speaking,
    finished,
    hand_over,
    hear,
    hear_nothing,
    named,
    open_session,
    provider_failed,
    released,
    retry_round,
    round_done,
    session_events,
    start_speaking,
    start_turn,
    suppress_barge_in,
    synthesize,
)
from vinga_server.events.values import ReplyOutcome
from vinga_server.telemetry import (
    _QUIETING,
    ASR_SPAN,
    LLM_SPAN,
    PLAYBACK_SPAN,
    TTS_SPAN,
    TURN_SPAN,
)

# One nanosecond per millisecond of the durations below, so a case can
# say what it expects in the units the events carry.
MS = 1_000_000


@pytest.fixture(autouse=True)
def _no_lease_outlives_its_case() -> Iterator[None]:
    """Every exporter a case here built is released at the end of it.

    The SDK's silence is one process-wide reference-counted lease, so an
    exporter nobody released keeps the namespace quiet for every case
    after it, in this file and in every other. Drained and then
    asserted, which is the pattern `test_telemetry.py` established: a
    leak this tidies away is a leak a server would have too.
    """
    yield
    released()
    assert _QUIETING.held() == 0, "a case left an exporter holding the SDK's silence"



def spans_of(name: str, spans: list) -> list:
    return [span for span in spans if span.name == name]


def a_turn(clock: Clock, telemetry) -> object:
    """A session with a turn open in it, which is what every stage span
    below hangs inside."""
    events = session_events(clock, telemetry)
    open_session(events)
    clock.tick(1.0)
    start_turn(events)
    return events


# --- ASR: four ends, one stage ----------------------------------------


def test_a_transcription_that_answered_is_a_span_inside_the_turn() -> None:
    """The ordinary end, and the parentage claim for all four: an ASR
    call is a CHILD of its turn, in the turn's own trace."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.3)
    heard_at = hear(events, duration_s=0.9, asr_ms=300)
    clock.tick(1.0)
    finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    asr, turn = named(spans, ASR_SPAN), named(spans, TURN_SPAN)
    assert asr.parent.span_id == turn.context.span_id
    assert asr.context.trace_id == turn.context.trace_id
    assert asr.attributes["vinga.asr.outcome"] == "heard"
    assert asr.attributes["vinga.asr.duration_s"] == pytest.approx(0.9)
    assert asr.attributes["vinga.asr.language"] == "en"
    assert asr.end_time - asr.start_time == 300 * MS
    assert asr.end_time == int((heard_at + telemetry._offset) * 1e9)


def test_an_empty_transcript_is_a_span_of_its_own_and_not_a_failure() -> None:
    """Gap C, which is the issue's motivating case: 0.9 s of speech
    transcribed to nothing used to be a log line and is now a span with
    a real duration.

    Marked as an outcome and never as an error: the engine answered, and
    an operator sent looking at a provider by a red span would be sent
    to the wrong place.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.25)
    hear_nothing(events, duration_s=0.9, asr_ms=220)
    finish_reply(events, outcome=ReplyOutcome.NOTHING_HEARD, sentences=0)
    close_session(events)

    asr = named(finished(telemetry, memory), ASR_SPAN)
    assert asr.attributes["vinga.asr.outcome"] == "nothing_heard"
    assert asr.attributes["vinga.asr.duration_s"] == pytest.approx(0.9)
    assert asr.end_time - asr.start_time == 220 * MS
    assert asr.status.status_code.name != "ERROR"


def test_a_failed_transcription_is_the_one_asr_span_marked_failed() -> None:
    """The only one of the four that IS a failure, carrying the
    exception's class name and nothing else of it."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(1.5)
    provider_failed(events, stage="asr", duration_ms=1500)
    finish_reply(events, outcome=ReplyOutcome.FAILED, sentences=0)
    close_session(events)

    asr = named(finished(telemetry, memory), ASR_SPAN)
    assert asr.attributes["vinga.asr.outcome"] == "provider_failed"
    assert asr.attributes["vinga.asr.error"] == "TimeoutError"
    assert asr.status.status_code.name == "ERROR"
    # No description: the only prose a failure has is the far side's
    # message, and the class name is the whole of what may travel.
    assert asr.status.description is None
    assert asr.end_time - asr.start_time == 1500 * MS


def test_an_abandoned_transcription_is_an_asr_span_and_not_a_failure() -> None:
    """The fourth end, from M1's review round: the answer stopped being
    wanted. It bounds a real interval (how long the call had run) and
    nothing failed, so nothing is marked failed."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.14)
    abandon_transcription(events)
    finish_reply(events, outcome=ReplyOutcome.BARGED_IN, sentences=0)
    close_session(events)

    asr = named(finished(telemetry, memory), ASR_SPAN)
    assert asr.attributes["vinga.asr.outcome"] == "transcription_abandoned"
    assert asr.status.status_code.name != "ERROR"
    assert asr.end_time - asr.start_time == 140 * MS


def test_an_asr_outcome_that_measured_nothing_is_a_span_with_no_extent() -> None:
    """A `heard` with no `asr_ms` (a shape the catalog admits) says when
    the stage ended and nothing about when it began. The span says
    exactly that much rather than inventing a start."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.3)
    hear(events, asr_ms=None, language=None)
    finish_reply(events)
    close_session(events)

    asr = named(finished(telemetry, memory), ASR_SPAN)
    assert asr.end_time == asr.start_time
    assert "vinga.asr.language" not in asr.attributes


def test_a_failure_at_another_stage_stays_a_span_event() -> None:
    """`provider_failed` is an ASR outcome only where it names the ASR
    stage. An LLM or TTS failure ends no interval this exporter draws,
    so it folds onto the turn with its fields, which is where a reader
    looking at a failed reply finds it."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.5)
    provider_failed(events, stage="tts", duration_ms=700)
    finish_reply(events, outcome=ReplyOutcome.FAILED, sentences=0)
    close_session(events)

    spans = finished(telemetry, memory)
    turn = named(spans, TURN_SPAN)
    assert spans_of(ASR_SPAN, spans) == []
    assert [event.name for event in turn.events] == ["provider_failed"]
    assert turn.events[0].attributes["stage"] == "tts"


# --- the LLM round, and the settled vocabulary -------------------------


def test_one_round_is_one_span_with_the_settled_gen_ai_keys() -> None:
    """The correspondence table, pinned key by key and value by value.

    This is the one set of attribute names in this module a foreign
    backend reads by name, so it is asserted exactly rather than by
    prefix: `type` becomes the provider name, `model` the request model,
    `host` the server address, and the two token counts the GenAI usage
    keys. Only the configured entry's name stays vinga's word.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.8)
    ended = round_done(
        events,
        duration_ms=800,
        first_token_ms=250,
        input_tokens=420,
        output_tokens=37,
        round_=1,
    )
    finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    llm, turn = named(spans, LLM_SPAN), named(spans, TURN_SPAN)

    assert llm.parent.span_id == turn.context.span_id
    assert llm.attributes["gen_ai.provider.name"] == "openai"
    assert llm.attributes["gen_ai.request.model"] == "gpt-4o-mini"
    assert llm.attributes["server.address"] == "api.openai.com"
    assert llm.attributes["gen_ai.usage.input_tokens"] == 420
    assert llm.attributes["gen_ai.usage.output_tokens"] == 37
    # The entry's name under the SAME attribute the retained provider
    # context uses for it, rather than a second spelling of one fact:
    # the session and turn spans say what the session opened against and
    # this says what the round that answered actually ran on.
    assert llm.attributes["vinga.provider.llm.name"] == "openai-main"
    assert llm.attributes["vinga.llm.round"] == 1
    assert llm.attributes["vinga.agent"] == AGENT
    # And nothing else wearing a foreign prefix: a key a backend reads
    # by name is a key this repository has to have chosen deliberately.
    assert {
        key for key in llm.attributes if not key.startswith("vinga.")
    } == {
        "gen_ai.provider.name",
        "gen_ai.request.model",
        "server.address",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
    }
    assert llm.end_time - llm.start_time == 800 * MS
    assert llm.end_time == int((ended + telemetry._offset) * 1e9)


def test_the_first_token_is_a_mark_inside_the_round() -> None:
    """The number a stalled reply is diagnosed by, drawn where it
    happened: 250 ms into a round that took 800."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.8)
    round_done(events, duration_ms=800, first_token_ms=250)
    finish_reply(events)
    close_session(events)

    llm = named(finished(telemetry, memory), LLM_SPAN)
    assert [event.name for event in llm.events] == ["first_token"]
    assert llm.events[0].timestamp - llm.start_time == 250 * MS


def test_a_round_that_spoke_no_token_gets_no_mark() -> None:
    """A round that only asked for a tool timed no spoken token. An
    event at the round's own start would say the first token arrived
    instantly, which is the wrong answer rather than a missing one."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.4)
    round_done(events, duration_ms=400, first_token_ms=None)
    finish_reply(events)
    close_session(events)

    llm = named(finished(telemetry, memory), LLM_SPAN)
    assert llm.events == ()


def test_a_provider_with_no_identity_carries_no_gen_ai_keys() -> None:
    """The quartet is atomic in the catalog, and the span inherits that:
    a provider the registry never built names no entry, no type, no host
    and no model, and a span with a null model would be a claim the
    event refused to make."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.4)
    round_done(
        events,
        duration_ms=400,
        first_token_ms=None,
        input_tokens=None,
        output_tokens=None,
        unbuilt=True,
    )
    finish_reply(events)
    close_session(events)

    llm = named(finished(telemetry, memory), LLM_SPAN)
    assert {key for key in llm.attributes if not key.startswith("vinga.")} == set()
    assert "vinga.provider.llm.name" not in llm.attributes


def test_two_rounds_are_two_spans_in_the_same_turn() -> None:
    """A generation after a handover is a round of its own, and both
    hang inside the one turn they belong to."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.5)
    round_done(events, duration_ms=500, round_=1)
    clock.tick(0.6)
    round_done(events, duration_ms=600, round_=2)
    finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    rounds = spans_of(LLM_SPAN, spans)
    turn = named(spans, TURN_SPAN)
    assert [span.attributes["vinga.llm.round"] for span in rounds] == [1, 2]
    assert {span.parent.span_id for span in rounds} == {turn.context.span_id}


def test_a_retry_stays_a_span_event_on_the_turn() -> None:
    """`llm_retry` names a round that had not finished, so there is no
    round span to hang it on when it is said. It folds by default onto
    the turn, keeping its own name and its own fields."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(10.0)
    retry_round(events, round_=1, duration_ms=10000)
    clock.tick(0.6)
    round_done(events, duration_ms=600, round_=1)
    finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    turn = named(spans, TURN_SPAN)
    assert [event.name for event in turn.events] == ["llm_retry"]
    assert turn.events[0].attributes["round"] == 1
    # And the round that eventually answered carries only its own mark,
    # so the retry is not counted twice in two places.
    assert [event.name for event in named(spans, LLM_SPAN).events] == ["first_token"]


# --- TTS, and the name that had to be argued for ----------------------


def test_a_sentence_is_a_stream_span_and_not_a_synthesis_one() -> None:
    """The extent is the stream's whole lifetime, backpressure included,
    which is why neither the span nor any attribute is called synthesis.
    The provider's own latency, the number that IS backpressure-free, is
    the attribute."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.9)
    ended = synthesize(events, index=0, stream_ms=900, first_chunk_ms=120)
    finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    tts, turn = named(spans, TTS_SPAN), named(spans, TURN_SPAN)
    assert tts.name == "tts_stream"
    assert tts.parent.span_id == turn.context.span_id
    assert tts.attributes["vinga.tts.index"] == 0
    assert tts.attributes["vinga.tts.first_chunk_ms"] == 120
    assert tts.end_time - tts.start_time == 900 * MS
    assert tts.end_time == int((ended + telemetry._offset) * 1e9)
    # Nothing here claims to be synthesis latency, which is the catalog's
    # own rule carried onto the span.
    assert not any("synthesis" in key for key in tts.attributes)


def test_every_sentence_gets_its_own_span() -> None:
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    for index in range(3):
        clock.tick(0.4)
        synthesize(events, index=index, stream_ms=400)
    finish_reply(events, sentences=3)
    close_session(events)

    streams = spans_of(TTS_SPAN, finished(telemetry, memory))
    assert [span.attributes["vinga.tts.index"] for span in streams] == [0, 1, 2]


def test_a_stream_that_produced_no_audio_carries_no_first_chunk() -> None:
    """Absent where the stream produced nothing at all, which the
    catalog states and the span does not paper over with a zero."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.3)
    synthesize(events, stream_ms=300, first_chunk_ms=None)
    finish_reply(events)
    close_session(events)

    tts = named(finished(telemetry, memory), TTS_SPAN)
    assert "vinga.tts.first_chunk_ms" not in tts.attributes


# --- playback, the one interval with two ends -------------------------


def test_the_paced_interval_is_bounded_by_two_real_deliveries() -> None:
    """First frame out to last frame out, which is what the pacer paces:
    neither the reply's whole life nor its tail."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.7)
    began = start_speaking(events)
    clock.tick(2.5)
    ended = finish_speaking(events, frames=42)
    clock.tick(0.3)
    finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    playback, turn = named(spans, PLAYBACK_SPAN), named(spans, TURN_SPAN)
    assert playback.parent.span_id == turn.context.span_id
    assert playback.attributes["vinga.playback.frames"] == 42
    assert playback.start_time == int((began + telemetry._offset) * 1e9)
    assert playback.end_time == int((ended + telemetry._offset) * 1e9)
    # And it closes strictly before the reply does, which is the point
    # of bounding it at a delivery rather than at `reply_finished`.
    assert playback.end_time < turn.end_time


def test_a_reply_that_never_spoke_opens_no_playback_span() -> None:
    """A reply with no delivery emits neither event, so there is nothing
    to bound and no span claiming an interval of zero."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.3)
    hear_nothing(events)
    finish_reply(events, outcome=ReplyOutcome.NOTHING_HEARD, sentences=0)
    close_session(events)

    assert spans_of(PLAYBACK_SPAN, finished(telemetry, memory)) == []


def test_the_interval_closes_even_though_its_event_arrives_last() -> None:
    """The order a real reply emits in, which is not the order it
    reads in.

    `reply_finished` is the reply `finally`'s FIRST statement and
    `finish_speaking` is its last, so the event that closes the paced
    interval is said after the event that closes the turn, while being
    stamped at the last delivery, which is before both. The span is
    therefore held open past the turn's own end and closed by its own
    event, and what it bounds is still first frame out to last frame
    out: inside the turn, in the turn's trace, ending before the turn
    does.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.5)
    start_speaking(events)
    clock.tick(2.0)
    last_frame = clock()
    clock.tick(0.2)
    finish_reply(events, sentences=1)
    finish_speaking(events, frames=30, at=last_frame)

    close_session(events)

    spans = finished(telemetry, memory)
    playback, turn = named(spans, PLAYBACK_SPAN), named(spans, TURN_SPAN)
    assert playback.parent.span_id == turn.context.span_id
    assert playback.attributes["vinga.playback.frames"] == 30
    assert playback.end_time == int((last_frame + telemetry._offset) * 1e9)
    assert playback.end_time < turn.end_time
    assert [event.name for event in turn.events] == []


def test_an_interval_whose_last_frame_never_arrives_is_dropped() -> None:
    """The bound on holding it open. A cancellation delivered into the
    reply's very last statement is the one way `speaking_finished` never
    arrives, and an interval with no last frame is one this exporter
    declines to invent an end for: the next turn drops it, and so does
    the session's close."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.5)
    start_speaking(events)
    clock.tick(0.5)
    finish_reply(events, outcome=ReplyOutcome.DEVICE_GONE, sentences=1)
    clock.tick(1.0)
    start_turn(events)
    clock.tick(1.0)
    finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    assert spans_of(PLAYBACK_SPAN, spans) == []
    assert len(spans_of(TURN_SPAN, spans)) == 2


# --- the whole turn, in pipeline order --------------------------------


def test_one_turn_carries_its_four_stages_and_its_stragglers() -> None:
    """The milestone's headline, driven in the order a reply really
    emits: the utterance is transcribed, a round answers, sentences are
    synthesized while the frames go out, and everything with no shape of
    its own is a span event on the turn.

    Read as a whole because that is how a trace is read: what a field
    tester opens is one turn, and what has to be in it is every stage
    that took time.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)
    open_session(events)

    clock.tick(1.0)
    start_turn(events, speech_ms=900)
    clock.tick(0.3)
    hear(events, duration_s=0.9, asr_ms=300)
    clock.tick(0.8)
    round_done(events, duration_ms=800, round_=1)
    clock.tick(0.4)
    synthesize(events, index=0, stream_ms=400)
    start_speaking(events)
    clock.tick(0.5)
    hand_over(events)
    clock.tick(1.5)
    synthesize(events, index=1, stream_ms=1500)
    last_frame = clock()
    clock.tick(0.1)
    # The reply's `finally` in its real order: the turn is closed first
    # and the paced interval's own event is the last thing said.
    finish_reply(events, sentences=2)
    finish_speaking(events, frames=60, at=last_frame)
    close_session(events)

    spans = finished(telemetry, memory)
    turn = named(spans, TURN_SPAN)
    inside = [span for span in spans if span.parent is not None]

    assert sorted(span.name for span in inside) == [
        ASR_SPAN,
        LLM_SPAN,
        PLAYBACK_SPAN,
        TTS_SPAN,
        TTS_SPAN,
    ]
    assert {span.parent.span_id for span in inside} == {turn.context.span_id}
    assert {span.context.trace_id for span in inside} == {turn.context.trace_id}
    # The one event with no shape of its own is still a span event, and
    # it is on the turn it happened in.
    assert [event.name for event in turn.events] == ["handover"]
    assert named(spans, "session").events == ()


def test_a_stage_event_with_no_turn_open_lands_on_the_session() -> None:
    """The fallback that keeps every event with a destination. A stage
    event between turns has no turn to hang a span inside, so it folds
    as a span event rather than being dropped or opening a trace of its
    own."""
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)
    open_session(events)

    clock.tick(1.0)
    hear(events)
    clock.tick(0.5)
    finish_speaking(events, frames=3)
    close_session(events)

    spans = finished(telemetry, memory)
    session = named(spans, "session")
    assert spans_of(ASR_SPAN, spans) == []
    assert [event.name for event in session.events] == ["heard", "speaking_finished"]


# --- the one-shots, which keep their own names ------------------------


def test_each_barge_in_suppression_is_its_own_span_event_with_its_reason() -> None:
    """The acceptance criterion, met three to one.

    The catalog holds three suppression variants, each with the fixed
    reason its own decision site chose, and the fold names a span event
    after the variant that was emitted rather than flattening the three
    into one name with a reason argument. So the closed reason set stays
    exactly as the decision sites wrote it, and it arrives on the turn
    that was being spoken over.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    for which in ("floor", "refractory", "no_transcript"):
        clock.tick(0.2)
        suppress_barge_in(events, which)
    finish_reply(events)
    close_session(events)

    turn = named(finished(telemetry, memory), TURN_SPAN)
    assert [event.name for event in turn.events] == [
        "barge_in_suppressed",
        "barge_in_suppressed",
        "barge_in_suppressed",
    ]
    assert [event.attributes["reason"] for event in turn.events] == [
        "min_speech",
        "refractory",
        "no_transcript",
    ]
    assert turn.events[0].attributes["speech_ms"] == 120


def test_the_promoted_dropped_frame_aggregate_lands_where_it_happened() -> None:
    """M1 moved the per-second aggregate onto the ordinary seam so that
    telemetry could see it at all, and the fold needs no row for it: it
    is a span event with the second it counted and the reasons it
    counted, on whichever span is open when the second rolled over."""
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)
    open_session(events)

    clock.tick(1.0)
    drop_frames(events, {"not_listening": 5}, second=3)
    close_session(events)

    session = named(finished(telemetry, memory), "session")
    assert [event.name for event in session.events] == ["frames_dropped"]
    assert session.events[0].attributes["second"] == 3
    # And the mapping arrives as the deterministic JSON string the
    # declared shape turns a mapping into, rather than being dropped by
    # the SDK for having no attribute type.
    assert session.events[0].attributes["reasons"] == '{"not_listening":5}'


# --- the context every stage span carries -----------------------------


def test_every_stage_span_carries_the_session_context() -> None:
    """The claim OTel's own model makes necessary.

    A child span carries its parent's id and NOTHING of its parent's
    attributes, so a backend filtering traces by device or by session
    sees only the spans that spell those out themselves. A stage span
    with nothing but its stage's fields is a span nobody can find, which
    is why the session's identity and the resolved providers of the
    agent that ran the stage are on all four.

    All four in one case deliberately: what is being pinned is that
    there is ONE derivation rather than four remembered copies.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.3)
    hear(events)
    clock.tick(0.8)
    round_done(events, duration_ms=800)
    clock.tick(0.4)
    synthesize(events, stream_ms=400)
    start_speaking(events)
    clock.tick(0.5)
    finish_reply(events, sentences=1)
    finish_speaking(events, frames=12, at=clock())
    close_session(events)

    spans = finished(telemetry, memory)
    stages = [span for span in spans if span.parent is not None]
    assert sorted(span.name for span in stages) == [
        ASR_SPAN,
        LLM_SPAN,
        PLAYBACK_SPAN,
        TTS_SPAN,
    ]
    for span in stages:
        carried = span.attributes
        assert carried["vinga.session.id"] == SESSION, span.name
        assert carried["vinga.device.id"] == DEVICE, span.name
        assert carried["vinga.agent"] == AGENT, span.name
        assert carried["vinga.conversation.id"] == CONVERSATION, span.name
        # The resolved entries of the agent that ran the stage, per
        # stage and per fact, exactly as the session and turn spans
        # carry them.
        assert carried["vinga.provider.asr.type"] == "faster_whisper"
        assert carried["vinga.provider.tts.name"] == "voice"
        # And the build revision, which is not an attribute and is not
        # missing: it rides the resource every span carries.
        assert span.resource.attributes["service.version"]


def test_a_stage_after_a_handover_carries_the_new_agent_s_providers() -> None:
    """The context follows the agent that actually ran the stage.

    A handover mid-reply changes which providers the rest of the reply
    runs on, and every stage event says which agent it belongs to. So
    the sentence spoken after the handover carries the incoming agent's
    voice rather than the one the session opened with, which is the
    difference between attributable and merely stamped.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.3)
    hand_over(events, to=OTHER_AGENT)
    events.agent = OTHER_AGENT
    clock.tick(0.6)
    synthesize(events, stream_ms=600, agent=OTHER_AGENT)
    finish_reply(events)
    close_session(events)

    tts = named(finished(telemetry, memory), TTS_SPAN)
    assert tts.attributes["vinga.agent"] == OTHER_AGENT
    assert tts.attributes["vinga.provider.llm.name"] == "local"
    assert tts.attributes["vinga.provider.llm.host"] == "127.0.0.1"


def test_the_round_speaks_for_its_own_stage_and_the_context_for_the_rest() -> None:
    """One attribute name, one source.

    `llm_round` carries the entry that actually answered, which after a
    mid-session change is not the entry the session opened against, so
    the round span states the LLM stage itself and the retained context
    states every other stage. A span that took both would have had two
    writers for one name and the later one would win in silence.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.8)
    round_done(events, duration_ms=800)
    finish_reply(events)
    close_session(events)

    llm = named(finished(telemetry, memory), LLM_SPAN)
    # The round's own entry, not the session's opening one.
    assert llm.attributes["vinga.provider.llm.name"] == "openai-main"
    assert llm.attributes["gen_ai.request.model"] == "gpt-4o-mini"
    # And the context still speaks for the stages the round says
    # nothing about.
    assert llm.attributes["vinga.provider.asr.name"] == "ears"
