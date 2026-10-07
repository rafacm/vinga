"""Which guide a reported board type names, and the facts it carries.

A board reports its type at the OTA check-in (`board.type`), and the
browser page reports `vinga-browser`. That string was chosen by an
unauthenticated request, so it is used for exactly one thing: looking
up a guide by name. It never enters what this module returns, which is
either a guide's own text or the fixed text below.

The mapping is derived from the packaged filenames rather than
tabulated, so a new device guide is reachable by existing. It searches
only the board guides: every packaged device page except the ones that
are not about one device, which are named below, so a new page of that
kind is a decision rather than an accident. A type, casefolded and
stripped, names the guide whose stem is that type, or `waveshare-` plus
it, since upstream reports the primary board without the vendor and
this repository's fixtures with it.

A guide's facts are its lead (the text before its first `##`) and its
`## Controls` section, verbatim. `tests/unit/test_knowledge_boards.py`
holds every board guide to having both, within a character budget.
"""

from __future__ import annotations

from functools import cache
from pathlib import PurePosixPath

from vinga_server.knowledge.library import pages, section

_DEVICES = "devices/"

# The device pages that are not about one device, by filename. Each is
# a page a board type could otherwise spell (`readme`, `flashing`), and
# answering a board with either would be answering it with the wrong
# page.
NOT_BOARD_GUIDES = frozenset(
    {
        # The common page every device guide defers to.
        "README.md",
        # The procedure for writing firmware onto a board.
        "flashing.md",
    }
)

# The vendor prefix a guide's stem carries and a reported type may not.
_VENDOR = "waveshare-"

# What the browser page reports as its board type (`ota.js`), and the
# guide stem it names. The one spelling that is not a stem.
_ALIASES = {"vinga-browser": "browser"}

_CONTROLS = "Controls"

# What a device with no guide gets: an absent type, `unknown`, or a
# type no board guide is named for. Fixed text, so nothing the device
# reported can reach a prompt through it.
VAGUE_BOARD_FACTS = (
    "The server has not been told which board this device is, so there are no facts "
    "here about its buttons, screen or controls. Answer questions about the device "
    "from the common device guide (Device guides, docs/devices/README.md), and say "
    "plainly when it does not cover the question rather than guessing. Restarting the "
    "device lets the server learn which board it is: a board reports its type when it "
    "checks in at boot."
)


@cache
def board_guides() -> frozenset[str]:
    """Every packaged board guide, by its path inside the copy."""
    return frozenset(
        page
        for page in pages()
        if page.startswith(_DEVICES)
        and "/" not in page.removeprefix(_DEVICES)
        and page.removeprefix(_DEVICES) not in NOT_BOARD_GUIDES
    )


@cache
def _by_type() -> dict[str, str]:
    """Every board type a guide answers to, casefolded, to the guide."""
    named = {PurePosixPath(guide).stem.casefold(): guide for guide in board_guides()}
    # A stem without its vendor after every whole stem, so a guide
    # whose own name is the shorter spelling keeps it.
    for stem, guide in sorted(named.items()):
        if stem.startswith(_VENDOR) and stem != _VENDOR:
            named.setdefault(stem.removeprefix(_VENDOR), guide)
    for alias, stem in _ALIASES.items():
        if stem in named:
            named[alias] = named[stem]
    return named


def board_facts(board: str | None) -> str:
    """The facts of the guide `board` names, or the vague text.

    The reported string is a key and nothing more: what comes back is
    a guide's own lead and controls, or `VAGUE_BOARD_FACTS`.
    """
    guide = None if board is None else _by_type().get(board.strip().casefold())
    if guide is None:
        return VAGUE_BOARD_FACTS
    lead = section(guide, None).text.rstrip()
    controls = section(guide, _CONTROLS).text.rstrip()
    return f"{lead}\n\n{controls}"
