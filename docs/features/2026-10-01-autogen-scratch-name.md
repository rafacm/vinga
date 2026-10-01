# Each autogeneration run makes its own scratch database

**Date:** 2026-10-01

**Local baseline:** not applicable. The change is to a maintainer's
migration-authoring command and its tests; no conversational
capability, provider or default moves.

## Problem

`python -m vinga_server.db.migrations.autogen` writes a candidate
migration by bringing a throwaway database to head and comparing the
chain's metadata against it. That database had one fixed name,
`SCRATCH = "vinga_autogen_scratch"`, and the command ran
`drop database if exists "vinga_autogen_scratch" with (force)` both
before the run and in its `finally`. The fixed name was deliberate: a
killed run left one findable database, and the next run's first drop
cleared it.

It also meant two runs against one Postgres instance shared that
database. `with (force)` terminates every connection to a database
before dropping it, so whichever run dropped second took the other
run's database away mid-use, connections and all. Two unit lanes from
two worktrees sharing the development instance is the ordinary state of
a development machine, and on 2026-10-01 it failed
`tests/unit/test_db_autogen.py::test_a_url_override_never_migrates_the_database_it_names`
in one branch's unit lane while another branch's lane ran; the file
passed alone. Within one lane `--dist loadfile` keeps the file on one
worker, so the collision needs two lanes, which is why it read as a
flake. CI gives each job its own Postgres and never shows it.

## Changes

### A name per run, dropped only by the run that made it

`generate` now names its database `SCRATCH_PREFIX` plus sixteen random
lowercase hex digits (`secrets.token_hex(8)`), for example
`vinga_autogen_scratch_1c15e0beacc7a4b6`. The constant `SCRATCH` is
replaced by `SCRATCH_PREFIX = "vinga_autogen_scratch_"`.

The drop before the run is gone. A name nobody else holds has nothing to
clear, and if it ever did exist, the `create` failing is the right
answer, because the database would be somebody else's. The drop after
the run keeps `with (force)` and moved into a `finally` that is entered
only once this run's own `create` has succeeded, so the force can only
ever reach a database this run made and only terminate this run's
connections. A failed `create` drops nothing.

`generate` returns the name, where it used to return nothing. The name
is chosen inside the call, and a caller that wants to confirm nothing
outlived the run has to ask about that one database: asking about the
prefix would also see a concurrent run's database, which is exactly the
flakiness this change removes. `main` ignores it; the command's exit
codes and its single sanitized failure sentence are unchanged.

### The leftover policy: named, not swept

A run killed before its `finally` (SIGKILL, a lost connection, a
machine going down) now leaves its database behind, and nothing removes
it automatically. Step 0 on the issue decided this rather than leaving
it to a default: a sweep by prefix, or by prefix and age, cannot tell a
killed run's database from one a concurrent run is still using, and
dropping a live one is this issue's own bug. The comment above
`SCRATCH_PREFIX` says so and gives the two statements that find and
drop a leftover by hand:

```sql
select datname from pg_database where datname like 'vinga\_autogen\_scratch\_%';
drop database "vinga_autogen_scratch_<suffix>" with (force);
```

A database under the old fixed name, left by a killed run of an earlier
build, does not match the new prefix's pattern (the prefix ends in an
underscore) and is not touched either; it is dropped the same way.

### A test that meets the collision every time

`test_two_runs_at_once_each_keep_their_own_scratch_database` runs two
lifecycles concurrently, one in a thread named `first` and one in the
test's own thread, each writing into its own copy of the domain chain.
Racing them would meet the collision only on some interleavings, so
the interleaving is forced instead: `alembic.command.revision` is
wrapped, and the `first` thread waits inside the wrapper, with its
scratch database at head and a connection to it open, until the second
run has gone through its whole lifecycle. Then it is released and
compares. The test asserts both runs returned a name, the names differ,
each chain gained exactly one revision file, and neither named database
is in `pg_database` afterwards. If the hold runs out before the second
run finishes, the first run fails with a sentence saying so rather than
comparing early, since an expired hold is a race and not the
interleaving the test claims.

The two existing lifecycle tests now assert the database gone by the
name `generate` returned rather than by the fixed constant, and the
domain-chain one also asserts the name's shape: exactly the prefix and
sixteen lowercase hex digits, and a lowercase identifier of at most 63
bytes that Postgres neither folds nor truncates.

### Both failure edges of the drop

Where the drop's `finally` sits is the whole of what keeps it safe, and
two real-Postgres cases pin it from either side:

- `test_a_failed_comparison_still_takes_its_scratch_database_away`
  makes `alembic.command.revision` raise after the scratch database was
  made, migrated and connected to, reads the database's name through
  the connection the command handed Alembic, and asserts the database
  is gone once the failure has travelled out.
- `test_a_name_already_taken_is_refused_and_left_alone` pins the random
  suffix to one drawn in the test (by replacing `secrets.token_hex`),
  creates that database first, and asserts the command refuses at its
  `create` with `DuplicateDatabase` and leaves the existing database in
  place.

Both clean up by the command's prefix afterwards, so a mutant that
leaks a database does not leave it on the instance.

## Key parameters

| What | Value |
| --- | --- |
| Name | `SCRATCH_PREFIX` + `secrets.token_hex(8)`, 38 characters |
| `SCRATCH_PREFIX` | `vinga_autogen_scratch_` (replaces `SCRATCH = "vinga_autogen_scratch"`) |
| Suffix | 64 random bits as 16 lowercase hex digits |
| Postgres identifier limit | 63 bytes (`NAMEDATALEN - 1`) |
| Drop before the run | removed |
| Drop after the run | `with (force)`, own name only, only after a successful `create` |
| Leftover sweep | none, by decision; removal by hand |
| `generate` return | the scratch database's name (was `None`) |

## Verification

- Falsification of the concurrency test, each version run 20 times
  alone, the module swapped by copy and restored by copy, never by
  checkout:
  - `main`'s module (fixed name, drop before and after), changed only to
    return its name so the assertion reads the collision rather than a
    missing return: failed 20 of 20, every time on the first run, with
    `AdminShutdown: terminating connection due to administrator
    command`. That is the reported failure's mechanism: the second
    run's forced drop killed the first run's open connection.
  - The new module with the suffix replaced by a constant: failed 20 of
    20, every time on the second run, with `DuplicateDatabase`, since
    with no drop first the second `create` meets the first run's
    database.
  - The fix: passed 20 of 20.
- Removing the drop in the `finally` fails the four tests that ask
  whether the run's database is gone
  (`test_the_scratch_database_is_made_migrated_and_taken_away`,
  `test_a_failed_comparison_still_takes_its_scratch_database_away`,
  `test_two_runs_at_once_each_keep_their_own_scratch_database`,
  `test_the_memory_chain_autogenerates_against_a_scratch_database`).
  The five databases that mutant left were listed by the prefix and
  dropped by hand afterwards, which exercised the stated policy; the
  run's own creation times and no open connections are what said they
  were that run's and not a concurrent one's.
- The review round's mutations, each watched failing the case written
  for it:
  - the drop moved onto the success path fails
    `test_a_failed_comparison_still_takes_its_scratch_database_away`
    only (1 failed, 11 passed);
  - the `finally` widened around `CREATE` fails
    `test_a_name_already_taken_is_refused_and_left_alone` only (1
    failed, 11 passed): the pre-existing database was dropped;
  - the suffix cut to `token_hex(1)` fails
    `test_the_scratch_database_is_made_migrated_and_taken_away` on
    `vinga_autogen_scratch_a0`;
  - the hold cut to 10 ms, so the second run outlives it: the
    concurrency case fails 10 of 10 with the hold sentence. Before the
    hold was checked, the same cut passed 3 of 13 runs silently. Of
    its 10 failures, the 9 whose output was kept were a `KeyError`
    (`'config'`, twice bare and seven times inside the storage
    refusal), which reads as two Alembic runs overlapping in one
    process and was not traced further; none named the hold.
- Lanes, from `vinga-server/` on the four-core machine with other
  branches' lanes sharing the same Postgres: `uv run ruff check .`
  clean; the unit lane (`-n 2 --dist loadfile`) `1 failed, 7807
  passed, 19 skipped in 1787.76s`; the integration lane (`-n 2 --dist
  loadfile`) `350 passed in 781.17s`. The one unit failure is
  `test_event_docs.py::test_a_reader_who_stops_reading_mid_chunk_gets_no_traceback`,
  whose precondition found the pipe short of full (`253952 of 262144
  bytes`) under a load average near 9. It is not this change's: the
  file failed the same way alone three times out of three on this
  branch and three out of three at `main` (`c6d6aa6b`), and it imports
  nothing this change touches. `test_db_autogen.py` passed in the full
  lane.

## Files modified

- `vinga-server/src/vinga_server/db/migrations/autogen.py`
- `vinga-server/tests/unit/test_db_autogen.py`
- `docs/features/2026-10-01-interrupted-seeding-hold.md` (a pointer
  from the run that recorded the collision)
- `docs/features/2026-10-01-autogen-scratch-name.md`: this doc.
- `changelog.d/585-autogen-scratch-name.md`
