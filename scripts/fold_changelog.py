#!/usr/bin/env python3
"""Changelog fragments: fold them, check them, guard the file they replace.

Usage:
  fold_changelog.py fold <repo-root>
  fold_changelog.py check <repo-root>
  fold_changelog.py guard            # changed files on stdin, body in PR_BODY

A branch never edits `CHANGELOG.md`. It writes one
`changelog.d/<issue>-<slug>.md` holding `### <Class>` headings from the
closed Keep a Changelog six and the entry text exactly as it should
read in the changelog. Two branches adding two files cannot conflict,
which is the conflict class this removes; `changelog.d/README.md`
states the contract for whoever writes one.

- `fold` moves every fragment's entries into the dated section of
  `CHANGELOG.md` and deletes the fragments. The section is the
  committer date of the commit that brought the fragment onto `main`,
  read along first-parent history and rendered in that commit's own
  recorded offset, so a merge just before midnight and a fold just
  after agree. Fragments are ordered by their introduction commit's
  position in that history, with the filename as the tie-breaker for
  fragments one commit brought in together. Nothing is written unless
  the post-conditions below hold, and a run that finds no fragments is
  a no-op.
- `check` validates fragments without writing: filenames, headings
  against the six, non-empty bodies, no date header.
- `guard` reads a changed-file list on stdin and the pull request body
  from `PR_BODY` (absent and empty both meaning no body), and refuses
  a list that touches `CHANGELOG.md` unless the body carries the
  literal escape phrase.

Exit codes follow `check_doc_links.py`: 0 success, 1 a failure the
caller has to act on, 2 a bad invocation.

What the fold promises, checked on the assembled text before any byte
reaches the disk:

- every fragment's entry appears verbatim exactly once;
- no conflict marker appears anywhere in the file;
- the file outside the sections this run touched is byte-identical;
- a section this run created is canonical, one heading per class in
  Keep a Changelog order, and a section it appended into keeps its
  standing shape, its headings still present and still in the order
  they were in.

And once they hold, the mutation is ordered so that no failure can
leave the tree half folded. The new changelog is written first, into a
file created exclusively beside the old one under a name nothing can
guess; then the fragments are removed; then the changelog is replaced
by a rename, which either happens or does not. So the changelog is
never half a fold, and a failure before the rename puts the fragments
back, content and mode, into the directory whose own removals just
proved it writable. A restore that itself fails says so in its own
sentence rather than hiding inside the first.

Line endings are content, and nothing in this repository forces them
to be one thing, so nothing here reads or writes through Python's
universal-newline translation. An entry keeps the fragment's own
endings because moving it verbatim means moving those bytes too; what
the fold adds around it (a dated heading, a class heading, a blank
line) is written in the changelog's own ending. A fragment and a
changelog that disagree therefore produce a section that disagrees
with itself, which is the honest outcome: the alternative is rewriting
an entry nobody asked to have rewritten.

The post-conditions are deliberately not global. Settled history is
not canonical (one section orders Fixed before Changed, another
carries two Added headings), so a global rule would have to reject the
repository or rewrite what is deliberately kept. Legacy sections are
parsed permissively and never validated, normalized or rewritten.

Output discipline, inherited wholesale from `check_doc_links.py`,
because every input here is repository-derived text landing in a
public CI log: fragment bodies, fragment filenames, changelog content
and git's own diagnostics. Every message is a fixed sentence of this
module's own, carrying at most a count. No fragment text, no heading,
no filename, no git output, no exception text and no traceback is ever
reproduced. Every filesystem call is a named refusal with its
exception chaining suppressed, and `main` carries an `OSError`
backstop for the one somebody adds later without remembering.
Fragment paths that are symlinks or otherwise not regular files are
refused before anything reads them, git runs as an argument-list
subprocess with both streams captured and neither re-emitted, and the
argument parser answers a bad invocation in this module's words rather
than by repeating what was typed.
"""

import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

# The closed six, in Keep a Changelog order. The order is the artifact:
# a section this script creates is written in it, and a heading this
# script has to insert is placed by it.
CLASSES = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

FRAGMENT_DIR = "changelog.d"
CHANGELOG = "CHANGELOG.md"

# The one file in the directory that is not a fragment, excluded by
# name so the contract can live where the fragments do.
NOT_A_FRAGMENT = "README.md"

# `<issue>-<slug>.md`: the issue number (or the pull request number
# where no issue exists), a dash, and a lowercase-and-dashes slug.
FRAGMENT_NAME = re.compile(r"^[0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")

SECTION = re.compile(r"^##[ \t]+(.+?)[ \t]*$")
ENTRY_HEADING = re.compile(r"^###[ \t]+(.+?)[ \t]*$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# What a fragment may not carry: the dated section header and the
# document title. The date is derived from the commit, so a fragment
# stating one is stating something it cannot know.
TOP_HEADING = re.compile(r"^#{1,2}[ \t]")

# The phrase that says a pull request means to correct history rather
# than to have forgotten the fragment. Pinned here, quoted in the
# refusal, and named by the test that holds it.
ESCAPE_PHRASE = "Corrects CHANGELOG history"

# The environment variable the workflow passes the pull request body
# in. An environment value rather than an interpolation into a shell
# script: a body is attacker-controlled text.
BODY_VARIABLE = "PR_BODY"


class Refusal(Exception):
    """A failure the caller has to act on, carrying a fixed sentence.

    Every refusal leaves through this one door, and its message is
    always assembled from literals of this module. That is what keeps
    a fragment body, a filename or a git diagnostic from reaching a CI
    log through the tool that found it wrong.
    """


NOT_A_REGULAR_FILE = "a path under changelog.d is not a regular file"
NOT_UTF8 = "a fragment is not valid UTF-8"
BAD_NAME = "a fragment is not named <issue>-<slug>.md"
UNKNOWN_HEADING = "a fragment names a heading outside the Keep a Changelog six"
NO_HEADING = "a fragment carries no class heading"
EMPTY_BODY = "a fragment has a class heading with no entry text"
DATE_HEADING = "a fragment carries a date or top-level heading"
NO_INTRODUCTION = "a fragment's introduction commit is not in the available history"
GIT_FAILED = "a git command failed"
UNREADABLE_CHANGELOG = "CHANGELOG.md is missing, a symlink, or not valid UTF-8"
NOT_ONCE = "an entry would not appear exactly once in the changelog"
CONFLICT_MARKER = "the changelog would carry a conflict marker"
OUTSIDE_CHANGED = "the changelog outside the folded sections would change"
MALFORMED_SECTION = "a folded section would not be well formed"
PREFIX_TEXT = "a fragment carries text before its first class heading"
NO_DIRECTORY = "changelog.d is missing, a symlink, or not a directory"
CANNOT_LIST = "the changelog.d directory cannot be listed"
CANNOT_REMOVE = "a fragment could not be removed"
CANNOT_WRITE = "CHANGELOG.md could not be written"
NOT_RESTORED = "a failed fold could not be undone and the tree is half folded"
FILESYSTEM = "a filesystem operation failed"


def _fail(reasons: list[str]) -> int:
    """Every distinct reason once, with the count of what hit it."""
    for reason in sorted(set(reasons)):
        print(f"{reason} ({reasons.count(reason)})", file=sys.stderr)
    return 1


# Fragments


def fragment_paths(root: Path) -> list[Path]:
    """Every fragment file, in filename order.

    The README is excluded by name and nothing else is excluded at
    all. A skipped entry is an entry nobody folds and nobody is told
    about: a tracked `.467-entry.md` passed `check` with zero failures
    and then made the fold report nothing to fold, which is a dropped
    changelog entry arriving through the door this mechanism was built
    to close. So every other name in the directory is a fragment and
    is held to the grammar, and a stray file is a refusal rather than
    a silence.

    The directory itself is part of the contract, and its absence is a
    refusal rather than an empty answer. An empty listing used to mean
    the same thing as a healthy empty directory, so a pull request
    replacing `changelog.d` with a regular file or a symlink passed
    `check` with zero fragments and left `main` with the mechanism
    switched off and every run green. A symlink is refused even when
    it points at a directory: the fold would then read and delete
    files outside the checkout it is folding.

    Enumeration is a filesystem call like any other and fails like one,
    so an unreadable directory is a fixed refusal rather than an
    `OSError` climbing out of the script and printing a traceback with
    repository paths in it.
    """
    directory = root / FRAGMENT_DIR
    if directory.is_symlink() or not directory.is_dir():
        raise Refusal(NO_DIRECTORY)
    try:
        listed = sorted(directory.iterdir(), key=lambda p: p.name)
    except OSError:
        raise Refusal(CANNOT_LIST) from None
    return [path for path in listed if path.name != NOT_A_FRAGMENT]


def text_of(path: Path) -> str:
    """One file's text with its line endings left alone.

    `read_text` translates every CRLF to a bare LF on the way in, and
    this script's two loudest promises are that an entry is moved byte
    for byte and that the changelog outside the touched sections is
    byte-identical. Under translation a CRLF fragment arrived as LF and
    was folded as LF, and a CRLF changelog was rewritten whole while
    the post-condition compared two already-normalized strings and saw
    nothing wrong. So nothing here reads through the translation, and
    nothing writes through it either.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _newline(text: str) -> str:
    """The ending a file writes its own lines with.

    What the fold adds (a heading, a blank line, a dated section) is
    written in the changelog's ending. What it moves keeps the
    fragment's, because moving it means moving the bytes.
    """
    return "\r\n" if "\r\n" in text else "\n"


def _read(path: Path) -> str:
    """One fragment's text, refusing anything that is not a plain file.

    The symlink check comes before the read, not after: following a
    link out of the checkout would fold text nobody reviewed into the
    changelog, and `is_file()` alone follows it.
    """
    if path.is_symlink() or not path.is_file():
        raise Refusal(NOT_A_REGULAR_FILE)
    try:
        return text_of(path)
    except UnicodeDecodeError:
        raise Refusal(NOT_UTF8) from None
    except OSError:
        raise Refusal(NOT_A_REGULAR_FILE) from None


def entries_of(text: str) -> list[tuple[str, str]]:
    """One fragment as the (class, entry text) pairs it declares.

    The entry text is what sits between one `###` heading and the
    next, with blank lines at either end trimmed and nothing else
    touched: what the fold moves is these bytes.
    """
    found: list[tuple[str, str]] = []
    heading: str | None = None
    body: list[str] = []
    for line in text.splitlines(keepends=True):
        match = ENTRY_HEADING.match(line.rstrip("\r\n"))
        if match is not None:
            if heading is not None:
                found.append((heading, "".join(body)))
            heading = match.group(1)
            body = []
            continue
        if heading is not None:
            body.append(line)
    if heading is not None:
        found.append((heading, "".join(body)))
    return [(name, _trimmed(text)) for name, text in found]


def prefix_of(text: str) -> str:
    """Whatever a fragment says before its first class heading.

    `entries_of` reads a fragment from that heading onward, so
    anything above it is text the fold would discard without telling
    anyone: an entry somebody wrote without its heading, or a note to
    the reviewer that would silently not become a changelog line. The
    parser accounts for the whole file, and this is the half that has
    nowhere to go.
    """
    taken: list[str] = []
    for line in text.splitlines():
        if ENTRY_HEADING.match(line.rstrip()):
            break
        taken.append(line)
    return "".join(f"{line}\n" for line in taken)


def _trimmed(text: str) -> str:
    """One entry's lines with the blank ones at either end removed and
    a single trailing newline."""
    lines = text.splitlines(keepends=True)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += _newline(text)
    return "".join(lines)


def validate(root: Path) -> list[str]:
    """Every fragment held to the contract, without writing anything."""
    reasons: list[str] = []
    for path in fragment_paths(root):
        try:
            if not FRAGMENT_NAME.match(path.name):
                reasons.append(BAD_NAME)
            text = _read(path)
        except Refusal as refusal:
            reasons.append(str(refusal))
            continue
        if any(TOP_HEADING.match(line.rstrip()) for line in text.splitlines()):
            reasons.append(DATE_HEADING)
        if prefix_of(text).strip():
            reasons.append(PREFIX_TEXT)
        declared = entries_of(text)
        if not declared:
            reasons.append(NO_HEADING)
        for name, body in declared:
            if name not in CLASSES:
                reasons.append(UNKNOWN_HEADING)
            if not body.strip():
                reasons.append(EMPTY_BODY)
    return reasons


# Dates and order, from git


def _git(root: Path, *args: str) -> str:
    """One git command, as an argument list, with both streams taken.

    Neither stream is ever re-emitted: git repeats paths and refs back
    in its diagnostics, and this script's whole output contract is
    that repository-derived text does not reach the log through it.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        raise Refusal(GIT_FAILED) from None
    if done.returncode != 0:
        raise Refusal(GIT_FAILED)
    return done.stdout


def _first_parent(root: Path) -> dict[str, int]:
    """Every commit on first-parent history, newest first, by position.

    The position is the total order the fold needs: a fragment
    introduced earlier folds before one introduced later, and the
    filename breaks the tie for two fragments one commit brought in,
    since a git tree encodes no order between the files of one commit.
    """
    listed = _git(root, "rev-list", "--first-parent", "HEAD").split()
    return {sha: index for index, sha in enumerate(listed)}


def _roots(root: Path) -> set[str]:
    """The commits that have no parent in the available history.

    In a shallow clone the graft boundary is one of these and appears
    to add every file in the tree, so a fragment dated from it would
    be dated from a truncation rather than from a merge.
    """
    return set(_git(root, "rev-list", "--max-parents=0", "HEAD").split())


def _is_shallow(root: Path) -> bool:
    return _git(root, "rev-parse", "--is-shallow-repository").strip() == "true"


def introduction(
    root: Path, path: Path, history: dict[str, int], truncated: bool
) -> tuple[str, int]:
    """The date one fragment folds into, and its place in merge order.

    The introduction commit is the NEWEST first-parent commit that
    added the file, and the date is its committer date in its own
    recorded offset. Newest, because a fold deletes the fragments it
    reads, so a path this repository has folded before can validly be
    used again: `467-a-thing.md` may name two different changes a
    month apart. What the fold has to date is the file standing in the
    tree now, and that is the most recent addition. Reading the oldest
    filed the second entry under the first one's day, a section it did
    not land on and where nobody would look for it.

    A fragment whose introduction cannot be found in the available
    history is refused rather than dated from today: a fold that
    guessed would put an entry under a day nothing landed on, and the
    guess would be invisible.
    """
    relative = path.relative_to(root).as_posix()
    listed = _git(
        root,
        "log",
        "--first-parent",
        "--diff-filter=A",
        "--format=%H %cI",
        "--",
        relative,
    ).splitlines()
    if not listed:
        raise Refusal(NO_INTRODUCTION)
    sha, _, stamp = listed[0].partition(" ")
    if sha not in history:
        raise Refusal(NO_INTRODUCTION)
    if truncated and sha in _roots(root):
        raise Refusal(NO_INTRODUCTION)
    day = stamp[:10]
    if not DATE.match(day):
        raise Refusal(NO_INTRODUCTION)
    return day, history[sha]


# The changelog, parsed permissively


class Section:
    """One dated section: its heading line and everything under it.

    Held as raw lines so that a section nothing touches reassembles
    byte for byte, which is the post-condition the whole fold is
    checked against.
    """

    def __init__(self, heading: str, body: list[str]) -> None:
        self.heading = heading
        self.body = body
        match = SECTION.match(heading.rstrip("\r\n"))
        title = match.group(1) if match else ""
        self.date = title if DATE.match(title) else None

    def text(self) -> str:
        return self.heading + "".join(self.body)


def parse(text: str) -> tuple[str, list[Section]]:
    """The changelog as its preamble and its dated sections.

    Permissive by design: a `##` heading opens a section whatever it
    says, and nothing below it is read except the `###` headings the
    fold has to place an entry against.
    """
    preamble: list[str] = []
    sections: list[Section] = []
    for line in text.splitlines(keepends=True):
        if SECTION.match(line.rstrip("\r\n")):
            sections.append(Section(line, []))
        elif sections:
            sections[-1].body.append(line)
        else:
            preamble.append(line)
    return "".join(preamble), sections


def _headings(body: list[str]) -> list[tuple[int, str]]:
    """Every `###` heading in one section body, as (index, class)."""
    found = []
    for index, line in enumerate(body):
        match = ENTRY_HEADING.match(line.rstrip("\r\n"))
        if match is not None:
            found.append((index, match.group(1)))
    return found


def _created(date: str, entries: dict[str, list[str]], nl: str) -> Section:
    """A section this run creates, canonical by construction.

    What this writes (the dated heading, the class headings, the blank
    lines between them) is in the changelog's own ending, `nl`. What it
    places between them is each entry exactly as the fragment held it,
    appended whole rather than rebuilt line by line, because rebuilding
    is where a line ending gets replaced by the one the code happened
    to be written with.
    """
    body: list[str] = [nl]
    for name in CLASSES:
        if name not in entries:
            continue
        body.append(f"### {name}{nl}")
        body.append(nl)
        for position, entry in enumerate(entries[name]):
            if position:
                body.append(nl)
            body.append(entry)
        body.append(nl)
    return Section(f"## {date}{nl}", body)


def _append(section: Section, name: str, entries: list[str], nl: str) -> None:
    """One class's entries appended into a section that already stands.

    Under the LAST heading matching the class, after its last entry,
    because a section may legitimately carry two headings of one class
    and the later one is where a reader looks. A class the section has
    no heading for gets one, placed in Keep a Changelog order relative
    to the headings that are there, whatever else the section holds.
    """
    block: list[str] = []
    for position, entry in enumerate(entries):
        if position:
            block.append(nl)
        block.append(entry)

    headings = _headings(section.body)
    matching = [index for index, heading in headings if heading == name]
    if matching:
        start = matching[-1]
        following = [index for index, _ in headings if index > start]
        end = following[0] if following else len(section.body)
        while end > start + 1 and not section.body[end - 1].strip():
            end -= 1
        section.body[end:end] = [nl, *block]
        return

    order = CLASSES.index(name)
    after = [
        index
        for index, heading in headings
        if heading in CLASSES and CLASSES.index(heading) > order
    ]
    if after:
        at = after[0]
        section.body[at:at] = [f"### {name}{nl}", nl, *block, nl]
        return
    end = len(section.body)
    while end > 0 and not section.body[end - 1].strip():
        end -= 1
    section.body[end:end] = [nl, f"### {name}{nl}", nl, *block]


def assemble(
    text: str, folding: dict[str, dict[str, list[str]]]
) -> tuple[str, set[str], set[str]]:
    """The changelog with every fragment's entries in place.

    Returns the new text, the dates whose sections were created, and
    the dates whose sections were appended into. Dates are handled
    oldest first so the result does not depend on the order the
    fragments happened to be read in.
    """
    nl = _newline(text)
    preamble, sections = parse(text)
    created: set[str] = set()
    appended: set[str] = set()
    for date in sorted(folding):
        entries = folding[date]
        standing = next((s for s in sections if s.date == date), None)
        if standing is None:
            section = _created(date, entries, nl)
            at = next(
                (
                    index
                    for index, other in enumerate(sections)
                    if other.date is not None and other.date < date
                ),
                len(sections),
            )
            # A new section needs a blank line in front of its heading,
            # and the only place the file may not already have one is
            # after its last section. Topping that up is a change to a
            # standing section, so the date is recorded as touched
            # rather than quietly excused from the byte-identity
            # post-condition.
            if at > 0 and sections[at - 1].body and sections[at - 1].body[-1].strip():
                sections[at - 1].body.append(nl)
                appended.add(sections[at - 1].date or "")
            sections.insert(at, section)
            created.add(date)
            continue
        for name in CLASSES:
            if name in entries:
                _append(standing, name, entries[name], nl)
        appended.add(date)
    return preamble + "".join(s.text() for s in sections), created, appended


# What the fold refuses to write

CONFLICT = ("<<<<<<<", ">>>>>>>", "|||||||")


def _has_conflict_marker(text: str) -> bool:
    for line in text.splitlines():
        if line.startswith(CONFLICT) or line.rstrip() == "=======":
            return True
    return False


def post_conditions(
    before: str,
    after: str,
    folding: dict[str, dict[str, list[str]]],
    created: set[str],
    appended: set[str],
) -> list[str]:
    """Everything that must hold before a byte is written."""
    reasons: list[str] = []
    for entries in folding.values():
        for group in entries.values():
            for entry in group:
                if after.count(entry) != 1:
                    reasons.append(NOT_ONCE)
    if _has_conflict_marker(after):
        reasons.append(CONFLICT_MARKER)

    old_preamble, old_sections = parse(before)
    new_preamble, new_sections = parse(after)
    touched = created | appended
    old_kept = [(s.date, s.text()) for s in old_sections if s.date not in touched]
    new_kept = [(s.date, s.text()) for s in new_sections if s.date not in touched]
    if old_preamble != new_preamble or old_kept != new_kept:
        reasons.append(OUTSIDE_CHANGED)

    standing = {s.date: s for s in old_sections}
    for section in new_sections:
        if section.date in created:
            names = [name for _, name in _headings(section.body)]
            wanted = [name for name in CLASSES if name in folding[section.date]]
            if names != wanted:
                reasons.append(MALFORMED_SECTION)
        elif section.date in appended and section.date in standing:
            was = [name for _, name in _headings(standing[section.date].body)]
            now = [name for _, name in _headings(section.body)]
            if not _keeps(was, now):
                reasons.append(MALFORMED_SECTION)
            elif any(name not in CLASSES for name in now if name not in was):
                reasons.append(MALFORMED_SECTION)
    return reasons


def _keeps(was: list[str], now: list[str]) -> bool:
    """Whether the standing headings are still there, in order.

    A subsequence test rather than a prefix test: an inserted heading
    may land anywhere among them, and what the section is held to is
    that nothing it had was removed or reordered.
    """
    remaining = iter(now)
    return all(any(name == seen for seen in remaining) for name in was)


# The verbs


def fold(root: Path) -> int:
    paths = fragment_paths(root)
    if not paths:
        print("no fragments to fold")
        return 0
    reasons = validate(root)
    if reasons:
        return _fail(reasons)

    # The other path the fold owns, held to being what it claims for
    # the same reason the directory is: a committed symlink here would
    # have the fold read one file and, through the replacement below,
    # decide the fate of another.
    changelog = root / CHANGELOG
    if changelog.is_symlink() or not changelog.is_file():
        return _fail([UNREADABLE_CHANGELOG])
    try:
        before = text_of(changelog)
    except (OSError, UnicodeDecodeError):
        return _fail([UNREADABLE_CHANGELOG])

    history = _first_parent(root)
    truncated = _is_shallow(root)
    ordered = []
    for path in paths:
        date, position = introduction(root, path, history, truncated)
        ordered.append((-position, path.name, date, path))
    ordered.sort(key=lambda row: (row[0], row[1]))

    sources = {path: _read(path) for path in paths}
    folding: dict[str, dict[str, list[str]]] = {}
    for _, _, date, path in ordered:
        for name, entry in entries_of(sources[path]):
            folding.setdefault(date, {}).setdefault(name, []).append(entry)

    after, created, appended = assemble(before, folding)
    reasons = post_conditions(before, after, folding, created, appended)
    if reasons:
        return _fail(reasons)

    reasons = _mutate(changelog, after, sources)
    if reasons:
        return _fail(reasons)
    print(f"folded {len(paths)} fragments into {len(created) + len(appended)} sections")
    return 0


def _stage(changelog: Path, after: str) -> Path:
    """The new changelog, written beside the old one under a name
    nothing can guess.

    Three properties, and each closes a door. Exclusive creation, so an
    existing path at that name is an error rather than a target: the
    previous spelling was a predictable `CHANGELOG.md.fold-tmp` opened
    with an ordinary write, so a committed symlink there had the fold
    write the whole new changelog through the link into another file
    and then move the link itself over `CHANGELOG.md`, ruining two
    paths that both sit inside what the fold workflow stages. An
    unguessable name, so nothing can be planted at it. And the same
    directory, so the replacement below is a rename rather than a copy.

    The staged file takes the changelog's own mode, because `mkstemp`
    creates a private one and the replacement would otherwise hand the
    repository a 0600 changelog.
    """
    handle, name = tempfile.mkstemp(
        dir=changelog.parent, prefix=".changelog-fold-", suffix=".tmp"
    )
    staged = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as out:
            out.write(after)
        os.chmod(staged, stat.S_IMODE(changelog.stat().st_mode))
    except OSError:
        _discard(staged)
        raise
    return staged


def _discard(path: Path) -> None:
    """Remove a staged file, without letting the removal become the
    failure being reported."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _mutate(changelog: Path, after: str, sources: dict[Path, str]) -> list[str]:
    """The only part of a fold that touches the disk, ordered so that
    no failure can leave the tree half folded.

    The staged changelog is written first, before anything is removed,
    so the step most likely to fail fails while the tree is still
    untouched. The fragments go next. The changelog is changed last and
    only by a rename, which either happens or does not, so there is no
    state in which the file is half a fold and `_restore` never has a
    changelog to put back, only fragments.

    And the fragments can be put back, which is an argument rather than
    a hope: they are written into the directory whose own removals just
    proved it writable, under the same permission bit.
    """
    try:
        staged = _stage(changelog, after)
    except OSError:
        return [CANNOT_WRITE]

    removed: list[Path] = []
    modes: dict[Path, int] = {}
    try:
        for path in sources:
            modes[path] = stat.S_IMODE(path.stat().st_mode)
            path.unlink()
            removed.append(path)
    except OSError:
        _discard(staged)
        return _restore(removed, sources, modes, CANNOT_REMOVE)

    try:
        os.replace(staged, changelog)
    except OSError:
        _discard(staged)
        return _restore(removed, sources, modes, CANNOT_WRITE)
    return []


def _restore(
    removed: list[Path],
    sources: dict[Path, str],
    modes: dict[Path, int],
    reason: str,
) -> list[str]:
    """Put back the fragments a failed mutation had already taken.

    Content and mode, because the tree a fold promises to leave behind
    is the tree it found and not a copy of its bytes. A fragment is a
    file with permissions; recreating it with whatever the process
    default happens to be would satisfy every content assertion while
    quietly changing what is on disk, and a mode is exactly the kind of
    thing nobody notices being lost.

    A restore that itself fails is reported as its own refusal, because
    a tree left half folded is a different thing from a fold that
    declined to start and must not be described as one.
    """
    try:
        for path in removed:
            with path.open("w", encoding="utf-8", newline="") as out:
                out.write(sources[path])
            os.chmod(path, modes[path])
    except OSError:
        return [reason, NOT_RESTORED]
    return [reason]


def check(root: Path) -> int:
    reasons = validate(root)
    if reasons:
        return _fail(reasons)
    print(f"checked {len(fragment_paths(root))} fragments, 0 failures")
    return 0


def guard(changed: list[str], body: str) -> int:
    if CHANGELOG not in changed:
        print("the changed files do not touch CHANGELOG.md")
        return 0
    if ESCAPE_PHRASE in body:
        print("the pull request body declares a correction of history")
        return 0
    print(
        "this pull request changes CHANGELOG.md, which a branch may not do. "
        "Write changelog.d/<issue>-<slug>.md instead; a genuine correction "
        f"of history says '{ESCAPE_PHRASE}' in the pull request body.",
        file=sys.stderr,
    )
    return 1


USAGE = "usage: fold_changelog.py {fold|check} <repo-root> | fold_changelog.py guard"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(USAGE, file=sys.stderr)
        return 2
    verb = argv[1]
    if verb == "guard":
        if len(argv) != 2:
            print(USAGE, file=sys.stderr)
            return 2
        changed = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
        return guard(changed, os.environ.get(BODY_VARIABLE) or "")
    if verb not in ("fold", "check") or len(argv) != 3:
        print(USAGE, file=sys.stderr)
        return 2
    root = Path(argv[2])
    if not root.is_dir():
        print("the given repo-root is not a directory", file=sys.stderr)
        return 2
    root = root.resolve()
    try:
        return fold(root) if verb == "fold" else check(root)
    except Refusal as refusal:
        return _fail([str(refusal)])
    except OSError:
        # The backstop, and it exists because the thing it catches is
        # the thing this script must never do: an unhandled OSError
        # prints a traceback, and a traceback carries repository paths
        # into a public CI log. Every filesystem call above is guarded
        # by name; this catches the one somebody adds later without
        # remembering to.
        return _fail([FILESYSTEM])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
