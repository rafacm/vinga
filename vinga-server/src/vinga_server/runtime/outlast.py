"""Waiting a task out through the caller's own cancellation.

An owner's last step is sometimes a wait it must not walk away from:
the session's close ending the reply in flight, and then the purge of
the threads that reply was speaking on. A cancellation of that owner
while it waits is real and is owed to its caller, but raising it at
once would leave the work it was waiting for running with nobody
holding it, and the close path goes on to close the store that work
writes to. So the cancellation is held and raised afterwards, and this
is the loop that holds it.

A module of its own because it belongs to neither of the two owners
that use it: a reply's value would otherwise own a purge's lifetime,
and the reply's value would otherwise import the runtime that owns it.

What a caller stops having to know: that `asyncio.wait` rather than
`await` is what keeps a cancellation of the waiter from reaching the
task, that a cancellation can arrive more than once while it waits, and
that the first one is the one kept.
"""

import asyncio
from typing import Any


async def outlast(
    task: asyncio.Future[Any], *, hurry: bool = False
) -> asyncio.CancelledError | None:
    """Wait until `task` is done, however many times the caller is
    cancelled meanwhile, and answer the first of those cancellations,
    or None. With `hurry`, each one is passed on to the task as a
    `cancel()`; without it, the task is never cancelled from here.
    Never raises and never reads the task's outcome: retrieving it,
    and raising the answered cancellation once whatever it waited for
    is done, are the caller's.

    The first rather than the last, because it is the one that says why
    the caller is being ended, and every one after it asks the same
    thing again. `hurry` is for a task built to take a second cancel
    and end sooner for it; it is cooperative, so it expedites such a
    task and bounds nothing.
    """
    held: asyncio.CancelledError | None = None
    while not task.done():
        try:
            # asyncio.wait rather than await: a cancellation of this
            # waiter stops at the waiter, and the task is cancelled
            # only below, when the caller asked for that.
            await asyncio.wait([task])
        except asyncio.CancelledError as cancelled:
            if held is None:
                held = cancelled
            if hurry:
                task.cancel()
    return held
