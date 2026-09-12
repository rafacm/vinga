"""The changelog fold's contract, exercised as a subprocess.

The script lives at the repository root (`scripts/fold_changelog.py`)
and runs in two workflows: the fold on `main`, whose commit lands
without a CI run of its own, and the two pull-request steps in the
docs workflow. Both are public CI log surfaces, so the no-leak
standard applies to it exactly as it applies to
`scripts/check_doc_links.py`, and these tests run the real script the
way the workflows do and read both streams whole.

The date derivation is driven through real git histories in temporary
repositories rather than mocked, because what is being checked is what
git answers: the committer date of the commit that introduced a
fragment, in that commit's own recorded offset, and the first-parent
position that orders two fragments.
"""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "fold_changelog.py"

# Credential-shaped, and never a value that exists anywhere real.
SENTINEL = "sk-SENTINEL8f3a1b2c4d5e6f70"

# A changelog with two settled sections, the shape the repository's own
# file has: newest first, entries already folded under their classes.
BASE = (
    "# Changelog\n"
    "\n"
    "All notable changes to this project will be documented in this file.\n"
    "\n"
    "## 2026-09-11\n"
    "\n"
    "### Added\n"
    "\n"
    "- **The standing entry**, folded on the day it landed.\n"
    "\n"
    "## 2026-09-06\n"
    "\n"
    "### Added\n"
    "\n"
    "- **An older entry**, folded long ago.\n"
)

# And the shapes settled history actually carries, which no canonical
# rule describes: a section ordering Fixed before Changed (2026-09-10
# in the repository) and a section with two Added headings (2026-09-06).
LEGACY = (
    "# Changelog\n"
    "\n"
    "All notable changes to this project will be documented in this file.\n"
    "\n"
    "## 2026-09-10\n"
    "\n"
    "### Added\n"
    "\n"
    "- **The first added entry.**\n"
    "\n"
    "### Fixed\n"
    "\n"
    "- **A fix, written above the changes.**\n"
    "\n"
    "### Changed\n"
    "\n"
    "- **A change, written below the fixes.**\n"
    "\n"
    "## 2026-09-06\n"
    "\n"
    "### Added\n"
    "\n"
    "- **The first of two Added headings.**\n"
    "\n"
    "### Changed\n"
    "\n"
    "- **A change between them.**\n"
    "\n"
    "### Added\n"
    "\n"
    "- **The second of two Added headings.**\n"
)


def run(*args: str, stdin: str = "", body: str | None = None) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment.pop("PR_BODY", None)
    if body is not None:
        environment["PR_BODY"] = body
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )


def git(root: Path, *args: str, when: str | None = None) -> None:
    environment = dict(os.environ)
    if when is not None:
        environment["GIT_COMMITTER_DATE"] = when
        environment["GIT_AUTHOR_DATE"] = when
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )


def repo(tmp_path: Path, changelog: str = BASE, name: str = "repo") -> Path:
    """A checkout with a changelog, a fragment directory and one commit."""
    root = tmp_path / name
    (root / "changelog.d").mkdir(parents=True)
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    (root / "changelog.d" / "README.md").write_text(
        "# Changelog fragments\n\nThe contract, not a fragment.\n", encoding="utf-8"
    )
    git(root.parent, "init", "-q", "-b", "main", str(root))
    git(root, "config", "user.email", "tester@example.invalid")
    git(root, "config", "user.name", "Tester")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "The settled changelog", when="2026-09-11T09:00:00+00:00")
    return root


def write(root: Path, name: str, text: str) -> None:
    (root / "changelog.d" / name).write_text(text, encoding="utf-8")


def land(root: Path, when: str = "2026-09-12T10:00:00+00:00") -> None:
    """Commit whatever is in the tree, as the merge that brought it in."""
    git(root, "add", "-A")
    git(root, "commit", "-qm", "A milestone", when=when)


def fragment(root: Path, name: str, text: str, when: str = "2026-09-12T10:00:00+00:00") -> None:
    write(root, name, text)
    land(root, when)


def section(text: str, date: str) -> str:
    """One dated section of a changelog, heading included."""
    after = text.split(f"## {date}\n", 1)[1]
    return after.split("\n## ", 1)[0]


def names(root: Path) -> list[str]:
    return sorted(path.name for path in (root / "changelog.d").iterdir())


# Folding


def test_a_fragment_folds_into_the_dated_section_that_already_exists(
    tmp_path: Path,
) -> None:
    """The ordinary case: the day already has a section and a class
    heading, and the entry lands after the entry already under it."""
    root = repo(tmp_path)
    fragment(
        root,
        "467-a-thing.md",
        "### Added\n\n- **A thing**, added by a milestone.\n",
        when="2026-09-11T23:30:00+00:00",
    )

    done = run("fold", str(root))

    assert done.returncode == 0, done.stderr
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    day = section(text, "2026-09-11")
    assert day.index("**The standing entry**") < day.index("**A thing**, added")
    assert names(root) == ["README.md"]


def test_a_new_day_creates_its_section_in_the_commits_own_offset(
    tmp_path: Path,
) -> None:
    """The date is the introduction commit's committer date rendered in
    the offset the commit records, which is what makes a merge just
    before midnight and a fold just after agree.

    Half past midnight at +02:00 is the twelfth where it was committed
    and still the eleventh in UTC, so a fold reading UTC would file
    this entry under the wrong day.
    """
    root = repo(tmp_path)
    fragment(
        root,
        "467-past-midnight.md",
        "### Added\n\n- **A thing that landed past midnight.**\n",
        when="2026-09-12T00:30:00+02:00",
    )

    done = run("fold", str(root))

    assert done.returncode == 0, done.stderr
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 2026-09-12\n" in text
    assert text.index("## 2026-09-12") < text.index("## 2026-09-11")
    assert section(text, "2026-09-12") == (
        "\n### Added\n\n- **A thing that landed past midnight.**\n"
    )


def test_a_reused_filename_is_dated_from_the_file_that_is_there(
    tmp_path: Path,
) -> None:
    """Folding deletes fragments, so a later change may reuse a path
    the repository has folded before, by design or by accident.

    The date has to come from the commit that introduced the file
    standing in the tree now, not from the first time that name ever
    existed. Reading the oldest addition filed the second entry under
    the first one's day, which is a section it did not land on.
    """
    root = repo(tmp_path)
    fragment(
        root,
        "467-reused.md",
        "### Added\n\n- **The first incarnation.**\n",
        when="2026-09-11T10:00:00+00:00",
    )
    assert run("fold", str(root)).returncode == 0
    land(root, when="2026-09-11T10:30:00+00:00")

    fragment(
        root,
        "467-reused.md",
        "### Added\n\n- **The second incarnation.**\n",
        when="2026-09-12T10:00:00+00:00",
    )

    done = run("fold", str(root))

    assert done.returncode == 0, done.stderr
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "**The second incarnation.**" in section(text, "2026-09-12")
    assert "**The first incarnation.**" in section(text, "2026-09-11")
    assert "**The second incarnation.**" not in section(text, "2026-09-11")


def test_a_created_section_lands_between_the_days_around_it(tmp_path: Path) -> None:
    """Date position, not file position: a day older than the newest
    section and newer than the oldest goes between them."""
    root = repo(tmp_path)
    fragment(
        root,
        "467-an-older-day.md",
        "### Fixed\n\n- **A fix from the eighth.**\n",
        when="2026-09-08T12:00:00+00:00",
    )

    done = run("fold", str(root))

    assert done.returncode == 0, done.stderr
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    dates = [line for line in text.splitlines() if line.startswith("## ")]
    assert dates == ["## 2026-09-11", "## 2026-09-08", "## 2026-09-06"]


def test_two_fragments_on_one_day_merge_in_keep_a_changelog_order(
    tmp_path: Path,
) -> None:
    """Classes appear in Keep a Changelog order whatever order the
    fragments arrived in, and a class the section has no heading for
    gets one placed by that order."""
    root = repo(tmp_path)
    fragment(
        root,
        "467-a-fix.md",
        "### Fixed\n\n- **A fix.**\n",
        when="2026-09-11T10:00:00+00:00",
    )
    fragment(
        root,
        "467-a-change.md",
        "### Changed\n\n- **A change.**\n",
        when="2026-09-11T11:00:00+00:00",
    )

    done = run("fold", str(root))

    assert done.returncode == 0, done.stderr
    day = section((root / "CHANGELOG.md").read_text(encoding="utf-8"), "2026-09-11")
    assert [line for line in day.splitlines() if line.startswith("### ")] == [
        "### Added",
        "### Changed",
        "### Fixed",
    ]


def test_entries_of_one_class_follow_merge_order_not_filename_order(
    tmp_path: Path,
) -> None:
    """Merge order is the introduction commit's place in first-parent
    history. The filenames here sort the other way round, so a fold
    ordering by name would read these two backwards."""
    root = repo(tmp_path)
    fragment(
        root,
        "9-merged-first.md",
        "### Added\n\n- **The entry that landed first.**\n",
        when="2026-09-11T10:00:00+00:00",
    )
    fragment(
        root,
        "1-merged-second.md",
        "### Added\n\n- **The entry that landed second.**\n",
        when="2026-09-11T11:00:00+00:00",
    )

    done = run("fold", str(root))

    assert done.returncode == 0, done.stderr
    day = section((root / "CHANGELOG.md").read_text(encoding="utf-8"), "2026-09-11")
    assert day.index("landed first") < day.index("landed second")


def test_two_fragments_from_one_commit_order_by_filename(tmp_path: Path) -> None:
    """The tie-breaker, which is the half a history position cannot
    supply: a git tree encodes no order between the files of one
    commit, so one pull request adding two fragments would otherwise
    fold in whatever order the directory happened to list them in."""
    root = repo(tmp_path)
    write(root, "467-beta.md", "### Added\n\n- **The beta entry.**\n")
    write(root, "467-alpha.md", "### Added\n\n- **The alpha entry.**\n")
    land(root, when="2026-09-11T12:00:00+00:00")

    done = run("fold", str(root))

    assert done.returncode == 0, done.stderr
    day = section((root / "CHANGELOG.md").read_text(encoding="utf-8"), "2026-09-11")
    assert day.index("alpha entry") < day.index("beta entry")


def test_a_multi_class_fragment_splits_into_its_classes(tmp_path: Path) -> None:
    """One file may carry several headings, and each entry goes to its
    own class rather than the file going to one of them."""
    root = repo(tmp_path)
    fragment(
        root,
        "467-three-classes.md",
        "### Security\n\n- **A security note.**\n"
        "\n"
        "### Added\n\n- **An addition.**\n"
        "\n"
        "### Fixed\n\n- **A fix.**\n",
    )

    done = run("fold", str(root))

    assert done.returncode == 0, done.stderr
    day = section((root / "CHANGELOG.md").read_text(encoding="utf-8"), "2026-09-12")
    assert [line for line in day.splitlines() if line.startswith("### ")] == [
        "### Added",
        "### Fixed",
        "### Security",
    ]


# The bytes an entry is written in are the bytes it is folded as: the
# fragment is reviewed in final form on the pull request, and a fold
# that reflowed or renumbered anything would make that review a review
# of something else.
VERBATIM = (
    "- **A deeply formatted entry** (#467, M2), which carries a nested\n"
    "  list and the punctuation that goes with it:\n"
    "\n"
    "  - one item, `with code` and *emphasis*\n"
    "  - another, whose line is long enough that a reflowing fold would "
    "have to break it somewhere\n"
    "\n"
    "  and a closing paragraph after the list.\n"
)


def test_entry_bytes_survive_the_fold_verbatim(tmp_path: Path) -> None:
    """Byte preservation, asserted on the block rather than on a
    sentence of it: blank lines, indentation and long lines all have to
    arrive as they were written."""
    root = repo(tmp_path)
    fragment(root, "467-verbatim.md", f"### Changed\n\n{VERBATIM}")

    done = run("fold", str(root))

    assert done.returncode == 0, done.stderr
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.count(VERBATIM) == 1


def test_crlf_bytes_survive_the_fold_on_both_sides(tmp_path: Path) -> None:
    """Line endings are content, and nothing in this repository forces
    them to be one thing.

    Reading through universal-newline translation turned a CRLF
    fragment into LF on the way in, so the entry was not moved byte for
    byte; and it turned a CRLF changelog into LF on the way in and back
    out, so every untouched section was rewritten while the
    post-condition compared two already-normalized strings and saw
    nothing. Both halves are asserted on bytes here, which is the only
    altitude at which the claim means anything.
    """
    changelog = BASE.replace("\n", "\r\n")
    root = repo(tmp_path, changelog=changelog)
    entry = "- **A thing**, added.\r\n  With a second line.\r\n"
    (root / "changelog.d" / "467-crlf.md").write_bytes(
        f"### Added\r\n\r\n{entry}".encode()
    )
    land(root, when="2026-09-12T10:00:00+00:00")

    done = run("fold", str(root))

    assert done.returncode == 0, done.stderr
    raw = (root / "CHANGELOG.md").read_bytes()
    assert raw.count(entry.encode()) == 1
    assert b"\n" not in raw.replace(b"\r\n", b"")
    boundary = changelog.index("## 2026-09-11")
    assert raw.startswith(changelog[:boundary].encode())
    assert raw.endswith(changelog[boundary:].encode())


def test_a_second_fold_with_no_fragments_is_a_no_op(tmp_path: Path) -> None:
    """Idempotence, which is what lets a queued run that lost the race
    exit green instead of folding half of something twice."""
    root = repo(tmp_path)
    fragment(root, "467-once.md", "### Added\n\n- **Folded once.**\n")

    assert run("fold", str(root)).returncode == 0
    folded = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    again = run("fold", str(root))

    assert again.returncode == 0
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == folded
    assert folded.count("**Folded once.**") == 1


def test_legacy_sections_are_byte_preserved_by_a_fold(tmp_path: Path) -> None:
    """The post-conditions are scoped for a reason: settled history is
    not canonical, and a global heading-order rule would have to reject
    this fixture or rewrite it. Both of these shapes are the
    repository's own, and a fold into a new day leaves every byte of
    them alone."""
    root = repo(tmp_path, changelog=LEGACY)
    fragment(root, "467-a-new-day.md", "### Added\n\n- **A new day's entry.**\n")

    done = run("fold", str(root))

    assert done.returncode == 0, done.stderr
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    boundary = LEGACY.index("## 2026-09-10")
    assert text.startswith(LEGACY[:boundary])
    assert text.endswith(LEGACY[boundary:])


def test_an_entry_appends_under_the_last_heading_of_its_class(
    tmp_path: Path,
) -> None:
    """A section with two headings of one class keeps both, and the
    entry goes under the later one, which is where a reader of that
    section looks for the day's additions."""
    root = repo(tmp_path, changelog=LEGACY)
    fragment(
        root,
        "467-into-the-duplicate.md",
        "### Added\n\n- **The entry folded into a duplicated heading.**\n",
        when="2026-09-06T12:00:00+00:00",
    )

    done = run("fold", str(root))

    assert done.returncode == 0, done.stderr
    day = section((root / "CHANGELOG.md").read_text(encoding="utf-8"), "2026-09-06")
    assert [line for line in day.splitlines() if line.startswith("### ")] == [
        "### Added",
        "### Changed",
        "### Added",
    ]
    assert day.index("second of two Added headings") < day.index("folded into a duplicated")


# Refusals
#
# Each builds a checkout that the fold must refuse, and each plants the
# sentinel where the refusal could leak it: in a fragment body, in a
# fragment filename, or in the path a git failure is about. The two
# tests below run every one of them, so a new refusal family is held to
# writing nothing and to reproducing nothing by construction.


def _unknown_heading(tmp_path: Path) -> Path:
    root = repo(tmp_path)
    fragment(root, "467-unknown.md", f"### Improved\n\n- {SENTINEL} improved.\n")
    return root


def _empty_body(tmp_path: Path) -> Path:
    root = repo(tmp_path)
    fragment(root, "467-empty.md", f"### Added\n\n\n### Fixed\n\n- {SENTINEL} fixed.\n")
    return root


def _date_heading(tmp_path: Path) -> Path:
    root = repo(tmp_path)
    fragment(root, "467-dated.md", f"## 2026-09-12\n\n### Added\n\n- {SENTINEL} added.\n")
    return root


def _duplicate_entry(tmp_path: Path) -> Path:
    root = repo(tmp_path)
    fragment(
        root,
        "467-duplicate.md",
        "### Added\n\n- **The standing entry**, folded on the day it landed.\n",
        when="2026-09-11T20:00:00+00:00",
    )
    return root


def _conflict_marker(tmp_path: Path) -> Path:
    spliced = BASE.replace(
        "### Added\n\n- **The standing entry**",
        "<<<<<<< HEAD\n### Added\n\n- **The standing entry**",
        1,
    )
    root = repo(tmp_path, changelog=spliced)
    fragment(root, "467-into-a-conflict.md", f"### Added\n\n- {SENTINEL} added.\n")
    return root


def _shallow_history(tmp_path: Path) -> Path:
    origin = repo(tmp_path, name="origin")
    fragment(origin, "467-before-the-graft.md", f"### Added\n\n- {SENTINEL} added.\n")
    root = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{origin}", str(root)],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return root


def _bad_filename(tmp_path: Path) -> Path:
    root = repo(tmp_path)
    fragment(root, f"467-{SENTINEL}.md", "### Added\n\n- **A well formed entry.**\n")
    return root


def _symlinked_fragment(tmp_path: Path) -> Path:
    root = repo(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text(f"### Added\n\n- {SENTINEL} added.\n", encoding="utf-8")
    (root / "changelog.d" / "467-a-link.md").symlink_to(outside)
    land(root)
    return root


def _text_before_the_first_heading(tmp_path: Path) -> Path:
    root = repo(tmp_path)
    fragment(
        root,
        "467-a-preamble.md",
        f"- {SENTINEL}, an entry written without its heading.\n"
        "\n"
        "### Added\n"
        "\n"
        "- **The entry that does have one.**\n",
    )
    return root


def _dotted_filename(tmp_path: Path) -> Path:
    root = repo(tmp_path)
    fragment(root, f".467-{SENTINEL}.md", "### Added\n\n- **A well formed entry.**\n")
    return root


def _not_a_repository(tmp_path: Path) -> Path:
    root = tmp_path / f"tree-{SENTINEL}"
    (root / "changelog.d").mkdir(parents=True)
    (root / "CHANGELOG.md").write_text(BASE, encoding="utf-8")
    (root / "changelog.d" / "467-no-history.md").write_text(
        "### Added\n\n- **A well formed entry.**\n", encoding="utf-8"
    )
    return root


REFUSALS = [
    ("unknown heading", _unknown_heading, "outside the Keep a Changelog six"),
    ("empty body", _empty_body, "no entry text"),
    ("date heading", _date_heading, "date or top-level heading"),
    (
        "text before the first heading",
        _text_before_the_first_heading,
        "before its first class heading",
    ),
    ("duplicate entry", _duplicate_entry, "exactly once"),
    ("conflict marker", _conflict_marker, "conflict marker"),
    ("shallow history", _shallow_history, "available history"),
    ("bad filename", _bad_filename, "<issue>-<slug>.md"),
    ("dotted filename", _dotted_filename, "<issue>-<slug>.md"),
    ("symlinked fragment", _symlinked_fragment, "not a regular file"),
    ("git failure", _not_a_repository, "git command failed"),
]


@pytest.mark.parametrize(
    ("build", "expected"),
    [(build, expected) for _, build, expected in REFUSALS],
    ids=[what for what, _, _ in REFUSALS],
)
def test_a_refusal_writes_nothing(tmp_path: Path, build, expected: str) -> None:
    """Exit 1 and an untouched tree, for every family.

    A fold that refused after writing would be worse than one that
    folded wrongly: the changelog would be half a state nobody meant
    and the fragments would be gone.
    """
    root = build(tmp_path)
    before = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    standing = names(root)

    done = run("fold", str(root))

    assert done.returncode == 1
    assert expected in done.stderr
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == before
    assert names(root) == standing


@pytest.mark.parametrize(
    "build",
    [build for _, build, _ in REFUSALS],
    ids=[what for what, _, _ in REFUSALS],
)
def test_a_refusal_reproduces_no_repository_text(tmp_path: Path, build) -> None:
    """The no-leak contract, held over both streams.

    A fragment body, a fragment filename and git's own diagnostics are
    repository-derived text landing in a public CI log. The sentinel is
    planted in whichever of the three the family can carry it in, and
    the refusal has to name the kind of failure without reproducing it.
    """
    root = build(tmp_path)

    done = run("fold", str(root))

    assert done.returncode == 1
    for stream in (done.stdout, done.stderr):
        assert SENTINEL not in stream
        assert "Traceback" not in stream


# Filesystem failures
#
# Every one of these is an `OSError` on a path the script owns, and
# `main` used to catch only `Refusal`, so each printed a traceback
# carrying repository-derived paths into a public CI log. They are also
# where a half-done fold could live, which is why the mutation order is
# what it is: the fragments are removed first, into a directory the
# removals themselves prove writable, and the changelog is replaced
# atomically afterwards. A failure at either step leaves the tree as it
# was, restored from text already in memory when it has to be.

not_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="permission bits do not constrain root",
)


def _as_a_regular_file(root: Path) -> None:
    shutil.rmtree(root / "changelog.d")
    (root / "changelog.d").write_text("not a directory at all\n", encoding="utf-8")


def _as_a_symlink(root: Path) -> None:
    elsewhere = root.parent / "somewhere-else"
    elsewhere.mkdir()
    (elsewhere / "467-smuggled.md").write_text(
        "### Added\n\n- **An entry from outside the directory.**\n", encoding="utf-8"
    )
    shutil.rmtree(root / "changelog.d")
    (root / "changelog.d").symlink_to(elsewhere, target_is_directory=True)


@pytest.mark.parametrize("verb", ["check", "fold"])
@pytest.mark.parametrize(
    "replace",
    [_as_a_regular_file, _as_a_symlink],
    ids=["a regular file", "a symlink"],
)
def test_a_changelog_d_that_is_not_a_directory_is_a_refusal(
    tmp_path: Path, replace, verb: str
) -> None:
    """The directory itself is part of the contract.

    An empty listing used to mean the same thing as a healthy empty
    directory, so a pull request replacing `changelog.d` with a regular
    file or a symlink passed `check` with zero fragments and left
    `main` with the whole mechanism switched off, every run green. It
    is the dotfile hole one level up, and the answer is the same: a
    path that is not what it claims is a refusal, not a silence.
    """
    root = repo(tmp_path)
    replace(root)

    done = run(verb, str(root))

    assert done.returncode == 1
    assert "not a directory" in done.stderr
    assert "Traceback" not in done.stderr


def test_a_planted_symlink_at_the_old_temp_path_corrupts_nothing(
    tmp_path: Path,
) -> None:
    """The staging file used to have a name anybody could predict, and
    it was opened with a write that follows a symlink.

    So a pull request could commit `CHANGELOG.md.fold-tmp` pointing at
    another file in the tree, and the fold would write the whole new
    changelog through the link into that file and then move the link
    itself over `CHANGELOG.md`. Both paths it ruins are inside the two
    the fold workflow stages, so the porcelain guard would have watched
    the bot commit the wreckage. The staging file is created
    exclusively under a name nothing can guess now, so a planted link
    is just a stray file.
    """
    root = repo(tmp_path)
    readme = root / "changelog.d" / "README.md"
    standing = readme.read_text(encoding="utf-8")
    (root / "CHANGELOG.md.fold-tmp").symlink_to(readme)
    fragment(root, "467-a-thing.md", "### Added\n\n- **A thing.**\n")

    done = run("fold", str(root))

    assert readme.read_text(encoding="utf-8") == standing
    assert not (root / "CHANGELOG.md").is_symlink()
    assert "**A thing.**" in (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Traceback" not in done.stderr


def test_a_symlinked_changelog_is_a_refusal(tmp_path: Path) -> None:
    """The other path the fold owns, held to the same standard as the
    directory: a committed symlink here would have the fold read one
    file and decide the fate of another."""
    root = repo(tmp_path)
    fragment(root, "467-a-thing.md", "### Added\n\n- **A thing.**\n")
    elsewhere = root / "somewhere.md"
    elsewhere.write_text("# Not the changelog\n", encoding="utf-8")
    (root / "CHANGELOG.md").unlink()
    (root / "CHANGELOG.md").symlink_to(elsewhere)

    done = run("fold", str(root))

    assert done.returncode == 1
    assert "a symlink" in done.stderr
    assert elsewhere.read_text(encoding="utf-8") == "# Not the changelog\n"


@not_root
def test_an_unreadable_fragment_directory_is_a_refusal(tmp_path: Path) -> None:
    """Enumeration is a filesystem call like any other, and it used to
    be the one nothing guarded: `iterdir` raised straight through."""
    root = repo(tmp_path)
    fragment(root, "467-unlistable.md", f"### Added\n\n- {SENTINEL} added.\n")
    before = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    (root / "changelog.d").chmod(0o000)
    try:
        done = run("fold", str(root))
    finally:
        (root / "changelog.d").chmod(0o755)

    assert done.returncode == 1
    assert "cannot be listed" in done.stderr
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == before
    for stream in (done.stdout, done.stderr):
        assert SENTINEL not in stream
        assert "Traceback" not in stream


@not_root
def test_a_fragment_that_cannot_be_removed_leaves_the_tree_alone(
    tmp_path: Path,
) -> None:
    """The removals come first, so a directory that refuses them stops
    the fold before the changelog has been touched at all."""
    root = repo(tmp_path)
    fragment(root, "467-unremovable.md", f"### Added\n\n- {SENTINEL} added.\n")
    before = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    standing = (root / "changelog.d" / "467-unremovable.md").read_text(encoding="utf-8")
    (root / "changelog.d").chmod(0o555)
    try:
        done = run("fold", str(root))
    finally:
        (root / "changelog.d").chmod(0o755)

    assert done.returncode == 1
    assert "could not be removed" in done.stderr
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == before
    assert (root / "changelog.d" / "467-unremovable.md").read_text(encoding="utf-8") == standing
    for stream in (done.stdout, done.stderr):
        assert SENTINEL not in stream
        assert "Traceback" not in stream


@not_root
def test_a_changelog_that_cannot_be_written_leaves_the_tree_as_it_was(
    tmp_path: Path,
) -> None:
    """The tree as it was means the tree as it was, mode included.

    A fragment is a file with a mode, and the recovery sentence is a
    claim about the tree and not only about its bytes. So the fragment
    here is executable, and the assertion is on the mode as well as on
    the content: a recovery that recreated the file with whatever the
    process default happened to be would have satisfied every other
    check in this module while quietly changing the tree.
    """
    root = repo(tmp_path)
    body = f"### Added\n\n- {SENTINEL} added.\n"
    fragment(root, "467-unwritable.md", body)
    standing = root / "changelog.d" / "467-unwritable.md"
    standing.chmod(0o755)
    before = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    root.chmod(0o555)
    try:
        done = run("fold", str(root))
    finally:
        root.chmod(0o755)

    assert done.returncode == 1
    assert "could not be written" in done.stderr
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == before
    assert standing.read_text(encoding="utf-8") == body
    assert standing.stat().st_mode & 0o777 == 0o755
    assert sorted(path.name for path in root.iterdir()) == [
        ".git",
        "CHANGELOG.md",
        "changelog.d",
    ]
    for stream in (done.stdout, done.stderr):
        assert SENTINEL not in stream
        assert "Traceback" not in stream


# check


def test_check_passes_a_well_formed_fragment_without_writing(tmp_path: Path) -> None:
    """The pull-request half, which needs no git history: a fragment is
    held to its shape before it can reach main."""
    root = repo(tmp_path)
    write(root, "467-well-formed.md", "### Added\n\n- **A well formed entry.**\n")
    before = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    done = run("check", str(root))

    assert done.returncode == 0, done.stderr
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == before
    assert names(root) == ["467-well-formed.md", "README.md"]


def test_check_refuses_text_before_a_fragments_first_heading(
    tmp_path: Path,
) -> None:
    """The other silence, and the same shape as the dotfile one.

    The parser read a fragment from its first `###` heading onward and
    ignored everything above it, so an entry written without its
    heading, or an introductory paragraph somebody added, passed
    `check` and then vanished during the fold. A fragment is accounted
    for whole now: nonblank text before the first class heading is a
    refusal, so the writer is told rather than the text discarded.
    """
    root = repo(tmp_path)
    write(
        root,
        "467-a-stray-line.md",
        "A note to the reviewer.\n\n### Added\n\n- **The entry.**\n",
    )

    done = run("check", str(root))

    assert done.returncode == 1
    assert "before its first class heading" in done.stderr


def test_check_refuses_a_fragment_whose_name_begins_with_a_dot(
    tmp_path: Path,
) -> None:
    """The silent hole a dotfile exclusion opened.

    A tracked `changelog.d/.467-entry.md` was skipped before its name
    was ever checked, so `check` reported zero failures on the pull
    request and the fold afterwards reported nothing to fold and exited
    green, leaving the claimed entry out of the changelog with no run
    going red anywhere. That is the dropped entry this whole mechanism
    exists to prevent, arriving through another door. Only the README
    is excluded now; everything else in the directory is a fragment and
    is held to the name.
    """
    root = repo(tmp_path)
    write(root, ".467-hidden.md", "### Added\n\n- **An entry nobody would fold.**\n")

    done = run("check", str(root))

    assert done.returncode == 1
    assert "<issue>-<slug>.md" in done.stderr


def test_check_refuses_a_malformed_fragment(tmp_path: Path) -> None:
    """And the half a passing assertion cannot show."""
    root = repo(tmp_path)
    write(root, "467-malformed.md", f"### Improved\n\n- {SENTINEL} improved.\n")

    done = run("check", str(root))

    assert done.returncode == 1
    assert "outside the Keep a Changelog six" in done.stderr
    assert SENTINEL not in done.stdout + done.stderr


def _script_module():
    """The script imported as a module.

    Every other case here drives the real command, which is the right
    altitude for a tool whose output contract is about what a CI log
    sees. This one cannot: the failure it covers is a race between two
    filesystem calls, and there is no way to lose that race on purpose
    from outside the process. So the module is imported and the one
    call that can raise is driven directly, and the streams are still
    read whole.
    """
    spec = importlib.util.spec_from_file_location("fold_changelog", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_root_that_stops_resolving_says_one_fixed_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Resolving a path is a filesystem walk, not a string operation.

    A directory that answered `is_dir` can be a symlink loop by the
    time it is walked, and the walk then raises rather than answering.
    Raising from outside the fixed-diagnostic handler printed a library
    traceback carrying the path somebody typed, and the contract is
    that no input value reaches the log through this script, the
    rejected ones included.
    """
    root = repo(tmp_path)
    module = _script_module()

    def a_loop(self: Path, *args: object, **kwargs: object) -> Path:
        raise RuntimeError(f"Symlink loop from {self}")

    monkeypatch.setattr(module.Path, "resolve", a_loop)
    code = module.main(["fold_changelog.py", "fold", str(root)])
    monkeypatch.undo()

    printed = capsys.readouterr()
    assert code == 1
    assert printed.err.strip() == f"{module.FILESYSTEM} (1)"
    for stream in (printed.out, printed.err):
        assert str(root) not in stream
        assert "Symlink loop" not in stream
        assert "Traceback" not in stream


def test_a_root_that_is_a_symlink_loop_names_no_path(tmp_path: Path) -> None:
    """And the same shape when the loop is there before the run rather
    than arriving during it, which is the half a real filesystem can
    reach: `is_dir` answers no and the refusal quotes nothing."""
    loop = tmp_path / "loop"
    other = tmp_path / "other"
    loop.symlink_to(other)
    other.symlink_to(loop)

    done = run("fold", str(loop))

    assert done.returncode == 2
    assert done.stdout == ""
    assert len(done.stderr.strip().splitlines()) == 1
    assert str(loop) not in done.stderr
    assert "Traceback" not in done.stderr


def test_a_bad_invocation_is_a_sentence_and_exit_two() -> None:
    """Argparse repeats what was typed, which is how a secret typed as
    an argument reaches a public log. This parser answers in its own
    words."""
    for done in (run(), run("frobnicate"), run("fold"), run("fold", "/nonexistent-root")):
        assert done.returncode == 2
        assert done.stdout == ""
        assert len(done.stderr.strip().splitlines()) == 1
        assert "Traceback" not in done.stderr


# guard

FILES = ["README.md", "vinga-server/src/vinga_server/config/cli.py"]


def test_guard_passes_a_pull_request_that_leaves_the_changelog_alone() -> None:
    done = run("guard", stdin="\n".join(FILES))

    assert done.returncode == 0, done.stderr


def test_guard_refuses_a_pull_request_that_edits_the_changelog() -> None:
    """And names the remedy and the escape phrase, because a check that
    only says no is a check somebody works around."""
    done = run("guard", stdin="\n".join([*FILES, "CHANGELOG.md"]), body="An ordinary body.")

    assert done.returncode == 1
    assert "changelog.d/<issue>-<slug>.md" in done.stderr
    assert "Corrects CHANGELOG history" in done.stderr


def test_guard_accepts_the_exact_escape_phrase() -> None:
    """The recorded precedent is a restoration of entries that were
    silently dropped, which is a genuine correction of history and has
    to stay possible."""
    body = "Restores five merges of dropped entries.\n\nCorrects CHANGELOG history.\n"

    done = run("guard", stdin="CHANGELOG.md", body=body)

    assert done.returncode == 0, done.stderr


def test_guard_refuses_a_near_miss_of_the_escape_phrase() -> None:
    """Literal, and case-sensitive: a phrase that matched loosely would
    be a phrase a body could carry by accident."""
    done = run("guard", stdin="CHANGELOG.md", body="corrects changelog history")

    assert done.returncode == 1


@pytest.mark.parametrize("body", [None, ""], ids=["absent", "empty"])
def test_guard_treats_a_missing_body_as_no_body(body: str | None) -> None:
    """A pull request opened with no description sends a null body
    through the event payload, and an environment variable cannot hold
    null. Both spellings mean the same thing and neither crashes."""
    done = run("guard", stdin="CHANGELOG.md", body=body)

    assert done.returncode == 1
    assert "Traceback" not in done.stderr


def test_guard_reproduces_neither_the_file_list_nor_the_body() -> None:
    """The list comes from the pull request files API and the body from
    the event payload. Both are contributor-written text, and this runs
    on every pull request."""
    done = run(
        "guard",
        stdin="\n".join([f"docs/{SENTINEL}.md", "CHANGELOG.md"]),
        body=f"An ordinary body mentioning {SENTINEL}.",
    )

    assert done.returncode == 1
    assert SENTINEL not in done.stdout + done.stderr
