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

## M2: the tier-closure floor

`test_tier_closure.py` is the integration lane's longest file, and
under `--dist loadfile` no file is split, so it is the floor the lane
cannot finish inside however wide the runner gets. Two of its cases
spawned one subprocess per row of the registration table and waited for
each before starting the next. They now run four at a time. Nothing
else about the file moved, and no production module was touched.

### What landed

| Piece | Where |
| --- | --- |
| The pool | `tests/integration/test_tier_closure.py`: `_ran_concurrently`, a `ThreadPoolExecutor` over the existing `_ran`, which is unchanged because the work it does is blocking in `subprocess.run` |
| The width, as a number with its reasoning beside it | the same file: `POOL_WIDTH = 4`, with the comment saying why it is bounded, why there is exactly one pool in a `loadfile` run, and that it was settled against the lane rather than against the file |
| The two pooled cases | the same file: `test_every_ungated_command_has_a_help_page_from_the_client_install` and `test_the_gated_commands_refuse_from_the_client_install`, each submitting its whole half and then asserting per row |
| One home for the split | the same file: `UNGATED`, derived as the table minus `GATED` rather than listed, so the two halves cannot come to disagree about which rows either covers |
| The inventory pin | the same file: `test_the_gated_set_is_what_the_table_says_it_is` now also asserts `set(UNGATED) \| GATED == set(table)` and that the two halves neither overlap nor repeat a row |
| The claim restated where it is made | the same file's module docstring: both sides are run as subprocesses "a bounded few at a time rather than one after another: the fresh interpreter per command is the claim, and its turn in a queue never was" |

Design footprint: a file-local helper and one constant, deliberately
not a module. The helper has two callers in one file and hides the pool
from both; inlined into either, the caller would grow a
`ThreadPoolExecutor` and an ordering argument it does not want to make
twice.

### The width, measured

The plan required widths 2, 4 and 8, measured both for the file alone
and for the whole lane at `-n 4 --dist loadfile`, with the LANE as the
thing minimized. Width 1 was added as this machine's serial control,
since the plan's 83.37s was taken on an idle machine at `c999d0dc` and
a claim about movement needs both ends measured on the same host.

All on the 14-core darwin development machine, against a Postgres of
this worktree's own (`docker compose -p wt491m2`, host port 55492),
with the `uv` build cache cleaned first, on the tree committed as
`2245c503`. The file column is the summed durations of every phase,
which is the instrument the plan's per-file table uses; the lane column
is pytest's own wall time, run twice per candidate width.

| Pool width | The file, summed durations | The lane, run 1 | The lane, run 2 |
| ---: | ---: | ---: | ---: |
| 1 (serial control) | 83.37s | 167.19s | not run |
| 2 | 72.29s | 138.19s | 138.52s |
| 4 | **68.33s** | **130.22s** | **130.10s** |
| 8 | 65.95s | 131.15s | 131.34s |

**Four, and the reason is the thing a file-only measurement cannot
see.** Eight is the fastest file and not the fastest lane. Under
`loadfile` this file sits on exactly one xdist worker, so there is one
pool in the whole run and it bids against the lane's other three
workers for the same cores; past the core count it buys its own file
seconds with theirs. The two lane passes separate 4 from 8 by about a
second and agree with each other to within 0.25s, which is small but
consistent in direction, and 2 is a clear 8s worse than both.

The width-1 control landed on 83.37s summed, the same number to the
hundredth as the plan's serial figure at `c999d0dc`. That is a
coincidence of two totals rather than a reproduction: within it, the
help case measured 22.35s here against the plan's 25.31s.

### The claim, against the arithmetic

The plan's formula is `83.37 - 25.31 + 25.31/w` plus pool overhead,
giving 64.4s at width four. Re-derived from this machine's own serial
run, where the two pooled cases are 22.35s and 1.16s rather than 25.31s
and unmeasured, it predicts `83.37 - 23.51 + 23.51/4` = **65.7s**, and
the measurement is **68.33s**.

Where the 2.6s went, from the per-case durations rather than from
supposition: 0.8s is the pool's own overhead on the help case (6.37s
against the 5.59s a perfect quarter would be) and 0.2s on the gated
case, and the remaining 1.6s is drift in the ~60s of `uv sync`
environment builds that are the rest of the file, which vary by more
than that between runs. So the file moves **83.37s to 68.33s**, an 18%
cut, against a predicted 21%, and the gap is overhead plus build noise
rather than a structural surprise.

At the lane level that is **167.19s to 130.22s**, but almost all of
that is the arithmetic of a bin-packing problem rather than this
milestone's doing: the serial-control lane run is the same lane with
this file 15s longer, and a 37s lane difference from a 15s file
difference is what happens when the longest file stops being the bin
that everything else waits on.

### Deviations from the plan

One, and it is an addition rather than a departure.

- **Width 1 was measured as well as 2, 4 and 8.** The plan names three
  widths. Without a serial number from this machine there is nothing to
  state the movement against except a figure taken on a different day
  with the machine to itself, and the milestone's whole claim is a
  movement. Width 1 is the pooled code with the pool degenerate rather
  than the pre-change loop, which is the better control anyway: it
  holds everything except the concurrency fixed.

No other departure. The falsification took the shape the plan's second
review round specified, the width was settled against the lane, the
inventory is pinned as sets rather than as a count, and `_ran` is
unchanged.

### The falsification drill

The regression this change could introduce is a pool that swallows
which row failed, and a green run does not distinguish that from a
working one. So the fault was injected at the pooling boundary, per the
plan: `_ran` was wrapped for the duration of the drill so that one
chosen `argv` came back with return code 3 and a recognizable stderr
while every other row ran for real.

Three runs, because one would have shown that a failure names *a* row
and not that it names *the* row:

| The injected row | What the failure said |
| --- | --- |
| `("device", "relocate")`, index 31 of 62 ungated | `AssertionError: (('device', 'relocate'), 'DRILL-6f3a: this one row was made to fail')` |
| `("device", "clear-location")`, elsewhere in the same half | `AssertionError: (('device', 'clear-location'), 'DRILL-6f3a: this one row was made to fail')` |
| `("ota-url",)`, the gated half | `AssertionError: (('ota-url',), '', 'DRILL-6f3a: this one row was made to fail')` |

The reported row moved with the injected one rather than staying put,
which is what separates working attribution from a coincidence, and the
gated half was drilled too because leaving one of two identical cases
unfalsified is the same trap as leaving one of them serial.

The drill edits a tracked file, so it was undone by AGENTS.md's restore
rule and not by `git checkout`: the original bytes were copied aside
before the first injection, copied back afterwards, the file `touch`ed
so a restored mtime could not land on the second a `.pyc` was compiled
on, and the tree's `__pycache__` directories removed. `git diff` after
the restore showed the milestone's 79 insertions and nothing of the
drill, and the file was rerun green before it was committed.

### What the verification proved

All local, on the machine and against the database named above, at
`2245c503`:

- `uv run ruff check .`: `All checks passed!`
- `uv run pytest tests/integration/test_tier_closure.py -q`: **43
  passed in 68.02s**, on the restored tree after the drill. The same 43
  tests as before the change, at every width measured.
- `uv run pytest tests/integration -q -n 4 --dist loadfile`, the
  invocation the width decision optimizes: **346 passed in 130.22s**
  and **346 passed in 130.10s**. The same 346 as M1's runs and as the
  plan's table, so nothing was skipped, deselected or lost.
- `uv cache clean vinga-server` was run before the measurements, per
  AGENTS.md, so none of them is a stale-build result. The trap did not
  fire during this milestone.

The test count is again the thing to read: 43 in the file and 346 in
the lane, unchanged across four pool widths and two lane passes.

### What is not verified, and is not claimed

- **CI.** Every number here is from a 14-core darwin machine. The
  runner has four cores, the pool competes with three other xdist
  workers there rather than with a machine's worth of spare capacity,
  and the width that wins here is not thereby the width that wins
  there. This milestone's CI evidence is the pull request's own run,
  which has not happened at the time this section is written, and no CI
  wall-time figure is claimed from it in advance.
- **The lane numbers are not a controlled comparison with the plan's.**
  The plan measured 130.66s at four workers with the machine to itself;
  these runs shared the host with sibling milestone agents and other
  worktrees' containers. That the two agree closely is luck as much as
  anything, and the claim rests on the within-session comparison across
  widths, which was taken under the same conditions.
- **Stability.** Two lane passes per width is enough to separate 4 from
  2 and not enough to call the lane stable under a pool.
- **The `image` job and the unit lane.** Untouched by this milestone.
  `tests/unit/test_command_spellings.py` was run because this milestone
  edits documents, and is reported with the documentation commit.

### What the review round changed

One P2, from codex/terra on PR #534, and it found a real hazard the
milestone's own falsification could not have: the drill proves a
failure names its row, and says nothing about how long the failure
takes to arrive.

The first shape was `pool.map` inside a `with ThreadPoolExecutor(...)`.
Three facts combine badly there. `ran` gives every command
`COMMAND_SECONDS`, which is 120, and raises when it expires; the map
submits the whole inventory at once rather than lazily; and leaving the
`with` block shuts the pool down without cancelling, so it waits for
rows that never started. A systemic hang therefore cost a deadline per
row per worker, which for sixty-two rows over four workers is roughly
half an hour, on a lane whose whole budget is now minutes. One red
command would have read as a wedged runner.

The rows are now submitted explicitly, collected in order through
`future.result()`, and the pool shut down with `cancel_futures=True` in
a `finally`. Ordered collection is kept deliberately, because it is what
lets a failure name its row.

The worst case is stated as two deadlines rather than one, and the two
is measured rather than reasoned to. On a stand-in with the deadline's
shape (raise on the first row, sleep on the rest, sixty-two rows, four
workers), cancelling started 8 rows in 1.01s and not cancelling started
all 62 in 8.05s. Eight is two waves, because the workers pick up a fresh
row between the deadlines expiring together and the shutdown reaching
them, and the docstring says so rather than claiming the tidier number.

The falsification drill was re-run once against the rewritten
collection, same boundary injection and same restore discipline: a
failing `("device", "relocate")` produced
`AssertionError: (('device', 'relocate'), 'DRILL-6f3a: this one row was
made to fail')`, so attribution survives. `uv run ruff check .` passed
and `uv run pytest tests/integration/test_tier_closure.py -q` gave **43
passed in 67.66s**, against 68.02s before the change, so the
cancellation costs nothing on a green run. The widths were not
re-measured: what changed is the failure path, and the numbers above
were all taken on runs where nothing failed.

### The changelog fragment, and why there is none

M2 writes no fragment, which is what the plan's documentation footprint
says for it. Nothing observable changed: no command moved, no product
behavior moved, no configuration key moved, and the CLI's registration
table is the same 65 rows it was. What changed is the order in which
one test file starts 65 subprocesses it already started. The changelog
records notable changes for the person running vinga, and a reader of
it would learn nothing true about their deployment from this one. The
lane's own speed is already the subject of M1's `### Changed` entry,
which is where a reader looking for it will be.
