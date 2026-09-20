# The documented test command works on a developer machine

Plan for [#537](https://github.com/rafacm/vinga/issues/537). Its
companion is
`docs/plans/2026-09-20-unit-lane-worker-safety-implementation.md`, one
section per milestone, appended in the same change that ticks the
milestone.

**Local baseline:** not applicable. Nothing here changes a
conversational capability. The whole change is how many worker
processes a test command starts; a deployment reaches none of it.

## What the issue reported, and what is actually true

The issue is accurate about the symptom and wrong about the cause, and
it says so itself: its mechanism is offered as a hypothesis, with
"I have not isolated the exact interleaving ... so this is where I stop
rather than guess further". Isolating it is this plan's job, and the
answer moves the fix out of the fixtures entirely.

The symptom reproduces exactly as reported. On a 14-core darwin machine
at `f2fccef1`, against the Postgres `docker compose up -d --wait`
starts, with the lane's documented environment pins:

| Invocation | Result |
| --- | --- |
| `-n 8 --dist loadfile` | **green**: 7433 passed, 19 skipped, 123.51s |
| `-n auto` (14), run 1 | 225 failed, 7153 passed, 719 errors, 115.79s |
| `-n auto` (14), run 2 | 256 failed, 7106 passed, 854 errors, 94.18s |
| `-n auto` (14), run 3 | 196 failed, 7167 passed, 660 errors, 95.62s |

Every client failure is the same line, and it is a **connect-time**
failure: `connection failed: server closed the connection
unexpectedly`. Across all three runs there is not one `does not exist`,
not one `too many clients`, and not one `LockNotAvailable`.

### The force-drop hypothesis is refuted

The issue reads `FATAL: terminating connection due to administrator
command` in the server log and traces it to `DROP DATABASE ... WITH
(FORCE)`, which is correct, and then infers that a force-drop is
terminating some *other* worker's connections. It is not.

With `log_statement='ddl'` and a `log_line_prefix` carrying the
database, run 1 produced exactly **17** of those FATALs against **667**
client failures. Every one of the 17 sits in the teardown window, every
one lands immediately after that same worker's own `drop database
"..._gwN" with (force)` from `_drop_this_process_databases`
(`vinga-server/tests/conftest.py:827`), and every victim is a backend
on the **dropping worker's own** database: its own pooled connections,
left open at session end, taken away with the database they belong to.
No worker ever terminates another's. During the window where the 667
failures happen there is no server-side error of any kind.

The decisive measurement is simpler still. In run 3, with
`log_connections` on, Postgres logged `connection received` **11,576**
times and `connection authorized` **11,576** times, exactly. Every
connection Postgres saw, it accepted. The 602 failed connections in
that run **never reached Postgres at all**, so nothing Postgres or the
fixtures did could have caused them.

### What the constraint actually is

The failures are produced by a limit in the host-to-container published
port path, and the variable is the number of processes concurrently
establishing connections.

Reproduced with no pytest, no fixtures and no `DROP DATABASE`: a script
that opens a connection, runs `select 1`, and closes it, in a tight
loop, from N host processes. Five seconds per point, 40 seconds of
cooldown between points so that accumulated `TIME_WAIT` sockets start
each point near zero:

| Processes | Throughput | Failures |
| ---: | ---: | ---: |
| 6 | 938/s | **0** |
| 8 | 1089/s | **0** |
| 10 | 971/s | 3173 |
| 12 | 1086/s | 2240 |
| 14 | 967/s | 4046 |

Throughput is flat at roughly 1000 connections a second across every
point, while failures appear only from ten processes upward, and their
counts are non-monotonic in exactly the way the issue reported for 10,
12 and 14. The error text is identical to the lane's, verbatim.

The same storm run **inside the container**, where no published port is
involved, does 2764 connections a second at 14 clients with zero
failures (`pgbench -C -c 14`), and 1206 a second when paced, also with
zero failures. Postgres is not the constraint.

### Two further hypotheses, measured and dropped

Recorded because both are plausible, both cost time here, and the
second was briefly believed.

- **A connection-rate limit.** A first sweep appeared to find a knee
  between 600 and 700 connections a second. It was an artifact: the
  sweep ran its points back to back, so each inherited the `TIME_WAIT`
  sockets the one before left behind. Re-run with cooldowns, 700/s and
  900/s are clean.
- **Host ephemeral-port exhaustion.** Real, and not what the lane hits.
  A sustained 900/s burst does die this way: clean for ten seconds,
  first failures as `TIME_WAIT` passes 9,000, total failure past
  11,869, and `TIME_WAIT` then pinned at 16,286 against a macOS
  ephemeral range of 16,384 (`net.inet.ip.portrange` 49152 to 65535).
  But the lane never gets close. Sampling every second through a
  failing `-n auto` run, `TIME_WAIT` peaked at **6,247**, and the
  connections Postgres received in that run peaked at 354/s against the
  green `-n 8` run's 277/s. The lane's rate and socket usage are
  ordinary; only its process count is not.

### Why CI never sees it

For two independent reasons, not the one the issue gives. `auto`
resolves to 4 on a four-core runner, **and** CI reaches Postgres as a
service container on the Docker network, with no published-port path in
between. This is a developer-machine fault by construction, which is
also why no amount of fixture repair would have shown up as a CI
change.

## What this plan does, and what it deliberately does not

The fault is in a third-party desktop tool's port forwarder, on
developer machines only. The proportionate repair is to stop the
documented command asking for more concurrency than that path sustains,
so that the command in `AGENTS.md` is correct everywhere as written.

`pytest-xdist` already has the knob. `--maxprocesses` is applied at
`xdist/plugin.py:322` as `numprocesses = min(numprocesses,
config.option.maxprocesses)`, after `auto` has been resolved, so it
clamps the resolved count rather than replacing the resolution. Setting
it in `addopts` is therefore the whole change.

Four things this plan rejects, each with its reason:

- **Repairing the template teardown, or narrowing `WITH (FORCE)`**, the
  issue's second and third directions. They address a mechanism that
  the measurements show is not happening. A fix committed in response
  to a refuted diagnosis is a fix to the wrong thing.
- **A bounded retry around the lane's connects**, so the path's limit
  stops mattering and all 14 cores stay usable. Rejected on
  proportion. The headroom it would buy is small by construction:
  `--dist loadfile`'s floor is the slowest single file, `-n 8` green is
  123.51s, and every `-n 14` figure in existence, this plan's and the
  issue's 106s alike, comes from a **failing** run and is therefore not
  a comparable green number. Retry machinery, with its backoff budget
  and its own falsification tests, would be built to chase seconds that
  have never been shown to exist.
- **Reducing the lane's connection count** (`clear_store` opens a fresh
  connection per test, about 7,500 a run; roughly 1.6 connections per
  test overall, 13,067 across the green run). It would lower the chance
  that ten workers are connecting in the same instant, so it helps
  probabilistically and cannot make the lane safe: any such instant
  still fails. It is a reasonable efficiency question and it belongs to
  #489 M2, which is the milestone that re-measures fixture overhead.
  This plan notes it there rather than doing it here.
- **Probing the machine for a safe width at startup.** The same
  overcomplication in a smaller box, and it would make the lane's width
  vary run to run, which is worse to debug than a constant.

## Open questions, resolved

### Where the clamp goes: `addopts`, not a conftest hook

`addopts` in `pyproject.toml` is where this repository already keeps
its one invocation-wide testing decision, `--import-mode=importlib`,
under a comment explaining why. A `pytest_cmdline_main` hook in
`tests/conftest.py` that sets `config.option.maxprocesses` would reach
the same value through a mechanism of its own, which is a pass-through
by the deletion test: it would hide nothing that the option does not
already express.

The cost is that `addopts` names an option only `pytest-xdist`
registers, so an environment running pytest without the dev group would
fail on an unrecognized argument. No environment in this repository
does: the throwaway installs `test_tier_closure.py` builds with
`uv sync --frozen --no-dev` run the server and the CLI, never pytest.
The verification below is what holds this claim, and it is checked
rather than asserted.

### The value is 8, as a commented constant

Eight is the last measured-clean point in the sweep above, at zero
failures with the throughput of every broken point, and it is
independently the width at which the full lane runs green. Six would
add margin nobody has shown is needed and would cost real parallelism;
ten is measured broken.

It is a ceiling, not a floor, so it changes nothing where `auto`
already resolves lower: CI's four-core runner resolves 4, and
`min(4, 8)` is 4. It is also overridable, because a later
`--maxprocesses` on the command line wins over the one in `addopts`,
which is what leaves a developer investigating this able to ask for 14
deliberately.

## Milestones

- [ ] **M1: the resolved worker count is bounded**. `--maxprocesses=8`
  joins `addopts` in `vinga-server/pyproject.toml`, under a comment
  carrying the measurement that justifies it: eight processes clean and
  ten broken at the same throughput, the limit in the published-port
  path rather than in Postgres or the fixtures, and CI unaffected
  because its `auto` already resolves lower. A `### Fixed` changelog
  fragment at `changelog.d/537-unit-lane-worker-bound.md`.
  **Design footprint:** none. No module, no seam, no new name. This
  milestone sets one existing option of an existing plugin.
  **Documentation footprint:** none, and that is the point of clamping
  rather than documenting. The command blocks in `AGENTS.md` (L47-L48)
  and `vinga-server/README.md` (L1397-L1398) stay true exactly as
  written, which they are not today on any machine with more than eight
  usable cores.

## Tests and verification

The claim is about an invocation, not about a unit of code, so the
proof is the invocation. A unit test asserting that `addopts` contains
a string would pin the spelling and prove nothing about the behavior.

- The full unit lane at `-n auto --dist loadfile` on a 14-core machine,
  green, which is the exact command and the exact machine class that
  fails today. Falsification is already in hand and recorded above:
  the same command without the clamp fails on three runs out of three.
- The full integration lane at `-n auto --dist loadfile`, which since
  #491 runs distributed too and reaches the same fixtures through the
  same path, so it carries the same hazard and the same clamp.
- `uv run ruff check .`, and the generated-document drift checks.
- The worker count is read off the run's own header (`8 workers` rather
  than `14 workers`), so the clamp is observed rather than inferred
  from the absence of failures.

CI cannot verify the fix, because CI cannot reproduce the fault: its
`auto` resolves to 4 with or without the clamp. What CI verifies is
that the clamp breaks nothing. The PR says so in those words rather
than checking a box it cannot honestly check.

## Risks

- **The constant ages.** Docker Desktop's limit is not a documented
  contract, and a future version may raise or lower it. Mitigated by
  the comment carrying the measurement rather than only the number, so
  the next person can re-run the sweep instead of re-deriving the
  question. A lower limit on some other machine surfaces as the same
  failure, and the comment is where they will land.
- **`addopts` depends on xdist being installed.** Checked above and
  verified by the two lane runs. If some future environment runs pytest
  without the dev group, this becomes an unrecognized-argument failure,
  which is loud and immediate rather than subtle.
- **Eight workers on a very large machine leaves cores idle.** True,
  and the measured cost is small: the lane is 123.51s at eight, against
  a `loadfile` floor set by the slowest file that more workers cannot
  go below. An explicit `--maxprocesses` still overrides it.
