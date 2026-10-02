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
    """Whether this text may be repeated as a class name."""
    return _CLASS_NAME.match(text) is not None


def failure_name(failure: BaseException) -> str:
    """The class name a sentence about a failure says, which is the
    whole of what it says about it, or `UNNAMED_FAILURE` where that
    name is not one it may repeat.

    The one way this server puts a caught exception's class into a
    retained log line, a CLI or API sentence, or the message of an
    exception rendered later. A lawful name comes back exactly as
    Python spells it, so a site that moved here says what it said
    before; only a name that is not an identifier changes, and it
    changes into the fixed phrase rather than into an exception of its
    own, because the caller is in the middle of saying that something
    else failed. Spelling `type(exc).__name__` at a site instead is what
    `tests/unit/test_class_name_sites.py` refuses.
    """
    name = type(failure).__name__
    return name if is_class_name(name) else UNNAMED_FAILURE


__all__ = [
    "CLASS_NAME_PATTERN",
    "UNNAMED_FAILURE",
    "failure_name",
    "is_class_name",
]
