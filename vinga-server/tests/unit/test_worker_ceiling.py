"""How many workers `-n auto` is allowed to start, and why there is a
ceiling at all.

`pyproject.toml` caps the resolved worker count, for a reason that has
nothing to do with the tests. Measured for #537 on a 14-core darwin
machine against the compose file's `postgres:17-alpine`: above roughly
eight processes connecting at once, connections from the host to that
instance through its published port start failing, and they fail as
"server closed the connection unexpectedly" at connect time. Hundreds
of tests then report that the database is unreachable while it is open
and serving every other worker.

That is the whole of what was measured, and the number below is not
claimed to be right anywhere else: another host, another container
runtime or another way of reaching the instance may have a different
limit or none. What travels is the shape of the fault, not the eight.

The cap is one token in one list, which is exactly the kind of thing a
later edit removes while tidying, and its absence is invisible
everywhere it matters: CI resolves four workers on a four-core runner,
so the lane that would catch the regression is the one lane that
cannot feel it.

What makes it testable anywhere is that xdist does not read the core
count directly. `-n auto` is resolved through the
`pytest_xdist_auto_num_workers` hook, and `--maxprocesses` is applied
to whatever that hook returns. So a nested run whose own conftest
answers that hook exercises the ceiling on a machine of any size.

The nested run collects one trivial file in a temporary directory,
which is what keeps this cheap and what keeps it off the database:
nothing under `tests/` is collected, so no lane conftest is imported
and nothing provisions a store.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

# The measured ceiling, written here as a literal on purpose. Reading
# it out of the file under test would make this suite agree with
# whatever that file said, so a change to an unmeasured nine would keep
# every case green while contradicting the plan, the changelog and the
# only evidence there is. The configuration is checked against this
# number, not the other way round.
MEASURED_CEILING = 8

PYPROJECT = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"

# What a nested run's `auto` is told to answer when the point is that
# the cap bites: well above the ceiling, so a clamped result cannot be
# the honest core count of any machine this suite plausibly runs on.
ABOVE = 14

# The line xdist prints once it has decided. Captured as a number
# rather than matched as a substring, so that "14 workers" can never
# satisfy a test looking for "4 workers".
_CREATED = re.compile(r"^created: (\d+)/\d+ workers$", re.MULTILINE)

# What a failed nested run is reported with. Its own sentence, and it
# repeats nothing of the child's output: that output is a pytest run's
# stdout, which carries this lane's environment through any traceback
# it happens to print, and both secrets this suite sets live there.
# The exit status is the fact worth having, and it is not a credential.
CHILD_REFUSED = (
    "the nested pytest run this test drives did not pass, so what it "
    "resolved its worker count to says nothing. Its output is not "
    "repeated here, because a child pytest's traceback can carry this "
    "lane's environment, and this lane's environment holds an auth "
    "secret and an API token. Re-run the command this test builds by "
    "hand to see it"
)


def _configured_ceiling() -> int:
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


def _workers_created(tmp_path: Path, auto: int, *extra: str) -> int:
    """How many workers one nested run actually started.

    Driven as a subprocess rather than through `pytester`, because what
    is under test is this repository's own ini file: `-c` points the
    nested run at it, and a `pytester` session would carry its own.

    The child's exit status is checked before its output is read at
    all. Without that, a run that printed the expected header and then
    failed would be indistinguishable from one that passed, and the
    header is printed before the first test executes.
    """
    (tmp_path / "conftest.py").write_text(
        f"def pytest_xdist_auto_num_workers(config):\n    return {auto}\n"
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
    assert finished.returncode == 0, f"{CHILD_REFUSED} (exit {finished.returncode})"
    created = _CREATED.search(finished.stdout)
    assert created is not None, (
        "the nested pytest run started no workers, or stopped announcing "
        "how many it started, so this file can no longer see the ceiling "
        "it exists to hold"
    )
    return int(created.group(1))


def test_the_configuration_carries_the_measured_ceiling() -> None:
    """The number itself, pinned against the evidence rather than
    against the file it is read from.

    Separate from the resolution tests below, because the two can fail
    for opposite reasons: xdist could clamp perfectly to a value nobody
    measured, and this is what says so.
    """
    assert _configured_ceiling() == MEASURED_CEILING, (
        f"the worker cap is not the {MEASURED_CEILING} that #537 "
        f"measured. Any other value needs its own sweep, because the "
        f"evidence behind this one is a single machine and a single "
        f"way of reaching the database"
    )


def test_auto_cannot_resolve_above_the_ceiling(tmp_path: Path) -> None:
    """The point of the file: a machine that would give fourteen gets
    the ceiling instead."""
    assert _workers_created(tmp_path, auto=ABOVE) == MEASURED_CEILING


@pytest.mark.parametrize("auto", [2])
def test_an_auto_below_the_ceiling_passes_through(
    tmp_path: Path, auto: int
) -> None:
    """A ceiling, not a floor.

    CI resolves four workers and must keep resolving four, so the cap
    has to leave a smaller `auto` alone. The resolution is what is
    exercised here: the hook answers below the ceiling and the run is
    still `-n auto`, because passing an explicit `-n2` would replace
    the resolution rather than test it.
    """
    assert _workers_created(tmp_path, auto=auto) == auto


def test_an_explicit_request_still_wins(tmp_path: Path) -> None:
    """The documented escape hatch, pinned.

    A later `--maxprocesses` beats the one in addopts, which is what
    leaves somebody investigating #537 able to ask for a width the cap
    would otherwise refuse. A change that made the cap absolute would
    pass every case above and break this one.
    """
    wanted = MEASURED_CEILING + 4
    assert wanted != ABOVE, (
        "the explicit width has to differ from what the nested `auto` "
        "returns, or a run that ignored the flag would pass this"
    )
    assert _workers_created(tmp_path, ABOVE, f"--maxprocesses={wanted}") == wanted
