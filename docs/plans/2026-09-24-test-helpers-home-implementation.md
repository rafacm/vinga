# The duplicated test helpers go home: implementation

Companion to
[`2026-09-24-test-helpers-home.md`](2026-09-24-test-helpers-home.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the helpers go home

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.281; 2026-09-24.

### What landed

| Item | Where | Commit |
| --- | --- | --- |
| 1, the walk moves and is completed | `vinga-server/tests/support/leaks.py` (`links`, `chain`, `_held`, the docstring paragraph), the pins in `vinga-server/tests/unit/test_support_leaks.py`, 23 importers moved off `tests/support/config_cli.py` | `Move the secret walker to leaks and complete it` |
| 1, the fifteen weak copies | the fifteen files the plan names | `Import the strong walker in the fifteen weak copies` |
| 1, the table's seven walkers | `test_providers_boundary.py`, `test_reach_upgrade.py`, `test_cli_live.py`, `test_turntaking.py` (replaced); `test_mcp_composed_reference.py` (iterates `links`); `test_server_event_pins.py` (delegates to `chain`); `test_session_reply_failures.py` (kept) | `Route the seven other exception walkers per the table` |
| 2, the migration driver | new `vinga-server/tests/support/migrations.py`: `upgrade_to`, `downgrade_to`, `version`, `version_of` over one private `_alembic` | `Drive Alembic to a revision through one support module` |
| 3, `speech_pcm` | four copies deleted, smoke included | `Import speech_pcm from wire instead of defining it` |
| 4, the stdio MCP entries | seven copies mapped by return shape; the support `stdio_entry` defined over `entry_data` | `Use the support stdio entries in place of seven copies` |
| 5, the SDK client | new `vinga-server/tests/support/openai_sdk.py` | `Give the speech providers' SDK client one home` |
| 6, `out` | beside `runner` in `tests/support/config_cli.py` | `Move the CLI capture reading beside its runner` |
| 7, the ordered row read | **dropped under the plan's own stop rule.** `rows` keeps its engine; its docstring now says what it waits for and names the two tests relying on it. No `test_support_stores.py`. See below | `Say what stores.rows waits for, and who relies on it` |
| 1's class, three inline walks found here | `test_config.py`, two tests in `test_memory_store.py` | `Route three inline secret walks through leaks.chain` |
| 8, the scripted model's reads | `results_of`, `errors_of` over one `_tool_results` in `tests/support/providers.py` | `Read the scripted model's tool results beside it` |
| The changelog fragment | `changelog.d/531-test-helpers-home.md`, `### Changed` | the closing commit |

### Item 7 dropped, and why: a caller relies on the writer's lock

The plan orders item 7 as three commits, `rows` moving to
`read_engine` first, and says: "A caller that turns out to depend on
`rows` migrating a fresh database stops the item and is reported, since
that caller was reading through a writer's path by accident." The
first commit met a caller of exactly that kind, with the lock rather
than the migration as the mechanism. The item stopped there, and the
orchestrator then dropped it rather than patching the callers; none of
the `read_engine` change or its pin is committed.

**What was done before stopping.** The pin was written first and
watched failing against the unchanged `rows` (`open_conversations`):
`AssertionError: rows queued behind the writer holding the lock`, one
failure in 3.03 s, as the plan predicts. With `rows` on `read_engine`
it passed. The nine caller files were then rerun.

**What broke.** Two tests in `tests/unit/test_agent_rename_in_flight.py`,
`test_a_rename_between_the_world_and_the_open_reaches_the_session` and
`test_a_session_opened_before_the_apply_still_writes_the_new_name`,
failed intermittently with `ValueError: not enough values to unpack
(expected 1, got 0)` at `(thread,) = rows("conversations")`. Measured:
on `read_engine`, the file failed in 4 of 4 serial runs (one or two
failures each) and the nine files together in 2 of 4 parallel runs;
on the unchanged `rows`, the file passed 9 of 9 serial runs.

**The mechanism, confirmed rather than assumed.** Both tests read the
record immediately after `a_finished_session`, whose docstring says
"its rows are all committed before they are read", while the
`served_store` writer thread is still running and may not have
committed the session's last batch. The old `rows` took the
conversations chain's advisory lock inside `open_conversations`, so it
queued behind the writer's in-flight transaction, and that queueing is
what made the docstring's claim true. The experiment that confirms it:
with `rows` on `read_engine` and `served_store.stop()` (which drains
the writer's queue) called before the reads, the file passed 5 of 5.
The experiment was not committed.

**The decision.** The wait on the chain's lock is load-bearing, so
the three `read_engine` copies (`stored` in `test_conversations_erasure.py`
and `test_conversations_namespace.py`, `rows_of` in
`test_conversations_retention.py`) are a different reader rather than
a duplicate of `rows`. Merging them would have meant adding drains to
the two rename tests, which trades about twenty lines of consolidation
for flake risk in CI, so no drain was added and item 7 is dropped.
What remains of it is one commit that changes no code: `rows`'
docstring, which called it "what a reader beside a running writer is",
now says it opens through `open_conversations`, waits for a writer
holding the conversations chain's lock to commit, and that the two
tests above rely on that. `test_support_stores.py` is not added. The
plan's "What stays" table gives `stored`/`rows_of` a row, and the
duplicate census keeps that group.

### Deviations from the plan

- **Item 7 was dropped** (above); its one commit corrects `rows`'
  docstring and changes no code.
- **Three inline walks outside the plan's table were routed through
  `leaks.chain`** (see Discoveries), on the orchestrator's decision
  that they are item 1's class.
- **The cause-alone and context-alone pins do not fail against either
  old walk.** The plan says every pin but the cycle case is watched
  failing against the old walk. Both old walks (the fifteen copies' and
  `config_cli.chain`) followed `__cause__ or __context__`, so a
  sentinel in a lone cause or a lone context is found by both; the
  pins exist to hold the traversal, not to show the old one weak. Each
  was watched failing against a walk that drops its link instead
  (`links` following only `__cause__` fails the context pin, the
  both-links pin and the `links` pin; following only `__context__`
  fails the cause pin and the `links` pin).
- **Four integration files imported `speech_pcm` from the integration
  conftest** (`test_mcp_reload.py`, `test_conversations.py`,
  `test_agent_guidance.py`, `test_drain.py`). The plan names the
  conftest as a copy to delete but not these importers. They now import
  from `tests/support/wire.py` directly, so the conftest does not
  become a forwarder of a name it no longer defines.
- **Two locals renamed to keep an imported name visible.**
  `test_config_store.py` bound a local `chain` in one test, which the
  imported walk would have met as an unbound local, so it is `carried`;
  `test_conversations_schema.py` and `test_memory_schema.py` bound a
  local `version`, now `stamped`.
- **`out` gained a docstring** in its new home, so the support
  definition is AST-identical to the five copies in its body, not in
  its whole definition.
- **The two `mock_client` comments were merged.** The copies were
  AST-identical, but their comments on `max_retries=0` each gave half
  the reason (the backoff, the count); the one comment now gives both.

### The walk, and its pins watched failing

Ten pins in `test_support_leaks.py`. Run against the fifteen copies'
walk (repr and str, one link): **7 failed, 3 passed**, the three being
the cause-alone, context-alone and cycle pins. Run against
`config_cli.chain` as it stood at `1bcf3dc4`: **5 failed, 5 passed**,
the failures being both attribute-name pins, the revealing-`str`
argument, the context-beside-a-cause pin and the `links` pin. Against
the new walk, 10 passed.

Each reading was then removed from the new walk one at a time:

| Mutation of `leaks.py` | What went red |
| --- | --- |
| `links` follows only `__cause__` | context-alone, context-beside-a-cause, `links` |
| `links` follows only `__context__` | cause-alone, `links` |
| no `str()` of each argument | the revealing-`str` argument |
| `_held` renders values only at the first level | the attribute-name pin, first level |
| `_held` renders values only at the second level | the attribute-name pin, second level |
| `_held` reads one level | the PyYAML-mark pin and the second-level name pin |
| the seen check removed | the cycle and `links` pins, by never returning (a 30 s `timeout` ended the run, exit 124) |

**A survivor, and what it taught.** The first version of the `links`
pin survived the seen-check mutation. The driver never reached the
condition: that version filtered already-seen exceptions at push time
as well, and its graph gave no exception two pending entries. The pin
now builds the commonest real shape, `raise ... from error` inside
`except error`, which makes one exception both the cause and the
context of another, and the push-time filter was removed as redundant
(its own mutation survived, rightly, since the pop-time check is the
authoritative one). After both changes the seen-check mutation fails
the pin.

### The walker's reach, both ways

The plan's supplementary evidence that the callers reach the walk, one
mutation per family, each reverted:

| Planted | With `leaks.chain` | With the old weak walk restored in the test file |
| --- | --- | --- |
| Provider path: `failure.planted = str(exc)` on the `ProviderCallError` in `providers/openai_asr.py` | `test_an_api_error_raises_the_taxonomy_with_the_status_and_no_body` red | green |
| Config path: `refusal.planted = name` on the fragment-name `ConfigError` in `config/store.py` | all eight cases of `test_an_unusable_fragment_name_is_refused_without_being_quoted` red | green |

The same nine cases are green with both walks on the unmutated
production code, which is the control.

### The migration driver, identities and mutations

Checked by AST before replacing, with the chain constants, the
revision name and the database parameter normalized:

- the four `at_the_baseline` bodies (device record, domain, memory,
  reach) are identical up to the chain;
- `test_metrics_views_upgrade._stamped` with its `_alembic` inlined is
  identical to them, and so is `migrations.upgrade_to` with its own
  `_alembic` inlined;
- the five integration `_version(settings)`s are identical up to the
  chain, and the two unit `_version(engine, schema_name)`s are
  identical to `migrations.version`.

Both metrics downgrade sites were `write_engine`, `connect`,
`command.downgrade`, `commit`, `dispose` in a `finally`, which is
`downgrade_to`'s body. After the move, a grep for `command.upgrade`,
`command.downgrade`, `command.stamp` and `AlembicConfig` under `tests/`
finds only `tests/support/migrations.py` and one wrapper in
`test_db_open.py` that monkeypatches the production module's own
`command.upgrade`, which is not an invocation.

| Mutation of `migrations.py` | Result |
| --- | --- |
| `upgrade_to` targets `"head"` | all five upgrade files red: 16 failed, 7 errors (the device-record file's fixtures), 12 passed |
| `downgrade_to` does nothing | both metrics downgrade cases red, 33 passed |

### The stdio entries, by return shape

AST, per the plan's table: `test_agent_guidance.stdio_entry` and
`test_tools.stdio_server` identical to `entry_data` but for the name;
`test_config_api_runtime.entry_data`, `test_tools_mcp_reload.entry_data`
and `test_tools_mcp_prompts.stdio_entry` identical; the two the table
calls not identical (`test_mcp_reload.stdio_entry`,
`test_tools_mcp_reload.stdio_entry`) differ. Equality, by calling each
copy and its destination: every helper accepting overrides equal with
none, with `args=["--other"]` and with `env={"A": "B"}`;
`test_mcp_reload.stdio_entry()` equal to `entry_data()` for its one
call. Every file's `STDIO_SERVER` resolved to the path
`tests/support/configs.STDIO_SERVER` names, and with its copy gone
none of them had a reader left, so each went. The support
`stdio_entry`, redefined over `entry_data`, was checked equal to the
old literal spelling for the same three calls.

### The other identities

- `speech_pcm`: all four copies AST-identical to `wire.speech_pcm`,
  whole definition. Every local `SAMPLE_RATE` kept, each having other
  readers.
- `mock_client`: both copies AST-identical to `openai_sdk.mock_client`.
  With `max_retries=2` the ASR suite's
  `test_a_retry_cut_off_by_the_deadline_discards_rather_than_fails`
  goes red, which is the reason the module states.
- `out`: all five copies AST-identical to each other and, docstring
  aside, to the support one.
- `results_of`/`_results` AST-identical docstring aside,
  `errors_of`/`_errors` AST-identical. The support pair over
  `_tool_results` was checked equal to the old comprehensions over a
  recorded history of three rounds, results in two of them.

### Inventories, before and after

All by AST over the tracked files, untruncated.

- **The duplicate census** (module-level non-test functions outside
  `tests/support`, identical arguments and body, docstring included,
  in more than one file): **71 groups, 213 definitions, 105 files**
  before, reproducing the plan's numbers, and **61 groups, 180
  definitions, 90 files** after. The ten groups gone are exactly the
  moved ones: `speech_pcm`, the stdio `entry_data` group, the
  integration `_version`, the three weak-walker groups (`chain` in
  five files, `_chain` in two, `_chain` in four), `out`, the unit
  `_version`, `mock_client` and `errors_of`/`_errors`, 33 definitions
  between them. Every other group is unchanged but for line numbers.
  `stored`/`rows_of` stays, since item 7 was dropped. The three inline
  walks routed afterwards were never module-level functions, so the
  final count is still **61 groups, 180 definitions, 90 files**.
- **The weak-walker inventory** (functions whose body, docstring
  aside, is the repr-and-str walk): **15 before, 0 after**.
- **The `ImportFrom` walk** for `chain` or `_held` from
  `tests.support.config_cli`: **23 before, 0 after**. The same walk
  over `tests.support.leaks` finds 46: the 23, the fifteen, the four
  replaced walkers, `test_server_event_pins.py`, the pin file,
  `test_config.py` and `test_memory_store.py`.
- **One-link traversals** (any function holding a
  `__cause__ or __context__` expression): **26 before** at `1bcf3dc4`,
  **1 after**: the table's kept `test_session_reply_failures.chain`. It
  was 4 until the three inline walks discovered below were routed.

### Discoveries

- **Three inline one-link walks the plan's inventory did not see.**
  `test_config.py:1086`, `test_memory_store.py:1416` and
  `test_memory_store.py:2246` each walk `__cause__ or __context__`
  inside a test body and assert a value absent from `str` of each link.
  They are not walker functions, so the plan's table does not list
  them. All three are secret-absence walks, the same weaker walk item 1
  retired elsewhere (no attributes, no arguments, no context beside a
  cause, and no seen set, so a cycle would never end), and on the
  orchestrator's decision each now asserts against `leaks.chain`
  instead, in one commit. No mutation was run for them: the walk they
  now use is the one `test_support_leaks.py` pins. The three tests
  still pass.
- **`test_session_reply_failures.chain` keeps the one-link traversal.**
  The table keeps it because it returns objects, and that is right; it
  could iterate `links` without changing what it returns, which the
  table did not ask for.
- **The census had to be reproduced before it could be rerun.** The
  plan's 71/213/105 is a key of the arguments and the body with the
  docstring; including the return annotation gives 70/209/103, and the
  body alone 72/221/108. The key that reproduces the plan's numbers was
  used for both counts above.

### Documentation footprint

`leaks.py`'s module docstring gained the paragraph item 1 asks for,
and `stores.rows`' docstring was corrected when item 7 was dropped.
The grep the plan names, `grep -rnE "config_cli import chain|_chain|speech_pcm|stdio_entry|mock_client" docs README.md`,
read in full before this document was written: **51 hits**, none in
`README.md` and none on a live page. 28 are in this milestone's own
plan; the other 23 are dated execution
records in `docs/plans/` (the 2026-08-03, 08-16, 08-17, 08-23, 08-26,
08-30, 09-05, 09-13, 09-22 and 09-23 plans and implementation docs),
which report what was true when written and were not touched. Most of
the `_chain` hits there are other words (`take_the_chain_lock`,
`_squashed_chain_`, `no_chain_behind_it`). No hand-maintained page
describes where these helpers live, as the plan said. The total is a
reading of one moment rather than a state: this document quotes the
names it records, so writing it added its own hits (19 when the section
was last edited), and none of those is a page describing where a helper
lives.

### Verification

All from `vinga-server/`. The two full lanes ran on the tree of
`Read the scripted model's tool results beside it`, before the two
follow-up commits (the `rows` docstring and the three inline walks);
what those two touched was then rerun on its own, as the last item
says. Everything else ran on the tree this section is committed with.

- **Pin before reshaping.** Collected counts before the first move and
  after the last, each lane's summary line: unit 7,620 then 7,630;
  integration 347 then 347; census 66 then 66; smoke 7 then 7. The
  unit lane differs by exactly the ten pins in
  `test_support_leaks.py`, and by nothing else.
- `uv run ruff check .`: all checks passed.
- `uv run pytest tests/unit -q -n auto --dist loadfile -ra`:
  `7611 passed, 19 skipped in 879.71s (0:14:39)`, parallel. All
  nineteen skips are the `faster-whisper` and `piper` extras not being
  installed.
- `uv run pytest tests/integration -q -n auto --dist loadfile -ra`:
  `347 passed in 214.41s (0:03:34)`, parallel.
- `uv run pytest tests/census -q -ra`: `66 passed in 26.87s`, serial.
  Neither manifest moved, so neither was regenerated: the new support
  modules reach no underscore name across a module (`_alembic`,
  `_held` and `_tool_results` are each read only inside their own
  module), and no documented command spelling changed.
- `uv run pytest tests/smoke --collect-only -q`: `7 tests collected`.
  The smoke conversation itself, and so the smoke lane's import of
  `speech_pcm` from `tests/support/wire.py` at run time, runs only in
  CI's `image` job.
- `python3 ../scripts/check_doc_links.py ..`: `checked 274 files, 0 failures`.
- After the follow-up commits, the files they touched and the walk's
  pins, `uv run pytest tests/unit/test_config.py tests/unit/test_memory_store.py tests/unit/test_agent_rename_in_flight.py tests/unit/test_support_leaks.py -q -n auto --dist loadfile -ra`:
  `274 passed in 17.41s`, parallel. The unit lane still collects 7,630.
- `python3 scripts/fold_changelog.py check .` from the checkout root:
  `checked 1 fragments, 0 failures`.
