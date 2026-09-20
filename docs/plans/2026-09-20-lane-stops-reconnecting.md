# The unit lane stops reconnecting, and the census stops asking for a database

Plan for [#489](https://github.com/rafacm/vinga/issues/489). Its
companion is
`docs/plans/2026-09-20-lane-stops-reconnecting-implementation.md`, one
section per milestone, appended in the same change that ticks the
milestone.

**Local baseline:** not applicable. Nothing here changes a
conversational capability. The whole change is how a test fixture
reaches the database and where one test file lives; a deployment
reaches none of it.

**Cheapest alternative:** none for M1, which is itself the cheapest
alternative to the boundary this issue originally proposed, and the
measurement that establishes it is the whole of the section below. For
M2, the cheaper option is to leave the census where it is and give
`docs.yml` a Postgres it does not use, which is the status quo this
issue exists to end; the move costs one file and buys a container per
documentation run.

## The measurement this plan starts from, and the milestone it closed

The issue as filed proposes splitting the unit suite into a pure lane
and a storage lane, with the classification enforced. It was measured
before it was planned, on `10dfb58f`, on a 14-core darwin machine
against the compose file's Postgres, `-n auto --dist loadfile`, which
is eight workers since #537.

**The split buys what one reused connection buys.** `clear_store`
opens a fresh `psycopg` connection for every test and closes it again:
16.91 ms per teardown against 15 tables, of which 4.26 ms is the
connect alone.

| Variant | Time | Saving |
| --- | ---: | ---: |
| Full lane today | 122.05 s (median of 5) | |
| Full lane, one truncation connection held per worker | **114.6 s** (median of 4, band 114.5-115.6) | **7.4 s** |
| The 92 genuinely pure files, with truncation | 40.08 / 41.10 s | |
| The same 92, truncation off, which is a pure lane's upper bound | 33.05 / 33.17 s | **7.3 s** |

Seven seconds either way. One is ten lines in one function that moves
no test and classifies nothing; the other is a boundary across 219
files that 127 of them may never cross.

**The suite is also harder to classify than the issue assumes.** Of
219 unit files, **127 need a database** and **92 are genuinely pure**.
The 92 were measured two ways: they pass with no database reachable at
all, and they pass with a database present and the truncation
disabled. That is what was observed, and it is deliberately not
stated as "they perform no writes", which neither run establishes: a
non-conflicting write, a uniquely keyed row, or code that tolerates an
unavailable database would survive both. The argument does not need
the stronger claim, because it rests on the seconds rather than on
purity. They hold 2,432 of 7,437 tests, **33%**, so an enforced
boundary would police two thirds of the suite to protect a third.

The route to those numbers is part of the evidence and is recorded
because it is the strongest argument here. Two attempts to classify
the suite were both wrong. The first summarized its run with `-rf`,
which lists failures and not errors, and 1,047 tests **errored**,
which is precisely how a storage test fails when provisioning is
disabled; it undercounted the storage files by fifteen. The second
defined pure as "passes with no database", which let through 159 tests
that write to a real store and depend on the truncation to clean up
after them. If classifying this suite defeats two attempts made with
the tests in hand and no other purpose, then an enforced classifier is
a rule this repository will keep tripping over.

So the split is closed with the numbers and no further change, which
the issue's own M2 names as a valid outcome, and the issue has been
re-scoped to say so. This plan implements what is left, which is where
the measured wins actually are.

## What is settled and not re-litigated

From the issue, and from the re-scoping recorded on it:

- **The truncation's condition stays the LANE and never the test.**
  This is the property the original design protects, for the stated
  reason that a per-test "did this one touch anything" is the same
  fixture with a hole in it, since what leaks is exactly the write
  nobody noticed. Nothing here touches it: every test in a
  provisioning lane still truncates.
- **Refuse, don't skip.** A lane that needs storage and cannot reach
  it still fails hard rather than skipping. Nothing here weakens that.
- **Storage tests keep testing storage.** No mocking pass, no doubles.
- **A contributor still needs the development instance running**, even
  for a test that touches no storage, because the lane still
  provisions once per worker. That is the split's third motivation and
  it is given up deliberately: it costs one `docker compose up -d
  --wait` that the setup documentation already prescribes.

## Open questions, resolved

### What happens to the held connection when a test breaks it

A connection opened per test is disposable by construction, and one
held for a session is not, so the failure this introduces is a
connection that a test leaves unusable: a server-side termination, an
aborted transaction, a socket closed under it.

**The recovery cannot live in the accessor**, which is where this plan
first put it. A connection whose peer has gone does not report
`closed` or `broken` until a statement is executed on it, which is
after any accessor has returned, and an aborted transaction is not a
broken connection at all: it stays open with a failed transaction
status. Inspecting the connection before handing it over therefore
cannot answer the question the accessor would be asked.

So `clear_store()` owns the recovery, over the whole operation rather
than over the connection:

- The guard and the truncate run together as one attempt.
- If that attempt fails with the driver marking the connection broken,
  the held connection is discarded, a new one is opened, and the
  attempt runs **once** more. Not a loop: a second failure is a real
  failure and is raised.
- **Every other SQL error keeps exactly the behavior it has today.**
  `LockNotAvailable` above all: a test that left a writer holding a
  lock still meets `lock_timeout` and still becomes the same
  `AssertionError` with the same sentence. A reconnect on that error
  would retry a wait the lane deliberately refuses to make, and would
  hide the defect it exists to name.

**The connection's parameters are preserved verbatim**, and two of
them are load-bearing. `autocommit=True` is what keeps a truncation
and its locks from surviving into the next test, which is precisely
the risk a held connection introduces. `options="-c lock_timeout=5000"`
is per-statement and unaffected by reuse. The `current_database()`
assertion stays where it is, inside the attempt, so it is re-checked
after a reconnect rather than trusted from before it.

**And the held connection is closed at session finish**, before this
worker drops its database. That is not tidiness. `_drop_this_process_databases`
force-drops the lane database, and a `DROP DATABASE ... WITH (FORCE)`
terminates every backend still on it: #537 measured exactly 17 such
terminations in one run, every one a worker's own leftover backends
taken by its own drop. A connection held for the whole session and
never closed would add one per worker to that count, which is the
opposite of what this milestone is for.

### Why not a pool

A pool is the same thing with a name and a size to tune. One
connection per worker process is what the lane needs, since a worker
runs one test at a time, and the deletion test applies: a pool of one,
inlined, is a variable.

### Where the census goes

`tests/unit/test_command_spellings.py` reads no rows. It provisions a
database only because it lives under `tests/unit`, whose conftest
declares that lane's storage at import. Moving the file is what frees
`docs.yml`.

It moves to `tests/census/`, a directory of its own with no conftest
declaring storage, rather than into `tests/smoke` (which is about
driving a container over HTTP and would become two unrelated things)
or `tests/tools` (which is the helpers' package, not a lane). The
manifest, `command-spellings.txt`, moves with it: the generator and
its output are one unit, and the regeneration command in `AGENTS.md`
changes with the module path.

The workflows change with it. `docs.yml` drops its `postgres`
service block and the comment justifying it, and the path it runs
becomes the new one; `vinga-server.yml`'s unit step still collects
`tests/unit` and therefore no longer collects the census, so the
census runs in both workflows through its own path. The one thing that
must stay true is that **every change still runs the census
somewhere**, which is what `AGENTS.md` promises and what the two
workflows' mirrored `paths-ignore` arrange.

## Milestones

- [x] **[M1: the lane stops reconnecting](2026-09-20-lane-stops-reconnecting-implementation.md#m1-the-lane-stops-reconnecting)** (PR TBD). `clear_store` takes its
  connection from a per-worker accessor that opens once and reopens
  only when the held one is unusable, instead of connecting and
  closing per test. The autouse fixture, its lane condition and the
  `current_database()` guard are untouched. Verified by the full lane
  green and by the wall-clock band above. **Design footprint:** one
  new module-level accessor beside `clear_store` in
  `tests/conftest.py`, which is where every other fact about this
  lane's database already lives; no new module, because a file whose
  only content is "hold a connection" would be a pass-through by the
  deletion test. A `### Changed` fragment at
  `changelog.d/489-lane-stops-reconnecting.md`.
  **Documentation footprint:** none; no page describes how the
  truncation reaches the database.
- [x] **[M2: the census stops asking for a database](2026-09-20-lane-stops-reconnecting-implementation.md#m2-the-census-stops-asking-for-a-database)** (PR TBD).
  `test_command_spellings.py` and `command-spellings.txt` move to
  `tests/census/`. **Both workflows change, not one**: `docs.yml`
  drops its Postgres service and the comment justifying it and runs
  the census at its new path, and `vinga-server.yml` gains an
  invocation of it, because its unit step collects `tests/unit` and
  would otherwise stop running the census altogether. That would
  leave the census in one workflow instead of two and quietly break
  the invariant this plan states. A `### Changed` fragment at
  `changelog.d/489-census-needs-no-database.md`.
  **Design footprint:** none; a file moves to a directory that
  declares nothing. **Documentation footprint:** `AGENTS.md` twice,
  for the regeneration command **and** for the literal manifest path
  `vinga-server/tests/unit/command-spellings.txt` it quotes, which the
  census cannot catch because it recognizes command invocations and
  not bare paths; plus any other page quoting either. Verified by a
  repository-wide search for both old paths, not by the census alone.

## Tests and verification

A wall-clock comparison is nondeterministic and cannot by itself show
that anything was reused: an implementation that reconnected on every
call would pass a timing check on a quiet machine and would pass a
termination test too. So the reuse is pinned deterministically, and
the timing is reported as a consequence rather than offered as proof.

- **Reuse, deterministically**: two consecutive `clear_store()` calls
  observed to run on **one** backend. The backend is identified from
  outside, by asking the lane database for `pg_backend_pid()`, so the
  test goes through `clear_store()` and reaches no private name. This
  is the test that fails against today's code.
- **Recovery, falsified rather than assumed**: that backend terminated
  server-side, after which one further `clear_store()` succeeds, runs
  on exactly one new backend, and **leaves seeded rows actually
  gone**. The last clause is what distinguishes a retry that completed
  the work from one that merely returned.
- **`LockNotAvailable` still raises its `AssertionError`**, pinned, so
  the retry cannot have swallowed the one error the lane wants loud.
- **The per-test connection is gone**: the issue's own count
  re-measured, from roughly 1.76 connections per test toward one per
  worker plus what the tests themselves open.
- The full unit lane, `-n auto --dist loadfile`, green, with its
  wall-clock against the 122.05 s median recorded above, reported as a
  consequence of the above rather than as evidence for it.
- The integration lane, green, since it shares `tests/conftest.py`.
- The census runs from its new home in **both** workflows, checked by
  reading each workflow rather than inferred, and `tests/unit` no
  longer collects it.
- A repository-wide search for the old module path and the old
  manifest path returns only deliberately historical mentions.
- `uv run ruff check .`, the doc link check, and the census itself.

## Risks

- **A held connection changes what a leaked lock does.** Today a test
  that leaves a writer holding a lock meets `lock_timeout` on a fresh
  connection; tomorrow it meets it on the held one. The timeout and
  the assertion that follows are unchanged, so the failure is the same
  failure with the same sentence; what differs is that the connection
  survives into the next test, which is why the reopen branch judges
  usability rather than assuming it.
- **The census moving could leave it running nowhere.** Mitigated by
  checking both workflows explicitly, and the plan states the
  invariant: every change runs the census somewhere.

## Plan review round

External adversarial review of this plan at `5d437ae3`, run read-only
in the worktree. Backend codex, `codex-cli 0.155.0`, model
`gpt-5.6-sol`, 2026-09-20. Eight findings: one P1, six P2, one P3.
Verdict: ready after the P1/P2 amendments.

### 1 (P1): the accessor cannot detect every unusable connection it promises to recover

A remotely terminated socket may not become `closed` or `broken` until
a statement executes on it, which is after the accessor has returned,
and an aborted transaction is not a broken connection at all: it stays
open with a failed transaction status. So "return the held connection
when it is usable" cannot be implemented by inspecting the connection.
`clear_store()` should own a single retry of the whole
guard-and-truncate instead, and ordinary SQL errors, `LockNotAvailable`
above all, must keep their present behavior rather than driving a
reconnect.

*Resolution*: accepted in full, and it corrects the design rather than
the wording. The plan's open question is rewritten: the retry lives in
`clear_store()`, covers the guard and the truncate together, runs at
most once, and is entered only when the driver marks the connection
broken. `LockNotAvailable` keeps its `AssertionError` exactly as
today, which the milestone now pins.

### 2 (P2): the held connection's transaction and shutdown lifecycle is unspecified

`autocommit=True` and the unconditional `close()` are load-bearing and
the plan named neither. Without autocommit a reused connection can
carry an uncommitted truncation and its locks into the next test, and
without a shutdown rule the held connection survives until process
exit.

*Resolution*: accepted, and the shutdown half is sharper than the
finding states. `_drop_this_process_databases` force-drops this
worker's database at session finish, so a held connection that is
still open is terminated by its own worker's drop. That is exactly the
17 self-inflicted `terminating connection due to administrator
command` lines #537 measured, and this change would have added to
them. The plan now requires `autocommit=True` and every existing
connection parameter to be preserved verbatim, and the held connection
to be closed at session finish before the drop.

### 3 (P2): the verification does not prove that connections are reused

A wall-clock comparison is nondeterministic, and the termination test
passes even against an implementation that reconnects on every call.

*Resolution*: accepted. The milestone now requires a deterministic
test: two consecutive `clear_store()` calls observed to use one
backend, a terminated backend causing exactly one replacement, and
seeded rows actually gone afterwards, so the retry is proved to have
completed the work rather than merely to have returned.

### 4 (P2): the reconnect test reaches through the fixture's interface

The plan made the accessor an implementation detail and then had the
test take the held connection from it, which is the underscore
reach-in `AGENTS.md` calls a review flag.

*Resolution*: accepted. The test goes through `clear_store()` and
identifies the backend from outside, through `pg_backend_pid()` on the
lane database, so nothing test-only is exported and no private name is
reached.

### 5 (P2): M2 does not name the required server-workflow edit

Once the census leaves `tests/unit`, `vinga-server.yml`'s unit step
stops collecting it, so naming only the `docs.yml` change would leave
the census running in one workflow rather than two and break the
invariant the plan itself states.

*Resolution*: accepted, and it is the finding most likely to have
produced a silently weakened check. M2 now names the
`vinga-server.yml` invocation as well as the `docs.yml` one, and the
verification checks both workflows explicitly.

### 6 (P2): the move lacks a reliable check for stale path references

`AGENTS.md` carries the literal manifest path
`vinga-server/tests/unit/command-spellings.txt`, and the census
recognizes command invocations rather than plain paths, so it cannot
be relied on to catch that one.

*Resolution*: accepted. M2 names both the command and the manifest
path in `AGENTS.md`, and the verification includes a repository-wide
search for the old module and manifest paths.

### 7 (P2): the required changelog fragment is absent

*Resolution*: accepted, a plain omission. Each milestone now carries
its `changelog.d/489-*.md` fragment.

### 8 (P3): passing without truncation does not establish that the 92 files perform no writes

Non-conflicting writes, unique rows, or code tolerating an unavailable
database can pass both described runs while still touching storage.

*Resolution*: accepted, and this is the fourth claim in this session's
work to be narrowed to its evidence, after three in #537. The plan now
says what was measured: those 92 files pass in both configurations,
and disabling the truncation for them saved about 7.3 seconds. The
inference "neither need storage nor write to it" is removed. The
conclusion the measurement supports is unchanged, because the argument
never rested on zero writes: it rests on the 7.3 seconds against 7.4.
