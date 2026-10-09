"""The built-in agent's lookup over the packaged pages (#612, M5).

Retrieval is held to what M5 measured against the queries the models
sent in the gate, with no model; the gate's own fixtures are read from
`tests/local/lookup_gate/`, where the model run that uses them lives.
"""

import pytest

from tests.local.lookup_gate import scoring
from vinga_server import knowledge
from vinga_server.knowledge import lookup

LCD = "devices/waveshare-esp32-s3-touch-lcd-1.54.md"

# What M5 measured (plan, Gate: the target is `scoring.RETRIEVAL_TARGET`,
# 32, and it was not reached). A floor rather than the target, so a
# change that loses a query fails here and one that gains a query
# raises it.
MEASURED_WITH_THE_BOARD = 29
MEASURED_WITHOUT_A_BOARD = 25

FROZEN = {question.id: question for question in scoring.frozen()}


def found(guide: str | None) -> int:
    return sum(
        scoring.holds(knowledge.search(query, guide), FROZEN[question].facts[0])
        for question, query in scoring.recorded_queries()
    )


def test_the_recorded_queries_find_their_fact_as_often_as_measured() -> None:
    """A hit is the answer's text holding the opening of the fact the
    question's first key fact quotes, which is stricter than the gate's
    "the right section in the top three": the passage answered has to
    be the part of the section that says it."""
    assert len(scoring.recorded_queries()) == 39
    assert found(LCD) >= MEASURED_WITH_THE_BOARD
    assert found(None) >= MEASURED_WITHOUT_A_BOARD


def test_the_session_s_board_guide_is_what_wake_word_questions_reach() -> None:
    """Every board has a wake-word section, and the one that answers is
    the board's in front of the person."""
    answer = knowledge.search("change wake word", LCD)
    assert "building the firmware with it" in scoring.flat(answer)
    first = lookup.ranked("change wake word", LCD)[0]
    assert first.page == LCD


def test_a_path_that_is_not_a_board_guide_weighs_nothing() -> None:
    assert lookup.ranked("change wake word", "concepts.md") == lookup.ranked(
        "change wake word", None
    )


def test_an_answer_is_at_most_three_passages_within_the_budget() -> None:
    for _, query in scoring.recorded_queries():
        answer = knowledge.search(query, LCD)
        assert len(answer) <= lookup.ANSWER_CHARS
        assert answer.count("\n---\n") <= lookup.TOP


def test_every_passage_fits_the_budget_alone() -> None:
    """So an answer always carries the best passage, whatever it is."""
    for page, text in knowledge.pages().items():
        for passage in lookup.passages_of(page, text):
            assert len(f"[{passage.title}]\n{passage.text}") <= lookup.ANSWER_CHARS
            assert len(passage.text) <= lookup.PASSAGE_CHARS


def test_the_glossary_is_cut_into_its_entries() -> None:
    titles = {p.title for p in lookup.passages_of("glossary.md", knowledge.pages()["glossary.md"])}
    assert "Glossary: Agent" in titles
    assert "Glossary: Wake word" in titles


def test_on_this_page_lists_are_left_out() -> None:
    for page, text in knowledge.pages().items():
        assert all("On this page" not in p.title for p in lookup.passages_of(page, text))


def test_a_heading_inside_a_fence_is_code() -> None:
    page = "# Title\n\n## Real\n\nbody\n\n```\n## not a heading\n```\n"
    assert [p.title for p in lookup.passages_of("x.md", page)] == ["Title: Real"]


def test_a_level_three_heading_is_titled_under_its_section() -> None:
    page = "# Title\n\n## Section\n\nlead\n\n### Sub\n\nbody\n"
    assert [p.title for p in lookup.passages_of("x.md", page)] == [
        "Title: Section",
        "Title: Section: Sub",
    ]


def test_inflections_meet() -> None:
    assert lookup.terms("changing changed changes") == ["chang"] * 3
    assert lookup.terms("Wi-Fi") == lookup.terms("wifi")


def test_a_query_matching_nothing_says_the_pages_do_not_cover_it() -> None:
    assert knowledge.search("zzqx qqzz", LCD) == lookup.NOTHING_FOUND
    assert knowledge.search("the and of", None) == lookup.NOTHING_FOUND


@pytest.mark.parametrize("guide", [LCD, None])
def test_the_answer_carries_nothing_of_the_query(guide: str | None) -> None:
    """The query is conversation content: what comes back is the pages'
    text, so a credential-shaped string searched for is not in it."""
    planted = "sk-live-QUERYSENTINEL0123456789 wake word"
    answer = knowledge.search(planted, guide)
    assert "QUERYSENTINEL" not in answer
    assert "querysentinel" not in answer.casefold()


def test_a_passage_past_the_budget_is_left_out_whole_and_the_answer_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the real constants three passages always fit, so the budget
    is driven with one that holds the best passage and nothing more."""
    best = lookup.ranked("change wake word", LCD)[0]
    block = f"[{best.title}]\n{best.text}"
    budget = len(block) + len("\n\n---\n\n") + len(lookup.MORE_LEFT_OUT) + 10
    monkeypatch.setattr(lookup, "ANSWER_CHARS", budget)

    answer = knowledge.search("change wake word", LCD)

    assert answer == f"{block}\n\n---\n\n{lookup.MORE_LEFT_OUT}"
    assert len(answer) <= budget
