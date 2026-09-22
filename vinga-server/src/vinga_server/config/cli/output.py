"""Output: which stream a thing goes to, and how a value is written.

The renderers every family shares, and the rule that decides the
stream. What a command answered is the artifact and goes to stdout;
what is true of this invocation is a notice and goes to stderr, under
it rather than above it, which is what the flushes here are for, since
stderr is unbuffered and stdout is not.

What its callers stop knowing: how a table is aligned, how wide a value
may be before a cell stops being a cell, that a null prints as a fixed
placeholder rather than as nothing, and which of the two streams a
sentence belongs on. A family writes a listing and hands it over; the
bounding, the columns and the notice are decided once, here.
"""

import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, cast

import yaml

from vinga_server.config.printing import printable
from vinga_server.config.responses import Applies

from .reach import PROGRAM

NOTHING_IMPORTED = (
    "the document names no section of the configuration, so nothing was imported. An\n"
    "imported document's top-level keys are the sections of the domain configuration"
)

# What a listing shows where the row has nothing. One character, fixed,
# and never derived from the answer: a null device, agent or close is an
# ordinary state of a session, and an empty cell would read as a column
# that failed to render.
NOTHING_THERE = "-"

# How much of any one value reaches a cell or a block line. Narrower
# than the glimpse the URLs are bounded to, because these land in a
# table: what a column is for is comparing one row against the next, and
# a cell as wide as a title makes a table with one row in it. A session
# id is 32 characters and a stamp is 32, so nothing this server minted
# is truncated by it.
CELL_LENGTH = 64

# What a page that is not the whole of a listing says, on stderr,
# because it is about this invocation rather than about the artifact:
# this page ended here and there is more, and what to type for the rest.
#
# The record's two nouns print no such notice and take no cursor, and
# the difference is what each listing is of. A session list is a window
# onto a log that only grows, where the newest page is the reading
# somebody opened it for. A memory is a bounded thing being audited: an
# agent may hold a thousand facts, a page holds two hundred, and a
# listing whose rest could not be reached would make this verb's own
# help a claim the grammar cannot keep.
MORE_PAGES = "this is one page and there is more; the next one is --cursor"

# The bound a value is printed under when it has none
#
# Three values are printed this way: the two an identity answer carries,
# which is where the rule was written, and a boundary sentence a server
# of any age composed, whose tail is the state it exists to state.
#
# `GLIMPSE_LENGTH` is the bound for far-side text quoted inside a
# sentence, and neither of these is that. The URL is the thing this
# command exists to hand a person, and a truncated URL is not a shorter
# answer, it is a wrong one: it is typed into a captive portal by hand
# and fails there, silently, with nothing on the terminal saying it was
# cut. The provenance is the sentence that says whether to trust the
# origin in it, and it ends with the fix, so a cut at any length loses
# exactly the half worth reading.
#
# No number would have done. `server.public_url` accepts an origin with
# a path prefix and bounds neither, so a legal configuration can compose
# an onboarding URL of any length; a bound here refuses nothing and
# corrupts quietly, which is the one failure this project's refusal
# posture exists to avoid. So they are printed whole, terminal-safe,
# which is the same call `_block` makes for a prompt and for the same
# reason. What a hostile far side could do with that it could already do
# through `agent preview`, and it would need this deployment's API token
# to try.
UNBOUNDED = None


def _paged(listing: Callable[[Any], str]) -> Callable[[Any], None]:
    """A listing, and what to type for the page after it.

    The continuation goes to stderr, which is where everything about
    this invocation goes and where the practice puts "what to run next"
    by name. Two things follow from that and both are the reason. A
    redirected `> facts.txt` holds the facts and nothing else, so the
    one-entry-per-line property the tables have survives the page being
    followed; and a script reads the same bytes on the same stream
    whatever the terminal is, so nothing here is an interactive
    affordance.

    The value is the API's own answer rather than anything typed, and it
    is bounded on the way out like every other value an answer carries.

    Stdout is flushed first, for the reason `_acknowledged` flushes it:
    stderr is unbuffered and stdout is not, so the notice would
    otherwise land above the page it is about.
    """

    def render(answer: Any) -> None:
        print(listing(answer), end="")
        after = answer["next_cursor"]
        if after is None:
            return
        sys.stdout.flush()
        print(f"{MORE_PAGES} {_cell(after)}", file=sys.stderr)

    return render


def _cell(value: object) -> str:
    """One value in a cell or on a block line, bounded.

    Null becomes the fixed placeholder rather than an empty cell, and
    everything else is truncated and made printable before it is
    written: a tab or a newline inside a cell is an unprintable here,
    because a cell that wraps stops being a cell and a block whose line
    structure came from an answer is a block an utterance can write.
    """
    if value is None:
        return NOTHING_THERE
    return printable(str(value), CELL_LENGTH) or NOTHING_THERE


def _columns(rows: Sequence[Sequence[str]]) -> str:
    """A borderless table: two spaces between columns, every column as
    wide as its widest cell, and no trailing whitespace on a line.

    The one renderer for it, because the pending listing and the session
    listing are the same shape and a second copy would be a second place
    for the gutter to change."""
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    return "".join(
        "  ".join(
            cell.ljust(width) for cell, width in zip(row, widths, strict=True)
        ).rstrip()
        + "\n"
        for row in rows
    )


# What stands in for a name that comes back from `printable` with
# nothing in it.
#
# There is such a name. `printable` strips before it bounds, so a name
# that is empty or is nothing but whitespace answers the empty string,
# and every shape here declares its names as strings without saying how
# long one may be. Printed as nothing, one would be an entry missing
# from a listing, or two of them a pair of separators with nothing
# between; on the comparison it was worse, because a kind whose only
# pending change rendered to nothing fell out of the answer and left the
# sentence that says nothing is pending (#425's review round).
#
# One question mark, which is what `printable` already answers for every
# other character it cannot write: a name the store accepted is a fact,
# and a fact that renders to nothing falsifies the listing it is in.
UNNAMEABLE = "?"


def _names(values: object) -> str:
    """A list of names from an answer, printed. Bounded and made
    printable one by one even though the shape it was read as has
    established they are strings: what that shape knows about them is
    their type, not their length and not whether every character in them
    can be written to a terminal. `None` is a list of nothing here, which
    is how a grant of the whole server reads.

    A list of N names prints as N things whatever they were spelled,
    which is what `UNNAMEABLE` above is for. Whether the list has
    anything in it is the caller's question and is asked of the list, not
    of this string.
    """
    return ", ".join(printable(str(value)) or UNNAMEABLE for value in _sequence(values))


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()

# What this client does about a boundary the API states
#
# The API says which boundary a write is waiting at, in tokens it
# publishes and never in a command (#386): what installs a stored
# configuration is a verb of a client's grammar, and a client is a
# program the server neither ships nor versions, so an image built
# before a rename would otherwise name a command the CLI beside it no
# longer has. This side owns the grammar, so this side names the
# command, and the spelling is then inside the command-spellings
# census's reach: a rename that missed it fails a test in this
# checkout rather than reaching an operator through an old image.
#
# One command crosses one of the four boundaries, and this is it. The
# other three are crossed by a device asking, a process starting and a
# server reading the store at boot, none of which is something a
# command of this grammar does. Written once and read by the three
# renderings below, so the diff's head and the advice under a write
# cannot come to spell it differently: that command is `vinga apply`.
INSTALLS = f"{PROGRAM} apply"

# What this client says about each set of boundaries a write can be
# waiting at, printed INSTEAD of the server's own sentence.
#
# Instead rather than under it (#426). The token is what travels, so
# whichever side can state the boundary states it once, and this side
# can: it knows what the set means and it knows the command that crosses
# it, while the server knows the first half only. Two lines said one
# thing twice, and the half an operator acts on was the second of them.
# So each line here stands alone, which is what it has to be able to do:
# it names the state first, because that is the half no compaction may
# cut, and the remedy after it.
#
# Keyed by the whole set rather than by a token, because what to say
# about `reload` and `check-in` together is one thing rather than two
# sentences in a row: the install crosses the first and the device
# crosses the second by itself.
#
# The keys are the sets there is something to run about, which is the
# whole of what a table like this may claim. A write waiting only at
# `check-in`, `restart` or `store-boot` is answered by the server's
# sentence and nothing else, because no command of this grammar crosses
# those and the server's words for them are already the whole answer; so
# is a set this client cannot name at all, which is what a boundary from
# a server newer than this one arrives as, the empty tuple `_declared`
# reads it down to. The rule either way is the same one: an unknown
# state is quoted, never guessed at.
SPOKEN: dict[frozenset[Applies], str] = {
    frozenset({Applies.RELOAD}): (
        f"stored, not serving yet: run `{INSTALLS}` to install it on the running "
        f"server, and `{PROGRAM} diff` to list everything pending."
    ),
    frozenset({Applies.RELOAD, Applies.CHECK_IN}): (
        f"stored, and the agent it names is not serving yet: run `{INSTALLS}`, and a "
        f"device reaches the agent at its next check-in after that."
    ),
}

# The one clause a whole document is answered with, which is the same
# clause for both sets above: they are waiting on the one install this
# grammar has, and a count line that named the pair twice would say less
# than saying it once. What the per-set lines add over this one is the
# check-in half, which is detail a single write's own answer carries and
# a document's does not: nothing is run about it either way.
NOT_SERVING_YET = f"not serving yet: run `{INSTALLS}`"


def _boundaries(applies: object) -> frozenset[Applies]:
    """The boundaries one answer carries, as the set they are.

    A body carries them as a sequence, which is JSON having no set, and
    the field's meaning is a set: `["reload", "check-in"]` and
    `["check-in", "reload"]` are one answer, and a token twice is the
    same answer as a token once. Everything downstream reads them
    through here, so the order a server happened to serialize them in
    reaches neither the table nor the dedupe.
    """
    return frozenset(cast(Iterable[Applies], applies))


def _announced(sentence: str, applies: frozenset[Applies]) -> str:
    """What one write is waiting at, as an operator reads it: this
    client's own line where it knows the set, and the server's sentence
    where it does not.

    One voice rather than two (#426). Both sides are answering the same
    question, so the one that can answer it whole answers it, and this
    side can wherever the set is a key above: it says the state and the
    command that crosses it in one line. A set with no line here is
    quoted from the server, which is what a boundary with nothing to run
    about, an older server's silence and a newer server's word all
    arrive as.
    """
    return SPOKEN.get(applies, sentence)


def _inline(data: Mapping[str, object]) -> str:
    """One body on one line, as `key=value` pairs.

    Every half of every pair goes through the display door. A key is a
    string by JSON's construction and nothing more than that: it is text
    the answer chose, exactly as the value beside it is, and a key
    carrying an escape sequence would steer the terminal from the left
    of the equals sign as readily as from the right.
    """
    return " ".join(f"{printable(key)}={_short(value)}" for key, value in data.items())


def _short(value: object) -> str:
    """One value of a body, short enough to sit on a line with the rest
    of the body.

    A structure is named rather than opened, at every depth but one. A
    mapping reads as `{...}` wherever it appears, including inside a
    list, because opening one is what puts a key nobody vouched for and
    whatever it holds onto the line: `str()` of a mapping is its repr,
    and a repr is not a rendering.

    The one depth that is opened is the outermost list, because that is
    what an agent's includes and its grants are: a line that said
    `[...]` where the fragments are named would be hiding the answer
    rather than bounding it. A list inside that one reads as `[...]`,
    which is the same rule as the mapping's and is what makes this
    depth-bounded: nothing here recurses, so a body nested a thousand
    deep costs one frame and one line rather than a `RecursionError` out
    of the boundary.

    Everything else reads as itself through the display door.
    """
    if isinstance(value, Mapping):
        return "{...}"
    if isinstance(value, list):
        return "[" + ", ".join(_item(item) for item in value) + "]"
    return printable(str(value))


def _item(value: object) -> str:
    """One item of the one list a line opens: a word through the display
    door, or the fact that it is a structure."""
    if isinstance(value, Mapping):
        return "{...}"
    if isinstance(value, list):
        return "[...]"
    return printable(str(value))


def _yaml(data: object) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)


def _imported(answer: Mapping[str, object]) -> None:
    """One imported document read out: what each entry did, and then the
    boundaries the ones that were written are waiting on.

    Every import is rendered this way, because an import installs
    nothing: the write is the whole of what the command did, so the
    boundaries are what the operator has to be told about.

    One line per entry on stdout, in the order the answer lists them,
    which is the configuration's own section order. What they are
    waiting on goes to stderr the way a single write's does, and it is
    one line over the whole document rather than one per entry: a
    document that wrote nine entities is waiting on one apply, not on
    nine, and printing a sentence nine times would say otherwise.
    """
    for notice in _imported_entries(answer):
        print(notice, file=sys.stderr)


def _imported_entries(answer: Mapping[str, object]) -> tuple[str, ...]:
    """What an imported document did, entry by entry, and what the
    entries that were written are waiting on.

    Apart from the rendering above it and printing rather than
    returning, because the two halves answer different questions: what
    was written goes to stdout as it is read, and what it is waiting on
    is a set the caller sends to stderr underneath.

    A document that named nothing has one line and no boundaries, which
    is the same shape rather than a second one: it leaves through the
    same flush, and an empty answer has nothing to be waiting on.
    """
    entries = answer["entries"]
    for entry in entries:
        print(f"{_entry_name(entry)}: {entry['outcome']}")
    if not entries:
        print(NOTHING_IMPORTED)
    # Flushed here rather than by the caller, so whatever follows on
    # stderr lands after the lines it is about rather than ahead of
    # them: stderr is unbuffered and stdout is not. That is the notice
    # this write is waiting on, and it has to arrive underneath what was
    # written.
    #
    # On both arms, which is what the early return used to miss: a
    # document that named nothing still printed a line, so the one
    # output an empty import has would have been read after the notice
    # it came before.
    sys.stdout.flush()
    # One line for the whole document, and the server's sentences under
    # it only where this client cannot speak for itself (#426).
    #
    # The count line is the answer to what the operator typed: they ran
    # `import`, so what they are told is what was imported and how much
    # of it. Counted over the entries that wrote, because an entry the
    # store already said is not something this command did; the two
    # halves of that agree by contract, which is what `_one_outcome`
    # refuses a body over. The boundary rides that line because both
    # sets this client knows are waiting on the one install this grammar
    # has, which is what the comment above `INSTALLS` says: a document of
    # nine entries is waiting on one apply, and saying so nine times, or
    # twice for two sets, says less than saying it once.
    #
    # What is not collapsed is what this client did not compose. An
    # entry waiting at a boundary with nothing to run about, one from a
    # server older than the vocabulary and one from a server newer than
    # it all contribute the sentence the server wrote, deduplicated by
    # the sentence itself: with no set to key on, the sentence is the
    # only half either of them has, and two such entries carrying
    # different sentences are two different things to be waiting on.
    written = [entry for entry in entries if entry["notice"] is not None]
    if not written:
        return ()
    actionable = False
    quoted: dict[str, str] = {}
    for entry in written:
        applies = _boundaries(entry["applies"])
        if applies in SPOKEN:
            actionable = True
            continue
        # Whole, for the reason a prompt and the onboarding URL are
        # printed whole: a boundary sentence cut at a bound would lose
        # the state it ends with, which is what an operator reads it
        # for. What the bound is never for is the other half of this
        # function, which has no exceptions: nothing an answer carries
        # steers a terminal.
        sentence = printable(str(entry["notice"]), UNBOUNDED)
        quoted.setdefault(sentence, sentence)
    counted = f"imported {len(written)} {'entry' if len(written) == 1 else 'entries'}"
    return (
        f"{counted}, {NOT_SERVING_YET}" if actionable else counted,
        *quoted.values(),
    )


def _entry_name(entry: Mapping[str, object]) -> str:
    """Where one imported entry is, as an operator reads their own
    document: the section, and the identity under it where the section
    holds entries rather than one thing.

    Both halves go through `printable` even though one of them is a
    closed token, because this line is far-side text on stdout: an
    identity is an operator's own name for a row as the store holds it,
    and a body that put an escape sequence or a lone surrogate in one
    would otherwise steer a terminal or raise a `UnicodeEncodeError`
    past the boundary that turns a failure into a sentence.
    """
    section, identity = printable(str(entry["section"])), printable(str(entry["identity"]))
    return f"{section}.{identity}" if identity else section


def _acknowledged(acknowledgement: Mapping[str, object]) -> None:
    """One write acknowledged: what it did, and when it takes effect.

    The first is the API's own words, carried through unchanged: what an
    act did is decided where the write happens, and this is where it is
    read out. The second is this client's wherever it knows the boundary
    set, because the command that crosses one is a fact of this grammar
    and not of the server's (#386), and the server's own sentence
    wherever it does not.

    Both leave through `printable`, and at different bounds, which is
    the line that function draws.
    """
    # At the default bound, which is the door `_entry_name` puts on the
    # same value one level up: this line is a kind and an identity an
    # operator chose, quoted inside a sentence of this client's own, and
    # a bound is what a value like that is protected by. The unbounded
    # rule below is for a boundary sentence, whose tail is the state it
    # exists to state and which a cut would lose.
    print(f"wrote {printable(str(acknowledgement['wrote']))}")
    # Flushed first, so the notice lands after the line it is about
    # rather than ahead of it: stderr is unbuffered and stdout is not.
    sys.stdout.flush()
    print(
        _announced(
            # Whole and through the display door, for the reason the
            # import path records: a boundary sentence cut at a bound
            # loses the state it ends with, and nothing an answer
            # carries steers a terminal. This is a sentence a server of
            # any age composed, so the arm that quotes it is the arm
            # that needs the door.
            printable(str(acknowledgement["notice"]), UNBOUNDED),
            _boundaries(acknowledgement["applies"]),
        ),
        file=sys.stderr,
    )
