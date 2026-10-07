"""What the built-in agent knows: the Use door, packaged with the build.

The pages under `pages/` are a committed copy of `docs/concepts.md`,
`docs/glossary.md` and `docs/devices/*.md`, byte for byte, written and
checked by `tests/census/test_packaged_pages.py`. Never edit them here:
edit the page under `docs/` and regenerate.

This package imports nothing beyond the standard library, so
`config/models.py` may reach it without breaking the import-weight pin
the configuration client is held to.

What a caller stops knowing: where the pages live and that they are a
copy, how a page is cut into sections, and how a reported board type
maps to a guide.

- `library` reads the copy once per process and cuts it into sections.
- `boards` names the board guides and answers a board type with its
  guide's facts, or with fixed text when no guide is named for it.

This `__init__` is the interface. Submodules import their siblings
directly and take nothing from here, so only this file aggregates.
"""

from vinga_server.knowledge.boards import (
    NOT_BOARD_GUIDES,
    VAGUE_BOARD_FACTS,
    board_facts,
    board_guides,
)
from vinga_server.knowledge.library import Section, pages, section, sections

__all__ = [
    "NOT_BOARD_GUIDES",
    "VAGUE_BOARD_FACTS",
    "Section",
    "board_facts",
    "board_guides",
    "pages",
    "section",
    "sections",
]
