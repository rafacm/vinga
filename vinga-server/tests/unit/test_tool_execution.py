"""Tool execution through its own verbs, with no session around it.

The session suites (`test_session_tools.py`, `test_session_record.py`,
`test_session_withheld.py`) reach every branch of this module through a
reply. What they cannot say directly is the two things a reply only
implies: in which order a round's calls are dispatched and answered,
and where each offered tool is said to have come from. So those are
asked here of a `ToolExecution` built over sources this file makes,
which is the whole of what the module is handed.
"""

import asyncio
from collections.abc import Sequence

from vinga_server.conversations.records import ToolInvocation
from vinga_server.events import SessionEvents
from vinga_server.providers import ToolCall, ToolDef
from vinga_server.runtime.tool_execution import Origin, ToolExecution
from vinga_server.runtime.turns import TurnUnderway
from vinga_server.session_conversations import SessionConversations
from vinga_server.tools import names


def a_tool(name: str) -> ToolDef:
    return ToolDef(name=name, description=name, input_schema={"type": "object"})


class Listed:
    """A source that publishes a fixed list and owns nothing, which is
    all an offer asks of one."""

    def __init__(self, *published: str) -> None:
        self._published = [a_tool(name) for name in published]

    def snapshot(self, agent: str) -> Sequence[ToolDef]:
        return self._published

    def owns(self, claim: ToolInvocation) -> bool:
        return False

    async def dispatch(self, claim: ToolInvocation, agent: str) -> tuple[str, bool]:
        raise AssertionError("an offer never dispatches")

    def timeout_for(self, claim: ToolInvocation) -> float:
        raise AssertionError("an offer never bounds a call")


class Journal:
    """A source that owns every name and writes down when each call
    started and finished, so the order a round ran in is a list.

    Every call yields to the loop before it finishes, and the ones
    named in `slow` yield for longer, so two calls running at once
    interleave in the journal rather than happening to line up."""

    def __init__(self, slow: frozenset[str] = frozenset()) -> None:
        self.journal: list[str] = []
        self._slow = slow

    def snapshot(self, agent: str) -> Sequence[ToolDef]:
        return []

    def owns(self, claim: ToolInvocation) -> bool:
        return True

    async def dispatch(self, claim: ToolInvocation, agent: str) -> tuple[str, bool]:
        self.journal.append(f"start {claim.name}")
        await asyncio.sleep(0.05 if claim.name in self._slow else 0)
        self.journal.append(f"end {claim.name}")
        return claim.name, False

    def timeout_for(self, claim: ToolInvocation) -> float:
        return 5.0


def execution_over(
    *sources: object,
    device: Sequence[str] = (),
    owners: dict[str, str] | None = None,
) -> tuple[ToolExecution, TurnUnderway]:
    """A `ToolExecution` over these sources for an active poet, and a
    turn to file its calls on."""
    conversations = SessionConversations("aa:bb:cc:dd:ee:01")
    active = conversations.activate("poet")
    known = owners or {}
    execution = ToolExecution(
        sources=tuple(sources),  # type: ignore[arg-type]
        device_tools=lambda: [a_tool(name) for name in device],
        owner_of=known.get,
        events=SessionEvents("tool-execution"),
        conversations=conversations,
        remembering=lambda: True,
    )
    return execution, TurnUnderway(active.conversation, active.agent, None)


# --- the order a round runs in ----------------------------------------


async def test_the_memory_writes_run_first_one_at_a_time_and_then_the_rest() -> None:
    """The model's order among the writes, and every write done before
    anything else is dispatched; then the rest, all of them started
    before any of them finishes."""
    assert {names.REMEMBER, names.SET_STATE} <= set(names.ORDERED_TOOL_NAMES)
    journal = Journal(slow=frozenset({"lamp"}))
    execution, turn = execution_over(journal)
    calls = [
        ToolCall(id="a", name="lamp"),
        ToolCall(id="b", name=names.REMEMBER),
        ToolCall(id="c", name="kettle"),
        ToolCall(id="d", name=names.SET_STATE),
    ]
    slots = execution.reserve(turn, calls)

    await execution.run(turn, list(zip(slots, calls, strict=True)))

    assert journal.journal == [
        "start remember",
        "end remember",
        "start set_state",
        "end set_state",
        "start lamp",
        "start kettle",
        "end kettle",
        "end lamp",
    ]


async def test_the_results_come_back_in_the_models_order() -> None:
    """Whatever order the calls ran and finished in, which here is
    neither the model's order nor each other's."""
    journal = Journal(slow=frozenset({"lamp"}))
    execution, turn = execution_over(journal)
    calls = [
        ToolCall(id="a", name="lamp"),
        ToolCall(id="b", name=names.REMEMBER),
        ToolCall(id="c", name="kettle"),
        ToolCall(id="d", name=names.SET_STATE),
    ]
    slots = execution.reserve(turn, calls)

    results = await execution.run(turn, list(zip(slots, calls, strict=True)))

    assert [(one.tool_call_id, one.content) for one in results] == [
        ("a", "lamp"),
        ("b", "remember"),
        ("c", "kettle"),
        ("d", "set_state"),
    ]
    # And each call is filed at the slot it was reserved at.
    assert [turn.reserved(slot).result for slot in slots] == [
        "lamp",
        "remember",
        "kettle",
        "set_state",
    ]


# --- where an offered tool came from ----------------------------------


def test_an_offer_says_where_each_of_its_tools_came_from() -> None:
    """One tool from each of the three namespaces, each named as the
    naming policy allows: a builtin by nothing but its namespace here,
    a board's tool the same, and a server's tool by the entry an
    operator configured."""
    execution, _ = execution_over(
        Listed(names.REMEMBER),
        Listed("self_lamp"),
        Listed("home__lamp"),
        device=("self_lamp",),
        owners={"home__lamp": "home"},
    )

    offer = execution.offer("poet")

    assert [tool.name for tool in offer.tools] == [names.REMEMBER, "self_lamp", "home__lamp"]
    assert dict(offer.origins) == {
        names.REMEMBER: Origin("builtin", None),
        "self_lamp": Origin("device", None),
        "home__lamp": Origin("mcp", "home"),
    }
    assert dict(offer.schemas) == {tool.name: tool.input_schema for tool in offer.tools}
