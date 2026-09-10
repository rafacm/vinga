"""The turn's own lifecycle, as the catalog speaks it since #66.

A turn used to be reconstructible only by inference: `heard` fired for a
non-empty transcript and for nothing else, `replied` was guarded by
whether anything was spoken, and a reply that failed, was cut short or
answered silence left no record saying so. The events here close that,
and what this file holds is the four claims a shape check cannot make.

**Every outcome is reachable.** `reply_finished` carries a closed set,
and a closed set whose members no path can produce is a vocabulary
rather than a record. So every one of the six is driven onto its own
decision site, and the assertion is over the set.

**A pair per turn, however the turn goes.** Consecutive silent and
failed turns in one still-open session each get their own
`turn_started` and their own `reply_finished`, which is exactly what the
old `replied` guard could not give.

**The barge-in gate is the interesting crossing.** A confirmed
interruption spends a whole ASR call deciding, so the turn that answers
it has to be stamped with the utterance rather than with the decision,
and its `heard` has to carry a latency it did not measure itself. A
candidate the gate turns away has to leave both surfaces alone.

**Nothing in the reply's tail can suppress the record.** The `finally`
opens with a cancellable await, and a cancellation delivered there once
would have skipped the event; the record goes out ahead of it, exactly
once, carrying the outcome that was latched and not the cancellation
that arrived afterwards.

The reads are through the tap, not through the log, because two of the
claims are about an emission's stamp and a log record does not carry
one. Attaching a consumer is the public way in (`SessionEvents.attach`),
which is what the exporter #66 exists for will do.
"""

import asyncio
from typing import Any, cast

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.support.configs import POET_MAC, base_config, config_with_agent
from tests.support.providers import (
    ScriptedEndpointer,
    ScriptedLlm,
    StallingLlm,
    Unreachable,
)
from tests.support.sessions import (
    end_utterance,
    events_of,
    plant_utterance,
    realtime_session,
    reply_in_flight,
    session_for,
    start_reply,
    turn_taking,
    wait_for_reply,
)
from tests.support.sockets import OrderedSocket, RecordingSocket
from tests.support.wire import speech_pcm
from vinga_server.events import Emission
from vinga_server.events.values import ReplyOutcome
from vinga_server.providers import AsrResult

pytestmark = pytest.mark.asyncio

# The audio a reply is handed where what it holds is beside the point:
# 20 ms of silence, which the configured ear answers whatever it holds.
UTTERANCE = b"\x00\x00" * 320


class Watching:
    """Every emission this session made, kept whole.

    A tap rather than `caplog`, because two of the claims below are
    about an emission's `at`: `turn_started` is stamped with an instant
    that is not the instant it was said at, and `speaking_finished` with
    the moment the last frame went out. A log record carries the payload
    and not the stamp.
    """

    def __init__(self) -> None:
        self.seen: list[Emission] = []

    def emit(self, emission: Emission) -> None:
        self.seen.append(emission)

    def of(self, event: str) -> list[Emission]:
        return [one for one in self.seen if one.payload["event"] == event]

    def names(self) -> list[str]:
        return [one.payload["event"] for one in self.seen]


def watching(session: Any) -> Watching:
    """A consumer attached the way the exporter will attach one."""
    tap = Watching()
    events_of(session).attach(tap)
    return tap


def outcomes(tap: Watching) -> list[str]:
    return [str(one.payload["outcome"]) for one in tap.of("reply_finished")]


class ScriptedEars:
    """One answer per utterance, in the order they were written down.

    An exception in the script is raised where the transcription would
    have answered, which is what makes a failed turn drivable in the
    same session as a silent one: the ear is a stage of the agent's
    providers and is handed in the way a deployment's own is, so
    swapping it between two turns of one conversation is not something
    a test could do at all.
    """

    def __init__(self, *answers: str | BaseException) -> None:
        self._answers = list(answers)
        self.asked = 0

    async def transcribe(
        self, pcm: bytes, sample_rate: int, language_hint: str | None = None
    ) -> AsrResult:
        answer = self._answers[min(self.asked, len(self._answers) - 1)]
        self.asked += 1
        if isinstance(answer, BaseException):
            raise answer
        return AsrResult(text=answer)


class Vanishing:
    """A device that took the socket and went away at the first word."""

    async def send_text(self, text: str) -> None:
        raise WebSocketDisconnect(1006)

    async def send_bytes(self, data: bytes) -> None:
        raise WebSocketDisconnect(1006)


def talking(scripts: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    """A session on a recording socket, which is what lets a reply run
    all the way through speaking."""
    session = session_for(
        base_config(),
        POET_MAC,
        cast(Any, scripts or {"poet": ScriptedLlm(["Two words."])}),
        **kwargs,
    )
    if session.websocket is None:
        session.websocket = cast(Any, RecordingSocket())
    return session


# --- the outcome set, one decision site at a time ----------------------


async def test_every_reply_outcome_has_a_decision_site_that_produces_it() -> None:
    """The closed set, driven rather than declared.

    Six paths, six words, and the assertion is over the set: a member
    nothing can latch would be a token the reference documents and no
    deployment ever sees, which is the same defect as an event nothing
    emits. Each one is reached the way the server reaches it, so the
    site the latch is written at is the site under test.
    """
    seen: list[str] = []

    # Nothing ended it, which is what `completed` is.
    ordinary = talking()
    tap = watching(ordinary)
    start_reply(ordinary, UTTERANCE)
    await wait_for_reply(ordinary)
    seen += outcomes(tap)

    # The ear answered, and answered with nothing.
    silent = talking(stages={"asr": cast(Any, ScriptedEars("   "))})
    tap = watching(silent)
    start_reply(silent, UTTERANCE)
    await wait_for_reply(silent)
    seen += outcomes(tap)

    # The ear could not answer at all, which the failure arm classifies.
    broken = talking(
        stages={"asr": cast(Any, Unreachable("asr", ConnectionRefusedError("no route")))}
    )
    tap = watching(broken)
    start_reply(broken, UTTERANCE)
    await wait_for_reply(broken)
    seen += outcomes(tap)

    # The device gave up on the answer, while the answer was still
    # being generated: a reply already over is a reply nothing aborted.
    aborting = talking({"poet": cast(Any, StallingLlm([5.0]))})
    tap = watching(aborting)
    start_reply(aborting, UTTERANCE)
    await asyncio.sleep(0.05)
    await aborting.runtime.device_aborted("wake_word_detected")
    seen += outcomes(tap)

    # The device went away mid-reply, which the body catches and returns
    # on: an unlatched exit would have called that a reply that finished.
    gone = talking(websocket=cast(Any, Vanishing()))
    tap = watching(gone)
    start_reply(gone, UTTERANCE)
    await wait_for_reply(gone)
    seen += outcomes(tap)

    # And the user cutting in, through the gate that decides it.
    seen += await _barged_in()

    assert set(seen) == {str(one) for one in ReplyOutcome}


async def _barged_in() -> list[str]:
    """One manual stop landing on a reply in flight, which is the
    unconditional cancel in `finish_utterance`: the gate ladder is not
    consulted, and the canceller still names itself."""
    ears = ScriptedEars("the first thing", "the second thing")
    session, _socket = realtime_session(
        config_with_agent(),
        cast(Any, ears),
        scripts={"assistant": cast(Any, StallingLlm([5.0]))},
    )
    tap = watching(session)
    turn_taking(session).endpointer = ScriptedEndpointer(speech_ms=600)
    plant_utterance(session, speech_pcm(320))
    await end_utterance(session)
    # Still generating, which is what makes the second utterance an
    # interruption rather than an ordinary next turn.
    await asyncio.sleep(0.05)
    assert reply_in_flight(session) is not None
    plant_utterance(session, speech_pcm(320))
    await end_utterance(session, endpointed=False)
    await session.runtime.drain(5.0)
    return outcomes(tap)


# --- a pair per turn, however the turn goes ----------------------------


async def test_consecutive_silent_and_failed_turns_each_get_their_own_pair() -> None:
    """What the old `replied` guard could not say.

    Two turns in one still-open session, neither of which spoke: the
    first is transcribed to nothing and the second cannot be
    transcribed at all. Each opens with a `turn_started` and closes with
    a `reply_finished` naming which of the two it was, and the session
    is still open at the end of both.
    """
    ears = ScriptedEars("   ", ConnectionRefusedError("no route"))
    session = talking(stages={"asr": cast(Any, ears)})
    tap = watching(session)

    start_reply(session, UTTERANCE)
    await wait_for_reply(session)
    start_reply(session, UTTERANCE)
    await wait_for_reply(session)

    lifecycle = [
        name
        for name in tap.names()
        if name in {"turn_started", "nothing_heard", "reply_finished", "session_closed"}
    ]
    assert lifecycle == [
        "turn_started",
        "nothing_heard",
        "reply_finished",
        "turn_started",
        "reply_finished",
    ]
    assert outcomes(tap) == ["nothing_heard", "failed"]
    # And the silent turn says what it cost to hear nothing, which is
    # the whole of the issue's motivating gap: an utterance that took a
    # real ASR call to come back empty.
    (heard_nothing,) = tap.of("nothing_heard")
    assert heard_nothing.payload["duration_s"] > 0
    assert heard_nothing.payload["asr_ms"] >= 0


# --- the barge-in gate, which is the interesting crossing --------------


class TimedConfirmation:
    """The first call is the reply's own ASR; every later one is a
    barge-in confirmation, which takes long enough to be measurable and
    records when it finished."""

    def __init__(self, confirmation: AsrResult, delay_s: float = 0.05) -> None:
        self._confirmation = confirmation
        self._delay_s = delay_s
        self.calls = 0
        self.fails: BaseException | None = None
        self.finished_at: float | None = None

    async def transcribe(
        self, pcm: bytes, sample_rate: int, language_hint: str | None = None
    ) -> AsrResult:
        self.calls += 1
        if self.calls == 1:
            return AsrResult(text="the question")
        await asyncio.sleep(self._delay_s)
        self.finished_at = asyncio.get_running_loop().time()
        if self.fails is not None:
            raise self.fails
        return self._confirmation


async def _speaking(config: Any, ears: Any) -> Any:
    """A session whose reply is past its own ASR and already speaking,
    which is where the last two gates are reached from."""
    session, socket = realtime_session(config, ears)
    turn_taking(session).endpointer = ScriptedEndpointer(speech_ms=600)
    start_reply(session, speech_pcm(600), speech_ms=600)
    while socket.frames < 3:
        await asyncio.sleep(0.02)
    return session


CUT_IN = config_with_agent(
    llm_reply="Answering {text}.", server={"barge_in_refractory_ms": 0}
)


async def test_a_confirmed_barge_in_is_stamped_with_the_utterance_it_answers() -> None:
    """The stamp crosses the gate, and the latency crosses with it.

    The confirmation is a whole ASR call, so the moment the interrupting
    reply starts is hundreds of milliseconds after the moment the user
    stopped talking. The turn is stamped with the earlier one, which is
    what makes an interrupted turn timed from the speech; and its
    `heard` carries the latency the gate measured for the confirmation
    it is reusing, rather than nothing at all.
    """
    ears = TimedConfirmation(AsrResult(text="stop and listen"))
    session = await _speaking(CUT_IN, cast(Any, ears))
    tap = watching(session)
    plant_utterance(session, speech_pcm(600))
    await end_utterance(session)
    await session.runtime.drain(5.0)

    (started,) = tap.of("turn_started")
    assert started.payload["barge_in"] is True
    assert ears.finished_at is not None
    # The whole claim in one comparison: the record of the turn predates
    # the decision that let the turn happen.
    assert started.at < ears.finished_at

    (heard,) = tap.of("heard")
    assert heard.payload["asr_ms"] >= 0


@pytest.mark.parametrize(
    ("what", "confirmation", "failure"),
    [
        ("nothing transcribed", AsrResult(text="   "), None),
        ("the confirmation failed", AsrResult(text=""), ConnectionRefusedError("no route")),
    ],
)
async def test_a_rejected_barge_in_candidate_starts_no_turn(
    what: str, confirmation: AsrResult, failure: BaseException | None
) -> None:
    """Both ways the gate turns a candidate away.

    Neither reaches `start_reply`, so neither says anything new: the
    rejection stays gate vocabulary, and the turn being spoken over goes
    on being the turn. The reply in flight is still the same one
    afterwards, which is what "the old turn resumes" means concretely.
    """
    ears = TimedConfirmation(confirmation)
    ears.fails = failure
    session = await _speaking(CUT_IN, cast(Any, ears))
    tap = watching(session)
    before = reply_in_flight(session)
    plant_utterance(session, speech_pcm(600))
    await end_utterance(session)

    assert tap.of("turn_started") == [], what
    assert tap.of("heard") == [], what
    assert tap.of("reply_finished") == [], what
    assert reply_in_flight(session) is before, what
    await session.runtime.drain(5.0)


# --- nothing in the reply's tail can suppress the record ---------------


async def test_a_cancellation_inside_the_filler_settle_reports_once() -> None:
    """The finding the emit's placement answers.

    The reply's `finally` opens with an await, and a cancellation
    delivered into that await would once have skipped the record
    entirely. The emit is the first statement now and `emit` is
    synchronous, so the record is already out when the settle is
    reached; a cancellation landing there changes neither how many
    records there are nor what the one says, which stays the outcome
    latched where the reply actually ended.
    """
    settling = asyncio.Event()
    session = talking(
        stages={"asr": cast(Any, Unreachable("asr", ConnectionRefusedError("no route")))}
    )
    tap = watching(session)
    calls: list[int] = []

    async def settle() -> None:
        # The failure arm settles once before the notice and the
        # `finally` settles again; it is the second that is under test,
        # because the record has been made by then.
        calls.append(1)
        if len(calls) < 2:
            return None
        settling.set()
        await asyncio.sleep(3600)

    session.runtime._filler.settle = settle  # type: ignore[method-assign]
    start_reply(session, UTTERANCE)
    await asyncio.wait_for(settling.wait(), timeout=5.0)

    await session.runtime.cancel_reply(ReplyOutcome.BARGED_IN)

    assert outcomes(tap) == ["failed"]


# --- the lookahead, against the window it overlaps ---------------------


async def test_a_synthesis_runs_inside_the_window_the_pacer_is_pacing() -> None:
    """What `sentence_synthesized` and the speaking pair say together.

    The lookahead exists so that a sentence's time to first byte is
    spent against playback that is already happening rather than against
    silence, and these three events are what make that visible from
    outside: the speaking window is first frame out to last frame out,
    and a later sentence's synthesis stream lives inside it. Pinned as
    an overlap rather than as a duration, because what the lookahead
    promises is concurrency and not a number.
    """
    session = talking(
        {"poet": ScriptedLlm(["One. Two. Three."])},
        websocket=cast(Any, OrderedSocket()),
    )
    tap = watching(session)
    start_reply(session, UTTERANCE)
    await wait_for_reply(session)

    (opened,) = tap.of("speaking_started")
    (closed,) = tap.of("speaking_finished")
    assert closed.payload["frames"] > 0
    assert closed.at >= opened.at

    streams = {
        int(one.payload["index"]): (one.at - one.payload["stream_ms"] / 1000, one.at)
        for one in tap.of("sentence_synthesized")
    }
    assert len(streams) >= 2, "one sentence cannot show a lookahead"
    later = streams[max(streams)]
    assert opened.at < later[0] < closed.at, (
        "the last sentence was synthesized outside the window the pacer paced, "
        "so nothing overlapped playback"
    )
