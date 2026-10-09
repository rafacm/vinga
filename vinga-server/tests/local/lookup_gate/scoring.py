"""The #612 lookup gate's question sets and its scorer, readable with no
model.

Four fixtures sit beside this module:

- `frozen.json`: the 32 questions frozen before the gate's first model
  call (sha256 `FROZEN_SHA256`), byte for byte as the gate ran them,
  each with the key facts a correct answer holds, quoted from a page.
- `amendments.json`: the questions whose key facts have since moved
  with the pages they quote, each with the reason. A question's text
  never changes; what is true about it follows the page.
- `rephrased.json`: the same 32 questions in other words, written
  before retrieval was tuned, for the second model run.
- `queries.json`: the 39 `search()` calls the models made on lookup
  questions in the gate's shape-A runs, which retrieval is measured on.

A key fact names its page and a phrase; the phrase is found by text,
not by line, so a page edit that keeps the sentence keeps the fact, and
`tests/unit/test_lookup_gate_fixtures.py` fails when one is lost.

The scorer is the gate's automatic score with the hand-check replaced
by a rule: what the rules cannot decide (an answer holding some of the
key facts, or none, with nothing contradicting them) is `undecided`,
reported for a person to read and never counted as correct or as a
hallucination. So the bar is held conservatively: an undecided answer
is one the gate does not credit.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent

FROZEN_SHA256 = "1442b569af5c90810eec945ab3d459a3337ec811030422fd110011d9d415e181"

# What the gate counts as needing the lookup, the device's own tool,
# and the two outcomes of a question the pages cannot answer.
LOOKUP = "lookup"
DEVICE_TOOL = "device_tool"
DECLINE = "decline"

VOLUME_TOOL = "self_audio_speaker_set_volume"

# The categories an answer is scored into. `undecided` is the one the
# hand-check used to settle.
CORRECT = "correct"
HALLUCINATED = "hallucinated"
HONEST_DECLINE = "honest_decline"
DEVICE_OK = "device_ok"
TOOL_ERROR = "tool_error"
TIMEOUT = "timeout"
UNDECIDED = "undecided"

# The bar M5's gate set (plan, Gate): at least this share correct and
# at most this share hallucinated, on each set.
CORRECT_AT_LEAST = 0.70
HALLUCINATED_AT_MOST = 0.10

# And retrieval's, measured with no model over `queries.json`.
RETRIEVAL_TARGET = 32

_DECLINING = re.compile(
    r"don'?t know|do not know|not sure|no information|couldn'?t find|could not find|"
    r"can'?t find|didn'?t find|did not find|not something|isn'?t something|"
    r"doesn'?t (support|have|mention|say|cover|include)|"
    r"does not (support|have|mention|say|cover|include)|"
    r"not (supported|possible|documented|mentioned|available|covered)|\bcan'?t\b|"
    r"\bcannot\b|\bunable\b|I don'?t have|isn'?t (a|an) (feature|capability)|"
    r"no (such )?feature|not (a )?feature|not able to|don'?t (support|offer)|"
    r"no mention|do not have|does not (specify|state)|not specified",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Fact:
    phrase: str
    doc: str
    match: str


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    expected: str
    facts: tuple[Fact, ...]
    contradicts: tuple[str, ...]
    exchange: str | None
    tool: dict | None
    confident: str | None


def _load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


@cache
def frozen() -> tuple[Question, ...]:
    """The frozen set, with the amendments applied to its facts."""
    amended = _load("amendments.json")["questions"]
    out = []
    for raw in _load("frozen.json")["questions"]:
        source = amended.get(raw["id"], raw)
        out.append(
            Question(
                id=raw["id"],
                text=raw["text"],
                expected=raw["expected"],
                facts=tuple(
                    Fact(f["phrase"], f["doc"], f["match"]) for f in source.get("facts", [])
                ),
                contradicts=tuple(source.get("contradicts", [])),
                exchange=raw.get("exchange"),
                tool=raw.get("tool"),
                confident=raw.get("confident"),
            )
        )
    return tuple(out)


@cache
def rephrased() -> tuple[Question, ...]:
    """The rephrased set: the frozen set's questions, facts and all,
    asked in other words."""
    texts = {q["id"]: q["text"] for q in _load("rephrased.json")["questions"]}
    return tuple(
        Question(
            id=q.id,
            text=texts[q.id],
            expected=q.expected,
            facts=q.facts,
            contradicts=q.contradicts,
            exchange=q.exchange,
            tool=q.tool,
            confident=q.confident,
        )
        for q in frozen()
    )


@cache
def recorded_queries() -> tuple[tuple[str, str], ...]:
    """The 39 recorded searches, as (question id, query)."""
    return tuple((q["question"], q["query"]) for q in _load("queries.json")["queries"])


def flat(text: str) -> str:
    """`text` with every run of whitespace one space, which is how a
    phrase is found in a page however the page wraps it."""
    return re.sub(r"\s+", " ", text).strip()


def holds(text: str, fact: Fact) -> bool:
    """Whether `text` carries the opening of `fact`'s phrase: the first
    line, up to forty characters, as the gate's retrieval check read it."""
    return flat(fact.phrase.split("\n")[0])[:40] in flat(text)


@dataclass(frozen=True)
class Call:
    name: str
    arguments: dict
    malformed: bool


@dataclass(frozen=True)
class Answer:
    """What one question got: the calls made, in order, the final text,
    and how the run ended."""

    calls: tuple[Call, ...]
    text: str
    looped: bool
    timed_out: bool


def score(question: Question, answer: Answer, lookup_tool: str) -> tuple[str, bool, str]:
    """The answer's category, whether it hallucinated, and why.

    The gate's automatic rules, first match wins, with `undecided` where
    the hand-check used to decide."""
    names = [call.name for call in answer.calls]
    looked_up = lookup_tool in names
    text = answer.text or ""
    if answer.timed_out:
        return TIMEOUT, False, "timed out"
    if answer.looped:
        return TOOL_ERROR, False, "still calling tools at the last round"
    if any(call.malformed for call in answer.calls):
        return TOOL_ERROR, False, "malformed arguments"
    if question.expected == DEVICE_TOOL:
        made = [call for call in answer.calls if call.name == VOLUME_TOOL]
        if not made:
            return TOOL_ERROR, False, "no device tool call"
        volume = made[-1].arguments.get("volume")
        if not isinstance(volume, int) or isinstance(volume, bool):
            return TOOL_ERROR, False, f"volume not an int: {volume!r}"
        assert question.tool is not None
        exact = question.tool.get("volume_exact")
        if exact is not None and volume != exact:
            return TOOL_ERROR, False, f"wrong volume {volume}"
        if not 0 <= volume <= 100:
            return TOOL_ERROR, False, f"volume out of range {volume}"
        if looked_up:
            return TOOL_ERROR, False, "looked up before the device command"
        return DEVICE_OK, False, f"volume={volume}"
    if VOLUME_TOOL in names:
        return TOOL_ERROR, True, "device tool called for a question"
    if question.expected == DECLINE:
        assert question.confident is not None
        if re.search(question.confident, text, re.IGNORECASE):
            return HALLUCINATED, True, "confident unsupported claim"
        if _DECLINING.search(text):
            return HONEST_DECLINE, False, "declined"
        return UNDECIDED, False, "no decline language and no confident claim"
    contradicted = [c for c in question.contradicts if re.search(c, text, re.IGNORECASE)]
    if contradicted:
        return HALLUCINATED, True, f"contradicts {contradicted}"
    present = [bool(re.search(f.match, text, re.IGNORECASE)) for f in question.facts]
    if present and all(present):
        return CORRECT, False, "every key fact"
    if question.expected == LOOKUP and not looked_up and not any(present):
        return TOOL_ERROR, False, "no lookup when one was needed, and no key fact"
    return UNDECIDED, False, f"key facts {sum(present)} of {len(present)}"
