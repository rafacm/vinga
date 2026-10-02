# The wedged-exporter shutdown test waits out its abandoned release

**Date:** 2026-10-02

**Local baseline:** not applicable. The change is confined to one
integration test; no conversational capability is added, removed or
moved off the machine.

## Problem

`test_the_shutdown_of_a_wedged_exporter_is_bounded`
(`vinga-server/tests/integration/test_telemetry_hardening.py`) failed
intermittently at teardown, in the file's autouse fixture
`_no_lease_outlives_its_case`, which asserts `_QUIETING.held() == 0`
and saw `1`. The case itself passed. It was seen twice in CI, the
latest in run 36920119842 attempt 1 (call 5.92 s, then `ERROR at
teardown`), on a branch that did not touch telemetry.

The case races its own `finally` against the fixture, and the race is
built into what it measures. The collector is wedged, so
`Telemetry.shutdown` hands the release to its daemon thread and its
bounded wait expires, which is the designed outcome. That thread is
still inside `provider.shutdown()`, and it gives the SDK's quieting
lease back only from `_complete`'s `finally`, once the export is really
over, because restoring the SDK's logging when the wait ended would let
the abandoned export log its endpoint. The case then set the collector
free and returned at once. The thread still had to wake, finish the
export, let the SDK join its own worker and release the lease, and the
fixture asserted as soon as the case returned, so on a loaded runner it
looked first.

Nothing leaked: the lease came back milliseconds after the fixture
looked. The production code behaves as its docstrings say, and this is
a test defect only.

## Changes

### The case waits for the one completion

After setting the collector free, the case now calls the public
`Telemetry.release`, which for a caller that did not claim the release
waits on the claimer's completion and returns at once if it is already
over. It runs on a daemon thread of the case's own, joined off the loop
with `asyncio.to_thread(finishing.join, SHUTDOWN_TIMEOUT_S)`, and the
case asserts the thread is no longer alive. The wait is in the case's
`finally`, so it happens whether or not the shutdown itself raised.

A daemon thread rather than `asyncio.wait_for(asyncio.to_thread(
telemetry.release), ...)`, for the reason `Telemetry.shutdown` gives
for its own worker: a release that never finished would pin a
default-executor thread, and the interpreter joins those at exit, so a
regression would hang the lane instead of failing it. The same shape,
a daemon thread running `release` and a bounded join, is already used
by `test_a_direct_release_and_a_shutdown_are_one_completion` in
`tests/unit/test_telemetry_lifecycle.py`.

The shutdown's duration is now taken inside the `try`, before the new
wait, so the bound the case asserts (`took < SHUTDOWN_TIMEOUT_S * 2`)
still measures the shutdown alone.

The fixture is unchanged. It is what catches a real leak, and the fix
makes the case stop racing it rather than making it look later.

### Interface

`release` is public, documented as the blocking door onto the same
completion `shutdown`'s worker runs, so the case reaches nothing past
the module's interface. The reach-in census is unchanged; it was run
last, and passes without regeneration.

## Audit of the sibling cases

Every file that asserts the lease count was inventoried with an
untruncated grep, run from `vinga-server/`:

```bash
grep -rln "_QUIETING.held() == 0" tests | wc -l                # 9
grep -rln "propagate is not False" tests | sort                  # 3
```

The first gives the nine files the issue named: this one,
`tests/integration/test_capture_upload.py`, and seven unit files
(`test_telemetry.py`, `test_telemetry_spans.py`,
`test_telemetry_transcripts.py`, `test_telemetry_llm_input.py`,
`test_tool_span_content.py`, `test_telemetry_lifecycle.py`,
`test_capture_upload.py`). The second adds one more file with a
fixture of the same shape, asserting that the lease's other
observable, the namespace's propagation, is restored:
`tests/integration/test_transcript_export.py`.

Two methods, the second checking the first.

**Reading.** Each case in those files that ends a telemetry exporter or
capture uploader was read for how its release finishes before the
check:

- The six unit telemetry fixtures call `released()` from
  `tests/support/telemetry.py` before asserting, and `released()` calls
  `release()` on every exporter `exporting()` built, which waits on any
  abandoned completion. The cases that build outside `exporting()` are
  `test_a_failed_export_leaks_nothing` (`test_telemetry.py`, a shutdown
  that completes inside its bound), the lifecycle case above (joins its
  own release thread and asserts it ended), and the lifespan cases
  (in-memory exporters, which shut down at once).
- In this file, the saturation case sets the collector free BEFORE its
  `shutdown`, so the bounded wait sees the completion; the late-failure
  case waits until the namespace's level is restored, which `Quieting`
  writes under the same lock and after the count drops; the
  withholding case calls `release` itself, unbounded.
- `tests/integration/test_transcript_export.py` calls
  `telemetry.release()` directly in each case's teardown, which blocks
  until the completion.
- The capture uploader has no release door: its `shutdown` joins the
  worker thread under a bound, and the worker gives its lease back in
  its own `finally` before the thread ends, so a join that returned
  inside its bound has seen the lease go back. A bound short enough to
  expire appears three times across the two files
  (`grep -n "shutdown_timeout_s=0\|shutdown_timeout_s=1\b"`): the unit
  overlapping-lifespans case, which waits on the count itself before
  its last shutdown; the integration case whose backend never answers,
  whose worker has already reported its failure and is idle when it
  shuts down; and the case discussed below. Every other case frees its
  gate before its last, 10 s or 20 s, shutdown.

**Mutation.** A delay injected ahead of the lease's give-back makes any
case that ends with a release still running fail its check, so each
audited file was run with one (not committed):

- 0.5 s ahead of `self._quieted.release()` in `Telemetry._complete`:
  all nine lease-count files together, `312 passed in 182.51s` (two
  workers, `--dist loadfile`), and `tests/integration/test_transcript_export.py`
  alone, `4 passed in 20.18s`.
- 0.5 s ahead of `lease.release()` in `CaptureUpload._run`: both capture
  upload files, `115 passed in 49.81s` (two workers).

**Result: no other case races its check.** One case was looked at
further and deliberately left alone.
`test_the_real_sdk_says_nothing_after_the_shutdowns_bound`
(`tests/integration/test_capture_upload.py`) lets a 0.2 s shutdown
bound expire with a request in flight and then sleeps a fixed 4.0 s
for that request's 3.0 s timeout before asserting
`_QUIETING.held() == 0` inline. That is a margin rather than a race
with none: the delay in the uploader's give-back was raised to 0.8,
1.1 and 1.4 s, two runs each, and every run passed. It is not the
issue's shape, and the uploader has no public completion to wait on
the way `release` gives the exporter one, so tightening it would mean
changing what its leak hunt waits on; that is a separate change, not
this one.

## Key parameters

| Run | Mutation (0.5 s before the give-back) | Fix | Outcome |
| --- | --- | --- | --- |
| The case alone | applied | absent | 10 of 10 `ERROR at teardown`, `assert 1 == 0` from `held()` |
| The case alone | applied | present | 10 of 10 passed |
| The case alone | 12 s instead of 0.5 s | present | 3 of 3 failed on "the abandoned release never finished", none hung |
| The whole file | none | present | 10 of 10 runs, 4 passed each |

The wait's bound is `SHUTDOWN_TIMEOUT_S` (5 s). Once the collector is
free, what the abandoned release has left is the batch processor's
queue (at most `QUEUE`, 4 spans) into an exporter that now answers at
once, so a bound the shutdown itself trusts is generous; the 12 s
mutation shows it is also a bound, not a hang.

## Verification

Run on agentpi, a 4-core machine shared with three other implementers
at the time, which is why single-case runs took between 6.5 and 30 s.

- The race reproduced deterministically before the fix, and passes
  with it: the first two rows of the table above.
- A completion that never comes fails rather than hangs: the third row.
- The whole of `tests/integration/test_telemetry_hardening.py`, ten
  serial runs with the fix and no mutation: `4 passed` in every
  run, between 37.36 s and 224.36 s each, the spread being the shared
  machine's load.
- The audit mutations above, and `tests/integration/test_transcript_export.py`
  under the 0.5 s telemetry mutation: `4 passed in 20.18s`, serial.
- `uv run ruff check .` passes.
- The full unit and integration lanes were not run locally: the change
  is one test file, and CI runs both lanes.
- `uv run pytest tests/census -q` passes, run after this document's
  last edit.

Every mutation was applied to a copy-aside of the source file and
restored by copying it back and touching it, and `git status` was
clean of source changes afterwards.

## Files modified

- `vinga-server/tests/integration/test_telemetry_hardening.py`
- `changelog.d/593-wedged-shutdown-teardown.md`
- `docs/features/2026-10-02-wedged-shutdown-teardown.md`
