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

**The fixtures open more connections than anyone would guess**:
13,067 across a green run of 7,433 tests, 1.76 each, of which exactly
7,433 are `clear_store`, one per test by construction because the
autouse truncation's condition is deliberately the lane and never the
test. It is not this fault's cause, and reducing it could not fix this
fault, since the limit is on processes rather than on connections.

It is ordinary fixture overhead, which is #489 M2's subject, and it
has been **moved there rather than merely mentioned**: that
milestone's text now carries this baseline and owes an attribution
against it. The baseline had to be taken here because M1 removes the
chance to take it, stopping the pure lane truncating at all across
115 of 217 unit files, so a large share of those 7,433 disappears as
a side effect of the split.

### PR review round

External adversarial review of PR #538's diff, backend codex, model
`gpt-5.6-sol`, 2026-09-20, posted as
[a comment on the PR](https://github.com/rafacm/vinga/pull/538#issuecomment-5749513840).
Four findings, one P1. Verdict: mergeable after the listed fixes. All
four accepted; every one was about the test rather than the change it
guards, which is the right proportion for a milestone whose behavior
is one token.

**1 (P1): the nested run could hide a failure, and could print raw
child output.** The helper ignored `finished.returncode` and fed the
concatenated stdout and stderr into rewritten assertions. Both halves
are real. xdist prints `created: N/N workers` before the first test
executes, so a child that announced eight workers and then failed was
indistinguishable from one that passed; and a mismatch would have had
pytest print a child pytest run's output, which carries this lane's
environment through any traceback in it, where both the auth secret
and the API token live.

*Resolution* (`1215d2df`): the exit status is asserted before the
output is read at all, the worker count is parsed to an integer with
an anchored pattern so that "14 workers" cannot satisfy a test looking
for four, and the refusal is a named sentence that repeats nothing of
the child's output but its exit code.

**2 (P2): the ceiling was not pinned to the measured value.** The
helper read `--maxprocesses` out of the file under test and derived
every expectation from it, so changing the cap to an unmeasured nine
left all three cases green while contradicting the plan and the
changelog.

*Resolution* (`1215d2df`): `MEASURED_CEILING = 8` is a literal in the
test now, with its own case asserting the configuration equals it, and
the resolution cases assert against the literal. The two can fail for
opposite reasons, which is why they are separate: xdist could clamp
perfectly to a number nobody measured. Watched failing: 8 to 9 turns
two cases red where it previously turned none.

**3 (P2): the published claims outran the measurement.** The changelog
fragment said the commands now work "on a developer machine" and
stated the threshold generally, while the plan limits its evidence to
one 14-core darwin machine reaching the compose instance one way.

*Resolution* (`1215d2df`): the fragment now says where it was measured
and states that the number is not claimed elsewhere, and the module
docstring says the same. This is the third time in this issue that a
claim had to be narrowed to its evidence.

**4 (P3): the lower-auto case did not exercise a lower auto.** It
forced the hook to 14 and then passed `-n2`, which replaces the
resolution rather than testing it, so the docstring's claim was
unproven.

*Resolution* (`1215d2df`): the hook answers 2 and the run stays
`-n auto`, so the pass-through is what is measured.
