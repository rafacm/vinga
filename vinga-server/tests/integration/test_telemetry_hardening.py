"""A collector that has stopped answering, against replies that must
not care.

This is the certificate the exporter is worth having. The easy failure
to test is a collector that refuses fast, which costs nothing whatever
the implementation does; the failure that hurts is one that ACCEPTS the
connection and then never answers, because that is where a naive
exporter's queue backs up into the thing that is filling it, and the
thing filling it here is a reply on the device's audio path.

So the transport is replaced by an exporter that blocks forever, the
batch queue is made small enough to fill in a handful of turns, and real
scripted replies are driven through a real session with the exporter's
tap attached. What is asserted is a FIXED upper bound on every one of
those replies, not "indistinguishable" and not a comparison against a
baseline the same machine measured a moment earlier: the providers are
scripted and their timings are known, so the number a healthy reply
takes is a number this file can name.

Dropped spans are the accepted cost, and they are asserted too: an
implementation that kept every span by growing without bound would pass
the latency half of this and fail a deployment overnight.
"""

import asyncio
import logging
import threading
import time
from typing import Any, cast

import pytest

from tests.support.configs import POET_MAC, base_config
from tests.support.events import every_format
from tests.support.providers import ScriptedLlm
from tests.support.sessions import (
    events_of,
    session_for,
    start_reply,
    wait_for_reply,
)
from tests.support.sockets import RecordingSocket
from tests.support.telemetry import open_session
from vinga_server.config.models import TelemetryConfig
from vinga_server.telemetry import build_telemetry

pytestmark = pytest.mark.asyncio

# 20 ms of silence, which the scripted ear answers whatever it holds.
UTTERANCE = b"\x00\x00" * 320

# Enough turns to fill the queue below several times over, so what is
# measured is the saturated exporter rather than the first batch.
TURNS = 12

# Small enough that the first blocked export leaves nowhere to put the
# next span, which is the state this file is about.
QUEUE = 4

# What one scripted reply may take, in seconds, against providers whose
# timings are this lane's own: a mock ear, a two-sentence scripted model
# and a mock voice into a recording socket. Generous by an order of
# magnitude against the healthy number, because what would fail this is
# a reply that WAITED on an export, and an export here waits forever.
REPLY_BOUND_S = 3.0


class Blocking:
    """A span exporter that accepts a batch and never answers.

    The hostile collector, in the one shape that can reach a reply: a
    fast refusal costs nothing, and a slow success is what fills a queue.
    It is released in the fixture's teardown, because the SDK's own
    shutdown joins this thread.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.released = threading.Event()
        self.batches = 0

    def export(self, spans: Any) -> Any:
        from opentelemetry.sdk.trace.export import SpanExportResult

        self.batches += 1
        self.entered.set()
        self.released.wait(30.0)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self.released.set()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def talking(telemetry: Any) -> Any:
    """A session on a recording socket, with a model that answers two
    sentences, which is what lets a reply run all the way through
    speaking, and the exporter's tap already on it.

    The `session_open` is emitted by hand, because it is the edge's and
    these sessions are built below the edge (`sessions.py` says so): the
    trace has no session span without it, and a turn with no session to
    link to opens nothing at all. Everything after it is the real reply
    path.
    """
    session = session_for(
        base_config(),
        POET_MAC,
        cast(Any, {"poet": ScriptedLlm(["Two words. And two more."])}),
    )
    session.websocket = cast(Any, RecordingSocket())
    events = events_of(session)
    events.attach(telemetry.session_tap())
    open_session(events)
    return session


async def test_a_collector_that_never_answers_costs_no_reply_anything() -> None:
    """The saturation case: every reply inside a fixed bound, with the
    exporter wedged from the first batch onward.

    The blocked export is asserted before the replies are measured. A
    lane where the exporter was never entered would measure a healthy
    server and call it a hardened one, which is exactly the shape of
    safety test that certifies nothing.
    """
    collector = Blocking()
    telemetry = build_telemetry(
        TelemetryConfig(enabled=True),
        exporter=collector,
        queue_size=QUEUE,
        batch_size=1,
        schedule_delay_ms=1,
    )
    assert telemetry is not None
    session = talking(telemetry)

    slowest = 0.0
    try:
        for _ in range(TURNS):
            began = time.monotonic()
            start_reply(session, UTTERANCE)
            await wait_for_reply(session)
            slowest = max(slowest, time.monotonic() - began)
            # The first turn is what wedges it; every turn after that
            # emits into a queue with a blocked exporter behind it.
            assert collector.entered.wait(1.0), "the exporter never blocked at all"

        assert slowest < REPLY_BOUND_S, (
            f"a reply took {slowest:.2f} s with the collector wedged"
        )
    finally:
        collector.released.set()
        await telemetry.shutdown()

    # And the accepted cost, said out loud: a wedged collector drops
    # spans rather than growing without bound. One batch is in the
    # exporter's hands and at most a queue's worth behind it, whatever
    # the session emitted.
    assert collector.batches <= QUEUE + 1


async def test_the_shutdown_of_a_wedged_exporter_is_bounded() -> None:
    """The other end of the same posture. A collector that has stopped
    answering must not hold a redeploy open, so the lifespan's release
    is bounded and what a timeout costs is spans.

    Measured rather than asserted about the constant, because what is
    being checked is that the wait is bounded at all: an unbounded
    shutdown would join a thread that is waiting on a collector that
    never answers, and the lane would hang until CI killed it.
    """
    from vinga_server.telemetry import SHUTDOWN_TIMEOUT_S

    collector = Blocking()
    telemetry = build_telemetry(
        TelemetryConfig(enabled=True),
        exporter=collector,
        queue_size=QUEUE,
        batch_size=1,
        schedule_delay_ms=1,
    )
    assert telemetry is not None
    session = talking(telemetry)
    start_reply(session, UTTERANCE)
    await wait_for_reply(session)
    assert collector.entered.wait(5.0), "the exporter never blocked at all"

    began = time.monotonic()
    try:
        await asyncio.wait_for(telemetry.shutdown(), SHUTDOWN_TIMEOUT_S * 3)
    finally:
        collector.released.set()
    took = time.monotonic() - began

    assert took < SHUTDOWN_TIMEOUT_S * 2, f"the shutdown waited {took:.1f} s"


class Late:
    """A collector that fails AFTER the shutdown gave up on it, with a
    credential in what it says.

    The shape the timeout actually leaves behind: an export in flight
    against an endpoint that will not answer, which eventually raises
    with the URL it could not reach in the message. A real one carries
    the operator's endpoint; this one carries a sentinel so the hunt
    below has something to look for.
    """

    def __init__(self, sentinel: str) -> None:
        self.sentinel = sentinel
        # Set by the TEST, to release the export once the public
        # shutdown has already given up on it.
        self.release = threading.Event()
        self.failed = threading.Event()
        # Set by the SDK, and last: a batch processor joins its worker
        # before it closes its exporter, so this is the one observable
        # that says everything the SDK was going to do about the failure
        # (including logging it) has been done. A hunt that raced this
        # would pass whether the suppression held or not.
        self.closed = threading.Event()

    def export(self, spans: Any) -> Any:
        self.release.wait(30.0)
        try:
            raise ConnectionError(f"POST https://user:{self.sentinel}@collector/v1/traces")
        finally:
            self.failed.set()

    def shutdown(self) -> None:
        self.closed.set()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


async def test_a_failure_after_the_timeout_reaches_no_surface(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """The half a bounded shutdown used to give away.

    The wait is bounded and the quieting is not, and the difference is
    the point: an export the timeout abandoned is still going to fail,
    and it fails by logging the endpoint it could not reach. Restoring
    the SDK's logging when the WAIT ended would have put that endpoint,
    userinfo and all, into the retained log a second later, on a path
    nothing was watching any more.

    So the sequence here is the one that used to be masked: the exporter
    is released only AFTER `shutdown()` has returned, it fails with a
    credential in its message, and the hunt runs once that failure has
    genuinely happened.
    """
    caplog.set_level(logging.DEBUG)
    collector = Late("sk-live-LATE-EXPORT-SENTINEL")
    telemetry = build_telemetry(
        TelemetryConfig(enabled=True),
        exporter=collector,
        queue_size=QUEUE,
        batch_size=1,
        schedule_delay_ms=1,
        # Short, because what this case is about is everything that
        # happens after the bound expires.
        shutdown_timeout_s=0.2,
    )
    assert telemetry is not None
    session = talking(telemetry)
    start_reply(session, UTTERANCE)
    await wait_for_reply(session)

    await telemetry.shutdown()

    # The public shutdown is over and the export has not failed yet,
    # which is the state the abandoned work lives in.
    assert not collector.failed.is_set()
    collector.release.set()
    assert collector.failed.wait(10.0), "the abandoned export never failed"
    assert collector.closed.wait(10.0), "the SDK never finished releasing the exporter"
    # And the namespace comes back once the work is genuinely over,
    # which is the other half: suppressed for longer than the wait, not
    # for ever.
    assert until_quiet_is_restored(), "the SDK namespace was never given back"

    captured = capsys.readouterr()
    assert collector.sentinel not in every_format(caplog)
    assert collector.sentinel not in captured.err
    assert collector.sentinel not in captured.out


def until_quiet_is_restored(seconds: float = 10.0) -> bool:
    """Wait for the release thread to put the SDK namespace back.

    The worker restores from its own `finally`, so this is the one
    observable that says it finished; polling rather than sleeping,
    because a fixed sleep is a flake waiting for a loaded runner.
    """
    namespace = logging.getLogger("opentelemetry")
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if namespace.level <= logging.CRITICAL:
            return True
        time.sleep(0.02)
    return False
