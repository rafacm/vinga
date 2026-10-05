"""The Run and Use page check's contract, exercised as a subprocess.

`scripts/check_run_use_pages.py` reads the Run vinga and Use vinga
sections of `docs/README.md`, enrolls every Markdown page they link,
and refuses an issue reference or the "decided direction" marker on
any of them. Its output is a CI log surface, so the no-leak standard
applies: a finding names a file, a line and a kind, never the line.

Each test builds a tree of its own with its own `docs/README.md`, runs
the real script the way both workflows do, and reads both streams
whole.
"""

import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "check_run_use_pages.py"
)

# Credential-shaped, and never a value that exists anywhere real.
SENTINEL = "sk-SENTINEL5e1d9c0b7a6f4e32"

DOORS = """# docs

Intro.

## Run vinga

- [**run page**](run.md): a page an operator reads.

## Use vinga

- [**use page**](use.md): a page a person at a device reads.

## Develop vinga

- [**dev page**](dev.md): a page a contributor reads.

## Reference

- [**reference**](reference/): generated.
"""

CLEAN = "# A page\n\nNothing owed to anyone here.\n"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def build(tmp_path: Path, pages: dict, index: str = DOORS) -> Path:
    """A tree whose docs/README.md is `index`, plus `pages` by path.

    Paths in `pages` are relative to the tree's root. The three door
    pages default to clean, so a test plants only what it is about.
    """
    files = {
        "docs/run.md": CLEAN,
        "docs/use.md": CLEAN,
        "docs/dev.md": CLEAN,
        **pages,
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (tmp_path / "docs" / "README.md").write_text(index, encoding="utf-8")
    return tmp_path


def findings(done: subprocess.CompletedProcess) -> set:
    """The finding lines, as (path, line, kind), without the summary."""
    out = set()
    for line in done.stdout.splitlines():
        if line.startswith("checked "):
            continue
        where, _, kind = line.rpartition(": ")
        path, _, lineno = where.rpartition(":")
        out.add((path, int(lineno), kind))
    return out


def assert_no_traceback(done: subprocess.CompletedProcess) -> None:
    for stream in (done.stdout, done.stderr):
        assert "Traceback" not in stream


# The clean case and the two door kinds of page


def test_a_clean_tree_passes(tmp_path: Path) -> None:
    done = run(str(build(tmp_path, {})))
    assert done.returncode == 0, done.stdout
    assert findings(done) == set()
    assert_no_traceback(done)


def test_an_issue_reference_on_a_run_page_fails(tmp_path: Path) -> None:
    build(tmp_path, {"docs/run.md": "# Run\n\nSee issue #123 for more.\n"})
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {("docs/run.md", 3, "issue-reference")}


def test_an_issue_reference_on_a_use_page_fails(tmp_path: Path) -> None:
    build(tmp_path, {"docs/use.md": "# Use\n\n(#123)\n"})
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {("docs/use.md", 3, "issue-reference")}


def test_an_issue_reference_inside_a_fence_fails(tmp_path: Path) -> None:
    page = "# Run\n\n```bash\n# see #123\necho ok\n```\n"
    build(tmp_path, {"docs/run.md": page})
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {("docs/run.md", 4, "issue-reference")}


def test_a_finding_never_republishes_its_line(tmp_path: Path) -> None:
    page = f"# Run\n\nkey {SENTINEL} owed to #123\n"
    build(tmp_path, {"docs/run.md": page})
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {("docs/run.md", 3, "issue-reference")}
    for stream in (done.stdout, done.stderr):
        assert SENTINEL not in stream
        assert "owed" not in stream
    assert_no_traceback(done)


# What counts as an issue reference, and what does not


def test_an_owner_repo_reference_fails(tmp_path: Path) -> None:
    build(tmp_path, {"docs/run.md": "# Run\n\nUpstream owner/repo#9.\n"})
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {("docs/run.md", 3, "issue-reference")}


def test_a_github_issue_url_fails(tmp_path: Path) -> None:
    page = "# Run\n\n<https://github.com/owner/repo/issues/5>\n"
    build(tmp_path, {"docs/run.md": page})
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {("docs/run.md", 3, "issue-reference")}


def test_a_github_pull_url_fails(tmp_path: Path) -> None:
    page = "# Run\n\n[it](https://github.com/owner/repo/pull/5)\n"
    build(tmp_path, {"docs/run.md": page})
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {("docs/run.md", 3, "issue-reference")}


def test_anchors_entities_and_page_fragments_pass(tmp_path: Path) -> None:
    page = (
        "# Run\n\n"
        "See [binding](concepts.md#binding).\n"
        "It&#8217;s fine.\n"
        "A numbered anchor: page.md#1, and docs/page.md#1.\n"
    )
    build(tmp_path, {"docs/run.md": page})
    done = run(str(tmp_path))
    assert done.returncode == 0, done.stdout
    assert findings(done) == set()


# The direction marker


def test_the_direction_marker_fails_in_any_case(tmp_path: Path) -> None:
    page = "# Use\n\nThis is **Decided Direction**.\n"
    build(tmp_path, {"docs/use.md": page})
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {("docs/use.md", 3, "direction-marker")}


def test_the_direction_marker_fails_across_a_line_break(
    tmp_path: Path,
) -> None:
    page = "# Use\n\nThis is a decided\ndirection, wrapped.\n"
    build(tmp_path, {"docs/use.md": page})
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {("docs/use.md", 3, "direction-marker")}


# Which pages are enrolled


def test_a_page_only_the_develop_door_links_passes(tmp_path: Path) -> None:
    page = "# Dev\n\n#1 and decided direction, both allowed here.\n"
    build(tmp_path, {"docs/dev.md": page})
    done = run(str(tmp_path))
    assert done.returncode == 0, done.stdout
    assert findings(done) == set()


def test_a_directory_link_under_docs_enrolls_its_pages(
    tmp_path: Path,
) -> None:
    index = DOORS.replace("(run.md)", "(guides/)")
    build(
        tmp_path,
        {
            "docs/guides/one.md": CLEAN,
            "docs/guides/deeper/two.md": "# Two\n\n#1\n",
        },
        index,
    )
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {
        ("docs/guides/deeper/two.md", 3, "issue-reference")
    }


def test_a_directory_link_outside_docs_enrolls_nothing(
    tmp_path: Path,
) -> None:
    index = DOORS.replace(
        "(run.md): a page an operator reads.",
        "(run.md): a page, with its artifacts in [`deploy/`](../deploy/).",
    )
    build(tmp_path, {"deploy/notes.md": "# Notes\n\n#1\n"}, index)
    done = run(str(tmp_path))
    assert done.returncode == 0, done.stdout
    assert findings(done) == set()


def test_an_index_link_enrolls_its_directory_and_nothing_beyond(
    tmp_path: Path,
) -> None:
    index = DOORS.replace("(run.md)", "(guides/README.md)")
    build(
        tmp_path,
        {
            # The index lists one guide and links one page outside its
            # own directory; the second guide is listed nowhere.
            "docs/guides/README.md": (
                "# Guides\n\n- [one](one.md)\n- [notes](../notes.md)\n"
            ),
            "docs/guides/one.md": CLEAN,
            "docs/guides/forgotten.md": "# Forgotten\n\n#1\n",
            "docs/notes.md": "# Notes\n\n#1\n",
        },
        index,
    )
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {
        ("docs/guides/forgotten.md", 3, "issue-reference")
    }


def test_a_readme_outside_docs_enrolls_that_page_alone(
    tmp_path: Path,
) -> None:
    index = DOORS.replace("(run.md)", "(../pkg/README.md)")
    build(
        tmp_path,
        {
            "pkg/README.md": "# Pkg\n\n- [other](other.md)\n\n#1\n",
            "pkg/other.md": "# Other\n\n#1\n",
            "pkg/sibling.md": "# Sibling\n\n#1\n",
        },
        index,
    )
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {("pkg/README.md", 5, "issue-reference")}


def test_the_generated_references_are_excluded(tmp_path: Path) -> None:
    index = DOORS.replace(
        "(run.md): a page an operator reads.",
        "(run.md): a page; [one key](reference/keys.md#a), [all](reference/).",
    )
    build(tmp_path, {"docs/reference/keys.md": "# Keys\n\n#1\n"}, index)
    done = run(str(tmp_path))
    assert done.returncode == 0, done.stdout
    assert findings(done) == set()


def test_anchors_and_non_markdown_targets_enroll_nothing(
    tmp_path: Path,
) -> None:
    index = DOORS.replace(
        "(run.md): a page an operator reads.",
        "(run.md): see [below](#reference) and [sql](../deploy/init.sql).",
    )
    build(tmp_path, {"deploy/init.sql": "-- #1\n"}, index)
    done = run(str(tmp_path))
    assert done.returncode == 0, done.stdout


def test_the_index_itself_is_never_enrolled(tmp_path: Path) -> None:
    # The index may cite issues (it is an index page); a door link
    # that names its own file is a same-page link, not an enrolment of
    # the whole docs directory.
    index = DOORS.replace(
        "(run.md): a page an operator reads.",
        "(run.md): see [the table](README.md#reference) and #615.",
    )
    build(tmp_path, {"docs/plans/old.md": "# Old\n\n#1\n"}, index)
    done = run(str(tmp_path))
    assert done.returncode == 0, done.stdout


# Door discovery fails closed


def test_a_missing_run_heading_fails_closed(tmp_path: Path) -> None:
    index = DOORS.replace("## Run vinga", "## Running vinga")
    build(tmp_path, {}, index)
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert ("docs/README.md", 0, "door-missing") in findings(done)


def test_a_missing_use_heading_fails_closed(tmp_path: Path) -> None:
    index = DOORS.replace("## Use vinga", "## Using vinga")
    build(tmp_path, {}, index)
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert ("docs/README.md", 0, "door-missing") in findings(done)


def test_a_missing_index_fails_closed(tmp_path: Path) -> None:
    build(tmp_path, {})
    (tmp_path / "docs" / "README.md").unlink()
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {("docs/README.md", 0, "door-missing")}
    assert_no_traceback(done)


def test_a_door_linking_no_page_fails_closed(tmp_path: Path) -> None:
    index = DOORS.replace(
        "- [**use page**](use.md): a page a person at a device reads.",
        "Nothing here yet, only [a heading](#reference).",
    )
    build(tmp_path, {}, index)
    done = run(str(tmp_path))
    assert done.returncode == 1
    # The Use vinga heading is line 9 of DOORS.
    assert findings(done) == {("docs/README.md", 9, "door-missing")}


def test_a_door_link_with_wrapped_text_enrolls_its_page(
    tmp_path: Path,
) -> None:
    index = DOORS.replace(
        "- [**run page**](run.md): a page an operator reads.",
        "- [**a run page whose\n  title wraps**](run.md): a page.",
    )
    build(tmp_path, {"docs/run.md": "# Run\n\n#123\n"}, index)
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert findings(done) == {("docs/run.md", 3, "issue-reference")}


def test_a_door_link_with_a_broken_target_is_malformed(
    tmp_path: Path,
) -> None:
    index = DOORS.replace(
        "- [**use page**](use.md): a page a person at a device reads.",
        "- [**use page**](use.md): a page.\n- [**guide**](guides/\n  one.md): x.",
    )
    build(tmp_path, {"docs/guides/one.md": CLEAN}, index)
    done = run(str(tmp_path))
    assert done.returncode == 1
    # The Use vinga heading is line 9 of DOORS.
    assert findings(done) == {("docs/README.md", 9, "door-malformed")}


def test_a_heading_inside_a_fence_does_not_open_a_door(
    tmp_path: Path,
) -> None:
    index = DOORS.replace(
        "## Run vinga", "```text\n## Run vinga\n```\n\n## Elsewhere"
    )
    build(tmp_path, {}, index)
    done = run(str(tmp_path))
    assert done.returncode == 1
    assert ("docs/README.md", 0, "door-missing") in findings(done)


# Invocation


def test_a_bad_invocation_is_a_sentence_and_exit_two() -> None:
    for done in (run(), run("/nonexistent-root-for-this-test")):
        assert done.returncode == 2
        assert done.stdout == ""
        assert len(done.stderr.strip().splitlines()) == 1
        assert_no_traceback(done)
