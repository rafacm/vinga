"""The built-in agent's lookup: the Use pages searched, the best three
passages answered, within a fixed budget.

Shape A of the #612 gate, `search(query)`, which every model measured
called and the `topics()` and `read()` pair none did. What a caller
stops knowing is how a page is cut for searching, how a passage is
scored, how the board a session speaks through weighs in, and how an
answer is bounded: it hands over the words the model searched with and
the board guide the session has, and gets back text the model reads.

**The cut.** Finer than `library.sections()`, which cuts at `##` for
the board facts: a passage here starts at every `##` and `###` heading
outside a fenced block, because the glossary's entries are all `###`
(cut at `##` it is one 28 KB section) and the device guides keep a
subsection under some of their sections. A passage is titled with the
page's title and the headings above it (`Glossary: Agent`,
`Device guides: Getting a board onto your server: Writing the server's
address into NVS`), and its title is searched as well as its text. A
passage longer than `PASSAGE_CHARS` is split at paragraph boundaries
into numbered parts, so one long section cannot take the whole budget
and the part that matches is the part answered. The pages' "On this
page" lists are links and nothing else, and are left out.

**The score.** BM25 over word stems. A word is lowercased, split on
anything that is not a letter or a digit, dropped when it is one of the
function words below, and cut to a stem by a handful of suffix rules
(`changing`, `changes` and `changed` meet at `chang`), so a model's
question and a page's wording meet where they differ only in
inflection. Words the pages spell two ways (`wifi` and `wi-fi`) are
joined before the split. The title counts twice, since a heading names
what its section is about. Plain term overlap and no embedding model:
the package imports nothing outside the standard library.

**The board.** A session that knows its board names that board's guide
(`boards.board_guide`), and the search then leaves the other board
guides out and weighs that guide's passages up by `BOARD_WEIGHT`: a
person asking how to change the wake word is asking about the board in
front of them, and another board's answer to it is a wrong one. A
session that does not know its board searches every page alike.

**The answer.** The best passages, at most `TOP`, each under its title,
best first, and never more than `ANSWER_CHARS` in all. A passage that
would pass the budget is left out whole, and a line says so, so the
model is never handed half a sentence and told it is the page. The
budget is what bounds the round after a lookup, whose first token waits
for the model to read the answer: on a small local model that wait is
the cost of the lookup. A query that matches nothing answers
`NOTHING_FOUND`, a sentence rather than an error, which says the pages
do not cover it.

The constants were chosen by measurement, with no model, against the
queries the models sent in the #612 gate
(`tests/local/lookup_gate/`), and `tests/unit/test_knowledge_lookup.py`
holds the result.

The query is model-written text derived from what a person said, so it
is conversation content: nothing here logs it, raises with it, or keeps
it, and what comes back holds the pages' text and nothing of the query.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import cache

from vinga_server.knowledge.boards import board_guides
from vinga_server.knowledge.library import pages

# How many passages an answer carries, which is the gate's shape A.
TOP = 3

# The longest passage, in characters, before it is split at paragraph
# boundaries into parts. Measured with no model (#612, M5): 700 to
# 1,200 found as much as 1,500 and 3,000 did, and 1,000 is where the
# count stopped moving with the two constants below.
PASSAGE_CHARS = 1_000

# The most an answer carries, in characters, headings and separators
# included. Three passages at the cap and their titles fit.
ANSWER_CHARS = 3_300

# How much more a passage of the session's own board guide counts.
BOARD_WEIGHT = 1.5

NOTHING_FOUND = (
    "The vinga documentation has nothing matching that. Say plainly that you do "
    "not know, or that it is not something vinga does; do not guess."
)

MORE_LEFT_OUT = "(More matched, and was left out to keep this answer short.)"

_SEPARATOR = "\n\n---\n\n"

_FENCES = ("```", "~~~")

_HEADING = re.compile(r"^(#{1,3}) +(.+?)\s*$")

_SKIPPED = frozenset({"on this page"})

# Function words, which every passage has and no question is about.
_STOP = frozenset(
    """a an and are as at be been but by can could do does did for from has have
    how i if in into is it its me my of on or our so than that the their them
    then there these they this those to was we were what when where which who
    why will with would you your yours i'm it's don't can't doesn't isn't""".split()
)

# Spellings the pages and the people asking write two ways, joined
# before the split so both reach one word.
_JOINED = (
    (re.compile(r"\bwi-fi\b"), "wifi"),
    (re.compile(r"\be-paper\b"), "epaper"),
)

_WORD = re.compile(r"[a-z0-9]+")

# Suffixes cut from a word, longest first, each only while the stem
# keeps at least three letters.
_SUFFIXES = ("ations", "ation", "ings", "ing", "edly", "ed", "ies", "es", "ly", "s")


@dataclass(frozen=True)
class Passage:
    """One searchable cut of one page: where it comes from, what it is
    called, and its text."""

    page: str
    title: str
    text: str


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            stem = word[: -len(suffix)]
            return stem + "y" if suffix == "ies" else stem
    return word


def terms(text: str) -> list[str]:
    """The words of `text` this search compares: lowercased, joined,
    split, function words dropped, stemmed."""
    lowered = text.casefold()
    for spelling, joined in _JOINED:
        lowered = spelling.sub(joined, lowered)
    return [_stem(word) for word in _WORD.findall(lowered) if word not in _STOP]


def _fenced(line: str) -> bool:
    return line.lstrip().startswith(_FENCES)


def _pieces(paragraph: str) -> list[str]:
    """A paragraph as itself, or, past `PASSAGE_CHARS`, as runs of its
    lines of at most that length (a long list or table is one paragraph
    to a blank-line split). A single line longer than that is a run of
    its own."""
    if len(paragraph) <= PASSAGE_CHARS:
        return [paragraph]
    runs: list[str] = []
    current = ""
    for line in paragraph.split("\n"):
        if current and len(current) + 1 + len(line) > PASSAGE_CHARS:
            runs.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        runs.append(current)
    return runs


def _parts(text: str) -> list[str]:
    """`text` as one part, or split at blank lines into parts of at most
    `PASSAGE_CHARS`, each a run of whole paragraphs (or of whole lines,
    for a paragraph longer than that)."""
    if len(text) <= PASSAGE_CHARS:
        return [text]
    parts: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", text):
        for piece in _pieces(paragraph):
            if current and len(current) + 2 + len(piece) > PASSAGE_CHARS:
                parts.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        parts.append(current)
    return parts


def passages_of(page: str, text: str) -> list[Passage]:
    """One page cut for searching, by the rule the module states."""
    cuts: list[tuple[list[str], list[str]]] = []
    title = page
    path: list[str] = []
    section: str | None = None
    body: list[str] = []
    fenced = False

    def close() -> None:
        # A cut with nothing but its page title (a lead that is only
        # the `# ` line) has nothing to answer with.
        if any(line.strip() and not _HEADING.match(line) for line in body):
            cuts.append((list(path), list(body)))

    for line in text.splitlines():
        if _fenced(line):
            fenced = not fenced
        heading = None if fenced else _HEADING.match(line)
        if heading is None:
            body.append(line + "\n")
            continue
        level, words = len(heading.group(1)), heading.group(2)
        if level == 1:
            title = words
            body.append(line + "\n")
            continue
        close()
        body = []
        if level == 2:
            section = words
        path = [words] if level == 2 or section is None else [section, words]
    close()
    found: list[Passage] = []
    for headings, lines in cuts:
        if headings and headings[-1].casefold() in _SKIPPED:
            continue
        named = ": ".join([title, *headings])
        parts = _parts("".join(lines).strip())
        for number, part in enumerate(parts, start=1):
            label = named if len(parts) == 1 else f"{named} ({number} of {len(parts)})"
            found.append(Passage(page=page, title=label, text=part))
    return found


@dataclass(frozen=True)
class _Index:
    passages: tuple[Passage, ...]
    counts: tuple[Counter[str], ...]
    lengths: tuple[int, ...]
    average: float
    weight: dict[str, float]


# BM25's two constants: term saturation and length normalization.
_K1 = 2.0
_B = 0.75


@cache
def _index() -> _Index:
    passages = tuple(cut for page, text in pages().items() for cut in passages_of(page, text))
    counts = tuple(Counter(terms(f"{p.title} {p.title} {p.text}")) for p in passages)
    lengths = tuple(sum(c.values()) for c in counts)
    holding: Counter[str] = Counter()
    for count in counts:
        holding.update(count.keys())
    n = len(passages)
    weight = {term: math.log(1 + (n - k + 0.5) / (k + 0.5)) for term, k in holding.items()}
    return _Index(passages, counts, lengths, sum(lengths) / n, weight)


def ranked(query: str, guide: str | None = None, limit: int = TOP) -> list[Passage]:
    """The passages that match `query` at all, best first, at most
    `limit` of them. `guide` is the session's board guide, by its path
    inside the copy, or None when the session does not know its board;
    a path that is not a board guide counts as None."""
    index = _index()
    known = guide if guide in board_guides() else None
    wanted = set(terms(query))
    scored: list[tuple[float, int]] = []
    for position, count in enumerate(index.counts):
        page = index.passages[position].page
        score = 0.0
        norm = _K1 * (1 - _B + _B * index.lengths[position] / index.average)
        for term in wanted:
            seen = count.get(term)
            if seen:
                score += index.weight[term] * seen * (_K1 + 1) / (seen + norm)
        if page == known:
            score *= BOARD_WEIGHT
        if score > 0:
            scored.append((score, position))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [index.passages[position] for _, position in scored[:limit]]


def search(query: str, guide: str | None = None) -> str:
    """The answer to one lookup: the best passages for `query` under
    their titles, within `ANSWER_CHARS`, or `NOTHING_FOUND`. `guide` as
    `ranked` takes it."""
    found = ranked(query, guide)
    if not found:
        return NOTHING_FOUND
    kept: list[str] = []
    used = 0
    left_out = False
    for passage in found:
        block = f"[{passage.title}]\n{passage.text}"
        cost = len(block) + (len(_SEPARATOR) if kept else 0)
        if used + cost + len(_SEPARATOR) + len(MORE_LEFT_OUT) > ANSWER_CHARS:
            left_out = True
            continue
        kept.append(block)
        used += cost
    answer = _SEPARATOR.join(kept)
    return f"{answer}{_SEPARATOR}{MORE_LEFT_OUT}" if left_out else answer
