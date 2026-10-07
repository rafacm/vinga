"""Who the built-in agent is, as the text its prompt opens with.

For now that is the concept summary alone: the section "The model in
one paragraph" of the packaged `concepts.md`, extracted at run time so
there is no second copy of it to drift from the page (plan D2). The
hand-written persona that goes in front of it (D1) arrives with the
built-in agent itself.
"""

from __future__ import annotations

from vinga_server.knowledge.library import section

SUMMARY_PAGE = "concepts.md"

SUMMARY_HEADING = "The model in one paragraph"


def persona() -> str:
    """The built-in agent's persona.

    Raises LookupError when the summary's heading is no longer in the
    page, so a rename fails loudly rather than emptying the summary.
    """
    return section(SUMMARY_PAGE, SUMMARY_HEADING).text.rstrip()
