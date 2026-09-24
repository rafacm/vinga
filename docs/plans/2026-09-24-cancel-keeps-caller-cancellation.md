# A reply's cancel keeps its caller's cancellation

Plan for [#559](https://github.com/rafacm/vinga/issues/559), as
re-verified in Step 0 at `c6671e46` (issue comment 5807837144). Its
companion is
`docs/plans/2026-09-24-cancel-keeps-caller-cancellation-implementation.md`,
one section per milestone, appended in the same change that ticks the
milestone.

**Local baseline:** not applicable. No conversational capability
changes. What changes is that a bound the server already promises
(`max_session_s`) can no longer be lost in one window.

**Cheapest alternative:** the issue's first option: keep
`await self._reply_task` inside the suppression, and afterwards
re-raise `CancelledError` when `asyncio.current_task().cancelling()`
has risen above its value on entry. It is the same size as this plan's
shape (one function, a few lines). What the `asyncio.wait` shape buys
over it is the second effect Step 0 found. Awaiting the task directly
forwards the caller's cancellation into the reply task as a second
`cancel()`, and that interrupts the reply's `finally`, which is where
`tts stop` is sent and the turn is recorded. The scratch reproduction
logged `tail interrupted` with today's await, which the re-raise shape
keeps; with the wait shape in its place the same script logged
`tail finished`, a propagated `CancelledError` and a `TimeoutError`, and
the existing `test_reply_in_flight.py` and `test_turn_lifecycle.py`
stayed green (26 passed). The cost is the same. Leaving the
problem alone was also priced: every barge-in, abort and manual stop
opens a window of at least one device send in which the session's only
unconditional bound is lost, and for an auto-mode device the idle
watchdog does not stand in for it.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code
2.1.281; 2026-09-24.

## Goal

`ReplyInFlight.cancel` swallows exactly the reply task's own
cancellation and nothing else. A caller cancelled while it waits the
reply out sees its own `CancelledError`, so `asyncio.timeout` around
`DeviceSession._serve` raises its `TimeoutError` and the session cap
holds. The reply it cancelled still finishes its `finally` undisturbed,
and it still has an owner: the runtime keeps its handle, and
`runtime.close()` sees it through as it already does on every close.

## The issue's decisions, restated

- **Suppress only the reply task's own cancellation.** The caller's
  cancellation propagates. Step 0 settled which of the issue's two
  shapes to use: `asyncio.wait([task])`, for the reason under
  "Cheapest alternative".
- **Regression tests watched failing first**: a cancelled caller, and
  a caller under `asyncio.timeout` with a reply whose `finally`
  blocks.
- **The fix lives in `ReplyInFlight.cancel`**, since #482 M3 (PR #560)
  has landed.

## Design decisions

### The shape of `cancel`

```python
self.latch(outcome)
task = self._reply_task
if task is None:
    return
task.cancel()
# asyncio.wait rather than await: a caller cancelled while it waits
# sees its own CancelledError here, and the reply is not cancelled a
# second time on its behalf, which would cut its finally short.
await asyncio.wait([task])
if not task.cancelled():
    task.result()
```

- `asyncio.wait` never raises the task's outcome and never cancels the
  task when the waiter is cancelled. Both are what the fix needs.
- `task.result()` after the wait is what keeps the settled contract
  that a reply ending in any exception other than its own cancellation
  raises out of `cancel`. A reply that finished normally before the
  cancel landed returns None, as it does today.
- `contextlib` stops being imported by the module if nothing else uses
  it.
- The docstring's contract sentence changes from "exactly
  `CancelledError` is suppressed" to what is now true: the reply's own
  cancellation is suppressed, and the caller's is not.

### `runtime.close()` purges even when its wait is cancelled

`PipelineRuntime.close` awaits `cancel_reply(ABORTED)` and then purges
the session's unrecorded threads. Today a cancellation of the session
task landing in that wait is swallowed, so the purge runs. After the
fix it propagates, which would skip the purge and leave the
unrecorded threads' ledgers in a process that never restarts. That is
the exact leak `close`'s docstring says it exists to prevent. So the
purge moves into a `finally` around the cancel. The session's
`_cleanly` already holds a `CancelledError` from `runtime.close()` and
re-raises it after the remaining close steps
(`device/session.py` `_cleanly`), so nothing above `close` changes.

Nothing else needs a guard. Every other caller of `cancel_reply` runs
on the serve loop's task (the device abort, the manual stop, the three
barge-in sites in `turntaking.py`), where propagating the caller's
cancellation is exactly the fix. Inventory command for the review and
the brief, untruncated:
`grep -rn "cancel_reply\|\.cancel(ReplyOutcome" vinga-server/src`.

### The handle survives a cancelled caller

`PipelineRuntime.cancel_reply` clears `_in_flight` only after
`reply.cancel` returns. A caller whose cancellation propagates out of
the wait never reaches that line, so the runtime still holds the reply,
`replying()` still answers True until it ends, and `close()` finds it
and waits it out. That is the behavior this plan wants, and a test pins
it (below), because it is the whole of why the reply is not left
ownerless.

## Module layout

- `vinga-server/src/vinga_server/runtime/reply_in_flight.py`:
  `cancel`'s body and docstring.
- `vinga-server/src/vinga_server/runtime/pipeline.py`: `close` puts
  the purge in a `finally`; `cancel_reply`'s docstring gains one
  sentence saying a cancelled caller leaves the handle in place.
- `vinga-server/tests/unit/test_reply_in_flight.py`: value-level tests.
- `vinga-server/tests/unit/test_turn_lifecycle.py`: runtime-level
  tests, beside `HoldsTheFirstStop`, which already holds a cancelled
  reply at the last send of its `finally`.
- `changelog.d/559-cancel-keeps-caller-cancellation.md`: `### Fixed`.

## Tests

Each new test is watched failing against `c6671e46`'s `cancel` before
the fix lands, and the commit body says so. All of it is straight-line
asyncio ordering driven by events rather than sleeps, so one failing
run per mutation is the proof; the one timing-sensitive test (the
timeout) is still event-driven, since the timeout fires while the tail
is held on an event and cannot race it.

Value level (`test_reply_in_flight.py`), with a body whose `finally`
waits on an event the test releases:

1. **A caller cancelled mid-wait sees its own cancellation.** The
   caller task awaiting `cancel` is cancelled while the tail is held;
   awaiting the caller raises `CancelledError`. Fails today: the
   caller returns normally.
2. **A caller under `asyncio.timeout` gets its `TimeoutError`.** Fails
   today: the block exits normally.
3. **The caller's cancellation does not cut the reply's tail short.**
   After (1), the tail is released and runs to its end; the body's
   own log records that it finished. Fails today: the tail is
   interrupted by a second `CancelledError`.
4. **A reply that finished before the cancel landed raises nothing**
   and keeps the latched outcome. This pins the `task.result()` arm's
   quiet case: a mutation raising whenever the task was not cancelled
   fails it. The existing
   `test_a_cancel_raises_what_the_reply_ended_in_otherwise` already
   pins the loud case and stays as it is.

Runtime level (`test_turn_lifecycle.py`), through `cancel_reply`, the
name the session's callers reach:

5. **The session cap's shape.** `cancel_reply(BARGED_IN)` runs under
   `asyncio.timeout` while `HoldsTheFirstStop` holds the reply's
   `tts stop`. The timeout raises `TimeoutError`. The reply is still
   the one in flight (`reply_in_flight(session)` is the same value,
   `replying()` True). On release, exactly one stop was sent and the
   recorded outcome is `barged_in`. Then `runtime.close()` returns with
   nothing in flight and no second outcome recorded. Fails today at
   the `TimeoutError` assertion.
6. **A cancelled close still purges.** A runtime built with a purge spy
   and a reply held at its stop: the task running `close()` is
   cancelled during the wait. It raises `CancelledError`, and the spy
   was called with the session's current threads. Fails with the fix
   applied but the `finally` removed, which is the mutation that
   proves the guard; the implementer records that run. How the spy
   reaches the runtime is the implementer's to find through the
   existing constructor argument (`purge=`) and test support, not
   through a new seam.

Existing suites that must stay green unchanged: every
`test_session_*` file, `test_turn_lifecycle.py`, `test_turntaking.py`
and `test_reply_in_flight.py`, both lanes, and `tests/census`.

## Standing lenses

- **No-leak:** nothing new reaches a retained surface; no exception
  text is rendered.
- **Pin before reshaping:** not a reshaping. The behavior changes on
  purpose, and tests 1-3 and 5 are the pins of the new behavior.
- **Closed sets:** no token or field changes. `ReplyOutcome` latching
  is untouched.
- **Honest seams:** no injectable dependency is added.
- **Inventories by tooling:** the caller inventory above is one
  untruncated grep, and the implementation doc records its output.
- **Falsify before claiming:** as under "Tests", with the six
  mutations named and each observed failing once.

## Risks and mitigations

- **A reply left running after a cancelled `close()`.** If the session
  task is cancelled during `close`'s wait, the reply's own cancellation
  has already been delivered and its `finally` is running; with the
  wait shape, it finishes on its own instead of being interrupted.
  Nothing awaits it afterwards. Today it is interrupted and awaited.
  The reply ends within the time its `finally` takes (one device send
  to a closing socket, one record), and it is referenced from its
  pending send until it does. Mitigation: accept, and say so in
  `close`'s docstring. The alternative (forwarding the cancel into the
  reply from `close` only) brings back the interrupted tail, the thing
  this plan removes.
- **A caller that relied on `cancel_reply` never raising
  `CancelledError`.** The inventory shows none outside `close`.
  `turntaking.finish_utterance` propagates it, which is correct: its
  caller is the serve loop being cancelled.
- **Stale bytecode during the mutation runs.** Mutations run under
  pytest, which writes no bytecode (AGENTS.md); anything run outside
  it sets `PYTHONDONTWRITEBYTECODE=1`.

## Documentation footprint

No hand-maintained page describes `cancel`'s suppression contract:
`grep -rln "cancel_reply\|ReplyInFlight.cancel" docs README.md` finds
only historical plans and one feature doc, and those record what was
true when they were written. So the footprint is the two docstrings
(`ReplyInFlight.cancel`, `PipelineRuntime.cancel_reply`), `close`'s
docstring for the risk above, and the changelog fragment.

## Milestones

- [ ] **M1: a reply's cancel keeps its caller's cancellation**
  (PR TBD). Commits in this order:
  1. The value-level tests 1-4 and the runtime-level test 5, with the
     fix: one commit, since tests 1-3 and 5 cannot be green without
     it. The body records each test's failing run against today's
     `cancel`.
  2. `close()`'s `finally` and test 6, with the mutation run recorded.
  3. The changelog fragment, this plan's tick, and the implementation
     doc's M1 section; the census manifests regenerated if either went
     stale.

  Design footprint: deepens `ReplyInFlight` (callers stop having to
  know that waiting out a cancelled reply could swallow their own
  cancellation), adds no module or seam. Documentation footprint as
  above.
