# The duplicated test helpers go home

Plan for [#531](https://github.com/rafacm/vinga/issues/531) M2, as
re-scoped on the issue on 2026-09-24
([comment](https://github.com/rafacm/vinga/issues/531#issuecomment-5815044061)).
Its companion is
`docs/plans/2026-09-24-test-helpers-home-implementation.md`, one
section per milestone, appended in the same change that ticks the
milestone. M3, the reach-in re-sweep, closes measured-and-kept by the
same comment and is not touched here; the pull request for this
plan's one milestone closes #531.

**Local baseline:** not applicable. Every file this plan changes is
under `vinga-server/tests/`; no conversational capability moves.

**Cheapest alternative:** the fifteen walker imports alone (the first
item under "What moves"), which is the one change here that
strengthens a claim rather than only removing a copy. What the rest
buys over it is one home for helpers whose copies must agree for a
stated reason: an Alembic driver that has to mirror
`db.upgrade_to_head`, an SDK client whose `max_retries=0` is what keeps
a failing request countable, and three helpers `tests/support` already
holds and that copies ignore. None of it is a number claim, so there
is nothing to measure against; it costs the same pull request and the
same review round, which is why it rides along instead of waiting.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.281; 2026-09-24.

## Where this starts from

Measured at `1bcf3dc4` (`main`'s head on 2026-09-24), with the
instruments named here so a later session can run them again.

**The duplicate census.** Module-level, non-test functions whose
bodies are AST-identical in more than one file, excluding
`tests/support`: **71 groups, 213 definitions, 105 files**, about 670
redundant lines of roughly 171,000. 29 groups are pytest fixtures
throughout; of the 42 that are not, 27 run to four lines or more.

**The drift that matters.** `tests/support/config_cli.py:353` holds a
secret walker, `chain`, that reads an exception's `repr`, its `str`,
its `args` and two levels of its attributes (`_held`), because a PyYAML
mark once carried a whole parsed source in an attribute the repr never
showed. **Fifteen** test files carry an older, AST-identical walker
that reads `repr` and `str` only, under the names `chain` and
`_chain`, and assert `SENTINEL not in` its result. The issue comment
said six; it matched by name, and nine of the fifteen are spelled
`_chain`. The fifteen:

`test_boundary_contract.py`, `test_config_apply.py`,
`test_config_bodies.py`, `test_config_env_names.py`,
`test_config_fragments.py`, `test_config_secrets.py`,
`test_config_store.py`, `test_doctor.py`, `test_onboarding_config.py`,
`test_providers.py`, `test_providers_elevenlabs.py`,
`test_providers_llm_tools.py`, `test_providers_openai_asr.py`,
`test_providers_openai_tts.py`, `test_secret_resolution.py`, all under
`tests/unit/`.

Rebinding the walker in all fifteen to the support one (confirmed by
import, not assumed) left all **687** of their tests green. The gap is
latent: nothing leaks through an attribute today, and nothing would
say so if it started to.

**Measured and left alone: the log renderers.** Eighteen files carry
seven variants of a log-leak renderer, most filtered to
`vinga_server.*` loggers, where `tests/support/leaks.renderings`
renders every record three ways and deliberately filters nothing.
Rebinding all eighteen to `renderings` failed **34** tests, and every
one of the 34 was the test client's own `httpx2` request line carrying
the value the test put in the URL, which is the filter's documented
reason. Rebinding them to `renderings` restricted to `vinga_server.*`
left all **700** green. So the filtered copies hide nothing this
server writes; whether `leaks.py`'s "every record" stance should reach
them is a decision about that module, not drift, and is not this
plan's.

## What moves

Each item names its home, what its callers stop having to know, and
the files it touches. Where an item claims a copy is identical to its
destination, the implementer confirms it by AST comparison before
replacing it, recorded in the implementation doc. Where an item maps a
copy that is not identical (item 4's table, item 1's walkers, item 7's
readers), it states the equivalence it relies on and how that is
checked, and the implementer records the check. A copy that differs
from what its item says is reported rather than silently unified.

1. **The secret walker goes to `tests/support/leaks.py`.** `chain`
   and `_held` move there from `tests/support/config_cli.py`, whose
   own callers import it from the new home; no re-export is left
   behind, since a name forwarded from one module to another is a
   pass-through. `leaks.py` is the right home because its module
   docstring already states the rule this applies ("a walk copied into
   each of them is one decision in two places, and the weaker of the
   two copies is the one nobody notices"); the docstring grows a
   paragraph saying it now holds the exception walk as well as the
   record walk. The fifteen files above delete their copy and import
   `chain`; a file whose local name was `_chain` renames its call
   sites. What callers stop knowing: which parts of an exception can
   carry a value out.

   The strong walker already has callers at its old home: 23 unit
   modules import `chain` from `tests.support.config_cli`, six of them
   aliased `_chain` (found by an AST walk of every `ImportFrom`, not by
   grep, at `1bcf3dc4`: `test_config_cli.py`,
   `test_config_cli_check.py`, `test_config_cli_confirmation.py`,
   `test_config_cli_dotenv.py`, `test_config_cli_events.py`,
   `test_config_cli_grammar.py`, `test_config_cli_info.py`,
   `test_config_cli_rendering.py`, `test_config_cli_secrets.py`,
   `test_config_cli_summary.py`, `test_config_cli_transport.py`,
   `test_config_cli_untransportable.py`,
   `test_config_control_character_identities.py`,
   `test_config_docgen.py`, `test_config_round_trip.py`,
   `test_config_url_credential_display.py`, `test_device_record.py`,
   `test_device_record_no_leak.py`, `test_missing_server_half.py`,
   `test_server_reference.py`, `test_session_device_location.py`,
   `test_simulator_board.py`, `test_simulator_conversation.py`). Each
   moves its import to `tests.support.leaks`, keeping its alias, in the
   same commit that deletes the old definition; the same AST walk
   rerun afterwards finds no import of `chain` or `_held` from
   `tests.support.config_cli`, and its count is recorded.

   Moving it, the walk is made complete in three ways, so that every
   walker it replaces is a subset of it by construction rather than by
   inspection:

   - It reads `str()` of each argument as well as the `repr` of the
     tuple: the one reading `_whole_chain` below makes that it lacked,
     for an argument whose `str` and `repr` differ.
   - It visits the exception graph rather than a chain. Today's walk,
     and every copy of it, follows `__cause__ or __context__`, so an
     exception carrying both is followed down its cause alone and a
     value that sits only in its context is never read. Python's own
     traceback printer suppresses that context too, but a handler
     that walks the objects (an error reporter, a structured logger)
     does not, and the no-leak lens names both links. Both links are
     followed from every exception, with an identity-keyed seen set,
     so a cycle terminates. The traversal is its own public operation,
     `links(exc)`, every exception in the graph in visit order, and
     `chain` renders over it, so a walker that renders differently
     (item 1's table keeps two) reuses the traversal instead of
     spelling a weaker one.
   - `_held` renders each attribute as `name=value!r`, at both levels,
     rather than the value alone: `carried` reads names too, and a
     value can travel as a key as easily as a value.

   The other seven exception walkers in the suite are not
   AST-identical to either version. Settled here, each read at
   `1bcf3dc4`, and binding: a source found to differ from what the
   table says is reported as a blocker rather than re-decided.

   | Walker | Reads | Disposition |
   |---|---|---|
   | `_whole_chain`, `test_providers_boundary.py:678` | `str` of each link and of each argument | Replaced by `leaks.chain`, a superset once it reads `str` of arguments |
   | `_whole_chain`, `test_reach_upgrade.py:404` | the same | Replaced, the same |
   | `carried`, `test_cli_live.py:411` | `repr`, `str`, and one attribute level deeper | Replaced: `_held` reads the same two levels, names and values, once it renders `name=value!r`. Its docstring's claim that `config_cli.chain` reads only `repr` and `str` has been stale since `_held` was added, and goes with it. Its deliberate-leak case (`:3029`, which must find the plant) stays and now proves `leaks.chain` finds it |
   | `chained`, `test_turntaking.py:120` | type name and `str` of each link | Replaced: `repr` carries the type name |
   | `chained`, `test_mcp_composed_reference.py:227` | the formatted traceback of each link, and its `repr` | Kept as a renderer: the traceback is a surface of its own (source lines, frames), which no rendering of the exception reproduces. Its traversal, which follows `__cause__ or __context__` and so has the same missing-context gap, is replaced by `links` |
   | `Consumer.rendered`, `test_server_event_pins.py:99` | every emission's payload and arguments, walking the chain of an argument that is an exception | Kept as a renderer of emissions; its exception walk delegates to `leaks.chain`, which carries `links` |
   | `chain`, `test_session_reply_failures.py:103` | nothing rendered: returns the exception objects | Kept: its callers assert on the objects, not on text |

   The walker gets committed pins in a new
   `tests/unit/test_support_leaks.py`, on the precedent of
   `test_support_fakes.py` ("what the shared fakes promise, pinned
   where the fakes live"), because fifteen suites' secret-absence
   claims now rest on it and none of their own tests can fail if it
   weakens: no exception in the tree carries a value where only the
   stronger walk looks. One case per reading the walk promises, each
   planting a sentinel only there: an attribute of the exception; an
   attribute of an object held by an attribute (the PyYAML mark shape,
   an object whose `buffer` holds the value); an attribute's name, at
   each of those two levels; an argument whose `str`
   reveals it and whose `repr` does not; the `__cause__` and the
   `__context__` of a raised exception; an exception carrying both
   links with the sentinel only down the context; and a graph with a
   cycle through both links, which must terminate. `links` gets its own
   pin, that it yields every exception of a branching graph exactly
   once. Each is watched
   failing against the old walk before it is committed (the cycle case
   excepted, which the old walk also survives; it pins termination).

2. **The migration driver gets a home: new `tests/support/migrations.py`.**
   Four integration tests (`test_device_record_upgrade.py`,
   `test_domain_upgrade.py`, `test_memory_upgrade.py`,
   `test_reach_upgrade.py`) carry the same fifteen-line fixture body
   that drives Alembic to a named revision "the way
   `db.upgrade_to_head` drives it", differing only in the chain, and
   `test_metrics_views_upgrade.py`'s `_stamped` is the same driver
   with the revision as a parameter. Five integration files carry
   `_version(settings)`, identical but for the chain's schema. Two unit
   files (`test_conversations_schema.py`, `test_memory_schema.py`)
   carry an identical `_version(engine, schema_name)`.

   The module owns every Alembic invocation the tests make, through
   one private builder of the Alembic config (the script location, the
   open connection and the chain, the three things the packaged
   environment refuses to run without). On it sit three operations,
   each owning its whole transaction, which is the shape every copy
   has today:

   - **Upgrade to a revision** (a database name, a chain and a
     revision in; the settings out): opens a write engine for the
     chain, creates the chain's schema (Alembic's version table lives
     in it, which is why `upgrade_to_head` creates it first), upgrades,
     commits, and disposes the engine in a `finally`.
   - **Downgrade to a revision** (settings, a chain and a revision in):
     the same shape without the schema creation. Both metrics
     downgrade sites (`:417`, `:512`) already open their own engine,
     downgrade, commit and dispose, so taking settings rather than a
     connection moves them whole.
   - **The stamped-version read** (by engine and schema, with a
     settings-and-chain form over it that opens and disposes a read
     engine).

   On failure each propagates the exception, the connection's context
   exit discards the uncommitted work, and the engine is disposed:
   what every copy does now. No test is added for that failure path.
   These are behavior-preserving moves of test fixtures, and what they
   preserve is the success path the five upgrade files drive;
   pinning a support helper's cleanup would pin a detail no caller
   relies on.

   `test_metrics_views_upgrade.py`'s `_alembic` is deleted and its two
   downgrades and its `_stamped` route through the module. The
   fixtures stay in their files as one-line calls, per the scope the
   issue comment settled. What callers stop knowing: the config the
   packaged environment needs, and the schema it needs first, in
   either direction.

   `vinga_server.db` exposes no revision-parameterized operation:
   `upgrade_to_head` (`db/__init__.py:452`) builds its own config
   privately at `:511` and targets head only. Widening the production
   interface for tests is out of this tests-only plan, so the support
   builder is the one test-side mirror of that private one, and says
   so in its docstring, naming `upgrade_to_head` as what it mirrors.
   The differing `_version`s in `test_db_open.py` and
   `test_conversations_boot.py` (one returns a single string) and the
   per-file `_rows` readers stay.

3. **`speech_pcm` uses the home it already has.**
   `tests/support/wire.py:94` defines it; `tests/integration/conftest.py`,
   `test_device_simulator.py`, `test_telemetry_export.py` and
   `tests/smoke/test_smoke.py` import it instead of defining it. Every
   copy computes over a `SAMPLE_RATE` of 16000, the value `wire.py`
   imports from `tests/support/configs.py:65`; a copy whose local
   `SAMPLE_RATE` still has other readers keeps that constant.

   The smoke lane is no exception. It is a black box in what it talks
   to (a running container), not in what it imports: its conftest
   already imports `vinga_server.auth` and `vinga_server.config.models`,
   pytest loads `tests/conftest.py` for it, and CI runs it from the
   checkout with the contributor environment installed. Importing a
   client-side waveform does not make the server any less external.
   A separate server-agnostic module for the one function, which the
   review offered, is not taken: `wire.py` would import it back, and a
   module whose whole content one other module re-exports fails the
   deletion test. The smoke lane is opt-in locally, so its import is
   verified by collecting it (`--collect-only`), and by the `image`
   job on the pull request.

4. **The stdio MCP entries use the home they already have.**
   `tests/support/tools_mcp.py` defines `entry_data` (a `dict`) and
   `stdio_entry` (an `McpServerConfig`). Not every copy is
   AST-identical to its destination, so each is mapped by return shape
   and proven equal rather than assumed:

   | Copy | Returns | Becomes | Identity |
   |---|---|---|---|
   | `stdio_entry`, `test_agent_guidance.py:64` | `dict` | `entry_data` | AST-identical but for the name |
   | `stdio_server`, `test_tools.py:30` | `dict` | `entry_data` | AST-identical but for the name |
   | `entry_data`, `test_config_api_runtime.py:108` | `dict` | `entry_data` | AST-identical |
   | `entry_data`, `test_tools_mcp_reload.py:83` | `dict` | `entry_data` | AST-identical |
   | `stdio_entry()`, `test_mcp_reload.py:41` | `dict` | `entry_data()` | No overrides parameter; equal for the no-argument call, which is every call it has |
   | `stdio_entry`, `test_tools_mcp_prompts.py:69` | model | `stdio_entry` | AST-identical |
   | `stdio_entry`, `test_tools_mcp_reload.py:91` | model | `stdio_entry` | `model_validate(entry_data(...))`: equal, and the better spelling |

   The last row's spelling becomes the support one: `stdio_entry` is
   defined over `entry_data`, so the support module stops holding the
   literal twice. Each file's own `STDIO_SERVER` is checked to be the
   same path as `tests/support/configs.STDIO_SERVER` before its copy
   goes. Equality is checked per public signature and recorded in the
   implementation doc: for a helper that accepts overrides, with none,
   with an `args` override and with an `env` override; for
   `test_mcp_reload.py`'s `stdio_entry()`, which accepts none, for the
   no-argument call alone.

5. **The OpenAI SDK client for provider tests.** `mock_client`, 13
   lines, identical in `test_providers_openai_asr.py` and
   `test_providers_openai_tts.py`, goes to a new
   `tests/support/openai_sdk.py`. Not `llm_sdk.py`: that module's
   docstring defines it as fake shapes for the two streamed LLM
   dialects, and this is a real `AsyncOpenAI` client over a mock
   transport for the speech providers. Its `max_retries=0` and the
   comment explaining it are the reason the two must agree: without
   it the SDK triples a deliberately failing request and hides how
   many the provider sends. The module passes the deletion test on
   that reason, since inlining it back means two suites each holding
   the retry and transport policy. What callers stop knowing: how the
   SDK is kept from retrying and from reaching the network. This one
   is an addition to the comment's list, made because it meets the
   issue's own test for moving (a reader of one copy would want the
   other to change with it).

6. **CLI invocation capture joins the CLI runner.** `out(run, capsys,
   *argv)`, identical in five CLI suites (`test_config_cli_conversations.py`,
   `test_config_cli_memory.py`, `test_config_cli_metrics.py`,
   `test_config_cli_rename.py`, `test_config_cli_sessions.py`), clears
   the capture, runs one command and returns its code and both
   streams. It goes to `tests/support/config_cli.py` beside `runner`,
   whose output it is the reading of. What callers stop knowing: that
   a stale capture has to be drained first.

7. **The ordered conversation-row read deepens the one that exists.**
   `stored`/`rows_of`, identical in `test_conversations_erasure.py`,
   `test_conversations_namespace.py` and `test_conversations_retention.py`,
   reads `record.<table>` ordered by id through `read_engine`.
   `tests/support/stores.py:237` already offers `rows(table, **where)`
   for the same schema, but opens it through `open_conversations`,
   which is "open and migrate" and takes the chain's advisory lock
   before it reads. That is wrong for a function whose docstring says
   it is "what a reader beside a running writer is": it can migrate
   while inspecting, and it can queue behind the writer it sits
   beside. So, in this order and as separate commits: `rows` first
   moves to `read_engine`, whose contract (`db/__init__.py:358`) is
   exactly "neither migrates nor takes the lock", and its nine caller
   files (`test_agent_rename.py`, `test_agent_rename_in_flight.py`,
   `test_conversations_durable.py`, `test_conversations_store.py`,
   `test_conversations_threads.py`, `test_device_record_no_leak.py`,
   `test_device_swap.py`, `test_session_device_name.py`,
   `test_session_record.py`, inventoried by grep and rerun in full)
   stay green; then it gains `order by id`, deterministic for every
   caller, and the files are run again; then the three copies call it.
   A caller that turns out to depend on `rows` migrating a fresh
   database stops the item and is reported, since that caller was
   reading through a writer's path by accident.

   The read contract gets one lasting pin, in a new
   `tests/unit/test_support_stores.py` beside `test_support_fakes.py`:
   with the conversations chain's advisory lock held by
   `the_lock_held(CONVERSATIONS_CHAIN)` (`tests/support/stores.py:85`),
   `rows` on an already-migrated database returns within a short bound.
   That is the caller-visible property (a reader beside a writer does
   not queue behind it) rather than which engine the helper opens, and
   it is watched failing, by timing out, against the
   `open_conversations` version before the switch.

   *Dropped at implementation, under this item's own stop rule.*
   Moving `rows` to `read_engine` made two tests in
   `test_agent_rename_in_flight.py` fail intermittently: they read the
   record while the conversation store's writer is still committing, and
   see it only because `rows` waits on the chain's advisory lock. That
   wait is load-bearing, so the three `read_engine` copies are a
   different reader rather than a duplicate of `rows`, and merging them
   would have meant adding drains to those tests. `rows` keeps its
   engine, its docstring now says what it waits for and who relies on
   it, and `test_support_stores.py` is not added. The implementation
   doc's M1 section has the measurements.

8. **The scripted LLM's tool-result reads go beside the fake.**
   Two projections of the shape `ScriptedLlm` records in `seen` are
   each identical in `test_session_conversations.py` and
   `test_session_recap.py`: `results_of`/`_results` (every tool
   result's content, in order) and `errors_of`/`_errors` (every tool
   result's `is_error`). `ScriptedLlm` lives in
   `tests/support/providers.py:79`, so a change to what it records
   breaks all four copies at once. Both reads join it there, over one
   shared walk of the recorded tool results, keeping the names
   `results_of` and `errors_of`.

## What stays, and why

- **Every fixture**, including the two-line `api`, `run`, `client`
  and `keys` groups. Each configures the file it sits in, and sharing
  one means a shared conftest (injection a reader cannot see) or an
  imported fixture; both make a test harder to read. Where a fixture's
  substance must agree (item 2), the substance moves and the fixture
  stays as a one-line call.
- **`tap`, dropped from the comment's list.** The fixture is
  identical in seven files (two more differ only in building a class
  named `Consumer`), but the class it builds is not: the
  first three measured are 8, 19 and 12 lines, each rendering what
  its own file asserts on. The shared part is attach, yield, detach,
  around `vinga_server.events`' own `attach_server_tap` and
  `detach_server_tap`; moving four lines of protocol while the
  per-file class stays buys nothing the deletion test would keep.
- **The log renderers**, for the reason measured above.
- **Every other group of four lines or more**, each for its own
  reason. Groups of three lines or fewer that are not fixtures stay
  as a class: at that size the import costs what the copy does.

  | Group | Files | Why it stays |
  |---|---|---|
  | `leaked`, `_leaked`, `logged`/`written` | 11 | The log renderers, measured above |
  | `envelope_of` | 2 | Its predicate names the slot each file's own setup plants (`llm`/`mock`); it moves if that setup does |
  | `manifest`, `bound_config`/`drain_config`, `banner_config` | 2 each | Test data: literals of the world each file builds, `banner_config` over a per-file `PINNED_KEY` |
  | `_pull` | 2 | One subprocess call over a per-file deadline constant |
  | `run` (`test_upstream_watch.py`, `test_wire_latency.py`) | 2 | Identical syntax over a per-file `SCRIPT` naming different scripts: identical by accident |
  | `_captured` | 2 | Builds each file's own `_Stream` class |
  | `failing` | 2 | A two-statement closure standing in for a boot read |
  | `_entries`, `entries` (the two census modules) | 2 | Each strips its own module's `MANIFEST_HEADER` |
  | `_config_file` | 2 | Writes one file under `tmp_path` |
  | `_get`, `erase_thread` | 3, 2 | One request plus the status each suite asserts about its own route |
  | `running` | 2 | Constructs and starts a manager, two statements |
  | `stored`, `rows_of` | 3 | A reader that never waits for a writer, where `stores.rows` waits on the chain's lock and two tests rely on that; item 7 was dropped for this reason |

## Verification

- **Pin before reshaping.** Collected test counts per lane
  (`--collect-only -q`, the summary line, untruncated) recorded before
  the first move and unchanged after; unit and integration lanes green
  with `-n auto --dist loadfile`; `ruff check .` clean.
- **Falsify the walker's reach.** The committed pins in
  `test_support_leaks.py` are the lasting protection, each watched
  failing against the old walk. As supplementary evidence that the
  callers now reach it, one mutation per family, run both ways and
  recorded: in one provider error path and one config error path,
  attach the planted secret to the raised exception as an attribute.
  With `leaks.chain`, that file's secret-absence test goes red; with
  the old walker restored locally, it stays green.
- **Falsify the driver move.** Break the support upgrade (target head
  instead of the revision) and watch all five upgrade files go red;
  break the support downgrade (make it a no-op) and watch the two
  metrics downgrade cases go red. Together they prove every Alembic
  invocation in the tests goes through the module.
- **Inventory by tooling.** The duplicate census and the walker
  inventory rerun after the change, untruncated, with the before and
  after counts in the implementation doc: the fifteen weak walkers
  gone, and the census down by the groups moved and no others.
- **Censuses.** `tests/census` green; the reach-in manifest
  regenerated if the moves shift a `path  name` pair, never by hand.

## Standing lenses

- **No-leak:** this plan strengthens fifteen no-leak checks and
  weakens none; the walker mutation above is its sentinel test.
- **Pin before reshaping, inventories by tooling, falsify before
  claiming, proportion:** as under Verification and "Cheapest
  alternative".
- **Closed sets, honest seams:** not touched; no production code
  changes.

## Documentation footprint

No hand-maintained page describes these helpers' locations. The
implementer confirms that with a grep for `config_cli import chain`,
`_chain`, `speech_pcm`, `stdio_entry` and `mock_client` over `docs/`
and the root `README.md`, recorded in full. `leaks.py`'s docstring is
the page that owns the fact and grows as item 1 says. A changelog
fragment, `changelog.d/531-test-helpers-home.md`, under `### Changed`.

## Milestones

- [x] **[M1: the helpers go home](2026-09-24-test-helpers-home-implementation.md#m1-the-helpers-go-home)**
  (#531 M2; PR #566; item 7 dropped at implementation, see its note).
  Items 1 to 8 above, one
  commit per item, the verification above, the changelog fragment.
  Design footprint: deepens `tests/support/leaks.py` (the exception
  walk joins the record walk), `tests/support/config_cli.py` (the
  capture joins the runner) and `tests/support/providers.py` (the scripted
  fake's two reads join it); adds `tests/support/migrations.py` (callers
  stop knowing the Alembic environment's three requirements) and
  `tests/support/openai_sdk.py` (callers stop knowing how the SDK is
  kept from retrying and from reaching the network).
  Documentation footprint: `leaks.py`'s docstring, and `stores.rows`'
  docstring corrected when item 7 was dropped. Closes #531.

## Plan review round

Reviewed 2026-09-24 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 7m59s, at commit 816352ee, plan blob bf936ad4.

---

1. **P1: The stronger secret walker has no lasting regression test**

   Evidence: The plan admits the existing tests remain green with the weak walker because no current exception carries the sentinel through an attribute (plan, lines 59-62 (`plan:59`)). Verification proposes only a temporary mutation (lines 194-200 (`plan:194`)). Consequently, reverting `chain` later to the old `repr`/`str` walk would leave the committed suite green. The behavior that matters, including the PyYAML-like second-level attribute described by `config_cli.py`, lines 367-381 (`tests/support/config_cli.py:367`), is not pinned.

   The plan should say instead: add committed tests for `leaks.chain` using an exception with a direct secret attribute, an attribute object whose hidden `buffer` contains the secret, chained exceptions, and a cycle. Keep the mutation as supplementary evidence, not the only protection.

   *Resolution:* accepted. Item 1 now commits `tests/unit/test_support_leaks.py`, one pin per reading the walk promises (a held attribute, the PyYAML-mark second level, a revealing `str` argument, cause, context, a cycle), each watched failing against the old walk; the mutation stays under Verification as supplementary evidence that the callers reach the walker.

2. **P1: The migration module leaves Alembic configuration duplicated and would strand downgrade callers**

   Evidence: The proposed interface exposes only blank-database upgrade and version reads (plan, lines 111-136 (`plan:111`)). However, `test_metrics_views_upgrade.py` builds the same Alembic configuration in `_alembic` (lines 103-113 (`tests/integration/test_metrics_views_upgrade.py:103`)) and still needs it for two downgrades (lines 407-420 (`tests/integration/test_metrics_views_upgrade.py:407`), lines 509-515 (`tests/integration/test_metrics_views_upgrade.py:509`)). Deleting `_alembic` breaks those tests; retaining it leaves the three Alembic requirements in two places, contradicting the module’s stated locality benefit.

   The plan should say instead: make `tests/support/migrations.py` own both upgrade-to-revision and downgrade-to-revision operations through one private Alembic-config builder. Route both downgrade cases through it and extend verification to cover that route.

   *Resolution:* accepted. Item 2's module now owns every Alembic invocation the tests make through one private config builder, with upgrade-to-revision, downgrade-to-revision and the version read on it; `_alembic` is deleted and both metrics downgrades route through the module, and Verification breaks the downgrade as well as the upgrade. Checked while amending: `vinga_server.db` exposes no revision-parameterized operation (`upgrade_to_head` builds its config privately at `db/__init__.py:511`), so the support builder is the one test-side mirror of it.

3. **P2: The plan defers resolvable exception-walker decisions to implementation**

   Evidence: The plan leaves seven walkers to conditional disposition in the implementation document (lines 99-109 (`plan:99`)). The current tree already resolves most of them: both `_whole_chain` implementations inspect only text and arguments (provider boundary, lines 678-689 (`tests/unit/test_providers_boundary.py:678`), reach upgrade, lines 404-416 (`tests/integration/test_reach_upgrade.py:404`)); `carried` performs the same attribute walk less completely (CLI live, lines 411-438 (`tests/integration/test_cli_live.py:411`)); and `turntaking.chained` is another weaker secret-absence walk (lines 120-130 (`tests/unit/test_turntaking.py:120`)). `Consumer.rendered` cannot be replaced wholesale, but its exception traversal can delegate to `leaks.chain` (server event pins, lines 99-114 (`tests/unit/test_server_event_pins.py:99`)).

   The plan should say instead: name which four weak walkers are replaced, which composite renderer delegates exception handling to `chain`, and which walkers remain because they preserve traceback formatting or return exception objects.

   *Resolution:* accepted, with the reviewer's reading confirmed at each site. Item 1 now carries a table: both `_whole_chain`s, `carried` and `turntaking.chained` are replaced; `Consumer.rendered` delegates its exception walk; the composed-reference `chained` (formatted tracebacks) and `test_session_reply_failures.chain` (returns objects) are kept with their reasons. To make "superset" true by construction, `leaks.chain` also gains `str()` of each argument, the one reading `_whole_chain` makes that it lacked, and item 1's pins cover it.

4. **P2: The residual duplicate inventory omits meaningful multi-file groups**

   Evidence: The plan characterizes everything else as three lines or fewer or unrelated two-file pairs (lines 184-186 (`plan:184`)). That does not cover the identical five-file `out(run, capsys, ...)` helper, for example `test_config_cli_sessions.py`, lines 145-149 (`tests/unit/test_config_cli_sessions.py:145`), nor the identical ordered conversation-row reader in three files (namespace, lines 191-202 (`tests/unit/test_conversations_namespace.py:191`), retention, lines 202-213 (`tests/unit/test_conversations_retention.py:202`), erasure, lines 194-205 (`tests/unit/test_conversations_erasure.py:194`)). Both groups share domain meaning, not merely syntax.

   The plan should say instead: move CLI invocation capture into `tests/support/config_cli.py`, deepen `tests/support/stores.py` to own the ordered conversation-row read, or provide explicit per-group reasons for keeping them. A blanket line-count disposition does not satisfy #531’s semantic test.

   *Resolution:* accepted. Three items added: `out` joins `runner` in `tests/support/config_cli.py` (item 6); the ordered row reader turns out to have a home already, `tests/support/stores.py:237` `rows`, which gains `order by id` (item 7, with the engine difference checked rather than assumed); and `errors_of`, which the same semantic test catches, joins `ScriptedLlm` in `tests/support/providers.py` (item 8). The blanket line is replaced by a table giving each remaining group of four lines or more its own reason.

5. **P2: The stdio helpers cannot pass the plan’s required AST-identity check**

   Evidence: The plan requires every moved body to be AST-identical to its destination and says divergent copies are not silently unified (lines 79-83 (`plan:79`)), then calls all listed stdio helpers identical (lines 146-155 (`plan:146`)). `test_mcp_reload.stdio_entry` has no override parameter or dictionary union (lines 41-46 (`tests/integration/test_mcp_reload.py:41`)), while `test_tools_mcp_reload.stdio_entry` calls its local `entry_data` and carries a docstring (lines 83-94 (`tests/unit/test_tools_mcp_reload.py:83`)). Neither body is AST-identical to the support destination.

   The plan should say instead: record explicit behavior-preserving mappings by return shape, including `test_mcp_reload.stdio_entry()` to `entry_data()` and both local helpers in `test_tools_mcp_reload` to the corresponding support functions. Verify equality for representative overrides rather than promising AST identity where it does not exist.

   *Resolution:* accepted, confirmed at each site. Item 4 is now a mapping by return shape with the identity each copy actually has: five `dict` copies to `entry_data` (one, `test_mcp_reload.stdio_entry()`, has no overrides and is equal for the only call it takes), two model copies to `stdio_entry`. Equality is checked for representative overrides and each file's `STDIO_SERVER` against the support one, rather than AST identity promised. The support `stdio_entry` is redefined over `entry_data`, which `test_tools_mcp_reload.py` already did, so the literal lives once.

6. **P2: The smoke-copy exception rests on a false isolation claim**

   Evidence: The plan says the smoke lane imports nothing except its own conftest and therefore must retain `speech_pcm` (lines 138-144 (`plan:138`)). In fact, the smoke conftest imports `vinga_server.auth` and `vinga_server.config.models` (lines 53-67 (`tests/smoke/conftest.py:53`)), and CI installs the full contributor environment before running smoke tests from the checkout (workflow, lines 1237-1252 (`.github/workflows/vinga-server.yml:1237`), lines 1646-1655 (`.github/workflows/vinga-server.yml:1646`)). Importing a client-side waveform generator does not make the server cease to be the external container.

   The plan should say instead: move the pure waveform generator to a server-agnostic support module and import it from `wire.py`, integration tests, and smoke tests. If smoke intentionally keeps an independent protocol oracle, state that semantic reason explicitly and verify the two copies separately; do not cite unavailable imports.

   *Resolution:* accepted in substance. The isolation claim was false and is gone: item 3 now moves the smoke copy as well, stating why the lane is a black box in what it talks to rather than what it imports, and verifies it by collection locally and by the `image` job. The server-agnostic module is not taken: `wire.py` would import the one function back, which fails the deletion test, and `wire.py` is importable wherever the smoke lane runs.

7. **P2: `llm_sdk.py` does not own the proposed ASR/TTS helper as documented**

   Evidence: The plan places the shared `AsyncOpenAI` client constructor in `tests/support/llm_sdk.py` and says only `leaks.py` needs documentation changes (plan, lines 157-165 (`plan:157`), lines 221-228 (`plan:221`)). The destination module explicitly defines its responsibility as fake shapes for the two streamed LLM dialects (`llm_sdk.py`, lines 1-17 (`tests/support/llm_sdk.py:1`)); the new helper instead constructs a real SDK client for ASR and TTS mock transports.

   The plan should say instead: give the constructor an OpenAI-wide SDK home, such as `tests/support/openai_sdk.py`, or explicitly broaden and update `llm_sdk.py`’s responsibility and documentation footprint. The former passes the deletion test because two suites otherwise duplicate the retry and transport policy.

   *Resolution:* accepted. Item 5 now puts `mock_client` in a new `tests/support/openai_sdk.py`, with the deletion-test reason written down (inlined back, two suites each hold the retry and transport policy), and the milestone's design footprint names it in place of `llm_sdk.py`.

**Verdict:** ready after the P1/P2 amendments.

## Plan review round 2

Reviewed 2026-09-24 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 3m04s, at commit d722bb9f, plan blob 22196f55.

---

1. **P1: `leaks.chain` still misses a context when a cause also exists**

   Evidence: Plan item 1 promises both `__cause__` and `__context__` coverage, but the inherited walker follows only `current.__cause__ or current.__context__` (config_cli.py (`tests/support/config_cli.py:353`)). A sentinel solely in `__context__` is missed whenever that exception also has a cause. Separate cause and context tests do not catch this.

   The plan should say instead: traverse the exception graph, visiting both links independently with an identity-based seen set. Pin a branching case with both links populated, with the sentinel only in the context branch, plus a cyclic graph.

   *Resolution:* accepted. Item 1 now makes the walk visit the exception graph, both links from every exception with an identity-keyed seen set, and the pins add an exception carrying both links with the sentinel only down the context, and a cycle through both links. This goes beyond parity with the copies: every copy had the same blind spot.

2. **P1: The proposed ordered-row home is not read-only**

   Evidence: Item 7 says `rows()` can replace readers using `read_engine` if `open_conversations` “must not migrate or write” (plan (`plan:266`)). But `rows()` calls `open_conversations` (stores.py (`tests/support/stores.py:237`)), whose contract is explicitly “Open and migrate” (store.py (`src/vinga_server/conversations/store.py:631`)). This fails the plan’s stated prerequisite and can acquire migration locks or mutate a database while merely inspecting it.

   The plan should say instead: first change `rows()` to use `read_engine`, preserving its second-engine purpose, then add `ORDER BY id`; verify all existing `rows` callers and a test that the reader neither invokes migration nor takes the writer path before replacing the three local readers.

   *Resolution:* accepted, confirmed at `conversations/store.py:631` and `db/__init__.py:358`, with one further reason: through `open_conversations`, `rows` also takes the advisory lock, so a reader documented as sitting beside a running writer could queue behind it. Item 7 now moves `rows` to `read_engine` first, as its own commit, with all nine caller files inventoried and rerun, then adds `order by id`, then replaces the copies. The dedicated test that the reader never migrates is not added: that is `read_engine`'s documented contract, and pinning which engine a support helper opens would pin a detail rather than a behavior its callers rely on.

3. **P2: The resolved stdio exception is still contradicted by the plan’s requirements**

   Evidence: The opening rule still requires AST identity for every moved body (plan (`plan:79`)), while item 4 correctly identifies non-identical mappings. It also requires `args` and `env` equality checks for each copy, despite `test_mcp_reload.stdio_entry()` accepting no overrides (test_mcp_reload.py (`tests/integration/test_mcp_reload.py:41`)).

   The plan should say instead: require AST comparison only where AST identity is claimed; require documented behavioral equivalence for the table’s non-identical mappings. Test override cases only for helpers whose public signature accepts overrides, and test the no-argument helper only for its sole supported call.

   *Resolution:* accepted. The opening rule now requires AST comparison only where an item claims identity, and a stated, checked equivalence where it maps a copy that is not identical; item 4 checks overrides only for helpers whose signature accepts them, and `test_mcp_reload.stdio_entry()` for its no-argument call alone.

4. **P2: Item 1 reopens decisions it says are settled**

   Evidence: The table gives final dispositions for all seven exception walkers (plan (`plan:119`)), but duplicated stale text immediately afterward says implementation will move each walker only “if” it is weaker (plan (`plan:148`)). That undoes the prior-review resolution and leaves scope to implementer discretion.

   The plan should say instead: remove the duplicated conditional disposition text. Retain the table as the binding implementation scope, with only unexpected source divergence reported as a blocker.

   *Resolution:* accepted, and the cause was mine: the round 1 amendment spliced item 1 with its anchors in the wrong order, which duplicated the pins paragraph and left the stale conditional text standing. Item 1 is rewritten once: the completed walk, the table (now stated as binding, with an unexpected divergence reported as a blocker), then the pins.

Verdict: **ready after the P1/P2 amendments.**

## Plan review round 3

Reviewed 2026-09-24 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 4m06s, at commit 8175050c, plan blob 4739d491.

---

1. **P1: Removing `config_cli.chain` leaves existing imports broken**

   Evidence: Item 1 requires no re-export but names only the fifteen local-walker files (plan lines 88-100). At least 24 other unit modules directly import `chain` from `tests.support.config_cli`, for example `test_config_cli_check.py:57`, `test_config_cli_events.py:46`, `test_config_cli_rendering.py:40`, `test_device_record.py:36`, and `test_device_record_no_leak.py:62`.

   The plan should say instead: inventory and update every existing `tests.support.config_cli.chain` import to `tests.support.leaks.chain`, including aliases, before deleting the old definition; verify no imports from the old home remain.

   *Resolution:* accepted, and the count confirmed by an AST walk of every `ImportFrom`: 23 modules, six aliasing it `_chain`. Item 1 now lists them, moves each import in the commit that deletes the old definition, and reruns the walk to show none remain.

2. **P1: The proposed replacement is not a superset of `carried`**

   Evidence: Item 1 says `_held` reads the same two attribute levels as `test_cli_live.carried` (plan line 128). `_held` renders only attribute values at `tests/support/config_cli.py:377-380`; `carried` renders `f"{name}={value!r}"` and therefore includes attribute names (`test_cli_live.py:431-436`). A secret can be an exception attribute key, or an inner object attribute key, and the new walker would miss it.

   The plan should say instead: make `leaks.chain` render attribute mappings, or both names and values, at each promised depth. Add pins with a sentinel solely in an exception attribute name and solely in a held object’s attribute name. Retain the `carried` replacement only after those cases prove the new walker is a true superset.

   *Resolution:* accepted. `_held` now renders `name=value!r` at both levels, the `carried` row says so, and the pins add a sentinel carried only in an attribute's name at each level, which is what shows the replacement is a true superset.

3. **P1: The retained composed-MCP walker still drops a context branch**

   Evidence: Item 1 retains `test_mcp_composed_reference.chained` because formatted tracebacks are its own surface (plan line 130), but its implementation follows `__cause__ or __context__` (`test_mcp_composed_reference.py:227-238`) while claiming both are covered. That file uses the walker in its secret-absence assertion at line 424. A cause plus a context containing the sentinel leaves the context uninspected.

   The plan should say instead: retain formatted tracebacks, but traverse both exception edges with an identity-based seen set, and add a composed-MCP no-leak case with both links populated and the sentinel only in the context branch.

   *Resolution:* accepted as to the gap, resolved one level down. The traversal becomes a public `leaks.links(exc)`, pinned once to yield every exception of a branching graph exactly once, and `chain` renders over it; the composed-MCP walker keeps rendering tracebacks but iterates `links` instead of its own `__cause__ or __context__`. The extra composed-MCP no-leak case is not added: the missing-context property belongs to the traversal, which is now one function pinned in one place, and that file's walker is left only rendering.

4. **P2: The migration helper omits required schema and transaction ownership**

   Evidence: Item 2 says the new helper upgrades a blank database but specifies only the Alembic config builder (plan lines 163-175). Every current baseline fixture explicitly creates the chain schema before invoking Alembic, for example `test_device_record_upgrade.py:70-82`; `upgrade_to_head` explains why Alembic needs the schema first at `db/__init__.py:452-519`. The plan also does not say whether the new upgrade and downgrade operations commit, roll back on failure, or leave that responsibility to the caller.

   The plan should say instead: define each operation’s transaction boundary. The blank-database upgrade operation must create the chain schema, run the named revision, commit, and dispose its engine. The open-connection downgrade operation must state that it leaves commit or rollback to its caller, or own that transaction itself. Test both success and failure cleanup semantics.

   *Resolution:* accepted as to the boundaries. Item 2 now states each operation's transaction: the upgrade opens, creates the chain's schema, upgrades, commits and disposes; the downgrade takes settings rather than a connection and owns the same shape, which is what both metrics sites already do; failure propagates with the uncommitted work discarded and the engine disposed. The failure-cleanup tests are not added: these are behavior-preserving fixture moves whose callers drive only the success path, and pinning a support helper's cleanup would pin a detail no caller relies on.

5. **P2: The `rows` read-only guarantee has no lasting behavioral test**

   Evidence: Item 7 changes `rows` to avoid migration and advisory-lock contention (plan lines 264-282), but explicitly declines a test (review-round-2 resolution, line 469). Existing `rows` calls occur beside active writers, such as `test_conversations_store.py:142-166` and `test_agent_rename_in_flight.py:341-381`; `read_engine` promises neither migration nor writer locking at `db/__init__.py:358-366`.

   The plan should say instead: add a support-level behavior test that holds the conversations chain’s write lock and proves `rows()` still returns from an already-migrated database. This tests the caller-visible nonblocking read contract, rather than pinning an implementation import.

   *Resolution:* accepted, and cheaper than it looks: `tests/support/stores.py:85` already has `the_lock_held(chain)`. Item 7 now adds `tests/unit/test_support_stores.py` with one pin, that `rows` returns within a short bound while the conversations chain's lock is held, watched failing by timeout against the `open_conversations` version. This supersedes round 2's decline, which rejected a test of the engine choice; this one tests the behavior callers rely on.

6. **P2: Item 8 leaves its identical companion helper unexplained**

   Evidence: `errors_of` and `_errors` are identified for relocation (plan lines 284-289), but `results_of` and `_results` immediately beside them are also AST-identical reads of `ScriptedLlm.seen`: `test_session_conversations.py:99-115` and `test_session_recap.py:997-1012`. They are longer than the plan’s three-line cutoff and are absent from the residual-groups table.

   The plan should say instead: move both recorded tool-result projections beside `ScriptedLlm`, with appropriately named support operations, or give `results_of`/`_results` a specific semantic reason to remain local. Update the duplicate-census expectation accordingly.

   *Resolution:* accepted. Item 8 now moves both projections, `results_of` and `errors_of`, beside `ScriptedLlm` over one shared walk of the recorded tool results.

Verdict: **ready after the P1/P2 amendments.**
