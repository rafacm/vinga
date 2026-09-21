# A reader who stops reading, in the window nobody measured

Plan for [#541](https://github.com/rafacm/vinga/issues/541). Its
companion is
`docs/plans/2026-09-21-broken-pipe-at-shutdown-implementation.md`, one
section per milestone, appended in the same change that ticks the
milestone.

**Local baseline:** not applicable. Nothing here changes a
conversational capability. What changes is the exit status and the
stderr of two commands that reach no server, and a device reaches
neither.

**Cheapest alternative:** the two `sys.stdout.flush()` lines and
nothing else. That is the whole behavior change, and the rest of this
plan is four tests and two corrected docstrings.
What they buy is stated where each is decided, but the headline is that
one of them pins a line the issue proposed deleting, and the
measurement below says deleting it would have reintroduced the very
symptom this issue is about. An unpinned load-bearing line is how this
issue came to propose removing it, so the pin is the part that stops
the next reader making the same offer.

## What was measured, before anything was decided

Every number below is from this repository at `4a23ed11`, on
`agentpi` (Raspberry Pi 5, Raspberry Pi OS, 16 KiB pages, so a default
pipe is 262,144 bytes), Python 3.12, with `PYTHONDONTWRITEBYTECODE=1`.
The generated event reference is **133,861 bytes** and
`vinga-server config openapi` is **455,602 bytes**; both print without
reaching a server.

The variants crossed below are the issue's two candidate edits:
**flush** is `sys.stdout.flush()` as the last statement inside the
`try` in `events_cli.main`, and **dup2** is the existing
`os.dup2(empty, sys.stdout.fileno())` in `reader_stopped_reading`,
present or replaced by `pass`.

### The issue's three regimes reproduce exactly

`events reference`, stdout on a pipe of the stated capacity, a reader
that reads one line and closes, one run per cell:

| variant | 16,384 | 65,536 | 131,072 | 262,144 |
| --- | ---: | ---: | ---: | ---: |
| committed (flush 0, dup2 1) | 141 | 141 | **120** | 0 |
| flush 0, dup2 0 | 141 | 141 | 120 | 0 |
| flush 1, dup2 1 | 141 | 141 | **141** | 0 |
| flush 1, dup2 0 | 141 | 141 | **120** | 0 |

Every 120 carries `Exception ignored in: <_io.TextIOWrapper
name='<stdout>' ...  BrokenPipeError: [Errno 32] Broken pipe` on
stderr; every 141 and every 0 has empty stderr. The first row is the
issue's reproduction, reproduced.

### The finding that inverts the issue's M3

Read the third and fourth rows together. **With the flush fix in
place, removing the `os.dup2` redirect puts the failure back**: 141
becomes 120, with the same complaint on stderr. The redirect is not
dead code. It is load-bearing, and it is load-bearing in exactly one
regime, the one the bug lives in.

The reason nobody could see it is in the first and second rows, which
are identical: **without** the flush, the redirect changes nothing at
any capacity, because the failure arrives at interpreter shutdown
where `reader_stopped_reading` never ran. So the issue's observation
that deleting the line leaves the suite green is correct, and its
inference that the line is therefore inert is not. The line's job only
begins once the flush gives it a `BrokenPipeError` to catch, which is
to say M1 of this plan is what makes M3's question answerable at all.

The mechanism, measured rather than recalled. The issue and the
session notes both hypothesize that "CPython drops the buffered data
when a flush fails, leaving the shutdown flush with nothing to write".
That is **false**, and a real process says so in eight lines: write a
payload into `sys.stdout` with the read end of the pipe already
closed, flush, catch, call `reader_stopped_reading`, exit.

| payload | dup2 1 | dup2 0 |
| ---: | --- | --- |
| 100 bytes | 141, empty stderr, 5/5 | **120**, `Exception ignored`, 5/5 |
| 8,000 bytes | 141, empty stderr, 5/5 | **120**, `Exception ignored`, 5/5 |
| 20,000 bytes | 1, a traceback | 1, a traceback |

The buffer is retained across the failed flush, which is why the
interpreter's own flush raises again, which is what the redirect is
for. The 20,000-byte row is the boundary of the construction rather
than a result about vinga: a write larger than the stream's buffer
goes straight to the descriptor and raises inside `write`, before any
of this is reached.

### `config/cli.py` has the same defect, now measured rather than read

The issue says this one "has been read rather than measured". It is
measured now, against `config openapi` (455,602 bytes) through the
deterministic construction described below, three runs per cell:

| variant | exit | stderr |
| --- | ---: | --- |
| committed | **120**, 3/3 at each of two deltas | `Exception ignored ...` |
| `sys.stdout.flush()` after `_parsed(...)` | **141**, 3/3 at each | empty |

### Why the regime cannot be left to a race, and what replaces it

The obvious way to write a regression test, a pipe of a chosen
capacity and a reader that reads one line and closes, is not stable
under things that have nothing to do with the code. Same capacity,
same document, same commit, five runs each, varying only how the
reader is opened:

| reader | 65,536 | 131,072 | 262,144 |
| --- | ---: | ---: | ---: |
| `os.fdopen(fd, "r")`, one `readline` | 141 | **120** | 0 |
| `os.fdopen(fd, "rb")`, one `readline` | 141 | **0** | 0 |
| closed without reading | 141 | 141 | 141 |

Each row is 5/5 stable and the rows disagree, because how much the
reader happens to drain before closing decides how much the writer
gets to absorb. A test built on this pins the reader's buffering
strategy, which is the same class of mistake as pinning the platform's
page size.

So the deterministic construction, which is what the plan's tests and
measurements use where a real process is needed:

1. Take a pipe whose capacity is the next power of two above the
   document, and **pre-fill it** so the free capacity is exactly
   `len(document) - delta`. The child therefore cannot finish, by
   exactly `delta` bytes, whatever the document's size is.
2. Start the child and **read nothing**.
3. Poll `FIONREAD` until the byte count stops moving, which is the
   child having written everything it is going to write.
4. Close the read end.

`delta` of 1, 1,024, 4,096 and 8,191, three runs each, twelve runs per
variant: committed 120 every time, flush-only 120 every time, flush
plus redirect 141 with empty stderr every time. Nothing here depends
on the platform's default pipe capacity, and nothing depends on when
the reader is scheduled.

## What this plan does

### The fix

`sys.stdout.flush()` as the last statement inside the `try`, in
`events_cli.main` and in `config.cli.main`. It moves the failure from
interpreter shutdown, where nothing catches it, into the `except`
arm that exists for it. Both were measured above. Nothing else in
either module changes.

### What gets pinned, and by what

Four claims, four tests. Three of them are narrow on purpose, because
they fail for three different reasons and a single test covering all
three would say only that something is wrong; the fourth is the
end-to-end regression that holds the composition of them together,
since a narrow test cannot see a change in dispatch, stream wrapping,
encoding or buffering that reintroduces the symptom with all three
still green.

- **`events_cli.main` flushes inside the `try`.** In process, with a
  `sys.stdout` whose `write` succeeds and whose `flush` raises
  `BrokenPipeError`: `main` must answer `BROKEN_PIPE_STATUS` and print
  nothing. This is the same shape as the `_ClosedPipe` test that
  already sits in `test_config_cli_events.py`, which raises from
  `write` instead, and the pair is the point: one pins the failure a
  command meets while writing, the other the failure it meets only
  when its buffer is emptied.
- **`config.cli.main` flushes inside the `try`.** The same test beside
  the existing `_ClosedPipe` one.
- **`reader_stopped_reading` redirects, so a retained buffer cannot
  raise at shutdown.** A real process, because interpreter shutdown is
  the only place this is observable and no in-process test reaches it.
  The eight-line construction measured above: a payload smaller than
  the stream's buffer, a read end closed from the start, and an
  assertion of exit 141 with empty stderr. Its falsification is
  recorded above and is the whole reason it exists: replace the
  `os.dup2` line with `pass` and this test goes to 120 with the
  interpreter's complaint on stderr, 5/5.

- **`events reference` answers 141 with empty stderr in the near-fit
  regime.** The end-to-end regression the issue asks for, and the only
  test here that runs the real command through the real failure. Its
  construction is the deterministic one measured above, and its two
  guards are what make it a regression test rather than a hopeful one:

  - **The regime is chosen, not inherited.** The free capacity is set
    to `len(document) - len(document) % io.DEFAULT_BUFFER_SIZE`, the
    document's whole-chunk part, by creating a pipe of the next power
    of two above the document and pre-filling it with the difference.
    The child then writes exactly the chunks that fit exactly, and
    retains the remainder, whatever the document's size has grown to.
    A remainder of zero would leave nothing retained, so the test
    asserts it is non-zero and says in its message what to do if the
    catalog ever lands on a multiple.
  - **The synchronization is bounded, and its conclusion is checked.**
    The parent reads nothing and polls `FIONREAD` until the count
    stops moving, with a deadline that fails the test rather than
    hanging it. What makes that poll safe is the assertion after it:
    the pipe must be **exactly full**, which is what the construction
    predicts and what a poll that fired early cannot produce, since a
    child still writing leaves it short. Measured full in all fifteen
    runs for this document, and measured 8,192 short for a larger one,
    so the assertion is known to be capable of failing.

  Then exit 141 and empty stderr, each with a message naming the
  mid-write regime as the thing to suspect.

The redirect test gets a new home, `tests/unit/test_broken_pipe.py`.
`broken_pipe.py` has no test file of its own today; its two claims are
asserted in the docstrings of tests belonging to two other modules,
and one of those claims is false. A module whose interface is two
names deserves a test surface of its own, and the docstrings then
point at it rather than at each other.

### The two docstrings

Both are corrected in the same milestone as the behavior, because both
describe it.

- `broken_pipe.py`'s module and function docstrings say the redirect is
  needed because the interpreter's final flush would raise again. That
  is **true**, and now demonstrated, so what it gains is the naming of
  the test that demonstrates it and the removal of the reason it gave,
  which was a description of the shutdown path rather than of the
  retained buffer.
- `test_config_cli_events.py::test_a_reader_who_stops_reading_gets_the_shell_s_own_status`
  says the redirect is "pinned in a real process by
  `test_event_docs.test_a_reader_who_stops_reading_gets_no_traceback`".
  That is **false today**: that test passes with the line deleted, at
  every capacity, on both machines this has run on. It is corrected to
  name `test_broken_pipe.py`, which does pin it.

### The existing real-process test stops asserting a property of the machine

`test_event_docs.py::test_a_reader_who_stops_reading_gets_no_traceback`
inherits the platform's default pipe capacity and needs it to be
smaller than the document. On a 16 KiB-page kernel it is not: the
default pipe is 262,144 bytes, the document is 133,861, the child
finishes, and the test fails with a bare `assert 0 == 141`. It fails
5/5 on `agentpi` today and passes in CI, whose x86_64 runner has 4 KiB
pages and therefore a 65,536-byte pipe.

It narrows the pipe to one page with `F_SETPIPE_SZ`, falling back
silently where that is unsupported (macOS has no such command and
refuses with `OSError`, leaving a 64 KiB default that still overflows),
and its assertion carries a message naming the cause. Widening the
assertion to `status in (0, 141)`, or skipping on capacity, is refused
for the reason the issue gives and the storage lane already
establishes: a test that goes green by ceasing to exercise the path is
worse than one that fails.

## What this plan rejects, and why

- **Deleting the `os.dup2` redirect**, which the issue offers as one of
  M3's two outcomes. Measured load-bearing, twelve runs to one
  construction and five to another. This is the finding the issue
  asked for and it points the other way.
- **A second end-to-end near-fit test, for `config openapi`.** One is
  committed, for `events reference`, and the config CLI's own flush is
  pinned in process instead. The two `main` functions differ in what
  they wrap, not in how they buffer, so a second real-process test
  would re-prove the composition rather than a second behavior, and
  `config openapi` is measured above to retain more than one buffer's
  worth, which is what puts the fullness assertion out of reach for it.
  What the config CLI gets is its in-process flush pin and the
  by-hand measurement recorded in this plan.
- **Flushing anywhere other than the last statement inside the `try`.**
  A `finally`, or a flush in `reader_stopped_reading`, would either run
  on paths that did not write or raise outside the arm that catches it.
- **`signal.signal(SIGPIPE, SIG_DFL)`**, the other common remedy. It
  makes the process die of the signal rather than answer a status,
  which is a different contract from the one `broken_pipe.py` records,
  and it would take the sanitizing boundary with it: a command killed
  by a signal runs no `except` arm, so nothing else this CLI promises
  about stderr would hold on that path.

## Milestones

- [ ] **M1: the failure surfaces where it is already caught**.
  `sys.stdout.flush()` as the last statement inside the `try` in
  `src/vinga_server/events_cli.py` and in
  `src/vinga_server/config/cli.py`. Three tests: the two in-process
  flush pins, one beside the existing `_ClosedPipe` test in
  `tests/unit/test_config_cli_events.py` and one in
  `tests/unit/test_event_docs.py`, and the real-process redirect pin in
  a new `tests/unit/test_broken_pipe.py`. And the fourth, the
  end-to-end near-fit regression on `events reference`, in
  `tests/unit/test_event_docs.py` beside the test M2 then repairs. The two docstring
  corrections. A `### Fixed` changelog fragment at
  `changelog.d/541-broken-pipe-at-shutdown.md`. The
  implementation-doc section and this checklist item ticked with its PR
  number and linked to that section.
  **Design footprint:** `broken_pipe.py` gains a test surface of its
  own and keeps its interface unchanged; nothing else moves. No new
  module, no new seam, and no deepening claimed: the change is two
  statements and the tests that hold them.
  **Documentation footprint:** none under `docs/` and none in any
  README. Checked rather than assumed: no user-facing page quotes
  `| head` against either command, and no page states either command's
  exit status. The claims this milestone corrects are both docstrings,
  which ship with the code they describe. `docs/reference/events.md` is
  generated and its content is untouched.
- [ ] **M2: the real-process test sets the capacity it needs**.
  `test_event_docs.py::test_a_reader_who_stops_reading_gets_no_traceback`
  narrows its own pipe to one page and stops inheriting the platform's
  default, and its status assertion carries a message naming the cause
  and forbidding the widening that would make it green and empty. The
  implementation-doc section and the tick.
  **The order of operations is the whole of it**, because the obvious
  spelling does not work: `Popen(stdout=subprocess.PIPE)` creates the
  pipe itself and the child is already writing before the parent could
  reach `child.stdout`, so a resize applied there changes nothing on
  the host this is for. The pipe is therefore created with `os.pipe()`,
  sized with `F_SETPIPE_SZ` to `resource.getpagesize()` and the
  fallback decided, all **before** the child starts; the sized write
  descriptor is passed as `stdout`, the parent closes its copy
  immediately after the spawn, and the test reads through
  `os.fdopen(read_fd)`. The fallback is silent, because where
  `F_SETPIPE_SZ` is absent or refused (macOS has no such command and
  raises `OSError`) the platform default of 64 KiB still overflows the
  document, which is the state every machine this test has run green on
  was already in.
  **Design footprint:** none. One test stops reading a value from the
  platform and states it instead.
  **Documentation footprint:** none.

## Tests and verification

From `vinga-server/`, for each milestone:

- `uv run ruff check .` and `uv run mypy`.
- `uv run pytest tests/unit -q`. On a 16 KiB-page host this lane has
  **one pre-existing failure** before M2 lands, the test M2 fixes. M1's
  PR says so in those words rather than claiming a green lane it does
  not have; CI is unaffected, because its 4 KiB pages put the same test
  in the regime it was written for.
- `uv run pytest tests/integration -q` and the generated-document drift
  checks.
- `uv run pytest tests/census -q`, because both milestones add
  documents that quote command spellings and both touch files under
  `tests/`. A stale manifest is regenerated with
  `uv run python -m tests.census.test_command_spellings` or
  `uv run python -m tests.census.test_reach_ins`, never edited by hand.

And the falsifications, each run before its claim is made, with the
count stated because two of them are about a mutation rather than a
value:

- The redirect pin, with `os.dup2(empty, sys.stdout.fileno())`
  replaced by `pass`: must fail, and must fail by reporting 120 with
  `Exception ignored` rather than by any other route. Already run,
  5/5, before this plan was written.
- Each in-process flush pin, with the new `sys.stdout.flush()` removed
  from the module it covers: must fail. One run each is enough; this is
  straight-line logic and a repeat would be noise.
- The end-to-end near-fit test, with the new `sys.stdout.flush()`
  removed from `events_cli.main`: must fail, and must fail by reporting
  120 with `Exception ignored` rather than by its fullness assertion or
  its deadline, since those two failing would mean the construction
  missed the regime rather than the code being wrong. Already run at
  plan time, 5/5 on each side of the mutation.
- The issue's own reproduction script, by hand, against the merged
  fix: exit 141 with empty stderr at 16,384, 65,536 and 131,072, and
  exit 0 at 262,144. Recorded in the implementation doc with the
  numbers it printed.

CI's default pipe would not reproduce the bug: on 4 KiB pages it is
65,536 bytes against a 133,861-byte document, which is the
cut-off-mid-write regime. That is why the near-fit test sizes and
pre-fills its own pipe rather than using the default, and it is the
one test here that reaches the near-fit regime; the two in-process
pins reach a stdout that raises, and the redirect pin reaches a
retained buffer, and neither of those is that regime. So CI does run
the reported failure, on its own runner, through the construction
rather than through the page size.

## Risks

- **The document grows past the near-fit window.** The event catalog
  grows, and with it the capacity at which the bug is reachable. This
  is a risk to the hand-run reproduction above and not to the
  near-fit test, which derives its capacity from the document it just
  rendered rather than naming one. The implementation doc records the
  document's size on the day, so a later reader knows which capacities
  to re-derive rather than reusing these.
- **`F_SETPIPE_SZ` is Linux-only.** M2 falls back silently, which is
  the behavior every platform this has run green on already had. The
  fallback is exercised nowhere in CI, so it is stated as untested
  rather than claimed: what is known is that macOS refuses with
  `OSError` and its 64 KiB default still overflows the document.
- **A payload-based redirect pin depends on the stream's buffer size.**
  The test writes 100 bytes, two orders of magnitude below the 8,192
  measured boundary, so a future buffer size would have to shrink by a
  factor of eighty to reach it. If it ever does, the test fails loudly
  with a traceback and exit 1, which is the 20,000-byte row above, not
  silently.

## Plan review round

External adversarial review of this plan at `f9b27251`, run read-only
in the worktree. Backend codex, `codex-cli 0.155.1`, model
`gpt-5.6-sol`, 2026-09-21, reviewer runtime 140s. Verdict: ready after
the P1 and P2 amendments. Two findings, both accepted.

The prompt named six small files to read in full and pasted the
nineteen relevant lines of `config/cli.py` (9,667 lines) rather than
naming it, together with an explicit instruction not to open it or
`vinga-server/README.md`. That is the recorded remedy for sol
returning empty stdout at exit 0 on this repository's large files, and
this round came back with a body.

### 1 (P1): M2 does not say how the pipe is sized, and the obvious way does not work

Resizing through `child.stdout` after `Popen` creates the pipe leaves
the child already writing before `F_SETPIPE_SZ` lands, which preserves
the exact race M2 exists to remove, and on a 262,144-byte host the
child can finish first. The pipe must be created with `os.pipe()` and
sized before the child starts, with the already-sized write descriptor
passed as `stdout`, the parent's copy closed, and the read descriptor
used for reading. The unsupported-platform fallback has to be decided
before the child starts too.

*Resolution*: accepted as a specification gap, and M2 now states the
mechanism. The finding is right that the plan did not say it, and the
sequence it prescribes is the one that was already prototyped and
verified 5/5 on two machines before this issue was filed; the plan
described the outcome and left the order of operations implied, which
is exactly the kind of thing a milestone brief then gets wrong.

### 2 (P2): the committed tests never run the real command through the near-fit path

The three proposed tests prove separately that `main` flushes and that
`reader_stopped_reading` redirects a retained buffer, but none of them
runs `events reference` through the near-fit shutdown path, so the
plan's sentence claiming "the near-fit regime is reached by the tests'
own construction" is false. A change in entrypoint dispatch, stream
wrapping, encoding, buffering or process termination could restore
exit 120 with all three green. Keep one deterministic real-process
near-fit regression built on the plan's own pre-filled-pipe
construction, with a bounded synchronization mechanism, assertions for
exit 141 and empty stderr, and an explicit guard on the retained-tail
precondition so the test fails rather than silently entering the
mid-write regime.

*Resolution*: accepted in full, and the rejection it overturns was the
worse of this plan's two judgement calls. The issue's M1 asks for this
test in as many words, which makes it a settled decision rather than
something to price on proportion, and the sentence the finding quotes
is this session's recurring error: it claimed for three tests a
property only a fourth one has. The test is added to M1, the rejection
bullet is gone, and the sentence is corrected.

The guard the finding asks for is now a measured construction rather
than an intention. Set the free capacity to
`len(document) - len(document) % io.DEFAULT_BUFFER_SIZE`, which is the
document's whole-chunk part, so the child writes exactly the chunks
that fit exactly and retains the remainder. The pipe then ends
**exactly full**, and that is the assertion that catches a settle-poll
which fired early, because a child still writing leaves it short.
Measured at `f9b27251`, five runs per variant: `events reference`
(133,861 bytes, remainder 2,789) fills the pipe to exactly 262,144 in
all fifteen runs, committed code exits 120, the flush fix exits 141
with empty stderr, and the flush fix without the redirect exits 120
again. The same construction against `config openapi` (455,602 bytes)
comes up 8,192 short, because a larger document retains more than one
buffer's worth, and that is the evidence that the fullness assertion
is a real check rather than a tautology: it can fail, and when it
fails it fails red.
