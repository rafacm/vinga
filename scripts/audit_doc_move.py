#!/usr/bin/env python3
"""Show that a page move lost nothing, without republishing the page.

Usage:
    python3 scripts/audit_doc_move.py OLD NEW MAPPING
    python3 scripts/audit_doc_move.py OLD --list LINE

OLD is the page before the move (for a pull request, `git show
<base>:<path>` written to a file), NEW the same page after it, and
MAPPING the committed record of where each part of OLD went. Run it
from the repository root: the destinations a mapping names are paths
relative to the current directory.

A paragraph is a run of non-blank lines; a fenced code block is one
paragraph whatever blank lines it holds. Paragraphs compare with their
whitespace collapsed, so a rewrapped paragraph is still verbatim, and
headings compare without their #s, so a demoted heading still matches.

MAPPING has one move unit per line, tab-separated:

    LINE [FIRST-LAST] DESTINATION [kinds=K,K] [edited=P,P]

LINE is the 1-based line of a heading in OLD. The unit is that
heading's section (its own paragraphs and those of deeper headings, up
to the next heading as shallow), or only its paragraphs FIRST to LAST
(1-based, inclusive, the heading being paragraph 1). --list prints the
paragraphs of the section at LINE with their positions.

DESTINATION is a page the unit moved to, or one of two keywords:

- DROP: the unit was removed on purpose; each paragraph is reported as
  declared dropped and must not stay in NEW.
- README: the unit stays in NEW on purpose, as a forwarding stub. It
  must name exactly one paragraph, a heading, which must still be in
  NEW; text left under it is still reported as left behind.

A moved unit says which kinds of text it holds, `kinds=` one or more
of procedure, explanation and contract, and may declare `edited=` the
positions expected not to be verbatim in its destination (a rewritten
link, a replaced table, a reworded claim, a new order). Blank lines and
lines starting with # are ignored.

Every paragraph of a moved unit must occur verbatim in its destination
at least as often as the units name it, unless it is declared edited;
none may occur in NEW more often than the paragraphs no unit moved
hold it. A paragraph two units name, a declared edit that is in fact
verbatim, and a README unit that is not one present heading are
findings too. Exit 0 when every paragraph is accounted for, 1 on any
finding, 2 on a bad invocation, an unreadable file or a malformed
mapping.

Output names a mapping row, a paragraph position, a source line, a
destination and the first 12 hex digits of a SHA-256, never any byte
of the page, headings included: whatever a paragraph ever held is not
republished into a log or a pull request body by the tool that audits
its move. Findings start with `finding:`, declarations with
`declared:`, and the last line counts both.
"""

import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

KINDS = frozenset({"procedure", "explanation", "contract"})
FENCE = ("```", "~~~")
HEADING_RE = re.compile(r"^(#{1,6})\s")
RANGE_RE = re.compile(r"^(\d+)-(\d+)$")
DROP = "DROP"
KEPT = "README"


class Malformed(Exception):
    """An invocation, a file or a mapping the audit cannot run on.

    Its message names rows, lines and paths only, never page text.
    """


def read(path: str, what: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Malformed(f"cannot read {what}") from exc


def paragraphs(text: str) -> list:
    """(start line, normalized text, depth) per paragraph; depth 0 is
    not a heading."""
    out, buf, start, fence = [], [], 0, False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(FENCE):
            fence = not fence
        if not line.strip() and not fence:
            if buf:
                out.append((start, buf))
                buf = []
        else:
            if not buf:
                start = n
            buf.append(line)
    if buf:
        out.append((start, buf))
    result = []
    for s, block in out:
        m = HEADING_RE.match(block[0])
        depth = len(m.group(1)) if m else 0
        joined = " ".join(block)
        if depth:
            joined = joined.lstrip("#")
        result.append((s, " ".join(joined.split()), depth))
    return result


def section(paras: list, line: int, row: str) -> list:
    """The paragraphs of the section whose heading starts at `line`."""
    starts = [s for s, _, _ in paras]
    if line not in starts:
        raise Malformed(f"{row}line {line} starts no paragraph of the old page")
    i = starts.index(line)
    depth = paras[i][2]
    if not depth:
        raise Malformed(f"{row}line {line} is not a heading")
    j = i + 1
    while j < len(paras) and not 0 < paras[j][2] <= depth:
        j += 1
    return paras[i:j]


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def positions(value: str, row: int) -> set:
    try:
        found = {int(p) for p in value.split(",") if p}
    except ValueError as exc:
        raise Malformed(f"row {row}: edited= takes positions") from exc
    if not found:
        raise Malformed(f"row {row}: edited= names no position")
    return found


def parse_unit(row: int, line: str, old: list) -> tuple:
    """(row, destination, chosen paragraphs, kinds, edited) for one row."""
    fields = line.split("\t")
    try:
        heading = int(fields[0])
    except ValueError as exc:
        raise Malformed(f"row {row}: the first field is a line number") from exc
    sec = section(old, heading, f"row {row}: ")
    rest = fields[1:]
    first, last = 1, len(sec)
    if rest and RANGE_RE.match(rest[0]):
        first, last = (int(x) for x in RANGE_RE.match(rest[0]).groups())
        rest = rest[1:]
        if not 1 <= first <= last <= len(sec):
            raise Malformed(f"row {row}: the range is outside the section's {len(sec)} paragraphs")
    if not rest or not rest[0] or "=" in rest[0]:
        raise Malformed(f"row {row}: no destination")
    dest, options = rest[0], rest[1:]
    kinds: set = set()
    edited: set = set()
    for option in options:
        key, _, value = option.partition("=")
        if key == "kinds":
            kinds = {k for k in value.split(",") if k}
            if not kinds or kinds - KINDS:
                raise Malformed(f"row {row}: kinds= takes {', '.join(sorted(KINDS))}")
        elif key == "edited":
            edited = positions(value, row)
        else:
            raise Malformed(f"row {row}: an unknown field")
    if dest in (DROP, KEPT):
        if kinds or edited:
            raise Malformed(f"row {row}: a {dest} unit takes no kinds= or edited=")
    elif not kinds:
        raise Malformed(f"row {row}: a moved unit says its kinds=")
    if edited - set(range(first, last + 1)):
        raise Malformed(f"row {row}: edited= names a position outside the unit")
    chosen = list(enumerate(sec, 1))[first - 1 : last]
    return row, dest, chosen, kinds, edited


def parse_mapping(text: str, old: list) -> list:
    units = []
    for row, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        units.append(parse_unit(row, line, old))
    if not units:
        raise Malformed("the mapping names no unit")
    return units


def audit(old_text: str, new_text: str, mapping_text: str) -> tuple:
    """(findings, declarations, summary) as output lines."""
    old = paragraphs(old_text)
    units = parse_mapping(mapping_text, old)
    new_counts = Counter(n for _, n, _ in paragraphs(new_text))

    kept = Counter(n for _, n, _ in old)
    claimed: Counter = Counter()
    for _, dest, chosen, _, _ in units:
        for _, (start, norm, _) in chosen:
            claimed[start] += 1
            if dest != KEPT:
                kept[norm] -= 1

    findings = [
        f"finding: line {start}: named by {count} units"
        for start, count in sorted(claimed.items())
        if count > 1
    ]
    declared = []
    tally: Counter = Counter()
    dests: dict = {}
    moved = 0
    for row, dest, chosen, _, edited in units:
        if dest == KEPT:
            (_, (start, norm, depth)), *more = chosen
            if more or not depth:
                findings.append(
                    f"finding: row {row}: a kept unit names one heading and nothing else"
                )
                continue
            tag = f"row {row}, paragraph {chosen[0][0]} (line {start}, {digest(norm)})"
            if new_counts[norm] > 0:
                declared.append(f"declared: {tag}: kept in the page")
                tally["kept"] += 1
            else:
                findings.append(f"finding: {tag}: not kept in the page")
            continue
        if dest != DROP and dest not in dests:
            text = read(dest, f"the destination on row {row}")
            dests[dest] = Counter(n for _, n, _ in paragraphs(text))
        for pos, (start, norm, _) in chosen:
            moved += 1
            tag = f"row {row}, paragraph {pos} (line {start}, {digest(norm)})"
            if dest == DROP:
                declared.append(f"declared: {tag}: dropped")
                tally["dropped"] += 1
            elif pos in edited:
                if dests[dest][norm] > 0:
                    findings.append(f"finding: {tag}: declared edited but verbatim in {dest}")
                else:
                    declared.append(f"declared: {tag}: edited, not verbatim in {dest}")
                    tally["edited"] += 1
            elif dests[dest][norm] > 0:
                dests[dest][norm] -= 1
            else:
                findings.append(f"finding: {tag}: not verbatim in {dest}")
            if new_counts[norm] > max(kept[norm], 0):
                findings.append(f"finding: {tag}: left behind in the page")
    summary = (
        f"{len(units)} units, {moved} paragraphs moved, {tally['edited']} declared edited, "
        f"{tally['dropped']} declared dropped, {tally['kept']} kept in the page, "
        f"{len(findings)} findings"
    )
    return findings, declared, summary


def list_section(old_text: str, line: str) -> list:
    try:
        heading = int(line)
    except ValueError as exc:
        raise Malformed("--list takes a line number") from exc
    out = []
    for pos, (start, norm, depth) in enumerate(section(paragraphs(old_text), heading, ""), 1):
        mark = ", heading" if depth else ""
        out.append(f"paragraph {pos}: line {start}, {digest(norm)}{mark}")
    return out


def main(argv: list) -> int:
    try:
        if len(argv) == 3 and argv[1] == "--list":
            print("\n".join(list_section(read(argv[0], "the old page"), argv[2])))
            return 0
        if len(argv) != 3:
            print(
                "usage: audit_doc_move.py OLD NEW MAPPING | audit_doc_move.py OLD --list LINE",
                file=sys.stderr,
            )
            return 2
        old_text = read(argv[0], "the old page")
        new_text = read(argv[1], "the new page")
        mapping_text = read(argv[2], "the mapping")
        findings, declared, summary = audit(old_text, new_text, mapping_text)
    except Malformed as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for line in declared + findings:
        print(line)
    print(summary)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
