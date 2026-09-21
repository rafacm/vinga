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
plan is three tests and two corrected docstrings, about sixty lines.
What they buy is stated where it is decided, but the headline is that
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

Three claims, three tests, and they are deliberately three rather than
one end-to-end test, because they fail for three different reasons and
a single test that covers all three says only that something is wrong.

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

That third test gets a new home, `tests/unit/test_broken_pipe.py`.
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
- **A real-process, end-to-end, near-fit test of `events reference`
  itself.** It is buildable: the deterministic construction above does
  exactly this and is what produced the plan's numbers. It is rejected
  on proportion. It costs the pre-fill arithmetic, a `FIONREAD` poll
  loop and a settling heuristic, roughly forty lines of machinery, to
  assert a composition of two things that are each pinned in eight
  lines by the tests above. It also carries a silent failure mode the
  cheap tests do not: when the document's length happens to be an
  exact multiple of the stream's buffer size there is no retained tail,
  the construction falls into the ordinary cut-off-mid-write regime,
  and the test stays green while testing nothing. That is the
  green-and-empty shape this issue exists to refuse, so the plan does
  not introduce a new instance of it. The construction stays in this
  document and in the verification below, where it is run by hand and
  its regime is checked by a human reading the numbers.
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
  a new `tests/unit/test_broken_pipe.py`. The two docstring
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
  narrows its own pipe with `F_SETPIPE_SZ` to one page, falls back
  silently where unsupported, and its status assertion carries a
  message naming the cause and forbidding the widening that would make
  it green and empty. The implementation-doc section and the tick.
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
- The issue's own reproduction script, by hand, against the merged
  fix: exit 141 with empty stderr at 16,384, 65,536 and 131,072, and
  exit 0 at 262,144. Recorded in the implementation doc with the
  numbers it printed.

CI cannot reproduce the bug: on 4 KiB pages the default pipe is 65,536
bytes against a 133,861-byte document, which is the cut-off-mid-write
regime. What CI verifies is that the fix and the tests break nothing,
and the near-fit regime is reached by the tests' own construction
rather than by the runner's page size, which is why the two in-process
pins and the redirect pin run everywhere.

## Risks

- **The document grows past the near-fit window.** The event catalog
  grows, and with it the capacity at which the bug is reachable. This
  is a risk to the hand-run reproduction above, not to the committed
  tests, which is the reason the committed tests do not use pipe
  capacity as their variable. The implementation doc records the
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
