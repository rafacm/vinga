"""What the built-in agent knows: the Use door, packaged with the build.

The pages under `pages/` are a committed copy of `docs/concepts.md`,
`docs/glossary.md` and `docs/devices/*.md`, byte for byte, written and
checked by `tests/census/test_packaged_pages.py`. Never edit them here:
edit the page under `docs/` and regenerate.

This package imports nothing beyond the standard library, so
`config/models.py` may reach it without breaking the import-weight pin
the configuration client is held to.

What a caller stops knowing: where the pages live and that they are a
copy, and how a page is cut into sections.

- `library` reads the copy once per process and cuts it into sections.

This `__init__` is the interface. Submodules import their siblings
directly and take nothing from here, so only this file aggregates.
"""

from vinga_server.knowledge.library import Section, pages, section, sections

__all__ = ["Section", "pages", "section", "sections"]
