# The interrupted-seeding case holds the script at a known write

**Date:** 2026-10-01

**Local baseline:** not applicable. The change is to one integration
test; no conversational capability, provider or default moves.

## Problem

`test_an_interrupted_seeding_fails_and_leaves_no_server_behind`
(`vinga-server/tests/integration/test_smoke_seeds.py`) starts
`tests/smoke/seed.sh`, waits for the server the script starts to
answer `/readyz`, sends the script SIGINT, and asserts a nonzero exit,
`interrupted` on stderr, and no server left listening. On the
four-core second machine it failed three times in a row with
`assert 0 != 0` while another milestone's lanes were running, and
passed when its file was run alone (#555, recorded in the #488 M3
section of
[`2026-09-22-cli-decomposition-implementation.md`](../plans/2026-09-22-cli-decomposition-implementation.md)).
The issue read this as the signal losing a race to the seeding's last
write under load. Measurement says otherwise on both counts.

### The failure was the signal's disposition, not load

A non-interactive POSIX shell starts each asynchronous list
(`command &`) with SIGINT and SIGQUIT ignored, and an ignored
disposition survives `exec`. CPython installs its own SIGINT handler
only when the inherited disposition is the default, so a runner
started as `uv run pytest ... &` keeps SIGINT ignored, and so does
every process it spawns. A non-interactive shell cannot trap a signal
that was ignored on entry: `trap on_interrupt INT` in the seeding
script is silently a no-op, the test's SIGINT is dropped, and the
script writes all seven entries and exits 0.

Probed directly: a pytest run from a foreground shell reports SIGINT
handled by `default_int_handler` and its children's `SigIgn` mask as
`0000000000000000`; the same run started as an asynchronous list
reports `SIG_IGN` and a child mask of `0000000000000006` (SIGINT and
SIGQUIT). The case itself, at `c277d023`:

| Launch | Machine | Runs | Result |
|---|---|---|---|
| asynchronous list (`sh -c '... & wait'`) | idle, load 0.1 | 3 | 3 failed, `assert 0 != 0` |
| foreground | idle | 3 | 3 passed |
| foreground | six busy loops on four cores, load average up to 10.8 | 5 | 5 passed |

A race was never plausible either. The seeding's write phase, from the
moment the test sees the server ready to the script's exit, measured
11.2 to 13.1 s idle and 13.1 to 14.8 s under four busy loops (three
runs each). Losing a race to it would need the runner descheduled for
the whole of that. Which launch the #488 M3 session used is not
recorded; the evidence above is why this doc attributes the failure to
an asynchronous launch rather than to load, and it is consistent with
everything that record says, including the pass when the file was run
alone.

### The interrupt never landed where the case said it did

The case's readiness helper said that the server being ready "is when
the script starts writing". The test polls `/readyz` every 0.1 s; the
script polls it every 0.5 s and each poll starts a Python interpreter.
So the test sees the server first and the signal lands while the
script is still inside `start_server`. With the disposition fixed, five
interrupted runs were read back: **all five had written nothing**. The
case proved an interrupted start-up and said nothing about an
interrupted write, which is the step it was named for.

## Changes

Three commits, all to the test; the seeding scripts and every
production module are untouched.

### The child gets a trappable SIGINT

`Popen(..., preexec_fn=_default_interrupt)` sets SIGINT to `SIG_DFL` in
the child between fork and exec, which is the disposition a terminal's
foreground job has and the one the script's handler is written for.
That function does one call and nothing else. Python documents
`preexec_fn` as unsafe in a process with threads, because the child
may inherit a lock another thread held; `signal.signal` takes none
beyond the interpreter's own, which the forking thread holds, and a
probe with a live second thread and `-W error` raised no warning on the
lane's Python 3.12.14.

### The script is held at its second write

A stand-in `vinga-server` on the script's `PATH`, the repository's
existing idiom for this (`tests/unit/test_docker_entrypoint.py` puts a
stand-in server on `PATH` the same way), appends a line to a call log
on every `config` call. On the second it creates a `held` file and
waits for a `released` file before `exec`ing the real CLI with the same
arguments. Every other call, including the one that starts the server,
goes straight to `exec`, so the process the script started is the one
it later stops.

The test waits for `held`, sends SIGINT, then creates `released`. The
shell runs a trap only once its foreground command returns, and the
signal is pending in the kernel before the write is let go, so where
the interrupt lands is fixed whatever the scheduler does: during the
second write, after the first one finished.

That makes a claim checkable that was not before, and the case now
asserts it: the held write finished and no later one began. Exactly
two CLI calls, providers for `llm` and `asr` only, no default agent.

The hold's wait is bounded at 60 s, so a test that dies while holding
it leaves a script that finishes rather than one that waits for ever.
The test's own wait for `held` is 180 s, the bound the other seeding
cases put on a whole script, since reaching the hold includes starting
the server.

### A failed run takes its server with it

The old failure path killed the shell, and only when the shell was
still running. A failure in which the shell had already exited
therefore left the server it started running, and one did: the
mutation below that deletes `seed.sh`'s INT trap lets the default
SIGINT end the shell without stopping the server, and that server
process was still running 45 minutes later, on a machine other lanes
were sharing, until it was killed by hand. The assertions now sit
inside the `try`, and any failure kills the whole process group with
`os.killpg`, which reaches the server and the stand-in whether or not
the shell is still there, since a process group lives as long as any
member does. A passing run sends nothing.

### Sibling cases

`test_a_seeding_script_reports_a_server_that_will_not_start`, the
file's other `returncode != 0` assertion, sends no
signal and has no race: it removes `VINGA_API_SECRET`, the server
refuses to boot, and the script's own `kill -0` sees it gone. It is
unaffected by the disposition as well, and is unchanged. No other test
in the repository sends a signal to a subprocess; the only other
signal sites are `tests/unit/test_drain.py`'s direct
`handle_exit(signal.SIGTERM, None)` calls, which send nothing.

### Deviation from the Step 0 decision

The decision was to hold the seeding at a known point rather than
loosen the assertion. That is what was done, with two differences.
The hold lives in the test as a `PATH` stand-in rather than as a hook
in the script, so no inert-unless-set seam reaches a deployment
artifact. And the hold is the second fix, not the first: on its own it
would not have stopped the reported failure, because a dropped signal
lets the held script run to the end either way.

### Against the cheaper alternatives

- **Loosen the assertion** to what holds under either interleaving (no
  server left behind) and move "fails" elsewhere. Rejected: the
  reported failure was not an interleaving, so a loosened case would
  have gone green by no longer asking the question, while the dropped
  signal stayed dropped.
- **The disposition reset alone.** One function and one argument, and
  it fixes the reported failure; it is the first commit. What the hold
  buys over it is measured rather than estimated: without it, five of
  five runs interrupted the start-up and none a write, so the case's
  stated subject was untested. The hold costs a thirteen-line shell
  stand-in and three marker files in the test's temporary directory,
  adds no module and no production seam, and replaces the readiness
  helper it makes unnecessary. The deletion test: inlining the
  stand-in would not shrink anything, since it is already a string in
  the one test that uses it.

## Key parameters

- The hold point: the second `config` call (`hold_at=2`). The first
  write has completed, so "mid-way" is a fact the database shows.
- The stand-in's own bound: 600 polls of 0.1 s.
- The test's wait for the hold: 180 s.

## Verification

- The old case reproduced as above: 3 of 3 asynchronous launches
  failed on an idle machine, 3 of 3 foreground runs and 5 of 5
  foreground runs under load passed.
- The new case passed 3 of 3 asynchronous launches and the whole
  seeds file passed (9 passed).
- Under contention: **20 of 20 passed**, each launched the way the
  original failure was, as an asynchronous list with SIGINT therefore
  ignored on entry, while four busy loops ran on the four cores
  throughout, this branch's own unit lane (`-n auto`) overlapped the
  first two runs, and other branches' lanes shared the machine and the
  Postgres instance (how many, run by run, is not recorded).
  One-minute load average at each run's start ranged from 5.5 to 20.3,
  and run times from 17 s to 464 s.
- Mutations, each applied by `sed`, run, and restored by copy and
  `touch`:

| Mutation | Result |
|---|---|
| no `preexec_fn`, asynchronous launch | killed: `assert 0 != 0` |
| `on_interrupt` exits 0 | killed: `assert 0 != 0` |
| no `trap on_interrupt INT` in `seed.sh` | killed: `interrupted` not on stderr; with the group kill, no server left running (one was before it) |
| `on_interrupt` returns instead of exiting | killed: 3 calls, not 2 (the previous case passes this one) |
| the stand-in never holds | killed: the seeding never reached its second write |
| release before the signal | survived, 3 of 3 |

  The surviving mutation reorders the test's own two lines. Sending
  the signal before the release is what guarantees where it lands;
  reversed, the window is as long as one CLI write (over a second),
  which no run here shrinks far enough to lose. The order is held by
  the comment above it, not by an assertion.

- Lanes, all from `vinga-server/` on the four-core machine:
  `uv run ruff check .` clean; the integration lane
  (`-n auto --dist loadfile`) `349 passed in 605.16s`; the unit lane
  (`-n auto --dist loadfile`) `7694 passed, 19 skipped in 1725.74s` on
  its second run.
- The unit lane's first run, beside another branch's unit lane on the
  same Postgres, reported `1 failed, 7693 passed, 19 skipped in
  1870.45s`. The failure is
  `test_db_autogen.py::test_a_url_override_never_migrates_the_database_it_names`,
  `cannot open the vinga database`, and is not this change's: the
  autogenerate command's scratch database has a fixed name
  (`vinga_autogen_scratch`, `db/migrations/autogen.py`) and is made and
  dropped `with (force)`, so two lanes sharing one Postgres instance
  can drop it from under each other. The file passed alone afterwards
  (`9 passed in 128.14s`).

## Files modified

- `vinga-server/tests/integration/test_smoke_seeds.py`: the stand-in,
  the disposition reset, the held interrupt and its new assertions, and
  the process-group kill on any failure; the readiness helper `_ready`
  removed.
- `docs/features/2026-10-01-interrupted-seeding-hold.md`: this doc.
- `changelog.d/555-interrupted-seeding-hold.md`: the changelog fragment.
