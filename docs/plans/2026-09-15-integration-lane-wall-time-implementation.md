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

## M3: the rest of the worklist, attributed and dispositioned

The lane's mock voice now speaks at a rate of its own, set in one place
and reaching every TTS entry the lane writes; the two cases whose
claims were derived from the old rate say what they used to assume; and
the two wedged-collector cases were timed by component before either
was touched, which found the thirty seconds somewhere neither of the
plan's two levers could have reached. No production module changed:
`providers/mock.py` speaks at 40 ms per character for anyone who
configures a mock voice, exactly as it did.

### What landed

| Piece | Where |
| --- | --- |
| The seam | `tests/integration/conftest.py`: `mock_voice(**options)`, returning a fresh entry carrying `LANE_MS_PER_CHAR` with the caller's own options on top |
| The rate, with the measurement that chose it | the same file: `LANE_MS_PER_CHAR = 4.0`, and beside it the playback figures at 40, 8, 4, 2 and the floor's asymptote |
| The voice's floor, once | the same file: `VOICE_MIN_MS = 240.0`, which two cases now derive a duration from instead of spelling it twice |
| The inventory, routed | twenty files, twenty-nine entries, each keeping its own name and its own `tone_hz` (below) |
| The duration window | `tests/integration/test_device_simulator.py`: `EXPECTED_REPLY_S` is `max(VOICE_MIN_MS, LANE_MS_PER_CHAR * len(reply))`, not `40 * len(reply)` |
| The drain's own proof | `tests/integration/test_drain.py`: the sleep is replaced by waiting for the first sentence, and two assertions a late drain cannot satisfy |
| The held export, answered | `tests/integration/test_telemetry_hardening.py`: `Withholding.answer()`, used by the teardown after every assertion has been made |
| The reply bound, from the measured reply | the same file: `REPLY_BOUND_S` 3.0 to 0.5, with the 0.4 ms it stands over written down |

Design footprint: one seam, a builder in the lane's own conftest, which
is where this lane already puts what two or more modules need. It
passes the deletion test in the direction that matters: inlined, its
twenty-nine callers would each carry the rate, and the rate would stop
being one fact.

### The inventory, by grep rather than from memory

Twenty-nine TTS entries in twenty files, all of them now built by
`mock_voice`:

| Shape | Files | Entries |
| --- | --- | ---: |
| A four-stage `MOCK_PROVIDERS` comprehension, with `tts` split out of it | `test_access_logs.py`, `test_activation.py`, `test_capture_upload.py`, `test_device_bindings.py`, `test_device_simulator.py`, `test_ota_endpoint.py`, `test_telemetry_export.py`, `test_wire_latency_capture.py`, `test_ws_auth.py` | 9 |
| An entry written inline in a config the file builds | `test_agent_guidance.py` (4), `test_tools.py` (3), `test_conversations.py`, `test_drain.py`, `test_mcp_reload.py`, `test_cli_simulator.py` | 11 |
| A named voice carrying a `tone_hz` or a name a case asserts on | `test_tools.py` (`tenor`, `alto`), `test_transcript_export.py` (`tenor`, `alto`), `test_two_personas.py` (`tenor`, `alto`), `test_llm_input_export.py` (`tenor`), `test_cli_live.py` (`voice`), `test_cli_wheel.py` (`voice`) | 9 |

This is why the plan's second review round was right to refuse a shared
`MOCK_PROVIDERS` block. Nine of the twenty-nine entries are named
voices, seven of them carry a `tone_hz`, and four of those are read
back out of the received audio by `dominant_hz`; eleven more are
written inline in a config the file builds rather than in any shared
block, and three of the files that do that are the ones the whole
attribution is about.

Three TTS entries in the lane are deliberately NOT routed, and the
reason is the same in each: nothing speaks.

- `test_config_api.py:30`, the `tts` row of `PIPELINE`. A request body
  in the write order a first deployment sends over the configuration
  API. No conversation is held and no audio is synthesized.
- `test_startup_failure.py:112`, a loop over every stage seeding a
  domain for a boot that is expected to refuse.
- `test_reach_upgrade.py:339`, a provider write the case expects to be
  refused.

`tests/support/configs.py` is untouched, per the plan: 79 unit files
import it, and some of them want the long reply on purpose
(`LONG_REPLY` is named for the eight seconds it takes).

### The rate, and why four

The A/B in the plan varied `ms_per_char` and measured the effect. What
settled the value is a second measurement, which the plan named as what
the stronger claim would need and said nothing depended on: the length
of every sentence the three files actually have spoken, recorded once,
then costed at each candidate rate. The voice's duration is
`max(min_ms, ms_per_char * len(text))`, so one run's sentence lengths
give the exact playback total for any rate, with no run-to-run noise in
it at all.

Those three files speak **128 sentences, 5,655 characters**, the
longest 273 and the median 33.

| `ms_per_char` | Audio emitted | Sentences at the 240 ms floor |
| ---: | ---: | ---: |
| 40 (shipped) | 227.20s | 17 / 128 |
| 16 | 94.26s | 35 / 128 |
| 8 | 52.67s | 58 / 128 |
| **4** | **34.50s** | **81 / 128** |
| 2 | 31.14s | 126 / 128 |
| 1 | 30.75s | 127 / 128 |
| the asymptote | 30.72s | 128 / 128 |

**Four, for two reasons the table makes visible.** The floor is
30.72s, which is those 128 sentences at 240 ms each, and no rate can go
below it: four is within 3.78s of it, so every smaller rate together is
worth the last 1.7% of what 40 cost. And four is the last rate at which
the voice still does what its docstring says it does, since 47 of the
128 sentences are still longer than the floor there, against 2 at a
rate of 2 and 1 at a rate of 1.

The wall-clock sweep agrees and cannot separate the small values, which
is the other half of the argument. Six files (the three worklist ones
plus the three that carry claims at risk), same machine, same database,
one pass each:

| `ms_per_char` | The six files |
| ---: | ---: |
| 8 | 84.06s |
| **4** | **76.87s** |
| 2 | 77.51s |
| 1 | 74.44s |

Two and four are within a second of each other in the wrong direction,
and one is 2.4s under four, against a 3.78s playback difference that is
the most any of them could have been worth. Every one of these values
passes every check; the choice is therefore made on the playback table,
where the numbers are exact, and not on this one.

**What the audio measurement adds to the plan's A/B.** The plan was
careful to say the A/B attributes 56% of those files to the mock
voice's duration setting with paced playback as the principal
demonstrated mechanism, and that it does not partition the delta. The
emitted audio is now measured directly: 227.20s at 40 against 34.50s at
4, a difference of 192.70s. The three files' wall time fell by 95.77s
over the same change, which is half of that, and the gap is not a
contradiction: several of these cases hold two conversations at once
(two personas, three agents on one entry), so audio the voice emits is
not audio the lane waits through one second at a time. The honest
statement is that the emitted audio fell by 193s and the wall time by
95s, and that the first is the mechanism of the second rather than its
measure.

### The three files, before and after

Same instrument as the plan's tables, `uv run pytest ... -q
--durations=0` run serially, on the 14-core darwin development machine,
against a Postgres of this worktree's own (`docker compose -p wt491m3`,
host port 55493).

| File | before, at `705d9af1` | after, at `6e6976a2` |
| --- | ---: | ---: |
| `test_agent_guidance.py` | 58.29s | **25.10s** |
| `test_tools.py` | 63.18s | **24.68s** |
| `test_conversations.py` | 40.33s | **18.14s** |
| the three together, pytest's own wall time | **163.95s** | **68.18s** |

The plan measured 163.98s for the same three files at `c999d0dc`, so
the before number reproduces to three hundredths of a second three
commits later.

### The claims that had to survive, each checked

- **`test_device_simulator.py`'s duration window.** It asserted
  `EXPECTED_REPLY_S / 2 <= duration_s <= EXPECTED_REPLY_S * 3` with
  `EXPECTED_REPLY_S` derived from a hardcoded 40, which at the lane's
  rate would have put the window's floor above the reply. Derived
  rather than overridden, which is the option the plan preferred: the
  expectation is now `max(VOICE_MIN_MS, LANE_MS_PER_CHAR * len(reply))`,
  both numbers read from the lane's own conftest. For "You said hello."
  at four that is the floor, 0.24s, and the window is 0.12s to 0.72s,
  which the decoded audio lands inside: the case is green and the
  assertion still bounds the reply on both sides. A 40 ms override was not kept, because the
  derivation holds the window and an override would have left this one
  file disagreeing with the lane about what its voice does.
- **`test_drain.py` landing mid-reply.** This is the one the plan
  called out as able to keep passing while testing nothing, and the
  measurement says the danger was not where it looked: every one of
  this reply's five sentences is under sixty characters, so all five
  cost the 240 ms floor at the lane's rate and at the shipped one
  alike, and the reply is 1.2s either way. The sleep was replaced
  anyway, because it was a hope rather than a claim. See below.
- **`dominant_hz` inside 20 Hz.** Confirmed by running
  `test_tools.py` and `test_two_personas.py` rather than by arithmetic,
  and the arithmetic says why it was never close: the floor makes every
  sentence at least 240 ms, which is 3,840 samples at the 16 kHz
  analysis rate and a resolution of 4.2 Hz, against the roughly 800
  samples 20 Hz needs. `audio.size > 0` likewise.
- **`spoken(events)`** reads `tts sentence_start` text, which no rate
  changes.
- **`test_the_utterance_is_paced_rather_than_burst`** asserts on
  recorded sleep calls for the simulator's OUTGOING utterance
  (`said = utterance.packaged()`), so it is untouched, as the plan said.

### The drain, falsified rather than argued

The case now waits for the server to start speaking the first sentence
instead of sleeping 0.05s, and then asserts two things a drain arriving
after the reply cannot satisfy: that the other four sentences arrived
after the drain was called, and that the drain itself took longer than
one sentence of speech.

The drill ran both shapes against the same server, in a scratch file
that was deleted afterwards:

| | sentences before the drain | sentences after it | the drain took |
| --- | --- | --- | ---: |
| the shape that ships | `['One.']` | `['Two.', 'Three.', 'Four.', 'Five.']` | 1.144s |
| a drain deliberately arriving late | all five | none | 0.001s |

The assertion the case had before this milestone, that the whole reply
was spoken, passes in BOTH rows. That is the point: it is satisfied by
a reply nobody interrupted. The two new ones fail in the second row,
which is what makes them a claim about draining.

### The two wedged-collector cases, timed separately

Timed by component before either was touched, with `time.monotonic()`
marks around each piece, in a scratch file that copied the case bodies
verbatim and was deleted afterwards. The plan's first draft treated
these as one case at 30.02s; they are two, and the 30 seconds belongs
entirely to one of them.

**`test_a_collector_that_never_answers_costs_no_reply_anything`**, the
one that replaces the exporter object: **0.07s, all of it.**

| Component | |
| --- | ---: |
| `build_telemetry` | 0.002s |
| the session, tapped | 0.006s |
| each of the twelve turns | 0.001s |
| teardown | 0.001s |

Nothing to reduce and nothing reduced. It closes **measured-and-kept**,
and the two things the plan would have wanted proved before touching
`TURNS` are recorded instead as the reasons for leaving it alone: the
exporter took exactly `QUEUE + 1` = 5 batches, which is the saturation
the case asserts, and `collector.entered` was set on every turn. Both
held identically on each of eight runs.

**`test_a_collector_that_answers_nothing_costs_no_reply_anything`**,
the one that keeps the real OTLP transport: **30.46s, of which 30.01s
was the teardown.**

| Component | before | after |
| --- | ---: | ---: |
| `Withholding()` | 0.000s | 0.000s |
| `build_telemetry` | 0.001s | |
| the session, tapped | 0.006s | |
| the preliminary turn | 0.002s | |
| `collector.entered.wait(15.0)` | 0.002s | |
| each of the twelve measured turns | 0.001s | |
| teardown: `collector.close()` | 0.000s | |
| teardown: `telemetry.shutdown()` | 5.006s | |
| teardown: `telemetry.release` | 25.002s | |
| **the whole case** | **30.46s** | **0.10s** |

**Both of the plan's levers are dead here, and the measurement is what
says so.** Per-reply speech is worth nothing: this case drives its
session below the wire onto a `RecordingSocket`, so there is no pacer
and a whole reply takes under a millisecond. `TURNS` is worth nothing
for the same reason: twelve turns are 0.012s of a 30.46s case.

What the teardown was actually waiting for is the collector's own
choice of how to stop. Hanging up on an outstanding OTLP request is a
retryable failure, so the exporter backed off against work nothing was
ever going to read: `shutdown()` spent its whole `SHUTDOWN_TIMEOUT_S`
of 5s, and the unbounded `release` that follows it spent the abandoned
export's own 25s afterwards. The collector now **answers** that request,
with the smallest response an OTLP exporter reads as a success, and
goes on answering until the endpoint is shut last.

Every assertion in the case is made before the teardown runs, so what
the exporter met for the whole of the measured part is still a
collector that answers nothing. The preconditions were checked at the
new shape rather than assumed: `collector.outstanding` was 1 on every
one of the twelve turns, on each of eight runs.

`TURNS` and `QUEUE` are therefore unchanged in both cases, and the
milestone owes no observable for a reduction it did not make.

`REPLY_BOUND_S` moves, 3.0 to 0.5. Its comment said it was generous by
an order of magnitude against the healthy reply; the healthy reply is
0.7 ms in the first case and 0.4 ms in the second, worst of twelve over
eight runs each, so it was generous by three orders. Half a second is
still roughly seven hundred times the measured reply, which leaves a
four-core runner carrying four test workers room to be slow without
being wrong, and is far below the five seconds the shortest wait on
this path would cost.

`test_the_shutdown_of_a_wedged_exporter_is_bounded` is untouched at
5.00s. It spends `SHUTDOWN_TIMEOUT_S` on purpose and measures it rather
than asserting about the constant, which is its whole claim. **Kept, on
its own evidence.**

The file: **35.44s to 5.76s.**

### Deviations from the plan

Two, both forced by measurements the plan asked for and could not have
had.

- **The wedged-collector reduction came from neither of the plan's two
  levers.** The plan named per-reply speech and `TURNS`, on the
  reasoning that the case's scripted reply is "about 1 s of audio at
  the shipped default" and that the rest was unattributed. The
  component timing says all twelve replies together are 0.012s and the
  teardown is 30.01s, so both named levers are worth nothing here. The
  plan's instruction that governs is the one above them, to time each
  case by component and then reduce whatever dominates; what dominates
  is how the collector stops, and that is what was changed. The plan's
  own levers were left exactly where they were, which is why this
  milestone states no observable for a `TURNS` reduction: there is none.
- **`test_drain.py`'s speech was never at risk.** The plan's second
  review round found that a shorter reply could leave the drain landing
  after it, and that the case would keep passing. Measured, every one
  of that reply's five sentences is already under the voice's floor at
  the shipped rate, so the reply is 1.2s at 40 ms per character and 1.2s
  at 4. The sleep was replaced anyway, because "it happens to be long
  enough today" is what the finding was really about.

One addition rather than a departure: the **emitted audio duration was
measured directly**, which the plan named as what a stronger claim
would need and said nothing depended on. It is what chose the rate, so
in the end something did.

### What the verification proved

All local, at `6e6976a2`, on the machine and against the database named
above:

- `uv run ruff check .`: `All checks passed!`
- `uv run pytest tests/integration -q -n 4 --dist loadfile`, CI's
  runner width: **346 passed in 88.53s**, against M2's 130.22s at the
  same width on this machine. The count is the thing to read: the same
  346 as M1, M2 and the plan's table, so nothing was skipped or lost.
- The three worklist files, serial: **23 passed in 68.18s**, against
  163.95s before, the same 23 tests.
- `test_device_simulator.py`, `test_drain.py`, `test_tools.py`,
  `test_two_personas.py`, the four carrying the claims at risk: **19
  passed in 33.32s**, run together and serially.
- `tests/integration/test_telemetry_hardening.py`: **4 passed in
  5.76s**, against 35.75s of summed durations before.
- `uv run pytest tests/unit/test_command_spellings.py`, run after this
  section and the plan's tick were written, which is the run that
  counts because the census sweeps every tracked file: **52 passed in
  6.18s**. The manifest did not move, so nothing was regenerated and
  none of this milestone's documentation changed the distinct set of
  classified command spellings.
- `scripts/check_doc_links.py .`: **checked 249 files, 0 failures**.

### What is not verified, and is not claimed

- **CI.** Every number here is from a 14-core darwin machine with
  sibling worktrees on it. This milestone's CI evidence is the pull
  request's own run, which has not happened as this section is written.
- **Stability.** One pass of the lane at four workers is not a
  stability proof, and `REPLY_BOUND_S` at 0.5s has not met a loaded
  four-core runner. What justifies it is the margin rather than a run:
  seven hundred times the measured reply, against a failure mode that
  costs seconds.
- **The unit lane.** Untouched by this milestone, which changes no
  module the unit lane imports: `tests/support/configs.py` is
  deliberately outside the seam and `providers/mock.py` is unchanged.
- **The `image` job.** Untouched and not run.

### The changelog fragment, and why there is none

M3 writes no fragment, which is what the plan's documentation footprint
allows for it: one only if a case's shape actually changes in a way
somebody outside the repository could see. Nothing observable did. No
command moved, no configuration key moved, no product behavior moved,
and the mock voice a person gets when they configure one still speaks
at 40 ms per character. What changed is how fast this repository's own
test lane talks to itself. The lane's speed is already the subject of
M1's `### Changed` entry, which is where a reader looking for it will
be.
