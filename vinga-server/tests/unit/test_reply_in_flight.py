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
