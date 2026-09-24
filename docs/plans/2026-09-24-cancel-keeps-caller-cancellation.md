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
`close()` itself is the one caller that must not let go early: a
cancellation reaching it is passed on to the reply and held, and it
reaches `close()`'s caller only once the reply's task is done, the
handle is cleared and the purge has run.

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

### `runtime.close()` sees the reply through, then re-raises

`PipelineRuntime.close` awaits `cancel_reply(ABORTED)` and then purges
the session's unrecorded threads, and it runs inside the session's
close path, whose contract is that a cancellation arriving there is
held until the record is finished (`_cleanly`, pinned by
`test_a_cancelled_cleanup_step_still_finishes_the_record`). Today a
cancellation of the session task landing in `close`'s wait is
forwarded into the reply by the direct await and then swallowed, so the
reply ends, the purge runs and `close` returns. Were `close` to use the
fixed `cancel` alone, the cancellation would propagate with the reply
still in its tail (possibly at `filler.settle`, before its turn is
recorded) and the purge skipped, and `_cleanly` would go on to
`session_closed`, the store's close and the export barrier while the
reply could still enqueue its turn behind them.

So `ReplyInFlight` gets a second way to end, beside `cancel`, named for
the caller whose situation it is:

```python
async def close(self, outcome: ReplyOutcome) -> None:
    self.latch(outcome)
    task = self._reply_task
    if task is None:
        return
    task.cancel()
    # Hurried, not released: each cancellation of the caller is passed
    # on to the reply, whose finally is built to take a second cancel,
    # and the first is held until the task is done.
    held = await outlast(task, hurry=True)
    # Retrieved whichever way this ends: a reply whose tail ended in
    # something other than its cancellation still has that exception
    # observed here, so asyncio never reports it as unretrieved, with
    # its text and chain, after the handle is gone.
    failed = None if task.cancelled() else task.exception()
    if held is not None:
        raise held
    if failed is not None:
        raise failed
```

With a cancellation held, the reply's own exception is retrieved and
dropped rather than chained: `raise held` sits outside any `except`
arm, so nothing is attached as its `__context__`, and the only thing
that reaches `close`'s caller is the cancellation it was already owed.
`cancel` has the same exposure in a narrower form (a caller cancelled
mid-wait leaves the task's outcome unread), and it is covered by the
handle surviving: the runtime still holds the reply, and the owner's
`close` is what reads its outcome.

and `PipelineRuntime.close` holds a cancellation across both of its
steps, not only the reply's:

```python
async def close(self) -> None:
    held: asyncio.CancelledError | None = None
    failed: BaseException | None = None
    reply = self._in_flight
    if reply is not None:
        try:
            await reply.close(ReplyOutcome.ABORTED)
        except asyncio.CancelledError as cancelled:
            held = cancelled
        except BaseException as exc:
            # Every other outcome, so the purge below is reached on
            # every path, and raised after it.
            failed = exc
        if self._in_flight is reply:
            self._in_flight = None
    if self._purge is not None:
        purging = asyncio.ensure_future(
            asyncio.to_thread(self._purge, list(self.conversations.current_threads()))
        )
        # A thread cannot be cancelled, so there is nothing to hurry:
        # the purge is outlasted, and a cancellation meanwhile is held.
        # outlast answers the cancellation it held, or None. Awaited
        # unconditionally and merged after, so the first one wins.
        later = await outlast(purging)
        # Read unconditionally, before any choice between failures, so
        # a failed purge is retrieved even when the reply failed first.
        purge_failed = None if purging.cancelled() else purging.exception()
        held = held or later
        failed = failed or purge_failed
    if held is not None:
        raise held
    if failed is not None:
        raise failed
```

The shape to hold to, rather than the exact lines: the purge is a
task `close` owns and waits out, never an await a cancellation can walk
away from, and the first cancellation `close` received is raised only
once the reply's task is done, the handle is cleared and the purge has
completed. A reply that failed, whatever it failed with, no longer
skips the purge either: today `close`'s `cancel_reply` raising a
reply's exception left the purge unrun, which is the same leak by
another road, and the plan closes it in passing because every outcome
of `reply.close` other than a cancellation is caught as a
`BaseException`, held, and raised after the purge. When both fail, the
reply's failure is the one raised and the purge's is retrieved and
dropped, as a held cancellation drops a reply's.

### The hold-until-done loop gets a module: `runtime/outlast.py`

Both owners wait a task out through any number of cancellations of
their own caller and raise the first only afterwards; they differ only
in whether each cancellation is passed on. Written twice, that is two
loops that must agree on which cancellation wins and on never reading
the task's outcome, so it is written once, in a module of its own,
because it belongs to neither owner: in `reply_in_flight.py` a reply
module would own a purge's lifetime, and in `pipeline.py`
`ReplyInFlight` would import its own owner. The interface is one
function:

```python
async def outlast(
    task: asyncio.Future[Any], *, hurry: bool = False
) -> asyncio.CancelledError | None:
    """Wait until `task` is done, however many times the caller is
    cancelled meanwhile, and answer the first of those cancellations,
    or None. With `hurry`, each one is passed on to the task as a
    `cancel()`; without it, the task is never cancelled from here.
    Never raises and never reads the task's outcome: retrieving it,
    and raising the answered cancellation once whatever it waited for
    is done, are the caller's."""
```

What its callers stop having to know: that `asyncio.wait` rather than
`await` is what keeps a cancellation of the waiter from reaching the
task, that a cancellation can arrive more than once, and which one
wins. It passes the deletion test on having two owners that would
otherwise each carry the loop; it is not a pass-through, since neither
caller's body would be simpler with it inlined. `hurry` is a keyword
rather than two functions because the loop is identical and the one
difference is a single call inside it. `ReplyInFlight.cancel` does not
use it: its caller's cancellation is meant to propagate at once, which
a single `asyncio.wait` already is.

Nothing above `close` changes: `_cleanly` already holds and re-raises
a `CancelledError` from it.

The two methods differ in exactly one decision, what a cancellation of
the caller means, and that is why they are two names rather than a
flag. For `cancel`, whose callers run on the serve loop, it means the
caller is being ended, so it propagates now and the reply is left to
its owner. For `close`, whose caller is the owner's last step, it means
the close is being hurried, so the reply is cancelled again and waited
out.

**Deviation from the review's wording:** the review asked for the
reply to be waited out *without* a second `task.cancel()`. The plan
passes the cancellation on instead, for two reasons. The reply's
`finally` is built for a second cancel: the only await between
`reply_finished` and the turn record is `filler.settle`, and its
`except BaseException` arm records the turn before re-raising, so a
hurried reply still records its turn before `close` returns, which is
the property the review is protecting. And a close that is being
cancelled is being asked to hurry: the second `task.cancel()` is an
attempt to expedite a tail that cooperates, which today's tail does at
every await, so the reply reaches its turn record and ends sooner than
it would if left to finish its sends to a closing device. It is not a
bound. `Task.cancel()` is cooperative, and a tail that ignored it
would wedge `close` either way; that risk is stated under "Risks" and
kept. Test 6 checks the turn lands before `close` returns with the
cancel arriving at the settle.

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

- `vinga-server/src/vinga_server/runtime/outlast.py` (new): `outlast`.
- `vinga-server/src/vinga_server/runtime/reply_in_flight.py`:
  `cancel`'s body and docstring, and the new `close` built on
  `outlast`.
- `vinga-server/src/vinga_server/runtime/pipeline.py`: `close` ends
  the reply through `ReplyInFlight.close` and outlasts the purge as a
  task it owns;
  `cancel_reply`'s docstring gains one sentence saying a cancelled
  caller leaves the handle in place.
- `vinga-server/tests/unit/test_outlast.py` (new): `outlast` directly.
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
6. **A cancelled close sees the reply through, then raises.** A
   runtime built with a purge spy, and a reply held at its tail's
   `filler.settle` (the stub `settle` the lifecycle suite already uses
   for this point, blocking on an event). The task running
   `runtime.close()` is cancelled while the reply is held there. Then:
   the reply's turn record has landed (the transcript collaborator or
   the store double the suite already uses) before `close()`'s task is
   done; `reply_in_flight(session)` is None; the purge spy was called
   with the session's current threads; the reply's task is done; and
   awaiting `close()`'s task raises `CancelledError`. With `close`
   built on the fixed `cancel` alone it fails (the purge is skipped and
   the reply is still running when the cancellation arrives), and with
   the purge skipped whenever a cancellation is held it fails on the
   spy; the implementer records both runs.
7. **A close cancelled twice still raises once, after the reply.** The
   same shape, with a second cancel delivered while the reply's
   (already hurried) tail is held on a later await; `close()`'s task
   still ends cancelled only after the reply's task is done. This pins
   the `while` loop: a mutation that waits once fails it.
8. **`ReplyInFlight.close` at value level**: a body whose `finally`
   notes the second `CancelledError` it receives. The caller of
   `close` is cancelled mid-wait; the body saw the second cancel, the
   task is done before the caller's `CancelledError` is observed, and a
   body ending in another exception with no caller cancellation still
   raises it, as `cancel` does.
9. **A held cancellation retrieves the reply's exception without
   chaining it.** The caller of `ReplyInFlight.close` is cancelled
   mid-wait, and the body's `finally` then raises a distinctive
   exception (`RuntimeError("the tail broke")`). Awaiting the caller
   raises `CancelledError` whose `__context__` and `__cause__` are
   None, and a loop exception handler installed for the test sees no
   "exception was never retrieved" report after a `gc.collect()`. A
   mutation raising `held` before reading `task.exception()` fails on
   the handler.
10. **A cancellation during the purge waits for the purge.** A
    runtime with no reply in flight and a purge spy that blocks on a
    `threading.Event`. The task running `close()` is cancelled while
    the purge is blocked; after the loop has run, that task is still
    not done; the event is set; the task then ends cancelled and the
    spy ran to completion exactly once. With the purge as a plain
    `await asyncio.to_thread(...)` it fails at "still not done".
11. **A reply that failed still purges, whatever it failed with.**
    Parametrized over a `RuntimeError` and a `BaseException` subclass
    that is not an `Exception`: a reply whose body raises it is
    closed; `close()` raises that exception and the purge spy was
    called. Fails against today's `close`, and the `BaseException` case
    fails with an `except Exception` arm.
12. **Both failing: the reply's is raised, the purge's retrieved.** A
    reply and a purge that each raise a distinctive exception.
    `close()` raises the reply's, and a loop exception handler sees no
    unretrieved-task report after a `gc.collect()`. Fails with
    `failed = failed or purging.exception()`.
13. **`outlast` directly** (`test_outlast.py`): cancelled twice while
    the task is held, it answers the first cancellation (by identity)
    only once the task is done; without `hurry` the task is never
    cancelled and finishes normally; with `hurry` the task receives
    one `cancel()` per held cancellation; a task already done answers
    None at once; and it raises nothing when the task failed, leaving
    the exception to be read.

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

- **A reply wedged in its tail wedges a close.** With `close` passing
  a cancellation on, a tail that ignores it (an `except BaseException`
  that loops, say) keeps `close` waiting, and so does one blocked on
  something that does not observe cancellation. Nothing in today's
  tail does either: every await in it is cancellable and its guard
  arms re-raise. The wedge is not introduced here, since today's
  `close` also waits the task out, but the second cancel does not
  remove it, and nothing in this plan claims it does. Mitigation:
  accept; a bound on the close path is a separate question, and it
  would belong to the session's close sequence rather than to one
  step of it.
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
  2. `runtime/outlast.py` and test 13.
  3. `ReplyInFlight.close`, `PipelineRuntime.close` built on both
     with the purge as an owned task, and tests 6-12, with the
     mutation runs recorded.
  4. The changelog fragment, this plan's tick, and the implementation
     doc's M1 section; the census manifests regenerated if either went
     stale.

  Design footprint: deepens `ReplyInFlight` (callers stop having to
  know that waiting out a cancelled reply could swallow their own
  cancellation, or that a close must outlast its reply before letting
  a cancellation through); adds one module, `runtime/outlast.py`,
  whose callers stop having to know how a task is waited out through
  their own cancellation and which cancellation wins; adds no seam.
  Documentation footprint as above.

## Plan review round

Reviewed 2026-09-24 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 5m37s, at commit 339c1744, plan blob 554b6ebf.

1. **P1: a cancelled close abandons the reply before session
   finalization.** The Goal promises `runtime.close()` sees the reply
   through, while Risks accepts that nothing awaits it after a
   cancelled close. With only the purge in a `finally`, `close()`
   exits while the reply is still in its tail, which can be blocked in
   `filler.settle` before the turn is recorded, not merely at the final
   device send. `_cleanly` then holds the cancellation and runs on
   through `session_closed`, the store's close, the capture's close and
   the export barrier, so the background reply can enqueue its turn
   after the session row has closed. Test 6 hides this by holding
   `HoldsTheFirstStop`, after `_record_turn`, and expects `close()` to
   raise with the reply still running. It contradicts the close path's
   contract that a cancellation is held until the record is complete
   (`test_a_cancelled_cleanup_step_still_finishes_the_record`). The
   plan should say `close()` preserves the caller's cancellation but
   delays it until the reply has finished, without a second
   `task.cancel()`, and until the purge has run; test cancellation at
   the filler-settle await, assert close stays pending, release, and
   assert the turn lands before session closure, `_in_flight` is
   cleared, the purge runs, no reply task remains, and only then does
   `CancelledError` reach the caller. Remove the risk acceptance and
   test 6.

   *Resolution:* accepted, with one deviation stated. `ReplyInFlight`
   gains `close(outcome)`, which waits the reply's task out through
   any number of caller cancellations, holds the first, and raises it
   only once the task is done; `PipelineRuntime.close` is built on it
   and purges in a `finally`, so the held cancellation reaches
   `_cleanly` after the turn is recorded, the handle is cleared and the
   purge has run ("`runtime.close()` sees the reply through, then
   re-raises"). The Goal now says so, the risk acceptance is gone, and
   test 6 is replaced by tests 6-8, with the cancel arriving at
   `filler.settle`. The deviation: a cancellation reaching `close` is
   passed on to the reply as a second cancel rather than held back
   from it, because the tail's `settle` arm already records the turn
   under a second cancel and holding it would make `close` unbounded
   where today it is bounded; the design section gives the reasoning
   in full.

Verdict: ready after the amendment.

## Plan review round 2 (re-review of the resolution)

Reviewed 2026-09-24 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 3m18s, at commit 1d868fde, plan blob 50d1bd17.

1. **P1: a second cancellation can skip the purge after the reply is
   finished.** `ReplyInFlight.close()` re-raises the held cancellation
   before `PipelineRuntime.close()` enters its purge `finally`, and a
   later cancellation while that `finally` awaits
   `asyncio.to_thread(self._purge, ...)` interrupts the await, so
   `_cleanly` proceeds to `session_closed`, the store's close and the
   export without waiting for the purge. Tests 6 and 7 cancel only
   while the reply tail is blocked. The plan should say
   `PipelineRuntime.close()` retains a cancellation across both the
   reply's completion and the purge's, with the purge as owned,
   waitable work not abandoned when its waiter is cancelled, the first
   held cancellation re-raised only after `_in_flight` is cleared and
   the purge has completed; and add an event-driven test that blocks
   the purge, cancels `close()` there, verifies it stays pending,
   releases, and verifies the cancellation propagates afterwards.

   *Resolution:* accepted. `PipelineRuntime.close` now runs the purge
   as a task it owns and outlasts, holding a cancellation across both
   steps and raising the first only after the reply's task is done,
   the handle is cleared and the purge has completed; the
   hold-until-done loop is one public function both `ReplyInFlight`
   and the purge use. Test 10 blocks the purge on a `threading.Event`,
   cancels there, and asserts `close` stays pending until release.
   Found while amending: a reply that failed skipped the purge today
   as well, since `cancel_reply` raised before it; the new shape
   reaches the purge on every path, and test 11 pins that.
2. **P1: `ReplyInFlight.close()` can leak an unobserved reply
   exception.** The sketch raises `held` before `task.result()`, and
   `asyncio.wait()` does not retrieve a task's exception. A reply whose
   cancellation path ends in another exception (the `filler.settle`
   guard re-raises any `BaseException`) then has it never retrieved
   before the handle is cleared, and asyncio's unretrieved-exception
   report can render exception text and chains, against the no-leak
   rules. Test 8 covers only an uncancelled caller. Retrieve the
   outcome even when a cancellation is held: with none held, keep
   `task.result()` propagation; with one held, mark a non-cancelled
   exception retrieved and re-raise the held cancellation without
   chaining the task's error into it. Test it with a cancelled
   `close()` caller and a `finally` raising a distinctive exception,
   asserting `CancelledError` and no unretrieved-task report at a loop
   exception handler.

   *Resolution:* accepted as written. The sketch reads
   `task.exception()` for a non-cancelled task before either raise, a
   held cancellation is raised outside any `except` arm so nothing is
   chained, and test 9 pins it with a loop exception handler and a
   distinctive exception.
3. **P2: the rationale describes the second cancel as a bound.**
   `Task.cancel()` is cooperative and cannot bound the wait, which the
   Risks section itself admits; describe it as an attempt to expedite a
   cooperative tail, relying on the `filler.settle` arm to record the
   turn, keep the wedge risk, and drop the claim of equivalence to a
   bounded close today.

   *Resolution:* accepted as written. The deviation paragraph now
   calls the second cancel an attempt to expedite a cooperative tail,
   relying on the `filler.settle` arm to record the turn, says in so
   many words that it is not a bound, and the Risks entry keeps the
   wedge and no longer implies today's close is bounded.

Verdict: ready after the P1/P2 amendments.

## Plan review round 3

Reviewed 2026-09-24 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 3m18s, at commit b726c709, plan blob af0a014a.

1. **P1: a reply failure can leave a purge failure unretrieved and
   leak its text.** `failed = failed or purging.exception()`
   short-circuits when the reply already failed, so a failed purge
   task is collected as "Task exception was never retrieved", with its
   text and chain. Tests 9 and 11 cover each failure alone. Retrieve
   the purge outcome unconditionally into a local, then pick the first
   failure; test both failing together, asserting the reply's failure
   is raised and a loop exception handler receives no unretrieved
   report after collection.

   *Resolution:* accepted as written. The purge's outcome is read
   into `purge_failed` unconditionally before the first failure is
   chosen, and test 12 pins both failing together.
2. **P2: the shared `outlast` has no decided home or interface.** The
   plan defers where the public function lives, the module layout
   names only two files, and the milestone claims no module is added.
   In `reply_in_flight.py` it gives a reply module an unrelated
   responsibility; in `pipeline.py` it makes `ReplyInFlight` depend
   upward on its owner. Name a small task-lifetime module, the exact
   signature and cancellation-result contract, test it directly, and
   update the layout.

   *Resolution:* accepted. `runtime/outlast.py` is decided, with the
   signature and contract written out ("The hold-until-done loop gets
   a module"), the reasons neither owner's module fits, a direct test
   (13), and the layout and design footprint updated.
3. **P2: "purge on every path" is contradicted by the exception
   boundary.** The sketch catches only `Exception` around
   `reply.close()` while `ReplyInFlight.close` re-raises any
   non-cancellation outcome, so a `BaseException` outcome bypasses the
   purge; test 11 covers only an ordinary exception, and the text still
   speaks of a purge `finally` the sketch does not have. Narrow the
   guarantee or make the purge reached on every outcome, and test the
   chosen scope.

   *Resolution:* accepted, choosing every outcome. The arm around
   `reply.close` catches `BaseException` after `CancelledError`, holds
   it, and raises it after the purge; test 11 is parametrized over an
   `Exception` and a non-`Exception` `BaseException`. The stale
   references to a purge `finally` are gone from the Tests and the
   layout.

Verdict: ready after the P1/P2 amendments.
