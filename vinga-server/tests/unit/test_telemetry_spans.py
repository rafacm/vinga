"""The stage spans, and the arithmetic that puts them where they were.

A turn trace is worth opening because of what is INSIDE it, and what is
inside it is four stages nobody watched while they ran: an ASR call, a
generation per round, a synthesis stream per sentence, and the paced
interval the frames actually went out over. A tool call the model asked
for is the fifth, built the same way. Every one of them is
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
what is proved is that the fourteen names with a shape of their own do not
also fold, and that the events beside them still do.
"""

import asyncio
import time
from collections.abc import Iterator
from typing import Any, cast

import pytest

from tests.support.configs import POET_MAC, base_config, config_with_agent
from tests.support.events import both_formats
from tests.support.events import events as logged_events
from tests.support.providers import BrokenStreamingTts, ScriptedEndpointer, ScriptedLlm
from tests.support.sessions import (
    drive_reply,
    end_utterance,
    events_of,
    plant_utterance,
    realtime_session,
    session_for,
    start_reply,
    turn_taking,
    wait_for_reply,
    with_device,
)
from tests.support.sockets import RecordingSocket
from tests.support.telemetry import (
    AGENT,
    CONVERSATION,
    DEVICE,
    OTHER_AGENT,
    PROVIDERS,
    SESSION,
    Clock,
    Identity,
    abandon_transcription,
    call_tool,
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
from tests.support.wire import speech_pcm
from vinga_server.events.values import ReplyOutcome
from vinga_server.providers import AsrResult
from vinga_server.telemetry import (
    _QUIETING,
    ASR_SPAN,
    LLM_SPAN,
    PLAYBACK_SPAN,
    SESSION_ID_ALIAS,
    TOOL_SPAN,
    TTS_SPAN,
    TURN_SPAN,
)
from vinga_server.telemetry import (
    OBSERVATION_USAGE_DETAILS as USAGE_DETAILS,
)

# One nanosecond per millisecond of the durations below, so a case can
# say what it expects in the units the events carry.
MS = 1_000_000

# The foreign-prefixed names every span carries whatever its stage did,
# which is the session id's grouping spelling (#67 M1) and nothing else.
# The closed-set assertions below subtract it by name rather than
# loosening to a prefix match: what they exist to catch is a key a
# backend reads by name arriving without anybody having chosen it.
GROUPING = {SESSION_ID_ALIAS}

# What a stage reports having been GIVEN, under the conventions'
# namespace with vinga's own unit in the name. Subtracted by name in the
# closed-set assertions below for the same reason the grouping alias is:
# a usage key is a fact somebody chose to export, and the point of those
# assertions is that nothing arrives under a foreign name by accident.
ASR_USED = {"gen_ai.usage.input_milliseconds", USAGE_DETAILS}
TTS_USED = {"gen_ai.usage.input_characters", USAGE_DETAILS}


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


# Which stage each span answers for ITSELF, which is the one stage whose
# open-time entries it does not carry: the event it was built from named
# the entry that actually ran, and one attribute name may have one
# source. The paced interval answers for none, no provider having
# produced it.
ANSWERS_FOR = {
    ASR_SPAN: "asr",
    LLM_SPAN: "llm",
    TTS_SPAN: "tts",
    PLAYBACK_SPAN: None,
}

# An ear and a voice that are NOT what the session opened against, in
# all four of their names. What they are for is the one span shape this
# module has to refuse: a call-time model beside an open-time type, a
# provider that never existed anywhere.
STANDBY_EAR = Identity(
    name="ears-standby",
    type="openai_asr",
    host="api.openai.com",
    model="whisper-1",
)
STANDBY_VOICE = Identity(
    name="voice-standby",
    type="elevenlabs",
    host="api.elevenlabs.io",
    model="eleven_turbo_v2",
)


def opened_against(carried: dict, stage: str) -> list[str]:
    """Every attribute on a span under one stage's provider prefix.

    Which is where what the session opened against lands, so a span that
    answers for that stage itself has exactly one of them, the entry
    name its own event said. Anything more is the open-time context
    still standing beside call-time data.
    """
    return [key for key in carried if key.startswith(f"vinga.provider.{stage}.")]


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
    assert asr.attributes["error.type"] == "TimeoutError"
    assert asr.status.status_code.name == "ERROR"
    # No description: the only prose a failure has is the far side's
    # message, and the class name is the whole of what may travel.
    assert asr.status.description is None
    assert asr.end_time - asr.start_time == 1500 * MS


def test_a_transcription_names_the_ear_that_ran_it() -> None:
    """The quartet on the ASR span, key by key.

    The same correspondence the round span carries, because an ear is a
    `gen_ai` provider like a generator is: the type is the provider
    name, the model is the request model, and only the configured
    entry's name stays vinga's own word. That is what makes "ASR latency
    by provider" one question with one answer at all three stages.

    The default ear runs in this process and reaches no host, which the
    catalog answers with an absence rather than with a placeholder, so
    the span carries no `server.address` at all.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.3)
    hear(events, duration_s=0.9, asr_ms=300)
    finish_reply(events)
    close_session(events)

    carried = named(finished(telemetry, memory), ASR_SPAN).attributes
    assert carried["vinga.provider.asr.name"] == "ears"
    assert carried["gen_ai.provider.name"] == "faster_whisper"
    assert carried["gen_ai.request.model"] == "small"
    assert "server.address" not in carried
    # And nothing else wearing a foreign prefix, for the same reason the
    # round span is pinned that way: a key a backend reads by name is a
    # key this repository has to have chosen deliberately.
    assert {key for key in carried if not key.startswith("vinga.")} == {
        "gen_ai.provider.name",
        "gen_ai.request.model",
        *GROUPING,
        *ASR_USED,
    }


def test_a_failed_transcription_names_the_ear_that_failed() -> None:
    """The outcome that is a failure carries the quartet too, off the
    same fields every other provider failure carries.

    It shares the ASR span, so it is the one ASR outcome whose quartet
    this milestone did not have to add: a provider failure has named the
    entry it was reaching for since it was declared, and the ASR span
    had nowhere to put it until this table gained the four keys.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(1.5)
    provider_failed(events, stage="asr", duration_ms=1500, identity=STANDBY_EAR)
    finish_reply(events, outcome=ReplyOutcome.FAILED, sentences=0)
    close_session(events)

    carried = named(finished(telemetry, memory), ASR_SPAN).attributes
    assert carried["vinga.provider.asr.name"] == "ears-standby"
    assert carried["gen_ai.provider.name"] == "openai_asr"
    assert carried["gen_ai.request.model"] == "whisper-1"
    assert carried["server.address"] == "api.openai.com"
    # The ear that failed, whole: nothing of the one the session opened
    # against is left standing beside it.
    assert opened_against(carried, "asr") == ["vinga.provider.asr.name"]


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


def test_a_tts_failure_is_one_real_failed_span() -> None:
    """A failed synthesis is the operation itself, never a turn event."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.5)
    provider_failed(events, stage="tts", duration_ms=700)
    finish_reply(events, outcome=ReplyOutcome.FAILED, sentences=0)
    close_session(events)

    spans = finished(telemetry, memory)
    assert spans_of(ASR_SPAN, spans) == []
    tts = named(spans, TTS_SPAN)
    assert tts.status.status_code.name == "ERROR"
    assert tts.status.description is None
    assert tts.attributes["error.type"] == "TimeoutError"
    assert named(spans, TURN_SPAN).events == ()


def test_an_unbuilt_failed_voice_keeps_the_retained_provider_context() -> None:
    """An absent failure quartet cannot erase what the session opened against."""
    telemetry, memory = exporting()
    events = a_turn(Clock(), telemetry)

    provider_failed(events, stage="tts", unbuilt=True)
    finish_reply(events, outcome=ReplyOutcome.FAILED, sentences=0)
    close_session(events)

    carried = named(finished(telemetry, memory), TTS_SPAN).attributes
    assert carried["vinga.provider.tts.name"] == "voice"
    assert carried["vinga.provider.tts.type"] == "piper"
    assert carried["vinga.provider.tts.model"] == "en_GB-alba-medium"


async def test_a_real_tts_failure_keeps_its_event_without_a_span_twin(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The log keeps the stream measurements while telemetry substitutes."""
    telemetry, memory = exporting()
    session = session_for(
        base_config(),
        POET_MAC,
        {"poet": ScriptedLlm(["The answer."])},
        stages={"tts": cast(Any, BrokenStreamingTts())},
    )
    with_device(session, POET_MAC)
    session.websocket = cast(Any, RecordingSocket())
    events = events_of(session)
    events.attach(telemetry.session_tap())
    open_session(events, providers={}, conversations=session.session_conversations)
    start_turn(events)

    with caplog.at_level("DEBUG"):
        await drive_reply(session, speech_pcm(600))
    close_session(events)

    spans = finished(telemetry, memory)
    (tts,) = spans_of(TTS_SPAN, spans)
    assert tts.status.status_code.name == "ERROR"
    assert tts.attributes["error.type"] == "RuntimeError"
    assert named(spans, TURN_SPAN).events == ()
    assert len(logged_events(caplog, "provider_failed")) == 1
    synthesized = logged_events(caplog, "sentence_synthesized")
    assert len(synthesized) == 1
    assert synthesized[0].stream_ms >= 0


def test_every_semantic_failure_is_one_safe_failed_span(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """All four operation kinds carry only their safe failure category."""

    class CredentialFailure(RuntimeError):
        pass

    sentinel = "sk-live-0SEMANTIC-FAILURE-SENTINEL"
    cause = ValueError(sentinel)
    failure = CredentialFailure(sentinel)
    failure.__cause__ = cause
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    with caplog.at_level("DEBUG"):
        provider_failed(events, stage="asr", failure=failure)
        provider_failed(events, stage="llm", failure=failure)
        provider_failed(events, stage="tts", failure=failure)
        call_tool(events, is_error=True, error_type="CredentialFailure")
        finish_reply(events, outcome=ReplyOutcome.FAILED, sentences=0)
        close_session(events)

    spans = finished(telemetry, memory)
    operations = [
        *spans_of(ASR_SPAN, spans),
        *spans_of(LLM_SPAN, spans),
        *spans_of(TTS_SPAN, spans),
        *spans_of(TOOL_SPAN, spans),
    ]
    assert len(operations) == 4
    assert {one.attributes["error.type"] for one in operations} == {
        "CredentialFailure"
    }
    assert all(one.status.status_code.name == "ERROR" for one in operations)
    assert all(one.status.description is None for one in operations)
    turn = named(spans, TURN_SPAN)
    assert not {event.name for event in turn.events} & {"provider_failed", "tool_call"}
    assert sentinel not in both_formats(caplog)
    assert all(sentinel not in repr(record.__dict__) for record in caplog.records)
    assert all(record.exc_info is None for record in caplog.records)


def test_an_unknown_failed_stage_keeps_the_default_span_event() -> None:
    """A catalog-valid future stage cannot disappear in an older exporter."""
    telemetry, memory = exporting()
    events = a_turn(Clock(), telemetry)

    provider_failed(events, stage="embedding")
    finish_reply(events, outcome=ReplyOutcome.FAILED, sentences=0)
    close_session(events)

    turn = named(finished(telemetry, memory), TURN_SPAN)
    assert [event.name for event in turn.events] == ["provider_failed"]


def test_a_returned_tool_error_uses_the_closed_category() -> None:
    telemetry, memory = exporting()
    events = a_turn(Clock(), telemetry)

    call_tool(events, is_error=True)
    finish_reply(events)
    close_session(events)

    tool = named(finished(telemetry, memory), TOOL_SPAN)
    assert tool.attributes["error.type"] == "tool_error"
    assert tool.status.status_code.name == "ERROR"


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
        cache_read_input_tokens=256,
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
    assert llm.attributes["gen_ai.usage.cache_read.input_tokens"] == 256
    # The entry's name under the SAME attribute the retained provider
    # context uses for it, rather than a second spelling of one fact:
    # the session and turn spans say what the session opened against and
    # this says what the round that answered actually ran on.
    assert llm.attributes["vinga.provider.llm.name"] == "openai-main"
    assert llm.attributes["vinga.llm.round"] == 1
    assert llm.attributes["vinga.llm.invocation.id"] == (
        "11111111111111111111111111111111"
    )
    assert llm.attributes["vinga.llm.purpose"] == "reply"
    assert llm.attributes["vinga.agent"] == AGENT
    # And nothing else wearing a foreign prefix: a key a backend reads
    # by name is a key this repository has to have chosen deliberately.
    assert {
        key for key in llm.attributes if not key.startswith("vinga.")
    } == {
        "gen_ai.operation.name",
        "gen_ai.provider.name",
        "gen_ai.request.model",
        "server.address",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.cache_read.input_tokens",
        "gen_ai.usage.output_tokens",
        *GROUPING,
    }
    assert llm.end_time - llm.start_time == 800 * MS
    assert llm.end_time == int((ended + telemetry._offset) * 1e9)


def test_a_failed_generation_is_one_real_span_with_its_join_key() -> None:
    telemetry, memory = exporting()
    events = a_turn(Clock(), telemetry)
    invocation = "fedcba9876543210fedcba9876543210"

    provider_failed(
        events,
        stage="llm",
        failure=ConnectionRefusedError("credential shaped words"),
        invocation=invocation,
    )
    finish_reply(events, outcome=ReplyOutcome.FAILED, sentences=0)
    close_session(events)

    spans = finished(telemetry, memory)
    llm = named(spans, LLM_SPAN)
    assert llm.attributes["vinga.llm.invocation.id"] == invocation
    assert llm.attributes["vinga.llm.purpose"] == "reply"
    assert llm.attributes["error.type"] == "ConnectionRefusedError"
    assert llm.status.status_code.name == "ERROR"
    assert llm.status.description is None
    assert named(spans, TURN_SPAN).events == ()


def test_a_successful_recap_is_a_generation_without_a_reply_ordinal() -> None:
    telemetry, memory = exporting()
    events = a_turn(Clock(), telemetry)
    invocation = "abcdefabcdefabcdefabcdefabcdefab"

    round_done(
        events,
        round_=None,
        invocation=invocation,
        purpose="recap",
        turns=7,
    )
    finish_reply(events)
    close_session(events)

    llm = named(finished(telemetry, memory), LLM_SPAN)
    assert llm.attributes["vinga.llm.invocation.id"] == invocation
    assert llm.attributes["vinga.llm.purpose"] == "recap"
    assert llm.attributes["vinga.llm.turns"] == 7
    assert "vinga.llm.round" not in llm.attributes
    assert llm.status.status_code.name != "ERROR"
    # A recap is the same OPERATION as a reply and differs only in its
    # purpose, which is the whole of why the operation name is a
    # constant rather than a field read. Asserted here and not only on
    # the reply case, because a regression that keyed the attribute on
    # purpose would leave every changed test in this file passing.
    assert llm.attributes["gen_ai.operation.name"] == "chat"


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


def test_a_provider_with_no_identity_carries_only_the_operation_key() -> None:
    """The quartet is atomic in the catalog, and the span inherits that:
    a provider the registry never built names no entry, no type, no host
    and no model, and a span with a null model would be a claim the
    event refused to make.

    What the span does still say is which operation it is, because that
    is a fact about this span rather than about the provider behind it.
    It is the only `gen_ai` key here for the same reason: a round with
    no identity is exactly the round a reader cannot otherwise type."""
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
    assert {
        key for key in llm.attributes if not key.startswith("vinga.")
    } == {"gen_ai.operation.name", *GROUPING}
    assert "vinga.provider.llm.name" not in llm.attributes
    assert "gen_ai.request.model" not in llm.attributes


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


# --- the tool call, which stopped being a span event ------------------
#
# The backend this surface exists for ingests no span events at all,
# which is what made an MCP call invisible on a trace that recorded
# everything around it. So a `tool_call` builds a span of its own,
# retrospectively out of `duration_ms` the way every stage span is
# built, and the span event goes away rather than staying beside it:
# two carriers of one fact on one trace is the locality rule broken,
# and a backend that DOES ingest span events would show every call
# twice.


def test_a_tool_call_is_a_span_inside_the_turn_and_no_span_event() -> None:
    """Both halves in one case, because the second is what makes the
    first a replacement rather than an addition."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.25)
    ended = call_tool(events, "builtin", name="remember", duration_s=0.25)
    finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    tool, turn = named(spans, TOOL_SPAN), named(spans, TURN_SPAN)
    assert tool.parent.span_id == turn.context.span_id
    assert tool.end_time - tool.start_time == 250 * MS
    assert tool.end_time == int((ended + telemetry._offset) * 1e9)
    assert [event.name for event in turn.events] == []


def test_a_tool_call_says_it_is_a_tool_call_in_the_conventions_words() -> None:
    """`execute_tool` is the GenAI conventions' own name for exactly
    this, so the span spells the fact in their vocabulary first and the
    live gate records what a backend does with it."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.25)
    call_tool(events, "builtin", name="remember")
    finish_reply(events)
    close_session(events)

    tool = named(finished(telemetry, memory), TOOL_SPAN)
    assert tool.attributes["gen_ai.operation.name"] == "execute_tool"
    # And nothing else wearing a foreign prefix: a key a backend reads
    # by name is a key this repository has to have chosen deliberately.
    assert {
        key for key in tool.attributes if not key.startswith("vinga.")
    } == {"gen_ai.operation.name", "gen_ai.tool.name", *GROUPING}


def test_a_round_says_it_is_a_chat_in_the_conventions_words() -> None:
    """The key the tool span already carried, on the span beside it.

    The conventions make `gen_ai.operation.name` required on a
    generation, and a round is one. It is also what a backend types the
    observation from when the provider reported no model, which a live
    Langfuse gate measured: untyped, the round's usage is never priced.

    `chat` is the conventions' value for a streamed chat completion. A
    recap is one too, and that clause is pinned where a recap is
    actually driven, in
    `test_a_successful_recap_is_a_generation_without_a_reply_ordinal`,
    rather than claimed here over an ordinary reply round.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.4)
    round_done(events, duration_ms=400)
    finish_reply(events)
    close_session(events)

    llm = named(finished(telemetry, memory), LLM_SPAN)
    assert llm.attributes["gen_ai.operation.name"] == "chat"


def test_a_failed_round_still_says_which_operation_failed() -> None:
    """A failure is not a reason to stop naming the operation: this is
    the round least likely to carry a model name, so it is the one a
    reader most needs the operation from."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.4)
    provider_failed(events, stage="llm", duration_ms=400, unbuilt=True)
    finish_reply(events, outcome=ReplyOutcome.FAILED, sentences=0)
    close_session(events)

    llm = named(finished(telemetry, memory), LLM_SPAN)
    assert llm.attributes["gen_ai.operation.name"] == "chat"
    assert llm.status.status_code.name == "ERROR"
    assert "gen_ai.request.model" not in llm.attributes


def test_a_builtin_names_its_tool_and_an_mcp_call_names_its_entry() -> None:
    """The naming policy the three variants make structural, carried
    onto the span by one table: a builtin's name is this server's own
    word and is the tool's name the conventions have a key for, and the
    entry is the operator's configured word for a far side whose own
    tool name never reaches this surface.

    One fold for all three, because `tool_call` is one declared event
    name and the fold skips a table key the payload does not carry.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.25)
    call_tool(events, "builtin", name="remember")
    clock.tick(0.25)
    call_tool(events, "mcp", name="search", is_error=True)
    finish_reply(events)
    close_session(events)

    builtin, mcp = spans_of(TOOL_SPAN, finished(telemetry, memory))
    assert builtin.attributes["gen_ai.tool.name"] == "remember"
    assert builtin.attributes["vinga.tool.source"] == "builtin"
    assert builtin.attributes["vinga.tool.is_error"] is False
    assert "vinga.tool.entry" not in builtin.attributes
    assert mcp.attributes["vinga.tool.entry"] == "search"
    assert mcp.attributes["vinga.tool.source"] == "mcp"
    assert mcp.attributes["vinga.tool.is_error"] is True
    assert "gen_ai.tool.name" not in mcp.attributes


def test_a_call_this_surface_may_not_name_carries_neither_name() -> None:
    """A device tool's name is the board's vocabulary and an unknown
    one is whatever the model invented, so the variant that may name
    neither carries neither, and the namespace it reached into is the
    whole of what it says."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.25)
    call_tool(events, "unnamed")
    finish_reply(events)
    close_session(events)

    tool = named(finished(telemetry, memory), TOOL_SPAN)
    assert tool.attributes["vinga.tool.source"] == "device"
    assert "gen_ai.tool.name" not in tool.attributes
    assert "vinga.tool.entry" not in tool.attributes


def test_a_tool_call_carries_the_session_context_every_span_carries() -> None:
    """The retained identity, so a call is findable by the session and
    the board it happened on, and the agent and thread it was asked
    for by.

    And NOT the provider entries: a tool call ran on no pipeline stage,
    so what the session opened against says nothing about it.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.25)
    call_tool(events, "builtin", name="remember")
    finish_reply(events)
    close_session(events)

    tool = named(finished(telemetry, memory), TOOL_SPAN)
    assert tool.attributes["vinga.session.id"] == SESSION
    assert tool.attributes["vinga.device.id"] == DEVICE
    assert tool.attributes["vinga.agent"] == AGENT
    assert tool.attributes["vinga.conversation.id"] == CONVERSATION
    assert [key for key in tool.attributes if key.startswith("vinga.provider.")] == []


def test_a_tool_call_with_no_turn_open_is_a_span_on_the_session() -> None:
    """A call that arrives with no turn to hang inside lands on the
    session, and lands there as a SPAN.

    The parent moves and the carrier does not, which is the whole of
    what a missing turn changes. Answering this case with a span event
    would be the milestone's own finding thrown away in the one place it
    is hardest to see: the backend ingests no span events, so a call
    recorded as one is a call that did not happen as far as any reader
    of that backend can tell."""
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)
    open_session(events)

    clock.tick(0.25)
    call_tool(events, "builtin", name="remember")
    close_session(events)

    spans = finished(telemetry, memory)
    (tool,) = spans_of(TOOL_SPAN, spans)
    session = named(spans, "session")
    assert tool.parent is session.context
    assert [event.name for event in session.events] == []


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


def test_a_stream_names_the_voice_that_produced_it() -> None:
    """The quartet on the TTS span, key by key, off the same
    correspondence.

    What makes a voice comparable across a fleet is its latency beside
    its identity: a span carrying only the first is exactly the "TTS
    latency by provider" question this issue was filed about, left
    unanswerable.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.9)
    synthesize(events, index=0, stream_ms=900, first_chunk_ms=120)
    finish_reply(events)
    close_session(events)

    carried = named(finished(telemetry, memory), TTS_SPAN).attributes
    assert carried["vinga.provider.tts.name"] == "voice"
    assert carried["gen_ai.provider.name"] == "piper"
    assert carried["gen_ai.request.model"] == "en_GB-alba-medium"
    assert "server.address" not in carried
    assert {key for key in carried if not key.startswith("vinga.")} == {
        "gen_ai.provider.name",
        "gen_ai.request.model",
        *GROUPING,
        *TTS_USED,
    }


# --- what each stage was given, in the unit it is billed in -----------


def test_a_transcription_reports_the_audio_the_ear_was_actually_sent() -> None:
    """`gen_ai.usage.input_milliseconds`, beside the two token counts a
    round already reports and read the same way.

    The direction is the model's, exactly as the conventions read the
    token halves: an ear is GIVEN the audio and produces a transcript,
    so the milliseconds are input. It is not cosmetic. A backend prices
    the keys `input`, `output` and `total`, so a number under any other
    name has no rate beside it and an ASR stage stays unpriceable
    however carefully it is measured.

    The unit is in the name because the conventions have no word for it,
    and it is milliseconds rather than seconds because the live gate
    found a non-integer usage value dropped outright.

    And the SOURCE is what the ear says it submitted, not how long the
    user spoke. The two cases below are the ones that come apart.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.3)
    hear(events, duration_s=0.9, asr_ms=300, submitted_ms=900)
    finish_reply(events)
    close_session(events)

    asr = named(finished(telemetry, memory), ASR_SPAN).attributes
    assert asr["gen_ai.usage.input_milliseconds"] == 900
    # An integer, because the gate found a float dropped by the backend
    # on both of the paths it could arrive on.
    assert isinstance(asr["gen_ai.usage.input_milliseconds"], int)
    # Two facts, two attributes: how long the user spoke stays under the
    # stage's own vinga name and is not what anyone is billed for.
    assert asr["vinga.asr.duration_s"] == pytest.approx(0.9)
    assert "gen_ai.usage.output_milliseconds" not in asr


def test_an_ear_that_was_sent_nothing_reports_a_usage_of_zero() -> None:
    """A clip under an endpoint's own floor never leaves the process, so
    the stage cost nothing and the span says nothing was sent.

    The number the span must NOT carry is the utterance's length, which
    is what this attribute used to be aliased to: it would invent a
    charge for a request no adapter made. Zero rather than an absence,
    because the adapter KNOWS it sent nothing, and the absence rule
    below is for a measurement nobody could take.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.05)
    hear_nothing(events, duration_s=0.05, asr_ms=1, submitted_ms=0)
    finish_reply(events, outcome=ReplyOutcome.NOTHING_HEARD, sentences=0)
    close_session(events)

    asr = named(finished(telemetry, memory), ASR_SPAN).attributes
    assert asr["gen_ai.usage.input_milliseconds"] == 0
    assert asr["vinga.asr.duration_s"] == pytest.approx(0.05)


def test_an_ear_that_heard_the_clip_twice_reports_both_hearings() -> None:
    """An echo retry sends the same bytes a second time, so the usage is
    twice the clip and the utterance is unchanged.

    Half the real cost is what the aliased attribute reported here, on
    exactly the short acknowledgements the echo guard fires on most.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.8)
    hear(events, duration_s=0.9, asr_ms=800, submitted_ms=1800)
    finish_reply(events)
    close_session(events)

    asr = named(finished(telemetry, memory), ASR_SPAN).attributes
    assert asr["gen_ai.usage.input_milliseconds"] == 1800
    assert asr["vinga.asr.duration_s"] == pytest.approx(0.9)


def test_an_ear_that_cannot_say_what_it_sent_reports_no_usage() -> None:
    """A local engine bills nothing and counts nothing, so it leaves the
    field out and the span carries no usage attribute at all.

    Which is a different answer from the zero above: one says the ear
    was sent nothing, the other says nobody measured. A backend reading
    the first prices it at zero, and reading the second knows not to.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.3)
    hear(events, duration_s=0.9, asr_ms=300, submitted_ms=None)
    finish_reply(events)
    close_session(events)

    asr = named(finished(telemetry, memory), ASR_SPAN).attributes
    assert "gen_ai.usage.input_milliseconds" not in asr
    # Beside the thing the case is about, so a span that never got built
    # cannot pass this.
    assert asr["vinga.asr.duration_s"] == pytest.approx(0.9)


def test_a_stream_reports_the_sentence_it_was_given_as_input_usage() -> None:
    """`gen_ai.usage.input_characters` on the synthesis span, in the
    same direction and for the same reason.

    A voice is GIVEN the sentence and produces the audio, so the
    characters are input, and the plan's first draft called them output
    in the same sentence that said the voice was given them.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.9)
    synthesize(events, index=0, characters=42, stream_ms=900, first_chunk_ms=120)
    finish_reply(events)
    close_session(events)

    tts = named(finished(telemetry, memory), TTS_SPAN).attributes
    assert tts["gen_ai.usage.input_characters"] == 42
    assert "gen_ai.usage.output_characters" not in tts
    # A size and never a byte of the sentence, which is what the count
    # is for: nothing on this span holds prose.
    assert not any(isinstance(held, str) and " " in held for held in tts.values())


def test_each_priced_stage_spells_its_usage_for_the_backend_too() -> None:
    """The fallback the plan named and the live gate proved necessary.

    The conventions' own key arrives at the backend and is never priced:
    a model definition prices `input`, `output` and `total`, so a
    `gen_ai.usage.input_characters` is lifted into the observation's
    usage under that suffix and costs nothing. So both stages carry a
    second spelling for that one reader, canonical JSON under the key a
    definition can price, which is the same shape as the session id's
    grouping alias rather than a second fact.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.3)
    hear(events, duration_s=0.9, asr_ms=300, submitted_ms=900)
    clock.tick(0.9)
    synthesize(events, index=0, characters=29, stream_ms=900)
    finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    asr = named(spans, ASR_SPAN).attributes
    tts = named(spans, TTS_SPAN).attributes

    assert asr[USAGE_DETAILS] == '{"input":900}'
    assert tts[USAGE_DETAILS] == '{"input":29}'
    # Beside the conventions' name and never instead of it: the vinga
    # spelling is the one a backend that has never heard of this project
    # reads, and it stays.
    assert asr["gen_ai.usage.input_milliseconds"] == 900
    assert tts["gen_ai.usage.input_characters"] == 29


def test_a_round_is_not_given_a_second_usage_spelling() -> None:
    """Only the two stages the conventions have no vocabulary for.

    A generation reports tokens under the conventions' own names, which
    this backend already parses and already prices, so a second spelling
    there would be one fact under two keys for no reader at all.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.8)
    round_done(events, input_tokens=420, output_tokens=37, cache_read_input_tokens=256)
    finish_reply(events)
    close_session(events)

    llm = named(finished(telemetry, memory), LLM_SPAN).attributes
    assert llm["gen_ai.usage.input_tokens"] == 420
    # The cached count included (#536): the backend maps the
    # conventions' key itself, subtracts it from the input and prices
    # it at the cached rate, while a `usage_details` string would
    # REPLACE that mapping rather than add to it, which is a second
    # structure that must agree with the first and a wrong price when
    # it does not.
    assert llm["gen_ai.usage.cache_read.input_tokens"] == 256
    assert USAGE_DETAILS not in llm


def test_a_round_carries_its_cached_input_beside_the_input_it_is_part_of() -> None:
    """`gen_ai.usage.cache_read.input_tokens`, the conventions' own name,
    carried as the subset of `gen_ai.usage.input_tokens` it is and never
    subtracted from it here: the backend does that subtraction, and the
    Step 0 gate for #536 showed it pricing the result at the cached rate.
    A round whose endpoint did not say carries no key, rather than a `0`
    that would claim nothing was cached."""
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.8)
    round_done(events, input_tokens=2000, output_tokens=10, cache_read_input_tokens=1536)
    clock.tick(0.8)
    round_done(events, input_tokens=2000, output_tokens=10, round_=2)
    finish_reply(events)
    close_session(events)

    cached, unsaid = sorted(
        (span for span in finished(telemetry, memory) if span.name == LLM_SPAN),
        key=lambda span: span.attributes["vinga.llm.round"],
    )
    assert cached.attributes["gen_ai.usage.input_tokens"] == 2000
    assert cached.attributes["gen_ai.usage.cache_read.input_tokens"] == 1536
    assert unsaid.attributes["gen_ai.usage.input_tokens"] == 2000
    assert "gen_ai.usage.cache_read.input_tokens" not in unsaid.attributes


def test_a_stage_with_no_usage_gets_no_priced_spelling_either() -> None:
    """The absence rule reaches both spellings.

    An ear that cannot say what it submitted leaves the conventions'
    attribute off, and a JSON blob saying the same nothing would be the
    one place this module invented a claim the event did not make.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.3)
    hear(events, duration_s=0.9, asr_ms=300, submitted_ms=None)
    finish_reply(events)
    close_session(events)

    asr = named(finished(telemetry, memory), ASR_SPAN).attributes
    assert "gen_ai.usage.input_milliseconds" not in asr
    assert USAGE_DETAILS not in asr
    assert asr["vinga.asr.duration_s"] == pytest.approx(0.9)


def test_a_stage_that_measured_nothing_reports_no_usage_rather_than_zero() -> None:
    """A failed transcription carries no `duration_s` in its payload at
    all, that field being rendered into the sentence and never carried,
    so the span says nothing about how much audio was given rather than
    saying none was.

    Zero is a claim the event did not make, and on a priced stage it is
    also a claim about money: a cost of zero seconds read as a fact is
    an ASR call that looks free, where an absent measurement looks like
    what it is.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(1.5)
    provider_failed(events, stage="asr", duration_ms=1500)
    finish_reply(events, outcome=ReplyOutcome.FAILED, sentences=0)
    close_session(events)

    asr = named(finished(telemetry, memory), ASR_SPAN).attributes
    assert "gen_ai.usage.input_milliseconds" not in asr
    assert "vinga.asr.duration_s" not in asr
    # The span itself is real, so this is an absence beside the thing
    # the case is about rather than a case that asserted nothing.
    assert asr["vinga.asr.outcome"] == "provider_failed"


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


def test_semantic_operations_with_no_turn_are_spans_on_the_session() -> None:
    """All four folds keep their span shape and use the same fallback parent."""
    clock = Clock()
    telemetry, memory = exporting()
    events = session_events(clock, telemetry)
    open_session(events)

    clock.tick(1.0)
    hear(events)
    round_done(events)
    synthesize(events)
    call_tool(events)
    clock.tick(0.5)
    finish_speaking(events, frames=3)
    close_session(events)

    spans = finished(telemetry, memory)
    session = named(spans, "session")
    operations = [
        named(spans, ASR_SPAN),
        named(spans, LLM_SPAN),
        named(spans, TTS_SPAN),
        named(spans, TOOL_SPAN),
    ]
    assert all(span.parent is session.context for span in operations)
    assert [event.name for event in session.events] == ["speaking_finished"]


# --- the one-shots, which keep their own names ------------------------


def test_each_barge_in_suppression_is_its_own_span_event_with_its_reason() -> None:
    """The acceptance criterion, met one span-event name per variant.

    The catalog holds one suppression variant per reason, each with the
    fixed reason its own decision site chose, and the fold names a span
    event after the variant that was emitted rather than flattening them
    into one name with a reason argument. So the closed reason set stays
    exactly as the decision sites wrote it, and it arrives on the turn
    that was being spoken over.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    for which in ("floor", "no_transcript"):
        clock.tick(0.2)
        suppress_barge_in(events, which)
    finish_reply(events)
    close_session(events)

    turn = named(finished(telemetry, memory), TURN_SPAN)
    assert [event.name for event in turn.events] == [
        "barge_in_suppressed",
        "barge_in_suppressed",
    ]
    assert [event.attributes["reason"] for event in turn.events] == [
        "min_speech",
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
        # carry them, for every stage this span does not answer for
        # itself. The one it does is its own event's word and is pinned
        # by the cases below.
        for stage, entry in PROVIDERS[AGENT].items():
            if stage == ANSWERS_FOR[span.name]:
                assert opened_against(carried, stage) == [
                    f"vinga.provider.{stage}.name"
                ], span.name
                continue
            for fact, held in entry.items():
                assert carried[f"vinga.provider.{stage}.{fact}"] == held, (
                    span.name,
                    stage,
                    fact,
                )
        # And the build revision, which is not an attribute and is not
        # missing: it rides the resource every span carries.
        assert span.resource.attributes["service.version"]


def test_every_span_spells_the_session_id_under_both_names() -> None:
    """The grouping alias, on every span shape this exporter makes.

    A backend that groups traces into sessions has to be told which
    attribute the session lives in, and `vinga.session.id` is not a name
    any of them reads: pointed at a live Langfuse, a three-turn
    conversation arrived as four unrelated traces with an empty session
    (the walkthrough record in
    `docs/plans/2026-09-12-langfuse-backend-implementation.md`). So every
    span carries the generic `session.id` beside vinga's own spelling,
    and the same value under both: two names for one fact is only safe
    while it stays one fact.

    Every shape in one case, deliberately, for the reason the context
    case above gives: the alias is one derivation rather than six
    remembered copies.
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
    assert {span.name for span in spans} == {
        "session",
        TURN_SPAN,
        ASR_SPAN,
        LLM_SPAN,
        TTS_SPAN,
        PLAYBACK_SPAN,
    }
    for span in spans:
        assert span.attributes[SESSION_ID_ALIAS] == SESSION, span.name
        assert span.attributes["vinga.session.id"] == SESSION, span.name


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


def test_no_stage_span_mixes_a_call_s_identity_with_the_session_s_own() -> None:
    """The shape this milestone exists to refuse, on both success-side
    stage spans at once.

    The session opened against one ear and one voice; the turn ran on
    two others, differing in all four names. What each stage span has to
    carry is one of those two providers whole, never a hybrid: an
    open-time type beside a call-time model would describe a provider
    that never existed anywhere, and it is the shape a table edit alone
    would have produced, since the context is merged before the event's
    own attributes and only the name would have been overwritten.

    Asserted as an emptiness rather than key by key, so a fifth
    open-time fact would fail here too.
    """
    clock = Clock()
    telemetry, memory = exporting()
    events = a_turn(clock, telemetry)

    clock.tick(0.3)
    hear(events, identity=STANDBY_EAR)
    clock.tick(0.9)
    synthesize(events, stream_ms=900, identity=STANDBY_VOICE)
    finish_reply(events)
    close_session(events)

    spans = finished(telemetry, memory)
    asr = named(spans, ASR_SPAN).attributes
    tts = named(spans, TTS_SPAN).attributes

    # The ear that ran, whole, and nothing of the one the session opened
    # against: not its type (`faster_whisper`) and not its model
    # (`small`), which are the two the name's overwrite would have left.
    assert asr["vinga.provider.asr.name"] == "ears-standby"
    assert asr["gen_ai.provider.name"] == "openai_asr"
    assert asr["gen_ai.request.model"] == "whisper-1"
    assert asr["server.address"] == "api.openai.com"
    assert opened_against(asr, "asr") == ["vinga.provider.asr.name"]

    # The voice that produced the audio, the same way.
    assert tts["vinga.provider.tts.name"] == "voice-standby"
    assert tts["gen_ai.provider.name"] == "elevenlabs"
    assert tts["gen_ai.request.model"] == "eleven_turbo_v2"
    assert tts["server.address"] == "api.elevenlabs.io"
    assert opened_against(tts, "tts") == ["vinga.provider.tts.name"]

    # And each span still carries what the session opened against for
    # the stages it says nothing about, which is what a suppression that
    # was not conditional on the stage would have taken with it.
    assert asr["vinga.provider.tts.name"] == "voice"
    assert asr["vinga.provider.llm.model"] == "claude-sonnet-4-5"
    assert tts["vinga.provider.asr.type"] == "faster_whisper"
    assert tts["vinga.provider.vad.name"] == "floor"


def test_an_asr_outcome_that_names_no_ear_keeps_the_session_s_own() -> None:
    """The other half of the rule, which is why the suppression is
    conditional at all.

    Two ways an ASR outcome names no ear: a variant that does not
    declare the quartet, and one that declares it and carries four
    absences, which is what a provider the registry never built
    produces. Neither says anything about the stage, so what the session
    opened against is the best answer there is and deleting it would
    leave the span with no ASR identity at all.
    """
    for outcome in (
        lambda events: hear_nothing(events),
        lambda events: hear(events, unbuilt=True),
    ):
        clock = Clock()
        telemetry, memory = exporting()
        events = a_turn(clock, telemetry)

        clock.tick(0.3)
        outcome(events)
        finish_reply(events)
        close_session(events)

        carried = named(finished(telemetry, memory), ASR_SPAN).attributes
        assert carried["vinga.provider.asr.name"] == "ears"
        assert carried["vinga.provider.asr.type"] == "faster_whisper"
        assert carried["vinga.provider.asr.model"] == "small"
        # And nothing claiming to be the call's own identity, which is
        # the claim the outcome declined to make. What a stage was GIVEN
        # is not such a claim: an outcome that measured the audio says
        # how much there was whether or not it can name the ear.
        assert {key for key in carried if not key.startswith("vinga.")} == (
            GROUPING | ASR_USED
        )


# --- the gate's rejection, driven through the real runtime ------------


class FailingConfirmation:
    """The reply's own ASR answers; every barge-in confirmation after it
    fails, which is one of the two ways the gate turns a candidate
    away."""

    def __init__(self) -> None:
        self.calls = 0

    async def transcribe(
        self, pcm: bytes, sample_rate: int, language_hint: str | None = None
    ) -> AsrResult:
        self.calls += 1
        if self.calls == 1:
            return AsrResult(text="the question")
        raise ConnectionRefusedError("no route")


CUT_IN = config_with_agent(llm_reply="Answering {text}.")


async def test_a_rejected_confirmation_is_a_second_real_asr_operation() -> None:
    """End to end, through the runtime that emits it.

    A barge-in whose confirmation fails never reaches `start_reply`, so
    it opens no turn: the reply being spoken over goes on being the
    turn. But the gate says `provider_failed` at the ASR stage while
    that turn is open. That call is a second semantic operation even
    though it never becomes the turn's accepted transcription.

    The attempted confirmation is still semantic provider work. It is a
    second failed ASR span rather than a duplicate event on the turn.
    """
    telemetry, memory = exporting()
    ears = FailingConfirmation()
    session, socket = realtime_session(CUT_IN, cast(Any, ears))
    events = events_of(session)
    events.attach(telemetry.session_tap())
    # The session's own device and pair: this module's fixed ones are
    # not the ones a running session is talking as.
    open_session(events, providers={}, conversations=session.session_conversations)
    turn_taking(session).endpointer = ScriptedEndpointer(speech_ms=600)

    start_reply(session, speech_pcm(600), speech_ms=600)
    deadline = time.monotonic() + 10.0
    while socket.frames < 3:
        assert time.monotonic() < deadline, "the reply never started speaking"
        await asyncio.sleep(0.02)

    plant_utterance(session, speech_pcm(600))
    await end_utterance(session)
    assert ears.calls >= 2, "the gate never ran a confirmation"
    await session.runtime.drain(5.0)
    await wait_for_reply(session)
    close_session(events)

    spans = finished(telemetry, memory)
    turn = named(spans, TURN_SPAN)
    asr = spans_of(ASR_SPAN, spans)
    assert len(asr) == 2
    assert sum(one.status.status_code.name == "ERROR" for one in asr) == 1
    assert {one.attributes.get("error.type") for one in asr} == {
        None,
        "ConnectionRefusedError",
    }
    said = [event.name for event in turn.events]
    assert "provider_failed" not in said
