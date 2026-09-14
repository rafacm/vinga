"""What a session was about to send a model, staged as it goes and put
onto that session's trace once it has ended (#502).

Its callers stop having to know that an assembled request is bounded,
that it is held per session and dropped at the close whatever happened,
that content never reaches the emit fold, and how a bounded OTLP
delivery reports its own failure; a caller hands over what it is about
to send a model, and asks nothing else. The composition asks
`build_llm_input_export` for one object or for nothing, hands it to the
runtime and to the device session, and puts its bounded shutdown on the
exit stack; the reply path tells it about each round and the session
tells it when the conversation ended. The byte bound, the drop
accounting, the bounded backlog, the worker, the delivery answer and
the outcome events are implementation, and none of it is reachable from
anywhere else.

**It is the fourth rung of the telemetry section's disclosure ladder,
and the widest.** `enabled` sends metadata, `export_audio` sends a
recording of a room, `export_transcripts` sends what was said, and this
sends what the model was given, which CONTAINS what was said. It is
behind a flag of its own that nothing above it implies, the flag's
description says so in those words, and a narrower `server.data_boundary`
refuses to build it.

**A sibling of `transcript_export.py` and deliberately not folded into
it.** That module reads the conversation store post hoc, which is a
source that exists whether or not anybody is watching. An assembled
request has no store behind it and this plan builds none: a session
assembles a request because it is about to make it, so this module owns
a LIVE stage as well as a post-close delivery, which is a second
responsibility on a second clock. The worker-and-bounded-queue shape
repeats as a pattern rather than as code, the rule its sibling states:
extracting it would be a layer forwarding its arguments.

**The local surface is the session's own working state, and the
retention answer is exact.** What is staged exists for the session, then
in the delivery job until it is delivered or dropped, and nowhere after
that. A process that dies with a job queued loses it, with no ledger to
recover from, which is unlike either class above: the capture
directory's files and the conversation store's rows outlive the process
that staged them. What that costs is bounded, and is why the answer is
acceptable: a lost export is a missing observation and never a lost
conversation, because what was said is in the store.

**The stage is bounded in bytes, and the bound is the design rather
than a guard.** A staged request carries the history, the tool schemas,
the arguments and the results, none of which has a size this server
chose, and a conversation grows as it goes, so a count of entries would
bound cardinality and not memory. There are two ceilings, both measured
on the serialized form that would actually be exported so the number
bounds what memory holds rather than a proxy for it: one request larger
than `MAX_REQUEST_BYTES` is dropped WHOLE at staging, never truncated,
because a shortened request is not the request the model was given and a
class whose whole point is fidelity must not ship an approximation of
itself; and past `SESSION_BUDGET_BYTES` whole requests go oldest first.
`MAX_STAGED_ROUNDS` sits behind both as a cheap entry guard. Both
absences are counted and the two reasons are told apart on the export's
own event, so a reader holding a partial export learns that it is
partial from the trace rather than by counting.

**One observation is one logical ROUND, not one provider attempt**, and
that is a finding rather than a preference. The first-token watchdog
retries by calling `make_stream()` a second time, over arguments fixed
before the first attempt, so a retry sends byte-identical content; two
observations would be the same bytes twice, and the fact a reader wants
about a retry is already on the trace as `llm_retry`. The staging call
therefore sits where the round is assembled and not where it is sent.

**It never touches the audio path.** Staging is a render and an append
on the session loop, the hand-over is a dictionary pop and a put on a
bounded queue, and every request happens on a daemon thread of this
module's own. A failure is a warning event and never a failed session.
"""

import asyncio
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from vinga_server.boundary import BoundaryRefusal, Reach, check_feature
from vinga_server.config import ConfigError
from vinga_server.config.models import ServerConfig
from vinga_server.events import ServerEvents
from vinga_server.events.catalog import LlmInputExported, LlmInputExportFailed
from vinga_server.events.values import (
    Count,
    LlmInputExportFailure,
    LlmPurpose,
    SessionId,
    Whole,
)
from vinga_server.providers.base import ToolCall, ToolDef, ToolResult, Turn
from vinga_server.quieting import Lease
from vinga_server.telemetry import Delivery, LlmInputRound, Telemetry, quiet_the_sdk

logger = logging.getLogger(__name__)
events = ServerEvents(__name__)

# Where the switch is written, which is what every refusal below names.
# One spelling, because a sentence an operator is told to edit by has to
# be the path they will find.
LLM_INPUT_KEY = "server.telemetry.export_llm_input"

# The two words that say which call shape assembled a request, and the
# whole of the vocabulary: a reply round is one the user is waiting
# through, a recap round is the summarization a resume makes before
# anybody has spoken. They are this module's own, which is why the two
# staging verbs below are two verbs rather than one taking a string: a
# caller says what it is doing, and never how this spells it.
REPLY = LlmPurpose.REPLY
RECAP = LlmPurpose.RECAP

# The per-request ceiling, in bytes of the serialized request. A single
# assembled request larger than this is dropped whole and counted.
#
# A quarter of a megabyte because that is far above any request a
# conversation with a device in a room produces and far below anything
# that would matter to a process: a long history with a dozen tool
# schemas renders to tens of kilobytes, so what this catches is a tool
# that answered with a file, a schema somebody generated, or a history
# that grew past what a model could have read anyway.
MAX_REQUEST_BYTES = 256 * 1024

# And the per-session budget, which is what actually does the bounding.
# Over it, whole requests go oldest first, which is the posture
# `PENDING_CAPTURES` and `RETAINED_TRACES` already take in `telemetry.py`.
#
# Four times the ceiling above rather than a number of its own: what a
# session may hold is a handful of the largest requests it is allowed to
# stage at all, and the two moving independently would be two numbers to
# reason about where the relationship is the fact.
SESSION_BUDGET_BYTES = 4 * MAX_REQUEST_BYTES

# The entry guard behind both, on the number of staged rounds rather
# than on their size. It is deliberately NOT the bound: a count cannot
# bound memory here, for the reason the module docstring gives. What it
# buys is that a session making thousands of tiny rounds holds a bounded
# LIST as well as bounded bytes.
MAX_STAGED_ROUNDS = 64

# How long the lifespan waits for the worker on the way out, the
# transcript exporter's own bound and for the same reason: a backend
# that has stopped answering must not hold a redeploy open. What a
# timeout costs here is more than it costs there, and is stated rather
# than softened: the requests are in memory and nowhere else, so a job
# left behind is an export nobody can make again.
SHUTDOWN_TIMEOUT_S = 5.0

# How often a waiting worker looks up to see whether it has been asked
# to stop. Short enough not to lengthen a shutdown measurably, long
# enough that an idle server is not spinning.
POLL_S = 0.05


def build_llm_input_export(
    config: ServerConfig,
    *,
    telemetry: Telemetry | None,
    boundary: Reach | None = None,
    max_request_bytes: int = MAX_REQUEST_BYTES,
    session_budget_bytes: int = SESSION_BUDGET_BYTES,
    max_rounds: int = MAX_STAGED_ROUNDS,
    shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
) -> "LlmInputExport | None":
    """One server's LLM input exporter, or nothing at all.

    It takes the whole server section for the reason its siblings do,
    and the order of the decisions here is the contract:

    1. **The flag.** Off, or a telemetry section that is absent
       altogether, answers None with nothing said. That is the default,
       and the default costs a server nothing: no object, no thread, no
       callback, and above all no render, so a deployment that has not
       asked for this never assembles a copy of anything.
    2. **Telemetry.** A request is written onto a trace this server
       exported, so the flag on with `enabled` off is refused. Here
       rather than as a model validator, for the reason `models.py`
       records for its siblings: a validator raises while the file is
       being PARSED, which is in front of everything a composition does.
    3. **The data boundary.** Asked of `boundary.py` before any
       construction and any thread, so under a boundary narrower than
       the telemetry section's declared reach nothing is built.

    There is no recording-first step, and its absence is the whole
    difference between this builder and the two beside it. The family
    rule's no-op arm applies where a class has a local surface with a
    switch of its own, and this class has none: a session assembles a
    request whatever `server.conversations` and `server.capture` say, so
    there is no second switch that could be off and no no-op to explain.

    There is no extra and no credential step either, which is what this
    surface costs less than the capture uploader: a request travels as
    OTLP spans over the transport the traces already use.

    Each refusal is a `ConfigError` with a fixed value-free sentence,
    raised outside the handler that read it so nothing is chained.

    The four bounds are the test seam and nothing else: a lane shrinks a
    ceiling so an oversized request is a sentence rather than a quarter
    of a megabyte, or shortens a wait so a case about what happens after
    it does not take five seconds to reach. A caller that passes none of
    them gets the real bounds.
    """
    section = config.telemetry
    if section is None or not section.export_llm_input:
        return None
    if not section.enabled:
        raise ConfigError(LLM_INPUT_NEEDS_TELEMETRY)
    if telemetry is None:
        # Unreachable through the configuration, since an enabled
        # telemetry section is what builds an exporter, and asserted
        # rather than assumed: a caller composing this by hand with no
        # exporter would otherwise get a worker that answered `no_trace`
        # to every session it was ever given, having staged every
        # request those sessions made.
        raise ConfigError(LLM_INPUT_NEEDS_AN_EXPORTER)

    refusal = _boundary_refusal(section.reach, boundary)
    if refusal is not None:
        raise ConfigError(refusal)

    return LlmInputExport(
        telemetry=telemetry,
        backlog=config.limits.max_sessions,
        max_request_bytes=max_request_bytes,
        session_budget_bytes=session_budget_bytes,
        max_rounds=max_rounds,
        shutdown_timeout_s=shutdown_timeout_s,
    )


# What an export with no trace to write onto is refused with. An
# assembled request is an observation on a trace this server exported;
# with no exporter there is no trace, and requests staged and written
# nowhere would be the widest content class in this repository held in
# memory for nothing.
#
# It reads like a cross-field configuration rule and it is one, and it
# is nonetheless here rather than on a model, for the reason the
# builder's step 2 gives. What the generated reference publishes about
# it is the `export_llm_input` field's own prose rather than a row in
# the cross-field section.
LLM_INPUT_NEEDS_TELEMETRY = (
    "telemetry.export_llm_input is on with telemetry.enabled off; an assembled "
    "request is written onto a trace this server exported, and there is no trace "
    "to write onto, so switch telemetry.enabled on or "
    "telemetry.export_llm_input off"
)

# And the one refusal here that an operator cannot reach by editing a
# file, kept as a sentence anyway: it is what a composition built by
# hand gets instead of an exporter that would stage every request every
# session made and answer `no_trace` to all of them.
LLM_INPUT_NEEDS_AN_EXPORTER = (
    f"{LLM_INPUT_KEY} is on and no exporter was built, so no session has a "
    f"trace to be written onto; switch server.telemetry.enabled on"
)


def _boundary_refusal(reach: Reach, boundary: Reach | None) -> str | None:
    """What the data boundary says about an LLM input export, or
    nothing.

    Asked before any construction and any thread, which is the caller's
    half of `check_feature`'s contract and the only way the refusal can
    honestly say nothing was built. The sentence is the boundary
    module's own, and only the sentence crosses back: the exception type
    belongs to whichever surface asked, which here is `ConfigError`.

    The reach is the telemetry section's own, for the reason its
    siblings' is: the requests travel over the transport the traces use,
    whose endpoint this server hands to the SDK without reading, so what
    the section declares about that destination is what there is to go
    on (#502).
    """
    try:
        check_feature(LLM_INPUT_KEY, reach, boundary)
    except BoundaryRefusal as refusal:
        return str(refusal)
    return None


@dataclass(frozen=True)
class _Staged:
    """One assembled request, rendered and weighed.

    The size is kept beside the round rather than recomputed, because
    the budget is enforced by subtraction as entries leave: recomputing
    it per eviction would encode the same fact twice, and the two could
    disagree the moment the rendering changed.
    """

    round: LlmInputRound
    size: int


@dataclass
class _Stage:
    """What one live session is holding, and what it has already lost.

    `index` counts every round the session ASSEMBLED rather than every
    round still held, which is what makes the ordinal on a surviving
    observation honest about where it sat in the conversation: a reader
    looking at rounds 1, 2 and 5 can see that two are missing, and the
    event beside them says why.
    """

    rounds: list[_Staged] = field(default_factory=list)
    held: int = 0
    index: int = 0
    oversized: int = 0
    over_budget: int = 0
    # And the third absence, which is neither of the bound's: a round
    # this server could not render at all. Counted here so the close has
    # something to report rather than a silence somebody would have to
    # infer from a gap in the ordinals.
    unrenderable: int = 0

    def anything(self) -> bool:
        """Whether this session has anything to say at its close, which
        is a round that survived or an absence worth reporting.

        All three absences, and the third is the one this question was
        getting wrong: a session whose every round failed to render used
        to answer False here, so the close said nothing at all and the
        rounds were not merely unexplained but unreported.
        """
        return bool(
            self.rounds or self.oversized or self.over_budget or self.unrenderable
        )


@dataclass(frozen=True)
class _Job:
    """One closed session's staged rounds, waiting for a worker.

    The context is captured at ADMISSION and carried here rather than
    looked up at export, which is what makes `no_trace` an answer about
    the moment the session closed: the retention is bounded and
    oldest-evicted, so a job queued behind a slow worker would otherwise
    watch its own trace age out and report a failure that never
    happened.

    The rounds are a tuple because the stage they came from is gone: the
    hand-over pops it, so nothing can append to what this job is
    carrying and this is the only reference left to any of it.
    """

    session: str
    context: Any
    rounds: tuple[LlmInputRound, ...]
    oversized: int
    over_budget: int
    unrenderable: int


class LlmInputExport:
    """One server's LLM input exporter, as the thing its callers hold.

    Built by `build_llm_input_export`, handed to the runtime factory and
    to the device session, shut down by the lifespan. What a caller may
    do with it is tell it about a round it is about to send, tell it a
    session closed, and shut it down.
    """

    def __init__(
        self,
        *,
        telemetry: Telemetry,
        backlog: int,
        max_request_bytes: int = MAX_REQUEST_BYTES,
        session_budget_bytes: int = SESSION_BUDGET_BYTES,
        max_rounds: int = MAX_STAGED_ROUNDS,
        shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
    ) -> None:
        self._telemetry = telemetry
        # What every live session is holding, by session id. Written and
        # read on the session loop alone, which is why it needs no lock:
        # staging happens inside a reply and the hand-over inside the
        # same session's close, and the worker below is handed a tuple
        # at admission and never sees this map at all.
        self._staged: dict[str, _Stage] = {}
        self._max_request_bytes = max(1, max_request_bytes)
        self._session_budget_bytes = max(1, session_budget_bytes)
        self._max_rounds = max(1, max_rounds)
        # A bounded best-effort backlog, sized from the session limit,
        # and the bound is honest about what it cannot promise, the way
        # the transcript exporter's is: a routine shutdown closes every
        # live session at once, and a healthy redeploy of a full server
        # must not deterministically drop any of those. A job the bound
        # turns away is dropped with its warning event, which is the
        # drop stated rather than hidden.
        self._queue: queue.Queue[_Job] = queue.Queue(maxsize=max(1, backlog))
        self._shutdown_timeout_s = shutdown_timeout_s
        # The worker, started at the first job rather than at build, so
        # a server whose sessions never close pays for no thread.
        #
        # The lock is admission's rather than the start's, one name and
        # one scope for what would otherwise be two: two sessions
        # closing at once must not start two workers, AND a job must not
        # be admitted across a shutdown that has already decided there
        # was no worker to wait for. The teardown takes the same lock
        # before it raises the flag.
        self._admission = threading.Lock()
        self._worker: threading.Thread | None = None
        self._stopping = threading.Event()
        # This exporter's claim on the SDK's silence, taken by the
        # worker before it does anything and given back only when the
        # worker has genuinely stopped, which is the asymmetry
        # `Telemetry.shutdown` explains: a bounded wait that expired
        # leaves work in flight, and what that work is about to log is
        # the endpoint it could not reach.
        self._quieted: Lease | None = None

    # --- the stage -----------------------------------------------------

    def stage_reply(
        self,
        session: str,
        *,
        invocation: str,
        agent: str | None,
        system: str,
        turns: "list[Turn]",
        tools: "list[ToolDef]",
        choice: str,
    ) -> None:
        """One round of a reply, as the model is about to be given it.

        Called once per logical round, where the round is assembled and
        not where it is sent, which is what makes a first-token
        watchdog's retry one observation rather than two: the retry
        re-sends content fixed before the first attempt.
        """
        self._stage(session, invocation, REPLY, agent, system, turns, tools, choice)

    def stage_recap(
        self,
        session: str,
        *,
        invocation: str,
        agent: str | None,
        system: str,
        turns: "list[Turn]",
        tools: "list[ToolDef]",
        choice: str,
    ) -> None:
        """And one summarization round, which is the other call shape.

        A verb of its own rather than an argument, so a caller says what
        it is doing and never learns how this spells it. Both shapes are
        staged because both are things a model was given, and a reader
        asking what it saw wants the recap as much as the reply.
        """
        self._stage(session, invocation, RECAP, agent, system, turns, tools, choice)

    def _stage(
        self,
        session: str,
        invocation: str,
        purpose: LlmPurpose,
        agent: str | None,
        system: str,
        turns: "list[Turn]",
        tools: "list[ToolDef]",
        choice: str,
    ) -> None:
        """Render this round, weigh it, and hold it under the bound.

        The render happens HERE rather than at the delivery, and that is
        the bound's own requirement rather than an optimization: the
        ceilings are measured on the serialized form that would actually
        be exported, so the number bounds what memory holds rather than
        a proxy for it, and a request weighed once and written twice
        could not be the same bytes.

        The order of the two ceilings is the accounting. A request over
        the per-request ceiling is `oversized` and never reaches the
        stage at all; everything that does reach it is then held against
        the session's budget, and what leaves under that pressure is
        `over_budget`. A request that passes the ceiling and is alone
        over the budget therefore counts once, as over budget, which is
        the honest word for it: the session cannot hold it.

        **Never raises, whatever it was handed**, and that is the
        standing posture of every surface on this ladder rather than a
        courtesy here: no content export may fail a conversation. This
        runs on the reply path and BEFORE the provider call, so an
        escape would not merely lose an observation, it would lose the
        answer the user is waiting for. The rendering and the weighing
        are therefore one operation inside one guard: an encode left
        outside it is an escape hatch, which is what the review round
        found, and the value that walks through it is reachable from a
        tool result rather than hypothetical.

        A round the rendering could not make at all is counted as
        `unrenderable`, a third absence with a name of its own. Not
        folded into either bound's count, because those two are the
        bound's vocabulary and mean something exact to whoever reads
        them: reporting a ceiling that was never reached would send an
        operator to tune a number that had nothing to do with it. And
        not left uncounted either, which is what it was: a round that
        vanished from the ledger is the one thing the plan's exhaustive
        accounting exists to prevent, and with no local store behind
        this class there is nowhere else to notice it from.
        """
        stage = self._staged.setdefault(session, _Stage())
        stage.index += 1
        try:
            request, size = _rendered(system, turns, tools, choice)
        except Exception:  # noqa: BLE001 - a reply never fails for this
            # Deliberately unbound and deliberately value-free: the line
            # names what happened and its consequence, and nothing it
            # was holding. A defect in this server is still a round that
            # carried the whole of a conversation.
            stage.unrenderable += 1
            logger.warning(
                "an assembled request could not be rendered for export, so this "
                "round will not be among the ones exported"
            )
            return
        if size > self._max_request_bytes:
            # Dropped WHOLE rather than truncated, the plan's own words
            # and the reason this class exists: a shortened request is
            # not the request the model was given, and an approximate
            # item in a fidelity class is worse than a missing one.
            stage.oversized += 1
            return
        stage.rounds.append(
            _Staged(
                round=LlmInputRound(
                    invocation=invocation,
                    index=stage.index,
                    purpose=purpose,
                    agent=agent,
                    request=request,
                ),
                size=size,
            )
        )
        stage.held += size
        while stage.rounds and (
            stage.held > self._session_budget_bytes
            or len(stage.rounds) > self._max_rounds
        ):
            dropped = stage.rounds.pop(0)
            stage.held -= dropped.size
            stage.over_budget += 1

    # --- the hook ------------------------------------------------------

    def session_closed(self, session: str) -> None:
        """A session ended. Queue its staged requests and let the stage
        go.

        Called from the device session's own close ordering, beside the
        transcript export's hand-over. The pop is unconditional and
        comes first, which is the retention answer made mechanical: the
        stage is gone at the close whatever happens next, so a session
        that had no trace, one the backlog turned away and one that
        exports cleanly all leave exactly nothing behind.

        A session that assembled nothing and lost nothing is silence,
        which is every connection refused before it spoke. A session
        whose every round was dropped is NOT silence: it says so, with
        no rounds and the two counts, because the absence is the whole
        of what a reader would otherwise have to guess at.

        It does no work. A dictionary pop, a read of a map and a put on
        a queue, on the session loop, which is the whole of what this
        costs a close.
        """
        stage = self._staged.pop(session, None)
        if stage is None or not stage.anything():
            return
        context = self._telemetry.retained_context(session)
        if context is None:
            # Decided here and never at export, which is what the
            # captured context is for: a session this exporter never
            # saw, or one whose trace had already aged out by the time
            # it closed, has nothing to be written onto.
            self._failed(session, LlmInputExportFailure.NO_TRACE)
            return
        reason = self._admit(
            _Job(
                session=session,
                context=context,
                rounds=tuple(held.round for held in stage.rounds),
                oversized=stage.oversized,
                over_budget=stage.over_budget,
                unrenderable=stage.unrenderable,
            )
        )
        if reason is not None:
            self._failed(session, reason)

    # --- the way out ---------------------------------------------------

    async def shutdown(self) -> None:
        """Interrupt the worker and let it go, bounded.

        Off the loop, because the wait is a thread join, and bounded,
        because a backend that has stopped answering must not hold a
        redeploy open.

        Interrupted rather than merely joined: the stop flag is what the
        queue wait watches, in short slices, so everything still queued
        is answered as `dropped` while the event tap and telemetry are
        still up. That ordering is the composition's half of the
        contract, which pushes this shutdown onto the exit stack behind
        the teardowns it has to unwind in front of.

        The wait is bounded and the QUIETING IS NOT, the asymmetry the
        transcript exporter states: what an expired wait leaves in
        flight is a request that is going to fail and log the endpoint
        it failed against. So the worker gives its lease back from its
        own `finally`, when the work is genuinely over.
        """
        with self._admission:
            # Under the admission lock, which is the whole of what makes
            # "no worker, so nothing is queued" true.
            self._stopping.set()
            worker = self._worker
        if worker is None:
            return
        await asyncio.to_thread(worker.join, self._shutdown_timeout_s)
        if worker.is_alive():
            # A plain sentence and nothing about the far side, and one
            # fact this exporter's sibling does not have to say: what
            # was being exported is in memory and nowhere else.
            logger.warning(
                "the LLM input exporter did not finish within %.0f s and was left "
                "behind; the requests it was exporting are held nowhere else",
                self._shutdown_timeout_s,
            )

    # --- the worker ----------------------------------------------------

    def _admit(self, job: _Job) -> LlmInputExportFailure | None:
        """This job onto the backlog, or the reason it never got there.

        The whole of admission under ONE lock, and the same lock the
        shutdown takes before it raises the stop flag, which is what
        makes the two one decision rather than two that can interleave.
        The window that shape closes is the transcript exporter's own,
        recorded there: starting the worker schedules a thread before
        the field that publishes it is assigned, so a shutdown landing
        between them would find no worker to join, and the job would
        then be queued behind a worker that was already gone. Neither
        exported nor reported, which is the one outcome this surface may
        never have, because nothing is persisted and the event is the
        whole of the ledger.

        The worker is a daemon thread rather than `asyncio.to_thread`
        for that module's reason too: the default executor's threads are
        joined by an `atexit` hook, so a wedged export on one of them
        would hold the process open exactly as long as the far side felt
        like holding it.

        The start is contained and the field is assigned only once it
        has succeeded: `Thread.start()` raises in a process that has run
        out of them and this runs inside a conversation's close, and a
        field holding a thread that never started is one the shutdown
        would try to join.
        """
        with self._admission:
            if self._stopping.is_set():
                # A session closing behind a shutdown, which a drain
                # produces: no worker will run this, so the drop is said
                # rather than left as a job nothing will ever answer.
                return LlmInputExportFailure.DROPPED
            if self._worker is None:
                worker = threading.Thread(
                    target=self._run, name="vinga-llm-input-export", daemon=True
                )
                try:
                    worker.start()
                except Exception:  # noqa: BLE001 - a close never fails for this
                    # Deliberately unbound and value-free: what a failed
                    # thread creation says is about this process, and the
                    # job's own event is where the outcome belongs.
                    logger.warning(
                        "the LLM input exporter could not start a worker, so this "
                        "session's assembled requests were not exported"
                    )
                    return LlmInputExportFailure.DROPPED
                self._worker = worker
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                return LlmInputExportFailure.DROPPED
        return None

    def _run(self) -> None:
        """Every queued job, until a shutdown ends it.

        The lease is taken here, before anything is constructed, and
        given back in the `finally`, which is the moment the work is
        genuinely over rather than the moment somebody stopped waiting
        for it.

        **The binding goes the instant the attempt is over**, and on
        this surface that is a retention rule rather than tidiness. The
        frame that polls is the frame that holds: a bare
        `self._attempt(job)` leaves `job` bound while the worker sits in
        its next `get`, and a `get` that times out rebinds nothing, so
        an idle server would hold the whole of the last session's
        assembled requests until another session closed or the process
        ended. This class promises "delivered or dropped, and nowhere
        after that", which is the strictest retention answer in this
        repository and the reason it was allowed to exist with no store
        behind it, so the `finally` below is part of that promise and
        not part of the loop's shape.

        Its sibling's worker keeps the same shape and needs no such
        line, which is the difference between the two surfaces rather
        than an omission there: a transcript job holds a session id, a
        pinned context and an acknowledgement, and the turns it exports
        are read from the store and let go inside `_attempt`.
        """
        self._quieted = quiet_the_sdk()
        try:
            while not self._stopping.is_set():
                try:
                    job = self._queue.get(timeout=POLL_S)
                except queue.Empty:
                    continue
                try:
                    self._attempt(job)
                finally:
                    del job
            self._drain()
        finally:
            lease, self._quieted = self._quieted, None
            if lease is not None:
                lease.release()

    def _drain(self) -> None:
        """Whatever a shutdown left queued, answered rather than left
        silent.

        Nothing is persisted and there is no sweep at the next boot to
        find these, and unlike the transcript exporter's drain there is
        nothing left on the host either: the event here is the whole of
        the ledger AND the whole of what survives.
        """
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                return
            self._failed(job.session, LlmInputExportFailure.DROPPED)

    def _attempt(self, job: _Job) -> None:
        """One session's staged rounds, from the bounded call to the
        event it produces.

        One call rather than the transcript exporter's page loop, and
        the difference is the bound: a session's turn count is bounded
        by nothing, so that module alternates a page read with a page
        export, where what this holds was already weighed against a byte
        budget before it was held at all. A job is therefore a bounded
        request by construction, and paging it would be machinery
        guarding a number that is already guarded.

        Never raises: a worker that died of one job would take every
        session after it, and what this surface promises is that a
        failure is an event.
        """
        began = time.monotonic()
        try:
            answer = self._telemetry.export_llm_input(
                job.session, job.context, job.rounds
            )
        except Exception:  # noqa: BLE001 - a worker never dies of a job
            # Deliberately unbound, for the reason the events package
            # gives where it does the same, and for the sharper one this
            # surface has: what a failing export is holding is the whole
            # of what a model was given.
            answer = Delivery.UNDELIVERED
        if answer is Delivery.NO_TRACE:
            self._failed(job.session, LlmInputExportFailure.NO_TRACE)
            return
        if answer is Delivery.STOPPED:
            self._failed(job.session, LlmInputExportFailure.DROPPED)
            return
        if answer is Delivery.UNDELIVERED:
            self._failed(job.session, LlmInputExportFailure.UNDELIVERED)
            return
        elapsed = int((time.monotonic() - began) * 1000)
        events.emit(
            lambda: LlmInputExported(
                session=SessionId(job.session),
                rounds=Count(len(job.rounds)),
                elapsed_ms=Whole(elapsed),
                oversized=Count(job.oversized),
                over_budget=Count(job.over_budget),
                unrenderable=Count(job.unrenderable),
            )
        )

    # --- what it says --------------------------------------------------

    def _failed(self, session: str, reason: LlmInputExportFailure) -> None:
        events.emit(
            lambda: LlmInputExportFailed(session=SessionId(session), reason=reason)
        )


def _rendered(
    system: str,
    turns: "list[Turn]",
    tools: "list[ToolDef]",
    choice: str,
) -> tuple[str, int]:
    """One round's four provider arguments as the string that will be
    exported, and the bytes that string is.

    The fidelity boundary, written out as a function: this is the
    request as vinga ASSEMBLED it, taken at the neutral seam every
    adapter translates FROM, and not the bytes any one vendor put on the
    wire. What that buys is stated in the ADR and is the reason the
    boundary is here: it is the one place the request exists once rather
    than once per vendor, and a snapshot taken after adapter translation
    would be a content surface built out of an SDK's own call arguments,
    which is where credentials live. The no-leak contract would then
    rest on an exclusion list per adapter, maintained forever, instead
    of on a seam that never sees one.

    So it contains the system prompt with its memory and know-how
    blocks, the message history as the model was given it, the tool
    schemas offered, the tool arguments the model asked for and the
    results it was handed back, and the tool choice. It does not contain
    vendor framing, the generation parameters, the endpoint, any header
    or any credential, none of which reach this function at all.

    Field by field rather than through a generic walk of the
    dataclasses, which is the same rule the transcript's own projection
    keeps: a seam type that grew a field would otherwise reach the wire
    without anybody deciding it should.

    Four keys and not five: which call shape assembled this is vinga's
    own label rather than something the model was handed, so it rides
    the span as an attribute and stays out of the request. A class whose
    value is that it is exactly what was sent must not quietly grow a
    field the model never saw.

    Canonical JSON, sorted and without padding, so the same round
    renders to the same bytes on every run. `default=str` is one
    totality clause: a value that is not JSON at all cannot have come
    off a model's wire or out of this server's own schemas, and
    rendering its text is a better answer inside a reply than an
    exception.

    **The size comes back with the string**, and that is the second
    totality clause rather than a convenience. The weighing has to
    happen on the bytes this exact string would become, and doing it at
    the call site put an encode OUTSIDE the guard that catches a
    rendering this server could not make: a value that renders and then
    will not encode would raise into a reply. Here the two are one
    operation and the pair that comes back is the pair the bound is
    applied to.

    The escaping is the third, and it is the one a hostile far side can
    reach. Python's JSON decoder accepts a lone-surrogate escape, so an MCP
    server's tool result can carry a LONE SURROGATE, and a tool result
    is staged content. `ensure_ascii=False` spells it back out as itself
    and UTF-8 refuses to encode it, so the compact spelling is tried
    first, for the size and the legibility it buys every ordinary
    conversation, and a round that cannot be encoded is rendered again
    with every non-ASCII code point escaped. That is always encodable,
    it is what the far side itself sent, and it costs nothing to a
    conversation that never carried one: the round is exported exactly
    rather than dropped for being awkward.
    """
    payload = {
        "system": system,
        "messages": [_message(turn) for turn in turns],
        "tools": [_tool(tool) for tool in tools],
        "tool_choice": choice,
    }
    compact = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    try:
        return compact, len(compact.encode("utf-8"))
    except UnicodeEncodeError:
        escaped = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return escaped, len(escaped.encode("utf-8"))


def _message(turn: "Turn") -> dict[str, Any]:
    """One history turn as the model was given it.

    The two tool halves contribute nothing when they are empty, which is
    every turn of a persistent history: an empty array on every message
    would be bytes against the budget saying nothing.
    """
    message: dict[str, Any] = {"role": turn.role, "content": turn.content}
    if turn.tool_calls:
        message["tool_calls"] = [_call(call) for call in turn.tool_calls]
    if turn.tool_results:
        message["tool_results"] = [_result(one) for one in turn.tool_results]
    return message


def _call(call: "ToolCall") -> dict[str, Any]:
    """One call the model asked for, with the arguments as the model
    sent them.

    The model's own values rather than the converted copy the far side
    received, which is the distinction `_for_execution` draws in the
    pipeline: what this class promises is what the model produced, and a
    string where a schema said integer is exactly the fact an operator
    diagnosing a marginal model is here to see. Arguments a model
    mangled beyond JSON ride the field the seam already keeps them in.
    """
    asked: dict[str, Any] = {
        "id": call.id,
        "name": call.name,
        "arguments": call.arguments,
    }
    if call.malformed_arguments is not None:
        asked["malformed_arguments"] = call.malformed_arguments
    return asked


def _result(result: "ToolResult") -> dict[str, Any]:
    """And one result it was handed back, failures included: a failed
    tool is a result the model read and phrased an answer from."""
    return {
        "tool_call_id": result.tool_call_id,
        "content": result.content,
        "is_error": result.is_error,
    }


def _tool(tool: "ToolDef") -> dict[str, Any]:
    """One tool as the model was told about it, schema and all, which is
    part of the request in exactly the sense the history is."""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }
