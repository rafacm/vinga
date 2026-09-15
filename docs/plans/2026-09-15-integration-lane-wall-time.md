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

**Outcome, added after the runs:** the prediction above was optimistic
by about a quarter and the claim it supports held. The step came in at
3m20s and 3m31s over two green runs rather than near 2m45s, the job at
4m04s and 4m08s rather than near 3m20s, and the integration lane
stopped being the critical path exactly as claimed. The numbers, the
run identifiers and why the scaling factor was wrong are in
[the implementation doc](2026-09-15-integration-lane-wall-time-implementation.md#the-ci-runs-which-are-m1s-real-verification);
this paragraph stays as written, because a prediction that is quietly
edited after the fact is not one.

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

This is why M2 exists and why its claim is modest, and the arithmetic
has to be done with the pool's width in it rather than against zero.
The pooled loop does not vanish; it divides. With width `w` the
optimistic floor is

```
83.37 - 25.31 + 25.31/w   (+ pool overhead, + whatever the gated loop returns)
```

which is **64.4s at width four**, not 58s. Subtracting the case whole
was the error: 58s is the `w` = infinity answer, and the plan
explicitly refuses 65-way concurrency, so it was never available.

**The width is 4, chosen as a starting point and required to be
confirmed by measurement, with the lane as the thing optimized.** The
reasoning: `loadfile` puts this file on exactly one worker, so there is
one pool in the run, competing with the other three xdist workers for a
four-core runner. Each pooled subprocess is a fresh interpreter whose
life is mostly importing the CLI, which is CPU, so a wide pool on a
saturated runner trades the file's wall time against every other
worker's. Four is the runner's core count and the point past which the
pool is bidding against its own lane.

That number is a hypothesis, not a result. M2 measures widths 2, 4 and
8, **both for the file alone and for the whole lane at `-n 4`**, and
takes the width that minimizes the LANE. A width that makes the file
faster and the lane slower has bought nothing, which is the trap a
file-only measurement cannot see.

The risk section previously said "four workers each running a pool".
That cannot happen under `loadfile` and the sentence is corrected: one
worker holds `test_tier_closure.py` and runs the only pool.

M2's claim is therefore stated as "the file's serial total moves from
83.37s toward roughly 64s at width four, confirmed or corrected by
measurement", never as a CI wall-time figure. Against a 492s lane total
that lets a four-worker pack approach ~123s rather than ~118s. Ten
seconds of CI wall time would not be worth a milestone on its own; what
makes it worth one is that it is the floor, which is what the next
runner width buys nothing against, and that it is 25 seconds of a
developer's local loop whether or not they pass `-n`.

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

### The three conversation cases are attributed: they are listening to speech in real time

This is done rather than deferred, and the answer is a single
mechanism shared by all three.

**The measurement.** Same three files, same machine, same commit, the
only variable the mock voice's `ms_per_char` (shipped default 40.0,
`providers/mock.py:345`), each run twice-clean with the bytecode caches
cleared:

| | `ms_per_char` 40 | `ms_per_char` 4 |
| --- | ---: | ---: |
| the three files together | **163.98s** | **72.36s** |
| one session across a reload, a switch, a memory write | 23.31s | 6.44s |
| a restricted agent is offered exactly its subset | 20.53s | 4.24s |
| a conversation's notes come back when the thread does | 16.68s | 5.69s |
| a device note reaches every agent on that device | 10.97s | 3.85s |
| a fact remembered in one conversation reaches the next | 10.42s | 3.87s |

**91.6 seconds of 164, 56% of those three files, is attributable to the
mock voice's duration setting**, with paced playback as the principal
demonstrated mechanism. The run's CPU share says what kind of cost it
is: 25.30s user against 163.98s wall, 17%. The lane is not computing,
it is waiting.

**What this A/B does and does not partition.** It varies one setting
and measures the effect of that setting, which is what M3 needs in
order to act. It does not prove the delta is *exclusively* playback
time, because `ms_per_char` also changes the generated PCM, the number
of synthesis iterations, the encoding, the packet count and the
per-packet delivery calls. What makes paced playback the principal
mechanism rather than a guess is `ReplyPacer`, which sleeps once per
packet against a wall clock (`device/pacing.py`), plus the 17% CPU
share, which rules out the generation and encoding work being where the
time goes. If M3 wants the stronger claim it measures emitted audio
duration or accumulated pacer wait directly; nothing in the milestone
depends on having it.

**Why it waits is product behavior, not a test artifact.**
`device/pacing.py` exists to send a reply's audio "at the rate it will
be heard at", because "the board plays what arrives as it arrives, so a
long answer sent as fast as it encodes floods its playback queue". So
the server deliberately paces outgoing audio in real time, and a test
that provokes a long reply waits through it.

**Why the replies are long.** These files use a mock model that answers
with the prompt it was handed (`speaks_its_prompt`, `{"reply":
"{system}"}`), which is the only way to see a session's assembled
prompt from the far end and is the whole point of those cases. A system
prompt is hundreds of characters, and the mock voice renders
`max(min_ms, ms_per_char * len(text))`, so a several-hundred-character
prompt echo becomes ten or twenty seconds of tone that the pacer then
plays out at real time.

This is the issue's second named mechanism (a test that proves
something "by actually sleeping through N") in a shape the review did
not anticipate: the tests are not sleeping through a timeout, they are
listening to a long reply.

### The disposition: a builder, not a shared block

The change is to the **lane's** mock voice, never to the shipped
default. `build_tts`'s 40 ms per character stays exactly as it is,
because it is the default a person gets when they configure a mock
voice and nothing here is about them. The precedent for overriding it
per configuration is already in the tree: `tests/support/configs.py`
sets `"ms_per_char": 1` on one entry today.

**Not a shared `MOCK_PROVIDERS` dictionary**, which was this plan's
first proposal and does not work. The grep, run rather than remembered:

- Ten integration files define their own
  `MOCK_PROVIDERS = {stage: {"mock": {"type": "mock"}} for stage in (...)}`:
  `test_access_logs.py`, `test_activation.py`, `test_capture_upload.py`,
  `test_device_simulator.py`, `test_device_bindings.py`,
  `test_drain.py`, `test_telemetry_export.py`, `test_ota_endpoint.py`,
  `test_ws_auth.py`, `test_wire_latency_capture.py`.
- **None of the three worklist files is among them.**
  `test_agent_guidance.py`, `test_tools.py` and `test_conversations.py`
  each write `"tts": {"mock": {"type": "mock"}}` inline inside a config
  they build for the case. So a shared block would not have reached the
  files the attribution is about.
- Several files name their voices and carry options that must survive:
  `test_two_personas.py` and `test_tools.py` use
  `{"tenor": {"type": "mock", "tone_hz": POET_TONE}, "alto": {...}}`,
  `test_llm_input_export.py` uses `{"tenor": {"type": "mock",
  "tone_hz": 440}}`, and `test_cli_wheel.py` and `test_cli_live.py` use
  a voice named `voice`. A shared dictionary would flatten all of that.

So the seam is a **builder**, in `tests/integration/conftest.py`: it
returns a fresh mock TTS entry carrying the lane's `ms_per_char`, and
it takes and preserves whatever per-entry options the caller already
passes, `tone_hz` above all. Fresh value per call, never one mutable
dictionary shared between tests. Each of the entries in the inventory
above is rewritten to go through it, keeping its own name and its own
options.

**`tests/support/configs.py` stays outside this seam.** It is imported
by 79 unit test files, some of which depend on the long-reply behavior
deliberately, so the lane's value must not be set there. This is an
integration-lane seam and nothing else.

### The claims that must survive, each checked rather than assumed

The first version of this section claimed that no integration test
asserts reply timing. That was wrong, and the correction is the reason
this round exists.

- **`test_device_simulator.py` asserts an audio-duration window, and it
  is derived from the constant this change moves.** It sets
  `EXPECTED_REPLY_S = 40 * len(EXPECTED_REPLY) / 1000` with a comment
  saying "The mock TTS speaks 40 ms per character with a 240 ms floor",
  and asserts `EXPECTED_REPLY_S / 2 <= duration_s <= EXPECTED_REPLY_S * 3`.
  For "You said hello." that window is 0.3 s to 1.8 s. At 4 ms per
  character the reply floors to 0.24 s and the case fails. M3 keeps
  this contract by deriving `EXPECTED_REPLY_S` from the lane's setting
  rather than from a hardcoded 40, keeping the duration assertion and
  the floor in the arithmetic, and updating the comment that states the
  constants. Retaining a 40 ms override for this one configuration is
  the acceptable alternative if the derivation cannot keep a meaningful
  window.
- **`test_drain.py` is timing-sensitive in a way that shortening a
  reply can silently defeat.** Its case starts a five-sentence reply,
  sleeps 0.05 s, then drains, and asserts the whole reply was spoken
  rather than the part that fitted before the drain. If the reply
  becomes short enough to finish inside that window, the case still
  passes while no longer testing a drain during speech. M3 either keeps
  this configuration's speech long enough that the drain lands
  mid-reply, or replaces the sleep with synchronization on the first
  spoken sentence. It does not simply let the number move.
- `spoken(events)` reads the `tts sentence_start` **text**, which is
  what the three worklist cases assert on. Text is unchanged by how
  long its audio is.
- `test_tools.py` asserts `audio.size > 0` and
  `abs(dominant_hz(audio) - TONE) < 20`, and `test_two_personas.py`
  reads `dominant_hz` too. Shortening the audio shortens the FFT
  window, so M3 confirms the remaining audio still resolves the tone
  inside 20 Hz. The 240 ms floor helps, giving 3,840 samples at the
  16 kHz analysis rate against the ~800 a 20 Hz resolution needs.
  Confirmed by running those cases, not by this arithmetic.
- `test_the_utterance_is_paced_rather_than_burst` is about the
  simulator's **outgoing** utterance and asserts on recorded sleep
  calls rather than elapsed time, so it is untouched. That part of the
  original claim stands; what was wrong was treating it as the whole
  search.

**What M3 does not claim.** `ms_per_char` of 4 was the A/B's probe, not
a proposed constant. M3 picks the lane's value as the smallest that
keeps every check above passing, states it with its reason, and
measures the three files again at that value.

### The wedged-collector case is timed by component before it is kept

The plan's earlier draft called both telemetry cases irreducible. That
was right about one and unproven about the other.

`test_the_shutdown_of_a_wedged_exporter_is_bounded` (5.00s) genuinely
exercises `SHUTDOWN_TIMEOUT_S` and its own docstring says it is
"measured rather than asserted about the constant". It is kept.

The remaining wedged-collector time is **two cases, not one**, and they
are different shapes with different preconditions. Treating them as one
was an error in this plan's first draft.

- **`test_a_collector_that_never_answers_costs_no_reply_anything`**
  replaces the exporter object, so what it certifies is the queue
  between the reply and the transport. It wedges during the first of
  its `TURNS = 12` turns. Its preconditions are that the exporter
  actually blocked (`collector.entered.wait(1.0)`, asserted every turn)
  and that saturation dropped rather than grew without bound
  (`collector.batches <= QUEUE + 1`).
- **`test_a_collector_that_answers_nothing_costs_no_reply_anything`**
  leaves the real OTLP exporter in place against an endpoint that
  accepts and never answers, so what it certifies is the whole path a
  deployment runs. It performs one preliminary turn (a span reaches the
  transport only when it ends) plus `TURNS` more. Its preconditions are
  that the request was entered (`collector.entered.wait(15.0)`) and was
  **still outstanding** when the replies finished
  (`collector.outstanding >= 1`).

Both assert every reply under `REPLY_BOUND_S = 3.0`, and both carry
speech from `ScriptedLlm(["Two words. And two more."])`. That reply is
short (two sentences, about 24 characters, roughly 1 s of audio at the
shipped default), so unlike the three cases above the speech is a
minority of each turn's ~2.3 s and the rest is not yet attributed.

So M3 times **each case separately** by component before touching
either: fixture setup, the turn that establishes the precondition, each
subsequent reply, and the teardown that releases and joins. Then, and
only then, it reduces whatever dominates, per case.

Two levers are available. Per-reply speech duration is one. `TURNS` is
the other, and it may not be cut on the "several times over" comment
alone: **if `TURNS` changes, the milestone states the observable that
demonstrates the precondition still holds at the new value**, which is
the batch count against `QUEUE + 1` for the first case and
`collector.outstanding >= 1` for the second. A turn count reduced until
the case still passes is not evidence; the case passing is compatible
with never having saturated anything.

`REPLY_BOUND_S` is then set from the newly measured healthy reply time,
since its comment says it is deliberately "generous by an order of
magnitude" against it. A bound left at 3.0 s over a 0.3 s reply would
be a weaker test, not a faster one.

Only the remainder that survives that closes as measured-and-kept.

### What M3 may and may not conclude

M3 is allowed to close a case measured-and-kept. It is not allowed to
close any case without the measurement, and it is not allowed to report
a reduction it did not measure at the file level, under the instrument
this plan's tables use, at the commit it ran on.

## Module layout

Small, and no production module is touched.

- `.github/workflows/vinga-server.yml`: two tokens on the integration
  step, and the two stale comments corrected (M1).
- `AGENTS.md`: the Commands block, whose `-n auto --dist loadfile` line
  is captioned "The unit lane the way CI runs it" and stops being true
  of only the unit lane (M1).
- `vinga-server/tests/integration/test_tier_closure.py`: two serial
  loops become pooled, and the pool helper is local to the file (M2).
- `vinga-server/tests/integration/conftest.py`: the lane's mock
  provider block gains one home, carrying the lane's `ms_per_char`
  (M3).
- The integration files that today repeat
  `MOCK_PROVIDERS = {stage: {"mock": {"type": "mock"}} for stage in (...)}`
  read it from there instead (M3). The exact list is the grep, run in
  the milestone and recorded in the implementation doc rather than
  copied into this plan, since an inventory written from memory is the
  thing the review lenses forbid.
- `vinga-server/tests/integration/test_telemetry_hardening.py`: the
  wedged-collector case, after its component timing (M3).

**No new module.** The pool helper in M2 is a handful of lines used by
two tests in one file, and a module beside it would fail the deletion
test: inlined into its only caller, the caller does not get harder to
read. M3's one seam is a fixture in the integration `conftest.py`,
which is where this lane already puts what two or more modules need,
and no production module is touched by either: `providers/mock.py`'s
shipped defaults do not change.

## Tests

The test suite is the subject here, so the verification is stated as
what is measured and what is pinned, not as new cases.

- **M1 changes no test.** Its proof is that the same 346 tests pass
  under the new invocation, locally at two widths (done, in the table
  above) and on the pull request's own CI run, which is the measurement
  that counts and is taken after the change rather than before it.
- **M2's pooled loops are falsified before they are believed**, by a
  fault that can only affect one row. The regression this change could
  introduce is a pool that swallows which row failed, and a green run
  does not distinguish that from a working one, so the drill has to
  produce a row-specific failure and check the row's name comes back.

  **Not by breaking a command's imports**, which was this plan's first
  proposal and cannot work. `command()` in `config/cli.py` builds the
  whole grammar per call and runs every row's `declare`, so a
  module-scope or declaration-time import that reaches the server half
  breaks *every* `--help` invocation rather than one; and an import
  inside a single handler is never executed by `--help` at all, since
  those are deferred until the action runs (`_ota_url` is the worked
  example). Neither end of that isolates a row.

  **The fault goes at the pooling boundary instead**: `_ran` is wrapped
  for the duration of the drill so that one chosen `argv` comes back
  with a non-zero return code and a recognizable stderr, every other
  row running normally. The pooled test must then fail naming that row
  and carrying that stderr, which is precisely the property the serial
  loop's `assert ..., (row.words, finished.stderr)` gives today and the
  only thing the pool could lose.

  The drill temporarily edits a tracked file, so it follows AGENTS.md's
  restore rule rather than `git checkout`: copy the original bytes
  aside, copy them back, and `touch` the restored file, because a
  restored mtime can land on the second a `.pyc` was compiled on and
  the interpreter will keep running the pre-restore version.
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
- **The pool starves the rest of the lane.** Under `loadfile` there is
  exactly one pool, on the one worker holding `test_tier_closure.py`,
  and it competes with the other three workers for a four-core runner.
  Bounded width, stated as a number (4 to start), and chosen by
  measuring widths 2, 4 and 8 against the whole lane at `-n 4` rather
  than against the file alone: a file that is faster in isolation and
  slower in the lane has bought nothing.
- **M3 finds nothing worth changing.** This is an outcome, not a risk,
  and the issue says so. The milestone is written to close that way
  without embarrassment, and its cost is capped at the attribution.
- **CHANGELOG.md.** Never edited on a branch; every entry is a
  `changelog.d/` fragment. A `docs` workflow check refuses the direct
  edit.

## Milestones

- [x] **[M1: the integration lane distributes](2026-09-15-integration-lane-wall-time-implementation.md#m1-the-integration-lane-distributes)** (PR #532). `-n auto --dist
  loadfile` on the workflow's integration step, the two stale comments
  in that file corrected, `AGENTS.md`'s Commands block made true of
  both lanes, and a `### Changed` changelog fragment. No test changes.
  Verified by the PR's own CI run and one dispatched re-run, both
  recorded with their numbers. **Design footprint:** none; no module,
  no seam. This milestone removes an asymmetry between two invocations
  of the same tool.
- [x] **[M2: the tier-closure floor](2026-09-15-integration-lane-wall-time-implementation.md#m2-the-tier-closure-floor)** (PR #534). The two serial subprocess loops
  in `test_tier_closure.py` run through a bounded pool, one fresh
  interpreter per command preserved exactly, failures still naming
  their row, falsified by a row-specific fault injected at the pooling
  boundary. Width starts at 4 and is settled by measuring 2, 4 and 8
  against the whole lane at `-n 4`, not against the file alone. Claim:
  the file's serial total moves from 83.37s toward roughly 64s, which
  is the lane's `loadfile` floor. **Design footprint:** a file-local
  helper, deliberately not a module; `_ran` is unchanged, which is the
  seam already there. Measured: the file 83.37s to 68.33s, the lane
  167.19s to 130.22s at four workers, width four confirmed against
  widths 1, 2 and 8 on the lane rather than on the file.
- [ ] **M3: the rest of the worklist, attributed and dispositioned.**
  The three conversation cases are already attributed (56% of those
  three files is real-time playback of a prompt-echo reply), so the
  work is the disposition: the lane's mock provider block gets one home
  in the integration `conftest.py` as a builder carrying the lane's
  `ms_per_char`, every TTS entry in the inventory rewritten through it
  keeping its own name and options, the value chosen as the smallest
  that keeps `dominant_hz` inside 20 Hz, `audio.size > 0`,
  `test_device_simulator.py`'s duration window (derived from the lane
  setting, not a hardcoded 40) and `test_drain.py`'s drain landing
  mid-reply, and the three files measured again at it. The
  bounded-shutdown case is kept. The two wedged-collector cases are
  timed separately by component before anything is changed, then
  reduced on whichever of per-reply speech or `TURNS` the measurement
  names, with any `TURNS` change stating the observable that shows its
  precondition still holds, and `REPLY_BOUND_S` set from the newly
  measured healthy reply.
  Anything that survives closes measured-and-kept. **Design footprint:**
  one seam, a mock-voice entry builder in the integration
  `conftest.py`, returning a fresh entry that carries the lane's
  `ms_per_char` and preserves the caller's own options such as
  `tone_hz`. Not a shared dictionary, which cannot reach the three
  worklist files and would flatten the named voices.
  `tests/support/configs.py` stays out of it, since 79 unit files
  import it.

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

*Resolution*: amended. The floor is now computed as
`83.37 - 25.31 + 25.31/w` with the pool's width in it, giving roughly
64s at width four rather than 58s, and the plan says plainly that 58s
was the `w` = infinity answer it had already refused. The width is
stated as 4, justified against one pool competing with three other
xdist workers on a four-core runner, and required to be settled by
measuring widths 2, 4 and 8 **against the whole lane at `-n 4`**, since
a file that is faster alone and slower in the lane has bought nothing.
The risk bullet's "four workers each running a pool" is corrected:
`loadfile` puts the file on one worker, so there is exactly one pool.

*Resolution*: amended. The drill no longer breaks a command's imports,
and the plan now says why that could not have worked: `command()`
builds the whole grammar per call and runs every row's `declare`, so a
declaration-time import breaks every `--help` invocation, while a
handler-level import is never reached by `--help` at all. The fault is
injected at the pooling boundary instead, by wrapping `_ran` so one
chosen `argv` returns non-zero with a recognizable stderr while every
other row runs normally; the pooled test must fail naming that row and
carrying that stderr, which is exactly what the serial loop's
`assert ..., (row.words, finished.stderr)` gives today. AGENTS.md's
restore rule is named with it, including the `touch`.

*Resolution for 1 (P1) and 2 (P2)*: both amended, by doing the
attribution rather than rewording the deferral.

The three conversation cases share one mechanism, now measured: an A/B
on the mock voice's `ms_per_char` alone (40 shipped against 4, same
files, same machine, commit `c999d0dc`) takes those three files from
163.98s to 72.36s, so **56% of them is the duration of synthesized
reply audio**. The run is 17% CPU, so it is waiting rather than
computing, and what it waits on is `device/pacing.py` deliberately
sending a reply at the rate it will be heard at. The replies are long
because those files use a model that answers with its whole system
prompt, which the mock voice renders at 40 ms per character.

The disposition is now stated with its files and its preserved
assertions: the lane's provider block gets one home in the integration
`conftest.py` carrying the lane's `ms_per_char`, the shipped default in
`providers/mock.py` is untouched, and the checks are `spoken()` reading
text rather than audio, `dominant_hz` still resolving inside 20 Hz
against the 240 ms floor, `audio.size > 0`, and the absence of any test
asserting the reply arrives paced (`test_the_utterance_is_paced_rather_than_burst`
is about the simulator's outgoing utterance and asserts on recorded
sleep calls). The probe value of 4 is explicitly not proposed as the
constant.

For finding 2, the 30-second case is no longer called irreducible. The
bounded-shutdown case is kept on its own evidence; the wedged-collector
case is timed by component first (setup, the wedging turn, each reply,
teardown), because its scripted reply is short enough that speech is a
minority of each turn and the rest is unattributed, and only then
reduced on whichever of per-reply speech or `TURNS` the measurement
names. `REPLY_BOUND_S` moves with the healthy number rather than
staying generous over a shorter reply.

## Plan review round 2

The first round's finding 1 said that if the attribution revealed a new
shared fixture or seam, the plan should be amended and reviewed before
that code was written. It did, so this round reviews that seam.

Backend codex, `codex-cli 0.154.0`, model `gpt-5.6-terra`, sandbox
read-only, 2026-09-15, against commit `48d03b51`. Reviewer runtime
6m41s. Verdict: ready after the P1/P2 amendments. Two P1s, both
confirmed against the tree before amendment.

### 6 (P1): the proposed provider block cannot reach the target TTS configurations

The plan describes a shared full `MOCK_PROVIDERS` block, but the actual
prompt-echo targets construct TTS inline: `test_agent_guidance.py:168`,
`test_tools.py:47`, `test_conversations.py:51`. Named voices also need
to retain `tone_hz`, for example `test_two_personas.py:41-44`. The plan
should name the full TTS-entry inventory now rather than defer it to a
milestone grep, and specify an integration-only, fresh-value builder in
`tests/integration/conftest.py` that applies the lane's `ms_per_char`
while preserving per-test options such as `tone_hz`. That passes the
deletion test; a shared mutable full dictionary does not.
`tests/support/configs.py` should stay outside this seam because unit
tests use it too, with intentional long-reply behavior.

### 7 (P1): the plan incorrectly says no integration test asserts reply timing

`test_device_simulator.py:32-34` derives `EXPECTED_REPLY_S` from 40 ms
per character and asserts an audio-duration window at `153-157`. With
`ms_per_char` of 4, "You said hello." reaches the 240 ms floor, below
the current 300 ms lower bound. The plan should explicitly preserve
that contract, either by retaining a 40 ms override for this
configuration or by deriving the expected duration from the lane
setting while keeping an audio-duration assertion. It should also
disposition the timing-sensitive drain setup, which relies on a short
sleep after starting a deliberately multi-sentence reply
(`test_drain.py:88-107`).

### 8 (P2): the A/B proves an effect, not that 56% is exclusively paced duration

Varying `ms_per_char` also changes generated PCM, synthesis iterations,
encoding, packet count and delivery calls in `MockTts.synthesize`.
`ReplyPacer` does support the pacing explanation by sleeping once per
packet (`pacing.py:186`), but the A/B alone does not partition the
delta exactly. The plan should say the A/B attributes 56% to the
mock-TTS duration setting, with paced playback as the principal
demonstrated mechanism, and measure emitted audio duration or pacer
wait time if it wants the stronger claim.

### 9 (P2): the wedged-collector amendment conflates two distinct test shapes

Only the real-transport case performs one preliminary reply plus twelve
more (`test_telemetry_hardening.py:445-456`); the replacement-exporter
case wedges during its first of twelve turns (`142-178`). The plan also
lacks a stated observable proving a reduced `TURNS` still saturates the
queue. It should split timing and disposition by test, require proof of
each one's distinct precondition, and if `TURNS` changes, specify the
observable that demonstrates saturation and set `REPLY_BOUND_S` from
the newly measured healthy reply time.

*Resolution for 6 (P1)*: amended. The disposition is no longer a shared
`MOCK_PROVIDERS` dictionary, and the plan now carries the grep rather
than promising one: ten files define their own `MOCK_PROVIDERS` and
**none of the three worklist files is among them**, because those three
write their TTS entry inline. Several files name their voices and carry
`tone_hz`, which a shared dictionary would flatten. The seam is now a
builder in `tests/integration/conftest.py` returning a fresh entry that
carries the lane's `ms_per_char` and preserves the caller's own
options. `tests/support/configs.py` is named as out of scope, with the
reason: 79 unit files import it.

*Resolution for 7 (P1)*: amended, and the false claim is corrected in
place rather than quietly dropped. `test_device_simulator.py` derives
`EXPECTED_REPLY_S` from a hardcoded 40 ms per character and asserts a
0.3 s to 1.8 s window that a 4 ms setting would fail, so M3 now derives
that expectation from the lane's setting and keeps the assertion.
`test_drain.py` is dispositioned too, with the sharper point that it
would keep PASSING while stopping to test anything: if the reply
finishes inside its 0.05 s window the drain no longer lands mid-speech.
The surviving half of the original claim, about
`test_the_utterance_is_paced_rather_than_burst`, is kept and labelled
as the part that was right.

*Resolution for 8 (P2)*: amended. The claim is now that the A/B
attributes 56% to the mock voice's duration setting, with paced
playback as the principal demonstrated mechanism, and the plan says
outright what the A/B does not partition: `ms_per_char` also moves the
generated PCM, the synthesis iterations, the encoding, the packet count
and the per-packet delivery calls. What makes pacing principal rather
than assumed is `ReplyPacer` sleeping once per packet against a wall
clock plus the 17% CPU share. Measuring emitted audio duration or pacer
wait directly is named as what the stronger claim would need, and
nothing in M3 depends on having it.

*Resolution for 9 (P2)*: amended. The two cases are separated with
their distinct shapes and preconditions written out: the
replacement-exporter case certifies the queue and wedges during its
first turn, asserting `entered` every turn and `batches <= QUEUE + 1`;
the real-transport case certifies the whole path, takes one preliminary
turn because a span reaches the transport only when it ends, and
asserts `entered` plus `outstanding >= 1`. Each is timed separately.
The plan now refuses a `TURNS` reduction justified by the case still
passing, and requires the observable that shows the precondition still
holds at the new value, naming which observable belongs to which case.
