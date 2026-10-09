"""The #612 lookup gate's committed fixtures, held to what they claim
(plan review round 2, finding 6): the frozen set is the set the gate
froze, the rephrased set asks the same questions, and every key fact
is still on the page it quotes."""

import hashlib

from tests.local.lookup_gate import scoring
from vinga_server import knowledge


def test_the_frozen_set_is_byte_for_byte_the_one_the_gate_froze() -> None:
    raw = (scoring.HERE / "frozen.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == scoring.FROZEN_SHA256


def test_both_sets_ask_the_same_32_questions() -> None:
    frozen = [q.id for q in scoring.frozen()]
    assert len(frozen) == 32
    assert [q.id for q in scoring.rephrased()] == frozen
    assert all(
        a.text != b.text for a, b in zip(scoring.frozen(), scoring.rephrased(), strict=True)
    )


def test_every_key_fact_is_still_on_its_page() -> None:
    """Found by text in the packaged copy, which is the page vinga
    reads, so a page edit that loses a quoted sentence fails here and
    names the question whose fact moved."""
    pages = knowledge.pages()
    lost = [
        question.id
        for question in scoring.frozen()
        for fact in question.facts
        if scoring.flat(fact.phrase) not in scoring.flat(pages[fact.doc.removeprefix("docs/")])
    ]
    assert lost == []


def test_every_recorded_query_belongs_to_a_lookup_question() -> None:
    expected = {q.id: q.expected for q in scoring.frozen()}
    assert {expected[question] for question, _ in scoring.recorded_queries()} == {
        scoring.LOOKUP
    }
