"""The packaged pages, read once, and the sections they are cut into.

The pages are package data, so they are read through
`importlib.resources` rather than from a path: what a wheel does not
carry is what an installed server does not have, and a path would be a
fact about this checkout rather than about the artifact.

They are read once per process, behind a cached function rather than a
field of the composition. They are immutable data shipped with the
build, so there is nothing to inject and nothing a test would want to
substitute; a field would be a seam with no second side.

A page is cut at its level-two headings. The text before the first one
is the page's lead, titled with the page's own title; every `##`
section after it is titled `<page title>: <heading>`. Level-three
headings stay inside their section, and a heading line inside a fenced
code block is code, not a heading. The cut is lossless: a page's
sections, joined in order, are the page.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from types import MappingProxyType

PACKAGE = "vinga_server.knowledge"

PAGES = "pages"

_SECTION = "## "

_TITLE = "# "

_FENCES = ("```", "~~~")

# What `section` says when the page or the heading is not there. Fixed,
# for the reason its docstring gives.
NO_SUCH_SECTION = "the packaged pages have no section under that page and heading"


@dataclass(frozen=True)
class Section:
    """One cut of one page, verbatim.

    `page` is the page's path inside the copy (`devices/browser.md`),
    `heading` is the `##` heading's text, or None for the lead, and
    `text` is the section as the page has it, heading line included.
    """

    page: str
    heading: str | None
    title: str
    text: str


def _walk(directory: Traversable, prefix: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for entry in directory.iterdir():
        name = f"{prefix}{entry.name}"
        if entry.is_dir():
            found.update(_walk(entry, f"{name}/"))
        elif entry.is_file():
            found[name] = entry.read_text(encoding="utf-8")
    return found


@cache
def _read() -> Mapping[str, str]:
    """Every packaged page's text, keyed by its path inside the copy.

    The one read of the package data, cached for the life of the
    process and handed out read-only, so no caller can change what the
    next one is given.
    """
    walked = _walk(files(PACKAGE) / PAGES, "")
    return MappingProxyType(dict(sorted(walked.items())))


def pages() -> Mapping[str, str]:
    """Every packaged page's text, keyed by its path inside the copy
    (`concepts.md`, `devices/README.md`), in path order."""
    return _read()


def _fence(line: str) -> bool:
    return line.lstrip().startswith(_FENCES)


def sections_of(page: str, text: str) -> tuple[Section, ...]:
    """One page cut into its lead and its `##` sections.

    The rule the module docstring states, as the function the package
    applies to every page. The page title is its first `# ` heading
    outside a fence, or the page's path when it has none.
    """
    cuts: list[tuple[str | None, list[str]]] = [(None, [])]
    title = None
    fenced = False
    for line in text.splitlines(keepends=True):
        if _fence(line):
            fenced = not fenced
        elif not fenced and line.startswith(_SECTION):
            cuts.append((line[len(_SECTION) :].strip(), []))
        elif not fenced and title is None and line.startswith(_TITLE):
            title = line[len(_TITLE) :].strip()
        cuts[-1][1].append(line)
    named = title if title is not None else page
    return tuple(
        Section(
            page=page,
            heading=heading,
            title=named if heading is None else f"{named}: {heading}",
            text="".join(lines),
        )
        for heading, lines in cuts
        if heading is not None or lines
    )


@cache
def sections() -> tuple[Section, ...]:
    """Every packaged page's sections, page by page in path order and
    in page order within each."""
    return tuple(cut for page, text in pages().items() for cut in sections_of(page, text))


def section(page: str, heading: str | None) -> Section:
    """The one section of `page` under `heading` (None for its lead).

    Raises LookupError when the page or the heading is not there, so a
    renamed heading fails loudly rather than reading as empty text. The
    message is fixed and quotes neither argument: the caller passed
    both, so it already knows which section it asked for, and a value
    that should never have been passed must not reach a message, a
    traceback or a log line through the refusal.
    """
    for cut in sections():
        if cut.page == page and cut.heading == heading:
            return cut
    raise LookupError(NO_SUCH_SECTION)
