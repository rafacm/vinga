"""How many workers `-n auto` is allowed to start, and why there is a
ceiling at all.

`pyproject.toml` caps the resolved worker count, for a reason that has
nothing to do with the tests: above roughly eight processes connecting
at once, connections from the host to the compose instance through its
published port start failing, and they fail as "server closed the
connection unexpectedly" at connect time. Hundreds of tests then report
that the database is unreachable while it is open and serving every
other worker (#537).

The cap is one token in one list, which is exactly the kind of thing a
later edit removes while tidying, and its absence is invisible
everywhere it matters: CI resolves four workers on a four-core runner,
so the lane that would catch the regression is the one lane that cannot
feel it.

What makes it testable anywhere is that xdist does not read the core
count directly. `-n auto` is resolved through the
`pytest_xdist_auto_num_workers` hook, and `--maxprocesses` is applied
to whatever that hook returns. So a nested run whose own plugin answers
that hook with fourteen exercises the ceiling on a machine of any size,
including a four-core runner.

The nested run collects one trivial file in a temporary directory,
which is what keeps this cheap and what keeps it off the database:
nothing under `tests/` is collected, so no lane conftest is imported
and nothing provisions a store. It costs about half a second.
"""

import subprocess
import sys
from pathlib import Path

import pytest

# The ceiling this file exists to hold. Read from the same place the
# runs read it, rather than spelled again here: a second spelling of
# the number would pass while the real one was gone, which is the whole
# failure this test is for.
PYPROJECT = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"

# What the nested run's `auto` answers, chosen well above the ceiling so
# that a clamped result cannot be the honest core count of any machine
# this suite plausibly runs on.
FORCED = 14


def _ceiling() -> int:
    """The number `--maxprocesses` carries in this project's addopts."""
    import tomllib

    addopts = tomllib.loads(PYPROJECT.read_text())["tool"]["pytest"][
        "ini_options"
    ]["addopts"]
    for option in addopts:
        if option.startswith("--maxprocesses="):
            return int(option.split("=", 1)[1])
    raise AssertionError(
        "this project's addopts no longer cap the worker count, so "
        "`-n auto` resolves to the machine's core count and the lane is "
        "unsafe on any developer machine with more than about eight "
        "usable cores (#537)"
    )


def _nested(tmp_path: Path, *extra: str) -> str:
    """One pytest run whose `auto` answers `FORCED`, and its output.

    Driven as a subprocess rather than through `pytester`, because what
    is under test is this repository's own ini file: `-c` points the
    nested run at it, and a `pytester` session would carry its own.
    """
    (tmp_path / "conftest.py").write_text(
        f"def pytest_xdist_auto_num_workers(config):\n    return {FORCED}\n"
    )
    (tmp_path / "test_one.py").write_text("def test_one():\n    assert True\n")
    finished = subprocess.run(
        [
            sys.executable, "-m", "pytest", str(tmp_path / "test_one.py"),
            "-c", str(PYPROJECT), "-p", "no:cacheprovider",
            "-n", "auto", "--dist", "loadfile", *extra,
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    return finished.stdout + finished.stderr


def test_auto_cannot_resolve_above_the_ceiling(tmp_path: Path) -> None:
    """The point of the file: a machine that would give fourteen gets
    the ceiling instead."""
    ceiling = _ceiling()
    assert f"{ceiling} workers" in _nested(tmp_path), (
        f"a nested run whose `auto` returns {FORCED} did not resolve to "
        f"the {ceiling} this project caps it at"
    )


def test_an_explicit_request_still_wins(tmp_path: Path) -> None:
    """The documented escape hatch, pinned.

    A later `--maxprocesses` beats the one in addopts, which is what
    leaves somebody investigating #537 able to ask for a width the cap
    would otherwise refuse. A change that made the cap absolute would
    pass the test above and break this one.
    """
    wanted = _ceiling() + 4
    assert wanted != FORCED, (
        "the explicit width has to differ from what the nested `auto` "
        "returns, or a run that ignored the flag would pass this"
    )
    assert f"{wanted} workers" in _nested(tmp_path, f"--maxprocesses={wanted}")


@pytest.mark.parametrize("asked", [2])
def test_the_ceiling_does_not_raise_a_smaller_request(
    tmp_path: Path, asked: int
) -> None:
    """A ceiling, not a floor.

    CI resolves four workers and must keep resolving four. This is the
    same shape: an `auto` below the cap passes through untouched, so the
    cap cannot silently widen a lane that asked for less.
    """
    assert f"{asked} workers" in _nested(tmp_path, f"-n{asked}")
