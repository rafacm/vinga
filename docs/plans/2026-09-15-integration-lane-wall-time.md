# The integration lane stops being the critical path

Plan for [#491](https://github.com/rafacm/vinga/issues/491). Its
companion is
`docs/plans/2026-09-15-integration-lane-wall-time-implementation.md`,
one section per milestone, appended in the same change that ticks the
milestone.

**Local baseline:** not applicable. Nothing here changes a
conversational capability. The whole change is how the test lanes are
run and how five test cases spend their seconds; a deployment reaches
none of it.

## The measurement this plan starts from

Taken at `c999d0dc`, on a 14-core darwin development machine, against
the Postgres the compose file starts, with the `uv` build cache cleaned
first (`uv cache clean vinga-server`, the trap `AGENTS.md` records:
without it the tier-closure cases fail wearing a database's error
message). The instrument is `uv run pytest tests/integration` with the
distribution tokens varied and nothing else:

| Invocation | Wall time | Result |
| --- | ---: | --- |
| `-q --durations=0` (serial, **what CI runs**) | **495.34s** | 346 passed |
| `-q -n 4 --dist loadfile` (CI's runner width) | **130.66s** | 346 passed |
| `-q -n auto --dist loadfile` (14 workers) | **92.36s** | 346 passed |

Per-file totals from the serial run, every phase summed, the six that
matter:

| File | Serial total |
| --- | ---: |
| `test_tier_closure.py` | 83.37s |
| `test_tools.py` | 62.44s |
| `test_agent_guidance.py` | 57.00s |
| `test_conversations.py` | 41.19s |
| `test_cli_wheel.py` | 37.03s |
| `test_telemetry_hardening.py` | 35.44s |

The issue's worklist reproduces, with the same cases in nearly the same
order as the review's CI sample: the wedged-collector case at 30.02s,
the help-page case at 25.31s, the one-session-across-a-reload case at
23.01s, the restricted-agent case at 20.37s, and the conversation-notes
case at 16.06s.

**What the review could not have seen**, because it read durations
rather than the workflow: the two lanes are not run the same way.

```
.github/workflows/vinga-server.yml:468   pytest tests/unit -v --durations=25 -n auto --dist loadfile
.github/workflows/vinga-server.yml:551   pytest tests/integration -v --durations=25
```

The integration lane is serial in CI and the unit lane is not. That is
the whole of why the integration job is the critical path, and it is
not a property of the tests.

### How the asymmetry got there, and why nothing is wrong with the tree

It was deliberate once and correct once.
[`9a4b1359`](https://github.com/rafacm/vinga/commit/9a4b135992e38b21d379bb10ace3b0edcfaa8870)
(2026-08-23, #254) put the unit lane under xdist because the unit lane
was then the critical path: "6m31s at its last measurement, against
roughly five minutes for the integration lane that runs beside it."
The changelog entry for that change records the consequence in the
same sentence that claims the win: it left "the critical path on the
integration lane, which now finishes last at 4m54s".

Three weeks later the order has not changed but the numbers have.
Measured from the GitHub API on the three most recent workflow runs at
the time of writing, job start to job completion:

| Run | unit | integration |
| --- | ---: | ---: |
| [34966200567](https://github.com/rafacm/vinga/actions/runs/34966200567) (`main`) | 8m43s | **10m57s** |
| [34965123991](https://github.com/rafacm/vinga/actions/runs/34965123991) | 8m58s | **10m56s** |
| [34935863342](https://github.com/rafacm/vinga/actions/runs/34935863342) | 8m57s | **10m36s** |

CI wall time is `max(unit, integration)`, so every run in this
repository, and every one of the roughly twenty pull requests the rest
of the architecture batch will open, waits on the lane nobody ever
distributed.

The step inside the job is almost the whole of it: on run
`34966200567` the "Integration tests" step ran 10m17s of the job's
10m57s, against 8m04s for "Unit tests". CI is therefore about 1.25x
slower than the machine this plan's local table was measured on
(10m17s against 8m15s for the same serial invocation), which is the
factor M1's prediction below is scaled by.

**What M1 is predicted to do, stated before it is done so the CI run
can falsify it.** Scaling the local four-worker result by that 1.25x
puts the integration step near 2m45s and the job near 3m20s. The
integration job then stops being the critical path and the unit job's
8m43s becomes it, so the saving in CI **wall** time is the roughly two
minutes by which integration currently exceeds unit, while the saving
in billed runner time is the full seven and a half minutes. Two
minutes a run is the smaller number and the honest one to claim.

This is also precisely what makes #489 worth doing after this and not
before: #489 shortens the unit lane, and until the integration lane
falls below it, a shorter unit lane buys no wall time at all.

Two comments in the workflow still describe the 2026-08-23 world and
are now false. `L97-L100` says "the unit tests are by far the longest
single item, and the integration tests fit entirely inside them".
`L470-L472` calls the integration job "the shorter lane" and says it
"finishes well before the other one", which is the stated reason the
drift checks and the wheel migration ride there. Both are corrected by
M1, because a stale justification is how the next session re-derives
the wrong thing.

## What is settled and not re-litigated

From the issue, and not reopened here:

- **Behavioral coverage is the invariant.** Every claim these tests
  make survives the change, and a case whose speed cannot be improved
  without weakening its claim **closes as measured-and-kept**, which
  the issue names as a valid outcome and this plan expects to use.
- **Attribution before change**, per case: what the seconds are
  actually spent on, then the cheapest change that preserves the claim.
- **Repeated process startup is amortized where the cold start is not
  itself the claim**; a real timeout is replaced by synchronization on
  the event it guards only where that preserves the claim, and a case
  whose claim is genuinely about elapsed real time moves to a small,
  named real-time suite instead, so the honest slow tests are few and
  deliberate rather than scattered.
- **Independent integration tests partition across workers with
  isolated databases**, which is the third bullet of the issue's own
  rule and is what M1 turns on.

Out of scope, with the issue's own pointers: unit-lane fixture overhead
is #489 M2, image-job and main-queue time is #490, growing what
integration covers is #305.

## Open questions, resolved

### The first lever is the workflow line, not the test bodies

The issue is written as a worklist of five slow cases, and its title
says the cases stop waiting on real time. The measurement says the
cases are the second lever and a smaller one.

Serial, the lane is 495.34s. At CI's four-worker width it is 130.66s,
for the same tests, the same claims and the same assertions. That is
365 seconds a run, on the job that sets the critical path, bought by
adding two tokens to one line. The entire worklist, if every case on
it were reduced to zero, is 115 seconds of serial time, and after the
lane distributes it is worth less than that, because what the five
cases cost is spread across workers.

So M1 is the lane, and it lands alone and first. The worklist is real
and M2 and M3 do it, with honest expectations attached.

### `-n auto --dist loadfile`, the unit lane's exact tokens

Not a different width and not a different distribution, for three
reasons.

`loadfile` keeps a file's tests on one worker, which is what this
lane's expensive fixtures assume. `test_tier_closure.py` builds six
throwaway installs in module-scoped fixtures (`client_env`, `serve_env`,
`sim_env`, `otel_env`, `langfuse_env`, `serve_otel_env`), and
`test_cli_wheel.py` builds a wheel, installs it, prepares a directory
outside the checkout and boots a server, all four module-scoped
(`wheel`, `installed`, `elsewhere`, `live`). Under `--dist load` those
fixtures would be rebuilt on every worker that received one of their
tests, and the lane would get slower rather than faster. Intra-file
order also stays exactly what it is, which is the property that makes
this change reviewable at all.

The two Docker-backed telemetry files are **not** an example of this.
`jaeger` in `test_telemetry_export.py` is a default function-scoped
fixture and `_collector` in `test_telemetry_fanout.py` is a context
manager used by its single test, so neither would be duplicated by a
different distributor. They matter to the shared-resource audit below,
which is a separate question, and citing them here would have been a
reason that does not hold.

`auto` rather than `4` so a runner resize is picked up without a second
edit, which is the reasoning `9a4b1359` recorded for the unit lane.

And the same two tokens in both places because two structures that must
agree are one structure with a bug pending. After M1 there is one way
this repository runs a pytest lane in CI, and the revert is still
exactly the removal of two tokens from one line.

### The lane is already built for this, and that is the evidence, not the hope

`tests/conftest.py` reads `PYTEST_XDIST_WORKER` (`L232`), derives a
per-worker `LANE_DATABASE` from it, clones each worker's database from
one migrated template, and serializes provisioning on a session-level
advisory lock chosen because `CREATE DATABASE` cannot run inside a
transaction. The integration `conftest.py` calls `provision_stores()`
at import for exactly this reason. The machinery was written for
parallel workers; CI is the one place it was never given any.

Three shared resources were checked rather than assumed, because "the
tests are independent" is the claim that is cheap to make and expensive
to be wrong about:

- **Ports.** No integration test binds a fixed port. Servers are
  `uvicorn.Config(..., port=0)` and the chosen port is read back off
  the socket (`_serving`, integration `conftest.py`).
- **Containers.** The two Docker-backed telemetry files publish on
  `127.0.0.1::4318`, an ephemeral host port read back with
  `docker port`, and name their containers with a `uuid`. Two workers
  holding one each do not contend.
- **Compute pools.** `OMP_NUM_THREADS`, `ORT_NUM_THREADS` and
  `OPENBLAS_NUM_THREADS` are already pinned to `1` at **workflow**
  level (`L92-L94`), not inside the unit job, so the oversubscription
  that #254 had to fix for four unit workers is already fixed for four
  integration workers. This is the one risk that would have been
  invisible until a flaky CI run, and it is retired by reading rather
  than by luck.

The positive evidence is the three runs in the table above: 346 passed
serial, 346 passed at four workers, 346 passed at fourteen. None of
that is a substitute for a real CI run, which is M1's actual
verification and a **new** measurement, not this one.

### After M1 the floor is the slowest file, and it is named

`loadfile` means no file is split, so the lane cannot finish sooner
than its longest file however wide the runner is. That floor is
`test_tier_closure.py` at 83.37s, and the achieved 130.66s at four
workers against a 492s total (the summed durations of the serial run) is a bin-packing result a few seconds off
its own optimum.

This is why M2 exists and why its claim is modest. Removing the
help-page case's 25.31s takes the floor to roughly 58s and lets a
four-worker pack approach ~118s. That is ten to twelve seconds of CI
wall time, which would not be worth a milestone on its own. What makes
it worth one is that it is the floor: it is what the next runner width
buys nothing against, and it is 25 seconds of a developer's local loop
whether or not they pass `-n`.

M2's claim is therefore stated as "the floor moves from 83s to ~58s",
never as a CI wall-time figure, and M2's verification measures the file
rather than the job.

### The help-page case gets a pool, not a consolidation

`test_every_ungated_command_has_a_help_page_from_the_client_install`
(`test_tier_closure.py:571`) is a serial loop over `cli.COMMANDS`,
spawning one subprocess per ungated row. Its docstring says why the
subprocess is the claim rather than an implementation detail: "a
command whose declaration or whose module-scope import reaches the
server half fails before it prints anything, and importing `cli` would
not have found it." The file's own header says it again: "Every command
is run, not imported."

So consolidating the 65 runs into one process would amortize away the
thing being tested. What the loop does not require is that the runs
happen **one after another**. A pool keeps one fresh interpreter per
command, which is the whole invariant, and divides the wall time by the
pool width.

`test_the_gated_commands_refuse_from_the_client_install` (`L591`) is
the same shape over the gated set and gets the same treatment, since
leaving one of two identical loops serial is the "two structures that
must agree" trap arriving by hand.

The pool is a `ThreadPoolExecutor` over the existing `_ran` helper,
which blocks in `subprocess.run`: the work is waiting on child
processes, so threads are the right tool and `_ran` is unchanged. The
assertions move from the loop body into a per-row result so a failure
still names its row, which is what the current `assert ..., (row.words,
finished.stderr)` buys and must not be lost. The pool width is bounded
and stated, not `len(COMMANDS)`: a runner with four cores should not be
asked for 65 concurrent interpreters, and the width is the one number
this change adds.

### The wedged-collector cases are real time, and M3's likely answer is to say so

`test_telemetry_hardening.py` holds 35.44s of the serial lane across
four cases, of which the two the issue names are
`test_a_collector_that_answers_nothing_costs_no_reply_anything`
(30.02s) and `test_the_shutdown_of_a_wedged_exporter_is_bounded`
(5.00s). Their claims are about elapsed real time by construction:
every reply lands inside a fixed bound with the exporter wedged, and a
wedged exporter's shutdown is bounded rather than unbounded. The second
one's docstring already says it is "measured rather than asserted about
the constant", because an unbounded shutdown "would hang until CI
killed it".

A controllable clock does not preserve either claim: what is being
proven is that the product's real bound holds against a real blocked
thread. So M3's expected outcome for these is the issue's
measured-and-kept, and its deliverable is that the disposition is
written down with its numbers rather than left as an impression.

What M3 must not do is assume the same of the other three worklist
cases. `test_one_session_across_a_reload_a_switch_and_a_memory_write`
(23.01s), `test_a_restricted_agent_is_offered_exactly_its_subset`
(20.37s) and `test_a_conversations_notes_come_back_when_the_thread_does`
(16.06s) are conversation tests whose cost is not attributed yet, and
the arithmetic says it is not simply the number of conversations they
hold: a single-conversation case in the same lane
(`test_a_conversation_triggers_an_mcp_tool_and_the_reply_reflects_it`)
costs 2.65s, and the restricted-agent case holds two and costs 20.37s.
Something other than the conversations dominates those three, and M3's
first deliverable is what.

### What M3 may and may not conclude

M3 is allowed to close every case measured-and-kept. It is not allowed
to close any case without the measurement, and it is not allowed to
report a reduction it did not measure at the file level. If the
attribution finds a shared fixture cost rather than five separate ones,
M3 says so and fixes the one thing.

## Module layout

Small, and no production module is touched.

- `.github/workflows/vinga-server.yml`: two tokens on the integration
  step, and the two stale comments corrected (M1).
- `AGENTS.md`: the Commands block, whose `-n auto --dist loadfile` line
  is captioned "The unit lane the way CI runs it" and stops being true
  of only the unit lane (M1).
- `vinga-server/tests/integration/test_tier_closure.py`: two serial
  loops become pooled, and the pool helper is local to the file (M2).
- `vinga-server/tests/integration/test_telemetry_hardening.py` and
  whichever files M3's attribution names (M3).

**No new module.** The pool helper in M2 is a handful of lines used by
two tests in one file, and a module beside it would fail the deletion
test: inlined into its only caller, the caller does not get harder to
read. If M3's attribution finds a cost shared by several files, the
seam it needs is a fixture in the integration `conftest.py`, which is
where this lane already puts what two or more modules need, and the
milestone names it then rather than now.

## Tests

The test suite is the subject here, so the verification is stated as
what is measured and what is pinned, not as new cases.

- **M1 changes no test.** Its proof is that the same 346 tests pass
  under the new invocation, locally at two widths (done, in the table
  above) and on the pull request's own CI run, which is the measurement
  that counts and is taken after the change rather than before it.
- **M2's pooled loops are falsified before they are believed.** The
  pooled test is watched failing against a deliberately broken command
  (a module-scope import of the server half added to one ungated
  command's arm, reverted after), and the failure must name that
  command. A pooled loop that swallows which row failed is the exact
  regression this change could introduce, and a green run does not
  distinguish it from a working one.
- **M2 pins the inventory, not a count.** The pooled test still walks
  `cli.COMMANDS` and still skips exactly `GATED`; the assertion that
  both halves together cover the whole table is what stops a pool from
  quietly ranging over fewer rows than the loop did.
- **M3 records before and after per file**, under the same instrument
  as this plan's table, and states the commit each number was taken at.

Nothing here reuses a test asset that does not already exist, and no
existing test is restated.

## Documentation footprint

- **M1.** `AGENTS.md`'s Commands block: the line
  `uv run pytest tests/unit -q -n auto --dist loadfile` is introduced
  as "The unit lane the way CI runs it", and after M1 that caption is
  false by omission, because it is how both lanes run. The block gains
  the integration spelling beside it under a caption that covers both.
  The workflow's two stale comments (`L97-L100`, `L470-L472`) are part
  of the same milestone: they are the file's own explanation of a
  decision M1 changes.
- **M1's changelog fragment**: `changelog.d/491-integration-lane-parallel.md`,
  `### Changed`, in the shape #254's entry used, citing measured
  numbers and naming what is unchanged (intra-file order, the tests
  themselves, the local default).
- **M2 and M3.** No hand-maintained page describes which integration
  cases are slow or how they are shaped, so their footprint is the
  implementation doc section and, for M3, a changelog fragment only if
  a case's shape actually changes. A milestone that closes
  measured-and-kept has no changelog entry, because nothing observable
  changed.
- **Generated references.** None. No model, command spelling or event
  changes, so the drift checks and the command-spellings census are
  untouched by M1 and M2. M3 states the same explicitly once its
  attribution is done, and any milestone that edits a document runs
  `tests/unit/test_command_spellings.py` before pushing, per AGENTS.md.

## Risks

- **A test that only fails in parallel, and only on CI.** The lane
  passed at 4 and at 14 workers locally, and the shared-resource audit
  above found no fixed port, no shared path and no unpinned compute
  pool. What local runs cannot model is a four-core runner's timing
  under load, which is what the workflow's thread caps exist for and
  what their comment says is "invisible on a development machine".
  Mitigation: M1's PR is its own experiment, and its CI run is the
  verification. If a case goes red, the fix is in that case, not in the
  two tokens: a test that cannot survive running beside another one is
  a finding about the test, and the issue's own rule already covers it.
- **A flake that appears later rather than on the PR.** One green run
  does not prove a parallel lane stable. Mitigation: M1's PR re-runs
  the workflow once against the branch (`gh workflow run
  vinga-server.yml --ref <branch>`) so the claim rests on two runs, and
  the implementation doc records both. Two is not a stability proof
  either and the doc says so rather than implying it.
- **The pool hides which command failed.** Named above, and falsified
  rather than reasoned about.
- **The pool starves a small runner.** Bounded width, stated as a
  number, chosen so four workers each running a pool do not
  collectively exceed the runner. M2 measures the file at four workers,
  not only alone, because a file that is faster in isolation and slower
  in the lane has bought nothing.
- **M3 finds nothing worth changing.** This is an outcome, not a risk,
  and the issue says so. The milestone is written to close that way
  without embarrassment, and its cost is capped at the attribution.
- **CHANGELOG.md.** Never edited on a branch; every entry is a
  `changelog.d/` fragment. A `docs` workflow check refuses the direct
  edit.

## Milestones

- [ ] **M1: the integration lane distributes.** `-n auto --dist
  loadfile` on the workflow's integration step, the two stale comments
  in that file corrected, `AGENTS.md`'s Commands block made true of
  both lanes, and a `### Changed` changelog fragment. No test changes.
  Verified by the PR's own CI run and one dispatched re-run, both
  recorded with their numbers. **Design footprint:** none; no module,
  no seam. This milestone removes an asymmetry between two invocations
  of the same tool.
- [ ] **M2: the tier-closure floor.** The two serial subprocess loops
  in `test_tier_closure.py` run through a bounded pool, one fresh
  interpreter per command preserved exactly, failures still naming
  their row, falsified against a deliberately broken command. Claim:
  the file's serial total moves from 83.37s toward ~58s, which is the
  lane's `loadfile` floor. **Design footprint:** a file-local helper,
  deliberately not a module; `_ran` is unchanged, which is the seam
  already there.
- [ ] **M3: the rest of the worklist, attributed and dispositioned.**
  Where the seconds go in the three conversation cases, which is not
  yet known and is the milestone's first deliverable; the
  wedged-collector cases named as real-time and kept, with their
  numbers written down; and whatever cheapest change the attribution
  justifies, or none. Allowed to close measured-and-kept in whole or in
  part. **Design footprint:** none unless the attribution finds a
  shared cost, in which case a fixture in the integration
  `conftest.py`, named in the implementation doc when it is known.

M2 and M3 stack on M1 and on each other, and each subagent starts when
its predecessor's PR opens rather than when it merges.

## Plan review round

Backend codex, `codex-cli 0.154.0`, model `gpt-5.6-sol`, sandbox
read-only, 2026-09-15, against commit `42b45310`. Reviewer runtime
7m21s. Verdict: ready after the P1/P2 amendments. Findings recorded as
received, condensed but faithful.

### 1 (P1): M3 leaves the issue's required attribution and design unresolved

The issue requires attribution before change, but the plan says the
three conversation cases are "not yet known", permits "whatever
cheapest change" is later discovered, and leaves both files and fixture
design unspecified. That prevents review of behavioral preservation,
shared-state safety and the deletion test before implementation. The
plan should attribute every worklist case now, state its exact
disposition, identify the files and configuration changes, and describe
the preserved assertions. If attribution reveals a new shared fixture
or seam, the plan should be amended and reviewed before that code is
written.

### 2 (P2): the 30-second telemetry case is classified as irreducible without measuring its components

The plan concludes both telemetry cases are inherently real-time and
should be kept. The 5-second shutdown case does deliberately exercise
`SHUTDOWN_TIMEOUT_S`. The 30-second case instead performs an initial
reply plus `TURNS = 12` more, and those replies use configurable mock
speech whose duration is `max(min_ms, ms_per_char * len(text))` with
defaults of 240 ms and 40 ms per character. A real monotonic latency
assertion does not require twelve long synthesized replies. The plan
should separately time setup, queue saturation, each reply and
teardown, reduce speech duration and turn count to the minimum that
demonstrably fills the queue and proves replies remain independent, and
close only an irreducible remainder as measured-and-kept.

### 3 (P2): M2's claimed 58-second floor is incompatible with a bounded pool

The plan subtracts the entire 25.31s help case and predicts a floor of
roughly 58s while explicitly retaining one fresh subprocess per command
and refusing 65-way concurrency. With pool width `w` the optimistic
floor is `83.37 - 25.31 + 25.31/w` plus pool overhead, about 64.4s at
width four, and the plan never chooses `w`. Its risk analysis also
discusses "four workers each running a pool"; `loadfile` places this
file on one worker, so there is one nested pool competing with the
other xdist workers. The plan should choose the exact width, justify it
against one pooled worker plus the remaining CI workers, give a
realistic target using the residual subprocess time, and measure both
the file alone and the complete four-worker lane.

### 4 (P2): the proposed M2 falsification cannot produce the targeted failure it claims

The drill proposes adding a module-scope import to one ungated
command's arm and expects the failure to name that command. The test
invokes only `vinga <words> --help`, and the CLI constructs the entire
command tree and executes every row's declaration for every invocation,
while server-only imports inside handlers are deferred until the action
runs. A true module-scope or declaration-time import therefore breaks
every help invocation; an import inside one handler is not executed by
`--help`. Neither isolates the named row. The plan should specify a
deterministic row-specific fault at the pooling boundary, such as
making `_ran` return a failing result for one chosen argv, and verify
the main test thread surfaces that row and its stderr. Because the
drill temporarily edits a tracked file, it should follow AGENTS.md's
restore rule: preserve the prior bytes, restore without `git checkout`,
and `touch` the restored file.

### 5 (P3): the `loadfile` rationale cites telemetry fixtures that are not module-scoped

The plan says `test_telemetry_export.py` and `test_telemetry_fanout.py`
boot containers in module-scoped fixtures that `--dist load` would
duplicate. In `test_telemetry_export.py`, `jaeger` is a default
function-scoped fixture; in `test_telemetry_fanout.py`, `_collector` is
a context manager used by its single test. The genuine expensive
module-scoped examples are the tier environments and the wheel build,
installed environment, server and runner in `test_cli_wheel.py`. The
plan should cite the actual module-scoped fixtures as the amortization
reason; the telemetry containers remain relevant to the cross-file
shared-resource audit but not to fixture duplication.

*Resolution*: amended in `5f0ee8a2`. The `loadfile` rationale now cites
`test_tier_closure.py`'s six module-scoped environment fixtures by name
and `test_cli_wheel.py`'s four (`wheel`, `installed`, `elsewhere`,
`live`), which are the genuinely expensive ones. The two telemetry
files are named explicitly as NOT an example, with their actual scopes,
and are left where they belong, in the shared-resource audit.
