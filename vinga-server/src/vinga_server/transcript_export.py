"""A closed session's turns, read back out of the store and put onto the
trace that session was exported under (#495).

Its callers stop having to know that a session's record has to be waited
for before it can be read, that a store read is paged, that a span
carries what was said, or that any of it happens on a thread. The
composition asks `build_transcript_export` for one object or for
nothing, hands it to the device session, and puts its bounded shutdown
on the exit stack; the session calls one method on it when a
conversation ends. The writer barrier, the bounded backlog, the worker,
the paging, the delivery answer and the outcome events are
implementation, and none of it is reachable from anywhere else.

**It is the third rung of the telemetry section's disclosure ladder,
and the second that sends content off this host.** `enabled` sends
metadata, `export_audio` sends a recording of a room, and this sends
what was said. It is behind a flag of its own that neither
`server.telemetry.enabled` nor `server.conversations.text` implies, the
flag's description says so in those words, and `server.local_only`
refuses to build it.

**It never touches the audio path.** Its one hook runs on the session
loop and does nothing but read a retained context and put a job on a
bounded queue; every wait, every database read and every request
happens on a daemon thread of this module's own. A failure is a warning
event and never a failed session: a conversation is worth more than a
record of it, and a record is worth more than a copy of it somewhere
else.

**The source is the store, post hoc, and the barrier is why this can be
said at all.** `ConversationStore.close_session` enqueues the close and
returns a handle; the writer settles it when the close's own
transaction commits, and because one writer thread consumes one FIFO
queue that answer means every earlier record of the session has been
resolved. So the worker waits on it before reading, and a `False`
answer is `unrecorded`: the turns may not be assumed readable. What it
then exports is exactly what the store HOLDS, which is correct because
the store is this feature's settled source of truth rather than the
conversation as it was spoken.

**A sibling of `capture_upload.py` and deliberately not folded into
it.** That module's vocabulary is hardlinks, media APIs and SDK
containment, and every one of its hard-won properties (staging
transactionality, the classification off typed errors, a second
credential family) is machinery a transcript does not need; folded into
`telemetry.py` instead, this would put a database engine and a writer
acknowledgement into a module whose rule is that it consumes emissions
and never stores. What the two post-close surfaces genuinely share is
already shared where it belongs, in the retained context and the
after-the-close fold. The worker-and-bounded-queue shape repeats as a
pattern rather than as code: extracting it would be a layer forwarding
its arguments.

**A page at a time, in both directions.** Nothing bounds a session's
turn count, so the worker alternates one keyset page read with one
bounded export of that page's spans. An arbitrarily long session
therefore costs bounded memory, a bounded database result and a bounded
request, however many pages it takes, and a page that fails to deliver
ends the job: the pages already delivered stand, and the failure event
beside them on the trace is what tells a reader the transcript stops
there.
"""

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from vinga_server.config import ConfigError
from vinga_server.config.models import DatabaseConfig, ServerConfig
from vinga_server.conversations.records import Acknowledgement
from vinga_server.conversations.threads import Reads, Unreadable
from vinga_server.egress import EgressRefusal, check_feature
from vinga_server.events import ServerEvents
from vinga_server.events.catalog import TranscriptExportFailed, TranscriptsExported
from vinga_server.events.values import (
    Count,
    SessionId,
    TranscriptExportFailure,
    Whole,
)
from vinga_server.quieting import Lease
from vinga_server.telemetry import Delivery, Telemetry, TranscriptTurn, quiet_the_sdk

logger = logging.getLogger(__name__)
events = ServerEvents(__name__)

# Where the switch is written, which is what every refusal below names.
# One spelling, because a sentence an operator is told to edit by has to
# be the path they will find.
TRANSCRIPTS_KEY = "server.telemetry.export_transcripts"

# And the two keys that decide whether there is anything to export at
# all, named in the one line this says out loud.
RECORDING_KEY = "server.conversations.enabled"
TEXT_KEY = "server.conversations.text"

# How many turns one page is, which is the bound on three things at
# once: the database result, the spans held in memory, and the protobuf
# payload of one request. Nothing about a session bounds its turn count
# (`max_session_s` bounds elapsed time, not turns), so this is the only
# bound there is. A single turn's stored text has no ceiling of its own
# here: bounding what a conversation may STORE is the store's question,
# and the page is what keeps any one request proportionate.
TRANSCRIPT_BATCH_TURNS = 256

# How long a job waits for the store to say the session's record is
# settled. The request-timeout posture, and deliberately loose: the
# writer's own durability wait is far shorter, so a bound this wide
# fires only when the store is genuinely wedged, and a wedged store for
# minutes is a louder problem than a late transcript.
ACKNOWLEDGEMENT_TIMEOUT_S = 30.0

# How long the lifespan waits for the worker on the way out, the
# exporter's own bound and for the same reason: a backend that has
# stopped answering must not hold a redeploy open. What a timeout costs
# is one session's transcript export, and the turns themselves stay in
# the store, re-exportable by any surface that comes later.
SHUTDOWN_TIMEOUT_S = 5.0

# How often a waiting worker looks up to see whether it has been asked
# to stop. Short enough not to lengthen a shutdown measurably, long
# enough that an idle server is not spinning. It is the slice the
# acknowledgement wait is made of, which is what makes a job sitting in
# that wait interruptible rather than merely joinable.
POLL_S = 0.05


def build_transcript_export(
    config: ServerConfig,
    *,
    telemetry: Telemetry | None,
    database: DatabaseConfig,
    local_only: bool = False,
    batch_turns: int = TRANSCRIPT_BATCH_TURNS,
    acknowledgement_timeout_s: float = ACKNOWLEDGEMENT_TIMEOUT_S,
    shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
) -> "TranscriptExport | None":
    """One server's transcript exporter, or nothing at all.

    It takes the whole server section rather than the telemetry one,
    because the first thing it has to resolve is recording, and the
    order of the decisions here is the contract:

    1. **Recording first.** With `server.conversations` absent, off, or
       storing no text, this answers None and none of the checks below
       run, so a deployment that records nothing boots identically
       whatever the telemetry section or `local_only` say. The flag on
       with nothing recorded is a no-op rather than a misconfiguration,
       which is the issue's own rule: an operator mid-toggle is not
       misconfigured. It is said out loud exactly when there is
       something to say, as one value-free line naming the two keys,
       because a switch that does nothing is otherwise a silence
       somebody has to debug. With the flag off as well there is no
       no-op to explain and nothing is said.
    2. **The flag.** Off, or a telemetry section that is absent
       altogether, answers None with nothing said. That is the default,
       and the default costs a server nothing: no object, no thread, no
       callback, no read.
    3. **Telemetry.** A transcript is written onto the trace its session
       was exported under, so the flag on with `enabled` off is refused.
       Here rather than as a model validator, and for the reason
       `models.py` records for its sibling: a validator raises while the
       file is being PARSED, which is in front of everything a
       composition does, and the recording-first no-op above could then
       never run.
    4. **Egress.** Asked of `egress.py` before any construction and any
       thread, so under `server.local_only` nothing is built.

    There is no extra step and no credential step, which is the whole of
    what this surface costs less than the capture uploader: a transcript
    travels as OTLP spans over the transport the traces already use, so
    there is no second distribution to install and no second credential
    family to point at the same deployment.

    Each refusal is a `ConfigError` with a fixed value-free sentence,
    raised outside the handler that read it so nothing is chained.

    `batch_turns`, `acknowledgement_timeout_s` and `shutdown_timeout_s`
    are the test seam and nothing else: a lane shortens a wait so a case
    about what happens after it does not take half a minute to reach, or
    narrows the page so an oversized session is four turns rather than a
    thousand. A caller that passes none of them gets the real bounds.
    """
    conversations = config.conversations
    telemetry_section = config.telemetry
    exporting = telemetry_section is not None and telemetry_section.export_transcripts
    if conversations is None or not conversations.enabled or not conversations.text:
        if exporting:
            logger.info(
                "%s is on and no conversation text is being recorded, so no "
                "transcripts will be exported; switch %s and %s on to record what "
                "is said",
                TRANSCRIPTS_KEY,
                RECORDING_KEY,
                TEXT_KEY,
            )
        return None
    if not exporting:
        return None
    if not telemetry_section.enabled:
        raise ConfigError(TRANSCRIPTS_NEED_TELEMETRY)
    if telemetry is None:
        # Unreachable through the configuration, since an enabled
        # telemetry section is what builds an exporter, and asserted
        # rather than assumed: a caller composing this by hand with no
        # exporter would otherwise get a worker that answered `no_trace`
        # to every session it was ever given.
        raise ConfigError(TRANSCRIPTS_NEED_AN_EXPORTER)

    refusal = _egress_refusal(local_only)
    if refusal is not None:
        raise ConfigError(refusal)

    return TranscriptExport(
        telemetry=telemetry,
        reads=Reads(database),
        backlog=config.limits.max_sessions,
        batch_turns=batch_turns,
        acknowledgement_timeout_s=acknowledgement_timeout_s,
        shutdown_timeout_s=shutdown_timeout_s,
    )


# What an export with no trace to write onto is refused with. A
# transcript is an observation on the trace its session was exported
# under; with no exporter there is no trace, and turns written nowhere
# would be the gap this surface exists to close wearing a success.
#
# It reads like a cross-field configuration rule and it is one, and it
# is nonetheless here rather than on a model, for the reason the
# builder's step 3 gives. What the generated reference publishes about
# it is the `export_transcripts` field's own prose rather than a row in
# the cross-field section.
TRANSCRIPTS_NEED_TELEMETRY = (
    "telemetry.export_transcripts is on with telemetry.enabled off; a transcript "
    "is written onto the trace its session was exported under, and there is no "
    "trace to write onto, so switch telemetry.enabled on or "
    "telemetry.export_transcripts off"
)

# And the one refusal here that an operator cannot reach by editing a
# file, kept as a sentence anyway: it is what a composition built by
# hand gets instead of an exporter that would answer `no_trace` to every
# session it was ever given.
TRANSCRIPTS_NEED_AN_EXPORTER = (
    f"{TRANSCRIPTS_KEY} is on and no exporter was built, so no session has a "
    f"trace to be written onto; switch server.telemetry.enabled on"
)


def _egress_refusal(local_only: bool) -> str | None:
    """What the egress rule says about a transcript export, or nothing.

    Asked before any construction and any thread, which is the caller's
    half of `check_feature`'s contract and the only way the refusal can
    honestly say nothing was built. The sentence is the egress module's
    own, and only the sentence crosses back: the exception type belongs
    to whichever surface asked, which here is `ConfigError`.
    """
    try:
        check_feature(TRANSCRIPTS_KEY, egress=True, local_only=local_only)
    except EgressRefusal as refusal:
        return str(refusal)
    return None


@dataclass(frozen=True)
class _Job:
    """One closed session, waiting for a worker.

    The context is captured at ADMISSION and carried here rather than
    looked up at export, which is what makes `no_trace` an answer about
    the moment the session closed: the retention is bounded and
    oldest-evicted, so a job queued behind a slow worker would otherwise
    watch its own trace age out and report a failure that never
    happened.

    The acknowledgement is the store's barrier for this session, and it
    is the reason a job can be admitted the instant a session closes and
    still read the session's turns when it is reached.
    """

    session: str
    context: Any
    recorded: Acknowledgement


class TranscriptExport:
    """One server's transcript exporter, as the thing its callers hold.

    Built by `build_transcript_export`, handed to the device session,
    shut down by the lifespan. What a caller may do with it is tell it a
    session closed, and shut it down.
    """

    def __init__(
        self,
        *,
        telemetry: Telemetry,
        reads: Reads,
        backlog: int,
        batch_turns: int = TRANSCRIPT_BATCH_TURNS,
        acknowledgement_timeout_s: float = ACKNOWLEDGEMENT_TIMEOUT_S,
        shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
    ) -> None:
        self._telemetry = telemetry
        self._reads = reads
        # A bounded best-effort backlog, sized from the session limit,
        # and the bound is honest about what it cannot promise. A
        # routine shutdown closes every live session at once, and a
        # healthy redeploy of a full server must not deterministically
        # drop any of THOSE; jobs from earlier sessions may still be
        # waiting when that drain begins, and a backlog that deep means
        # the store or the backend has been slow for a while. A job the
        # bound turns away is dropped with its warning event, which is
        # the drop stated rather than hidden.
        self._queue: queue.Queue[_Job] = queue.Queue(maxsize=max(1, backlog))
        self._batch_turns = max(1, batch_turns)
        self._acknowledgement_timeout_s = acknowledgement_timeout_s
        self._shutdown_timeout_s = shutdown_timeout_s
        # The worker, started at the first job rather than at build, so
        # a server whose sessions never close pays for no thread. Under
        # a lock because two sessions closing at once would otherwise
        # start two.
        self._starting = threading.Lock()
        self._worker: threading.Thread | None = None
        self._stopping = threading.Event()
        # This exporter's claim on the SDK's silence, taken by the
        # worker before it does anything and given back only when the
        # worker has genuinely stopped, which is the asymmetry
        # `Telemetry.shutdown` explains: a bounded wait that expired
        # leaves work in flight, and what that work is about to log is
        # the endpoint it could not reach. The claim is this exporter's
        # and the quieting is the process's, which is why one is a field
        # here and the other is telemetry's module-level one.
        self._quieted: Lease | None = None

    # --- the hook ------------------------------------------------------

    def session_closed(self, session: str, recorded: Acknowledgement | None) -> None:
        """A session ended. Queue its transcript export.

        Called from the device session's own close ordering, straight
        after the capture hook and with the handle `close_session`
        returned. Both arguments come from that one moment on purpose:
        the handle is the barrier this session's read waits on, and the
        retained context is read HERE so that eviction between now and
        the worker cannot turn a healthy export into `no_trace`.

        A session with nothing recorded is silence, which is most of
        what this sees in a deployment that only sometimes records: no
        handle means the store was never told about this session, so
        there is nothing to wait for and nothing to read.

        It does no work. A read of a map and a put on a queue, on the
        session loop, which is the whole of what this costs a close.
        """
        if recorded is None:
            return
        if self._stopping.is_set():
            # A session closing behind a shutdown, which a drain
            # produces: no worker will start for it, so the drop is said
            # here rather than left as a job nothing will ever answer.
            self._failed(session, TranscriptExportFailure.DROPPED)
            return
        context = self._telemetry.retained_context(session)
        if context is None:
            # Decided here and never at export, which is what the
            # captured context above is for: a session this exporter
            # never saw, or one whose trace had already aged out by the
            # time it closed, has nothing to be written onto.
            self._failed(session, TranscriptExportFailure.NO_TRACE)
            return
        self._start()
        try:
            self._queue.put_nowait(
                _Job(session=session, context=context, recorded=recorded)
            )
        except queue.Full:
            self._failed(session, TranscriptExportFailure.DROPPED)

    # --- the way out ---------------------------------------------------

    async def shutdown(self) -> None:
        """Interrupt the worker and let it go, bounded.

        Off the loop, because the wait is a thread join, and bounded,
        because a store or a backend that has stopped answering must not
        hold a redeploy open.

        Interrupted rather than merely joined, and that is this method's
        whole design. A job may lawfully be sitting thirty seconds deep
        in an acknowledgement wait when a shutdown begins, so the stop
        flag is what that wait watches, in short slices: the job in
        flight ends as `dropped`, everything still queued is answered
        the same way, and all of it is said while the store, the event
        tap and telemetry are still up. That ordering is the
        composition's half of the contract, which pushes this shutdown
        onto the exit stack LAST so it unwinds FIRST.

        The wait is bounded and the QUIETING IS NOT, the exporter's own
        asymmetry: what an expired wait leaves in flight is a request
        that is going to fail and log the endpoint it failed against. So
        the worker gives its lease back from its own `finally`, when the
        work is genuinely over.
        """
        self._stopping.set()
        worker = self._worker
        if worker is None:
            # Nothing ever started, so nothing is queued behind it
            # either: `session_closed` starts the worker before it puts.
            return
        await asyncio.to_thread(worker.join, self._shutdown_timeout_s)
        if worker.is_alive():
            # A plain sentence and nothing about the far side: what
            # could not be reached is the store or the endpoint, and
            # neither is a string this module writes down.
            logger.warning(
                "the transcript exporter did not finish within %.0f s and was "
                "left behind; the turns it was exporting are still in the store",
                self._shutdown_timeout_s,
            )

    # --- the worker ----------------------------------------------------

    def _start(self) -> None:
        """The worker, started at the first job and never again.

        A daemon thread of its own rather than `asyncio.to_thread`, the
        exporter's reasoning: the default executor's threads are joined
        by an `atexit` hook, so a wedged export on one of them would
        hold the process open exactly as long as the far side felt like
        holding it, which is what a bounded shutdown exists to prevent.
        """
        with self._starting:
            if self._worker is not None or self._stopping.is_set():
                return
            self._worker = threading.Thread(
                target=self._run, name="vinga-transcript-export", daemon=True
            )
            self._worker.start()

    def _run(self) -> None:
        """Every queued job, until a shutdown ends it.

        The lease is taken here, before anything is read or constructed,
        and given back in the `finally`, which is the moment the work is
        genuinely over rather than the moment somebody stopped waiting
        for it.
        """
        self._quieted = quiet_the_sdk()
        try:
            while not self._stopping.is_set():
                try:
                    job = self._queue.get(timeout=POLL_S)
                except queue.Empty:
                    continue
                self._attempt(job)
            self._drain()
        finally:
            lease, self._quieted = self._quieted, None
            if lease is not None:
                lease.release()

    def _drain(self) -> None:
        """Whatever a shutdown left queued, answered rather than left
        silent.

        Nothing is persisted, so there is no sweep at the next boot to
        find these: the event here is the whole of the ledger, and a
        transcript nobody exported is a fact a reader is entitled to,
        since the turns are still in the store and can still be read by
        somebody who knows to look.
        """
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                return
            self._failed(job.session, TranscriptExportFailure.DROPPED)

    def _attempt(self, job: _Job) -> None:
        """One session, from the barrier it waits on to the event it
        produces.

        Never raises: a worker that died of one job would take every
        session after it, and what this surface promises is that a
        failure is an event.
        """
        began = time.monotonic()
        try:
            reason, turns = self._export(job)
        except Exception:  # noqa: BLE001 - a worker never dies of a job
            # Deliberately unbound, for the reason the events package
            # gives where it does the same: what is never looked at
            # cannot leak by accident later.
            reason, turns = TranscriptExportFailure.UNDELIVERED, 0
        if reason is not None:
            self._failed(job.session, reason)
            return
        if turns == 0:
            # A session whose readable turns number zero says nothing.
            # A trail entry for an empty export would be noise a reader
            # filters out, and the flag's own boot line already says why
            # nothing will ever export when that is config's doing.
            return
        elapsed = int((time.monotonic() - began) * 1000)
        events.emit(
            lambda: TranscriptsExported(
                session=SessionId(job.session),
                turns=Count(turns),
                elapsed_ms=Whole(elapsed),
            )
        )

    def _export(self, job: _Job) -> tuple[TranscriptExportFailure | None, int]:
        """The export itself: the barrier, then a page read alternating
        with a bounded delivery, until the session runs out.

        The ordinal is carried across pages rather than derived inside
        one, which is the only place it can be: it counts the turns this
        export actually wrote, in `id`-ascending order, so a session's
        first exported turn is index 1 whatever the store's row ids
        happen to be and whatever the thread held before this session.

        A page that fails to deliver ends the job. The pages in front of
        it stand, deliberately: a reader meets the leading turns and the
        failure event on the same trace, and where the transcript stops
        is the highest index they can see, which is why no count rides
        the event.
        """
        if not self._recorded(job):
            return self._unrecorded(), 0
        cursor: int | None = None
        ordinal = 0
        while True:
            page = self._reads.transcript_rows(
                job.session, after=cursor, limit=self._batch_turns
            )
            if isinstance(page, Unreadable):
                return TranscriptExportFailure.UNREADABLE, ordinal
            if not page:
                return None, ordinal
            cursor = int(page[-1]["id"])
            turns, ordinal = _turns(page, ordinal)
            answer = self._telemetry.export_transcript(
                job.session, job.context, turns
            )
            if answer is Delivery.STOPPED:
                return TranscriptExportFailure.DROPPED, ordinal
            if answer is Delivery.UNDELIVERED:
                return TranscriptExportFailure.UNDELIVERED, ordinal
            if len(page) < self._batch_turns:
                # A short page is the end of the session, and asking for
                # the page after it would be a round trip to learn what
                # this one already said.
                return None, ordinal

    def _recorded(self, job: _Job) -> bool:
        """Whether the store says this session's record is settled,
        waited for in slices so a shutdown can end the wait.

        The slices are the whole of what makes this interruptible: a
        single bounded `wait` would hold the worker for the full budget
        with a stop flag set beside it, and the job would then be
        answered after the tap it has to speak through came off.

        `settled` is asked as well as `wait`, because `wait` answers
        false for "not yet" and for "no" alike: without that question a
        record the writer already refused would cost this its whole
        budget, every time, which is exactly what a stopped store
        produces for every session a drain closes.
        """
        deadline = time.monotonic() + self._acknowledgement_timeout_s
        while not self._stopping.is_set():
            if job.recorded.wait(POLL_S):
                return True
            if job.recorded.settled():
                return False
            if time.monotonic() >= deadline:
                return False
        return False

    def _unrecorded(self) -> TranscriptExportFailure:
        """Which failure an unsettled record is, which depends on why the
        wait ended.

        A shutdown ending it is `dropped`, because nothing was learned
        about the store: the job was ended, not answered. Anything else
        is `unrecorded`, the acknowledgement's own three answers that it
        deliberately does not tell apart.
        """
        if self._stopping.is_set():
            return TranscriptExportFailure.DROPPED
        return TranscriptExportFailure.UNRECORDED

    # --- what it says --------------------------------------------------

    def _failed(self, session: str, reason: TranscriptExportFailure) -> None:
        events.emit(
            lambda: TranscriptExportFailed(
                session=SessionId(session), reason=reason
            )
        )


def _turns(
    page: list[dict[str, Any]], ordinal: int
) -> tuple[list[TranscriptTurn], int]:
    """One page's rows as the turns a span is made from, and the ordinal
    the next page carries on from.

    A turn whose text halves are both null contributes no turn and
    consumes no ordinal: it was recorded before the text switch went on,
    or nothing was said and nothing was answered, and a span with no
    input and no output would be an observation carrying nothing at all.
    """
    turns = []
    for row in page:
        if row["heard"] is None and row["reply"] is None:
            continue
        ordinal += 1
        turns.append(
            TranscriptTurn(
                index=ordinal,
                id=int(row["id"]),
                t_ms=int(row["t_ms"]),
                agent=row["agent"],
                heard=row["heard"],
                reply=row["reply"],
                legs=row["legs"],
            )
        )
    return turns, ordinal
