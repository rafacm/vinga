"""Waiting a task out through the caller's own cancellation, with no
session and no reply.

The two owners that use `outlast` are the session's close and the reply
value's own close, and their suites drive it through a whole runtime
(`test_turn_lifecycle.py`) or a reply body written for the test
(`test_reply_in_flight.py`). What those cannot do cheaply is cancel the
waiter any number of times and look at the task in between, which is
what the loop's own claims are about: which cancellation it answers,
when, and whether the task ever heard about it.

The cancellations carry a message each, which is how the first is told
from the second: a `CancelledError` is made fresh where it is thrown
into the waiter, so there is no instance outside to compare against.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from vinga_server.runtime.outlast import outlast

# Long enough that a wedged wait fails the assertion rather than the
# suite's own scheduling, and never reached when the code is correct.
TIMEOUT_S = 5.0


class Stubborn:
    """A task body that takes every cancellation it is sent, counts it,
    and goes on waiting until it is let go, which is a tail that is
    hurried and still has work to finish."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.hurried = 0
        self.nudged = asyncio.Event()

    async def body(self) -> str:
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.hurried += 1
                self.nudged.set()
        return "finished"


@pytest.fixture
async def stubborn() -> AsyncIterator[Stubborn]:
    """A `Stubborn` body, let go at teardown whatever the test did: one
    that takes every cancellation would otherwise outlive the loop's own
    attempt to cancel what a failing test left running."""
    body = Stubborn()
    yield body
    body.release.set()


async def settled() -> None:
    """Let every ready callback on the loop run, twice over: a
    cancellation delivered to the waiter and anything it passes on
    each take a turn of the loop to land."""
    for _ in range(4):
        await asyncio.sleep(0)


async def test_the_first_cancellation_is_answered_once_the_task_is_done(stubborn: Stubborn) -> None:
    body = stubborn
    task = asyncio.create_task(body.body())
    waiter = asyncio.create_task(outlast(task))
    await settled()

    waiter.cancel("first")
    await settled()
    waiter.cancel("second")
    await settled()

    assert not waiter.done()
    body.release.set()
    answered = await asyncio.wait_for(waiter, TIMEOUT_S)

    assert isinstance(answered, asyncio.CancelledError)
    assert answered.args == ("first",)
    assert task.done()


async def test_without_hurry_the_task_never_hears_of_it(stubborn: Stubborn) -> None:
    body = stubborn
    task = asyncio.create_task(body.body())
    waiter = asyncio.create_task(outlast(task))
    await settled()

    waiter.cancel()
    await settled()
    waiter.cancel()
    await settled()
    body.release.set()
    await asyncio.wait_for(waiter, TIMEOUT_S)

    assert body.hurried == 0
    assert task.result() == "finished"


async def test_with_hurry_each_cancellation_is_passed_on_once(stubborn: Stubborn) -> None:
    body = stubborn
    task = asyncio.create_task(body.body())
    waiter = asyncio.create_task(outlast(task, hurry=True))
    await settled()

    waiter.cancel()
    await asyncio.wait_for(body.nudged.wait(), TIMEOUT_S)
    body.nudged.clear()
    await settled()
    assert body.hurried == 1

    waiter.cancel()
    await asyncio.wait_for(body.nudged.wait(), TIMEOUT_S)
    await settled()
    assert body.hurried == 2

    body.release.set()
    answered = await asyncio.wait_for(waiter, TIMEOUT_S)
    assert isinstance(answered, asyncio.CancelledError)
    assert body.hurried == 2


async def test_a_task_already_done_is_answered_at_once() -> None:
    """At once meaning without suspending at all: the first step of the
    coroutine is its last."""
    task = asyncio.create_task(asyncio.sleep(0))
    await task

    waiting = outlast(task)
    with pytest.raises(StopIteration) as stopped:
        waiting.send(None)

    assert stopped.value.value is None


async def test_a_failed_task_is_left_for_the_caller_to_read() -> None:
    """Nothing raised here, cancellation held or not, and the task's
    exception still there to read, which is the caller's to do."""
    release = asyncio.Event()

    async def failing() -> None:
        await release.wait()
        raise RuntimeError("the task broke")

    quiet = asyncio.create_task(failing())
    loud = asyncio.create_task(failing())
    calm = asyncio.create_task(outlast(quiet))
    cancelled = asyncio.create_task(outlast(loud))
    await settled()
    cancelled.cancel("the caller")
    await settled()

    release.set()
    assert await asyncio.wait_for(calm, TIMEOUT_S) is None
    answered = await asyncio.wait_for(cancelled, TIMEOUT_S)

    assert isinstance(answered, asyncio.CancelledError)
    assert answered.args == ("the caller",)
    assert isinstance(quiet.exception(), RuntimeError)
    assert isinstance(loud.exception(), RuntimeError)
