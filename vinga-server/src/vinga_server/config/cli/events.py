"""The live event stream.

The one read of this API whose answer does not finish, which is why it
is a local function rather than an `Act`: an act is a buffered request
whose one answer is handed to one renderer, and bending that shape
around a body with no end would deform the grammar's core for one
command. What it borrows instead is the transport, which is the half
that matters: `reach._streamed` carries the whole no-leak boundary
across opening, iterating and giving the connection back.

What its callers stop knowing: what the wire looks like and what a
frame has to be to be printed. Server-Sent Events is a line vocabulary
rather than a document, and a 200 whose body happens to parse is not
this API's output; the media type and the frame envelope are the two
things standing between a stranger's body and an operator's terminal,
and both are checked here.

What the wire looks like is the API's published contract rather than an
import. This half of the program is the client, and the module that
writes these frames is precisely what it may not reach
(`tests/unit/test_cli_import_weight.py`); a generated client would
carry the same words for the same reason.
"""

import contextlib
import json
import logging
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import datetime
from typing import Any

from vinga_server.config.loader import ConfigError

from .acts import _path
from .invocation import Invocation
from .reach import UNRECOGNIZED_ANSWER, _reached, _streamed

# And what a frame this client cannot read as an event says. Nothing of
# the frame is in it, for the reason no other unreadable answer is
# quoted back: what a proxy or a gateway writes into a stream is not
# this API's own output.
UNREADABLE_EVENT = (
    f"the event stream carried {UNRECOGNIZED_ANSWER}, so the tail stopped rather than "
    f"printing it. It is not quoted back: what reaches a stream from a middlebox is "
    f"not the API's sanitized output."
)


# The stream's own event name for a reader that fell behind, and the key
# its object carries.
DROPPED_EVENT = "dropped"

# The two fields the stream owns and the one every event carries, which
# this renderer prints in front of the rest rather than among them, and
# which together are the envelope a frame has to have to be read at all.
STREAM_TIME = "ts"

STREAM_LEVEL = "level"

EVENT_NAME = "event"

# The four names the stream stamps a level with, which are the four
# `--level` takes.
#
# Derived from the logging module rather than typed out, because that is
# where the server's own copy comes from: `events/live.py` writes the
# `level` field with `logging.getLevelName`, so these are the same four
# strings arrived at the same way rather than a second spelling of them.
LEVEL_NAMES = tuple(
    logging.getLevelName(level)
    for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR)
)

# The one level whose name is not printed. It is the default the stream
# filters at, so it is what most of a tail is, and a word on every line
# saying "ordinary" is a word that stops being read. Every other level
# is named, DEBUG included: an event admitted below the default has to
# say that it is one.
UNNAMED_LEVEL = "INFO"

# How far a frame may nest before this client stops reading it.
#
# An event is a small object of scalars by construction, and the deepest
# thing any of them carries is a mapping of counts a level or two down.
# The bound is not about taste: `json.loads` raises `RecursionError` on a
# document nested a few thousand deep, and so can rendering it, and a
# stream is untrusted input all the way down. Refusing above a depth no
# event reaches means neither can be provoked from the far side, and the
# check that applies it walks the structure with a stack of its own
# rather than by recursion, since a recursive check would be the third
# thing that could be made to blow up.
MAX_FRAME_DEPTH = 8

# What may be printed as a bare word rather than as an encoded value.
#
# Two things go through this: an event's name and its level's name, both
# of which are vocabulary from a closed declared set and both of which
# would be unreadable in quotes. The pattern is what makes printing them
# bare safe rather than trusting: a name that is not one of these
# characters is not one this API declares, so it is encoded like any
# other value and the line's one-line guarantee is kept whatever
# arrived.
_BARE_WORD = re.compile(r"\A[A-Za-z0-9_.:-]{1,64}\Z")

EVENTS_DEVICE_HELP = "only the events of this board, by MAC (default: every board)"

EVENTS_SESSION_HELP = (
    "only the events of this session, by its uuid hex (default: every session)"
)

# Composed from the names above rather than restating them, so the page
# an operator reads and the set a frame is held to cannot come apart.
# The last is joined with `or` because this is a sentence.
EVENTS_LEVEL_HELP = (
    f"the lowest level to show, in any case: {', '.join(LEVEL_NAMES[:-1])} or "
    f"{LEVEL_NAMES[-1]} (default: {UNNAMED_LEVEL}, which is what the retained log "
    f"carries)"
)

FOLLOW_HELP = (
    "keep streaming until interrupted; without it the command prints the first "
    "matching event and exits"
)

TAIL_HELP = (
    "what this server is saying right now, one line per event, as it says it; "
    "without --follow it waits for the first event, prints it and exits"
)


def _events_tail(args: Invocation) -> None:
    """The structured events of the running server, as they happen.

    Two modes and two exact contracts. Without `--follow` this waits for
    the first event the filters admit, prints it and exits 0, which is
    the scriptable "wait for the next X" and the only reading a tail
    with no buffer behind it can offer. With `--follow` it prints until
    something stops it: an interrupt, which is a reader who was told to
    stop and is therefore exit 0, or the stream ending, which is exit 1
    and `STREAM_ENDED`.

    The events go to stdout, one line each and flushed as they arrive,
    because that is what a caller opened this for and a block-buffered
    pipe would deliver a live stream in four-kilobyte lumps. The dropped
    notices go to stderr, because a reader falling behind is about this
    invocation rather than about the deployment: `tail | grep` reads
    only the events, and the person watching still learns that some went
    past.
    """
    reached = _reached(args)
    with contextlib.closing(
        _streamed(reached, _path("runtime", "events"), _event_filters(args))
    ) as lines:
        try:
            for name, fields in _frames(lines):
                if name == DROPPED_EVENT:
                    print(_shown(_dropped_notice, fields), file=sys.stderr)
                    continue
                print(_shown(_event_line, fields))
                sys.stdout.flush()
                if not args.follow:
                    return
        except KeyboardInterrupt:
            # A tail that was told to stop did its job. Caught here
            # rather than at the boundary because this is the one
            # command in the grammar whose ordinary ending it is.
            return


def _event_filters(args: Invocation) -> dict[str, str]:
    """What narrows the stream. Only what was written: an absent flag is
    an argument the request does not carry, so the API's own defaults
    are the defaults, said once.

    The device is kept apart from the two beside it on the one point
    `_metric_window` states: an explicitly empty value still travels, so
    `--device ''` meets the API's MAC refusal rather than reading as no
    filter and widening one board's traffic to the whole server's.
    """
    filters = {
        name: value
        for name, value in (("session", args.session), ("level", args.level))
        if value
    }
    if args.mac is not None:
        filters["device"] = args.mac
    return filters


def _frames(lines: Iterable[str]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """The stream's lines as the events they encode.

    Server-Sent Events is a line vocabulary rather than a document: a
    frame is the lines up to the next blank one, `event:` names it and
    `data:` carries it, and a line beginning with a colon is a comment,
    which is what the keepalive an idle stream sends is made of. A field
    this client has no use for is ignored, which is what the format asks
    a reader to do and what keeps a stream that grows a field from
    breaking a client that does not want it.

    The name travels with the object because it is what the object is
    held to: this stream has two kinds of frame and they have different
    shapes, so which one arrived decides what it has to be.
    """
    name = ""
    data: list[str] = []
    for line in lines:
        if line == "":
            if data:
                yield name, _frame_fields(name, "\n".join(data))
            name, data = "", []
        elif not line.startswith(":"):
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == EVENT_NAME:
                name = value
            elif field == "data":
                data.append(value)


def _frame_fields(name: str, data: str) -> Mapping[str, Any]:
    """One frame's object, held to this stream's contract, or a refusal
    with nothing of the frame in it.

    Refused rather than skipped. A tail that quietly dropped what it
    could not parse would go on looking live while showing less than
    arrived, which is the failure this whole command's end-of-stream
    contract exists to make impossible.

    Both arms are recorded inside their handler and raised outside it,
    this module's rule, and here it is not a formality: a JSON decoding
    error carries the document it was decoding, and this document came
    off a socket.

    `RecursionError` is caught beside `ValueError` because it is the
    same event wearing another name. A document nested a few thousand
    deep makes the decoder exhaust the stack rather than reject the
    input, and an untrusted stream can send one, so without this arm the
    far side chooses whether this command ends with a sentence or with a
    traceback.
    """
    problem: str | None = None
    read: list[object] = []
    try:
        read.append(json.loads(data))
    except (ValueError, RecursionError):
        problem = UNREADABLE_EVENT
    if problem is not None:
        raise ConfigError(problem)
    if not _carries(name, read[0]):
        raise ConfigError(UNREADABLE_EVENT)
    return read[0]  # type: ignore[return-value]


def _carries(name: str, fields: object) -> bool:
    """Whether one frame is a frame of this stream.

    The second of the two things standing between a stranger's body and
    an operator's terminal, the first being the media type. A 200 whose
    body happens to parse as a JSON object is not this API's output, and
    this command prints an object's values, so "it parsed" is not a
    reason to print it.

    What is checked is the envelope, which is all this half can check: an
    event's own field names are the catalogue's, and the module that
    declares them is precisely what the client tier may not import. So an
    ordinary frame has to carry the three keys every streamed event
    carries, in the shapes the route publishes them in, and a `dropped`
    frame has to be its own small envelope and nothing else. A frame
    under any other name is not in the contract at all. Past that the
    event's own fields are rendered escaped, which is what keeps a
    hostile value to one line whatever it holds.

    The stamp is required to be a string rather than to be a stamp: what
    a string means is the renderer's question, and one that will not
    parse still prints as the value it is.
    """
    if not isinstance(fields, dict) or _too_deep(fields):
        return False
    if name == DROPPED_EVENT:
        return list(fields) == [DROPPED_EVENT] and _is_count(fields[DROPPED_EVENT])
    if name:
        return False
    return (
        _is_bare(fields.get(EVENT_NAME))
        and fields.get(STREAM_LEVEL) in LEVEL_NAMES
        and isinstance(fields.get(STREAM_TIME), str)
    )


def _too_deep(fields: Mapping[str, Any]) -> bool:
    """Whether a frame nests further than an event ever does.

    Walked with a stack of its own rather than by recursion, which is the
    whole point: this runs on untrusted input to keep the decoder and the
    renderer from being made to exhaust the stack, and a recursive walk
    would be a third way to do exactly that. The depth is checked before
    a container's contents are pushed, so a document nested a thousand
    deep is refused having been walked eight levels.
    """
    standing: list[tuple[object, int]] = [(fields, 1)]
    while standing:
        value, depth = standing.pop()
        if not isinstance(value, dict | list):
            continue
        if depth > MAX_FRAME_DEPTH:
            return True
        held = value.values() if isinstance(value, dict) else value
        standing.extend((inner, depth + 1) for inner in held)
    return False


def _is_count(value: object) -> bool:
    """Whether a value is a count: a whole number that is not a flag.
    `True` is an `int` in this language and is not a count in any
    other."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_bare(value: object) -> bool:
    """Whether a value is one of the declared words this prints
    unquoted."""
    return isinstance(value, str) and _BARE_WORD.match(value) is not None


def _shown(render: Callable[[Mapping[str, Any]], str], fields: Mapping[str, Any]) -> str:
    """One frame rendered, or the refusal a rendering that could not
    finish becomes.

    The envelope check above bounds what reaches a renderer, so nothing
    here should ever fire. It is here anyway, and for one reason: what
    is being rendered came off a socket, and the cost of being wrong
    about that is the far side choosing that this command ends in a
    traceback. `RecursionError` beside `ValueError` for the reason
    `_frame_fields` catches it, since encoding a structure walks it as
    surely as decoding one built it.
    """
    problem: str | None = None
    written: list[str] = []
    try:
        written.append(render(fields))
    except (ValueError, RecursionError):
        problem = UNREADABLE_EVENT
    if problem is not None:
        raise ConfigError(problem)
    return written[0]


def _event_line(fields: Mapping[str, Any]) -> str:
    """One event as one physical line.

    The clock time it happened at, its level unless that is the one a
    tail is mostly made of, its name, and then everything else it
    carries as `key=value` in the order the event declares them, which
    is the order the retained record writes them in.

    One line by encoding rather than by hope. An event's values are
    identifiers, counts, durations and reason tokens, and the identifier
    vocabulary explicitly admits bytes a terminal reads as instructions,
    so a value is rendered as its compact JSON encoding: a newline
    arrives as `\\n` and an escape sequence as `\\u001b` instead of
    breaking the line in two or steering the terminal it landed in. That
    is the output-determinism practice's second half, which has no
    exception.

    This is a rendering of the record the JSON log retains, not a second
    vocabulary. A reader who needs the object itself reads the log, or
    the stream, which carries exactly it.
    """
    # The three the envelope guarantees, read directly: a frame that did
    # not carry them never reached a renderer (`_carries`).
    parts = [_time_of_day(fields[STREAM_TIME])]
    if fields[STREAM_LEVEL] != UNNAMED_LEVEL:
        parts.append(fields[STREAM_LEVEL])
    parts.append(fields[EVENT_NAME])
    parts += [
        f"{_bare(key)}={_value(value)}"
        for key, value in fields.items()
        if key not in (STREAM_TIME, STREAM_LEVEL, EVENT_NAME)
    ]
    return " ".join(parts)


def _dropped_notice(fields: Mapping[str, Any]) -> str:
    """What a reader that fell behind is told, in the count's own words.

    On stderr and phrased as a gap rather than as an error, because it
    is neither this command's failure nor the server's: the stream
    overwrites the oldest events for a reader that has stopped keeping
    up, which is the alternative to slowing a conversation down.
    """
    return (
        f"{fields[DROPPED_EVENT]} events are missing above this line: this reader fell "
        f"behind, and the server overwrote the oldest of them rather than holding a "
        f"conversation up for it."
    )


def _time_of_day(stamp: str) -> str:
    """The stream's stamp as a person watching reads it: the clock time,
    without the date a tail is already inside of.

    A string by the envelope's guarantee, and a stamp only by this
    server's habit: what a string means is a rendering question, so one
    that will not parse prints as the value it is rather than ending the
    tail."""
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(stamp).strftime("%H:%M:%S")
    return _value(stamp)


def _bare(value: object) -> str:
    """A declared word printed as it is, and anything else encoded.

    What still goes through it is an event's own field NAMES, which are
    the catalogue's and which this half cannot hold to a list it does not
    have. The two words the envelope does check, the event's name and its
    level's, are bare by that check and are printed directly."""
    return value if _is_bare(value) else _value(value)


def _value(value: object) -> str:
    """One value as a line may carry it.

    Numbers as themselves, because a count and a duration are what a
    reader scans a tail for and quoting them would bury them. Everything
    else as compact JSON with nothing above plain ASCII left unescaped,
    which is the whole of the one-line guarantee. A boolean is not a
    number here: `true` is what the record says and `1` is not.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return json.dumps(value, separators=(",", ":"))
    return str(value)
