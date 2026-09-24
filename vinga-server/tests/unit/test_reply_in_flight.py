"""The reply in flight and the speaking pass, through their own
interface and with no session.

The session-level suites drive these through whole replies
(`test_turn_lifecycle.py` for the outcome each boundary latches,
`test_session_events.py` and `test_session_withheld.py` for a pass
starting from nothing); what they cannot do cheaply is put a reply at
an exact point of its life, which is what the ordering claims below are
about. So here a value is handed a body written for the test: one that
waits on an event it is released by, one that fails, one that notes
what it saw on the way out.
"""

import asyncio
import gc
import weakref
from typing import Any

import pytest

from vinga_server.events.values import ReplyOutcome
from vinga_server.runtime.reply_in_flight import ReplyInFlight, SpeakingPass


async def test_a_new_reply_has_ended_nowhere_and_keeps_its_utterance() -> None:
    named = ReplyInFlight("0f1e2d3c4b5a69780f1e2d3c4b5a6978")
    unnamed = ReplyInFlight(None)

    assert named.utterance == "0f1e2d3c4b5a69780f1e2d3c4b5a6978"
    assert unnamed.utterance is None
    assert (named.outcome, unnamed.outcome) == (None, None)
    assert not named.running()


async def test_the_first_outcome_latched_is_the_one_it_keeps() -> None:
    """A barge-in landing on a reply already inside its failure arm did
    not fail it, and the other way round: whichever acted first."""
    reply = ReplyInFlight(None)

    reply.latch(ReplyOutcome.FAILED)
    reply.latch(ReplyOutcome.BARGED_IN)

    assert reply.outcome is ReplyOutcome.FAILED


async def test_a_reply_runs_until_its_body_is_done() -> None:
    release = asyncio.Event()

    async def body() -> None:
        await release.wait()

    reply = ReplyInFlight(None)
    reply.start(body())
    assert reply.running()

    release.set()
    await reply
    assert not reply.running()


async def test_a_cancel_is_latched_before_the_body_sees_it() -> None:
    """The ordering the reply's `finally` depends on: it reads the
    outcome off the value, so the canceller's word has to be there by
    the time the cancellation reaches the body, however promptly it
    lands."""
    seen: list[ReplyOutcome | None] = []
    reply = ReplyInFlight(None)

    async def body() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            seen.append(reply.outcome)

    reply.start(body())
    await asyncio.sleep(0)
    await reply.cancel(ReplyOutcome.BARGED_IN)

    assert seen == [ReplyOutcome.BARGED_IN]
    assert not reply.running()


async def test_a_cancel_that_ends_the_reply_as_asked_raises_nothing() -> None:
    """The cancellation is how the reply ending as asked looks from the
    canceller, so it is the one thing suppressed."""

    async def body() -> None:
        await asyncio.Event().wait()

    reply = ReplyInFlight(None)
    reply.start(body())
    await asyncio.sleep(0)

    await reply.cancel(ReplyOutcome.ABORTED)

    assert reply.outcome is ReplyOutcome.ABORTED
    assert not reply.running()


async def test_a_cancel_raises_what_the_reply_ended_in_otherwise() -> None:
    """Exactly `CancelledError` is suppressed. A reply that ended in
    something else ended in something the canceller has to hear about,
    as awaiting the task inside a suppression of cancellations alone
    always made it."""
    reply = ReplyInFlight(None)

    async def body() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            raise RuntimeError("the tail broke")

    reply.start(body())
    await asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="the tail broke"):
        await reply.cancel(ReplyOutcome.BARGED_IN)


class HeldTail:
    """A reply body whose `finally` waits for the test to let it go,
    and writes down how its tail ended.

    What the tail can be told apart by is the whole of the claims below:
    a tail let go by the test finishes, and a tail cancelled a second
    time on its caller's behalf is interrupted."""

    def __init__(self) -> None:
        self.holding = asyncio.Event()
        self.release = asyncio.Event()
        self.tail: list[str] = []

    async def body(self) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            self.holding.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.tail.append("interrupted")
                raise
            self.tail.append("finished")


async def held(tail: HeldTail) -> ReplyInFlight:
    """A reply running `tail`'s body, let as far as its first await, so
    a cancel from here lands inside the `try` and the `finally` holds."""
    reply = ReplyInFlight(None)
    reply.start(tail.body())
    await asyncio.sleep(0)
    return reply


async def test_a_caller_cancelled_while_it_waits_sees_its_own_cancellation() -> None:
    """The reply's own cancellation is what a cancel swallows, and only
    that: the caller being cancelled is a different fact, and a caller
    that went on as though it were not is how a session outlived its
    cap."""
    tail = HeldTail()
    reply = await held(tail)
    caller = asyncio.create_task(reply.cancel(ReplyOutcome.BARGED_IN))
    await asyncio.wait_for(tail.holding.wait(), timeout=5.0)

    caller.cancel()

    with pytest.raises(asyncio.CancelledError):
        await caller
    tail.release.set()
    assert await reply.drain(5.0)


async def test_a_caller_under_a_timeout_gets_its_timeout() -> None:
    """The shape of the session cap, one level down: `asyncio.timeout`
    raises only when the cancellation it delivered comes back out."""
    tail = HeldTail()
    reply = await held(tail)

    async def capped() -> None:
        async with asyncio.timeout(0.05):
            await reply.cancel(ReplyOutcome.BARGED_IN)

    caller = asyncio.create_task(capped())
    await asyncio.wait_for(tail.holding.wait(), timeout=5.0)

    with pytest.raises(TimeoutError):
        await caller
    tail.release.set()
    assert await reply.drain(5.0)


async def test_the_callers_cancellation_leaves_the_reply_tail_alone() -> None:
    """Propagating the caller's cancellation is not forwarding it: the
    reply is cancelled once, by the cancel, and its `finally` is where
    the closing `tts stop` and the turn record are, so a second cancel
    on the caller's behalf would cut those short."""
    tail = HeldTail()
    reply = await held(tail)
    caller = asyncio.create_task(reply.cancel(ReplyOutcome.BARGED_IN))
    await asyncio.wait_for(tail.holding.wait(), timeout=5.0)
    caller.cancel()
    # Waited on rather than awaited: how the caller ended is the test
    # above's claim, and this one is about the reply alone.
    await asyncio.wait([caller])

    tail.release.set()
    assert await reply.drain(5.0)

    assert tail.tail == ["finished"]
    assert reply.outcome is ReplyOutcome.BARGED_IN


async def test_a_reply_that_finished_before_its_cancel_raises_nothing() -> None:
    """The quiet half of what a cancel raises: a reply whose body
    returned before the cancel landed ended well, and the cancel only
    writes its word down."""
    finished: list[str] = []

    async def body() -> None:
        finished.append("the whole reply")

    reply = ReplyInFlight(None)
    reply.start(body())
    assert await reply.drain(5.0)

    await reply.cancel(ReplyOutcome.ABORTED)

    assert finished == ["the whole reply"]
    assert reply.outcome is ReplyOutcome.ABORTED
    assert not reply.running()


async def test_a_cancelled_close_hurries_the_reply_and_raises_after_it() -> None:
    """A close is an owner's last step, so a cancellation of its caller
    means hurry rather than leave: it is passed on to the reply, and it
    reaches the caller only once the reply's task is done."""
    tail = HeldTail()
    reply = await held(tail)
    closing = asyncio.create_task(reply.close(ReplyOutcome.ABORTED))
    await asyncio.wait_for(tail.holding.wait(), timeout=5.0)
    running_when_closed: list[bool] = []
    closing.add_done_callback(lambda _: running_when_closed.append(reply.running()))

    closing.cancel()

    done, _ = await asyncio.wait([closing], timeout=5.0)
    assert done, "the close never let its caller go"
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert tail.tail == ["interrupted"]
    assert running_when_closed == [False]
    assert reply.outcome is ReplyOutcome.ABORTED


async def test_a_close_raises_what_the_reply_ended_in_otherwise() -> None:
    """The same contract `cancel` keeps, with no cancellation of the
    caller in the way."""
    reply = ReplyInFlight(None)

    async def body() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            raise RuntimeError("the tail broke")

    reply.start(body())
    await asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="the tail broke"):
        await reply.close(ReplyOutcome.ABORTED)


class Witness:
    """Something only a reply's own frame holds, so its going is how a
    test knows the reply's task was collected rather than kept."""


async def collected() -> None:
    """Collect, more than once and with a turn of the loop between, as
    `test_drain.py` does: a task, its coroutine and the traceback of what
    it raised reference each other, and one pass can leave them for the
    next."""
    for _ in range(3):
        gc.collect()
        await asyncio.sleep(0)


async def test_a_held_cancellation_reads_the_reply_failure_and_drops_it() -> None:
    """A reply whose tail broke under the second cancel ended in
    something other than its cancellation, and the caller is owed the
    cancellation alone. The failure is still read, though: a task whose
    exception nobody retrieved is reported by the loop when it is
    collected, text and chain included, and that is a retained surface
    this server keeps exception text off."""
    loop = asyncio.get_running_loop()
    reports: list[dict[str, Any]] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _, context: reports.append(context))
    try:
        holding = asyncio.Event()

        async def body(witness: Witness) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                holding.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    raise RuntimeError("the tail broke")

        witness = Witness()
        gone = weakref.ref(witness)
        reply = ReplyInFlight(None)
        reply.start(body(witness))
        del witness
        await asyncio.sleep(0)
        closing = asyncio.create_task(reply.close(ReplyOutcome.ABORTED))
        await asyncio.wait_for(holding.wait(), timeout=5.0)

        closing.cancel()

        done, _ = await asyncio.wait([closing], timeout=5.0)
        assert done, "the close never let its caller go"
        with pytest.raises(asyncio.CancelledError) as raised:
            await closing
        assert raised.value.__context__ is None
        assert raised.value.__cause__ is None
        assert not reply.running()
        # Everything here that could still hold the reply's task, let
        # go, so collecting it is what would report it.
        del raised, closing, done, reply
        await collected()
        assert gone() is None, "the reply outlived the check, which proves nothing"
    finally:
        loop.set_exception_handler(previous)

    assert [context.get("message") for context in reports] == []


async def test_cancelling_a_reply_never_started_only_latches() -> None:
    """A body run on the caller's own task has no task here to cancel;
    what a cancel can still do is write the word down."""
    reply = ReplyInFlight(None)

    await reply.cancel(ReplyOutcome.ABORTED)

    assert reply.outcome is ReplyOutcome.ABORTED
    assert not reply.running()


async def test_a_drain_waits_and_never_cancels() -> None:
    """False at the grace, and the reply still going afterwards: the
    drain is how a polite close asks, and asking is not ending it."""
    release = asyncio.Event()
    finished: list[str] = []

    async def body() -> None:
        await release.wait()
        finished.append("the whole reply")

    reply = ReplyInFlight(None)
    reply.start(body())

    assert await reply.drain(0.02) is False
    assert reply.running()
    assert reply.outcome is None

    release.set()
    assert await reply.drain(1.0) is True
    # The body ran to its own end rather than being ended for it.
    assert finished == ["the whole reply"]


async def test_a_drain_counts_a_failed_reply_as_finished() -> None:
    """A reply that failed is not speaking any more, which is what the
    caller asked, and its exception is not the drain's to raise."""

    async def body() -> None:
        raise RuntimeError("the provider went away")

    reply = ReplyInFlight(None)
    reply.start(body())

    assert await reply.drain(1.0) is True
    # Retrieved here so the loop has nothing to complain about later.
    with pytest.raises(RuntimeError):
        await reply


async def test_a_drain_with_nothing_started_is_already_done() -> None:
    assert await ReplyInFlight(None).drain(0.0) is True


async def test_awaiting_a_reply_answers_what_its_body_ended_in() -> None:
    """The value stands where the task stood for whoever awaited it, so
    it has to answer the same way: the body's own exception, raised."""

    async def body() -> None:
        raise ValueError("inside the reply")

    reply = ReplyInFlight(None)
    reply.start(body())

    with pytest.raises(ValueError, match="inside the reply"):
        await reply


async def test_a_new_pass_has_counted_nothing() -> None:
    """What a pass is made with is what the reply's loop used to reset
    three fields to at its top."""
    fresh = SpeakingPass()

    assert (fresh.round, fresh.spoke, fresh.withheld) == (0, False, False)
