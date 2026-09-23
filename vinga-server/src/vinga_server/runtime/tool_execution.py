"""Executing one round's tool calls, and what a reply's offer of tools is.

The reply knows it has an offer, calls, and results. Everything between
those is here: how a call is classified, reserved on the turn's record,
coerced to the types its tool declared, bounded, dispatched to the
source that owns it, reported, and filed; where each offered tool came
from; and what a sentence withheld as a leaked call is reported as.

The runtime keeps what only it can do. A move (a handover, a new
conversation, a resume) rebinds conversations and ends the loop, so the
split of a round's calls into moves and the rest, and the moves
themselves, stay in `pipeline.py`; what reaches `run` is the plain half.
Whether a reply withheld anything is a fact about the whole reply, which
spans legs while an offer is one leg's, so the flag stays there too and
`withheld` only answers.

Nothing with a reply lifetime is held here. The turn a call is filed on
is an argument to every method that files, and the pair an event is
attributed to is read off the device session's conversations inside
each emit's thunk, at the moment the record is made: taken any earlier,
a handover landing between a reservation and its result would name the
wrong agent.
"""

import asyncio
import functools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from vinga_server.conversations.records import ToolInvocation
from vinga_server.events import SessionEvents, assembly, logger
from vinga_server.events.catalog import Variant
from vinga_server.events.values import Fragment
from vinga_server.providers import ToolCall, ToolDef, ToolResult
from vinga_server.runtime.speech import withhold_tool_shaped
from vinga_server.runtime.turns import BUILTIN, MCP, UNKNOWN, TurnUnderway, tool_source
from vinga_server.session_conversations import SessionConversations
from vinga_server.tools import names
from vinga_server.tools.arguments import with_lossless_coercions
from vinga_server.tools.source import ToolSource, no_such_tool, withheld

# How long a builtin or a device tool may take. Server tools use their
# own entry's tool_timeout_s. The device hears silence meanwhile, which
# is why this is not generous.
DEFAULT_TOOL_TIMEOUT_S = 15.0


def _coercions(sent: Mapping[str, Any], executing: Mapping[str, Any]) -> int:
    """How many of a call's arguments the coercion changed.

    Identity first, and for anything left alone it is the whole answer:
    `with_lossless_coercions` answers the object it was handed for every
    value it did not convert, so the same object is the same argument
    whatever it compares to. `NaN` is why that has to be the first
    question. It is not equal to itself, and both provider adapters
    decode with Python's permissive `json.loads`, which accepts one, so
    asking `!=` first reports an untouched `NaN` as coerced: a copy
    nobody needed and an event saying something that did not happen.

    The type is asked beside the value for the other half, because
    `100 == 100.0` and `True == 1` in Python. A float rewritten as the
    integer the schema declared is a different object AND a different
    type, and it has to count as a change here or the conversion would
    never leave this method.
    """
    return sum(
        1
        for name, held in executing.items()
        if held is not sent[name]
        and (type(held) is not type(sent[name]) or held != sent[name])
    )


def _tool_fragment(classified: ToolInvocation) -> Fragment:
    """The fragment a sentence about one call renders where its name
    would go, which is nothing at all for the two namespaces this
    surface may not name.

    One home for that decision. `events/assembly.py` renders whichever
    name it is handed and refuses nothing, deliberately: deciding is
    reading the classifier's source constants, which live next door in
    `runtime/turns.py`. So the decision is here, where those constants
    are, and it is here ONCE, so the plain line about unparseable
    arguments and the `tool_call` event beside it cannot come to
    disagree about which names are this application's to print.
    """
    return assembly.tool_fragment(
        classified.name if classified.source == BUILTIN else None,
        classified.entry if classified.source == MCP else None,
    )


def _tool_arguments_coerced(
    classified: ToolInvocation, agent: str, conversation: str, coerced: int
) -> Variant:
    """The `tool_arguments_coerced` event for one corrected call.

    The naming policy is `_tool_called`'s, read from the same two
    constants for the same reason: a builtin's name is this server's own
    word, an MCP call is named by the entry an operator configured, and
    a device tool or an invented name is named by nothing. One reading
    of it rather than a second, so the two events about one call cannot
    come to disagree about what may be printed.
    """
    return assembly.tool_arguments_coerced(
        agent,
        conversation,
        classified.source,
        classified.name if classified.source == BUILTIN else None,
        classified.entry if classified.source == MCP else None,
        coerced,
    )


def _tool_called(
    classified: ToolInvocation,
    agent: str,
    conversation: str,
    duration_s: float,
    is_error: bool,
    error_type: str | None,
) -> Variant:
    """Which of the three `tool_call` shapes describes this call.

    The selection is here rather than in `events/assembly.py` because it
    reads the classifier's own constants, and `runtime/turns.py` spells
    those locally on purpose: `TOOL_SOURCES` is one structure, and a
    second home for it in the event vocabulary would be a second
    structure that has to agree. What each shape is made of is the
    assembly module's; which one this call is, is the classifier's
    neighbour's.
    """
    if classified.source == BUILTIN:
        return assembly.builtin_tool_called(
            agent, conversation, classified.name, duration_s, is_error, error_type
        )
    if classified.source == MCP and classified.entry is not None:
        return assembly.mcp_tool_called(
            agent, conversation, classified.entry, duration_s, is_error, error_type
        )
    return assembly.unnamed_tool_called(
        agent, conversation, classified.source, duration_s, is_error, error_type
    )


@dataclass(frozen=True)
class Origin:
    """Where one offered tool came from, as this reply may name it.

    The classifier's two answers, kept together because they are one
    answer: the namespace, and the configured entry for the one
    namespace that has one. Frozen and built where the offer is taken,
    so what a withheld sentence is reported as is a fact about the
    reply rather than a question asked of the registries afterwards.

    Nothing far-side is in it. An MCP tool keeps the entry an operator
    wrote and never the server's own name for the tool, and a device
    tool keeps neither, which is the naming policy `tool_call` follows
    made structural at the point the provenance is captured.
    """

    source: str
    entry: str | None


# What a withholding that resolved to no single tool is reported as.
# One instance rather than a construction at each of the two sites that
# reads it, since it holds nothing about anything.
_UNKNOWN_ORIGIN = Origin(UNKNOWN, None)


def _sentence_withheld(
    source: str,
    entry: str | None,
    name: str | None,
    agent: str,
    conversation: str,
    characters: int,
) -> Variant:
    """Which of the three `sentence_withheld` shapes describes this
    withholding.

    `_tool_called`'s own selection, read off the same two constants, so
    the two records about one tool cannot come to disagree about which
    names this surface may print. A sentence that named no single tool
    arrives here classified `unknown` with no name, which is the shape
    that names nothing, and is where an argument-only leak fitting
    several offered tools lands.
    """
    if source == BUILTIN and name is not None:
        return assembly.builtin_sentence_withheld(agent, conversation, name, characters)
    if source == MCP and entry is not None:
        return assembly.mcp_sentence_withheld(agent, conversation, entry, characters)
    return assembly.unnamed_sentence_withheld(agent, conversation, source, characters)


@dataclass(frozen=True)
class Offer:
    """What one agent leg offers, taken once: the tools, their declared
    schemas by published name, and each one's origin.

    One value because the three are one answer. The schemas are the only
    place a tool's declared shape exists at reply time, and a call's
    coercion cannot see them otherwise; the origins are what a withheld
    sentence is named from, rather than the registries later on, because
    those move under a reply and a name matched against what this reply
    offered must be reported as what this reply offered it as (#391).
    Taken apart, any of the three could come from a different moment
    than the others; made together by `ToolExecution.offer`, they
    cannot.
    """

    tools: tuple[ToolDef, ...]
    schemas: Mapping[str, dict[str, Any]]
    origins: Mapping[str, Origin]


class ToolExecution:
    """One session's tool calls, from the offer to the results.

    Five verbs, in the order a leg uses them: `offer` once per leg,
    `withheld` per sentence spoken, and per round of calls `reserve`,
    `for_execution` and `run`. How long a call may take is decided
    inside `run`, because nothing else asks.

    `sources` are the three places a tool can come from, built by the
    runtime because the builtins are handed runtime state. The two
    questions about the registries arrive as callables and are asked at
    the moment of asking: a board can rediscover its tools and an apply
    can replace the MCP registry between two calls, so an answer taken
    at construction would be the wrong answer by the second reply.
    `remembering` is the reply's memory policy, asked before a call to a
    memory tool is answered at all.
    """

    def __init__(
        self,
        sources: tuple[ToolSource, ...],
        device_tools: Callable[[], Sequence[ToolDef]],
        owner_of: Callable[[str], str | None],
        events: SessionEvents,
        conversations: SessionConversations,
        remembering: Callable[[], bool],
    ) -> None:
        self._sources = sources
        self._device_tools = device_tools
        self._owner_of = owner_of
        self._events = events
        self._conversations = conversations
        self._remembering = remembering

    @property
    def _agent(self) -> str | None:
        """The agent talking now, read off the device session's
        conversations at the moment it is asked, which inside an emit's
        thunk is the moment the record is made."""
        active = self._conversations.active
        return None if active is None else active.agent

    @property
    def _conversation(self) -> str | None:
        """The thread the active agent is on, read the same way."""
        active = self._conversations.active
        return None if active is None else active.conversation

    def offer(self, agent: str) -> Offer:
        """What the active agent may reach this reply: the builtins that
        apply, the device's tools once discovery has finished, and the
        tools of the MCP servers it is granted that are up.

        Each source answers for itself, in the fixed order they were
        built in, so the merged list is the same list it always was and
        this method holds no rule about any one of them.

        Taken per reply rather than per session, so a server that came
        back, a device that finished discovering and a reload that
        landed mid-conversation are all picked up on the next
        utterance."""
        tools: list[ToolDef] = []
        for source in self._sources:
            tools.extend(source.snapshot(agent))
        return Offer(
            tools=tuple(tools),
            schemas={tool.name: tool.input_schema for tool in tools},
            origins=self._origins(tools),
        )

    def _origins(self, tools: Sequence[ToolDef]) -> dict[str, Origin]:
        """Where each tool this reply offers came from, classified while
        the offer is being made.

        Derived from the snapshot rather than gathered beside it, so
        the two cannot come to disagree about which tools this reply
        has: the names are the snapshot's names, and every one of them
        gets an answer.

        Read once, here, because the two registries behind it move. A
        board finishes a discovery and republishes its tools; an apply
        replaces the MCP registry whole, and an entry that owned a name
        can stop owning it or be replaced by another entry that does.
        Asking them at the moment a sentence is withheld would report a
        name matched against this reply's offer as whatever the world
        happens to say a round later: `unknown` for a board tool that
        has since been re-discovered, or somebody else's entry for a
        name an apply moved (#391). What the record has to say is what
        this reply offered, so the answer is taken when the offer is.

        Sanitized by construction. What is kept per name is the
        namespace it came from and, for an MCP tool, the configured
        entry an operator wrote, which are the two things the naming
        policy may print; the far side's own name never enters.
        """
        published = {one.name for one in self._device_tools()}
        return {
            tool.name: Origin(*tool_source(tool.name, published, self._owner_of(tool.name)))
            for tool in tools
        }

    def withheld(self, sentence: str, offer: Offer) -> bool:
        """Whether this sentence is a leaked tool call, in which case it
        has already been reported and nothing else happens to it.

        The one way into the guard: the rule and the record are one
        decision, and a caller that only asked the predicate would be a
        sentence dropped with nothing saying so.

        Nothing about the sentence is kept. `withhold_tool_shaped` hands
        back the tool it identified and a character count, and the
        emission below closes over those rather than over the text, so
        the withheld bytes reach no payload, no log line and no list
        this reply carries (#385).
        """
        return withhold_tool_shaped(
            sentence, offer.tools, functools.partial(self._report_withheld, offer.origins)
        )

    def _report_withheld(
        self, origins: Mapping[str, Origin], tool: str | None, characters: int
    ) -> None:
        """Say that a sentence was withheld.

        The name is named as this reply offered it, read out of the
        provenance taken with the snapshot the sentence was matched
        against, so a tool the model leaked into its speech is named on
        this record the way it would have been named on its `tool_call`
        and stays named that way however the registries move underneath.

        `unknown` is left for the one thing that genuinely is unknown:
        an argument-only match whose keys fit more than one offered
        tool, which names none of them because which one it was is what
        could not be decided. A name the guard answered is always one of
        the offered names, so the lookup below always has it; the
        default is what an unreachable third case would read as rather
        than a second meaning for the token.
        """
        origin = _UNKNOWN_ORIGIN if tool is None else origins.get(tool, _UNKNOWN_ORIGIN)
        self._events.emit(
            lambda: _sentence_withheld(
                origin.source,
                origin.entry,
                tool,
                self._agent,
                self._conversation,
                characters,
            )
        )

    def reserve(self, turn: TurnUnderway, calls: Sequence[ToolCall]) -> list[int]:
        """Put every call this round issued on the turn's record, at the
        position the model issued it, and answer where each one landed."""
        return [
            turn.reserve(self._classified(call, position))
            for position, call in enumerate(calls)
        ]

    def _classified(self, call: ToolCall, position: int) -> ToolInvocation:
        """The half of a call's record that is known before it runs:
        where its name came from, and what the model asked with it.

        Classified here rather than at the dispatch, and so before
        anything can stop the dispatch from happening. That is also what
        closes the set over the paths the routing hides: a malformed
        call, whose arguments are the model's own bytes rather than a
        JSON object, is flagged and carries none of them, and its name
        is classified anyway, because a model that mangles its arguments
        still says which tool it meant."""
        malformed = call.malformed_arguments is not None
        source, entry = tool_source(
            call.name,
            {tool.name for tool in self._device_tools()},
            self._owner_of(call.name),
        )
        return ToolInvocation(
            position=position,
            source=source,
            entry=entry,
            name=call.name,
            malformed=malformed,
            arguments=None if malformed else dict(call.arguments),
        )

    def for_execution(
        self, turn: TurnUnderway, call: ToolCall, slot: int, offer: Offer
    ) -> ToolCall:
        """One call as the far side receives it: the model's own, with
        every argument whose string form converts losslessly to the type
        the tool declared converted (`tools/arguments.py`).

        A copy, and an execution-only one. The reservation, the
        conversation record, the API's body and the working history keep
        the values the model sent, because "what the model passed" is
        what those surfaces promise and a string where the schema says
        integer is the fact an operator diagnosing a marginal model
        needs to see. What the device, the MCP server or the builtin is
        handed is what its own schema declared, since the far side is
        entitled to refuse anything else.

        The original object where nothing converted, so a reply that
        needed none of this allocates none of it, and `is` still holds
        across the boundary for everything the model got right.

        The event is emitted here and only where something converted,
        because this is a decision vinga owns and the record cannot
        stand in for it: the record's `arguments` is null under text-off
        and it retains no schema, so an original string beside a success
        does not say a coercion happened. `slot` is where this call was
        reserved, and the classification is read back from there rather
        than taken again, exactly as the dispatch reads it.
        """
        arguments = with_lossless_coercions(call.arguments, offer.schemas.get(call.name, {}))
        coerced = _coercions(call.arguments, arguments)
        if not coerced:
            return call
        classified = turn.reserved(slot)
        self._events.emit(
            lambda: _tool_arguments_coerced(
                classified, self._agent, self._conversation, coerced
            )
        )
        return replace(call, arguments=arguments)

    async def run(
        self, turn: TurnUnderway, calls: Sequence[tuple[int, ToolCall]]
    ) -> list[ToolResult]:
        """Execute one round's calls, none of them a move, each paired
        with the slot it was reserved at. Almost all of them run
        concurrently, since device and server tools are independent.

        The exception is the calls `names.ORDERED_TOOL_NAMES` names,
        which run first and one at a time, in the order the model issued
        them. Every one of them writes a memory, and two writes in one
        round decide each other: by the identity the model gave them, a
        ledger key or a fact's number, or by the prune a scope at its cap
        runs on every write. What is true afterwards is whichever ran
        last, so run concurrently the answer would be decided by which
        transaction reached the chain's lock first rather than by what
        the model asked for, and a set followed by a clear could leave
        the set.

        Before the rest rather than beside them, which costs a round
        trip nothing was waiting on and buys the simplest cancellation
        story there is: a barge-in during one of these leaves no
        dispatch running that nobody is awaiting."""
        answered: dict[int, ToolResult] = {}
        for slot, call in calls:
            if call.name in names.ORDERED_TOOL_NAMES:
                answered[slot] = await self._run_one(turn, call, slot)
        together = [(slot, call) for slot, call in calls if slot not in answered]
        answered.update(
            zip(
                (slot for slot, _ in together),
                await asyncio.gather(
                    *(self._run_one(turn, call, slot) for slot, call in together)
                ),
                strict=True,
            )
        )
        # Back into the order the model asked in, whatever order they
        # ran in: what the model reads next is a list of results, and a
        # list that reordered them would be this method describing a
        # round that did not happen.
        return [answered[slot] for slot, _ in calls]

    async def _run_one(self, turn: TurnUnderway, call: ToolCall, slot: int) -> ToolResult:
        """One tool call, bounded and never raising into the loop. Every
        failure becomes an error result: the model explains it in its
        own words, where a canned apology would be fixed-language and
        would throw away whatever the model could still salvage.

        `slot` is where this call was reserved on the turn's record, and
        it is filled in below only once there is something to say about
        it. A cancellation on the way through leaves it as reserved,
        which is what a call the user talked over looks like.

        `call` is the execution copy `_tool_loop` derived, so its
        arguments are the ones the far side is owed and the reserved
        claim's are the ones the model sent. The dispatch is routed by
        the claim and given the copy's arguments, which is the whole of
        the split: the record and the events keep the originals, and
        nothing but the source that runs the call sees the conversions.
        A malformed call carries none either way."""
        # The classification the reservation already holds, read back
        # rather than taken again: the `tool_call` event below says
        # where the name came from, the row at this slot says the same,
        # and asking twice could answer twice (an MCP reload between the
        # reservation and now is enough to move a name's owner).
        classified = turn.reserved(slot)
        dispatched = replace(
            classified,
            arguments=None if classified.malformed else dict(call.arguments),
        )
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            async with asyncio.timeout(self._timeout_for(classified)):
                content, is_error = await self._dispatch(call, dispatched)
            error_type = "tool_error" if is_error else None
        except TimeoutError:
            content, is_error = f'the tool "{call.name}" did not answer in time', True
            error_type = "TimeoutError"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            content, is_error = f'the tool "{call.name}" failed: {exc}', True
            error_type = type(exc).__name__
        elapsed = loop.time() - started
        self._events.emit(
            lambda: _tool_called(
                classified,
                self._agent,
                self._conversation,
                elapsed,
                is_error,
                error_type,
            )
        )
        turn.executed(slot, content, is_error, round(elapsed * 1000))
        return ToolResult(tool_call_id=call.id, content=content, is_error=is_error)

    async def _dispatch(self, call: ToolCall, classified: ToolInvocation) -> tuple[str, bool]:
        """Hand a call to the source that owns it, or answer it here.

        Three answers are nobody's tool to give and stay: a name this
        reply withheld, which does not exist for the length of it; a
        call whose arguments the model never closed, which no source
        should be asked to run; and a name none of them claims, which is
        what the model invented one looks like.

        The withheld one is first, and the order is the contract rather
        than a preference. Everything below it is an answer about a tool
        that exists: "the arguments were not a JSON object" is what a
        real tool says to a mangled call, so answering it for a
        withheld name would tell a model that the name is real and only
        its arguments were wrong. A withheld memory tool is answered
        exactly as a name nobody publishes is, whatever the model sent
        with it, and nothing about the call is logged, because there is
        no tool here to have been called badly.

        `classified` is the answer `_run_one` already has, passed in
        rather than recomputed, and it is the whole of what a source is
        told: the one line here that says anything about the call
        describes it exactly as its `tool_call` event does, two
        classifications of one call could disagree, and a source that
        resolved the name again could route around the reservation."""
        if withheld(classified.name, self._remembering):
            return no_such_tool(classified.name)
        if call.malformed_arguments is not None:
            # A plain line and not an event, and it obeys the same rule
            # as the event beside it (#120): the size of what the model
            # streamed rather than the bytes, since those are content,
            # and a name only where this server authored one. A device's
            # tool name and a name nobody publishes are the peer's own
            # bytes on a retained surface whether the line carrying them
            # is structured or not. The length is what tells a truncated
            # object from a model that answered in prose, and the record
            # carries the same fact as its `malformed` flag.
            named = _tool_fragment(classified).carried()
            logger.warning(
                "session %s: %s tool%s got %d characters of unparseable arguments",
                self._events.session_id,
                classified.source,
                named,
                len(call.malformed_arguments),
            )
            return "the arguments were not a JSON object; call again with valid ones", True
        assert self._agent is not None
        for source in self._sources:
            if source.owns(classified):
                return await source.dispatch(classified, self._agent)
        return no_such_tool(call.name)

    def _timeout_for(self, classified: ToolInvocation) -> float:
        """How long this call may take, answered by the source that owns
        it: a server tool gets its entry's configured timeout, builtins
        and device tools the module default above.

        Asked of the same claim the dispatch routes by, so a tool cannot
        be run against one entry's timeout and dispatched to another.
        Asking the registry by name here is what used to make that
        possible: a reload landing between the two answers
        differently."""
        for source in self._sources:
            if source.owns(classified):
                return source.timeout_for(classified)
        return DEFAULT_TOOL_TIMEOUT_S
