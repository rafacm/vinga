#!/usr/bin/env python3
"""Hold every Run and Use page to the current-only rule.

Usage: python3 scripts/check_run_use_pages.py <repo-root>

A Run or Use page describes vinga as it is today and stands alone, so
it carries no issue or pull request reference and no "decided
direction" marker; direction lives with its owning issue or record, or
on the Develop door's direction page. Which pages those are is not a
list kept here: it is derived from the Run vinga and Use vinga
sections of docs/README.md, so a page added to either door is under
this check in the commit that adds it.

Enrolment, from the links in those two sections:

- a Markdown page is enrolled, anchor stripped;
- a directory under docs/ enrolls every .md file under it, and a
  directory anywhere else enrolls nothing (it holds artifacts, not
  pages);
- a README.md under docs/ is an index and enrolls its whole directory,
  exactly as a link to the directory would, so a guide its index
  forgot to list is still enrolled; an index is never followed out of
  its directory;
- a README.md outside docs/ enrolls that page alone;
- pages under docs/reference/ are excluded (the generated references
  are the facts class, changed only through their generators), as are
  same-page anchors, non-Markdown targets, external links and
  docs/README.md itself, which is an index page and may cite issues.

Refused on every line of an enrolled page, fenced code included: a
`#<digits>` not preceded by a word character, `&` or `/`; an
`<owner>/<repo>#<digits>`; a github.com issues or pull URL; and the
phrase "decided direction" in any case, including across a line break.

Door discovery fails closed: a missing docs/README.md, a missing
`## Run vinga` or `## Use vinga` heading, or a door section that
enrolls no page is a `door-missing` finding, so a renamed heading
cannot switch the check off. A door heading that appears twice gives
two sections, each held to these rules, so a second one cannot hide
the pages the first links. Each door section is read as one text
(its lines outside fences joined with spaces), so link text wrapped
across lines is still a link; a link whose target is broken by a line
break cannot be read that way, and a section with more `](` openers
than links read is a `door-malformed` finding on its heading line.

A finding names the file, the line and the kind (`issue-reference`,
`direction-marker`, `door-missing`, `door-malformed`) and nothing of
the line itself, on the link checker's reasoning: what a page should
never have held is not republished into a CI log by the tool that
finds it. Exit 1 on any finding, 2 on a bad invocation or an
unreadable page.

The link grammar and the fence rule are the link checker's own,
imported rather than copied, since the two must agree on what a link
is.
"""

import re
import sys
from pathlib import Path

from check_doc_links import CODE_FENCE_RE, IMG_RE, LINK_RE, SKIP_SCHEMES

DOORS = ("Run vinga", "Use vinga")
SECTION_END_RE = re.compile(r"^#{1,2}\s")

ISSUE_PATTERNS = (
    # A bare #123, but not #binding, &#8217; or page.md#1.
    re.compile(r"(?<![\w&/])#\d+"),
    # owner/repo#123; a Markdown path's fragment (page.md#1) is not one.
    re.compile(r"(?<![\w./-])[A-Za-z0-9][A-Za-z0-9-]*/[\w.-]+(?<!\.md)#\d+"),
    # https://github.com/owner/repo/issues/123 or /pull/123.
    re.compile(r"github\.com/[^/\s]+/[^/\s]+/(?:issues|pull)/"),
)
MARKER_RE = re.compile(r"decided\s+direction", re.IGNORECASE)


class Unreadable(Exception):
    """A page the check was asked to read and could not."""


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Unreadable(path) from exc


def door_sections(lines: list) -> dict:
    """Each door's sections, as (heading line, body lines outside fences).

    A door heading that appears twice gives the door two sections, each
    held to the door rules on its own, so a page linked only from the
    first is still enrolled rather than replaced by the second.
    """
    sections: dict = {}
    current = None
    in_fence = False
    for lineno, line in enumerate(lines, 1):
        if CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if SECTION_END_RE.match(line):
            title = line.lstrip("#").strip()
            if title in DOORS:
                current = (lineno, [])
                sections.setdefault(title, []).append(current)
            else:
                current = None
            continue
        if current is not None:
            current[1].append(line)
    return sections


def markdown_under(directory: Path) -> list:
    return sorted(p for p in directory.rglob("*.md") if p.is_file())


def enroll(target: str, index: Path, root: Path) -> list:
    """The pages one door link brings under the check."""
    if target.startswith(SKIP_SCHEMES):
        return []
    path, _, _ = target.partition("#")
    if not path:
        return []
    try:
        resolved = (index.parent / path).resolve()
    except OSError:
        return []
    docs = root / "docs"
    if not resolved.is_relative_to(root) or resolved == index:
        return []
    if resolved.is_dir():
        return markdown_under(resolved) if resolved.is_relative_to(docs) else []
    if resolved.suffix != ".md" or not resolved.is_file():
        return []
    if resolved.name == "README.md" and resolved.is_relative_to(docs):
        return markdown_under(resolved.parent)
    return [resolved]


def scan(text: str) -> set:
    """(line, kind) for every refused pattern in a page's text."""
    found = set()
    for lineno, line in enumerate(text.splitlines(), 1):
        if any(p.search(line) for p in ISSUE_PATTERNS):
            found.add((lineno, "issue-reference"))
    for m in MARKER_RE.finditer(text):
        found.add((text.count("\n", 0, m.start()) + 1, "direction-marker"))
    return found


def check(root: Path) -> tuple:
    """Every finding, as (path, line, kind), in output order, and the
    number of pages enrolled."""
    index = root / "docs" / "README.md"
    rel_index = index.relative_to(root).as_posix()
    if not index.is_file():
        return [(rel_index, 0, "door-missing")], 0
    sections = door_sections(read(index).splitlines())
    findings = []
    pages: set = set()
    reference = root / "docs" / "reference"
    for door in DOORS:
        if door not in sections:
            findings.append((rel_index, 0, "door-missing"))
            continue
        for heading, body in sections[door]:
            text = " ".join(body)
            targets = [m.group(1) for m in LINK_RE.finditer(text)]
            read_links = len(targets) + len(IMG_RE.findall(text))
            if text.count("](") > read_links:
                findings.append((rel_index, heading, "door-malformed"))
            enrolled = set()
            for raw in targets:
                if raw.startswith("<") and raw.endswith(">"):
                    raw = raw[1:-1]
                enrolled.update(
                    p for p in enroll(raw, index, root)
                    if not p.is_relative_to(reference)
                )
            if not enrolled:
                findings.append((rel_index, heading, "door-missing"))
            pages |= enrolled
    for page in sorted(pages):
        rel = page.relative_to(root).as_posix()
        for lineno, kind in sorted(scan(read(page))):
            findings.append((rel, lineno, kind))
    return findings, len(pages)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_run_use_pages.py <repo-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    if not root.is_dir():
        print("the given repo-root is not a directory", file=sys.stderr)
        return 2
    root = root.resolve()
    try:
        findings, pages = check(root)
    except Unreadable as exc:
        where = Path(str(exc)).relative_to(root).as_posix()
        print(f"cannot read {where}", file=sys.stderr)
        return 2
    for path, lineno, kind in findings:
        print(f"{path}:{lineno}: {kind}")
    print(f"checked {pages} Run and Use pages, {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
