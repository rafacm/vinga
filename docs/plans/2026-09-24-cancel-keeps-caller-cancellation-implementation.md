# A reply's cancel keeps its caller's cancellation: implementation

Companion to [`2026-09-24-cancel-keeps-caller-cancellation.md`](2026-09-24-cancel-keeps-caller-cancellation.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: a reply's cancel keeps its caller's cancellation

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.281; 2026-09-24.

`ReplyInFlight.cancel` swallows the reply task's own cancellation and
nothing else: it waits with `asyncio.wait`, so a caller cancelled while
it waits sees its own `CancelledError`, `asyncio.timeout` around the
serve loop raises its `TimeoutError`, and the reply is not cancelled a
second time on the caller's behalf. The session's close keeps the
stricter rule it needs through a second way to end a reply,
`ReplyInFlight.close`, and `PipelineRuntime.close` built on it: a
cancellation there is passed on to the reply, held, and raised only
once the reply's task is done, the handle is cleared and the purge,
now a task the close owns, has finished. The hold-until-done loop both
use is `runtime/outlast.py`.

### The commits

| Commit | What it is |
| --- | --- |
| `Keep a cancel's caller cancellation its own` | The fix to `cancel`, tests 1-4 in `test_reply_in_flight.py`, test 5 in `test_turn_lifecycle.py`, and `cancel_reply`'s docstring sentence |
| `Add outlast: wait a task out through cancellation` | `runtime/outlast.py` and `tests/unit/test_outlast.py` (test 13), nothing using it yet |
| `Hold a close's cancellation until its work is done` | `ReplyInFlight.close`, `PipelineRuntime.close` with the purge as an owned task, tests 6-12 |
| `Record M1 of the cancel fix` | The changelog fragment, the reach-in manifest, this section and the tick |

### What landed

| Piece | Where |
| --- | --- |
| `cancel` | `runtime/reply_in_flight.py`: `asyncio.wait([task])`, then `task.result()` unless the task was cancelled; `contextlib` no longer imported; the docstring's contract sentence now says the reply's own cancellation is suppressed and the caller's is not |
| `close` on the value | `runtime/reply_in_flight.py`: `ReplyInFlight.close(outcome)`, latch, `cancel()`, `outlast(task, hurry=True)`, the task's exception read before either raise, the held cancellation raised first |
| The loop | `runtime/outlast.py`: `outlast(task, *, hurry=False) -> CancelledError \| None`, the plan's signature and contract |
| The runtime | `runtime/pipeline.py`: `close` ends the reply through `ReplyInFlight.close`, catches `CancelledError` then `BaseException`, clears the handle, runs the purge as `asyncio.ensure_future(asyncio.to_thread(...))` and outlasts it, reads its outcome unconditionally, raises held, else the reply's failure, else the purge's; `cancel_reply`'s docstring gains the sentence the plan names; the `_in_flight` field note names `close` beside `cancel_reply` |
| Tests | `test_reply_in_flight.py` (tests 1-4, 8, 8's second half, 9), `test_turn_lifecycle.py` (tests 5, 6 as two tests, 7, 10, 11, 12), `test_outlast.py` (test 13 as five tests) |

### The caller inventory

The plan's command, from the repository root, untruncated, at this
milestone's head:

```text
$ grep -rn "cancel_reply\|\.cancel(ReplyOutcome" vinga-server/src
vinga-server/src/vinga_server/runtime/pipeline.py:407:      `cancel_reply` or `close` only if it is still the reply that call
vinga-server/src/vinga_server/runtime/pipeline.py:931:        await self.cancel_reply(ReplyOutcome.ABORTED)
vinga-server/src/vinga_server/runtime/pipeline.py:2637:    async def cancel_reply(self, outcome: ReplyOutcome) -> None:
vinga-server/src/vinga_server/runtime/turntaking.py:134:    (`cancel_reply`), and the confirmation transcription the gate ladder
vinga-server/src/vinga_server/runtime/turntaking.py:258:        before the new reply's `tts start`, because `cancel_reply` waits
vinga-server/src/vinga_server/runtime/turntaking.py:307:                await self._reply.cancel_reply(ReplyOutcome.BARGED_IN)
vinga-server/src/vinga_server/runtime/turntaking.py:386:            await self._reply.cancel_reply(ReplyOutcome.BARGED_IN)
vinga-server/src/vinga_server/runtime/turntaking.py:438:        await self._reply.cancel_reply(ReplyOutcome.BARGED_IN)
$ grep -rn "cancel_reply\|\.cancel(ReplyOutcome" vinga-server/src | wc -l
8
```

Four call sites, all on the serve loop's task: `device_aborted`
(`pipeline.py:931`), `finish_utterance` (`turntaking.py:307`) and the
two in `_gate_barge_in` (`turntaking.py:386`, `438`). The other four
lines are the definition and three docstring mentions, one of them
this milestone's own. `close` is no longer a caller: it ends the reply
through `ReplyInFlight.close`, and `ReplyInFlight.cancel` has no caller
outside `cancel_reply`.

### The falsification runs

One run per test or mutation: every claim is straight-line asyncio
ordering driven by events, and the one timed test (the timeout) fires
while the tail is held on an event. Every mutation was applied to a
copy of the file set aside and copied back, then touched, under
pytest, which writes no bytecode.

Against `c6671e46`'s `cancel`, before the fix:

| Test | Result |
| --- | --- |
| 1. a caller cancelled mid-wait sees its own cancellation | `DID NOT RAISE CancelledError` |
| 2. a caller under `asyncio.timeout` gets its timeout | `DID NOT RAISE TimeoutError` |
| 3. the caller's cancellation leaves the reply's tail alone | `['interrupted'] == ['finished']` |
| 5. the session cap's shape through `cancel_reply` | `DID NOT RAISE TimeoutError` |

Test 4 (a reply that finished before its cancel) passes against the old
code by design, since it pins the quiet half of the `task.result()` arm.

Mutations:

| Mutation | Result |
| --- | --- |
| `cancel`: `raise task.exception()` in place of `task.result()` | test 4 fails, `TypeError: exceptions must derive from BaseException` |
| `outlast`: `if` for `while` (waits once) | three `test_outlast.py` tests fail |
| `outlast`: the last cancellation kept, not the first | `('second',) == ('first',)` |
| `outlast`: `hurry` ignored | the hurry test times out waiting for the nudge |
| `outlast`: `await task` for `asyncio.wait` | four tests fail: the task is cancelled without `hurry`, and its `RuntimeError` escapes |
| `outlast`: the task always cancelled | the no-hurry and failed-task tests fail |
| `outlast`: an `await` before looking | the already-done test's first step does not raise `StopIteration` |
| `ReplyInFlight.close` not hurried | tests 8 and 9: "the close never let its caller go" |
| `ReplyInFlight.close` as `cancel` (one `asyncio.wait`, nothing held) | tests 8 and 9: the tail never interrupted, the close ended with the reply running |
| `ReplyInFlight.close`: a failed reply raises nothing | test 8's second half: `DID NOT RAISE RuntimeError` |
| `ReplyInFlight.close`: `raise held` before the task's outcome is read | test 9: **survived the first pass**, then `['Task exception was never retrieved'] == []` after the fix below |
| `PipelineRuntime.close` as at `c6671e46` (`cancel_reply`, then a plain awaited purge), which is `close` built on the fixed `cancel` alone | all seven runtime close tests fail: 6 (`['closed with the reply running'] == ['turn', 'closed']`), 6's purge half, 7, 10, both cases of 11 (the purge never ran), 12 |
| the purge skipped whenever a cancellation is held | test 6's purge half: `['closed'] == ['purged', 'closed']` |
| the purge as a plain `await asyncio.to_thread(...)` | test 10 at "still not done"; test 12 raises the purge's failure |
| `except Exception` for the `BaseException` arm | test 11's `base-exception` case: the purge never ran |
| `failed = failed or purging.exception()` | test 12: `'Task exception was never retrieved'` |
| `outlast` handling one cancellation, then one unguarded wait | test 7: `['turn', 'closed with the reply running'] == ['turn', 'closed']` |

The six runtime-level mutations were run a second time against the
committed test file, after the settle stubs were routed through one
helper, with the same results.

The one survivor was a finding about the test, and the driver did reach
the condition: a probe of the mutated run showed the reply's task alive
after the test's single `gc.collect()`, held in a cycle of the task, its
coroutine and the held cancellation's traceback through `close`'s and
`outlast`'s frames, and a second pass after a turn of the loop collected
it and the handler saw the report. The test now collects three times
with a loop turn between, as `test_drain.py` does, and proves the task
went with a `Witness` only the reply body's frame holds; test 12 proves
its purge failure went the same way.

### Deviations from the plan

- **Test 6 is two tests.** A runtime is handed the purge only where it
  is handed no store to record turns in (`bespoke_runtime_factory`
  passes `memory.purge_threads if conversations is None else None`),
  so no one session can show the turn record landing and the purge
  running. `test_a_cancelled_close_records_the_turn_before_it_lets_go`
  holds the store half and
  `test_a_cancelled_close_purges_after_the_reply_and_before_it_lets_go`
  the purge half; each is falsified by the plan's first named mutation,
  and the purge half by its second.
- **Test 13 names the first cancellation by its message, not by
  identity.** A `CancelledError` is made where it is thrown into the
  waiter, so no instance outside it exists to compare with `is`.
- **Test 7's "later await" is the closing `tts stop`.** The first
  cancellation lands at a settle stub that stands its clip down and
  returns, so the hurried tail goes on to the stop `HoldsTheFirstStop`
  holds, where the second arrives. The mutation "waits once" was run
  as a loop that takes one cancellation and then waits once more
  unguarded, which is the shape test 7 can see; the `if`-for-`while`
  shape is test 13's.
- **Test 12 does not assert the reply's failure is unchained.** It is:
  its `__context__` is the `CancelledError` it broke under, which is the
  reply's own chain and nothing `close` added. Test 9 is the one that
  pins that a held cancellation carries no chain.
- **The purge spy wraps the lane's memory store.** The purge reaches
  the runtime as `memory.purge_threads`, so `PurgeSpy` is a memory store
  that delegates everything else to the lane's own and is passed as
  `memory=`, with no reach-in.
- **The `_in_flight` field note in `PipelineRuntime`'s docstring
  changed.** It named `cancel_reply` as the only thing that lets the
  handle go; `close` does now as well. Outside the plan's footprint list,
  one line.
- **The reach-in manifest moved by one.** The runtime tests stand a stub
  in for `filler.settle` through one helper, `settling_with`, the
  precedent `test_a_cancellation_inside_the_filler_settle_reports_once`
  set, so `tests/unit/test_turn_lifecycle.py  _filler` goes from 1 to 2.

Otherwise none: the shape of `cancel`, the module and signature of
`outlast`, `ReplyInFlight.close`, `PipelineRuntime.close` and the
documentation footprint are the plan's.

### Discoveries

- **A test body that takes every cancellation can wedge the loop's
  teardown under a mutation.** `test_outlast.py`'s `Stubborn` body and
  test 7's settle that gives way both swallow a cancellation, so when a
  mutation fails a test early and leaves them pending, the loop's own
  teardown cancel is taken too and the run hangs rather than failing.
  The first mutation runs hung this way and were stopped. `Stubborn` is
  now released by a fixture at teardown and test 7 releases its device
  in a `finally`; both fail cleanly under every mutation above.
- **`asyncio.wait_for` cannot bound a close that holds cancellations.**
  On its timeout it cancels the inner task and waits for it, and a
  close that holds that cancellation keeps it waiting, so a bound
  written that way hangs exactly when it is needed. Tests 6 to 10
  bound the wait with `asyncio.wait(..., timeout=...)` and assert the
  task is done.
