"""Every reach-in the test suite makes, counted once and frozen once.

The design guide's rule is that a test reaches the names a caller
reaches, so an underscore reach-in is a review flag: either the module
is missing an interface callers need, or the test pins a detail that is
free to change. `tests/tools/reach_ins.py` has counted them since #210's
M6, and counting them is not the same as noticing them arrive. The
census went from 162 sites to 355 with nobody reading a diff, because a
number nobody renders is a number nobody compares.

So the census emits the manifest beside it (`reach-ins.txt`): one line
per distinct `path  name` pair with the number of sites at it, and the
drift test below fails when the committed copy and a fresh walk
disagree. What that buys is not detection, which an exact-count pin
would buy for ten lines and no artifact. It is naming. A pin's diff
reads `355 -> 356` and the reviewer has to run the tool to learn what
landed; a manifest line reading `tests/unit/test_x.py  _foo  1` is the
review moment itself.

The count column is where this manifest diverges from
`command-spellings.txt`, which records the distinct set and nothing
else. The divergence is deliberate and was measured: over the 400
revisions touching `tests/` that the plan read, eleven of the
twenty-eight changes moved a count while the pair set stood still, so a
count-free render here would have missed eleven of twenty-eight while
looking like the safer copy of its own precedent.

What the manifest does not do is approve of its contents. It freezes
355 sites and claims no reduction: that is #531 M3's, after #482 and
#488 M1 retire the share of it their extractions are expected to.

Regenerating is `uv run python -m tests.census.test_reach_ins` from
`vinga-server/`, never a hand edit.
"""

from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

import pytest

from tests.tools.reach_ins import MANIFEST_HEADER, Site, manifest_of, tracked, walk

# The tests directory, found from this file rather than from the
# working directory, for the same reason the tool passes `git -C`: the
# lane runs from `vinga-server/` and nothing should change if it does
# not.
TESTS_ROOT = Path(__file__).resolve().parents[1]

MANIFEST = Path(__file__).with_name("reach-ins.txt")


def manifest() -> str:
    """The census as the committed manifest reads."""
    reached, _own = walk(TESTS_ROOT)
    return manifest_of(reached)


def test_the_manifest_is_the_census() -> None:
    """The committed count, held to a fresh walk.

    This is the milestone's point and the only test here that reads the
    real tree. A reach-in that arrives without its manifest line fails
    in both workflows, which is what makes the next one arrive as a diff
    line with a justification beside it rather than as a number nobody
    compared.
    """
    assert MANIFEST.read_text(encoding="utf-8") == manifest()


# The aggregation, pinned in both directions
#
# Synthetic sites rather than real ones, so a fixture cannot go stale
# when the file it was found in is fixed, and so what is checked is the
# shape rather than today's tree.


def at(path: str, line: int, name: str) -> Site:
    """One site, with the receiver the manifest deliberately forgets."""
    return Site(path=path, line=line, receiver="session", name=name)


def entries(rendered: str) -> list[str]:
    """One rendered manifest's lines below its header."""
    assert rendered.startswith(MANIFEST_HEADER)
    return rendered.removeprefix(MANIFEST_HEADER).splitlines()


def test_two_sites_at_one_pair_are_one_line_carrying_two() -> None:
    """The aggregation itself: the pair is the line, the count is what
    the line says, and the order the sites were walked in is not in the
    artifact at all, so a rebase cannot reorder it."""
    rows = [at("tests/unit/test_a.py", 10, "_foo"), at("tests/unit/test_a.py", 40, "_foo")]

    assert entries(manifest_of(rows)) == ["tests/unit/test_a.py  _foo  2"]
    assert manifest_of(list(reversed(rows))) == manifest_of(rows)


def test_one_name_reached_in_two_files_is_two_lines() -> None:
    """And the half the aggregation must not collapse. The path is what
    makes a line actionable, so the same private name reached in two
    files is two entries rather than one reading 2."""
    rows = [at("tests/unit/test_a.py", 10, "_foo"), at("tests/unit/test_b.py", 10, "_foo")]

    assert entries(manifest_of(rows)) == [
        "tests/unit/test_a.py  _foo  1",
        "tests/unit/test_b.py  _foo  1",
    ]


def test_a_site_moving_within_its_file_moves_nothing() -> None:
    """No positions, which is the property that keeps the artifact
    still. An import shuffle, a reformat or any edit above a site moves
    its line and nothing else, and the manifest is unmoved by all of
    them."""
    before = [at("tests/unit/test_a.py", 10, "_foo")]
    after = [at("tests/unit/test_a.py", 900, "_foo")]

    assert manifest_of(after) == manifest_of(before)


def test_a_site_leaving_a_pair_another_site_keeps_moves_the_line() -> None:
    """The divergence from `command-spellings.txt`, asserted rather than
    described.

    That manifest records a distinct set, so dropping one of two sites
    at a pair renders byte-identically and the change is invisible: a
    real loss of granularity, priced when its positions were dropped.
    Here the count is what the line says, so the same drop moves the
    line. The property is pinned so no later edit can quietly recover
    the cheaper shape while keeping the claim.
    """
    both = [at("tests/unit/test_a.py", 10, "_foo"), at("tests/unit/test_a.py", 40, "_foo")]
    one_gone = [at("tests/unit/test_a.py", 10, "_foo")]

    assert manifest_of(one_gone) != manifest_of(both)
    assert entries(manifest_of(one_gone)) == ["tests/unit/test_a.py  _foo  1"]


def test_the_render_sorts_rather_than_inheriting_a_walk_order() -> None:
    """Determinism, made rather than found. The sort is explicit, so the
    order is a property of the manifest rather than of `git ls-files`,
    of the filesystem, or of `Counter`'s insertion order."""
    rows = [
        at("tests/unit/test_b.py", 3, "_bar"),
        at("tests/unit/test_a.py", 9, "_zed"),
        at("tests/unit/test_a.py", 1, "_foo"),
        at("tests/unit/test_a.py", 2, "_foo"),
        at("tests/support/fakes.py", 7, "_foo"),
    ]
    shuffled = random.Random(20260920).sample(rows, len(rows))

    assert manifest_of(shuffled) == manifest_of(rows)
    assert entries(manifest_of(rows)) == [
        "tests/support/fakes.py  _foo  1",
        "tests/unit/test_a.py  _foo  2",
        "tests/unit/test_a.py  _zed  1",
        "tests/unit/test_b.py  _bar  1",
    ]


# The file set
#
# A throwaway checkout rather than the real tree, because the claims
# here are about what git lists and what the working tree holds, and
# neither can be arranged under `tests/` without a test that writes into
# the suite it is measuring. `git ls-files` reads the index, so `git
# add` is enough and nothing needs committing.

REACHES = "def test_x(session):\n    assert session.{name}\n"


def checkout(root: Path, tracked_files: dict[str, str]) -> Path:
    """A throwaway checkout with `tests/` inside it, returned."""
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    for name, text in tracked_files.items():
        written = root / name
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(text, encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "add", "--", *tracked_files],
        check=True,
        capture_output=True,
    )
    return root / "tests"


def test_an_untracked_file_does_not_change_the_render(tmp_path: Path) -> None:
    """The reason the enumeration moved off `Path.rglob`.

    A scratch file nobody committed is not census surface, and under a
    filesystem walk it would be: with a committed manifest diffed
    against the walk, `tests/scratch.py` turns into a red run that
    blames the manifest for a file that is not in the repository.
    """
    root = checkout(tmp_path / "repo", {"tests/test_a.py": REACHES.format(name="_foo")})
    before = manifest_of(walk(root)[0])

    (root / "scratch.py").write_text(REACHES.format(name="_untracked"), encoding="utf-8")

    assert entries(before) == ["tests/test_a.py  _foo  1"]
    assert manifest_of(walk(root)[0]) == before


def test_a_tracked_path_that_is_not_on_disk_is_skipped(tmp_path: Path) -> None:
    """`ls-files` lists a file deleted but not yet staged, and a missing
    file is a fact about the working tree rather than about the census,
    so the walk steps over it instead of raising."""
    root = checkout(
        tmp_path / "repo",
        {
            "tests/test_a.py": REACHES.format(name="_foo"),
            "tests/test_gone.py": REACHES.format(name="_bar"),
        },
    )
    (root / "test_gone.py").unlink()

    assert tracked(root) == [root / "test_a.py", root / "test_gone.py"]
    assert entries(manifest_of(walk(root)[0])) == ["tests/test_a.py  _foo  1"]


def test_a_root_outside_the_checkout_is_refused_by_its_name(tmp_path: Path) -> None:
    """Refused rather than walked another way. Two enumerations would be
    two structures that must agree, and the failure a silent fallback
    produces is an empty census, which reads exactly like a clean
    tree."""
    outside = tmp_path / "not-a-checkout"
    outside.mkdir()

    with pytest.raises(ValueError, match=str(outside)):
        walk(outside)


@pytest.mark.parametrize(
    ("root", "quoted"),
    [
        (TESTS_ROOT, "tests/unit/test_config_cli_rendering.py"),
        (TESTS_ROOT / "unit", "unit/test_config_cli_rendering.py"),
    ],
    ids=["the default root", "a nested root"],
)
def test_a_root_renders_the_paths_it_always_has_from_anywhere(
    root: Path, quoted: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rendering the tracked-file switch had to leave alone.

    Each root still renders relative to its own parent, and it renders
    the same paths from a working directory that is not
    `vinga-server/`, which is the case an ambient `git ls-files` would
    silently get wrong: the listing would be relative to wherever the
    caller happened to stand, and every path in the manifest would move
    with it.
    """
    from_the_lane = manifest_of(walk(root)[0])
    monkeypatch.chdir(tmp_path)

    assert manifest_of(walk(root)[0]) == from_the_lane
    assert f"{quoted}  " in from_the_lane


def test_the_receivers_the_census_excludes_stay_out_of_the_manifest(tmp_path: Path) -> None:
    """A test file's own fakes keep private state of their own, and
    reaching for it crosses no interface. The tool excludes `self` and
    `cls` at the census level; the manifest must not quietly undo the
    exclusion by rendering what the walk already dropped."""
    own_state = (
        "class Fake:\n"
        "    def read(self):\n"
        "        return self._value\n"
        "\n"
        "    @classmethod\n"
        "    def make(cls):\n"
        "        return cls._default\n"
    )
    root = checkout(tmp_path / "repo", {"tests/test_a.py": own_state})

    assert entries(manifest_of(walk(root)[0])) == []


if __name__ == "__main__":  # pragma: no cover - the regeneration entry point
    MANIFEST.write_text(manifest(), encoding="utf-8")
    sys.stdout.write(f"wrote {MANIFEST}\n")
