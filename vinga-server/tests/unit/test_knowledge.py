"""The packaged Use pages, as the built-in agent's knowledge reads them.

Driven through the package's interface over the real copy, so what is
checked is what a caller is handed. The copy itself is held to
`docs/` by `tests/census/test_packaged_pages.py`; this file takes that
as given and checks what is built on it.
"""

from __future__ import annotations

import pytest

from tests.census.test_packaged_pages import sources
from vinga_server import knowledge
from vinga_server.knowledge.library import sections_of

# The reader


def test_the_reader_hands_out_every_packaged_page() -> None:
    """Every page the census copies, under the name it is copied to,
    with the text it has under `docs/`."""
    expected = {name: path.read_text(encoding="utf-8") for name, path in sources().items()}

    assert dict(knowledge.pages()) == expected


def test_what_the_reader_hands_out_cannot_be_changed_for_the_next_caller() -> None:
    """The read is cached for the process, so a caller that could write
    into it would change what every later caller is told."""
    with pytest.raises(TypeError):
        knowledge.pages()["concepts.md"] = "something else"  # type: ignore[index]


# The cut


def test_every_page_is_its_sections_joined() -> None:
    """Lossless: nothing is dropped between sections, nothing repeated.
    A cut that lost a line would lose a fact vinga could be asked."""
    for page, text in knowledge.pages().items():
        assert "".join(cut.text for cut in knowledge.sections() if cut.page == page) == text


def test_a_section_after_the_lead_opens_on_its_own_heading() -> None:
    for cut in knowledge.sections():
        if cut.heading is not None:
            assert cut.text.startswith(f"## {cut.heading}\n"), cut.title


def test_a_section_is_titled_by_its_page_and_its_heading() -> None:
    """`<page title>: <heading>`, and the lead by the page title alone,
    which is the page's `# ` line."""
    [lead, first, *_] = [cut for cut in knowledge.sections() if cut.page == "concepts.md"]

    page_title = knowledge.pages()["concepts.md"].splitlines()[0].removeprefix("# ")
    assert lead.heading is None
    assert lead.title == page_title
    assert first.title == f"{page_title}: {first.heading}"


PAGE = """\
# A page

Its lead.

## First

Text with a level-three heading under it.

### Kept inside

```sh
## a shell comment, not a heading
```

## Second
"""


def test_the_cut_is_at_level_two_headings_outside_fences() -> None:
    """The rule on a page written for it: level three stays inside its
    section, and a `##` line inside a fenced block is code."""
    cuts = sections_of("devices/a-page.md", PAGE)

    assert [cut.title for cut in cuts] == ["A page", "A page: First", "A page: Second"]
    assert "### Kept inside" in cuts[1].text
    assert "## a shell comment" in cuts[1].text
    assert "".join(cut.text for cut in cuts) == PAGE


def test_a_page_with_no_title_is_titled_by_its_path() -> None:
    [cut] = sections_of("devices/untitled.md", "## Only\n\nText.\n")

    assert cut.title == "devices/untitled.md: Only"


def test_a_missing_section_is_refused_by_name_rather_than_read_as_empty() -> None:
    with pytest.raises(LookupError, match="no section headed 'Not a heading'"):
        knowledge.section("concepts.md", "Not a heading")
