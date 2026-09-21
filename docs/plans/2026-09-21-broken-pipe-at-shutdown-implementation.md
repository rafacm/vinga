# A reader who stops reading, in the window nobody measured: implementation

Companion to
[`2026-09-21-broken-pipe-at-shutdown.md`](2026-09-21-broken-pipe-at-shutdown.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the failure surfaces where it is already caught

### What landed

| Piece | Where |
| --- | --- |
| The flush, events group | `vinga-server/src/vinga_server/events_cli.py`, last statement inside `main`'s `try` |
| The flush, configuration group | `vinga-server/src/vinga_server/config/cli.py`, the same position in `main` |
| The in-process flush pin, events | `vinga-server/tests/unit/test_event_docs.py`, `test_a_reader_who_stops_reading_between_chunks_gets_the_status`, with `_EmptiedIntoAClosedPipe` beside it |
| The in-process flush pin, configuration | `vinga-server/tests/unit/test_config_cli_events.py`, the same name, beside the existing `_ClosedPipe` |
| The redirect pin, in a process of its own | `vinga-server/tests/unit/test_broken_pipe.py`, `test_a_retained_buffer_cannot_raise_at_interpreter_shutdown`, a new file |
| The end-to-end near-fit regression | `vinga-server/tests/unit/test_event_docs.py`, `test_a_reader_who_stops_reading_mid_chunk_gets_no_traceback`, with `queued` and `settled` beside it |
| The two docstring corrections | `vinga-server/src/vinga_server/broken_pipe.py` (module and `reader_stopped_reading`) and `test_config_cli_events.py::test_a_reader_who_stops_reading_gets_the_shell_s_own_status` |
| The changelog fragment | `changelog.d/541-broken-pipe-at-shutdown.md`, `### Fixed` |
| The census manifest | `vinga-server/tests/census/command-spellings.txt`, one line added: `respell  config openapi` |

### One deviation: the configuration pin drives `openapi`, not the tail

The plan says the configuration flush pin is "the same test beside the
existing `_ClosedPipe` one", which reads as the same command. It is
beside it and it is not the same command, and what forced the change is
a property of the tail that nothing had written down: `events tail`
flushes after every line it prints, so that `| head -n 1` answers before
the next event arrives rather than after the next eight kilobytes.
`main`'s flush is therefore never what the tail's remainder meets.

The first version of this test was driven through the tail, and it
**passed with the fix removed**. That is the falsification requirement
earning its place rather than confirming something already believed: the
test was worth nothing and one mutation said so in three seconds.
`openapi` prints one long document and leaves the emptying to the
boundary, which is every other row of the grammar's shape and the one
the pin is about. The test's docstring says all of this where it is
driven, so the next reader does not move it back.

Nothing else departs from the plan.

### The mechanism, read at the syscall rather than inferred

The plan measured the behavior and named the retained buffer. What M1
added, because the near-fit construction cannot be written without it,
is why the remainder is retained and why the construction's arithmetic
is what it is.

A blocking write to a pipe with no room sleeps until there is room. When
the reader closes instead, Linux does not fail that write: `pipe_write`
returns the byte count it had already placed, and only a write that
placed nothing returns `EPIPE`. So the child's one large raw write comes
back short rather than broken. CPython's `BufferedWriter` then loops
only while what is left exceeds its own buffer, so a remainder under
8,192 bytes is kept rather than retried, and `write` returns as if the
whole document had gone out.

That is the whole of why the free capacity has to be the document's
**whole-chunk** part. Set it anywhere else and the remainder can exceed
one buffer, the loop retries, the retry gets `EPIPE` with nothing
placed, and `BrokenPipeError` is raised inside `write`, which every
version of this code has answered correctly. The construction is not
merely a convenient capacity: it is the only one that lands in the
regime the bug lives in.

### The document on the day

Recorded because the plan's first risk asks for it: the catalog grows,
and with it the capacities at which any of this is reachable.

| Quantity | Value |
| --- | ---: |
| `vinga-server events reference`, bytes | 133,861 |
| `io.DEFAULT_BUFFER_SIZE` | 8,192 |
| Remainder, the part that stays retained | 2,789 |
| Whole-chunk part, the free capacity the test sets | 131,072 |
| Next power of two above the document, the pipe's capacity | 262,144 |
| Pre-fill | 131,072 |
| Host page size, and therefore the default pipe capacity | 16,384 and 262,144 |

The test derives every one of these from the document it has just
rendered, so none of them is written down in it.

### Falsification

Every claim was watched red before it was made, and the tree was watched
green again after each restore. Restores were made by copying the file
back from a copy taken beforehand, never with `git checkout`, and each
restored file was touched and its caches cleared.

| Mutation | Test | How it failed |
| --- | --- | --- |
| `sys.stdout.flush()` removed from `events_cli.main` | the events in-process pin | `assert 0 == 141` |
| `sys.stdout.flush()` removed from `config.cli.main` | the configuration in-process pin | `assert 0 == 141` |
| `os.dup2(empty, sys.stdout.fileno())` replaced by `pass` | the redirect pin | the `Exception ignored` assertion; by hand, exit 120 with `Exception ignored in: <_io.TextIOWrapper name='<stdout>' mode='w' encoding='utf-8'>` and `BrokenPipeError` |
| `sys.stdout.flush()` removed from `events_cli.main` | the near-fit regression | the `Exception ignored` assertion; by hand, exit 120 with the same stderr |
| `os.dup2(empty, sys.stdout.fileno())` replaced by `pass` | the near-fit regression | the same assertion, the same status |
| The tail rather than `openapi` (a construction fault, not a code one) | the configuration in-process pin | it did not fail, which is what found the per-line flush |

The near-fit regression's two mutations matter for **how** they failed
as much as that they did. The plan requires that it fail by reporting
120 with `Exception ignored`, and not by its fullness assertion or its
deadline, since either of those would mean the construction had missed
the regime rather than the code being wrong. Both mutations got past the
fullness assertion, so the pipe was exactly full at 262,144 in every
mutated run as well as in every clean one.

### The fullness assertion is a real check

Its message claims it can fail, so it was made to. The same construction
against the much larger `config openapi` document, 455,602 bytes:
whole-chunk part 450,560, capacity 524,288, pre-fill 73,728, and the
pipe settles at **516,096**, exactly 8,192 short, because a larger
document retains more than one buffer's worth and the writer's loop
therefore runs one more time. The command still exits 141 with empty
stderr, which is the configuration group's own fix working end to end in
the mid-write regime.

### The issue's reproduction, by hand against the fix

The plan's fourth verification item, run against the merged tree at four
capacities with a reader that reads one line and closes:

| Pipe capacity | Status | stderr |
| ---: | ---: | --- |
| 16,384 | 141 | empty |
| 65,536 | 141 | empty |
| 131,072 | 141 | empty |
| 262,144 | 0 | empty |

Every row is what the plan predicted. The 131,072 row is the one that
reported 120 with `Exception ignored` before this milestone, and it is
the regime the near-fit test now reaches without depending on a
capacity.

### Two decisions the plan did not settle

**`fcntl` does export the pipe commands.** The milestone brief said the
module does not re-export `F_SETPIPE_SZ` and `F_GETPIPE_SZ` and gave
their numeric values. On Python 3.12 it does: `fcntl.F_SETPIPE_SZ` is
1031 and `fcntl.F_GETPIPE_SZ` is 1032. The test reads the attribute
rather than the number, which is better than either: the attribute is
absent exactly where the command is, so its absence is the portable
signal rather than a platform list to keep current.

**The near-fit test skips where a pipe cannot be resized.** This is a
platform it cannot run on rather than a capacity it does not like, and
the plan refuses only the second. The construction needs a capacity
above the document, and on macOS there is no command to ask for one, so
there is nothing to exercise rather than something exercised less well.
The skip is explicit in its reason, it is unreachable on every machine
this repository's lanes run on, and `pytest.skip` is also what answers a
resize the kernel refuses, with the errno in the message.

### Verification

- `uv run ruff check .`: all checks passed.
- `uv run mypy`: success, no issues found in 5 source files.
- `uv run pytest tests/unit -q -ra`: **1 failed, 7,394 passed, 19
  skipped** in 1,715.69 s. The one failure is the pre-existing one this
  plan names,
  `test_event_docs.py::test_a_reader_who_stops_reading_gets_no_traceback`,
  with `assert 0 == 141`, and it is M2's to fix: this host has 16 KiB
  pages, so the platform's default pipe is 262,144 bytes against a
  133,861-byte document and the child finishes writing. It fails on this
  machine at `main` too. CI is unaffected, because a 4 KiB-page runner
  puts the same test in the regime it was written for. The 19 skips are
  the `faster-whisper` and `piper` extras.
- `uv run pytest tests/integration -q -ra`: 346 passed in 524.10 s.
- `uv run pytest tests/census -q -ra`: 66 passed. One manifest moved and
  was regenerated rather than edited:
  `command-spellings.txt` gained `respell  config openapi`, because this
  milestone's tests and this document quote that invocation for the
  first time. The reach-in manifest did not move: the new tests reach
  `main`, `BROKEN_PIPE_STATUS` and `reader_stopped_reading`, which are
  the three public names these modules have.
- `uv run python scripts/check_doc_links.py .`: 257 files, 0 failures.
- `uv run python scripts/fold_changelog.py check .`: 1 fragment, 0
  failures.

### PR review round

External adversarial review of PR [#542](https://github.com/rafacm/vinga/pull/542)'s
diff against `origin/main`. Backend codex, `codex-cli 0.155.1`, model
`gpt-5.6-sol`, 2026-09-21. Verdict: mergeable after the one listed fix.
One finding.

**1 (P2): the completed milestone still links to `PR TBD`.** The
checklist item is ticked and its implementation-doc link resolves, but
the pull request it names is a placeholder, which AGENTS.md requires to
be the number.

*Resolution*: accepted and fixed in the commit that carries this
section. The placeholder is the pipeline's own ordering (the milestone
is ticked in the change that completes it, which is necessarily before
the pull request exists), so what the finding catches is the
substitution not having happened yet rather than a decision.

An empty round on the substance is worth recording as such rather than
reading as a clean bill: the reviewer had the whole diff, including the
four tests and the two docstring corrections, and returned nothing
about them.
## M2: the real-process test sets the capacity it needs

### What landed

| Piece | Where |
| --- | --- |
| The sized pipe | `vinga-server/tests/unit/test_event_docs.py`, `narrowed_pipe`, beside the test that uses it |
| The test that stops inheriting a capacity | the same file, `test_a_reader_who_stops_reading_gets_no_traceback` |
| The status assertion's message | the same test, naming the cause and refusing the two widenings |

No production code moved and no other test did. This milestone is one
test that stops reading a number off the machine and states it.

### One deviation: `SET_PIPE_SIZE` moved up

M1 put `SET_PIPE_SIZE = getattr(fcntl, "F_SETPIPE_SZ", None)` with the
near-fit test, which was the only thing that wanted it. Two tests want
it now, and the plan does not say where it should live when that
happens. Defining it twice is the rule against two structures that must
agree, so the constant moved up to the head of the real-process section
and its comment now carries both readings of its absence: the test that
narrows an inherited pipe still has a pipe without the command, so it
runs, and the test that needs a pipe larger than the document has no
construction without it, so it skips. That is the whole of the
deviation, and neither of M1's four tests was otherwise touched.

### Why the fallback is silent here and a skip there

The two judgements look inconsistent read side by side, so the reason is
written down where each one is made. What `F_SETPIPE_SZ` buys this test
is a *narrower* pipe than the platform's, and the platform's is already
narrow enough everywhere the command is missing: macOS defaults to
65,536 bytes against a 133,861-byte document, which is the regime this
test was written for and the one it has always run in. Losing the
command costs it a regime chosen badly rather than no regime at all, so
it runs. The near-fit test needs a pipe *wider* than the document, which
no platform hands out by default and only that command can ask for, so
without it there is nothing to exercise. The plan refuses a skip on
capacity and this is not one: it is a skip on a construction that cannot
be built.

### The failure it fixes, watched in both directions

| Run | Result |
| --- | --- |
| Before the change, on this host | `assert 0 == 141`, the bare failure the plan names |
| After the change | passed, 5 runs out of 5 |
| With the resize made a no-op, as if the platform had refused | failed, and failed through the new message before `assert 0 == 141` |

The mutation is the one that matters, because the fallback is the part
of this change nothing else checks. Replacing the `fcntl.fcntl` call with
`pass` puts the test back on the host's 262,144-byte default, which is
exactly what an unsupported platform leaves it with, and the failure
that comes back is the explanatory one rather than the bare compare.
This host is therefore a machine where the silent fallback can be
observed failing, which macOS, where the fallback is real, is not: there
the default is small enough that the test passes on it.

The document on the day is M1's table above, unchanged: 133,861 bytes,
against a pipe this test now sets to one page, 16,384 bytes on this
host.

### No changelog fragment

Judged rather than skipped. M1's `### Fixed` fragment describes the
user-visible change, which is the exit status and the stderr of two
commands, and this milestone changes neither. What it changes is which
machines a test is honest on, and a person running vinga meets nothing
of it. A second fragment would say "a test now sizes its own pipe" under
a heading meant for behavior.

### Verification

- `uv run ruff check .`: all checks passed.
- `uv run mypy`: success, no issues found in 5 source files.
- `uv run pytest tests/unit -q -ra`: **7,395 passed, 19 skipped** in
  1,705.62 s, no failures. M1 left this lane with one, the test this
  milestone repairs, and the plan says the lane is green on a 16 KiB-page
  host once M2 lands. It is. The 19 skips are the `faster-whisper` and
  `piper` extras, unchanged.
- `uv run pytest tests/integration -q -ra`: 346 passed in 541.00 s.
- `uv run pytest tests/census -q`: 66 passed. Neither manifest moved, and
  neither should have: this milestone quotes no command spelling that was
  not already quoted, and the test reaches no private name.
- `uv run python scripts/check_doc_links.py .`: 257 files, 0 failures.
- `uv run python scripts/fold_changelog.py check .`: 1 fragment, 0
  failures, which is M1's and still the only one.

The repaired test was run five times on its own after the change, 5/5
green, and the whole file 23/23 alongside it.
