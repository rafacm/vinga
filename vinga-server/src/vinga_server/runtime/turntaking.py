"""Who holds the floor: the mic feed, the utterance buffer, and the
gates in front of a barge-in.

The sibling of [`turns.py`](turns.py), and the two are told apart by
what they are about: `turns.py` records what a turn contained, this
module decides who is speaking. Nothing here retains a transcript or
orchestrates a reply (the gate does inspect the confirmation ASR's
text, but only to decide the cancel, and hands it on untouched), and
nothing there watches the microphone.

While the device listens, every decoded frame lands in the utterance
buffer and in the agent's endpointer. When the endpointer says the
utterance ended, or the device says so by hand, the buffer is trimmed
back to the speech and handed to the orchestrator as the thing to
answer.

An utterance that ends while a reply is streaming is the user cutting
in, which is what barge-in is. An endpointer-driven cancel is gated: a
reply is only cancelled on evidence of user speech (enough classified
speech, a transcript when in doubt), because acoustics alone are as
often noise or the reply's own bleed as the user (#28). A manual
`listen stop` mid-reply is a deliberate act and cancels unconditionally.

The orchestrator is reached through four calls and nothing else, so the
reply task, the conversation history, and the provider observability
stay where they are: this module decides, and something else acts on
the decision.
"""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vinga_server.config import ServerConfig
from vinga_server.device.boundary import PIPELINE_SAMPLE_RATE, DeviceOutput
from vinga_server.events import SessionEvents, logger
from vinga_server.events.catalog import (
    BargeIn,
    BargeInMerged,
    BargeInUnderFloor,
    BargeInWithoutTranscript,
)
from vinga_server.events.values import ABSENT, Absent, Real, ReplyOutcome, Whole
from vinga_server.providers import AsrResult, Endpointer

if TYPE_CHECKING:
    # Named for the annotation alone: `pipeline` imports this module, so
    # a runtime import here would close the cycle.
    from vinga_server.runtime.pipeline import PipelineRuntime

# How much recent mic audio the utterance buffer keeps. A realtime
# session listens through the silences too, so without a bound the
# buffer would grow for the whole session (about 115 MB at the one-hour
# cap). Well above the endpointer's 10 s `max_utterance_ms`, so what a
# trim can ever drop is silence nobody is going to transcribe.
UTTERANCE_TAIL_S = 30
UTTERANCE_TAIL_BYTES = UTTERANCE_TAIL_S * PIPELINE_SAMPLE_RATE * 2


@dataclass(frozen=True)
class Confirmation:
    """What a confirmation transcription answered, and the ear that
    answered it.

    Two fields rather than a bare result, because the two are only true
    together. The call is awaited while the reply it is deciding about
    is still running, and that reply can hand the conversation over,
    which rebinds the session's providers; so which ear ran this
    transcription is knowable at the call and nowhere after it. The turn
    that goes on to reuse the result already reports what the call cost,
    and a record whose latency and whose provider described two
    different calls would say less than one that named neither.

    `provider` is typed `object` for the reason the seam itself exists:
    the ladder needs an answer rather than the machinery that produces
    one, and `object` is exactly what `events/assembly.py` takes, so
    nothing about a provider's own types reaches this module.
    """

    result: AsrResult
    provider: object


@dataclass(frozen=True)
class Utterance:
    """What the floor hands the orchestrator to answer.

    One type rather than a widening argument list, and the reason is
    that every field of it is a fact the floor knows and the reply
    cannot recover: when the user stopped speaking, how much of what
    they said was classified as speech, whether answering this one means
    interrupting a reply, and the transcription the barge-in gate
    already ran with what it cost.

    `ended_at` is a reading of the session's clock taken as the
    utterance closed, and it is the whole of why this type exists. The
    confirmation ladder can spend a whole ASR call deciding whether an
    interruption is real, so the instant the reply starts and the
    instant the user stopped talking are hundreds of milliseconds apart
    on exactly the path an operator most wants timed. Carrying the
    earlier one across the gate is what lets `turn_started` be stamped
    with the utterance rather than with the decision about it.

    `transcript`, `asr_ms` and `asr_provider` travel together and are
    set together: a confirmed barge-in already transcribed this audio to
    decide the cancel, so the reply reuses the result rather than
    running ASR twice, and the latency of the run that produced it and
    the ear that ran it both belong to the turn that is answering it.
    The ear rides along rather than being looked up at the far end for
    the reason `Confirmation` gives: a handover can rebind the session's
    providers while a confirmation is in flight.
    """

    pcm: bytes
    ended_at: float
    speech_ms: int
    barge_in: bool
    transcript: AsrResult | None = None
    asr_ms: int | None = None
    asr_provider: object | None = None


class TurnTaking:
    """One conversation's floor, for the life of one connection.

    `endpointer` is public and starts as None: the agent's VAD makes it,
    and an agent handover replaces it, since the previous agent's
    endpointer carries the previous agent's tuning and mid-utterance
    state.

    `reply` is the orchestrator, and only four of its members are ever
    touched from here: whether a reply is in flight (`replying`), how
    one is started (`start_reply`), how one is cancelled
    (`cancel_reply`), and the confirmation transcription the gate ladder
    needs (`confirm_transcript`). Narrow on purpose. The confirmation is
    asked for whole rather than assembled here, because what it runs
    inside (the provider watch, the session's language lock) belongs to
    the orchestrator and the ladder needs none of it to decide."""

    def __init__(
        self,
        events: SessionEvents,
        output: DeviceOutput,
        server: ServerConfig,
        reply: "PipelineRuntime",
    ) -> None:
        self._events = events
        self.session_id = events.session_id
        self._output = output
        self._server = server
        self._reply = reply
        self.endpointer: Endpointer | None = None
        self._utterance = bytearray()
        # How much the tail cap has cut from the front of `_utterance`
        # since the last reset, which is what maps the endpointer's
        # speech-start offset (counted over everything fed) onto a
        # position in the buffer that remains.
        self._utterance_dropped = 0
        # The PCM the reply task in flight was handed, held until its
        # ASR call returns. Still being set is the mid-ASR marker: a
        # barge-in landing then killed the head of the user's own
        # sentence, so this is also the merge source that reconstitutes
        # it in front of the continuation.
        self._reply_pcm: bytes | None = None
        # Whether this runtime is holding the device's outgoing frames
        # while a barge-in is confirmed. Tracked here rather than asked
        # of the device: the runtime is the only thing that ever pauses
        # the stream, so its own intent is the honest answer, and the
        # boundary stays free of a query only the filler would read.
        self._output_paused = False

    @property
    def output_paused(self) -> bool:
        """Whether the outgoing frames are held for a confirmation, read
        by the filler's fire-time stand-down and written by nothing
        outside the ladder below."""
        return self._output_paused

    async def feed(self, pcm: bytes) -> None:
        """One decoded mic frame, at `PIPELINE_SAMPLE_RATE`. Called only
        while the device is listening and the edge's guards passed, which
        is why the VAD sample below records the listening as true without
        asking."""
        if self.endpointer is None:
            return
        self._utterance.extend(pcm)
        if len(self._utterance) > UTTERANCE_TAIL_BYTES:
            excess = len(self._utterance) - UTTERANCE_TAIL_BYTES
            del self._utterance[:excess]
            self._utterance_dropped += excess
        endpointed = self.endpointer.feed(pcm)
        # After the feed, so the sample is the endpointer's opinion of
        # the audio just recorded rather than of the frame before it.
        self._events.vad(self.endpointer.speech_ms(), True, self._reply.replying())
        if endpointed:
            await self.finish_utterance(endpointed=True)

    def restart(self) -> None:
        """Start a fresh utterance: the buffer, the drop accounting and
        the endpointer all go back to where they began."""
        self._utterance.clear()
        self._utterance_dropped = 0
        if self.endpointer is not None:
            self.endpointer.reset()

    def forget_reply_audio(self) -> None:
        """The reply's playback is over: the endpointer stops carrying
        it into whatever the user says next.

        A continuously listening session feeds the endpointer the
        assistant's own echo for the whole of a reply, and the device's
        playback trails the server by about 760 ms, so the loudest
        thing in the buffer when the user answers is the question they
        are answering. A recurrent endpointer scores their answer
        against that, and misses it (#456).

        Only the endpointer's memory of the audio, and deliberately not
        `restart` beside it: a user who is already mid-sentence when
        the reply ends keeps their buffer, their drop accounting and
        their endpointing progress, which is the continuation `restart`
        here would throw away (#80). Unconditional for the same reason
        it is cheap: a re-warm costs about one window against a
        trailing-silence budget of about twenty-one, so there is
        nothing for a branch on "is an utterance open" to buy.
        """
        if self.endpointer is not None:
            self.endpointer.forget_audio()

    async def manual_stop(self) -> None:
        """A manual end of utterance. Nothing buffered means nothing was
        said, so there is nothing to answer."""
        if self._utterance:
            await self.finish_utterance()

    def clear_pending(self) -> None:
        """The reply in flight is past its own ASR, or over: nothing of
        the user's sentence is left for a barge-in to destroy, so the
        merge source comes down."""
        self._reply_pcm = None

    def speech_ms(self) -> int:
        """How much of what was fed the endpointer classified as speech,
        rounded to milliseconds, and zero where no endpointer exists
        yet."""
        return round(self.endpointer.speech_ms()) if self.endpointer is not None else 0

    async def finish_utterance(self, endpointed: bool = False) -> None:
        """Hand the buffered utterance to the reply task. Listening then
        stops until the device asks again, which auto mode does by
        sending `listen start` after the reply's `tts stop`. Not in
        realtime mode: that device asked once and is still streaming, so
        stopping here would leave nobody to re-arm it and the session
        would answer one utterance and go deaf.

        An utterance that ends while a reply is still streaming is the
        user cutting in, so the reply in flight is cancelled and this one
        answered instead. Cancelling sends the old reply's `tts stop`
        before the new reply's `tts start`, because `cancel_reply` waits
        for the task it cancelled. When the endpointer decided the end,
        the cancel first has to pass the gates in `_gate_barge_in`,
        because that decision is acoustic and acoustics mid-reply are as
        often noise or playback bleed as the user; a manual `listen
        stop` is the user holding the button and speaking, so it stays
        unconditional. With `server.barge_in` off the utterance is
        dropped instead, which is what a board with leaky echo
        cancellation wants; from the mic that case is already filtered
        in `_handle_audio`, so what reaches here is a manual `listen
        stop` mid-reply."""
        # Read first, and before the gates below can spend an ASR call:
        # this is the instant the user stopped speaking, and it is what
        # the turn that answers them is stamped with however long the
        # deciding takes.
        ended_at = self._events.now()
        speech_ms = self.speech_ms()
        pcm = self._trimmed_utterance()
        self.restart()
        # Reported before any of the gates below can drop the utterance:
        # somebody talked, whether or not it earns a reply, and the edge
        # counts the idle timeout from both ends of a turn.
        self._output.user_turn_ended()
        result: AsrResult | None = None
        asr_ms: int | None = None
        asr_provider: object | None = None
        # Whether answering this utterance means interrupting a reply,
        # which is true of every shape that reaches `start_reply` with
        # one in flight: a confirmed barge-in, a mid-ASR merge, and a
        # manual stop that cut one short.
        interrupting = self._reply.replying()
        if interrupting:
            if not self._server.barge_in:
                logger.warning(
                    "session %s: dropping an utterance, a reply is already streaming",
                    self.session_id,
                )
                return
            if endpointed:
                gated = await self._gate_barge_in(pcm, speech_ms)
                if gated is None:
                    return
                pcm, result, asr_ms, asr_provider = gated
            else:
                self._events.emit(
                    lambda: BargeIn(
                        speech_ms=Whole(speech_ms), speaking_ms=self._speaking_ms()
                    )
                )
                await self._reply.cancel_reply(ReplyOutcome.BARGED_IN)
        logger.info(
            "session %s: utterance of %.1f s",
            self.session_id,
            len(pcm) / 2 / PIPELINE_SAMPLE_RATE,
        )
        self._reply_pcm = pcm if result is None else None
        self._reply.start_reply(
            Utterance(
                pcm=pcm,
                ended_at=ended_at,
                speech_ms=speech_ms,
                barge_in=interrupting,
                transcript=result,
                asr_ms=asr_ms,
                asr_provider=asr_provider,
            )
        )

    async def _gate_barge_in(
        self, pcm: bytes, speech_ms: int
    ) -> tuple[bytes, AsrResult | None, int | None, object | None] | None:
        """Decide what an endpointed utterance may do to the reply in
        flight: None to drop it and let the reply live, or the PCM to
        answer (with its transcription, what that transcription cost and
        the ear that ran it, when confirming it already ran ASR). The
        gates exist because a reply is only cancelled on evidence of
        user speech; acoustics alone can at most pause it (see the ADR
        of that name).

        The confirmation's latency is measured here, at the site that
        runs it, and handed over with the result it belongs to. The turn
        that goes on to answer this audio did not transcribe it and has
        no way to time what it is reusing, so a `heard` carrying nothing
        would be the one interruption an operator cannot see the ASR
        cost of. The ear travels the same way and for a sharper reason:
        the reply in flight can hand the conversation over while this
        call is awaited, so the far end cannot read it at all.

        In order: too little classified speech is a noise blip and is
        dropped; a reply still inside ASR was transcribing the head of
        the user's own sentence, so it is cancelled and its audio
        prepended, one reply answering the whole sentence; anything else
        pauses the outgoing frames and asks ASR, and only a non-empty
        transcript cancels. An empty one resumes the paced stream where
        it stopped, so a wrong pause costs one ASR latency, not a reply.

        Nothing is dropped for arriving early in the playback, and that
        absence is deliberate (#80). A refractory window used to sit
        between the merge and the confirmation, dropping an interruption
        that endpointed within a configured second of the reply's first
        delivered frame as the onset transient a device's echo
        cancellation lets through. Three facts say echo cannot reach
        this far: the speech floor above is checked first, so anything
        arriving here already carries at least half a second of
        classified speech; the primary board's playback trails the
        server by roughly 760 ms (the mic envelope correlates with the
        speaker envelope at r = 0.60 to 0.74 at that lag across three
        replies, and not at all at lag 0); and the window was measured
        from the first frame this server delivered, so a second of it
        was at most about 240 ms of sound in the room. Echo has no way
        to supply 500 ms of speech out of 240 ms of playback, and the
        field agreed: four suppressions in 48 h, every one of them a
        user finishing their own sentence. What the gate cost was the
        rest of that sentence, discarded unheard; what the fall-through
        costs is one ASR call in the same 48 h, which is the ladder's
        own tradeoff and no longer has an exception."""
        server = self._server
        if speech_ms < server.barge_in_min_speech_ms:
            self._events.emit(
                lambda: BargeInUnderFloor(
                    speech_ms=Whole(speech_ms),
                    floor_ms=Real(server.barge_in_min_speech_ms),
                )
            )
            return None
        if self._reply_pcm is not None:
            head = self._reply_pcm
            self._events.emit(lambda: BargeInMerged(speech_ms=Whole(speech_ms)))
            await self._reply.cancel_reply(ReplyOutcome.BARGED_IN)
            return head + pcm, None, None, None
        self._pause_output()
        failed: str | None = None
        # On the session's clock, which is the one the events are
        # stamped with, so the latency and the offsets around it are
        # comparable.
        started = self._events.now()
        measured: int | None = None
        ran_it: object | None = None
        try:
            # In the receive path on purpose: incoming frames buffer in
            # the socket for the duration, so ordering is unaffected.
            confirmation = await self._reply.confirm_transcript(pcm)
            result, ran_it = confirmation.result, confirmation.provider
            measured = round((self._events.now() - started) * 1000)
        except Exception as exc:
            # The class name, and nothing else: no `exc_info`, no
            # `str(exc)`. The confirmation runs inside the runtime's
            # `_watching("asr", ...)`, so a failure on the wire has
            # already been reported as `provider_failed` with the
            # stage, the provider and the host on it, sanitized at
            # that decision site. What is left for this line to add is
            # which utterance was dropped and what class of failure
            # dropped it. A traceback here would print the provider's
            # own message and the chain behind it onto the retained
            # log, which is what the observability ADR's no-leak
            # contract forbids (#183).
            failed = type(exc).__name__
        # Reported and cleaned up out here rather than in the arm, the
        # way the device edge raises `DeviceGone` (`device/session.py`)
        # and for the same reason read the other way round: inside the
        # arm, the provider's exception is the active one, so anything
        # that fails here (the resume, or the logging call itself)
        # escapes with it attached as `__context__` and carries the
        # message this line took care not to print out to whoever
        # catches it.
        if failed is not None:
            logger.error(
                "session %s: barge-in confirmation failed: %s", self.session_id, failed
            )
            self._resume_output()
            return None
        if not result.text.strip():
            self._events.emit(
                lambda: BargeInWithoutTranscript(speech_ms=Whole(speech_ms))
            )
            self._resume_output()
            return None
        self._events.emit(
            lambda: BargeIn(speech_ms=Whole(speech_ms), speaking_ms=self._speaking_ms())
        )
        await self._reply.cancel_reply(ReplyOutcome.BARGED_IN)
        # The pause belonged to the cancelled reply; the one about to
        # answer starts with the frames flowing. Resuming rather than
        # clearing by hand shifts a pacing clock the next agent leg
        # restarts from scratch anyway.
        self._resume_output()
        return pcm, result, measured, ran_it

    def _speaking_ms(self) -> Whole | Absent:
        """The barge_in event's speaking_ms: milliseconds from
        speaking_started to the cancel decision, absent when the reply
        had not yet spoken.

        Absent rather than null, and the two are different answers: a
        reply that had not spoken has no such interval, so the record
        carries no key rather than a key holding nothing."""
        if self._output.speaking_started_at() is None:
            return ABSENT
        elapsed = asyncio.get_running_loop().time() - self._output.speaking_started_at()
        return Whole(round(elapsed * 1000))

    def _trimmed_utterance(self) -> bytes:
        """The buffered utterance, cut down to the speech plus a short
        pre-roll. A continuously listening session buffers everything
        between utterances (the reply's own playback time, the pause
        while the user thinks), and the endpointer rightly ignores that
        silence, so it would otherwise all ride along to ASR (#14). The
        pre-roll keeps the first phoneme intact; the trailing silence
        the endpointer sat through stays, since it is bounded and ASR
        needs the end of the speech anyway."""
        speech_start = self.endpointer.speech_start() if self.endpointer is not None else None
        if speech_start is None:
            return bytes(self._utterance)
        pre_roll = int(self._server.utterance_pre_roll_ms / 1000 * PIPELINE_SAMPLE_RATE) * 2
        start = speech_start - self._utterance_dropped - pre_roll
        if start <= 0:
            return bytes(self._utterance)
        start -= start % 2  # never split a 16-bit sample
        return bytes(self._utterance[start:])

    def _pause_output(self) -> None:
        self._output_paused = True
        self._output.pause_output()

    def _resume_output(self) -> None:
        self._output_paused = False
        self._output.resume_output()
