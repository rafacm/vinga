"""Every way a log record can carry a value out of this process.

A no-leak claim about logs is a claim about the record rather than about
the line, because a handler this deployment does not configure is still
handed the whole object.

So `renderings` answers three readings of every record a case captured:
the JSON format, the text format, and the record itself, its whole
attribute dictionary, its unformatted arguments and whatever exception
it carries. A sentinel absent from all three is absent from a log file
whatever is configured in front of it.

The third reading is the one that earns its place, and what it adds is
narrower than "the formatters print only the message": this server's
JSON formatter serializes every non-standard `extra` and formats an
attached exception, so those two shapes are caught by the formatters
already. What it catches that neither of them does, measured rather
than assumed: an argument no placeholder consumed (a mapping passed
beside a message with no `%` in it formats away to the message alone),
and a value written onto one of logging's own attributes, which the
JSON formatter skips by name and the text format never prints. Both are
shapes a caller can reach by accident, and both leave the value in the
object a third-party handler serializes whole.

One home, because two suites make the same claim about the same value
from opposite sides of the wire: the API's write routes assert it about
a body they were sent, and the CLI's verbs assert it about a word an
operator typed. A walk copied into each of them is one decision in two
places, and the weaker of the two copies is the one nobody notices.

Every record and not this server's own alone, which is the whole of what
the claim can honestly mean: a credential in a client library's request
line is in the deployment's log file exactly as much as one in a line
this code wrote.

`config_cli.logged` is the other reading and stays what it is: one
string, per record, of the message and what the formatter would put back
into it, which is what the CLI suites that sweep a whole run assert
against. This is the stronger walk, for the cases whose subject is one
value and where it could have gone.

The module holds the exception walk as well as the record walk, for the
same reason. A refusal is the other thing a caller is handed that can
carry a value out, and fifteen suites once each held their own copy of
a walk over it that read `repr` and `str` alone, while a stronger one
sat a directory away: the weaker copy is the one nobody noticed. So
`chain` is the one walk every secret-absence assertion about an
exception makes, and it reads everything a handler walking the objects
could print: each exception's `repr` and `str`, its arguments both
ways, and two levels of what its attributes hold, names as well as
values. `links` is the traversal under it, every exception reachable
through `__cause__` and `__context__` both, for a caller that renders
the exceptions its own way and should not spell a weaker walk to reach
them.
"""

import logging

import pytest

from vinga_server import logs


def renderings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every record captured, three ways: both formats a deployment
    writes one in, and the object behind them."""
    text = logging.Formatter(logs.TEXT_FORMAT)
    return [
        rendering
        for record in caplog.records
        for rendering in (
            logs.JsonFormatter().format(record),
            text.format(record),
            f"{record.getMessage()}\n{record.__dict__!r}\n{record.args!r}\n"
            f"{record.exc_info!r}\n{record.exc_text!r}",
        )
    ]


def links(exc: BaseException) -> list[BaseException]:
    """Every exception reachable from this one, each once, in the order
    a depth-first walk visits them, cause before context.

    Both links from every exception, not `__cause__ or __context__`: an
    exception carrying both would otherwise be followed down its cause
    alone, and a value sitting only in its context would never be read.
    Python's own traceback printer suppresses that context too, but a
    handler that walks the objects (an error reporter, a structured
    logger) does not. The seen set is keyed by identity, so a graph with
    a cycle through either link ends.
    """
    visited: list[BaseException] = []
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        visited.append(current)
        pending += [
            linked for linked in (current.__context__, current.__cause__) if linked is not None
        ]
    return visited


def chain(exc: BaseException) -> str:
    """Everything an exception carries, including what a walker of its
    graph would find behind it: its text, its arguments both ways, what
    its own attributes hold, and the same again for every exception
    `links` reaches.

    Each argument's `str` as well as the tuple's `repr`, because an
    argument can render one way and print the other, and a formatter
    that interpolates it prints the `str`.
    """
    parts: list[str] = []
    for current in links(exc):
        parts += [repr(current), str(current), repr(current.args)]
        parts += [str(argument) for argument in current.args]
        parts.append(_held(current))
    return "\n".join(parts)


def _held(exc: BaseException) -> str:
    """What one exception's attributes hold, and what theirs hold, each
    rendered as `name=value!r`.

    Two levels rather than one, because the lesson that made this
    necessary is a PyYAML mark: the exception's repr says nothing, its
    `problem_mark` attribute is an object, and that object's `buffer` is
    the whole source being parsed. A walk that stopped at the repr would
    miss exactly what it is looking for. Names as well as values at both
    levels, because a value can travel as a key as easily as a value.
    """
    parts: list[str] = []
    for name, value in vars(exc).items():
        parts.append(f"{name}={value!r}")
        if hasattr(value, "__dict__"):
            parts += [f"{inner_name}={inner!r}" for inner_name, inner in vars(value).items()]
    return "\n".join(parts)
