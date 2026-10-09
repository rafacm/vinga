"""The packaged Use pages, as the built-in agent's knowledge reads them.

Driven through the package's interface over the real copy, so what is
checked is what a caller is handed. The copy itself is held to
`docs/` by `tests/census/test_packaged_pages.py`; this file takes that
as given and checks what is built on it.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from tests.support.packaged_pages import sources
from vinga_server import knowledge
from vinga_server.knowledge.library import sections_of
from vinga_server.tools import names

# What importing it costs


def test_importing_the_package_loads_only_the_standard_library() -> None:
    """The property that lets `config/models.py` reach this package
    without breaking the configuration client's import-weight pin.

    In a fresh interpreter, because this suite's own `sys.modules`
    holds the whole server already; and with `-B`, for the reason
    `tests/unit/test_onboarding_import_weight.py` gives.
    """
    source = textwrap.dedent(
        """
        import sys

        before = set(sys.modules)
        import vinga_server.knowledge

        print("\\n".join(sorted(set(sys.modules) - before)))
        """
    )
    finished = subprocess.run(
        [sys.executable, "-B", "-c", source], capture_output=True, text=True, check=True
    )

    loaded = finished.stdout.split()
    assert "vinga_server.knowledge" in loaded
    assert [
        name
        for name in loaded
        if name.split(".")[0] not in sys.stdlib_module_names
        and name != "vinga_server"
        and not name.startswith("vinga_server.knowledge")
    ] == []


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


def test_a_missing_section_is_refused_rather_than_read_as_empty() -> None:
    with pytest.raises(LookupError):
        knowledge.section("concepts.md", "Not a heading")


SENTINEL = "sk-section-4b9e2a71-never-a-real-credential"


def chain(raised: BaseException) -> list[BaseException]:
    """An exception and everything it was raised from or during."""
    found: list[BaseException] = []
    current: BaseException | None = raised
    while current is not None and current not in found:
        found.append(current)
        current = current.__cause__ or current.__context__
    return found


@pytest.mark.parametrize(
    ("page", "heading"),
    [(SENTINEL, None), ("concepts.md", SENTINEL), (SENTINEL, SENTINEL)],
    ids=["page", "heading", "both"],
)
def test_the_refusal_quotes_neither_the_page_nor_the_heading(
    page: str, heading: str | None
) -> None:
    """The caller passed both values, so it already knows which section
    it asked for; the refusal is a fixed sentence, so a value that
    should never have been passed cannot reach a message, a traceback
    or a log line through it."""
    with pytest.raises(LookupError) as refused:
        knowledge.section(page, heading)

    for raised in chain(refused.value):
        assert SENTINEL not in str(raised)
        assert all(SENTINEL not in repr(arg) for arg in raised.args)


# The concept summary


def test_the_summary_s_heading_is_in_the_packaged_concepts_page() -> None:
    """Plan D2. The summary is extracted at run time, so renaming the
    heading would empty it; this is what makes that a red run."""
    headings = [cut.heading for cut in knowledge.sections() if cut.page == "concepts.md"]

    assert "The model in one paragraph" in headings


def test_the_persona_ends_with_the_concept_summary_verbatim() -> None:
    """The page's own section, so there is no second copy of it to
    drift, after the hand-written persona (D1, D2)."""
    summary = knowledge.section("concepts.md", "The model in one paragraph").text

    assert knowledge.persona().endswith("\n\n" + summary.rstrip())
    assert "A **device** is a physical endpoint" in knowledge.persona()


def test_the_persona_opens_with_who_vinga_is_and_how_it_speaks() -> None:
    """D1: the hand-written text comes first, says it is vinga, names
    commands rather than running them, speaks briefly and without
    markdown, says when it does not know, and does not configure by
    voice."""
    opening = " ".join(knowledge.persona().split("## The model in one paragraph")[0].split())

    assert opening.startswith("You are vinga")
    for promise in (
        "you never run one yourself",
        "one or two short sentences",
        "no markdown",
        "the language the person spoke",
        "say so plainly rather than guessing",
        "by voice",
        "switching agents",
    ):
        assert promise in opening


def test_the_persona_answers_the_device_from_the_facts_it_is_given() -> None:
    """Since M4 the prompt carries the facts of the board's guide, or a
    fixed text saying the board is not known, so the persona sends a
    question about the buttons and controls to those facts. Since M5
    anything else about the device or about vinga is looked up with the
    lookup tool before it is answered, and only what neither covers is
    declined: a first run of the gate with the facts called the only
    source ("from those facts alone") had the model decline three of
    the first six questions that needed the lookup without making it.
    The gate measured small models inventing what a prompt does not
    hold, so it still says what to do when nothing covers a question."""
    opening = " ".join(knowledge.persona().split("## The model in one paragraph")[0].split())

    assert "you do not know this particular board yet" not in opening
    assert "from those facts alone" not in opening
    assert "buttons and controls from those facts" in opening
    assert opening.count(names.SEARCH_DOCS) == 1
    assert "neither what you were told nor the documentation covers" in opening
    assert "device guide" in opening
