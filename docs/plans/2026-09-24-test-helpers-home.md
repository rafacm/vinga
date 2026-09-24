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
the files it touches. The implementer confirms each body is identical
to its destination's before replacing it (an AST comparison, recorded
in the implementation doc), and a copy found to differ is reported
rather than silently unified.

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

   The other seven exception walkers in the suite are not
   AST-identical to either version (`_whole_chain` in
   `test_providers_boundary.py` and `test_reach_upgrade.py`, `carried`
   in `test_cli_live.py`, `chained` in `test_turntaking.py` and
   `test_mcp_composed_reference.py`, `rendered` nested in
   `test_server_event_pins.py`, and `chain` in
   `test_session_reply_failures.py`, which returns the exceptions
   rather than a rendering). Each gets a one-line disposition in the
   implementation doc: moved to `leaks.chain` only if it is a
   secret-absence walker strictly weaker than it, kept with its reason
   otherwise.

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

   The module offers the driver (a blank database, a chain and a
   revision in; the settings out) and the stamped-version read (by
   engine and schema, with a settings-and-chain form over it). The
   fixtures stay in their files as one-line calls, per the scope the
   issue comment settled. What callers stop knowing: the three things
   the packaged Alembic environment refuses to run without.

   Before writing it, the implementer checks whether `vinga_server.db`
   already exposes a revision-parameterized upgrade; if it does, the
   tests use that instead and the support module shrinks to the
   version read, because the interface is the test surface. The
   differing `_version`s in `test_db_open.py` and
   `test_conversations_boot.py` (one returns a single string) and the
   per-file `_rows` readers stay.

3. **`speech_pcm` uses the home it already has.**
   `tests/support/wire.py:94` defines it; `tests/integration/conftest.py`,
   `test_device_simulator.py` and `test_telemetry_export.py` import it
   instead of defining it. `tests/smoke/test_smoke.py` keeps its copy:
   the smoke lane is a black box against a running container and
   imports nothing but its own conftest, and `wire.py` imports
   `vinga_server`; that sentence goes beside the copy.

4. **The stdio MCP entries use the home they already have.**
   `tests/support/tools_mcp.py` defines `stdio_entry` and `entry_data`;
   the identical copies (`stdio_entry` in `test_agent_guidance.py`,
   `test_mcp_reload.py`, `test_tools_mcp_prompts.py`,
   `test_tools_mcp_reload.py`; `stdio_server` in `test_tools.py`;
   `entry_data` in `test_config_api_runtime.py` and
   `test_tools_mcp_reload.py`) import from it, confirmed identical
   first. Note the two return shapes, a `dict` and an
   `McpServerConfig`: a copy goes only to the support function with
   the same body and return.

5. **The OpenAI SDK client for provider tests.** `mock_client`, 13
   lines, identical in `test_providers_openai_asr.py` and
   `test_providers_openai_tts.py`, goes to `tests/support/llm_sdk.py`,
   the home #144 made for SDK shapes. Its `max_retries=0` and the
   comment explaining it are the reason the two must agree: without
   it the SDK triples a deliberately failing request and hides how
   many the provider sends. This one is an addition to the comment's
   list, made because it meets the issue's own test for moving (a
   reader of one copy would want the other to change with it).

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
- **Everything else in the census**: groups of three lines or fewer,
  and two-file pairs with no reason to agree (test data such as
  `manifest`, `a_turn`, `envelope_of`).

## Verification

- **Pin before reshaping.** Collected test counts per lane
  (`--collect-only -q`, the summary line, untruncated) recorded before
  the first move and unchanged after; unit and integration lanes green
  with `-n auto --dist loadfile`; `ruff check .` clean.
- **Falsify the walker's reach.** One mutation per family, run both
  ways and recorded: in one provider error path and one config error
  path, attach the planted secret to the raised exception as an
  attribute. With `leaks.chain`, that file's secret-absence test goes
  red; with the old walker restored locally, it stays green. That is
  the claim this plan makes (the moved walker sees what the copies
  could not), so it is shown failing rather than asserted.
- **Falsify the driver move.** Break the support driver (target head
  instead of the revision) and watch all five upgrade files go red,
  which proves each one now goes through it.
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

- [ ] **M1: the helpers go home** (#531 M2). Items 1 to 5 above, one
  commit per item, the verification above, the changelog fragment.
  Design footprint: deepens `tests/support/leaks.py` (the exception
  walk joins the record walk), adds `tests/support/migrations.py`
  (callers stop knowing the Alembic environment's three
  requirements), and adds one function to `tests/support/llm_sdk.py`.
  Documentation footprint: `leaks.py`'s docstring only. Closes #531.
