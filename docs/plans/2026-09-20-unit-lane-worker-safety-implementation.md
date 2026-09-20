# The documented test command works on a developer machine: implementation

Companion to
[`2026-09-20-unit-lane-worker-safety.md`](2026-09-20-unit-lane-worker-safety.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the resolved worker count is bounded

One option, its reasoning, and a test that can see the option
disappear. No fixture changed, no lane conftest was touched, and the
revert is the removal of one token from one list.

### What landed

| Piece | Where |
| --- | --- |
| The cap itself | `vinga-server/pyproject.toml`: `--maxprocesses=8` joins `addopts` beside `--import-mode=importlib` |
| Why, beside it | the same file: the measurement rather than only the number, since the reasoning is what carries to another machine, plus why the cap is repository-wide and why CI is untouched |
| The test | `vinga-server/tests/unit/test_worker_ceiling.py`: three cases over a nested run whose `auto` answers 14 |
| The changelog fragment | `changelog.d/537-unit-lane-worker-bound.md`, `### Fixed` |

### Deviations from the plan

None in what landed. Two things the plan promised are worth confirming
were done rather than assumed: the census ran and was already current,
so no manifest regeneration was needed, and the two command blocks in
`AGENTS.md` and `vinga-server/README.md` were left untouched, which is
the milestone's whole claim about documentation.

### The test, and why it is shaped that way

The obvious test for this is a unit test asserting that `addopts`
contains a string, and it is the wrong test: it pins a spelling and
proves nothing about what pytest does with it. The plan review's
second finding is what produced the right one.

`-n auto` is not resolved from the core count directly. xdist calls
`pytest_xdist_auto_num_workers` and applies `--maxprocesses` to
whatever that hook returns
([`xdist/plugin.py:315`](https://github.com/pytest-dev/pytest-xdist/blob/v3.8.0/src/xdist/plugin.py#L315)).
So a nested run whose own conftest answers that hook with 14 exercises
the ceiling on a machine of any size, which matters because the one
lane that could otherwise never feel this setting vanish is CI, where
`auto` resolves to four with or without it.

The nested run collects a single trivial file in a temporary
directory. That is what keeps it cheap and what keeps it off the
database: nothing under `tests/` is collected, so no lane conftest is
imported and nothing provisions a store. Three cases:

| Case | Property |
| --- | --- |
| `test_auto_cannot_resolve_above_the_ceiling` | an `auto` of 14 resolves to 8 |
| `test_an_explicit_request_still_wins` | a later `--maxprocesses=12` beats the one in addopts |
| `test_the_ceiling_does_not_raise_a_smaller_request` | `-n2` stays 2, so a ceiling cannot widen a lane |

The ceiling is read out of `pyproject.toml` rather than spelled again
in the test, because a second spelling of the number would keep
passing while the real one was gone, which is the failure the file
exists for.

**Watched failing.** With the cap removed from `addopts`, the first
two cases go red and the third stays green, which is right: the third
is about a different property. The whole file runs in 3.90s.

### Verification

| Check | Result |
| --- | --- |
| `uv run pytest tests/unit/test_worker_ceiling.py -q` | 3 passed in 3.90s |
| The same, cap removed | 2 failed, 1 passed, the intended falsification |
| `uv run pytest tests/unit -q -n auto --dist loadfile` | green, 7433 passed, 19 skipped; 8 runs at this width, 7 fully green and one carrying two failures with zero errors, classified in the plan as an ordinary timing flake rather than this fault |
| `uv run pytest tests/integration -q -n auto --dist loadfile` | green, 346 passed, 73.30s |
| `uv run pytest tests/unit/test_command_spellings.py -q` | 52 passed, manifest already current |
| `uv run ruff check .` | recorded on the pull request |

What CI cannot verify is the fix, because CI cannot reproduce the
fault: its `auto` resolves to four with or without the cap. What CI
verifies is that the cap breaks nothing, and that the ceiling test
holds, which is the half that a four-core runner can honestly speak
to.

### Discoveries

**Three hypotheses were measured and killed before this one-line
change was written**, and they are in the plan in full so that nobody
re-derives them. The issue's own force-drop race (17 such terminations
against 667 failures, every one taking the dropping worker's own
leftover backends); a connection-rate knee, which turned out to be an
artifact of sweep points run without cooldowns, each inheriting the
last one's `TIME_WAIT`; and host ephemeral-port exhaustion, which is
real for a sustained storm at the 16,384 ceiling but which the lane
never approaches, peaking at 6,247 and failing anyway.

**The fixtures open more connections than anyone would guess**, about
1.6 per test and 13,067 across a run, because `clear_store` opens a
fresh one per test on top of what each test's own store opens. It is
not this fault's cause and reducing it could not fix this fault, since
the limit is on processes rather than on connections. It is a real
efficiency question and it belongs to #489 M2, the milestone that
re-measures fixture overhead.
