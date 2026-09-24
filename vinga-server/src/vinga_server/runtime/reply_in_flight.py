"""The reply in flight, and the speaking pass inside it: one value per
lifetime.

The sibling of [`pipeline.py`](pipeline.py), and what it holds is the
reply state that used to be fields of the runtime reset by discipline.
A reply has three clocks, and two of them are here. A started reply
owns its task, how it ended and the utterance it answers, from the
floor's decision to the task's end; a speaking pass owns its round
count and whether any sentence went out or was withheld, from the top
of the reply's loop to its last leg. Each is a value made where its
lifetime begins, so being fresh is what making one means rather than a
line somebody has to remember to write. The third clock, the memory
permission per agent leg, stays with the loop that resolves it.

Nothing here knows what a reply does. The runtime hands `ReplyInFlight`
the coroutine to run and asks it the questions the device edge and the
floor ask about the reply in flight; it hands `SpeakingPass` nothing and
reads and writes its three fields.
"""

import asyncio
from collections.abc import Coroutine, Generator
from dataclasses import dataclass
from typing import Any

from vinga_server.events.values import ReplyOutcome
from vinga_server.runtime.outlast import outlast


class ReplyInFlight:
    """One started reply: its task, how it ended, and the utterance it
    answers.

    `utterance` is the id `turn_started` names and every record of the
    reply carries, or None for a reply no floor decision started. Only
    the runtime's `start_reply` mints one; a reply body driven without
    it is a reply nobody named, which is what its records then say.

    The latch is fresh because the value is new, which is the whole of
    what retires the window a runtime field had: a latch cleared inside
    the task would be cleared whenever the loop got round to starting
    it, and a latch cleared before the task is a line that has to be
    written in the right place. A value made per reply has neither.

    A value that is never started is a reply whose body runs on the
    caller's own task: it is still what the body latches its outcome on,
    and it is never running, since there is nothing of its own to run.
    """

    def __init__(self, utterance: str | None) -> None:
        self._utterance = utterance
        # How this reply ended, written once by whichever boundary ended
        # it and read by the body's `finally` that reports it. None
        # means nothing has ended it, which is what `completed` is.
        self._outcome: ReplyOutcome | None = None
        self._reply_task: asyncio.Task[None] | None = None

    @property
    def utterance(self) -> str | None:
        """The utterance this reply answers, or None where nothing named
        it."""
        return self._utterance

    @property
    def outcome(self) -> ReplyOutcome | None:
        """What ended this reply, or None while nothing has."""
        return self._outcome

    def start(self, body: Coroutine[Any, Any, None]) -> None:
        """Run this reply's body as a task of its own, from now on. Once
        per value: a second task would be a reply this value could no
        longer cancel or wait for."""
        assert self._reply_task is None, "a reply in flight starts once"
        self._reply_task = asyncio.create_task(body)

    def running(self) -> bool:
        """Whether this reply is still going: started, and not yet
        done, whichever way it will end."""
        return self._reply_task is not None and not self._reply_task.done()

    def latch(self, outcome: ReplyOutcome) -> None:
        """Write down how this reply ended, once.

        First writer wins, and that is the precedence rule whole: what
        ended a reply is whatever acted first, and everything after it
        is consequence. A barge-in that cancels a reply already inside
        its failure arm did not fail it.
        """
        if self._outcome is None:
            self._outcome = outcome

    async def cancel(self, outcome: ReplyOutcome) -> None:
        """End this reply as `outcome`, and see the cancellation through.

        Latched before the cancel rather than after it, so the body's
        own `finally` finds the outcome already there however promptly
        the cancellation lands: `CancelledError` cannot tell a barge-in
        from a shutdown, and the canceller is the one that knows which
        it is. Waited out, because a fire-and-forget cancel leaves the
        task not yet done, and an utterance finishing in that window
        would be dropped.

        The reply's own cancellation is suppressed, which is how the
        reply ending as asked looks from here; a cancellation of the
        caller is not. A caller cancelled while it waits (the session
        cap running out on a barge-in, say) sees its own
        `CancelledError`, and the reply goes on through its `finally`
        undisturbed, still held by whoever holds this value. A reply
        whose task ended in any other exception raises it out of this
        call, as awaiting the task always did.
        """
        self.latch(outcome)
        task = self._reply_task
        if task is None:
            return
        task.cancel()
        # asyncio.wait rather than await: a caller cancelled while it
        # waits sees its own CancelledError here, and the reply is not
        # cancelled a second time on its behalf, which would cut its
        # finally short.
        await asyncio.wait([task])
        if not task.cancelled():
            task.result()

    async def close(self, outcome: ReplyOutcome) -> None:
        """End this reply as `outcome` for an owner that is closing, and
        let nothing through until the reply's task is done.

        The sibling of `cancel`, and the two differ in exactly one
        decision: what a cancellation of the caller means. `cancel`'s
        callers run on the serve loop, where it means the caller is
        being ended, so it propagates at once and the reply is left to
        its owner. This one's caller is that owner's last step, where it
        means the close is being hurried: each cancellation is passed on
        to the reply as another `cancel()`, which its `finally` is built
        to take (the turn is recorded under it), and the first is raised
        only once the task is done, so nothing the reply still writes
        can land behind whatever the owner closes next.

        Hurried is not bounded. `Task.cancel()` is cooperative, and a
        tail that ignored it would keep this waiting; nothing in the
        reply's tail does.

        A reply that ended in anything other than its own cancellation
        raises it out of this call, as `cancel` does. With a
        cancellation held, the reply's exception is still read, so the
        loop never reports it as unretrieved with its text and chain,
        and it is dropped rather than chained: the caller is owed the
        cancellation and nothing else.
        """
        self.latch(outcome)
        task = self._reply_task
        if task is None:
            return
        task.cancel()
        held = await outlast(task, hurry=True)
        # Read whichever way this ends, before either raise below.
        failed = None if task.cancelled() else task.exception()
        # Both raised outside any `except` arm, so neither is chained
        # to anything.
        if held is not None:
            raise held
        if failed is not None:
            raise failed

    async def drain(self, grace_s: float) -> bool:
        """Let this reply finish, and answer whether it did within
        `grace_s`. Never cancels it."""
        task = self._reply_task
        if task is None or task.done():
            return True
        # asyncio.wait rather than await: a reply that failed is a reply
        # that finished, and its exception is not this method's to raise.
        done, _ = await asyncio.wait([task], timeout=grace_s)
        return bool(done)

    def __await__(self) -> Generator[Any, None, None]:
        """Wait for this reply's task, and answer exactly what awaiting
        the task answers: its result, or the exception it ended in,
        cancellation included."""
        assert self._reply_task is not None, "a reply never started has no task to await"
        return self._reply_task.__await__()


@dataclass
class SpeakingPass:
    """One pass of the reply's speaking loop: the rounds across its
    legs, and whether any sentence of it went out or was withheld.

    Made where the loop begins, so a reply's counts start from nothing
    by construction and a pass driven directly makes its own. `round`
    is counted up per generation across every agent the pass speaks
    through, which is what makes the generation after a handover a
    round of its own in the logs. `spoke` and `withheld` are the pair
    the empty-reply check reads: kept for the whole pass rather than per
    leg because a leg's own list is cleared at every boundary, and set
    as they happen because the withholding is decided a call away, where
    a sentence is matched against the tools one leg offered.
    """

    round: int = 0
    spoke: bool = False
    withheld: bool = False
