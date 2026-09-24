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
import gc
import json
import threading
import weakref
from typing import Any, cast

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.support.configs import POET_MAC, base_config, config_with_agent
from tests.support.providers import (
    GatedAsr,
    ScriptedEndpointer,
    ScriptedLlm,
    StallingLlm,
    Unreachable,
)
from tests.support.records import SpyStore
from tests.support.sessions import (
    REPLY_TIMEOUT_S,
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
from tests.support.stores import memory as lane_memory
from tests.support.wire import speech_pcm
from vinga_server.device.boundary import PlayableAudio
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


# What a turn is made of, as far as the sequence assertions below are
# concerned: the pair that bounds it, the four ways its ASR stage can
# end, and the one gate decision that happens between two turns. Named
# once, because a sequence assertion is only as exact as the filter in
# front of it.
_LIFECYCLE = frozenset(
    {
        "turn_started",
        "heard",
        "nothing_heard",
        "transcription_abandoned",
        "provider_failed",
        "reply_finished",
        "barge_in_merged",
    }
)


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


async def test_each_boundary_reports_the_outcome_it_latched() -> None:
    """The same decision sites, each held to its own word, and the one
    canceller the set above has no need to reach.

    The test above is over the set, so two sites that traded words would
    pass it. What `reply_finished` carries is what the boundary that
    ended the reply wrote down, so each path is asserted alone: nothing
    ended it, the ear heard nothing, the ear failed, the device gave up,
    the session closed under it, the device went away, and the user cut
    in. The close is the one the set does not need, since it latches
    the same word a device abort does; it is a boundary of its own all
    the same, and where the latch lives is exactly what can separate
    two callers that write the same word.
    """
    ordinary = talking()
    tap = watching(ordinary)
    start_reply(ordinary, UTTERANCE)
    await wait_for_reply(ordinary)
    assert outcomes(tap) == ["completed"]

    silent = talking(stages={"asr": cast(Any, ScriptedEars("   "))})
    tap = watching(silent)
    start_reply(silent, UTTERANCE)
    await wait_for_reply(silent)
    assert outcomes(tap) == ["nothing_heard"]

    broken = talking(
        stages={"asr": cast(Any, Unreachable("asr", ConnectionRefusedError("no route")))}
    )
    tap = watching(broken)
    start_reply(broken, UTTERANCE)
    await wait_for_reply(broken)
    assert outcomes(tap) == ["failed"]

    aborting = talking({"poet": cast(Any, StallingLlm([5.0]))})
    tap = watching(aborting)
    start_reply(aborting, UTTERANCE)
    await asyncio.sleep(0.05)
    await aborting.runtime.device_aborted("wake_word_detected")
    assert outcomes(tap) == ["aborted"]

    closing = talking({"poet": cast(Any, StallingLlm([5.0]))})
    tap = watching(closing)
    start_reply(closing, UTTERANCE)
    await asyncio.sleep(0.05)
    await closing.runtime.close()
    assert outcomes(tap) == ["aborted"]
    assert not closing.runtime.replying()

    gone = talking(websocket=cast(Any, Vanishing()))
    tap = watching(gone)
    start_reply(gone, UTTERANCE)
    await wait_for_reply(gone)
    assert outcomes(tap) == ["device_gone"]

    # The interrupted reply names the cut. The reply answering the
    # interruption is still generating when the drain gives up on it,
    # so the one record is the cut's.
    assert await _barged_in() == ["barged_in"]


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

    lifecycle = [name for name in tap.names() if name in _LIFECYCLE]
    assert lifecycle == [
        "turn_started",
        "nothing_heard",
        "reply_finished",
        "turn_started",
        "provider_failed",
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


CUT_IN = config_with_agent(llm_reply="Answering {text}.")


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


async def test_a_mid_asr_merge_leaves_both_turns_with_an_asr_outcome() -> None:
    """The shape the review round found, driven end to end.

    A barge-in landing while the reply is still inside its own
    transcription is the one path that cancels an ASR call rather than
    letting it answer: the head of the user's sentence is reconstituted
    in front of the continuation and one reply answers the whole thing.
    The cancelled call is not a provider failure, and `watching`
    catches `Exception`, so nothing used to say anything about that
    turn's ASR stage at all: it opened with `turn_started` and closed
    with `reply_finished` and the stage between them was invisible.

    Both turns are asserted whole, in order, because what is being
    claimed is a sequence rather than the presence of one record.
    """
    ears = GatedAsr()
    session, _socket = realtime_session(config_with_agent(), cast(Any, ears))
    tap = watching(session)
    turn_taking(session).endpointer = ScriptedEndpointer(speech_ms=600)
    plant_utterance(session, speech_pcm(320))
    await end_utterance(session)
    # Inside `transcribe`, which is what the merge needs: the gate reads
    # the held audio as the head of the sentence still being spoken.
    await asyncio.sleep(0.05)
    plant_utterance(session, speech_pcm(480))
    await end_utterance(session)
    ears.release.set()
    await session.runtime.drain(5.0)

    lifecycle = [name for name in tap.names() if name in _LIFECYCLE]
    assert lifecycle == [
        "turn_started",
        "barge_in_merged",
        "transcription_abandoned",
        "reply_finished",
        "turn_started",
        "heard",
        "reply_finished",
    ]
    assert outcomes(tap) == ["barged_in", "completed"]
    # And what the abandoned call cost, which is a bound on what it
    # would have cost rather than a latency it ever reported.
    (abandoned,) = tap.of("transcription_abandoned")
    assert abandoned.payload["asr_ms"] >= 0
    assert abandoned.payload["duration_s"] > 0


async def test_a_device_that_leaves_while_the_transcript_shows_still_says_heard() -> None:
    """The other way an ASR outcome went missing.

    The transcript is shown to the device before the reply speaks, and
    that send can meet a device that has gone away. `heard` used to be
    emitted after it, so a successful transcription followed by a
    disconnect ended the turn `device_gone` with nothing saying the ASR
    stage had answered at all. The record is made where the result is
    classified now, ahead of any socket: what the ear answered is a fact
    about this turn and does not depend on the device still being there
    to be shown it.
    """
    session = talking(websocket=cast(Any, Vanishing()))
    tap = watching(session)
    start_reply(session, UTTERANCE)
    await wait_for_reply(session)

    lifecycle = [name for name in tap.names() if name in _LIFECYCLE]
    assert lifecycle == ["turn_started", "heard", "reply_finished"]
    assert outcomes(tap) == ["device_gone"]


async def test_the_playback_window_opens_at_the_frame_and_not_before_it() -> None:
    """Where the opening stamp is taken, which is behavior.

    Everything between handing a batch to the pacer and the first frame
    reaching the device belongs to the pacer: the frame's own slot in
    the cadence, the pause a barge-in confirmation holds the stream
    with, and the send itself. The event used to be emitted in front of
    all three, so a first delivery that was held or slow inflated an
    interval the generated reference calls first frame out to last frame
    out. It is stamped with the delivery now, and the pause is what
    makes the difference measurable: the batch is handed over while the
    stream is held, released a beat later, and the record has to name
    the later instant.
    """
    held = asyncio.Event()

    class Waiting:
        """A device whose first frame cannot leave until it is let."""

        def __init__(self) -> None:
            self.frames = 0

        async def send_text(self, text: str) -> None:
            return None

        async def send_bytes(self, data: bytes) -> None:
            if self.frames == 0:
                await held.wait()
            self.frames += 1

    session = talking(websocket=cast(Any, Waiting()))
    tap = watching(session)
    handed = events_of(session).now()
    sending = asyncio.create_task(session.send_audio(PlayableAudio([b"frame", b"frame"])))
    # Long enough that an interval opened at the hand-over would be
    # visibly wrong rather than arguably early.
    await asyncio.sleep(0.2)
    assert tap.of("speaking_started") == [], "the window opened before a frame went out"
    held.set()
    await sending

    (opened,) = tap.of("speaking_started")
    assert opened.at >= handed + 0.2


# --- nothing in the reply's tail can suppress the record ---------------


async def test_a_cancellation_inside_the_filler_settle_reports_once() -> None:
    """The event and transcript boundaries both survive the tail await.

    The reply tail opens with an await, and a cancellation delivered
    into that await would once have skipped both records entirely. The
    event is emitted synchronously before the await. The cancellation
    arm now closes the transcript utterance too, so the root held by
    that event cannot survive the session.
    """
    settling = asyncio.Event()
    class Transcripts:
        def __init__(self) -> None:
            self.missing: list[tuple[str, str]] = []

        def turn_missing(self, session: str, utterance: str) -> None:
            self.missing.append((session, utterance))

    transcripts = Transcripts()
    session = talking(
        stages={"asr": cast(Any, Unreachable("asr", ConnectionRefusedError("no route")))},
        conversations=SpyStore(),
        transcripts=transcripts,
    )
    tap = watching(session)
    calls: list[int] = []

    async def settle() -> None:
        # The failure arm settles once before the notice and the
        # reply tail settles again; it is the second that is under test,
        # because both terminal records have to survive it.
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
    [(missing_session, utterance)] = transcripts.missing
    assert missing_session == session.session_id
    assert utterance


# --- a cancel lets go of its own reply and nothing else ----------------


class HoldsTheFirstStop:
    """A device whose first `tts stop` cannot leave until it is let.

    The stop is the last thing a reply's `finally` sends, so holding it
    holds a cancelled reply at the very end of its life, which is where
    the canceller is still waiting for it."""

    def __init__(self) -> None:
        self.stops = 0
        self.stopping = asyncio.Event()
        self.release = asyncio.Event()

    async def send_text(self, text: str) -> None:
        if json.loads(text).get("state") != "stop":
            return
        self.stops += 1
        if self.stops == 1:
            self.stopping.set()
            await self.release.wait()

    async def send_bytes(self, data: bytes) -> None:
        return None


async def test_a_reply_started_while_a_cancel_waits_stays_the_reply_in_flight() -> None:
    """A cancel lets go of the reply it cancelled and of nothing else.

    No path in a served session starts a reply while a cancel is still
    waiting one out: the floor starts and cancels on one task, in turn.
    What a cancel may clear is still worth holding, because the answer
    used to be "whatever is there once the wait is over", and a reply
    started in that wait would have been running with nothing left
    holding it: not cancellable, not drained, and not what `replying()`
    answers about.
    """
    device = HoldsTheFirstStop()
    session = talking(
        {"poet": cast(Any, StallingLlm([5.0]))}, websocket=cast(Any, device)
    )
    tap = watching(session)
    start_reply(session, UTTERANCE)
    await asyncio.sleep(0.05)

    cancelling = asyncio.create_task(
        session.runtime.cancel_reply(ReplyOutcome.BARGED_IN)
    )
    await asyncio.wait_for(device.stopping.wait(), timeout=5.0)
    start_reply(session, UTTERANCE)
    started = reply_in_flight(session)
    device.release.set()
    await cancelling

    assert reply_in_flight(session) is started
    assert session.runtime.replying()
    await session.runtime.cancel_reply(ReplyOutcome.ABORTED)
    assert outcomes(tap) == ["barged_in", "aborted"]
    assert reply_in_flight(session) is None


async def test_a_cancel_cut_short_by_the_session_cap_keeps_the_cap() -> None:
    """The session cap's own shape: a barge-in's cancel waiting out a
    reply's closing `tts stop` when `max_session_s` runs out.

    The cap is `asyncio.timeout` around the serve loop, and it raises
    only if the cancellation it delivered comes back out of the wait. A
    cancel that swallowed it let the session run on with nothing left
    to end it. Nor is the reply let go: the runtime still holds it, so
    it finishes its stop undisturbed and the close sees it through."""
    device = HoldsTheFirstStop()
    session = talking(
        {"poet": cast(Any, StallingLlm([5.0]))}, websocket=cast(Any, device)
    )
    tap = watching(session)
    start_reply(session, UTTERANCE)
    await asyncio.sleep(0)
    cancelled = reply_in_flight(session)

    async def capped() -> None:
        async with asyncio.timeout(0.05):
            await session.runtime.cancel_reply(ReplyOutcome.BARGED_IN)

    serving = asyncio.create_task(capped())
    await asyncio.wait_for(device.stopping.wait(), timeout=5.0)

    with pytest.raises(TimeoutError):
        await serving
    assert reply_in_flight(session) is cancelled
    assert session.runtime.replying()

    device.release.set()
    assert await session.runtime.drain(5.0)
    assert device.stops == 1
    assert outcomes(tap) == ["barged_in"]

    await session.runtime.close()
    assert reply_in_flight(session) is None
    assert outcomes(tap) == ["barged_in"]


# --- a close sees its reply and its purge through ----------------------
#
# The close is the one caller of the reply's end that must not let go
# early: the session's close path goes on to close the store and the
# export behind it, so a cancellation reaching it is held until the
# reply is done, the handle is cleared and the purge has run.
#
# The reply is held in its tail's `filler.settle` by replacing the
# runner's method, the precedent the settle test above set: it is the
# only await between `reply_finished` and the turn record, and nothing
# the reply is built from reaches it any other way.


class TurnLog:
    """The transcript collaborator, writing down when the reply's last
    record was made into a log the test also writes the close's end
    into, so the assertion is over their order."""

    def __init__(self, log: list[str]) -> None:
        self._log = log

    def turn_recorded(self, session: str, record: Any, landed: Any, *, final: bool) -> None:
        if final:
            self._log.append("turn")

    def turn_missing(self, session: str, utterance: str) -> None:
        self._log.append("turn")


class PurgeSpy:
    """The lane's memory store, with the session-close purge watched.

    The purge is the memory store's own method, handed to a runtime
    whose deployment records nothing, which is how a session built here
    gets one at all. Everything else is the lane's store, reached
    through this. `on_call` runs in the purge's worker thread, first;
    `blocks` holds the purge there until `release` is set; `fails` is
    made and raised once the purge has otherwise finished."""

    def __init__(
        self,
        *,
        blocks: bool = False,
        fails: Any = None,
        on_call: Any = None,
    ) -> None:
        self._store = lane_memory()
        self.purged: list[list[str]] = []
        self.finished = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self._blocks = blocks
        self._fails = fails
        self.on_call = on_call

    def purge_threads(self, threads: Any) -> None:
        self.purged.append(list(threads))
        if self.on_call is not None:
            self.on_call()
        self.entered.set()
        if self._blocks:
            assert self.release.wait(REPLY_TIMEOUT_S), "the purge was never released"
        self.finished += 1
        if self._fails is not None:
            raise self._fails()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


def settling_with(session: Any, settle: Any) -> None:
    """Stand `settle` in for the reply tail's `filler.settle`: the one
    reach past the runtime these tests make, for the reason above."""
    session.runtime._filler.settle = settle


def held_at_settle(session: Any, *, gives_way: bool = False) -> asyncio.Event:
    """Hold the reply's tail at `filler.settle` until it is cancelled,
    and answer the event set when it gets there.

    `gives_way` is a settle that, cancelled, stands its clip down and
    returns rather than re-raising, so the tail goes on to its closing
    `tts stop`: a tail a hurry reached and did not end."""
    settling = asyncio.Event()

    async def settle() -> None:
        settling.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if not gives_way:
                raise

    settling_with(session, settle)
    return settling


def when_closed(closing: asyncio.Task[None], reply: Any, log: list[str]) -> None:
    """Write the close's end into `log`, saying whether the reply was
    still running at that moment."""
    closing.add_done_callback(
        lambda _: log.append("closed with the reply running" if reply.running() else "closed")
    )


async def let_go(closing: asyncio.Task[None]) -> None:
    """Wait for a cancelled close to end, bounded, and see that it ended
    in its caller's cancellation."""
    done, _ = await asyncio.wait([closing], timeout=REPLY_TIMEOUT_S)
    assert done, "the close never let its caller go"
    with pytest.raises(asyncio.CancelledError):
        await closing


async def test_a_cancelled_close_records_the_turn_before_it_lets_go() -> None:
    """The cancellation arrives while the reply is at its settle, before
    its turn is recorded. It is passed on, the tail's settle arm records
    the turn under it, and only then does the close end, cancelled."""
    log: list[str] = []
    session = talking(
        {"poet": cast(Any, StallingLlm([5.0]))},
        conversations=SpyStore(),
        transcripts=TurnLog(log),
    )
    tap = watching(session)
    settling = held_at_settle(session)
    start_reply(session, UTTERANCE)
    await asyncio.sleep(0)
    reply = reply_in_flight(session)
    closing = asyncio.create_task(session.runtime.close())
    when_closed(closing, reply, log)
    await asyncio.wait_for(settling.wait(), timeout=5.0)

    closing.cancel()

    await let_go(closing)
    assert log == ["turn", "closed"]
    assert reply_in_flight(session) is None
    assert outcomes(tap) == ["aborted"]


async def test_a_cancelled_close_purges_after_the_reply_and_before_it_lets_go() -> None:
    """The same cancellation on a deployment that records nothing, where
    the close's second step is the purge: it runs once the reply's task
    is done and the handle is cleared, with the session's current
    threads, and the close ends after it.

    A separate session from the test above because the two halves
    cannot share one: a runtime is handed the purge only where it is
    handed no store to record turns in."""
    log: list[str] = []
    spy = PurgeSpy()
    session = talking({"poet": cast(Any, StallingLlm([5.0]))}, memory=cast(Any, spy))
    settling = held_at_settle(session)
    start_reply(session, UTTERANCE)
    await asyncio.sleep(0)
    reply = reply_in_flight(session)
    spy.on_call = lambda: log.append(
        "purged with the reply running"
        if reply.running() or reply_in_flight(session) is not None
        else "purged"
    )
    closing = asyncio.create_task(session.runtime.close())
    when_closed(closing, reply, log)
    await asyncio.wait_for(settling.wait(), timeout=5.0)

    closing.cancel()

    await let_go(closing)
    assert log == ["purged", "closed"]
    assert spy.purged == [list(session.runtime.conversations.current_threads())]


async def test_a_close_cancelled_twice_raises_once_after_the_reply() -> None:
    """The first cancellation hurries a tail that gives way at its
    settle and goes on to its closing stop; the second arrives there.
    The close still waits the reply out, and ends cancelled once."""
    device = HoldsTheFirstStop()
    log: list[str] = []
    session = talking(
        {"poet": cast(Any, StallingLlm([5.0]))},
        websocket=cast(Any, device),
        conversations=SpyStore(),
        transcripts=TurnLog(log),
    )
    settling = held_at_settle(session, gives_way=True)
    start_reply(session, UTTERANCE)
    await asyncio.sleep(0)
    reply = reply_in_flight(session)
    closing = asyncio.create_task(session.runtime.close())
    when_closed(closing, reply, log)
    try:
        await asyncio.wait_for(settling.wait(), timeout=5.0)

        closing.cancel()
        await asyncio.wait_for(device.stopping.wait(), timeout=5.0)
        assert not closing.done()
        closing.cancel()

        await let_go(closing)
    finally:
        # A tail that gives way at its settle takes the loop's own
        # teardown cancel there too, and would then wait on this stop
        # for ever: let it go, whatever the test found.
        device.release.set()
    assert log == ["turn", "closed"]
    assert device.stops == 1
    assert reply_in_flight(session) is None


async def test_a_cancellation_during_the_purge_waits_for_the_purge() -> None:
    """A thread cannot be cancelled, so a close that let a cancellation
    through here would leave the purge running behind the store's own
    close. It is waited out instead, and the cancellation raised
    after."""
    spy = PurgeSpy(blocks=True)
    session = talking(memory=cast(Any, spy))
    closing = asyncio.create_task(session.runtime.close())
    try:
        assert await asyncio.to_thread(spy.entered.wait, REPLY_TIMEOUT_S)
        closing.cancel()
        # Turns of the loop enough for a cancellation to land and a
        # task it ended to finish.
        for _ in range(10):
            await asyncio.sleep(0)
        assert not closing.done()
    finally:
        spy.release.set()

    await let_go(closing)
    assert (len(spy.purged), spy.finished) == (1, 1)


class Collapse(BaseException):
    """A failure that is not an `Exception`, which an arm catching only
    those would let past the purge."""


@pytest.mark.parametrize("failure", [RuntimeError, Collapse], ids=["exception", "base-exception"])
async def test_a_reply_that_failed_still_purges(failure: type[BaseException]) -> None:
    """A reply whose tail broke raises out of the close, as it always
    did, and no longer skips the purge on the way."""
    spy = PurgeSpy()
    session = talking({"poet": cast(Any, StallingLlm([5.0]))}, memory=cast(Any, spy))

    async def settle() -> None:
        raise failure("the tail broke")

    settling_with(session, settle)
    start_reply(session, UTTERANCE)
    await asyncio.sleep(0)

    with pytest.raises(failure, match="the tail broke"):
        await session.runtime.close()

    assert len(spy.purged) == 1
    assert reply_in_flight(session) is None


class Witness:
    """Something only a failed purge's exception holds, so its going is
    how a test knows that exception was collected rather than kept."""


class PurgeBroke(Exception):
    """The purge's own failure, carrying a witness."""

    def __init__(self) -> None:
        super().__init__("the purge broke")
        self.witness: Witness | None = Witness()


async def test_when_both_fail_the_reply_is_raised_and_the_purge_is_read() -> None:
    """The reply's failure is the one raised; the purge's is read and
    dropped. Read rather than left: a task whose exception nobody
    retrieved is reported by the loop when it is collected, text and
    chain included."""
    loop = asyncio.get_running_loop()
    reports: list[dict[str, Any]] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _, context: reports.append(context))
    witnesses: list[weakref.ref[Witness]] = []

    def failing() -> PurgeBroke:
        broke = PurgeBroke()
        assert broke.witness is not None
        witnesses.append(weakref.ref(broke.witness))
        return broke

    try:
        spy = PurgeSpy(fails=failing)
        session = talking({"poet": cast(Any, StallingLlm([5.0]))}, memory=cast(Any, spy))

        async def settle() -> None:
            raise RuntimeError("the reply broke")

        settling_with(session, settle)
        start_reply(session, UTTERANCE)
        await asyncio.sleep(0)

        with pytest.raises(RuntimeError, match="the reply broke") as raised:
            await session.runtime.close()

        del raised
        # More than one pass, and a turn of the loop between, as
        # `test_drain.py` does: a task, its coroutine and the traceback
        # of what it raised reference each other.
        for _ in range(3):
            gc.collect()
            await asyncio.sleep(0)
        [gone] = witnesses
        assert gone() is None, "the purge's failure outlived the check, which proves nothing"
    finally:
        loop.set_exception_handler(previous)

    assert [context.get("message") for context in reports] == []


# --- the window that is never opened -----------------------------------


async def test_a_reply_that_never_spoke_emits_neither_half_of_the_pair() -> None:
    """The other half of the balanced-pair claim, and the one that
    guards a line nothing else does.

    `speaking_started` and `speaking_finished` bound the interval the
    pacer paced. A reply that put no frame on the wire opened no
    interval, so it must emit neither, and `_finished_speaking`'s early
    return on a pacer reporting no delivery is the whole of what makes
    that true.

    That line is load-bearing and was, until this test, entirely
    unpinned: removing it leaves every other assertion in this suite
    green while `speaking_finished` starts firing with `frames` zero on
    replies that never spoke, unbalancing the pair in the opposite
    direction and giving everything derived from it a phantom
    zero-length interval. It is also the line a reader is most likely
    to reach for, since #455 named it as the prime suspect for an
    absence that turned out to be a deployment running code without the
    event in it at all.

    Three ways a reply reaches its `finally` having said nothing, driven
    in one still-open session because the claim is about every one of
    them rather than about a lucky one: transcribed to nothing, an ear
    that cannot be reached, and a voice that cannot be reached. The
    third is the one that matters most, because it is the only one that
    gets as far as asking for audio.
    """
    ears = ScriptedEars("   ", ConnectionRefusedError("no route"), "Say something.")
    session = talking(
        stages={
            "asr": cast(Any, ears),
            "tts": cast(Any, Unreachable("tts", ConnectionRefusedError("no route"))),
        }
    )
    tap = watching(session)

    for _ in range(3):
        start_reply(session, UTTERANCE)
        await wait_for_reply(session)

    assert outcomes(tap) == ["nothing_heard", "failed", "failed"], (
        "the three turns did not end the three ways this test is about"
    )
    # The third turn was heard, so it really did reach the voice rather
    # than stopping short of it, which is what makes its silence a
    # statement about the pacer and not about the ear.
    assert len(tap.of("heard")) == 1
    assert [one.payload["stage"] for one in tap.of("provider_failed")] == ["asr", "tts"]

    assert tap.of("speaking_started") == [], (
        "an interval was opened for a reply that put no frame on the wire"
    )
    assert tap.of("speaking_finished") == [], (
        "an interval was closed that was never opened; the early return in "
        "_finished_speaking is what keeps the pair balanced here"
    )


# --- what a synthesis cost, measured at the sentence -------------------


async def test_each_stream_reports_the_length_of_its_own_sentence() -> None:
    """`characters` is the sentence the voice was handed, not the reply
    it came out of and not the sentence before it.

    The size is what a voice is billed on, so it is the one fact this
    surface carries about the text: a count and never a word of it. The
    three sentences are deliberately three different lengths, because a
    count taken from the wrong string is invisible against sentences
    that happen to match.
    """
    session = talking(
        {"poet": ScriptedLlm(["One. Two two. Three three three."])},
        websocket=cast(Any, OrderedSocket()),
    )
    tap = watching(session)
    start_reply(session, UTTERANCE)
    await wait_for_reply(session)

    counted = {
        int(one.payload["index"]): one.payload["characters"]
        for one in tap.of("sentence_synthesized")
    }
    # "One." then "Two two." then the tail the splitter flushes,
    # "Three three three.", each measured as the voice received it.
    assert counted == {0: 4, 1: 8, 2: 18}


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
