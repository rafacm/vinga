"""The page-move audit's contract, exercised as a subprocess.

`scripts/audit_doc_move.py` compares a Markdown page before a move
with the page after it and the pages its sections moved to, by a
committed mapping of move units, and exits 0 only when every paragraph
of every unit is accounted for: found verbatim in its destination,
declared edited, declared dropped, or declared kept in the page. Its
output reaches a log and a pull request body, so the no-leak standard
applies: it names a mapping row, a paragraph position, a source line
and a digest, never a byte of the page, headings included.

Each test writes a page, its successor, the destinations and a mapping
into a directory of its own, and runs the real script there, the way a
pull request runs it from the repository root.
"""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "audit_doc_move.py"

# Credential-shaped, and never a value that exists anywhere real.
SENTINEL = "sk-SENTINEL7c2e9a41d0b38f56"

OLD = """# Server

Intro paragraph.

## Alpha

Alpha one.

Alpha two.

### Alpha deep

Alpha three.

## Beta

Beta one.

```bash
echo first

### not a heading, inside a fence
echo second

echo third
```

## Gamma

Gamma one.
"""

# The page with Alpha and Beta gone, which is what a clean move of
# both leaves behind.
WITHOUT_ALPHA_AND_BETA = """# Server

Intro paragraph.

## Gamma

Gamma one.
"""

BETA_GUIDE = """# Doing beta

What you will have at the end.

## Beta

Beta one.

```bash
echo first

### not a heading, inside a fence
echo second

echo third
```
"""


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=cwd,
    )


def line_of(text: str, line: str) -> int:
    """The 1-based line number of the first line equal to `line`."""
    return text.splitlines().index(line) + 1


def audit(tmp_path: Path, old: str, new: str, mapping: str, pages: dict):
    """Write the four inputs and run the audit over them."""
    (tmp_path / "old.md").write_text(old, encoding="utf-8")
    (tmp_path / "new.md").write_text(new, encoding="utf-8")
    (tmp_path / "moves.tsv").write_text(mapping, encoding="utf-8")
    for rel, text in pages.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return run(tmp_path, "old.md", "new.md", "moves.tsv")


def without_beta(text: str) -> str:
    """`text` with its Beta section cut out, as a clean move leaves it."""
    return text.replace(text[text.index("## Beta") : text.index("## Gamma")], "")


def summary(done: subprocess.CompletedProcess) -> str:
    return done.stdout.strip().splitlines()[-1]


def finding_lines(done: subprocess.CompletedProcess) -> list:
    return [line for line in done.stdout.splitlines() if line.startswith("finding: ")]


def assert_no_traceback(done: subprocess.CompletedProcess) -> None:
    for stream in (done.stdout, done.stderr):
        assert "Traceback" not in stream


ALPHA = line_of(OLD, "## Alpha")
BETA = line_of(OLD, "## Beta")
GAMMA = line_of(OLD, "## Gamma")


# Moves that account for everything


def test_a_clean_split_passes(tmp_path: Path) -> None:
    """One section cut between two destinations, a heading demoted."""
    mapping = (
        f"{ALPHA}\t1-3\tdocs/a.md\tkinds=explanation\n"
        f"{ALPHA}\t4-5\tdocs/b.md\tkinds=procedure\n"
        f"{BETA}\tdocs/beta.md\tkinds=procedure\n"
    )
    pages = {
        "docs/a.md": "# A\n\nNew opening.\n\n## Alpha\n\nAlpha one.\n\nAlpha two.\n",
        "docs/b.md": "# B\n\n## Alpha deep\n\nAlpha three.\n",
        "docs/beta.md": BETA_GUIDE,
    }
    done = audit(tmp_path, OLD, WITHOUT_ALPHA_AND_BETA, mapping, pages)
    assert done.returncode == 0, done.stdout + done.stderr
    assert finding_lines(done) == []
    assert summary(done).startswith("3 units, 8 paragraphs moved, ")
    assert summary(done).endswith(", 0 findings")
    assert_no_traceback(done)


def test_the_mapping_may_carry_comments_and_blank_lines(tmp_path: Path) -> None:
    mapping = f"# what moved where\n\n{BETA}\tdocs/beta.md\tkinds=procedure\n\n"
    new = without_beta(OLD)
    done = audit(tmp_path, OLD, new, mapping, {"docs/beta.md": BETA_GUIDE})
    assert done.returncode == 0, done.stdout + done.stderr
    assert summary(done).startswith("1 units, 3 paragraphs moved, ")


# The planted faults the prototype was run against


def test_a_paragraph_missing_from_a_split_destination_fails(tmp_path: Path) -> None:
    mapping = (
        f"{ALPHA}\t1-3\tdocs/a.md\tkinds=explanation\n"
        f"{ALPHA}\t4-5\tdocs/b.md\tkinds=procedure\n"
        f"{BETA}\tdocs/beta.md\tkinds=procedure\n"
    )
    pages = {
        "docs/a.md": "# A\n\n## Alpha\n\nAlpha one.\n\nAlpha two.\n",
        "docs/b.md": "# B\n\n## Alpha deep\n",
        "docs/beta.md": BETA_GUIDE,
    }
    done = audit(tmp_path, OLD, WITHOUT_ALPHA_AND_BETA, mapping, pages)
    assert done.returncode == 1
    three = line_of(OLD, "Alpha three.")
    found = finding_lines(done)
    assert len(found) == 1
    assert found[0].startswith(f"finding: row 2, paragraph 5 (line {three}, ")
    assert found[0].endswith(": not verbatim in docs/b.md")
    assert summary(done).endswith(", 1 findings")


def test_a_section_also_left_in_the_page_fails(tmp_path: Path) -> None:
    """Copied rather than moved: every paragraph is reported."""
    mapping = f"{BETA}\tdocs/beta.md\tkinds=procedure\n"
    done = audit(tmp_path, OLD, OLD, mapping, {"docs/beta.md": BETA_GUIDE})
    assert done.returncode == 1
    found = finding_lines(done)
    assert len(found) == 3
    assert all(line.endswith(": left behind in the page") for line in found)


def test_a_duplicated_paragraph_needs_both_copies_in_its_destination(
    tmp_path: Path,
) -> None:
    old = OLD.replace("Alpha two.", "Same words.").replace("Beta one.", "Same words.")
    new = WITHOUT_ALPHA_AND_BETA
    mapping = (
        f"{ALPHA}\tdocs/all.md\tkinds=explanation\n"
        f"{BETA}\tdocs/all.md\tkinds=procedure\n"
    )
    one_copy = (
        "# All\n\n## Alpha\n\nAlpha one.\n\nSame words.\n\n### Alpha deep\n\n"
        "Alpha three.\n\n## Beta\n\n```bash\necho first\n\n"
        "### not a heading, inside a fence\necho second\n\necho third\n```\n"
    )
    done = audit(tmp_path, old, new, mapping, {"docs/all.md": one_copy})
    assert done.returncode == 1
    found = finding_lines(done)
    assert len(found) == 1
    assert found[0].startswith("finding: row 2, paragraph 2 ")
    assert found[0].endswith(": not verbatim in docs/all.md")


def test_one_copy_moved_while_both_stay_in_the_page_fails(tmp_path: Path) -> None:
    """A paragraph that also occurs in a section nobody moved may stay
    as often as that section holds it, and no more."""
    old = OLD.replace("Gamma one.", "Beta one.")
    mapping = f"{BETA}\tdocs/beta.md\tkinds=procedure\n"
    kept_both = old.replace("## Beta\n\n", "")
    done = audit(tmp_path, old, kept_both, mapping, {"docs/beta.md": BETA_GUIDE})
    assert done.returncode == 1
    found = finding_lines(done)
    assert len(found) == 2  # the heading is gone; Beta one. and the fence are not
    removed = without_beta(old)
    done = audit(tmp_path, old, removed, mapping, {"docs/beta.md": BETA_GUIDE})
    assert done.returncode == 0, done.stdout


def test_overlapping_units_fail(tmp_path: Path) -> None:
    mapping = (
        f"{ALPHA}\tdocs/a.md\tkinds=explanation\n"
        f"{ALPHA}\t2-2\tdocs/b.md\tkinds=explanation\n"
    )
    pages = {
        "docs/a.md": "# A\n\n## Alpha\n\nAlpha one.\n\nAlpha two.\n\n"
        "### Alpha deep\n\nAlpha three.\n",
        "docs/b.md": "# B\n\nAlpha one.\n",
    }
    new = OLD.replace(OLD[OLD.index("## Alpha") : OLD.index("## Beta")], "")
    done = audit(tmp_path, OLD, new, mapping, pages)
    assert done.returncode == 1
    one = line_of(OLD, "Alpha one.")
    assert f"finding: line {one}: named by 2 units" in done.stdout.splitlines()


# Nothing of the page reaches the output


SECRET_OLD = f"""# Server

## Key {SENTINEL}

Token {SENTINEL} here.

## Rest

Rest one.
"""


def test_no_byte_of_the_page_reaches_a_passing_run(tmp_path: Path) -> None:
    line = line_of(SECRET_OLD, f"## Key {SENTINEL}")
    mapping = f"{line}\tdocs/k.md\tkinds=procedure\n"
    new = "# Server\n\n## Rest\n\nRest one.\n"
    guide = f"# K\n\n### Key {SENTINEL}\n\nToken {SENTINEL} here.\n"
    done = audit(tmp_path, SECRET_OLD, new, mapping, {"docs/k.md": guide})
    assert done.returncode == 0, done.stdout
    for stream in (done.stdout, done.stderr):
        assert SENTINEL not in stream
        assert "Token" not in stream
        assert "Key" not in stream


def test_no_byte_of_the_page_reaches_a_failing_run(tmp_path: Path) -> None:
    line = line_of(SECRET_OLD, f"## Key {SENTINEL}")
    mapping = f"{line}\tdocs/k.md\tkinds=procedure\n"
    done = audit(tmp_path, SECRET_OLD, SECRET_OLD, mapping, {"docs/k.md": "# K\n"})
    assert done.returncode == 1
    assert len(finding_lines(done)) == 4
    for stream in (done.stdout, done.stderr):
        assert SENTINEL not in stream
        assert "Token" not in stream
        assert "Key" not in stream
    assert_no_traceback(done)


def test_list_names_positions_lines_and_digests_only(tmp_path: Path) -> None:
    (tmp_path / "old.md").write_text(SECRET_OLD, encoding="utf-8")
    line = line_of(SECRET_OLD, f"## Key {SENTINEL}")
    done = run(tmp_path, "old.md", "--list", str(line))
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines()[0].startswith(f"paragraph 1: line {line}, ")
    assert done.stdout.splitlines()[0].endswith(", heading")
    assert len(done.stdout.splitlines()) == 2
    for stream in (done.stdout, done.stderr):
        assert SENTINEL not in stream
        assert "Token" not in stream


def test_list_reads_a_fence_as_one_paragraph(tmp_path: Path) -> None:
    (tmp_path / "old.md").write_text(OLD, encoding="utf-8")
    done = run(tmp_path, "old.md", "--list", str(BETA))
    assert done.returncode == 0, done.stderr
    assert len(done.stdout.splitlines()) == 3


# Declared edits, drops and kept headings


def test_a_declared_edit_passes(tmp_path: Path) -> None:
    mapping = f"{BETA}\tdocs/beta.md\tkinds=procedure,contract\tedited=2\n"
    guide = BETA_GUIDE.replace("Beta one.", "Beta one, with a [link](x.md).")
    done = audit(tmp_path, OLD, without_beta(OLD), mapping, {"docs/beta.md": guide})
    assert done.returncode == 0, done.stdout
    one = line_of(OLD, "Beta one.")
    declared = [line for line in done.stdout.splitlines() if line.startswith("declared: ")]
    assert len(declared) == 1
    assert declared[0].startswith(f"declared: row 1, paragraph 2 (line {one}, ")
    assert declared[0].endswith(": edited, not verbatim in docs/beta.md")


def test_a_stale_declared_edit_fails(tmp_path: Path) -> None:
    mapping = f"{BETA}\tdocs/beta.md\tkinds=procedure\tedited=2\n"
    new = without_beta(OLD)
    done = audit(tmp_path, OLD, new, mapping, {"docs/beta.md": BETA_GUIDE})
    assert done.returncode == 1
    found = finding_lines(done)
    assert len(found) == 1
    assert found[0].endswith(": declared edited but verbatim in docs/beta.md")


def test_a_dropped_unit_passes(tmp_path: Path) -> None:
    mapping = f"{BETA}\tDROP\n"
    new = without_beta(OLD)
    done = audit(tmp_path, OLD, new, mapping, {})
    assert done.returncode == 0, done.stdout
    declared = [line for line in done.stdout.splitlines() if line.startswith("declared: ")]
    assert len(declared) == 3
    assert all(line.endswith(": dropped") for line in declared)


def test_a_dropped_unit_still_in_the_page_fails(tmp_path: Path) -> None:
    done = audit(tmp_path, OLD, OLD, f"{BETA}\tDROP\n", {})
    assert done.returncode == 1
    assert len(finding_lines(done)) == 3


def test_a_kept_heading_passes(tmp_path: Path) -> None:
    """The forwarding stub: the heading stays, one new sentence under it."""
    mapping = (
        f"{BETA}\t1-1\tREADME\n"
        f"{BETA}\t2-3\tdocs/beta.md\tkinds=procedure\n"
    )
    new = OLD.replace(
        OLD[OLD.index("## Beta") : OLD.index("## Gamma")],
        "## Beta\n\nBeta is now [a guide](docs/beta.md).\n\n",
    )
    done = audit(tmp_path, OLD, new, mapping, {"docs/beta.md": BETA_GUIDE})
    assert done.returncode == 0, done.stdout
    kept = [line for line in done.stdout.splitlines() if line.endswith(": kept in the page")]
    assert len(kept) == 1
    assert kept[0].startswith(f"declared: row 1, paragraph 1 (line {BETA}, ")


def test_a_kept_unit_naming_a_body_paragraph_fails(tmp_path: Path) -> None:
    mapping = (
        f"{BETA}\t1-1\tdocs/beta.md\tkinds=procedure\n"
        f"{BETA}\t2-2\tREADME\n"
        f"{BETA}\t3-3\tdocs/beta.md\tkinds=procedure\n"
    )
    new = OLD.replace(
        OLD[OLD.index("## Beta") : OLD.index("## Gamma")], "Beta one.\n\n"
    )
    done = audit(tmp_path, OLD, new, mapping, {"docs/beta.md": BETA_GUIDE})
    assert done.returncode == 1
    assert "finding: row 2: a kept unit names one heading and nothing else" in (
        done.stdout.splitlines()
    )


def test_a_kept_unit_naming_two_paragraphs_fails(tmp_path: Path) -> None:
    mapping = (
        f"{BETA}\t1-2\tREADME\n"
        f"{BETA}\t3-3\tdocs/beta.md\tkinds=procedure\n"
    )
    new = OLD.replace("```bash\necho first", "```bash\necho moved")
    done = audit(tmp_path, OLD, new, mapping, {"docs/beta.md": BETA_GUIDE})
    assert done.returncode == 1
    assert "finding: row 1: a kept unit names one heading and nothing else" in (
        done.stdout.splitlines()
    )


def test_procedure_text_left_under_a_kept_heading_fails(tmp_path: Path) -> None:
    """The exception covers the heading and nothing under it."""
    mapping = (
        f"{BETA}\t1-1\tREADME\n"
        f"{BETA}\t2-3\tdocs/beta.md\tkinds=procedure\n"
    )
    new = OLD.replace("Beta one.", "Beta is now a guide.\n\nBeta one.")
    done = audit(tmp_path, OLD, new, mapping, {"docs/beta.md": BETA_GUIDE})
    assert done.returncode == 1
    found = finding_lines(done)
    assert len(found) == 2
    assert all(line.endswith(": left behind in the page") for line in found)


def test_a_kept_heading_gone_from_the_page_fails(tmp_path: Path) -> None:
    mapping = (
        f"{BETA}\t1-1\tREADME\n"
        f"{BETA}\t2-3\tdocs/beta.md\tkinds=procedure\n"
    )
    new = without_beta(OLD)
    done = audit(tmp_path, OLD, new, mapping, {"docs/beta.md": BETA_GUIDE})
    assert done.returncode == 1
    found = finding_lines(done)
    assert len(found) == 1
    assert found[0].endswith(": not kept in the page")


# Bad invocations and bad mappings exit 2, and say nothing of the page


# Every destination a bad mapping could name exists, so the refusal
# under test is the only reason the run can stop.
PAGES = {"docs/a.md": "# A\n", "docs/beta.md": BETA_GUIDE}


def bad(tmp_path: Path, mapping: str, said: str) -> None:
    done = audit(tmp_path, OLD, WITHOUT_ALPHA_AND_BETA, mapping, PAGES)
    assert done.returncode == 2, done.stdout + done.stderr
    assert said in done.stderr
    assert "Alpha one" not in done.stderr
    assert_no_traceback(done)


def test_no_arguments_exits_2(tmp_path: Path) -> None:
    done = run(tmp_path)
    assert done.returncode == 2
    assert "usage" in done.stderr


def test_an_unreadable_mapping_exits_2(tmp_path: Path) -> None:
    (tmp_path / "old.md").write_text(OLD, encoding="utf-8")
    (tmp_path / "new.md").write_text(OLD, encoding="utf-8")
    done = run(tmp_path, "old.md", "new.md", "missing.tsv")
    assert done.returncode == 2
    assert_no_traceback(done)


def test_an_unreadable_destination_exits_2(tmp_path: Path) -> None:
    bad(tmp_path, f"{BETA}\tdocs/missing.md\tkinds=procedure\n", "cannot read the destination")


def test_a_line_that_is_not_a_heading_exits_2(tmp_path: Path) -> None:
    one = line_of(OLD, "Alpha one.")
    bad(tmp_path, f"{one}\tdocs/a.md\tkinds=procedure\n", f"line {one} is not a heading")


def test_a_line_that_starts_no_paragraph_exits_2(tmp_path: Path) -> None:
    inside = line_of(OLD, "echo second")
    bad(tmp_path, f"{inside}\tdocs/a.md\tkinds=procedure\n", "starts no paragraph")


def test_a_mapping_with_no_unit_exits_2(tmp_path: Path) -> None:
    bad(tmp_path, "# nothing moved\n\n", "names no unit")


def test_a_unit_without_kinds_exits_2(tmp_path: Path) -> None:
    bad(tmp_path, f"{BETA}\tdocs/beta.md\n", "says its kinds=")


def test_an_unknown_kind_exits_2(tmp_path: Path) -> None:
    bad(tmp_path, f"{BETA}\tdocs/beta.md\tkinds=prose\n", "kinds= takes")


def test_an_unknown_field_exits_2(tmp_path: Path) -> None:
    bad(tmp_path, f"{BETA}\tdocs/beta.md\tkinds=procedure\tmoved=yes\n", "unknown field")


def test_an_edit_declared_outside_its_unit_exits_2(tmp_path: Path) -> None:
    bad(
        tmp_path,
        f"{BETA}\t2-3\tdocs/beta.md\tkinds=procedure\tedited=1\n",
        "outside the unit",
    )


def test_a_range_outside_the_section_exits_2(tmp_path: Path) -> None:
    bad(tmp_path, f"{BETA}\t2-9\tdocs/beta.md\tkinds=procedure\n", "outside the section")


def test_a_rewrapped_paragraph_is_still_verbatim(tmp_path: Path) -> None:
    """Whitespace collapses, so moving a link onto one line, or
    reflowing a paragraph, is not an edit."""
    mapping = f"{BETA}\tdocs/beta.md\tkinds=procedure\n"
    guide = BETA_GUIDE.replace("Beta one.", "Beta\n   one.")
    done = audit(tmp_path, OLD, without_beta(OLD), mapping, {"docs/beta.md": guide})
    assert done.returncode == 0, done.stdout
