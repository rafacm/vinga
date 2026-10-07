"""Who the built-in agent is, as the text its prompt opens with.

Two parts, in this order. The hand-written persona, `persona.md` beside
this module (plan D1): who vinga is, what it answers, and how it speaks.
Then the concept summary: the section "The model in one paragraph" of
the packaged `concepts.md`, extracted at run time so there is no second
copy of it to drift from the page (plan D2). The persona states no fact
about how vinga behaves; those are the summary's and the pages', which
is what keeps one home for each.

Read through `importlib.resources` like the pages, and once per process,
for the reason `library` gives: it is immutable data shipped with the
build.
"""

from __future__ import annotations

from functools import cache
from importlib.resources import files

from vinga_server.knowledge.library import PACKAGE, section

PERSONA_FILE = "persona.md"

SUMMARY_PAGE = "concepts.md"

SUMMARY_HEADING = "The model in one paragraph"


@cache
def _hand_written() -> str:
    return (files(PACKAGE) / PERSONA_FILE).read_text(encoding="utf-8").strip()


def persona() -> str:
    """The built-in agent's persona: the hand-written text, a blank
    line, and the concept summary verbatim, heading included.

    Raises LookupError when the summary's heading is no longer in the
    page, so a rename fails loudly rather than emptying the summary.
    """
    summary = section(SUMMARY_PAGE, SUMMARY_HEADING).text.rstrip()
    return f"{_hand_written()}\n\n{summary}"
