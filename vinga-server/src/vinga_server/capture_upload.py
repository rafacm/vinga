"""A closed session's recording, put beside the trace it was exported
under (#67).

Its callers stop having to know that Langfuse exists, that a media
upload is three requests, that a hardlink is what keeps a recording
alive through a prune, or that any of it happens on a thread. The
composition asks `build_capture_upload` for one object or for nothing
and hands it to the capture store; the store calls two methods on it and
the lifespan closes it. The staging, the bounded backlog, the worker,
the SDK bootstrap, the retries and the failure classification are
implementation, and none of it is reachable from anywhere else.

**It is the one surface that deliberately sends content off this host.**
Everything else that leaves is metadata: the JSON log, the OTLP spans
derived from it, the conversation record inside the deployment's own
database. This sends a recording of a room, which is why it is behind a
flag of its own that neither `server.capture` nor
`server.telemetry.enabled` implies, why the flag's description says so
in those words, and why `server.local_only` refuses to build it.

**It never touches the audio path.** The two halves of its hook run on
the session loop and do nothing but a hardlink and a queue put; every
request, every retry and every second of waiting happens on a daemon
thread of this module's own. A failure is a warning event and never a
failed session: a conversation is worth more than a recording of it, and
a recording is worth more than a copy of it somewhere else.

**Two halves, because the moments are two.** The pair is final when
`SessionCapture.close()` has patched the WAV header and written the
manifest, which happens at `CaptureStore.finished()`; a capture also
finishes there early, at its duration limit or after a write failure,
while the conversation carries on. And `finished()` is also where
pruning starts considering the files, so the one moment the pair is
guaranteed both final and still on disk is inside that callback. So
`stage()` runs there and hardlinks the two files aside, and
`session_closed()` runs from the device session's own close ordering and
is what queues the job. An early-finished capture is therefore staged
the moment its files are final and uploaded only when its session ends,
and a prune storm in between cannot erase it, because the links are
already somewhere else.

**Exactly two files.** The WAV and the manifest. The decision track
beside them is a third content-bearing artifact nothing authorized to
leave, so it stays local, and the wire tests assert that no request ever
carries it.

**The dangerous bytes enter below the catalog**, the same rule
`telemetry.py` states. The credentials arrive in `LANGFUSE_PUBLIC_KEY`
and `LANGFUSE_SECRET_KEY`, the endpoint in `LANGFUSE_HOST`, and the
upload itself goes to a PRESIGNED URL, which is a credential in a query
string that the HTTP stack would log as a request line. So no value of
theirs becomes an event field or a line of log text, the SDK's namespace
and the HTTP stack under it are quieted before the client is
constructed, and a failure is reported as a reason from a closed set and
never as the far side's words.

**What it is not.** It is not a second exporter. The Langfuse SDK's
tracing client owns a tracer provider, background consumer threads and
an `atexit` hook, and this server already has an exporter of its own and
a shutdown that has to stay bounded; what this uses is the SDK's
generated REST client, whose media calls are the published way to put an
asset beside a trace.
"""

import asyncio
import base64
import contextlib
import datetime as dt
import hashlib
import json
import logging
import os
import queue
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from vinga_server.config import ConfigError
from vinga_server.config.models import ServerConfig
from vinga_server.egress import EgressRefusal, check_feature
from vinga_server.events import ServerEvents
from vinga_server.events.catalog import CaptureUploaded, CaptureUploadFailed
from vinga_server.events.values import (
    AttemptedUpload,
    CaptureUploadFailure,
    Count,
    Real,
    SessionId,
    Whole,
)
from vinga_server.quieting import Lease, Quieting
from vinga_server.telemetry import Telemetry

logger = logging.getLogger(__name__)
events = ServerEvents(__name__)

# Where the switch is written, which is what every refusal below names.
# One spelling, because a sentence an operator is told to edit by has to
# be the path they will find.
ATTACH_KEY = "server.telemetry.attach_captures"

# The extra that carries the SDK, and the command that installs it. The
# registry's sentence shape, which `telemetry.py` follows too: the
# entry, the extra, and what to type.
LANGFUSE_EXTRA = "langfuse"

NEEDS_THE_LANGFUSE_EXTRA = (
    f"{ATTACH_KEY} is on, which needs the {LANGFUSE_EXTRA} extra; "
    f"install it with: uv sync --extra {LANGFUSE_EXTRA}"
)

# The environment family the SDK reads its transport and its credentials
# out of. Read here rather than configured, and named as a family: what
# a message may name is the variable and never its value.
#
# Vinga does no validation of them, deliberately. Their contract belongs
# to the SDK, a boot check would be a second parser over another
# library's names, and what a wrong or missing value produces is the
# first upload's warning event rather than a refused boot. A missing key
# reaches the far side as an unauthenticated request and comes back
# `refused`, which is the honest report.
LANGFUSE_HOST_ENV = "LANGFUSE_HOST"
LANGFUSE_BASE_URL_ENV = "LANGFUSE_BASE_URL"
LANGFUSE_PUBLIC_KEY_ENV = "LANGFUSE_PUBLIC_KEY"
LANGFUSE_SECRET_KEY_ENV = "LANGFUSE_SECRET_KEY"

# The namespaces quieted for as long as an uploader has work in flight.
#
# `langfuse` is the SDK's own, the way `opentelemetry` is the
# exporter's. The other three are the HTTP stack it drives, and they are
# the ones that matter here: `httpx` logs every request as a line
# carrying its URL, and the URL of the second request of every upload is
# a PRESIGNED one, which is a credential in a query string. An operator
# who wants any of it attaches a handler to the namespace itself, which
# is a deliberate act rather than the default.
QUIETED_NAMESPACES = ("langfuse", "httpx", "httpcore", "backoff")

# Where a staged pair waits, under the capture directory so the links
# land on the same filesystem as the files they are links to, which is
# what makes staging a hardlink rather than a copy.
STAGING_DIRECTORY = "upload-staging"

# What the two links are called inside one job's own directory. Fixed
# names rather than the session's, because the job directory already
# carries the session and a name a reader has to parse is a name that
# can disagree with the directory it is in.
AUDIO_NAME = "capture.wav"
MANIFEST_NAME = "capture.json"

# And the name a job wears while it is being built, so a directory that
# appears under the staging root is a job whose two links are both
# there: the build happens under this and is committed by one rename.
BUILDING_PREFIX = "."
BUILDING_SUFFIX = ".building"

# What a session id may be spelled with to become a directory name. The
# ids this server mints are hex, so nothing real is turned away; what
# this refuses is a separator or a traversal arriving as a session id,
# which is the one way a name could reach outside the staging root.
SAFE_NAME = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
NAME_LIMIT = 64

# How long any one request may take. The export timeout's own posture
# (`telemetry.py`), and it is what makes a failure event possible at
# all: the hostile failure here is an endpoint that accepts the
# connection and never answers, where an unbounded request would mean no
# `capture_upload_failed` ever fires and a bounded shutdown would merely
# abandon the job in silence.
REQUEST_TIMEOUT_S = 30.0

# And the ceiling on retrying it. Two retries with a doubling wait, then
# the failure event: a backend that is down stays down for longer than
# this, and a job retried forever is a worker that never reaches the
# next session's recording.
RETRIES = 2
BACKOFF_S = 0.5

# How long the lifespan waits for the worker on the way out, the
# exporter's own bound and for the same reason: a backend that has
# stopped answering must not hold a redeploy open. What a timeout costs
# is an upload, and what is left staged is swept at the next startup
# with its own event, so nothing is lost in silence.
SHUTDOWN_TIMEOUT_S = 5.0

# How often an idle worker looks up to see whether it has been asked to
# stop. Short enough not to lengthen a shutdown measurably, long enough
# that an idle server is not spinning.
POLL_S = 0.05

# What this server will not even ask a backend to take. The default
# per-session capture bound is fifteen minutes, which is about 57 MB of
# stereo 16 kHz, and an operator may raise it; this is the point past
# which asking is a request that will be refused after the bytes have
# been read, so it is answered here instead.
MAX_ATTACHMENT_BYTES = 512 * 1024 * 1024

# Which of a Langfuse observation's three attachable fields the pair
# lands on. `metadata` rather than `input` or `output`, because a
# recording is a fact about the session rather than something said to a
# model or by one.
MEDIA_FIELD = "metadata"

# The two content types, spelled as the media API's own closed
# enumeration spells them.
AUDIO_TYPE = "audio/wav"
MANIFEST_TYPE = "application/json"

MB = 1024 * 1024


def staging_root(directory: Path) -> Path:
    """Where this directory's staged uploads live.

    One home, and it is here rather than in `capture.py` because the
    shape of a job is this module's fact. The capture store reads it
    because the sweep is the store's: a boot with the uploader switched
    off, refused, or without its extra builds no uploader at all, and
    room audio staged by the run before it would then sit there
    silently in exactly the configurations an operator chose to stop
    exporting in.
    """
    return directory / STAGING_DIRECTORY


def build_capture_upload(
    config: ServerConfig,
    *,
    telemetry: Telemetry | None,
    local_only: bool = False,
    timeout_s: float = REQUEST_TIMEOUT_S,
    retries: int = RETRIES,
    backoff_s: float = BACKOFF_S,
    shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
) -> "CaptureUpload | None":
    """One server's uploader, or nothing at all.

    It takes the whole server section rather than the telemetry one,
    because the first thing it has to resolve is capture, and the order
    of the decisions here is the contract:

    1. **Capture first.** With `server.capture` absent, or present with
       `enabled` off, this answers None and none of the checks below
       run. The issue's own words are that the flag on with capture off
       is a no-op, so a capture-off deployment boots identically with or
       without the extra, the telemetry section or `local_only`, and an
       operator mid-toggle is not a misconfiguration. It is said out
       loud exactly when there is something to say: with the flag on and
       nothing to record, one value-free line, because a switch that
       does nothing is otherwise a silence somebody has to debug.
    2. **The flag.** Off, or a telemetry section that is absent
       altogether, answers None with nothing said. That is the default,
       and the default costs a server nothing: no import, no object, no
       thread, no callback.
    3. **Telemetry.** An attachment names the trace its session was
       exported under, so `attach_captures` on with `enabled` off is
       refused. That refusal is `TelemetryConfig`'s own model validator
       rather than a check here, because both keys are in one model;
       what is left here is the assertion that keeps this function
       total.
    4. **Egress.** Asked of `egress.py` before any import, any
       construction and any thread, so under `server.local_only` the
       SDK is provably never reached.
    5. **The extra.** Imported HERE rather than at module scope, the
       provider registry's `_resolved` pattern, which is what lets this
       module be imported by a server that does not have the SDK.

    The three refusals are `ConfigError` with a fixed value-free
    sentence, raised outside the handler that read them so nothing is
    chained: an ImportError carries its module search path, and an
    egress refusal is somebody else's sentence.

    `timeout_s`, `retries`, `backoff_s` and `shutdown_timeout_s` are the
    test seam and nothing else: a lane shortens the wait so a case about
    what happens after a timeout does not take half a minute to reach
    it. A caller that passes none of them gets the real bounds.
    """
    capture = config.capture
    telemetry_section = config.telemetry
    attaching = telemetry_section is not None and telemetry_section.attach_captures
    if capture is None or not capture.enabled:
        if attaching:
            logger.info(
                "%s is on and nothing is being recorded, so no capture will be "
                "attached; switch server.capture.enabled on to record",
                ATTACH_KEY,
            )
        return None
    if not attaching:
        return None
    if telemetry is None:
        # Unreachable through the configuration, because the model
        # refuses the combination that would produce it, and asserted
        # rather than assumed: a caller composing this by hand with no
        # exporter would otherwise get an uploader with nothing to ask
        # for a trace id.
        raise ConfigError(ATTACHMENT_NEEDS_AN_EXPORTER)

    refusal = _egress_refusal(local_only)
    if refusal is not None:
        raise ConfigError(refusal)

    sdk = _import_sdk()
    if sdk is None:
        raise ConfigError(NEEDS_THE_LANGFUSE_EXTRA)

    return CaptureUpload(
        capture.dir,
        sdk=sdk,
        telemetry=telemetry,
        backlog=config.limits.max_sessions,
        timeout_s=timeout_s,
        retries=retries,
        backoff_s=backoff_s,
        shutdown_timeout_s=shutdown_timeout_s,
    )


# The one refusal here that an operator cannot reach by editing a file,
# kept as a sentence anyway: it is what a composition built by hand gets
# instead of an uploader that would answer `no_trace` to every session
# it was ever given.
ATTACHMENT_NEEDS_AN_EXPORTER = (
    f"{ATTACH_KEY} is on and no exporter was built, so no session has a trace "
    f"to be attached to; switch server.telemetry.enabled on"
)


def _egress_refusal(local_only: bool) -> str | None:
    """What the egress rule says about an uploader, or nothing.

    Asked before any import, any construction and any thread, which is
    the caller's half of `check_feature`'s contract and the only way the
    refusal can honestly say nothing was built. The sentence is the
    egress module's own, and only the sentence crosses back: the
    exception type belongs to whichever surface asked, which here is
    `ConfigError`.
    """
    try:
        check_feature(ATTACH_KEY, egress=True, local_only=local_only)
    except EgressRefusal as refusal:
        return str(refusal)
    return None


@dataclass(frozen=True)
class Sdk:
    """The three names this module needs out of the SDK, resolved once.

    The registry's `_resolved` pattern: the import happens when an
    uploader is built and not before, so this module imports clean in an
    install that does not have the distribution, and no SDK symbol
    escapes this file.

    `client` is the generated REST client and not the tracing one, for
    the reason the module docstring gives: the tracing client owns a
    tracer provider, consumer threads and an `atexit` hook, and this
    server has an exporter of its own.

    Public, and it is the test seam, which is the same shape
    `build_telemetry(exporter=...)` is: a lane substitutes one of these
    and drives the whole staging, queue, worker and retry path without
    an SDK or a network, and the three names are exactly what the far
    side has to provide. A caller that passes none gets `_import_sdk`'s.
    """

    client: Any
    error: Any
    content_type: Any


def _import_sdk() -> Sdk | None:
    """The SDK, or nothing where it is not installed.

    Nothing rather than a raise, so the sentence the caller prints is
    raised outside this function's `except` and chains no ImportError.
    """
    try:
        from langfuse.api import MediaContentType
        from langfuse.api.client import LangfuseAPI
        from langfuse.api.core import ApiError
    except ImportError:
        return None
    return Sdk(client=LangfuseAPI, error=ApiError, content_type=MediaContentType)


@dataclass(frozen=True)
class _Job:
    """One staged pair, waiting for a worker."""

    session: str
    path: Path


class _Refused(Exception):
    """A failure there is no point retrying, carrying the reason it will
    be reported as.

    The far side answered, and what it said is not going to change in a
    second and a half: a credential it will not accept, a project that
    does not exist, a payload over its ceiling. Distinct from every
    other exception here so the retry loop can tell "try again" from
    "say so now" without reading a status code twice.
    """

    def __init__(self, reason: AttemptedUpload) -> None:
        super().__init__(reason)
        self.reason = reason


class CaptureUpload:
    """One server's uploader, as the thing its callers hold.

    Built by `build_capture_upload`, handed to the capture store, closed
    by the lifespan. What a caller may do with it is tell it a capture's
    files are final, tell it a session closed, and shut it down.
    """

    def __init__(
        self,
        directory: Path,
        *,
        sdk: Sdk,
        telemetry: Telemetry,
        backlog: int,
        timeout_s: float = REQUEST_TIMEOUT_S,
        retries: int = RETRIES,
        backoff_s: float = BACKOFF_S,
        shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
    ) -> None:
        self._root = staging_root(directory)
        self._sdk = sdk
        self._telemetry = telemetry
        # A bounded best-effort backlog, sized from the session limit,
        # and the bound is honest about what it cannot promise. A
        # routine shutdown closes every live session at once, and a
        # healthy redeploy of a full server must not deterministically
        # drop any of THOSE; jobs from earlier sessions may still be
        # waiting when that drain begins, and a backlog that deep means
        # the backend has been failing for a while. A job the bound
        # turns away is dropped with its warning event, which is the
        # drop stated rather than hidden.
        self._queue: queue.Queue[_Job] = queue.Queue(maxsize=max(1, backlog))
        self._timeout_s = timeout_s
        self._retries = retries
        self._backoff_s = backoff_s
        self._shutdown_timeout_s = shutdown_timeout_s
        # What has been staged and is waiting for its session to close,
        # and which sessions were not staged because their recording
        # disowns itself. Both written and read on the session loop, the
        # two halves of the hook, so neither needs a lock.
        self._staged: dict[str, Path] = {}
        self._incomplete: set[str] = set()
        # The worker, started at the first job rather than at build, so
        # a server that records nothing pays for no thread. Under a lock
        # because two sessions closing at once would otherwise start
        # two.
        self._starting = threading.Lock()
        self._worker: threading.Thread | None = None
        self._stopping = threading.Event()
        # The SDK's silence, taken by the worker before it constructs
        # anything and given back only when the worker has genuinely
        # stopped, which is the asymmetry `Telemetry.shutdown` explains:
        # a bounded wait that expired leaves work in flight, and what
        # that work is about to log is a presigned URL.
        self._quieted: Lease | None = None
        self._quieting = Quieting(*QUIETED_NAMESPACES)
        self._client: Any | None = None
        self._http: httpx.Client | None = None

    # --- the two halves of the hook -----------------------------------

    def stage(self, session: str, audio: Path, manifest: Path) -> None:
        """A capture's files are final. Put them somewhere a prune
        cannot reach.

        Called from `CaptureStore.finished()`, which is the one moment
        the pair is guaranteed both final and still on disk: the header
        is patched and the manifest written by the close that leads
        here, and pruning starts considering the files on the line
        after. Two hardlinks, on the same filesystem by construction, so
        this costs no copy and no measurable time on the close path.

        A capture the manifest disowns is never staged. A write failure
        leaves `complete: false` and a WAV whose header may never have
        been patched, and attaching that would present broken evidence
        as evidence; the session records `incomplete` when it closes
        instead.

        It does not upload. An early-finished capture, at its duration
        limit or after a write failure, reaches here while its
        conversation carries on, and a recording that went out before
        its session ended would be an attachment to a trace that is
        still open.
        """
        if not self._named(session):
            self._failed(session, CaptureUploadFailure.STAGING_LOST)
            return
        if not _complete(manifest):
            self._incomplete.add(session)
            return
        building = self._root / f"{BUILDING_PREFIX}{session}{BUILDING_SUFFIX}"
        final = self._root / session
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            _remove(building)
            _remove(final)
            building.mkdir()
            os.link(audio, building / AUDIO_NAME)
            os.link(manifest, building / MANIFEST_NAME)
            # One rename, which is what makes the pair atomic: a
            # directory that appears under the staging root has both its
            # links in it, so a sweep and a worker never meet half a
            # job.
            building.rename(final)
        except OSError:
            _remove(building)
            self._failed(session, CaptureUploadFailure.STAGING_LOST)
            return
        self._staged[session] = final

    def session_closed(self, session: str) -> None:
        """A session ended. Queue whatever was staged for it.

        Called from the device session's own close ordering, after
        `SessionCapture.close()`, which is the only signal that means
        the conversation is over: `CaptureStore.finished()` fires for an
        early-finished capture too.

        A session with nothing staged and nothing to report is silence,
        which is most sessions: capture off for this one, a capture that
        never opened, a server whose flag went on mid-session.
        """
        if session in self._incomplete:
            self._incomplete.discard(session)
            self._staged.pop(session, None)
            self._failed(session, CaptureUploadFailure.INCOMPLETE)
            return
        path = self._staged.pop(session, None)
        if path is None:
            return
        self._start()
        try:
            self._queue.put_nowait(_Job(session=session, path=path))
        except queue.Full:
            # The links go in the same breath as the event, because a
            # job nobody will ever run is room audio sitting on a disk
            # for the sweep to find at the next boot.
            _remove(path)
            self._failed(session, CaptureUploadFailure.DROPPED)

    # --- the way out ---------------------------------------------------

    async def shutdown(self) -> None:
        """Let the worker finish what it can, bounded.

        Off the loop, because the wait is a thread join, and bounded,
        because a backend that has stopped answering must not hold a
        redeploy open. The worker drains what it can inside the bound
        and whatever is left stays staged, which the next startup sweeps
        with one `abandoned` event per job: nothing is lost in silence,
        and nothing is persisted for retry either, because a retry store
        would be a durability promise this flag does not make.

        The wait is bounded and the QUIETING IS NOT, which is the
        exporter's asymmetry and is here for the same reason: a shutdown
        that expired left a request in flight against an endpoint that
        is not answering, and that request is going to fail and log the
        presigned URL it failed against. So the worker gives the lease
        back from its own `finally`, when the work is genuinely over.
        """
        self._stopping.set()
        worker = self._worker
        if worker is None:
            return
        await asyncio.to_thread(worker.join, self._shutdown_timeout_s)
        if worker.is_alive():
            # A plain sentence and nothing about the far side: what
            # could not be reached is the endpoint, which is the one
            # string this module never writes down.
            logger.warning(
                "the capture uploader did not finish within %.0f s and was left "
                "behind; what it had staged is swept at the next startup",
                self._shutdown_timeout_s,
            )

    # --- the worker ----------------------------------------------------

    def _start(self) -> None:
        """The worker, started at the first job and never again.

        A daemon thread of its own rather than `asyncio.to_thread`, the
        exporter's reasoning: the default executor's threads are joined
        by an `atexit` hook, so a wedged upload on one of them would
        hold the process open exactly as long as the backend felt like
        holding it, which is what a bounded shutdown exists to prevent.
        """
        with self._starting:
            if self._worker is not None or self._stopping.is_set():
                return
            self._worker = threading.Thread(
                target=self._run, name="vinga-capture-upload", daemon=True
            )
            self._worker.start()

    def _run(self) -> None:
        """Every queued job, until there is nothing left and a shutdown
        has been asked for.

        The lease is taken here, before anything is constructed and
        before any request, and given back in the `finally`, which is
        the moment the work is genuinely over rather than the moment
        somebody stopped waiting for it.
        """
        self._quieted = self._quieting.take()
        try:
            while True:
                try:
                    job = self._queue.get(timeout=POLL_S)
                except queue.Empty:
                    if self._stopping.is_set():
                        return
                    continue
                self._attempt(job)
        finally:
            self._close_client()
            lease, self._quieted = self._quieted, None
            if lease is not None:
                lease.release()

    def _attempt(self, job: _Job) -> None:
        """One job, from the trace it needs to the event it produces.

        Whatever happens, the links go: this module keeps nothing for a
        retry, and the event is the ledger.
        """
        began = time.monotonic()
        try:
            reason = self._deliver(job, began)
        except Exception:  # noqa: BLE001 - a worker never dies of a job
            # Deliberately unbound, for the reason the events package
            # gives where it does the same: what is never looked at
            # cannot leak by accident later.
            reason = CaptureUploadFailure.UNREACHABLE
        if reason is not None:
            self._failed(job.session, reason)
        _remove(job.path)

    def _deliver(self, job: _Job, began: float) -> AttemptedUpload | None:
        """The upload itself, or the reason it did not happen."""
        trace = self._telemetry.trace_of(job.session)
        if trace is None:
            # Never retried, and the walkthrough that settled this is
            # M1's: the media API accepts a `traceId` it has not
            # ingested yet and holds the association, so the race
            # between a batched export and an upload is not a failure
            # mode at all. What is left for this reason is the case
            # where this server itself has no id to name.
            return CaptureUploadFailure.NO_TRACE
        try:
            audio = (job.path / AUDIO_NAME).read_bytes()
            manifest = (job.path / MANIFEST_NAME).read_bytes()
        except OSError:
            return CaptureUploadFailure.STAGING_LOST
        if len(audio) + len(manifest) > MAX_ATTACHMENT_BYTES:
            return CaptureUploadFailure.TOO_LARGE
        reason = self._send(trace, audio, manifest)
        if reason is not None:
            return reason
        elapsed = int((time.monotonic() - began) * 1000)
        events.emit(
            lambda: CaptureUploaded(
                session=SessionId(job.session),
                audio_bytes=Count(len(audio)),
                manifest_bytes=Count(len(manifest)),
                elapsed_ms=Whole(elapsed),
                megabytes=Real((len(audio) + len(manifest)) / MB),
            )
        )
        return None

    def _send(self, trace: str, audio: bytes, manifest: bytes) -> AttemptedUpload | None:
        """Both attachments, retried as a pair, or the reason they did
        not land.

        Retried whole rather than per request, and that costs nothing
        twice over: a media id is content-addressed, so a second attempt
        against bytes already uploaded answers with no upload URL at all
        and the SDK's own uploader does the same thing for the same
        reason.
        """
        reason: AttemptedUpload = CaptureUploadFailure.UNREACHABLE
        wait = self._backoff_s
        for attempt in range(self._retries + 1):
            try:
                client = self._media()
                self._attach(client, trace, audio, AUDIO_TYPE)
                self._attach(client, trace, manifest, MANIFEST_TYPE)
                return None
            except _Refused as refused:
                return refused.reason
            except Exception as raised:  # noqa: BLE001 - every failure is an event
                reason, again = self._classify(raised)
                if not again:
                    return reason
            if attempt < self._retries and not self._stopping.is_set():
                time.sleep(wait)
                wait *= 2
        return reason

    def _media(self) -> Any:
        """The SDK's REST client, constructed at the first job that
        needs it.

        Deferred out of the builder deliberately: a client constructed
        at boot would turn whatever the SDK validates about its
        environment into a boot failure, and the settled position is
        that missing credentials are the first upload's warning rather
        than a refused start. Every exception from here is contained by
        the caller and reported as a reason, so a construction that
        raises is an upload that failed and never a thread that died.
        """
        if self._client is None:
            base = os.environ.get(LANGFUSE_BASE_URL_ENV) or os.environ.get(
                LANGFUSE_HOST_ENV
            )
            if not base:
                # No default, and specifically not the SDK's own, which
                # is a vendor's hosted endpoint: a server that quietly
                # shipped room audio to a cloud nobody named would be
                # the opposite of what this flag is for.
                raise _Refused(CaptureUploadFailure.UNREACHABLE)
            self._http = httpx.Client(timeout=self._timeout_s)
            self._client = self._sdk.client(
                base_url=base,
                username=os.environ.get(LANGFUSE_PUBLIC_KEY_ENV),
                password=os.environ.get(LANGFUSE_SECRET_KEY_ENV),
                timeout=self._timeout_s,
                httpx_client=self._http,
            )
        return self._client

    def _attach(self, client: Any, trace: str, payload: bytes, kind: str) -> None:
        """One file, by the three requests the media API is.

        Asked for an upload URL against the trace, PUT to the presigned
        URL that comes back, and the record closed with what the PUT
        answered. The first request is idempotent by content: bytes the
        backend already holds come back with no upload URL, and then
        there is nothing to PUT.
        """
        digest = base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")
        answer = client.media.get_upload_url(
            content_type=self._sdk.content_type(kind),
            content_length=len(payload),
            sha256hash=digest,
            field=MEDIA_FIELD,
            trace_id=trace,
        )
        upload_url = getattr(answer, "upload_url", None)
        if not upload_url:
            return
        assert self._http is not None
        began = time.monotonic()
        response = self._http.put(
            upload_url,
            headers={
                "Content-Type": kind,
                "x-amz-checksum-sha256": digest,
                "x-ms-blob-type": "BlockBlob",
            },
            content=payload,
        )
        response.raise_for_status()
        client.media.patch(
            answer.media_id,
            uploaded_at=dt.datetime.now(dt.UTC),
            upload_http_status=response.status_code,
            upload_time_ms=int((time.monotonic() - began) * 1000),
        )

    def _classify(self, raised: BaseException) -> tuple[AttemptedUpload, bool]:
        """Which of the closed set this failure is, and whether trying
        again could change it.

        Read off a status code and never off a message: the far side's
        words are a response body next to a credential, and a reason is
        what an operator acts on. Anything this cannot place is
        `unreachable` and not retried, because saying `refused` would
        claim the far side answered and because an exception with no
        status behind it is this server's own problem rather than a
        connection that might come back. A connection that never
        completed IS retried, which is the one case the timeout and the
        backoff exist for.
        """
        status = _status_of(raised, self._sdk.error)
        if status is None:
            return CaptureUploadFailure.UNREACHABLE, isinstance(
                raised, httpx.TransportError
            )
        if status == httpx.codes.REQUEST_ENTITY_TOO_LARGE:
            return CaptureUploadFailure.TOO_LARGE, False
        if status == httpx.codes.TOO_MANY_REQUESTS or status >= 500:
            return CaptureUploadFailure.UNREACHABLE, True
        if status >= 400:
            return CaptureUploadFailure.REFUSED, False
        return CaptureUploadFailure.UNREACHABLE, False

    def _close_client(self) -> None:
        """Let the HTTP stack go, under its own guard: this runs on a
        path that may already be handling a failure."""
        http, self._http = self._http, None
        self._client = None
        if http is not None:
            with contextlib.suppress(Exception):
                http.close()

    # --- what it says --------------------------------------------------

    def _failed(self, session: str, reason: AttemptedUpload) -> None:
        events.emit(
            lambda: CaptureUploadFailed(
                session=SessionId(session), reason=reason
            )
        )

    def _named(self, session: str) -> bool:
        """Whether this session id may be a directory name.

        The ids this server mints are hex, so nothing real is turned
        away. What this refuses is a separator or a traversal arriving
        as a session id, which is the one way a name could reach outside
        the staging root.
        """
        return bool(session) and len(session) <= NAME_LIMIT and set(session) <= SAFE_NAME


def _complete(manifest: Path) -> bool:
    """Whether the manifest says its capture is whole.

    The manifest's own word, which is the only one there is: a capture
    stopped by a write failure says `complete: false` and its WAV header
    may never have been patched. Anything unreadable is not complete
    either, for the same reason the flag exists.
    """
    try:
        held = json.loads(manifest.read_text(encoding="utf-8"))
        return bool(held["capture"]["complete"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _status_of(raised: BaseException, error: Any) -> int | None:
    """The HTTP status behind a failure, or None where there is not one.

    Two shapes, because the two halves of an upload use two clients: the
    SDK's generated error carries `status_code`, and a presigned PUT
    that answered badly arrives as an httpx status error.
    """
    if isinstance(raised, error):
        status = getattr(raised, "status_code", None)
        return status if isinstance(status, int) else None
    if isinstance(raised, httpx.HTTPStatusError):
        return raised.response.status_code
    return None


def _remove(path: Path) -> None:
    """One staged job's directory, gone, under its own guard.

    Every caller is either finishing with a job or handling a failure,
    and a failure to clean up must not become the failure that gets
    reported.
    """
    with contextlib.suppress(OSError):
        shutil.rmtree(path)
