# The unit lane stops reconnecting: implementation

Companion to
[`2026-09-20-lane-stops-reconnecting.md`](2026-09-20-lane-stops-reconnecting.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the lane stops reconnecting

### What landed

| Piece | Where |
| --- | --- |
| The held connection | `vinga-server/tests/conftest.py`: `_TRUNCATION`, `_open_truncation_connection`, and the measurement as a comment |
| The attempt, as one unit | the same file: `_truncate`, with the `current_database()` guard inside it so a reconnect re-checks it |
| The single retry | the same file: `clear_store`, entered only when the connection is broken after the attempt |
| The shutdown | the same file: `close_truncation_connection`, called from `pytest_sessionfinish` before the database is dropped |
| The tests | `vinga-server/tests/unit/test_truncation_connection.py`, three cases |
| The changelog fragment | `changelog.d/489-lane-stops-reconnecting.md`, `### Changed` |

### The plan's open question, answered by measurement rather than by argument

The plan's first draft put the recovery in the accessor: hand back the
held connection when it is usable, open a new one when it is not. The
review's P1 said that cannot work. It is right, and the reason is
worth keeping because it is not obvious:

```
after pg_terminate_backend:   closed=False  broken=False
on next use:               -> AdminShutdown
after that:                   closed=True   broken=True
```

A connection whose backend has been terminated looks perfectly healthy
until a statement runs on it. So there is nothing an accessor can
inspect, and the only honest test of a connection is the attempt
itself. The retry therefore lives in `clear_store`, around the guard
and the truncation together, and runs at most once.

`LockNotAvailable` is caught **before** the broken-connection arm, and
that order is load-bearing rather than stylistic: it is an
`OperationalError` subclass, so a broader arm placed first would
swallow the one error this lane wants loud. Retrying it would also sit
through a `lock_timeout` the lane deliberately refuses to wait out.

### Deviations from the plan

None in what landed. Two things the plan asked for are worth
confirming were done rather than assumed: every connection parameter
is preserved verbatim, `autocommit=True` included, and the held
connection is closed at session finish before
`_drop_this_process_databases` runs.

That ordering is not tidiness. `DROP DATABASE ... WITH (FORCE)`
terminates every backend still on the database, and #537 measured
seventeen such terminations in one run, each a worker's own leftovers
taken by its own drop. A connection held for a whole session and never
closed would have added one more per worker, so this change would have
made that count worse rather than better.

### The tests, and what each one would catch

The reuse is pinned deterministically rather than by a stopwatch,
because an implementation that reconnected on every call would pass a
timing check on a quiet machine. The backend is identified from
outside, by asking `pg_stat_activity` for the application name the
truncation now connects under, so every case goes through
`clear_store` and none reaches a private name.

| Case | Property |
| --- | --- |
| `test_two_cleanups_run_on_one_backend` | the second truncation does not connect |
| `test_a_terminated_backend_is_replaced_once_and_the_work_still_happens` | one replacement, and the seeded row is actually gone |
| `test_a_held_lock_still_fails_the_test_rather_than_reconnecting` | `LockNotAvailable` still raises, and the connection is not replaced |

The second case's last clause is the one that earns its keep: a retry
that reconnected and returned without truncating would satisfy a test
that only checked for an absent exception.

**Watched failing**, both ways:

| Mutation | Result |
| --- | --- |
| open a connection per call again | all three red |
| catch `QueryCanceled` instead of `LockNotAvailable` | the lock case red, the other two green |

The second mutation is the sharper one: it leaves the feature working
and breaks only the guarantee about which errors may be retried.

### Verification

| Check | Result |
| --- | --- |
| `uv run pytest tests/unit/test_truncation_connection.py -q` | 3 passed |
| Full unit lane, `-n auto --dist loadfile` | green; 128.09 s, 114.09 s, 114.96 s over three runs |
| Integration lane, same | green, 346 passed, 72.18 s |
| `uv run ruff check .` | passed |
| Connections the lane opens, `log_connections` on | **5,552** over 7,391 tests, **0.75 each** |

The connection count is the measurement the plan promised and the
changelog publishes, and it is recorded here because a published
number that was never taken is the failure this project keeps
catching. Before the change: 13,067 over 7,433 tests, 1.76 each. The
drop is 7,515, slightly more than the one-per-test the change removes,
because the census's own tests left `tests/unit` in M2 as well.

Against the 122.05 s median the plan recorded for the unlanded tree,
that is roughly **7.5 seconds**, which is what the plan predicted and
what the pure/storage lane split would have bought. The first run's
128.09 s is left in the table rather than dropped: it is the cold one,
and a band with its outlier shown is more use than a median with it
removed.

## M2: the census stops asking for a database

### What landed

| Piece | Where |
| --- | --- |
| The move | `vinga-server/tests/census/test_command_spellings.py` and `command-spellings.txt`, from `tests/unit/` |
| The empty conftest | `vinga-server/tests/census/conftest.py`, which exists so the absence of a storage declaration reads as a decision |
| The documentation workflow | `.github/workflows/docs.yml`: the `postgres` service and the five database variables are gone, and the old comment is replaced by what actually happened |
| The server workflow | `.github/workflows/vinga-server.yml`: an explicit census step in the `unit` job |
| The two prose references | `AGENTS.md` (the manifest path) and `.claude/skills/implement-issue/SKILL.md` (the path and the regeneration command) |
| The changelog fragment | `changelog.d/489-census-needs-no-database.md`, `### Changed` |

### Why the server workflow had to change too

This is the review's fifth finding and it would otherwise have
produced a silently weakened check. `vinga-server.yml`'s unit step
runs `pytest tests/unit`, so it collected the census by collecting the
directory. Moving the file out takes it out of that command, and
naming only the `docs.yml` change would have left the census running
in one workflow rather than two while `AGENTS.md` went on promising
that every change runs it somewhere.

### Deviations from the plan

None. The plan named both workflows and both prose references after
the review round, and both were done as named.

The repository-wide search the plan requires returns only historical
mentions: `CHANGELOG.md` recording what #467 did at the time, earlier
implementation docs recording their own verification runs as they
happened, and this plan's own description of the pre-move state.

### Verification

| Check | Result |
| --- | --- |
| `uv run pytest tests/census -q` with `VINGA_DB_PORT=5999` | 52 passed, with no database reachable at all |
| Both workflows parsed, census step present in each | `docs.yml` job `docs`, `vinga-server.yml` job `unit` |
| `docs.yml` services | none; the job has no service container left |
| Full unit lane after the move | green, 7,388 passed, 111.47 s |
| Integration lane | green, 346 passed, 71.01 s |
| `python3 scripts/check_doc_links.py .` | 252 files, 0 failures |
| `uv run ruff check .` | passed |

The census running with `VINGA_DB_PORT` pointed at a closed port is
the direct evidence for this milestone's claim: it is not that the
census happens to pass without a container, but that it cannot notice
whether one exists.

## PR review round

External adversarial review of PR #539's diff, backend codex, model
`gpt-5.6-sol`, 2026-09-20, posted as
[a comment on the PR](https://github.com/rafacm/vinga/pull/539#issuecomment-5750979322).
Six findings: one P1, four P2, one P3. Verdict: mergeable after the
listed fixes. Five accepted, one rejected with its reasons.

**1 (P1): driver failures leaked the driver's own words.** The retry
introduced escape paths the disposable version did not have: a
non-broken statement error re-raised raw, a failure while reconnecting,
and a second-attempt failure. `_open_truncation_connection` is the
sharp one, because a failure there raises a `psycopg` exception
quoting the DSN it tried, **password included**, which is exactly why
`_maintenance` has built its own sentence since it was written. The
pre-existing `from exc` on the lock refusal had the same shape.

*Resolution*: every failure on this path is now fixed text, built in
the handler and raised outside it, with no `from`. Three sentences:
`LOCK_HELD`, `TRUNCATION_REFUSED` and `RECONNECT_REFUSED`, the last
distinguishing a second failure from a dropped connection.
`test_no_failure_carries_the_driver_s_own_words` asserts that
`__cause__` and `__context__` are both `None` and that neither the
password nor the driver's name appears in the rendered message.
Watched failing: raising the refusal inside the handler instead of
after it turns that case red.

**2 (P2): a lock met after a reconnect bypassed the mapping.** The
retry was a bare `_truncate` outside the arm that names a held lock,
so a terminated backend followed by a leaked writer lock would have
raised a raw driver exception rather than the lane's sentence.

*Resolution*: both attempts go through one `_attempt` helper that does
the identical mapping, and only the first may answer "broken" in a way
that reconnects. `test_a_lock_met_after_a_reconnect_still_reads_as_a_lock`
is the case, and it is the one the review asked for.

**3 (P2): the one-retry limit was not pinned, and the review was right
in a way the first fix was not.** Every other case injects a single
broken attempt, so an unbounded loop satisfies them all: the loop
simply never goes round twice. **The first replacement test did not
fix this.** Mutating the code to an unbounded retry loop left all six
cases green, which is the finding reproducing itself against the fix
for it.

What pins it is making **both** attempts break, with a
`BEFORE TRUNCATE` trigger that terminates whichever backend is running
the truncation. A bounded implementation gives up and raises the
second-failure sentence; an unbounded one reconnects forever. The call
is driven on a thread with a thirty-second deadline, because an
unbounded implementation would otherwise hang the suite rather than
fail it, and a hang is a worse thing to hand a reader than an
assertion. Re-run against the same mutation, the case now goes red.

**4 (P2): `TRUNCATION_APPLICATION` is a test-facing export.**
*Rejected, with reasons.* The plan's commitment was that the test
"should not export the holder or create a test-only accessor", and
this is neither: it is a value the connection is configured with, not
a handle to it or a way in. `application_name` also earns its place
independently of the test, because it is what makes these connections
identifiable in `pg_stat_activity` to a human debugging a lane run;
before this change they were anonymous. And the alternative the
finding proposes, counting sessions on the lane database without
naming them, is measurably more fragile: tests legitimately hold store
connections open on that database, so a count would be pinning the
behaviour of every other test in the file rather than this one.
`tests/conftest.py` is test code, and a public name it offers to test
code is not the reach-in the design guide is about.

**5 (P2): the path sweep was incomplete, and the implementation doc
said otherwise.** `.github/workflows/docs.yml:9` still named
`tests/unit/test_command_spellings.py`, and `AGENTS.md` carried the
manifest path without the regeneration command the plan required.

*Resolution*: both fixed, and the cause is worth recording because it
is a repeat. The sweep was run through `head`, so the workflow line
sat below the cut on a search whose completeness was its entire point.
Re-run without truncation, every remaining mention is a historical
record: the changelog, earlier implementation and feature docs
recording their own verification runs, and this plan's description of
the pre-move state. The implementation doc's claim that only
historical references remained was false when written and is corrected
here rather than quietly edited.

**6 (P3): a published number that was never measured.** The changelog
claimed "roughly 7,400 fewer connections" while the verification table
recorded only tests, timings and lint.

*Resolution*: measured, with `log_connections` on. **5,552
connections over 7,391 tests, 0.75 each**, against 13,067 over 7,433
tests, 1.76 each, before. The drop is 7,515, slightly more than the
one-per-test this change removes, because M2 also took the census's
own tests out of the lane. The changelog now carries the measurement
instead of the estimate.
