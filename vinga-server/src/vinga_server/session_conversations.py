"""The conversations of one device session, and the moves between them.

A device session is one connection episode from one board: it begins
when the device connects and ends when the connection does, powering
the board off included. The next connect is a new device session, and
it starts a new conversation with the device's default agent; a past
conversation comes back only through the conversation tools, from the
store. So this object lives exactly as long as the connection, and what
it holds is the live side of that connection's conversations:

- which thread each agent is on in this device session, minted the
  first time the agent is activated and continued on every later
  activation, so "Sophia, let me talk to Nadia, back to Sophia" is one
  device session touching two threads;
- the in-memory history of every thread it has been on, which is what
  a round is written against;
- the store's handle for the last turn written to each thread, which a
  resume waits on before it reads that thread back;
- and which agent is talking now, on which thread.

Those used to be four fields of the pipeline runtime and two attributes
of the events object, kept in step by the order of the statements that
wrote them. They are one object now because they are one fact seen four
ways: a move that rebinds an agent's thread without installing that
thread's history, or that installs the history without moving the
active pair, is a session answering from one thread and recording on
another. Each move below is one synchronous call with no await inside,
which is the ordering rule the runtime used to keep by being careful
and that this class keeps by construction.

The edge constructs it, the moment the device's MAC is normalized, and
hands it to the runtime factory beside the events object. The edge
rather than the runtime because the conversations belong to the device
session and must outlive whichever runtime is serving the active agent:
a handover may one day cross runtimes (#92), and the connection is the
only object with this lifetime. Both sides read the active pair here:
the runtime stamps its records with it, and the edge stamps
`speaking_started` and the capture manifest about a pair it never
chose.

What is deliberately NOT here: activating an agent (its providers, its
prompt, its endpointer), which is the runtime's; the offer protocol a
resume goes through, which is `runtime/resumption.py`'s; and storage,
which is `conversations/threads.py`'s. Nothing here opens a connection
or imports the store: the one type it names from there is imported for
the annotation alone.

One thing this class makes visible and does not change. A thread
resumed in the same device session is rebuilt from the store, not from
the history kept here, so a thread the session has already been on has
two copies kept in step only by the bounded wait in `settled`. That is
the general case seen from inside it: a thread from an earlier device
session has no copy here at all, and coming back to one is the
ordinary way a user resumes. Preferring the in-memory copy would be a
behavior change (the store's copy is budgeted and hydrated, this one is
not) and belongs to an issue of its own.

No user concept. The key is the agent, per device session. On a device
shared between speakers the current-thread map's key would become the
speaker and the agent, and `activate` would take the speaker; the
object would stay one per device session. Nothing here models a user
now.
"""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Both named for the annotations alone, so importing this module
    # executes nothing but the standard library. `conversations/__init__`
    # imports the store and with it the database layer, and an object
    # that takes no storage must not drag storage into every import of
    # it. `providers/__init__` re-exports the provider registry, which
    # builds every configured engine's client, for the reason
    # `device/boundary.py` defers its own provider names: that module
    # imports this one, and is read by callers that want its terms
    # without the provider layer.
    from vinga_server.conversations.records import Acknowledgement
    from vinga_server.providers.base import Turn

# How long a resume waits for the turn this device session last
# recorded on the target thread to be durably written, before that
# thread's context is rebuilt out of the store.
#
# The read-your-writes bound, and it exists for one scenario: switching
# away from a conversation and back to it inside one device session,
# where the turn that ended the first leg is still in the writer's
# queue while the resume is already reading the rows. Short, because it
# is a wait on the device's own turnaround and the writer commits at the
# marker the turn itself is; and bounded, because a database that is
# not answering must cost a resumed conversation its last turn rather
# than cost the user their reply.
RESUME_ACKNOWLEDGEMENT_S = 2.0


def mint() -> str:
    """A new conversation id: a uuid hex, the same shape and role as the
    session id.

    The one place an id is minted. An agent's first thread in a device
    session is minted by `activate`, and a fresh conversation is minted
    by the runtime's tool selection, which has to know the id before the
    move applies (the transition carries it, and the turn that ends the
    leg is recorded before the boundary) and then hands it to
    `start_new`. Minted here rather than by the store, because the
    boundary is decided at this seam and the id has to exist before the
    first turn it stamps."""
    return uuid.uuid4().hex


@dataclass(frozen=True)
class Active:
    """The agent talking and the thread it is talking on.

    One frozen value rather than two fields, so no reader can ever see
    the incoming agent beside the outgoing thread: a move replaces the
    pair whole."""

    agent: str
    conversation: str


class SessionConversations:
    """The live side of one device session's conversations.

    `device` is the board's normalized MAC, and this object is its one
    authority for the rest of the connection: the edge reads it back
    for the rejections and the manifest, the runtime for the address
    device memory is filed under where no record was resolved, and the
    events object took a one-time snapshot of it for the identity it
    stamps.

    `active` is None only before the first activation, which the
    runtime makes in its constructor; everything that reads the pair
    after that reads a value.
    """

    def __init__(self, device: str) -> None:
        self._device = device
        # The thread each agent is on now, one per agent this device
        # session has activated. Replaced for the active agent by the
        # two moves that change which thread it is on.
        self._current: dict[str, str] = {}
        # One history per thread, keyed by the conversation it belongs
        # to, including threads a move has since left: the history of a
        # thread an agent comes back to on a handover is what it said
        # the first time.
        self._histories: dict[str, list[Turn]] = {}
        # The store's handle for the last turn recorded on each thread.
        # Kept and never waited on here except by `settled`, which is
        # what keeps the recording path non-blocking.
        self._acknowledged: dict[str, Acknowledgement] = {}
        self._active: Active | None = None

    @property
    def device(self) -> str:
        """The device this session is on, as the edge normalized it."""
        return self._device

    @property
    def active(self) -> Active | None:
        """Who is talking now, on which thread. None before the first
        activation, and never again after it."""
        return self._active

    def history(self) -> "list[Turn]":
        """The history of the thread the active agent is on, as a list
        its callers append to.

        Mutable on purpose: the reply path appends the user's turn and
        the answer to it, and each agent leg appends its own, and every
        one of those appends has to land on the thread the round is
        written against. `setdefault` rather than a lookup, because a
        thread's first history is empty and minting one at activation
        would be a second place that knows a thread exists.

        Asserted rather than defaulted: an agent is activated before a
        runtime can be asked for anything, so a history asked for
        without one is a defect in the caller.
        """
        assert self._active is not None
        return self._histories.setdefault(self._active.conversation, [])

    def activate(self, agent: str) -> Active:
        """Make this agent the one talking, on its thread in this device
        session: minted the first time it is activated, continued on
        every later activation.

        The connect and the handover alike. What does not come with it
        is anything about the agent itself (its providers, its prompt,
        its endpointer), which is the runtime's activation, and the
        runtime's refusal of an agent the device is not bound to, which
        happens before this is called.
        """
        conversation = self._current.get(agent)
        if conversation is None:
            conversation = mint()
            self._current[agent] = conversation
        self._active = Active(agent, conversation)
        return self._active

    def start_new(self, conversation: str) -> None:
        """Move the active agent onto a fresh conversation, with an
        empty history.

        The id is the caller's, minted by `mint` before the boundary,
        because the transition that carries the move exists before the
        move applies."""
        self._move(conversation, [])

    def reactivate(self, conversation: str, history: "Sequence[Turn]") -> None:
        """Move the active agent onto a thread it has been on before,
        with the history the store returned for it.

        The history is copied rather than kept, so what the store handed
        back cannot be changed underneath this session and this
        session's appends cannot reach back into it."""
        self._move(conversation, list(history))

    def _move(self, conversation: str, history: "list[Turn]") -> None:
        """The two moves' shared body: rebind the active agent's thread,
        install the history, and replace the active pair, with no await
        between them.

        Installed rather than merged: a resume brings the thread's own
        history and a fresh conversation brings none, and either way
        what the thread held here before this line is what the store
        has already been told about. Nothing about the agent moves,
        because it is the same agent answering."""
        active = self._active
        assert active is not None
        self._current[active.agent] = conversation
        self._histories[conversation] = history
        self._active = Active(active.agent, conversation)

    def acknowledge(self, conversation: str, handle: "Acknowledgement") -> None:
        """Keep the store's handle for the turn just recorded on this
        thread, replacing the previous one. Never waited on here, which
        is what lets the recording path hand a turn over and walk
        away."""
        self._acknowledged[conversation] = handle

    async def settled(self, conversation: str) -> None:
        """Wait, briefly, for what this device session last wrote to
        that thread to be durably written.

        Read-your-writes for one case, and it is the case a session
        produces by itself: leaving a conversation and coming back to it
        without the connection closing in between. The turn that ended
        the first leg is on the writer's queue while this runs, and
        hydrating without it would rebuild the thread one turn short of
        what the user just said.

        It precedes the store read and cannot be one call with
        `reactivate`, which is the other half of the same rule: the read
        is the resumption flow's, and the history it returns is what
        `reactivate` installs, so the read sits between the two by
        necessity. What this class gives the rule is one home for both
        halves.

        A wait that expires is not an error and is not reported: the
        thread is rebuilt from what has landed, which is the same answer
        a slower database would have given a moment earlier. The wait
        itself is a blocking one on a handle the writer settles, so it
        happens off the loop every live conversation shares.
        """
        landed = self._acknowledged.get(conversation)
        if landed is None:
            return
        await asyncio.to_thread(landed.wait, RESUME_ACKNOWLEDGEMENT_S)

    def current_threads(self) -> tuple[str, ...]:
        """The thread each agent is on now, one per agent activated.

        What the close path purges where nothing is recorded, and
        deliberately each agent's CURRENT thread rather than every
        thread the device session touched: a thread a move replaced is
        not in it. Whether a purge should reach those too is a behavior
        question of its own, and on every deployment that purges today
        the two sets are equal, since the moves that replace a thread
        exist only where something is recorded."""
        return tuple(self._current.values())
