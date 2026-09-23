"""The conversations of one device session, through their own interface.

`SessionConversations` holds four things that used to be four fields
kept in step by statement order: each agent's current thread, every
thread's history, the store's handle for each thread's last write, and
the active pair. What can go wrong is exactly what the class exists to
make impossible, so each test below drives one rule and is named for
it: an agent's thread continues across activations, a move rebinds the
active agent and no other, an installed history is a copy, appends
land on the active thread, the pre-resume wait happens off the loop
with its bound, and the close path's purge sees each agent's current
thread and nothing a move replaced.

No storage and no session: the class takes neither, and a test here
that needed a database would be a design defect in the class.
"""

import asyncio
import re
import threading
from typing import Any, cast

from vinga_server.providers import Turn
from vinga_server.session_conversations import (
    RESUME_ACKNOWLEDGEMENT_S,
    Active,
    SessionConversations,
    mint,
)

DEVICE = "aa:bb:cc:dd:ee:01"

MINTED = re.compile(r"^[0-9a-f]{32}$")

# Two stored threads in the shape the runtime mints.
GALAXY = "1f0c1d2e3a4b5c6d7e8f90a1b2c3d4e5"
RECIPE = "2f0c1d2e3a4b5c6d7e8f90a1b2c3d4e5"

# Long enough that a wedged wait fails the test rather than the suite,
# and never reached when the code is correct.
TIMEOUT_S = 5.0


def owner() -> SessionConversations:
    return SessionConversations(DEVICE)


def test_the_device_is_the_one_it_was_built_for_and_nothing_is_active_yet() -> None:
    conversations = owner()

    assert conversations.device == DEVICE
    assert conversations.active is None


def test_a_mint_is_a_fresh_uuid_hex() -> None:
    first, second = mint(), mint()

    assert MINTED.match(first) and MINTED.match(second)
    assert first != second


def test_activation_mints_an_agents_thread_once_and_continues_it() -> None:
    """Sophia, let me talk to Nadia, back to Sophia: one device session,
    two threads, and the way back is Sophia's first thread rather than
    a third."""
    conversations = owner()

    poet = conversations.activate("poet")
    tutor = conversations.activate("tutor")
    back = conversations.activate("poet")

    assert poet.agent == "poet" and MINTED.match(poet.conversation)
    assert tutor.agent == "tutor" and MINTED.match(tutor.conversation)
    assert tutor.conversation != poet.conversation
    assert back == poet
    assert conversations.active == Active("poet", poet.conversation)


def test_starting_new_rebinds_the_active_agent_alone_onto_an_empty_thread() -> None:
    """The active agent is the second one activated, so a move that
    rebound whichever agent came first would be rebinding the wrong
    one rather than, by coincidence, the right one."""
    conversations = owner()
    poet = conversations.activate("poet")
    tutor = conversations.activate("tutor")
    conversations.history().append(Turn("user", "we were talking about the galaxy"))

    conversations.start_new(RECIPE)

    assert conversations.active == Active("tutor", RECIPE)
    assert conversations.history() == []
    # The other agent's thread is where it was, and the tutor's new
    # thread is the one a later activation continues.
    assert conversations.activate("poet") == poet
    assert conversations.activate("tutor") == Active("tutor", RECIPE)
    assert tutor.conversation != RECIPE


def test_reactivating_rebinds_the_active_agent_alone_onto_the_stored_thread() -> None:
    """The active agent is the second one activated, for the reason the
    fresh-conversation case above gives."""
    conversations = owner()
    poet = conversations.activate("poet")
    tutor = conversations.activate("tutor")
    stored = [Turn("user", "what is out there"), Turn("assistant", "Galaxies.")]

    conversations.reactivate(GALAXY, stored)

    assert conversations.active == Active("tutor", GALAXY)
    assert conversations.history() == stored
    assert conversations.activate("poet") == poet
    assert conversations.activate("tutor") == Active("tutor", GALAXY)
    assert tutor.conversation != GALAXY


def test_an_installed_history_is_a_copy() -> None:
    """What the store handed back cannot change under the session, and
    what the session appends cannot reach back into it."""
    conversations = owner()
    conversations.activate("poet")
    stored = [Turn("user", "what is out there")]

    conversations.reactivate(GALAXY, stored)
    stored.append(Turn("assistant", "added to the source afterwards"))
    conversations.history().append(Turn("assistant", "added to the session"))

    assert [turn.content for turn in conversations.history()] == [
        "what is out there",
        "added to the session",
    ]
    assert [turn.content for turn in stored] == [
        "what is out there",
        "added to the source afterwards",
    ]


def test_appends_land_on_the_thread_the_active_agent_is_on() -> None:
    conversations = owner()
    conversations.activate("poet")
    conversations.history().append(Turn("user", "for the poet"))

    conversations.activate("tutor")
    tutors = conversations.history()
    tutors.append(Turn("user", "for the tutor"))
    conversations.activate("poet")

    assert [turn.content for turn in conversations.history()] == ["for the poet"]
    conversations.activate("tutor")
    assert conversations.history() is tutors
    assert [turn.content for turn in tutors] == ["for the tutor"]


class GatedHandle:
    """An acknowledgement whose `wait` blocks until the test releases it,
    and which records what it was asked to wait for and whether the
    event loop kept turning while it blocked.

    `beats` is read at the start and at the end of the blocking wait,
    so `loop_ran` says whether the loop's heartbeat advanced in
    between: true where the wait runs on a thread of its own, and false
    where it blocks the loop, which stops the heartbeat with it."""

    def __init__(self, beats: Any) -> None:
        self._beats = beats
        self.entered = threading.Event()
        self.release = threading.Event()
        self.timeouts: list[float] = []
        self.loop_ran: bool | None = None

    def wait(self, timeout: float) -> bool:
        self.timeouts.append(timeout)
        before = self._beats()
        self.entered.set()
        self.release.wait(timeout)
        self.loop_ran = self._beats() > before
        return True


async def test_a_thread_nobody_wrote_to_is_not_waited_for() -> None:
    conversations = owner()
    conversations.activate("poet")
    handle = GatedHandle(lambda: 0)
    conversations.acknowledge(GALAXY, cast(Any, handle))

    await asyncio.wait_for(conversations.settled(RECIPE), TIMEOUT_S)

    assert handle.timeouts == []


async def test_the_wait_is_for_the_last_write_to_a_thread_and_not_an_earlier_one() -> None:
    """A thread written twice before a resume holds two handles over its
    life, and only the later one says the thread is complete: waiting on
    the earlier, already settled, would read the thread back one turn
    short while the latest turn is still queued. Both handles are open,
    so which one was waited on is what each recorded, not how long the
    wait took."""
    conversations = owner()
    conversations.activate("poet")
    earlier = GatedHandle(lambda: 0)
    latest = GatedHandle(lambda: 0)
    earlier.release.set()
    latest.release.set()
    conversations.acknowledge(GALAXY, cast(Any, earlier))
    conversations.acknowledge(GALAXY, cast(Any, latest))

    await asyncio.wait_for(conversations.settled(GALAXY), TIMEOUT_S)

    assert earlier.timeouts == []
    assert latest.timeouts == [RESUME_ACKNOWLEDGEMENT_S]


async def test_the_wait_for_a_written_thread_is_bounded_and_off_the_loop() -> None:
    """The handle blocks, so waiting on it on the loop would stall every
    other conversation this process holds. A heartbeat on the loop is
    what shows it kept turning: the handle is released only once the
    heartbeat has advanced past where it stood when the wait began."""
    conversations = owner()
    conversations.activate("poet")
    beats = 0

    async def heartbeat() -> None:
        nonlocal beats
        while True:
            beats += 1
            await asyncio.sleep(0)

    handle = GatedHandle(lambda: beats)
    conversations.acknowledge(GALAXY, cast(Any, handle))
    pulse = asyncio.create_task(heartbeat())
    try:
        waiting = asyncio.create_task(conversations.settled(GALAXY))
        deadline = asyncio.get_running_loop().time() + TIMEOUT_S
        while not handle.entered.is_set():
            assert not waiting.done(), "settled returned without waiting"
            assert asyncio.get_running_loop().time() < deadline, "the handle was never waited on"
            await asyncio.sleep(0)
        seen = beats
        while beats <= seen + 3:
            await asyncio.sleep(0)
        # A wait made on the loop has already run to its bound by the
        # time this line runs, with the heartbeat stopped throughout.
        assert handle.loop_ran is not False, "the wait blocked the event loop"
        assert not waiting.done(), "settled returned before its handle was released"
        handle.release.set()
        await asyncio.wait_for(waiting, TIMEOUT_S)
    finally:
        pulse.cancel()

    assert handle.loop_ran is True
    assert handle.timeouts == [RESUME_ACKNOWLEDGEMENT_S]


def test_the_purge_sees_each_agents_current_thread_and_none_a_move_replaced() -> None:
    conversations = owner()
    poet = conversations.activate("poet")
    tutor = conversations.activate("tutor")
    conversations.activate("poet")

    assert conversations.current_threads() == (poet.conversation, tutor.conversation)

    conversations.start_new(RECIPE)
    assert conversations.current_threads() == (RECIPE, tutor.conversation)

    conversations.reactivate(GALAXY, [])
    assert conversations.current_threads() == (GALAXY, tutor.conversation)
