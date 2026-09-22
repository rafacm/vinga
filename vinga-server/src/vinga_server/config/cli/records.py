"""The record: sessions, conversations, memory and the aggregates over them.

Four readings of the conversation store, all of them requests for the
reason the amendment to #190 gives: a command that touches the record
is a request like every other, and there is no second way in. A session
is one connection episode, a conversation is a durable thread with one
agent that may span several of them, a memory is what an agent, a board
or a thread holds, and a view is a question about days rather than
about any one of the three.

What its callers stop knowing: which of the three owners a memory verb
addressed and therefore which route it asks. The scope is the first
segment of every one of those paths, so the row reads it and chooses
the act, which is what keeps one noun over three resources from being
three nouns.
"""

import textwrap
from collections.abc import Mapping, Sequence
from typing import Any

from vinga_server.config import docgen
from vinga_server.config.loader import ConfigError
from vinga_server.config.printing import printable
from vinga_server.config.responses import (
    ConversationDetail,
    ConversationList,
    ConversationTurns,
    Erasure,
    MemoryConversations,
    MemoryCorrection,
    MemoryErasure,
    MemoryFact,
    MemoryFacts,
    MemoryOwners,
    MemoryState,
    MemoryStateErasure,
    MemoryStateKey,
    MetricRows,
    MetricViews,
    SessionDetail,
    SessionList,
    ThreadErasure,
)

from .acts import UNREADABLE_WRITE, Act, _path, _printed
from .input import (
    MEMORY_KEY_AT_A_TERMINAL,
    MEMORY_KEY_EMPTY,
    MEMORY_TEXT_AT_A_TERMINAL,
    MEMORY_TEXT_EMPTY,
    _typed,
)
from .invocation import Invocation
from .output import NOTHING_THERE, _cell, _columns, _names, _paged
from .reach import _NOTHING

# The session listing's columns. Upper case, because these are field
# names an operator matches against the API and the store rather than
# words about a board, and because a session id is a uuid hex whose
# column would otherwise be hard to find in a wall of them.
SESSION_COLUMNS = ("SESSION", "DEVICE", "AGENT", "STARTED", "CLOSED", "REASON", "TURNS")

NO_SESSIONS = (
    "this server has recorded no sessions matching that. Recording is off unless "
    "server.conversations.enabled says otherwise, and a session older than "
    "server.conversations.retention_days has been pruned"
)

# The thread listing's columns, upper case for the reason the session
# listing's are. `LAST-ACTIVE` rather than `LAST_ACTIVE`, because these
# are headings a person reads across a line and this one is two words.
CONVERSATION_COLUMNS = ("CONVERSATION", "AGENT", "TITLE", "LAST-ACTIVE", "TURNS")

NO_CONVERSATIONS = (
    "this server has recorded no conversations matching that. Recording is off unless "
    "server.conversations.enabled says otherwise, and a thread whose last activity is "
    "older than server.conversations.retention_days has been pruned"
)

# What `conversation show` prints where a thread answers no turns.
# Narrow and real rather than defensive: a thread is created by its
# first turn and deleted when it loses its last, so the way to see this
# is for an erasure to land between the two reads this one command
# makes.
#
# A thread recorded under text-off is NOT this case. It has its turns
# and none of the words in them, so its dialogue prints with the fixed
# placeholder on both speakers, which is what says the turn happened and
# nothing of it was stored.
NO_DIALOGUE = (
    "this conversation holds no turns. A thread is created by its first turn and "
    "deleted when it loses its last, so an empty answer here means the store moved "
    "between this command's two reads"
)

# Who said what, in front of a dialogue line. The user's label is fixed
# and this client's own; the agent's is the turn's own agent, bounded
# like every other value an answer carries.
SPEAKER = "you"

# What a deletion reports, in the order the rows go. Written out here so
# that the block below prints what the API answers rather than whatever
# a dictionary happened to iterate as, and so that a count added to the
# contract is a line added here rather than a line that quietly appears.
#
# One order for both erasures rather than a second tuple beside it.
# Erasing a thread answers six of these and not the two about sessions,
# because it touches neither the sessions its turns were spoken in nor
# their telemetry, so the block prints the counts its answer carries in
# this order and says nothing about the ones it does not.
#
# The last two are the memory the deleted threads took with them, which
# goes in the same transaction as their turns: what each conversation
# was keeping, and the facts it had forgotten.
#
# `facts` is last and is the memory noun's alone: an erasure of what an
# agent or a board remembers answers that one count and none of the
# others, and the block prints the counts its answer carries. One tuple
# rather than two, because what this states is the order counts are read
# in and there is one such order.
ERASED_COUNTS = (
    "sessions",
    "turns",
    "tool_invocations",
    "events",
    "conversations",
    "milestones",
    "state",
    "held_facts",
    "facts",
)

# The memory listings' columns, upper case for the reason the record's
# are. What an owner listing answers is short on every column, so it is
# a table; what a fact listing answers is content, so it is not.
MEMORY_OWNER_COLUMNS = ("OWNER", "FACTS")

MEMORY_CONVERSATION_COLUMNS = ("CONVERSATION", "STATE", "HELD")

NO_MEMORY_OWNERS = (
    "nothing is remembered under that scope. An agent is told something with the "
    "remember tool during a conversation, and a board's notes are made the same way; "
    "an operator writes none of it"
)

NO_MEMORY_CONVERSATIONS = (
    "no conversation is keeping anything. A conversation's ledger is written by the "
    "agent as it goes and is deleted with the thread, so an empty answer here is a "
    "deployment with nothing live and nothing recently forgotten"
)

NO_FACTS = (
    "this memory holds nothing. An owner with no rows is not an error: an agent that "
    "has been told nothing, a board nobody has made a note about, and a name that was "
    "never anybody's all read the same way"
)

NO_STATE = (
    "this conversation is keeping nothing. A ledger is written by the agent as the "
    "conversation goes and is deleted whole when the thread ends, so this is what a "
    "thread that has ended, or one that has been told nothing, reads as"
)

# What the named aggregates print
#
# Nothing here says what a view is. The answer carries the declaration
# `conversations/views.py` holds, column matrix and caveats and all, so
# these render what came back rather than a second description of it:
# the headings are the answer's columns upper-cased, and the statements
# under a listing are the ones the registry declares. A word written
# here would be a second home for a fact that has one.
METRIC_WINDOW = "days"

# Said once over the whole answer rather than on every row, which is
# what the guide's rule about a boundary asks for: both of the days the
# window names are inside it, and the two printed are the two the
# server used, so a caller that named neither reads its defaults here.
METRIC_WINDOW_ENDS = "both included"

NO_METRIC_ROWS = (
    "no rows on those days. Nothing was recorded in the window, which is also what a "
    "deployment that has recorded nothing at all answers: an empty window is an "
    "ordinary answer here and never a refusal"
)

# The markers the declared statements carry because they are written
# once for three surfaces, two of which render Markdown. A terminal is
# the third and is not one of them, so the emphasis and the code spans
# are taken out and nothing else is: the words, their order and their
# punctuation are the registry's.
_MARKDOWN_MARKERS = ("**", "`")

# A paragraph of those statements is wrapped where every other piece of
# generated prose in this repository wraps, which is a fixed width and
# therefore the same bytes into a pipe as onto a terminal.
METRIC_PROSE_WIDTH = docgen.PROSE_WIDTH

# What a held fact's line says, and what an active one's does not say at
# all. A word rather than a column, because held is the rare state and a
# column of blanks would be a column nobody reads.
FORGOTTEN_IN = "forgotten in"


def _session_listing(page: Mapping[str, Any]) -> str:
    """The sessions this deployment recorded, one line each.

    Columns, because every field of a session is short and the question
    this answers is which of several sessions is the one wanted: the id
    to address, the board it was held on, the agent it opened with, when
    it ran and how much was said.

    Every cell goes through `printable`, including the ones this server
    minted itself. What a cell can hold is not decided here: the agent
    name is an operator's, the device is a board's self-description, and
    a column that wrapped, moved the cursor or recolored the terminal
    would stop being a column. `CELL_LENGTH` rather than the wider bound
    the URLs are printed under, because a cell as wide as a title makes
    a table with one row in it.
    """
    items = page["items"]
    if not items:
        return f"{NO_SESSIONS}\n"
    rows = [SESSION_COLUMNS] + [
        (
            _cell(item["session"]),
            _cell(item["device"]),
            _cell(item["agent"]),
            _cell(item["started_at"]),
            _cell(item["closed_at"]),
            _cell(item["close_reason"]),
            _cell(item["turns"]),
        )
        for item in items
    ]
    return _columns(rows)


def _session_block(session: Mapping[str, Any]) -> str:
    """One session, whole, as lines rather than as columns.

    A block because half of what a session row carries is a list or a
    nested object, and a column holding one is a column that wraps. The
    order is the reading order: what it was, where it ran, how it ended,
    what it recorded, and which build recorded it.
    """
    lines = [
        f"session: {_cell(session['session'])}",
        f"  device: {_cell(session['device'])}",
        # The dated name beside the MAC, already stripped by the API's
        # answer and bounded here like every other cell: the changelog
        # promises the block and `GET /api/sessions/{session}` answer
        # the same field.
        f"  device_name: {_cell(session['device_name'])}",
        f"  client: {_cell(session['client'])}",
        f"  agent: {_cell(session['agent'])}",
        f"  agents: {_names(session['agents'] or ()) or NOTHING_THERE}",
        f"  protocol: {_cell(session['protocol'])}",
        f"  started: {_cell(session['started_at'])}",
        f"  closed: {_cell(session['closed_at'])}",
        f"  duration_s: {_cell(session['duration_s'])}",
        f"  close_reason: {_cell(session['close_reason'])}",
        f"  turns: {_cell(session['turns'])}",
        f"  events: {_cell(session['events'])}",
        f"  dropped: {_cell(session['dropped'])}",
        f"  telemetry: {_yes(session['telemetry'])}",
        f"  text: {_yes(session['text'])}",
        f"  server_version: {_cell(session['server_version'])}",
        f"  revision: {_cell(session['revision'])}",
    ]
    return "\n".join(lines) + "\n"


def _conversation_listing(page: Mapping[str, Any]) -> str:
    """The threads this deployment recorded, one line each.

    Columns for the reason the session listing has them, and one of
    these cells is content: a title is an utterance of the thread's,
    which came out of a room and through a transcriber, so it goes
    through the same bounding as everything else here and a null one is
    the fixed placeholder rather than an empty cell.
    """
    items = page["items"]
    if not items:
        return f"{NO_CONVERSATIONS}\n"
    rows = [CONVERSATION_COLUMNS] + [
        (
            _cell(item["conversation"]),
            _cell(item["agent"]),
            _cell(item["title"]),
            _cell(item["last_active_at"]),
            _cell(item["turns"]),
        )
        for item in items
    ]
    return _columns(rows)


def _conversation_block(thread: Mapping[str, Any]) -> str:
    """One thread's header, as lines rather than as columns.

    What the dialogue underneath it is a dialogue of: which thread,
    whose it is, what it is called and the two instants that bound it.
    `incomplete` is printed only when it is true, because a thread with
    nothing lost is the ordinary case and a line saying so on every
    thread would make the one that matters harder to see.
    """
    lines = [
        f"conversation: {_cell(thread['conversation'])}",
        f"  agent: {_cell(thread['agent'])}",
        f"  title: {_cell(thread['title'])}",
        f"  created: {_cell(thread['created_at'])}",
        f"  last active: {_cell(thread['last_active_at'])}",
    ]
    if thread["incomplete"]:
        lines.append("  incomplete: yes")
    return "\n".join(lines) + "\n"


def _dialogue_blocks(page: Mapping[str, Any]) -> str:
    """What was said, oldest first, two labelled lines per turn.

    Blocks rather than columns, and that is the whole reason this is not
    a table: a column holding an utterance is a column that wraps, and a
    wrapped column is not a column. The line structure is this
    renderer's alone, which is what the bounding is for: a newline
    inside an utterance is an unprintable and is substituted, so nothing
    a room said can add a line, move the cursor or recolor a terminal.
    """
    items = page["items"]
    if not items:
        return f"{NO_DIALOGUE}\n"
    return "\n".join(
        f"{SPEAKER}: {_cell(turn['heard'])}\n{_cell(turn['agent'])}: {_cell(turn['reply'])}\n"
        for turn in items
    )


def _memory_owner_listing(page: Mapping[str, Any]) -> str:
    """Who is remembering anything in one scope, one line each.

    Columns, because both fields are short and the question is which of
    several owners is the one wanted. An owner is an agent's name or a
    board's MAC, so it goes through the bounding every other name from an
    answer does.
    """
    items = page["items"]
    if not items:
        return f"{NO_MEMORY_OWNERS}\n"
    rows = [MEMORY_OWNER_COLUMNS] + [
        (_cell(item["owner"]), _cell(item["facts"])) for item in items
    ]
    return _columns(rows)


def _memory_conversation_listing(page: Mapping[str, Any]) -> str:
    """Which conversations hold memory, one line each: what each is
    keeping now, and what it has forgotten and could bring back."""
    items = page["items"]
    if not items:
        return f"{NO_MEMORY_CONVERSATIONS}\n"
    rows = [MEMORY_CONVERSATION_COLUMNS] + [
        (
            _cell(item["conversation"]),
            _cell(item["state"]),
            _cell(item["held_facts"]),
        )
        for item in items
    ]
    return _columns(rows)


def _memory_fact_blocks(page: Mapping[str, Any]) -> str:
    """What one memory holds, oldest first, a block per fact.

    Blocks rather than columns, and the fact itself printed whole. This
    command exists to show what an agent will be sent, so a concealed
    tail is exactly what the operator came to see, which is the rule
    `agent preview` already draws: a value that IS what the reader came
    for is not bounded, and nothing an answer carries may steer a
    terminal either way. A fact is stored as one line, so a newline
    arriving in one is a mangled answer and reads as mangled.

    The forgotten line is printed only where there is one. A held fact
    is the rare state and the conversation that can bring it back is
    what an operator needs to know about it; a line saying "not
    forgotten" on every other fact would bury it.
    """
    items = page["items"]
    if not items:
        return f"{NO_FACTS}\n"
    lines: list[str] = []
    for item in items:
        lines.append(f"{_cell(item['id'])}: {_stored(item['fact'])}")
        lines.append(f"  written: {_cell(item['at'])}")
        if item["forgotten_at"] is not None:
            lines.append(
                f"  forgotten: {_cell(item['forgotten_at'])}"
                f" ({FORGOTTEN_IN} {_cell(item['forgotten_in'])})"
            )
    return "\n".join(lines) + "\n"


def _memory_state_blocks(body: Mapping[str, Any]) -> str:
    """What one conversation is currently keeping, by key.

    Blocks and printed whole for the reason the facts are: both halves
    of an entry are content, the key as much as the value, since the
    model chose both.
    """
    items = body["items"]
    if not items:
        return f"{NO_STATE}\n"
    lines: list[str] = []
    for item in items:
        lines.append(f"{_stored(item['key'])}: {_stored(item['value'])}")
        lines.append(f"  updated: {_cell(item['updated_at'])}")
    return "\n".join(lines) + "\n"


def _memory_fact_line(fact: Mapping[str, Any]) -> str:
    """One corrected fact read back, the block the listing prints for
    it. One rendering rather than two, so what a correction answers and
    what the listing shows are the same shape."""
    return _memory_fact_blocks({"items": [fact]})


# What the named aggregates look like on a terminal
#
# Both renderings are a function of the answer and of nothing else. The
# columns are the ones the answer's own declaration lists, in its order,
# and the statements under them are the ones the registry declares and
# the API sends: a header written here would be a second encoding of a
# view's shape, and a caveat written here would be a fourth copy of a
# sentence that has one home (`conversations/views.py`).


def _readable(text: str) -> str:
    """One declared statement, as a terminal should read it.

    The statements are written once and rendered by three surfaces, two
    of which render Markdown: the committed reference and the API's own
    contract. A terminal is the third and is not one of them, so the
    emphasis and the code-span markers come out and nothing else does.
    The words, their order and their punctuation are the registry's, and
    what is removed cannot hide anything, since `_stored` has already
    turned every character a terminal would obey into a question mark.
    """
    plain = _stored(text)
    for marker in _MARKDOWN_MARKERS:
        plain = plain.replace(marker, "")
    return plain


def _wrapped(text: str, indent: str, hanging: str = "") -> list[str]:
    """A paragraph at the width every other piece of generated prose
    here is written to, indented.

    A fixed width rather than the terminal's, which is the output rule
    this module keeps everywhere: two runs of one answer are the same
    bytes on a laptop, on a runner and through a pipe. `hanging` is what
    a labelled statement's continuation lines are set in, so the label
    is the only thing at the left margin of its block; a paragraph with
    no label is set flush and passes none.
    """
    return [
        indent + line
        for line in textwrap.wrap(
            text,
            width=METRIC_PROSE_WIDTH - len(indent),
            break_long_words=False,
            break_on_hyphens=False,
            subsequent_indent=hanging,
        )
    ]


def _separated(blocks: Sequence[Sequence[str]]) -> list[str]:
    """Several blocks of lines as one, a blank line between them and
    none above the first or below the last."""
    return [
        line for index, block in enumerate(blocks) for line in ([""] if index else []) + list(block)
    ]


def _metric_note(label: str, value: object, indent: str = "  ") -> list[str]:
    """One labelled statement of a view's declaration."""
    return _wrapped(f"{label}: {_readable(str(value))}", indent, hanging="  ") or [
        f"{indent}{label}: {NOTHING_THERE}"
    ]


def _metric_columns(columns: Sequence[Mapping[str, Any]]) -> str:
    """A view's columns, each with its unit where it has one.

    The unit and not the SQL type, because what a reader about to quote
    a number needs is what the number is of; a column whose value has no
    unit says so in the declaration and is printed bare rather than with
    the word `none` after it.
    """
    return ", ".join(
        f"{_cell(column['name'])} ({_cell(column['units'])})"
        if str(column["units"]) not in ("none", "")
        else _cell(column["name"])
        for column in columns
    )


def _metric_view_block(view: Mapping[str, Any]) -> list[str]:
    """One view: how it is spelled, what it answers, what it cannot say,
    and the row it hands back."""
    return [
        _cell(view["view"]),
        *_metric_note("question", view["question"]),
        *_metric_note("denominator", view["denominator"]),
        *_metric_note("telemetry off", view["telemetry_off"]),
        *_metric_note("columns", _metric_columns(view["columns"])),
        *_metric_note("select from", view["relation"]),
    ]


def _metric_caveats(common: Sequence[Mapping[str, Any]]) -> list[str]:
    """What holds for every view, under the headings the registry gives
    them.

    Printed beside the numbers rather than left on a documentation page,
    because what a number here cannot be made to say is the half a
    reader is most likely to be missing at the moment they quote one.
    That is why the API sends them with every answer, and this is the
    third reader of the one declaration.

    Answered with the blank line that separates them from whatever they
    follow, and with nothing at all where a server sent none, so both
    renderings end the same way rather than each carrying its own
    conditional.
    """
    blocks = [
        [
            _cell(group["heading"]),
            *(
                line
                for note in group["notes"]
                for line in _wrapped(_readable(str(note)), "  ")
            ),
        ]
        for group in common
    ]
    return ["", *_separated(blocks)] if blocks else []


def _metric_view_listing(answer: Mapping[str, Any]) -> str:
    """The aggregates this deployment serves, a block each.

    Blocks rather than columns, because three of the five things worth
    reading about a view are sentences and one is a list, and a column
    holding either is a column that wraps.
    """
    lines = _separated([_metric_view_block(view) for view in answer["items"]])
    lines += _metric_caveats(answer["common"])
    return "\n".join(lines) + "\n"


def _metric_rows(answer: Mapping[str, Any]) -> str:
    """One view over one window: what answered, which days, the numbers,
    and what they cannot be made to say.

    The window is stated once over the whole answer rather than on every
    row, and it is the window the server used rather than the one that
    was typed, so a caller that named neither day reads its defaults
    here. The rows are columns because every cell of them is a number, a
    day or a short name.

    A null cell prints the placeholder every other listing here uses and
    never a zero: a rate with no denominator is null, and a renderer
    that wrote `0` for it would report a day nothing could have happened
    on as a day nothing went wrong on.

    The view's own telemetry-off sentence is here as well as on the
    listing, because the behaviour is per view and the numbers are what
    it qualifies: a reader about to quote one is on this rendering, not
    on the vocabulary page they read once.
    """
    view = answer["view"]
    columns = view["columns"]
    lines = [
        _cell(view["view"]),
        *_metric_note("question", view["question"]),
        *_metric_note("telemetry off", view["telemetry_off"]),
        f"{METRIC_WINDOW}: {_cell(answer['since'])} to {_cell(answer['until'])}"
        f", {METRIC_WINDOW_ENDS}",
        "",
    ]
    rows = answer["rows"]
    if not rows:
        lines.append(NO_METRIC_ROWS)
    else:
        # The headings are the answer's text the way the cells are, so
        # they go through the same bounding: uppercased first, because
        # the mangling `_cell` does must be the last hand on the value.
        table = [tuple(_cell(str(column["name"]).upper()) for column in columns)] + [
            tuple(_cell(row.get(column["name"])) for column in columns) for row in rows
        ]
        lines += _columns(table).splitlines()
    lines += _metric_caveats(answer["common"])
    return "\n".join(lines) + "\n"


def _stored(value: object) -> str:
    """One stored value printed whole, made safe for a terminal and
    nothing else.

    `printable` with no bound, which is a different rule rather than a
    bigger number and is the one that module states for a value that IS
    what the reader came for. A remembered fact and a ledger entry are
    that value: this command's whole purpose is to show what an agent
    will be sent, and a renderer that quietly cut one would make it lie
    about it. Every unprintable becomes a question mark, a newline
    included, so nothing a room said can add a line or drive the
    terminal.
    """
    if value is None:
        return NOTHING_THERE
    return printable(str(value), None) or NOTHING_THERE


def _erasure_block(taken: Mapping[str, Any]) -> str:
    """What a deletion took, one line per table.

    Counts rather than a sentence, because the caller of a purge named a
    set by selector and cannot know what was in it. Rendered in the
    order the rows go: the sessions named, the dialogue they held, and
    the threads and checkpoints left with nothing.
    """
    return (
        "\n".join(f"{name}: {taken[name]}" for name in ERASED_COUNTS if name in taken)
        + "\n"
    )


def _yes(value: object) -> str:
    """A boolean the API answered, as a word. Not through `_cell`: what
    a switch says is this client's own vocabulary, and a body that put
    something else there meets strict validation long before this."""
    return "yes" if value else "no"


# The conversation store's sessions: three acts on the two resources the
# store serves, and the one place in this grammar that reaches a schema
# the domain configuration knows nothing about. They are here for the
# reason the amendment to #190 gives: a command that touches the record
# is a request like every other, and there is no second way in.


def _sessions_path(args: Invocation) -> str:
    return _path("sessions")


def _session_path(args: Invocation) -> str:
    return _path("sessions", args.session)


def _session_filters(args: Invocation) -> dict[str, str]:
    """What narrows a listing. Only what was written: an absent flag is
    an argument the request does not carry, so the API's own defaults
    are the defaults, said once.

    The device is kept apart from the limit on one point, the rule
    `_metric_window` states: an explicitly empty value still travels, so
    `--device ''` meets the API's MAC refusal rather than reading as no
    filter and widening the listing to every board.
    """
    filters = {"limit": args.limit} if args.limit else {}
    if args.mac is not None:
        filters["device"] = args.mac
    return filters


def _purge_selectors(args: Invocation) -> dict[str, str]:
    """What a purge names. The same rule as the filters above, and the
    refusal for naming none of them is the API's: a purge that erased
    everything because its arguments were lost on the way is exactly
    what the endpoint refuses, and a second copy of that rule here would
    be a second sentence for one decision.

    The device travels when it was written, empty included, and here
    that rule is load-bearing rather than tidy: a dropped `--device ''`
    leaves `--before` alone with the set, so an erasure meant for one
    board takes that day from every board, and there is no undo.
    """
    selectors = {
        name: value
        for name, value in (("session", args.session), ("before", args.before))
        if value
    }
    if args.mac is not None:
        selectors["device"] = args.mac
    return selectors


LIST_SESSIONS = Act(
    method="GET",
    path=_sessions_path,
    query=_session_filters,
    answers=SessionList,
    render=_printed(_session_listing),
)

SHOW_SESSION = Act(
    method="GET",
    path=_session_path,
    answers=SessionDetail,
    render=_printed(_session_block),
)

DELETE_SESSION = Act(
    method="DELETE",
    path=_session_path,
    answers=Erasure,
    refusal=UNREADABLE_WRITE,
    render=_printed(_erasure_block),
)

PURGE_SESSIONS = Act(
    method="DELETE",
    path=_sessions_path,
    query=_purge_selectors,
    answers=Erasure,
    refusal=UNREADABLE_WRITE,
    render=_printed(_erasure_block),
)

# And the store's other projection, the thread. The same schema and a
# different question: a session is one connection episode, a
# conversation is a durable thread with one agent that may span several
# of them, and a turn belongs to both.


def _conversations_path(args: Invocation) -> str:
    return _path("conversations")


def _conversation_path(args: Invocation) -> str:
    return _path("conversations", args.conversation)


def _dialogue_path(args: Invocation) -> str:
    return _path("conversations", args.conversation, "turns")


def _conversation_filters(args: Invocation) -> dict[str, str]:
    """What narrows a thread listing. The rule the session filters
    follow: only what was written, so the API's own defaults are the
    defaults, said once. No cursor flags, deliberately, and the reason
    is the same as there: one invocation prints one page, and walking
    the record is what the API is for."""
    return {
        name: value
        for name, value in (("agent", args.name), ("limit", args.limit))
        if value
    }


LIST_CONVERSATIONS = Act(
    method="GET",
    path=_conversations_path,
    query=_conversation_filters,
    answers=ConversationList,
    render=_printed(_conversation_listing),
)

SHOW_CONVERSATION = Act(
    method="GET",
    path=_conversation_path,
    answers=ConversationDetail,
    render=_printed(_conversation_block),
)

READ_DIALOGUE = Act(
    method="GET",
    path=_dialogue_path,
    answers=ConversationTurns,
    render=_printed(_dialogue_blocks),
)

DELETE_CONVERSATION = Act(
    method="DELETE",
    path=_conversation_path,
    answers=ThreadErasure,
    refusal=UNREADABLE_WRITE,
    render=_printed(_erasure_block),
)

# And the third schema: what this deployment remembers.
#
# Three scopes with an owner apiece, addressed in the URL's own order,
# which is why the scope is a positional rather than a flag: it is the
# first segment of every one of these paths. Each act reads the field
# whose name is its own path parameter, and which act an invocation
# performs is the row's to choose from the scope it was given.


def _memory_owners_path(args: Invocation) -> str:
    return _path("memory", "agents")


def _memory_devices_path(args: Invocation) -> str:
    return _path("memory", "devices")


def _memory_conversations_path(args: Invocation) -> str:
    return _path("memory", "conversations")


def _agent_memory_path(args: Invocation) -> str:
    return _path("memory", "agents", args.name, "facts")


def _device_memory_path(args: Invocation) -> str:
    return _path("memory", "devices", args.mac, "facts")


def _agent_fact_path(args: Invocation) -> str:
    return _path("memory", "agents", args.name, "facts", args.fact)


def _device_fact_path(args: Invocation) -> str:
    return _path("memory", "devices", args.mac, "facts", args.fact)


def _memory_state_path(args: Invocation) -> str:
    return _path("memory", "conversations", args.conversation, "state")


def _memory_page(args: Invocation) -> dict[str, str]:
    """Which page of a memory listing, and how big.

    Only what was written, so the API's own defaults are the defaults,
    said once. One invocation is still one request, which is what keeps
    every wait here bounded by the endpoint's own timeout: the
    alternative is a command that walks a listing whose length nothing
    bounds, since conversations hold memory at thread-creation pace and
    no finite number could be derived for it.
    """
    return {
        name: value
        for name, value in (("limit", args.limit), ("cursor", args.cursor))
        if value
    }


def _correction(args: Invocation) -> object:
    """What a fact should say instead, read from a file or from standard
    input and never from an argument."""
    return {"fact": _typed(args, MEMORY_TEXT_AT_A_TERMINAL, MEMORY_TEXT_EMPTY)}


def _state_key(args: Invocation) -> object:
    """Which entry to clear, read from standard input, or no body at
    all, which is what clears the whole ledger.

    One act rather than two, because the two are one operation with and
    without a body: what makes them different requests is `--all`, and
    the API's own rule is that a request carrying no body means the
    ledger.
    """
    if args.all_of_it:
        return _NOTHING
    return {"key": _typed(args, MEMORY_KEY_AT_A_TERMINAL, MEMORY_KEY_EMPTY)}


LIST_AGENT_MEMORIES = Act(
    method="GET",
    path=_memory_owners_path,
    query=_memory_page,
    answers=MemoryOwners,
    render=_paged(_memory_owner_listing),
)

LIST_DEVICE_MEMORIES = Act(
    method="GET",
    path=_memory_devices_path,
    query=_memory_page,
    answers=MemoryOwners,
    render=_paged(_memory_owner_listing),
)

LIST_CONVERSATION_MEMORIES = Act(
    method="GET",
    path=_memory_conversations_path,
    query=_memory_page,
    answers=MemoryConversations,
    render=_paged(_memory_conversation_listing),
)

READ_AGENT_MEMORY = Act(
    method="GET",
    path=_agent_memory_path,
    query=_memory_page,
    answers=MemoryFacts,
    render=_paged(_memory_fact_blocks),
)

READ_DEVICE_MEMORY = Act(
    method="GET",
    path=_device_memory_path,
    query=_memory_page,
    answers=MemoryFacts,
    render=_paged(_memory_fact_blocks),
)

READ_STATE = Act(
    method="GET",
    path=_memory_state_path,
    answers=MemoryState,
    render=_printed(_memory_state_blocks),
)

CORRECT_AGENT_FACT = Act(
    method="PUT",
    path=_agent_fact_path,
    body=_correction,
    sends=MemoryCorrection,
    answers=MemoryFact,
    refusal=UNREADABLE_WRITE,
    render=_printed(_memory_fact_line),
)

CORRECT_DEVICE_FACT = Act(
    method="PUT",
    path=_device_fact_path,
    body=_correction,
    sends=MemoryCorrection,
    answers=MemoryFact,
    refusal=UNREADABLE_WRITE,
    render=_printed(_memory_fact_line),
)

FORGET_AGENT_FACT = Act(
    method="DELETE",
    path=_agent_fact_path,
    answers=MemoryErasure,
    refusal=UNREADABLE_WRITE,
    render=_printed(_erasure_block),
)

FORGET_DEVICE_FACT = Act(
    method="DELETE",
    path=_device_fact_path,
    answers=MemoryErasure,
    refusal=UNREADABLE_WRITE,
    render=_printed(_erasure_block),
)

CLEAR_AGENT_MEMORY = Act(
    method="DELETE",
    path=_agent_memory_path,
    answers=MemoryErasure,
    refusal=UNREADABLE_WRITE,
    render=_printed(_erasure_block),
)

CLEAR_DEVICE_MEMORY = Act(
    method="DELETE",
    path=_device_memory_path,
    answers=MemoryErasure,
    refusal=UNREADABLE_WRITE,
    render=_printed(_erasure_block),
)

CLEAR_STATE = Act(
    method="DELETE",
    path=_memory_state_path,
    body=_state_key,
    sends=MemoryStateKey,
    answers=MemoryStateErasure,
    refusal=UNREADABLE_WRITE,
    render=_printed(_erasure_block),
)

# What the three scopes mean on each verb, read by the rows below.
#
# One mapping per verb rather than one with three-tuples in it, because
# the verbs do not cover the same scopes: a conversation's ledger is
# read and cleared but never corrected, since what is in it is written
# by the agent as the conversation goes and an operator's correction of
# a live position would be a move nobody made.
_MEMORY_LISTINGS: dict[str, tuple[Act, Act]] = {
    "agent": (LIST_AGENT_MEMORIES, READ_AGENT_MEMORY),
    "device": (LIST_DEVICE_MEMORIES, READ_DEVICE_MEMORY),
    "conversation": (LIST_CONVERSATION_MEMORIES, READ_STATE),
}

_MEMORY_CORRECTIONS: dict[str, Act] = {
    "agent": CORRECT_AGENT_FACT,
    "device": CORRECT_DEVICE_FACT,
}

_MEMORY_DELETIONS: dict[str, tuple[Act, Act]] = {
    "agent": (FORGET_AGENT_FACT, CLEAR_AGENT_MEMORY),
    "device": (FORGET_DEVICE_FACT, CLEAR_DEVICE_MEMORY),
}

# What a scope this grammar does not have is answered with, and what a
# verb that does not reach a scope it does have is. Fixed sentences
# naming the words this grammar knows, never the word that was typed:
# what follows the verb is typed, and a mistyped command is where a
# value lands in an address field.
UNKNOWN_SCOPE = (
    "the first word after the verb says which memory: agent, device or conversation. "
    "What was typed is not quoted back"
)

STATE_IS_NOT_CORRECTED = (
    "a conversation's ledger is not corrected from here. It holds what is currently "
    "true in one conversation, written by the agent as the conversation goes, and an "
    "operator's correction of it would be a move nobody made; clear an entry instead, "
    "with memory delete conversation"
)

NO_FACT_TO_DELETE = (
    "this deletes one fact, named by the number the listing shows beside it, or the "
    "whole of a memory with --all. A number and --all are two different requests, so "
    "exactly one of them is given and a mistyped number can never mean everything"
)

NO_NUMBER_FOR_STATE = (
    "a conversation's ledger is addressed by the names its entries were written "
    "under, not by numbers. Clearing one reads its name from standard input, and "
    "--all clears the whole ledger"
)


def _memory_listing(args: Invocation) -> tuple[Act, ...]:
    """Which listing an invocation asked for: the owners in a scope
    where it named none, and one owner's own memory where it did.

    The same words one level up, which is what makes the pair one verb:
    `memory list agent` is who is remembering anything and
    `memory list agent poet` is what one of them remembers.
    """
    owners, one = _MEMORY_LISTINGS[_scope(args)]
    return (one,) if _owner(args) else (owners,)


def _memory_correction(args: Invocation) -> tuple[Act, ...]:
    """Which correction an invocation asked for.

    The address is three required positionals, so the only thing left to
    decide is the scope, and one of the three is refused rather than
    answered.
    """
    scope = _scope(args)
    if scope not in _MEMORY_CORRECTIONS:
        raise ConfigError(STATE_IS_NOT_CORRECTED)
    return (_MEMORY_CORRECTIONS[scope],)


def _memory_deletion(args: Invocation) -> tuple[Act, ...]:
    """Which deletion an invocation asked for.

    A number and `--all` are two different requests and exactly one of
    them is given, which is the whole reason the whole-scope form is a
    flag rather than an absent number: a mistyped number would otherwise
    mean everything.

    A conversation is the exception in shape rather than in rule: its
    entries are named rather than numbered and the name never rides
    argv, so what stands in for the number there is a read of standard
    input.
    """
    scope = _scope(args)
    if scope == "conversation":
        if args.fact:
            raise ConfigError(NO_NUMBER_FOR_STATE)
        return (CLEAR_STATE,)
    one, whole = _MEMORY_DELETIONS[scope]
    if bool(args.fact) == args.all_of_it:
        raise ConfigError(NO_FACT_TO_DELETE)
    return (whole,) if args.all_of_it else (one,)


def _scope(args: Invocation) -> str:
    """Which memory a command was asked about, refused where it is not
    one of the three."""
    if args.scope not in _MEMORY_LISTINGS:
        raise ConfigError(UNKNOWN_SCOPE)
    return args.scope


def _owner(args: Invocation) -> str:
    """The owner this invocation addressed, whichever scope it named.

    One of the three fields is filled per invocation, by the declaration
    that read the positional, so this is which of them it was rather
    than a second decision about the scope.
    """
    return args.name or args.mac or args.conversation


# The fourth reading of the same rows, and the one that answers about
# days rather than about a session, a thread or a memory.
#
# Requests like the three above them, and for the same reason the
# amendment to #190 gives: a command that touches the record is a
# request like every other, and there is no second way in. The plan for
# this surface promised a local path in its first draft and the review
# round took it out, so there is nothing here that reads a view
# directly; `vinga-server conversations views` renders what the views
# ARE from the declarations and reaches no database, and this asks a
# running server what is in them.


def _metrics_path(args: Invocation) -> str:
    return _path("metrics")


def _metric_path(args: Invocation) -> str:
    return _path("metrics", args.view)


def _metric_window(args: Invocation) -> dict[str, str]:
    """What bounds the answer. The rule the session filters follow: only
    what was written, so the API's own defaults are the defaults, said
    once and read back off the answer rather than computed here.

    The device is one of them and is not held to anything here: which
    groupings admit a filter, and what a MAC has to be, are the API's
    rules and its own fixed sentences, and a second vocabulary in front
    of them would be a second sentence per refusal. It is kept apart
    from the three above on one point only: an explicitly empty value
    still travels, so `--device ''` meets the API's MAC refusal rather
    than reading as no filter and widening the answer to every board.
    """
    window = {
        name: value
        for name, value in (
            ("since", args.since),
            ("until", args.until),
            ("group", args.group),
        )
        if value
    }
    if args.mac is not None:
        window["device"] = args.mac
    return window


LIST_METRICS = Act(
    method="GET",
    path=_metrics_path,
    answers=MetricViews,
    render=_printed(_metric_view_listing),
)

SHOW_METRIC = Act(
    method="GET",
    path=_metric_path,
    query=_metric_window,
    answers=MetricRows,
    render=_printed(_metric_rows),
)
