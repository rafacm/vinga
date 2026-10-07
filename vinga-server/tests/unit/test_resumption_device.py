"""The built-in agent's resumption, held to the device it talks
through (#612).

vinga's threads are the whole deployment's, so a search it makes is
held to the board the session is on, and a pick from such a search is
checked against the board the thread was begun on: the offer gate is
the first defense and the backlog's own answer is the second. Driven
through `Resumption` with the store written down as `StoredThreads`, so
the second defense is reached by an offer the store forged rather than
by a reach-in.
"""

from tests.support.stores import StoredThreads, a_backlog, a_candidate
from vinga_server.conversations import threads
from vinga_server.runtime.resumption import Resumed, Resumption
from vinga_server.tools import builtin

KITCHEN = "aa:bb:cc:dd:ee:01"
HALL = "aa:bb:cc:dd:ee:02"

THREAD = "9f0c1d2e3a4b5c6d7e8f90a1b2c3d4e5"


def store_offering(begun_on: str) -> StoredThreads:
    """A store whose search offers one vinga thread, begun on `begun_on`,
    to whatever device the search was held to."""
    return StoredThreads(
        found={"vinga": threads.Candidates(matched=True, found=(a_candidate(THREAD),))},
        held={THREAD: a_backlog(THREAD, agent="vinga", said=(("hi", "hello"),), device=begun_on)},
    )


async def test_a_search_held_to_the_device_asks_the_store_for_that_board() -> None:
    store = store_offering(HALL)
    flow = Resumption(store, 4096, 5.0, HALL)

    await flow.described("vinga", "the galaxy", on_device=True)

    assert store.held_to == [HALL]


async def test_an_unheld_search_asks_for_every_board() -> None:
    store = store_offering(HALL)
    flow = Resumption(store, 4096, 5.0, HALL)

    await flow.described("poet", "the galaxy")

    assert store.held_to == [None]


async def test_a_thread_begun_on_this_board_is_resumed() -> None:
    flow = Resumption(store_offering(HALL), 4096, 5.0, HALL)
    await flow.described("vinga", "the galaxy", on_device=True)

    resumed = await flow.resumed("vinga", THREAD)

    assert isinstance(resumed, Resumed)
    assert resumed.conversation == THREAD


async def test_an_offer_of_another_board_s_thread_is_refused_at_the_pick() -> None:
    """The store forged the offer: a search held to the hall answered a
    thread the kitchen began. The pick is refused by the backlog's own
    answer, as a thread of another agent's is."""
    flow = Resumption(store_offering(KITCHEN), 4096, 5.0, HALL)
    await flow.described("vinga", "the galaxy", on_device=True)

    assert await flow.resumed("vinga", THREAD) == builtin.NO_SUCH_CANDIDATE
    assert await flow.recap("vinga", THREAD) == builtin.NO_SUCH_CANDIDATE


async def test_an_unheld_search_resumes_a_thread_from_any_board() -> None:
    """Every other agent's threads are agent-scoped, as before: a thread
    begun on one board is resumed from another."""
    store = StoredThreads(
        found={"poet": threads.Candidates(matched=True, found=(a_candidate(THREAD),))},
        held={THREAD: a_backlog(THREAD, agent="poet", said=(("hi", "hello"),), device=KITCHEN)},
    )
    flow = Resumption(store, 4096, 5.0, HALL)
    await flow.described("poet", "the galaxy")

    assert isinstance(await flow.resumed("poet", THREAD), Resumed)


async def test_a_session_with_no_board_offers_nothing_held_to_one() -> None:
    store = store_offering(HALL)
    flow = Resumption(store, 4096, 5.0)

    answer = await flow.described("vinga", "the galaxy", on_device=True)

    assert answer == builtin.NOTHING_TO_RESUME
    assert store.asked == []


async def test_a_pick_is_held_to_the_device_by_who_is_picking_not_by_who_searched() -> None:
    """Review round 1, finding 1: an unscoped search's offer, picked by
    an agent that is the built-in one now, is checked against this board
    as a held search's would be. The restriction belongs to the agent
    selecting, whatever the search was."""
    flow = Resumption(store_offering(KITCHEN), 4096, 5.0, HALL)
    await flow.described("vinga", "the galaxy")

    assert await flow.resumed("vinga", THREAD, on_device=True) == builtin.NO_SUCH_CANDIDATE
    assert await flow.recap("vinga", THREAD, on_device=True) == builtin.NO_SUCH_CANDIDATE
    assert isinstance(await flow.resumed("vinga", THREAD), Resumed)
