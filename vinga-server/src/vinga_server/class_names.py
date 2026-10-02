"""What this server may call a caught exception's class.

A type name says what went wrong, and a message says what a stranger
wrote, so a failure is reported by its class and never by its words.
The class name is not safe merely for being a class name, though:
`type(name, (Exception,), {})` accepts any string as `name`, a line
break and a forged log line after it included (#217, #565). A name is
repeated only when it is an identifier, and that rule lives here.

Two readers, one rule. `events.values.ClassName`, which is how a
failure's class reaches the typed events, admits a value only when
`is_class_name` does; `failure_name` below is the same rule for every
other place a class is said, which is a retained log line, a CLI or API
sentence, and the message of an exception rendered later.

A leaf, deliberately, importing nothing of this server: the client half
the configuration CLI reaches (`device_endpoint`, `protocol.messages`)
says class names too, and the event vocabulary would drag the whole
event catalog in behind it (`tests/unit/test_cli_import_weight.py`).
"""

import re
from typing import Final

# A Python identifier in its ASCII spelling, which is every class this
# server and the libraries it runs are made of.
CLASS_NAME_PATTERN: Final = r"[A-Za-z_][A-Za-z0-9_]*"

_CLASS_NAME = re.compile(rf"\A(?:{CLASS_NAME_PATTERN})\Z")

# What `failure_name` says in place of a class name it may not repeat.
# A phrase rather than nothing, so a sentence still says that something
# was raised, and fixed, so it says nothing about what. Worded to stand
# wherever a class name stood, after a colon or inside parentheses.
UNNAMED_FAILURE: Final = "an exception whose class name is not an identifier"


def is_class_name(text: str) -> bool:
    """Whether this text may be repeated as a class name.

    A plain `str` and nothing else, before the pattern is asked: a
    `str` subclass can match it and still print as anything at all,
    since formatting calls its own `__format__` and `__str__`.
    """
    return type(text) is str and _CLASS_NAME.match(text) is not None


def class_name_of(failure: BaseException) -> str | None:
    """The class name of this failure where it may be repeated, or None.

    Total, because it is called from inside the arm that caught the
    failure, where anything it raised would carry that failure out as
    its `__context__`, message and all. A metaclass decides what
    `__name__` answers, so the answer can be a number, a `str` subclass,
    or a lookup that raises (#565's review round): the first two are
    refused by `is_class_name`, and the third is contained here and
    answered with None. `Exception` and not `BaseException`, so a
    cancellation or an interpreter exit still goes where it was going.

    The one place this server reads a type's name off a failure.
    `failure_name` below and `events.values.ClassName.of` both ask it,
    and spelling `type(exc).__name__` anywhere else is what
    `tests/unit/test_class_name_sites.py` refuses.
    """
    try:
        name = type(failure).__name__
    except Exception:  # noqa: BLE001 - a report never raises out of its arm
        return None
    return name if is_class_name(name) else None


def failure_name(failure: BaseException) -> str:
    """The class name a sentence about a failure says, which is the
    whole of what it says about it, or `UNNAMED_FAILURE` where
    `class_name_of` has no name to give.

    The one way this server puts a caught exception's class into a
    retained log line, a CLI or API sentence, or the message of an
    exception rendered later. A lawful name comes back exactly as
    Python spells it, so a site that moved here says what it said
    before; anything else changes into the fixed phrase rather than
    into an exception of its own, because the caller is in the middle
    of saying that something else failed.
    """
    named = class_name_of(failure)
    return UNNAMED_FAILURE if named is None else named


__all__ = [
    "CLASS_NAME_PATTERN",
    "UNNAMED_FAILURE",
    "class_name_of",
    "failure_name",
    "is_class_name",
]
