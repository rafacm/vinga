"""Stored dialogue, as the context a model is handed.

The one module that knows what a thread read back out of the database
looks like to an LLM. Its callers hand it rows and a budget and get a
list of turns; what they stop knowing is how an utterance, a reply, the
tools that ran and the holes left by a stricter storage setting become
messages, and which of them a budget leaves room for.

Near-pure on purpose. Nothing here opens a connection or names a table:
the thread store hands it `records.StoredTurn` values, so the whole of
this module is exercised by writing turns down and reading messages
back, and a suite about what a resumed conversation reads like needs no
database at all. The input type is declared in `records.py` rather than
here, which is what keeps the store's read path off the provider
vocabulary a rendered turn is written in: reading a thread must not
load the model adapters, and the API that reads one is rendered without
them.

Five rules carry everything below.

**The unit is a whole stored turn.** A turn's user half, the tool
exchanges it kept and its reply are budgeted and truncated together,
never separately, so a reply can never be rebuilt without the utterance
it answered, nor a tool result without the call that asked for it.

**A turn's tool exchanges are rebuilt as the session kept them.** The
rows are grouped into the rounds they were made in (a round starts at
each call written at position zero), and only then is the session's
own rule applied: a call is kept when it has its result and its name.
A successful move answered nothing and a call a cut left unexecuted has
no result, so neither comes back; a malformed call comes back with no
arguments beside the error it was answered with, which is all the store
kept of it. A turn renders as the user's utterance, then per round that
kept anything an assistant turn holding its calls and a tool turn
holding their results, then the stored reply. The reply is the whole of
what was heard, so a round's preamble is not repeated in front of its
calls: the same words as the session held them, split once rather than
per round. Ids are minted the way the session mints them (`h<n>`,
counting the calls already rebuilt), so a call the resumed session
keeps next follows on from them. What a later request does with a past
exchange (clearing a result over the cap, turning a call to a tool it
does not offer into a note) is `runtime/history.py`'s, applied when the
request is built, exactly as for the session's own.

**What comes out opens with the user, and an assistant turn never
follows another one.** That is a property of the output rather than of
the input, because the input has two shapes that do not carry it. A
turn that was heard and never answered, with no reply and no exchange
kept (a reply provider that failed after the utterance was recorded),
has a user half and nothing else, and rendering it would put two user
messages in a row; a turn seeded by a move onto this thread has an
answer and nothing heard, because what the user said was said on the
thread they were moved off. The first is a hole, on the rule below. The
second is joined onto the turn before it, which is what it was: things
the assistant said and did with nothing from the user in between. Its
rounds stay structured, and where the joined pieces would put an
assistant's text straight in front of another assistant turn, the text
becomes the start of that turn's content, one line apart. A history
that would still open on an answer opens after it instead, since the
first message a provider is handed is the user's. A tool turn may be
followed by the next user turn, which is what a reply cut before it
spoke leaves, in the session and here alike.

**The budget is an estimate and says so, and it errs long.**
`ESTIMATED_CHARS_PER_TOKEN` is the whole of the arithmetic. A tokenizer
per provider would be exact for one of them and wrong for the rest, and
what the number is for is deciding how far back to read rather than
what a request will cost. Hydration does not know what a later request
will offer, and the offer decides whether each call goes structured or
as the longer degraded note, so a unit is charged as a request offering
no tools would send it: every call as its note, every result held to
the cap. That is never smaller than whatever a later request sends, so
a unit that fit still fits; the price is reading a thread whose tools
are all still offered a little less far back than an exact count would.

**A checkpoint is a pinned head, never a unit.** Where a thread has a
recap milestone, its text goes in front of everything as one assistant
message and the budget trims only the tail behind it. It is the one
thing here that truncation may not reach: it stands for turns that are
not in this list at all, and dropping it would silently delete the
oldest part of the conversation while the newest survived.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from vinga_server.conversations.records import StoredCall, StoredTurn
from vinga_server.providers import ToolCall, ToolResult, Turn
from vinga_server.runtime.history import Pair, as_sent, kept_round

# How many characters of stored text are counted as one token.
#
# Four, the ratio the vendors' own rules of thumb agree on for prose in
# a Latin script, and deliberately a constant rather than a per-provider
# tokenizer: an exact count for one model would be a wrong count for the
# next, and what this number decides is how far back into a thread to
# read, which a fifth of a token either way does not change. Stated in
# the reference documentation as the approximation it is.
ESTIMATED_CHARS_PER_TOKEN = 4

# How a recap milestone is put in front of the turns after it.
#
# The assistant's own voice, because it is: the recap was spoken by this
# agent to this user and stored byte for byte as it was heard, so a
# message attributed to anybody else would be the one line of this
# history that never happened. The frame says what it is standing in
# for, so the model does not read a summary as the last thing it said.
MILESTONE_NOTE = "(recap of the earlier part of this conversation: {text})"


@dataclass(frozen=True)
class Hydrated:
    """What a thread became, and what had to be left out of it.

    `rendered` and `skipped` count stored turns rather than messages:
    one turn is one unit here, and a caller reporting "I could not read
    three of these" means three turns. `over_budget` is the fact the
    recap offer turns on and the reason a resume can say it started from
    recent turns: the untruncated thread did not fit.

    `from_turn` and `after_turn` are the ids of the oldest and the
    newest stored turn this actually rendered, and null where it
    rendered none. They exist for the recap: a checkpoint records the
    range it really read, so a summary bounded by its own budget cannot
    claim coverage of the turns it dropped.
    """

    turns: tuple[Turn, ...] = ()
    rendered: int = 0
    skipped: int = 0
    over_budget: bool = False
    from_turn: int | None = None
    after_turn: int | None = None


def hydrated(
    stored: Sequence[StoredTurn], budget_tokens: int, milestone: str | None = None
) -> Hydrated:
    """The newest of these turns that fit in the budget, oldest first,
    behind whatever checkpoint stands for the rest.

    Walked from the newest backwards, because what a resumed
    conversation needs most is what was said last, and stopped at the
    first whole unit that does not fit. Everything older than that is
    gone; nothing inside a unit is ever cut, so the result never holds a
    reply whose question was truncated away.

    A turn with no answer on it, no reply and no exchange kept, is a
    hole rather than a unit, whether it stored nothing at all (text-off)
    or stored the utterance and never the reply (a provider that failed
    after the `heard` was recorded). A hole costs nothing and stops
    nothing, and rendering half of one would put two user messages in a
    row. A turn that kept an exchange and spoke nothing is not a hole:
    what it did is there to rebuild, and it ends on its tool turn, as
    the session that made it does.

    Holes are counted over the whole thread, not over the window the
    budget kept. What the count answers is whether the record has gaps
    in it, and a thread whose losses are all older than the cutoff has
    them just the same; counting only what the walk reached would report
    fewer the longer the conversation got.

    A turn with an answer and nothing heard is the first turn of a
    thread this session moved onto, and it is joined onto the turn
    before it, in that order and in the same unit: the two were said
    and done one after the other with nothing from the user in between.
    Its rounds stay structured; an answer it follows becomes the start
    of its first round's assistant turn rather than a second assistant
    message. One with nothing before it is dropped rather than led with,
    because the first message a provider is handed is the user's.
    Neither is a hole: nothing about that turn was lost.

    A unit is charged as a request offering no tools would send it,
    every call as its degraded note and every result held to the cap
    (`runtime.history.as_sent` with nothing offered), which is the
    largest form any later request can send it in.

    `milestone` is the text of the thread's latest recap checkpoint, and
    its caller has already left out the turns that checkpoint covers. It
    is pinned as the head and charged to the budget before any turn is,
    so a long tail trims against it rather than around it; it is never
    itself dropped, because what it stands for is not in this list and
    dropping it would delete the oldest part of the conversation while
    keeping the newest.

    The single newest unit is included even when it alone exceeds the
    budget, which is the answer for a thread with no checkpoint: an
    empty resume would be a worse answer than an over-budget one, and
    the budget is an estimate to begin with. With a checkpoint there is
    already something to say, so the head wins and `over_budget` says
    the tail did not fit.

    `over_budget` means a turn was left out, never that the head alone
    was large: what the flag decides is whether to offer a recap, and a
    recap of nothing new is not worth asking anybody about.
    """
    head = [] if milestone is None else [Turn("assistant", MILESTONE_NOTE.format(text=milestone))]
    # What each kept unit is, newest first while walking and turned
    # around once at the end: the utterance and the pieces said and done
    # after it, its own and those of the answers joined onto it.
    units: list[tuple[str, list[_Piece]]] = []
    rendered = 0
    spent = _tokens(head)
    over_budget = False
    # Pieces of turns with no utterance of their own, oldest first,
    # waiting for the turn they follow. Cleared onto it, and dropped
    # where the walk ends before one arrives. The id kept beside them is
    # the newest of the group, because a coverage boundary must name the
    # newest turn actually represented, and a joined answer is
    # represented.
    trailing: list[_Piece] = []
    joined = 0
    newest_trailing: int | None = None
    first: int | None = None
    last: int | None = None
    for turn in reversed(stored):
        pieces = _pieces(turn)
        if not pieces:
            continue
        if not turn.heard:
            trailing[:0] = pieces
            joined += 1
            if newest_trailing is None:
                newest_trailing = turn.id
            continue
        unit = (turn.heard, [*pieces, *trailing])
        cost = _cost(unit)
        if (units or head) and spent + cost > budget_tokens:
            over_budget = True
            break
        if not units and not head and cost > budget_tokens:
            # The newest unit, over the budget on its own, taken anyway.
            over_budget = True
        units.append(unit)
        spent += cost
        rendered += 1 + joined
        first = turn.id
        if last is None:
            last = turn.id if newest_trailing is None else newest_trailing
        trailing = []
        joined = 0
        newest_trailing = None
    out: list[Turn] = list(head)
    for heard, pieces in reversed(units):
        out.extend(_rendered(heard, pieces, out))
    return Hydrated(
        turns=tuple(out),
        rendered=rendered,
        skipped=sum(1 for turn in stored if not _pieces(turn)),
        over_budget=over_budget,
        from_turn=first,
        after_turn=last,
    )


# One thing a stored turn said or did after its utterance: a round's
# kept calls with their results, or the reply.
_Piece = str | tuple[Pair, ...]


def _pieces(turn: StoredTurn) -> list[_Piece]:
    """What this turn said and did after its utterance, in order: each
    round that kept a call, then the reply. Empty for a hole."""
    pieces: list[_Piece] = [kept for kept in _rounds(turn.calls) if kept]
    if turn.reply:
        pieces.append(turn.reply)
    return pieces


def _rounds(calls: Sequence[StoredCall]) -> list[tuple[Pair, ...]]:
    """The calls grouped into the rounds they were made in, and only
    then each round's kept ones: grouping after a filter could drop the
    zero that says where a round began."""
    rounds: list[list[StoredCall]] = []
    for call in calls:
        if call.position == 0 or not rounds:
            rounds.append([])
        rounds[-1].append(call)
    return [tuple(_pair(call) for call in one if _kept(call)) for one in rounds]


def _kept(call: StoredCall) -> bool:
    """The session's rule, read off a row: a call is kept when it has
    its result, and a row with no name has nothing to call it by."""
    return call.result is not None and call.name is not None


def _pair(call: StoredCall) -> Pair:
    """One kept row as the call and result the history holds. Its id is
    minted where the round is placed; a malformed call has no arguments,
    because the store kept none of what the model streamed."""
    assert call.name is not None and call.result is not None
    arguments = {} if call.malformed or call.arguments is None else call.arguments
    return Pair(
        ToolCall(id="", name=call.name, arguments=arguments),
        ToolResult(tool_call_id="", content=call.result, is_error=call.is_error),
        call.source,
        call.entry,
    )


def _rendered(heard: str, pieces: Sequence[_Piece], before: Sequence[Turn]) -> list[Turn]:
    """One unit as messages, ids minted against `before` and what the
    unit renders ahead of each round.

    An assistant's text is never left directly in front of another
    assistant turn: it becomes the start of that turn's content, one
    line apart, which is the joining rule for two answers and keeps a
    joined turn's calls structured."""
    out = [Turn("user", heard)]
    for piece in pieces:
        if isinstance(piece, str):
            added = [Turn("assistant", piece)]
        else:
            added = kept_round([*before, *out], "", piece)
        for turn in added:
            last = out[-1]
            if turn.role == "assistant" and last.role == "assistant" and not last.tool_calls:
                text = "\n".join(part for part in (last.content, turn.content) if part)
                out[-1] = replace(turn, content=text)
            else:
                out.append(turn)
    return out


def _cost(unit: tuple[str, Sequence[_Piece]]) -> int:
    """What this unit is charged: the unit as a request offering no
    tools would send it, which degrades every call and holds every
    result to the cap, and which no other request exceeds."""
    messages = _rendered(*unit, ())
    return _tokens(as_sent(messages, len(messages), frozenset()).turns)


def _tokens(messages: Sequence[Turn]) -> int:
    """What these messages are estimated to cost, rounded up so that a
    unit with anything in it costs at least one token."""
    characters = sum(len(message.content) for message in messages)
    return -(-characters // ESTIMATED_CHARS_PER_TOKEN)


__all__ = [
    "ESTIMATED_CHARS_PER_TOKEN",
    "MILESTONE_NOTE",
    "Hydrated",
    "hydrated",
]
