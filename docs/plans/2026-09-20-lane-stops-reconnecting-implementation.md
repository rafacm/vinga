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
