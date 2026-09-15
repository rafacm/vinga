# The integration lane stops being the critical path: implementation

Companion to [`2026-09-15-integration-lane-wall-time.md`](2026-09-15-integration-lane-wall-time.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the integration lane distributes

The workflow's integration step now runs its tests the way the unit
step has run its own since #254. Nothing else about the lane moved: no
test file was touched, no fixture changed, and the revert is still
exactly the removal of two tokens from one line.

### What landed

| Piece | Where |
| --- | --- |
| The change itself | `.github/workflows/vinga-server.yml`: the `Integration tests` step gains ` -n auto --dist loadfile`, the unit step's exact two tokens |
| Why those tokens, beside them | the same file: a comment on the step naming the module-scoped fixtures `loadfile` amortizes (`test_tier_closure.py`'s six throwaway installs, `test_cli_wheel.py`'s wheel, install, directory and server), the local measurement, and where a red lane is graded |
| The two-lane justification, corrected | the same file's `jobs:` header: which lane is longest is a property neither of them owns, with the three measured runs that show it had moved, and the repair stated as running both lanes the same way rather than as moving work between them |
| The integration job's header, corrected | the same file: no longer "the shorter lane". The drift checks and the wheel migration ride here because they are far too cheap to decide either lane's finish (40 seconds of a 10m57s job) and because a drifted document is then reported from one place |
| Both command blocks | `AGENTS.md` and `vinga-server/README.md`: the integration spelling beside the unit one, under a caption covering both lanes, with the serial-by-default note kept |
| The changelog fragment | `changelog.d/491-integration-lane-parallel.md`, `### Changed` |

No test file changed, which is what M1 is.

### Deviations from the plan

Two, both additions rather than departures, and no departure at all.

- **`vinga-server/README.md`'s command block moved with `AGENTS.md`'s.**
  The plan's documentation footprint names only `AGENTS.md`. The README
  carries the same block under the caption "What CI runs the unit lane
  as", put there by #254 in the change that added the `AGENTS.md` line,
  and #254's own changelog entry calls the two "both command blocks".
  The plan's reason for the `AGENTS.md` edit, that the caption is false
  by omission once both lanes run that way, applies to the second block
  word for word, and leaving one of two blocks that must agree is the
  trap the design conventions name. So both moved, and the fragment can
  say "both command blocks" truthfully.
- **The integration step got a comment of its own.** The plan asks for
  two tokens and two corrected comments, not a third comment. But the
  unit step's identical tokens carry twenty lines explaining
  themselves, and after this milestone the integration job's header no
  longer explains the lane's shape at all, so the new tokens would have
  arrived with nothing saying why `loadfile` rather than the default
  distribution, and nothing saying what to do if the lane turns
  intermittently red. Tokens with no explanation beside them are how
  the two stale comments this milestone corrects came to exist. The new
  comment states the amortized fixtures, the local measurement with its
  commit and machine, and the grading order, pointing at the unit
  step's ladder rather than copying it.

### What the verification proved

All local, on the 14-core darwin development machine this plan's tables
were measured on, against a Postgres of this worktree's own (`docker
compose -p wt491m1`, host port 55491) rather than the shared
development instance, on the tree committed as `778fd9ba`:

- `uv run ruff check .`: `All checks passed!`
- `uv run pytest tests/integration -q -n auto --dist loadfile`, which
  is the invocation this milestone puts into CI: **346 passed in
  92.88s**, against the plan's 92.36s for the same spelling at
  `c999d0dc`.
- `uv run pytest tests/integration -q -n 4 --dist loadfile`, CI's
  actual runner width: **346 passed in 164.17s**. The plan measured
  130.66s at that width. The two are not a controlled comparison: the
  plan's figure was taken with the machine to itself, and this one was
  taken on a host also carrying other worktrees' containers and two
  sibling milestone agents. What both runs support is the only claim
  M1 rests on locally, which is that the whole lane passes distributed,
  at two widths, with every test accounted for.
- `uv run pytest tests/unit -q -n 4 --dist loadfile`: **7433 passed,
  19 skipped in 208.02s**. Run at CI's width rather than serially: the
  serial lane was started first and measured at 14% after 13 minutes on
  this machine, projecting to roughly 90 minutes, which is not a price
  worth paying for a milestone that changes no Python at all. The
  distributed spelling is what CI actually runs and is the one that can
  see this change's only possible unit-test effect, which is the
  spellings census below. The serial unit lane is therefore recorded as
  not run.
- `uv run pytest tests/unit/test_command_spellings.py` after the
  documentation edits: **52 passed in 6.33s**, and again after the
  implementation doc and the plan tick were committed, which is the run
  that counts because the census sweeps every tracked file. The
  manifest did not move, so nothing was regenerated and none of this
  milestone's documentation changed the distinct set of classified
  command spellings.

The test count is the thing to read rather than the seconds: 346 serial
and 346 at both widths, so nothing was skipped, deselected or silently
lost by the distribution.

### The CI runs, which are M1's real verification

Two runs, both green in both lanes, recorded with the commit each ran
on because a rerun after a change is a new measurement.

| | before (`c999d0dc`) | [35013431041](https://github.com/rafacm/vinga/actions/runs/35013431041) `pull_request`, `65197b12` | [35013309547](https://github.com/rafacm/vinga/actions/runs/35013309547) `workflow_dispatch`, `37684920` |
| --- | ---: | ---: | ---: |
| `Integration tests` step | 10m17s | **3m20s** | **3m31s** |
| `integration` job | 10m57s | **4m04s** | **4m08s** |
| `Unit tests` step | 8m04s | 7m41s | 8m12s |
| `unit` job | 8m43s | 8m16s | 8m51s |

A third data point exists and is reported for completeness rather than
relied on: run
[35012831765](https://github.com/rafacm/vinga/actions/runs/35012831765)
was cancelled when the census fix superseded it, but its `integration`
job had already finished `success` at 3m57s with a 3m24s step. The
cancellation reached the `unit` job, which was still running at 5m16s.

**The claim M1 rests on holds.** The integration lane is no longer the
critical path: it finishes around 4m against the unit lane's 8m16s to
8m51s, so CI wall time, which is the longer of the two, is now set by
the unit job. The saving in wall time is the roughly two minutes the
plan claimed, and is 2m41s on the pull-request run measured against the
10m57s the integration job took before.

**The plan's prediction was optimistic by about a quarter, and the
reason is worth keeping.** It predicted a step near 2m45s and a job
near 3m20s; the step came in at 3m20s and 3m31s, the job at 4m04s and
4m08s. The prediction scaled the local four-worker result by 1.25x,
which was measured from the SERIAL comparison (CI 10m17s against local
8m15s). The parallel factor is 1.56x (CI 3m20s against local 2m11s),
because the local four-worker run had four workers on a fourteen-core
machine, where each had a real core and headroom, while CI runs four
workers on four cores against everything else on the runner. A scaling
factor measured serially does not transfer to a parallel run, which is
the calibration to carry into #489 and #490, both of which will want to
predict CI numbers from local ones.

### What is not verified, and is not claimed

- **Stability.** Two green runs do not prove a parallel lane stable.
  What they establish is that the lane passes distributed in CI twice,
  on two different commits and two different event types, with all 346
  tests accounted for each time. A case that fails intermittently under
  parallelism would not necessarily have shown itself yet, and the
  workflow's grading ladder (thread-pool caps, then `-n 3`, then `-n 2`,
  then the tokens) is what it is for.
- **The `image` job.** It does not run on a pull request, and in the
  dispatched run it was still going when this section was written. It
  is untouched by this milestone.
- **The `image` job.** Untouched by this milestone and not run locally.
- **The serial unit lane.** Not run to completion, for the reason above.
