# vinga, the built-in default agent: implementation

Companion to [`2026-10-06-vinga-built-in-agent.md`](2026-10-06-vinga-built-in-agent.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries. M2 landed before M1, so
its section comes first.

## M2: the Use door, packaged

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.291; 2026-10-07.

### What landed

- `vinga_server/knowledge/`, standard library only, held there by a
  test that imports it in a fresh interpreter. Its interface, from
  `knowledge/__init__.py`: `pages()` (every packaged page's text, keyed
  by its path inside the copy, read-only), `Section` and `sections()`
  (every page cut at its `##` headings, the lead titled with the page's
  `# ` title and each section `<page title>: <heading>`), `section(page,
  heading)` (one section, refusing a missing heading by name),
  `board_guides()` and `NOT_BOARD_GUIDES` (the device pages minus the
  two named exclusions, `README.md` and `flashing.md`),
  `board_facts(board)` and `VAGUE_BOARD_FACTS` (D3), and `persona()`
  (the concept summary, D2). Three submodules behind it: `library`
  (the cached reader and the cut), `boards` (the guide set, the
  matcher, the facts), `persona` (the summary today, D1's file in M3).
- `knowledge/pages/`, the committed copy, eight files, 118,470 bytes.
- `tests/census/test_packaged_pages.py`, with the page set in
  `tests/support/packaged_pages.py`: run as a module it writes the
  copy, removing any file no page backs; collected, its
  `test_the_packaged_pages_are_the_tree` checks the same file set and
  the same bytes. The census lane's `conftest.py` docstring names it
  as the lane's third check.
- The D10 pin, `test_vinga_s_knowledge_is_held_to_the_live_grammar`,
  in `tests/census/test_command_spellings.py`.
- The wheel-level assertion,
  `test_the_installed_wheel_carries_the_built_in_agent_s_pages`, in
  `tests/integration/test_cli_wheel.py`: the installed environment's
  own `knowledge.pages()`, run outside the checkout, equals the pages
  under `docs/`.
- AGENTS.md (the CI paragraph and the rebase section) and the
  `implement-issue` skill's census paragraphs name the copy and its
  regenerate command.

No runtime caller, no behavior change, no changelog fragment (D9).

### Deviations

- **One test beyond the plan's list:** the import-weight property Q8
  states ("importing nothing beyond the standard library") is asserted
  rather than described, in `tests/unit/test_knowledge.py`.
- **`sections_of(page, text)` is public in `knowledge.library`**,
  though not re-exported from the package. The fence rule (a `##` line
  inside a fenced block is code) has no instance in today's pages, so
  it cannot be falsified over the real copy; the test drives the cut
  over a page written for it through this function rather than through
  an underscore reach-in.
- **The page set lives in `tests/support/packaged_pages.py`**, not in
  the census module the plan names. The census module still writes the
  copy (`python -m tests.census.test_packaged_pages`) and holds
  `test_the_packaged_pages_are_the_tree`, but the set of pages, the
  copy's path and the regenerate command are read by three suites
  (the census, the D10 pin, the unit and wheel cases), and
  `test_no_test_module_imports_another_test_module` forbids one test
  module importing another. The first full unit lane caught the
  original layout; the move is its own commit.
- **The browser's type is read from the page it ships.** The plan
  names `vinga-browser` as the one spelling that is not a stem. It is
  an alias in `knowledge/boards.py`, and a test reads `BOARD_TYPE` out
  of the packaged `browser/static/ota.js` and asserts that string
  reaches the browser guide, so the JavaScript constant and the alias
  are held together rather than written twice and trusted.

### Resolutions

- **The census reads the filesystem, not `git ls-files`**, on both
  sides, unlike its two neighbours. What the wheel and the image carry
  is what is on disk under the package, tracked or not, and the
  regenerator writes from what is on disk; a tracked-only check could
  pass while the build shipped something else. The module docstring
  says so.
- **What a section's text is:** verbatim, heading line included, and
  the cut is lossless (a page's sections joined are the page, asserted
  over every packaged page). `board_facts` is the lead and the
  `## Controls` section, each right-stripped, joined by one blank line:
  1,808 to 3,162 characters across the four board guides, within the
  3,500 budget. The plan's figures (1,807 to 3,161) differ by the one
  character of how the two halves are joined.
- **`persona()` is the summary section verbatim, heading included**,
  right-stripped: 1,530 characters (the plan's 1,529, same cause).
- **The vague text** names the common page twice over, by its title
  ("Device guides", which is how its sections are titled for a future
  lookup) and its path, says to say plainly when that page does not
  cover the question, and says a restart lets the server learn the
  board.
- **Matcher precedence:** whole stems first, then the vendor-stripped
  spellings with `setdefault`, so a guide whose own stem is the shorter
  spelling keeps it; then the `vinga-browser` alias.

### Discoveries

- **The glossary has no `##` headings.** Its entries are `###`, so the
  plan's cut (by `##`) makes the whole glossary one 28 KB section,
  where the gate's harness cut at levels one to four. Not a problem for
  M2, which has no caller, but M5's retrieval work should decide the
  cut before it measures: either the glossary cuts at `###`, or the
  lookup bounds a section, as the gate's harness did at 1,500
  characters.
- **Three packaged pages carry an "On this page" section**
  (`concepts.md`, `devices/README.md`, `devices/flashing.md`): a list
  of links, which the gate's harness skipped. The cut keeps it,
  since it is part of the page; M5's scoring is the place to drop it.
- **The copies blind the spellings manifest to the exemption D10
  guards.** With `docs/devices/` added to `_HISTORICAL_PATHS`, only the
  D10 pin failed: the manifest did not move, because every pair those
  pages quote stays `respell` through the copies and was already
  `historical` through the plans. So the pin is the only guard, which
  is what the plan argued it would be.
- **The plan's claim that the copies do not move the spellings
  manifest holds:** `test_the_manifest_is_the_census` passed with the
  copy committed and no regeneration.
- **The copies' relative links do not resolve inside the package**
  (`concepts.md` links `reference/conversations-schema.md`, the device
  guides link `../concepts.md` and `../run/...`), and
  `scripts/check_doc_links.py` scans only the root READMEs, AGENTS.md
  and `docs/`, so it neither checks nor flags them; it reported 0
  failures over 335 files. Harmless while the copy is read by a model
  rather than navigated, and the reason a lookup answer (M5) should
  not present a link as something to follow.
- **A comment the census read as a command.** The first draft of a
  test comment said "every vinga prompt on that board", which the
  census reads as the invocation `vinga prompt`, a command the tree
  does not have. Reworded in its own commit.
- **A wheel without the pages fails at first read**, with
  `FileNotFoundError` from the reader, rather than with a sentence of
  its own. Nothing reads it in M2; M3 is where a missing copy would
  first reach a session, and whether it wants a fixed sentence (as
  `simulator.utterance.NO_UTTERANCE` has) is M3's call.

### Mutations

Run once each, logged in this worktree's `.logs/m2-mutations.log`:

| Mutation | Killed by |
| --- | --- |
| One byte of a packaged copy changed | `test_the_packaged_pages_are_the_tree` |
| A guide added to `docs/devices/` without its copy | `test_the_packaged_pages_are_the_tree` |
| `docs/devices/` added to `_HISTORICAL_PATHS` | `test_vinga_s_knowledge_is_held_to_the_live_grammar`, alone |
| The matcher accepting `flashing` (`flashing.md` dropped from `NOT_BOARD_GUIDES`) | `test_the_board_guides_are_the_device_pages_but_the_two_about_no_one_device`, `test_every_board_guide_has_a_lead_and_controls_within_the_budget`, `test_a_type_with_no_board_guide_gets_the_vague_text[flashing]` |
| `board_facts` interpolating the reported string into the vague text | all four `test_the_reported_type_never_enters_the_facts` cases and fifteen `test_a_type_with_no_board_guide_gets_the_vague_text` cases |
| Mapping only one LCD spelling (M4's target, run here since the matcher is here) | the three `test_a_waveshare_board_is_reached_with_or_without_the_vendor` cases and `test_a_reported_type_is_casefolded_and_stripped` |
| The summary's heading renamed in the copy | `test_the_summary_s_heading_is_in_the_packaged_concepts_page`, `test_the_persona_is_the_concept_summary_verbatim` |
| The fence rule disabled in the cut | `test_the_cut_is_at_level_two_headings_outside_fences` |
| The package importing a third-party module (`yaml`) | `test_importing_the_package_loads_only_the_standard_library` |
| A wheel built without the pages (hatch `exclude`) | `test_the_installed_wheel_carries_the_built_in_agent_s_pages` |

No survivor.

### Verification

All on the Raspberry Pi 5, logs in this worktree's `.logs/`. Both lanes
ran with `-n auto --dist loadfile` (four cores, so four workers; `-q`
does not print the count), starting at 49.6 and 51.3 degrees, so never
the `-n 2` fallback.

- `uv run ruff check .`: all checks passed.
- Unit lane, first run: `1 failed, 8411 passed, 19 skipped in
  1058.40s`, the one failure being
  `test_no_test_module_imports_another_test_module` (fixed by moving
  the page set to `tests/support`). Second run, after the move:
  `8412 passed, 19 skipped in 970.08s (0:16:10)`.
- Integration lane: `358 passed in 244.45s (0:04:04)`, the wheel lane
  and its new case included.
- The CI drift checks (domain, server, conversations, metrics views,
  events, OpenAPI, CLI reference, CLI recipes), scripted from the
  workflow's steps: all current.
- `scripts/check_doc_links.py .`: `checked 335 files, 0 failures`.
- `uv build --wheel`: the archive carries `vinga_server/knowledge/`
  with its four modules and all eight pages, each byte-identical to
  the tree; a wheel built from a copy of exactly what the image's
  build context sends (`pyproject.toml`, `uv.lock`, `README.md`,
  `src/`, `examples/`) carries the same eight pages.
- `tests/census`, run last: `69 passed in 29.24s`; neither manifest
  needed regenerating.

Not verified: the image itself was not built (the wheel built from the
image's context stands in for it), and the browser lane was not run,
since nothing it drives changed.

### PR review round

Reviewed 2026-10-07 by openai/gpt-6-sol, thinking high via codex CLI 0.160.1, read-only sandbox, at commit 2a13f297 ([the round](https://github.com/rafacm/vinga/pull/631#issuecomment-6031810978)). The fix is by anthropic/claude-opus-5-5, thinking high, M2's own implementer.

1. **P1: a missing section's error quoted its input.** `section(page,
   heading)` put both caller-supplied values into its `LookupError`, so
   a credential-shaped value reached the exception text and any
   traceback. *Resolution:* the error is one fixed sentence,
   `NO_SUCH_SECTION`, quoting neither; the caller passed both values and
   already knows which section it asked for. It was the package's only
   raise (grep over `knowledge/`). A test plants a sentinel as the page,
   the heading and both, and asserts it absent from the message, the
   args and the cause and context chain; it failed on the old code
   three times (`dc8f758b`).

The round's CI run also went red on the census: the spellings manifest
missed two prose phrases this implementation doc quotes, because the
lane ran before the doc was tracked; regenerated in `8e5be536`.

Verification after the round: `uv run ruff check .` clean; the unit lane
(`-n auto --dist loadfile`) `8415 passed, 19 skipped in 1153.80s`;
`tests/census`, last, `69 passed`.

## M1: an unbound device only pairs

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.291; 2026-10-07.

### What landed

| Plan item | Where | Commit |
| --- | --- | --- |
| The helpers bind `DEVICE_MAC` (Tests) | `tests/support/configs.py` (`config_with_agent`, `base_config`) | `Bind the device under test in the shared configs` |
| The claim: `ALREADY_COVERED` goes, the agent is optional, D8 | `config/store.py` (`claim_device`, `_device_write`), `config/responses.py` (`PendingClaim`), `config/api.py` (`add_device`, `_claimed_agents`), `config/cli/grammar.py` (`_bound_by_code`), `config/cli/devices.py` (`ADD_DEVICE`), the OpenAPI document and the CLI reference | `Let a claim name no agent and drop ALREADY_COVERED` |
| The rule loses its fallback in both homes (Q3, Q4) | `config/models.py` (`Config.bound_to`, `agents_for_device`), `device/bindings.py` (`_bound`), `onboarding/pending.py` (`retire_all` goes), `config/api.py` (no pending housekeeping on a default agent), `onboarding/unbound.py` and `ota/reply.py` docstrings | `Resolve an unbound device to no agent` |
| The live read stops reading the default row; the pin moves alone | `config/store.py` (`LiveBinding`, `read_live_binding`, `_live_binding`, `read_live_attachment`), `tests/unit/test_live_binding_pin.py`, `tests/unit/test_live_device_read.py` | `Stop reading the default agent in the live binding` |
| The boot rule goes, and `check_completeness` with it | `config/models.py`, `config/entities.py` (the setting's notes), the domain-config reference | `Drop the boot rule that required a default agent` |
| The mint loses both D4a refusals | `browser/router.py`, `browser/__init__.py`, `browser/static/identity.js` | `Mint a browser identity on every deployment` |
| Notices, descriptions, help | `config/entities.py`, `config/api.py`, `config/models.py`, `config/responses.py`, `config/store.py`, `config/cli/{grammar,local,simulator,deployment}.py`, `config/docgen.py`, `config/api_descriptions/api.md`, `events/catalog.py`, the references | `Say what a default agent is now, everywhere it is said` |
| The smoke seeds bind the smoke MAC | `tests/smoke/seed*.sh`, `tests/integration/test_smoke_seeds.py` | `Bind the smoke board in the seeds, not a default` |
| The browser lane's pairing case | `tests/browser/test_browser_client.py` | `Pair the browser lane's browser with a default set` |
| The failing set, rebound or rewritten | below | `Rebind or rewrite the unit suites that leaned on it`, `Rebind or rewrite the integration suites too` |
| The ADR | `docs/adr/2026-10-07-an-unbound-device-only-pairs.md` | `Record that an unbound device only pairs` |
| The documentation footprint | as the plan lists it, below | `Document pairing-only onboarding and the new default`, `Regenerate the packaged Use pages` |
| The fragment | `changelog.d/612-pairing-only.md` | `Add the changelog fragment for pairing-only` |

Design footprint as planned: `device/bindings.py` answers names from one
rule whose snapshot half is `Config.bound_to`; `config/store.py`'s claim
and enrolment share one "a new device with no agents named starts on the
default" step; `browser/router.py`'s `try_identity` is two lines and
reads nothing. No new module.

### Deviations from the plan

1. **An eighth notice, `DEFAULT_AGENT_NOTICE`.** Q4 rewords
   `DEFAULT_AGENT_UNSERVED_NOTICE` (now `reload` alone) and stops there.
   Setting or clearing a default agent that is served was answered with
   `BINDING_NOTICE`, whose sentence promises the write reaches "the
   device" at its next check, which after M1 is exactly the wrong
   impression: no device changes. It gets a sentence of its own on the
   same `check-in` token (the devices it affects are the ones claimed
   from now on, and each meets its binding at its next check-in).
   `_binding_notice` gained a `live` parameter beside `unserved`.
   `tests/support/notices.py`, the notice count test and the CLI
   guide's "Eight sentences" follow.
2. **An empty `agents` list is "none named" on the claim.** Q4 says the
   claim's agents become optional. `PendingClaim.agents` defaults to the
   empty list and the store treats empty as none named, so `{}` and
   `{"agents": []}` both bind the default, and the CLI's zero-agent
   claim sends the binding body it always sent. Before M1 an empty list
   on the claim was refused with `_CLAIM_REFUSED`, whose sentence ("the
   request's agents name at least one agent this deployment does not
   have") was false for it. A claim that named no agent passes the
   store's refusal through as itself, since there were no names for the
   substitute sentence to protect; that is how `NOTHING_TO_ENROLL_ONTO`
   reaches the caller.
3. **`recording_config` is rebound too, and several per-file configs.**
   The plan names `config_with_agent` and `base_config`. The inventory
   showed `recording_config` was the same helper shape (25 of the 58
   unit failures), so it binds `DEVICE_MAC` the same way.
4. **The two no-agent log templates changed.** `OtaCheckNoAgent` and
   `RejectedNoAgent` ended "bind it under devices or set default_agent";
   the second remedy no longer works, so it went. Not in Q4's list; the
   events reference was regenerated.
5. **`PendingDevices.retire_all` went.** Its only callers were the
   default-agent write and an applied `default_agent`, both retiring
   every pending code because "a default agent covers every device".
   With that false, so was the housekeeping; the tests that pinned it now
   pin that a default agent leaves the listing alone.
6. **No ADR index entry.** `docs/adr/README.md` has no list of records,
   and `docs/README.md` points at the directory whole, so there is no
   index to add a line to. The record is cited from `docs/concepts.md`
   (Binding), `docs/run/security.md` and
   `docs/run/onboarding-a-device.md` instead.
7. **The presets describe the claim in prose.** Every command a preset
   quotes as an indented `vinga ...` line is a published recipe that
   `test_every_published_recipe_line_but_the_preset_apply_runs` runs
   against an empty server, where no code is pending, so the claim is
   named in the comment's prose and only `device bind` and
   `default-agent set` stay quoted.
8. **The boot refusals the suites used.** With the completeness rule
   gone, no write or pair of writes can leave a store a boot refuses on
   whole (every write checks references). The suites that need such a
   store (`check`, the boot re-read, the refused reload, the
   control-character and credential-display ones) plant a default agent
   naming no agent underneath the repository, through one helper,
   `tests/support/stores.dangling_default_agent`. Its reference sentence
   lists the defined agents as the completeness rule's list did, so the
   no-leak claims those suites make keep their subject.

### Resolutions

- **Q3, `Config.bound_to`:** landed as `bound_to(mac) -> tuple[str, ...]`,
  the record's agents or nothing; `agents_for_device` is
  `list(self.bound_to(mac))` until M6 adds `reachable_from`.
- **Q4, `check_completeness`:** it held one rule (grep over `src/`
  found no other caller than `Config._check_domain`), so the function
  went whole.
- **Q4, the live read:** one statement now, `LiveBinding` one field.
- **Q4, the page's branches:** `page.js` and `identity.js` have no branch
  of their own for either refusal (the page shows whatever sentence a
  refused request carries, which redemption still uses), so what went
  is `identity.js`'s two comments describing the refusal.
- **Q4, try links:** unchanged, as the plan says: `NO_DEFAULT_AGENT`,
  enrolment and `NOTHING_TO_ENROLL_ONTO` stay for M1b and M3.
- **Plan review round 2, finding 2:** the test the resolution asked for
  is `test_a_minted_browser_pairs_and_is_admitted_only_once_claimed`
  (`tests/unit/test_browser_routes.py`): with a default agent set, a
  minted identity checks in, is offered a code and no token, is still
  refused a token at its next check-in, and is admitted only once the
  code is claimed, bound to the default agent.
- **`vinga simulator check-in --claim`** still takes an agent: the
  plan does not make it optional, and nothing in M1 needed it.

### Discoveries

1. **Prose that still says "a MAC a default agent covers".** The
   `sessions.device_name` column comment in the conversations schema,
   with the matching descriptions in `conversations/store.py`, the
   event catalog's `device_name` note and `responses.py`'s session
   model, lists that among the reasons a name is null. It stays true of
   sessions recorded before M1, the four agree with each other, and
   changing the column comment needs a comment-only migration, so it is
   left as a follow-up rather than done here.
2. **The comparison still labels `default_agent` as `check-in`**
   (`config/diff.py`, `APPLIES`). Its footer was reworded to say the
   default agent is read by the next claim; the token stays, since
   nothing about a stored default agent waits for an apply.
3. **A baseline integration failure of my own making.** The baseline
   integration run before any code change had one failure,
   `test_every_published_recipe_line_but_the_preset_apply_runs`, caused
   by an edit to a preset's comment made while that run was in flight
   (it quoted `vinga device pending claim 418293 assistant`, which the
   recipe lane then ran). Deviation 7 is the fix; the unit baseline was
   green (`8372 passed, 19 skipped in 915.73s`).
4. **The machine was shared.** M2's implementer ran its own unit lane
   during this one's targeted runs, and one 89-test file took 400 s
   against 25 s alone; the lane timings below were taken with the
   machine otherwise idle.

### The failing set

From full runs with `-ra` after every behavior commit and before any
rebinding (`.logs/inventory-unit.log`, `58 failed, 8321 passed, 19
skipped in 1659.66s`, no errors; `.logs/inventory-integration.log`, `19
failed, 338 passed in 374.70s`, no errors). Tests that asserted a
behavior a commit changed on purpose were rewritten in that commit and
are not in this list: the claim's (`test_device_record.py`,
`test_config_api_pending.py`, `test_config_cli.py`), the bindings'
(`test_device_bindings.py`), the pin's (`test_live_binding_pin.py`,
`test_live_device_read.py`), the boot rule's (`test_config_checks.py`,
two in `test_config.py`, one in `test_config_store.py`), the mint's
(`test_browser_routes.py`), the notices' (`test_config_api_writes.py`)
and the seeds' (`test_smoke_seeds.py`).

**Unit lane (58)**, every node the run reported, none truncated:

- `tests/unit/test_agent_rename_in_flight.py::test_a_rename_between_the_world_and_the_open_reaches_the_session`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_agent_rename_in_flight.py::test_a_session_opened_before_the_apply_still_writes_the_new_name`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_api_openapi.py::test_a_write_declares_the_entity_schema_it_takes`: follows `PendingClaim`.
- `tests/unit/test_browser_no_leak.py::test_a_browsers_identity_reaches_exactly_the_fields_a_boards_does`: rebound: the file's own config binds the MAC it presents.
- `tests/unit/test_browser_no_leak.py::test_an_accepted_token_reaches_only_the_reply_that_handed_it_over`: rebound: the file's own config binds the MAC it presents.
- `tests/unit/test_config_boot.py::test_the_re_read_validates_the_whole_snapshot`: rewritten onto a planted dangling default agent (`stores.dangling_default_agent`).
- `tests/unit/test_config_cli_check.py::test_a_refusal_about_the_store_repeats_nothing_stored`: rewritten onto a planted dangling default agent (`stores.dangling_default_agent`).
- `tests/unit/test_config_cli_check.py::test_a_store_that_does_not_compose_names_the_entry_and_the_rule`: rewritten onto a planted dangling default agent (`stores.dangling_default_agent`).
- `tests/unit/test_config_cli_check.py::test_no_refusal_carries_a_sentinel_on_any_surface[composition]`: rewritten onto a planted dangling default agent (`stores.dangling_default_agent`).
- `tests/unit/test_config_cli.py::test_every_mutating_command_says_when_the_write_applies`: follows the reworded default-agent notices.
- `tests/unit/test_config_cli_rendering.py::test_the_comparison_groups_what_is_pending_under_one_head`: follows the reworded default-agent notices.
- `tests/unit/test_config_cli_respelling.py::test_the_respelled_grammar_behaves_as_the_old_one_did`: follows the reworded default-agent notices.
- `tests/unit/test_config_control_character_identities.py::test_a_boot_refusal_names_the_stored_entry_with_the_byte_escaped`: rewritten onto a planted dangling default agent (`stores.dangling_default_agent`).
- `tests/unit/test_config.py::test_a_device_can_be_bound_to_several_agents`: rewritten to assert the fallback is gone.
- `tests/unit/test_config.py::test_device_macs_are_normalized`: rewritten to assert the fallback is gone.
- `tests/unit/test_config_url_credential_display.py::test_the_check_command_speaks_a_name_that_is_itself_secret_shaped`: rewritten onto a planted dangling default agent (`stores.dangling_default_agent`).
- `tests/unit/test_config_url_credential_display.py::test_the_completeness_refusal_lists_the_names_without_their_credential`: rewritten onto a planted dangling default agent (`stores.dangling_default_agent`).
- `tests/unit/test_conversations_api.py::test_a_real_conversation_reads_back_over_the_same_server`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_a_cancelled_cleanup_step_still_finishes_the_record`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_a_conversation_lands_a_session_row_shaped_like_the_manifest`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_a_credential_in_a_provider_url_reaches_no_record`: rebound: the file's own config binds the MAC it presents.
- `tests/unit/test_conversations_session.py::test_a_device_that_vanishes_at_the_hello_opens_no_record`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_a_failed_write_costs_the_batch_and_not_the_conversation`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_a_failure_after_the_open_still_finishes_the_record[device discovery]`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_a_failure_after_the_open_still_finishes_the_record[the idle watchdog]`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_a_mid_session_read_stops_at_the_last_completed_turn`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_a_parked_writer_never_delays_a_reply`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_a_real_conversation_lands_a_thread_its_turns_name`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_a_rejected_tool_argument_is_kept_as_content_and_named_on_no_telemetry`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_a_turn_is_visible_before_its_events_are`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_events_beyond_the_bound_go_and_the_conversation_does_not`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_no_producer_on_the_session_loop_can_wait`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_the_events_rows_are_the_decision_track_verbatim`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_the_session_row_is_there_from_the_open`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_the_switch_combinations_decide_what_a_row_keeps[False-False]`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_the_switch_combinations_decide_what_a_row_keeps[False-True]`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_the_switch_combinations_decide_what_a_row_keeps[True-False]`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_the_switch_combinations_decide_what_a_row_keeps[True-True]`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_the_turn_rows_and_the_event_rows_agree`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_the_turns_and_their_tool_calls_land_with_their_numbers`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_conversations_session.py::test_what_a_person_said_becomes_a_title_and_reaches_nothing_else`: rebound: `recording_config` binds `DEVICE_MAC`.
- `tests/unit/test_endpointer_echo.py::test_the_first_answer_after_a_reply_is_heard`: rebound: the file's own config binds the MAC it presents.
- `tests/unit/test_event_baseline.py::test_every_catalog_variant_on_a_scoped_channel_is_produced`: rebound: the driver binds the device it checks in with.
- `tests/unit/test_event_baseline.py::test_every_driver_produces_the_shape_its_path_declares`: rebound: the driver binds the device it checks in with.
- `tests/unit/test_onboarding_activation.py::test_a_configured_default_agent_keeps_todays_behavior_for_unknown_devices`: rewritten to assert pairing (a code, no token).
- `tests/unit/test_ota.py::test_a_device_the_configuration_covers_is_never_asked_to_activate`: rewritten to assert pairing (a code, no token).
- `tests/unit/test_ota.py::test_unknown_device_falls_back_to_the_default_agent`: rewritten to assert pairing (a code, no token).
- `tests/unit/test_ota_tokens.py::test_the_default_agent_makes_every_device_a_bound_one`: rewritten to assert pairing (a code, no token).
- `tests/unit/test_recording_order.py::test_a_session_refused_before_its_hello_records_nothing[no agent]`: rewritten: "no agent" is now an unbound device beside a default agent.
- `tests/unit/test_session_device_location.py::test_a_device_a_default_agent_covers_is_refused_a_place`: removed: its condition cannot arise (no-record refusal stays covered by the deleted-record case).
- `tests/unit/test_session_device_name.py::test_a_device_with_no_record_records_no_name`: rewritten: a snapshot binding with no name drives the null name.
- `tests/unit/test_session.py::test_a_device_gets_the_prompt_and_the_voice_of_its_own_agent[aa:bb:cc:dd:ee:04-POET-440.0-880.0]`: rewritten: the unbound MAC is turned away.
- `tests/unit/test_session_reply_failures.py::test_a_barge_in_while_the_mask_settles_cancels_rather_than_wedging`: rebound: the file's own config binds the MAC it presents.
- `tests/unit/test_simulator_board.py::test_the_trap_state_names_every_reading_that_produces_it`: follows `MAY_NOT_SPEAK`, which no longer names `default_agent`.
- `tests/unit/test_ws_browser_credential.py::test_a_browser_with_a_valid_token_is_accepted_selecting_the_protocol`: rebound: the file's own config binds the MAC it presents.
- `tests/unit/test_ws_browser_credential.py::test_the_session_serves_the_identity_the_subprotocols_presented`: rebound: the file's own config binds the MAC it presents.
- `tests/unit/test_ws_browser_credential.py::test_the_whole_start_a_browser_makes_check_in_then_upgrade`: rebound: the file's own config binds the MAC it presents.
- `tests/unit/test_ws_browser_credential.py::test_with_auth_off_a_browser_offers_no_token_and_is_accepted`: rebound: the file's own config binds the MAC it presents.

**Integration lane (19)**, every node the run reported, none truncated:

- `tests/integration/test_browser_handshake.py::test_a_browser_and_a_board_each_reach_a_session`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_capture_upload.py::test_a_recorded_session_is_attached_to_its_trace`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_capture_upload.py::test_audio_alone_files_the_clips_and_exports_no_transcript`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_capture_upload.py::test_the_uploaded_pair_is_referenced_on_the_session_trace`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_capture_upload.py::test_the_upload_outcome_reaches_the_collector_too`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_capture_upload.py::test_transcripts_alone_export_the_words_and_stage_no_clip`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_cli_live.py::test_a_board_is_onboarded_by_the_code_on_its_screen`: rewritten: a default set, the board still pairs, a claim naming no agent binds it to the default.
- `tests/integration/test_cli_live.py::test_the_check_reads_the_store_the_running_server_booted_on`: rewritten onto a planted dangling default agent (`stores.dangling_default_agent`).
- `tests/integration/test_cli_simulator.py::test_a_deployment_that_issues_no_tokens_holds_the_whole_conversation`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_device_simulator.py::test_a_scripted_conversation_gets_a_spoken_reply`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_device_simulator.py::test_a_second_utterance_is_answered_without_reconnecting`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_mcp_reload.py::test_a_refused_reload_leaves_the_running_servers_alone`: rewritten onto a planted dangling default agent (`stores.dangling_default_agent`).
- `tests/integration/test_telemetry_export.py::test_one_source_tree_turn_arrives_directly_in_jaeger`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_telemetry_export.py::test_one_turn_arrives_at_a_collector_as_the_trace_it_is`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_telemetry_export.py::test_the_gen_ai_keys_arrive_spelled_as_the_conventions_spell_them`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_telemetry_export.py::test_the_resource_that_arrives_is_the_servers_own`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_telemetry_export.py::test_the_session_id_arrives_under_the_grouping_alias_too`: rebound: the file's own config binds the MAC it presents.
- `tests/integration/test_two_personas.py::test_an_unbound_device_gets_the_default_agent`: rewritten: the unbound MAC is turned away.
- `tests/integration/test_wire_latency_capture.py::test_the_script_measures_a_turn_of_a_session_it_recorded`: rebound: the file's own config binds the MAC it presents.

### The pages naming the default agent

`git grep -n -i "default.agent" -- docs README.md vinga-server/examples
vinga-server/config.example.yaml ':!docs/plans' ':!docs/adr'
':!docs/features' ':!docs/reference'`, taken at the base before any
edit: 54 lines in 19 files, every one below with what became of it.
"A device's own default" is the first entry of its binding, which M1
does not touch.

- `README.md:246` (the Getting Started document's `default_agent`
  comment): reworded, the key kept (M7 changes the presets);
  `README.md:314` (step 5): rewritten to pair with a claim naming no
  agent.
- `docs/architecture/cli-guide-audit.md:130`: a dated audit, unchanged.
- `docs/architecture/cli-guide.md:241` and `:861` (history), `:779` and
  `:798` (`info`'s "no default agent", still true), `:998` (a comparison
  listing, whose token is unchanged): unchanged; `:670`: rewritten for
  the two default-agent notices.
- `docs/architecture/direction.md:28`, `:30`, `:40`: a device's own
  default by voice (#606), unchanged.
- `docs/concepts.md:185`: the location tool's sentence about a board a
  default agent merely covers, removed; `:245`: rewritten (Binding);
  `:249`, `:339`, `:445`, `:446`: a device's own default, unchanged.
- `docs/devices/README.md:300`,
  `docs/devices/waveshare-esp32-s3-touch-amoled-2.16.md:72`,
  `docs/devices/waveshare-esp32-s3-touch-lcd-1.54.md:61`,
  `docs/glossary.md:574`: a device's own default, unchanged. The
  glossary gains a "Default agent" entry.
- `docs/devices/browser.md:35`: the try link binds the default agent,
  unchanged until M1b; `:66`: the D4a paragraph, rewritten.
- `docs/run/configuration-api.md:72` (the list of kinds): unchanged;
  `:166`, `:177`, `:188`: rewritten (the claim body, the notices).
- `docs/run/configuration.md:46`, `:102`, `:166`, `:168`, `:209`: all
  rewritten (what `default_agent` is, the boot rule, when it applies).
- `docs/run/onboarding-a-device.md:103`, `:123`: rewritten (steps 4 and
  5, which devices are offered a code); `:175`, `:206`, `:207`: the try
  link, unchanged until M1b and M3.
- `docs/run/security.md:186`: rewritten ("Who gets a token is the
  allowlist").
- `docs/run/with-a-coding-agent.md:337`: rewritten; `:382`: the
  completeness refusal's sentence, removed; `:148`, `:521`, `:552`: the
  try link, unchanged until M1b; `:358`: a default agent naming a
  removed agent, still a conflict, unchanged.
- `vinga-server/config.example.yaml:17`, `:23`: the section list and the
  import recipe, unchanged; `:166`: rewritten.
- `vinga-server/examples/README.md:109`, `:110`: kept, with the
  paragraph after them rewritten.
- `vinga-server/examples/presets/cloud-stack.yaml:31`, `:40` and
  `local-stack.yaml:23`, `:32`: the comment block rewritten
  (deviation 7).

### Tests first, and the mutations

Every new test was run red against the code before it changed, except
the round-2 pairing test, which was written after the rule change and
held to a mutation instead. Each mutation was applied once, run, and
restored by copy and `touch`.

| Mutation | Killed by |
| --- | --- |
| `_bound`'s stored arm answers `stored.default_agent` for an empty binding (before the pin moved) | `test_an_unbound_device_reaches_no_agent_while_a_default_is_set[database]`, `test_setting_a_default_agent_admits_no_unbound_device` |
| `_bound`'s stored arm falls back to the served world's `default_agent` (on the final tree) | `test_an_unbound_device_reaches_no_agent_while_a_default_is_set[database]`, `test_a_minted_browser_pairs_and_is_admitted_only_once_claimed` (at the first check-in's token) |
| `Config.bound_to` answers the default agent for a MAC with no record | `test_an_unbound_device_reaches_no_agent_while_a_default_is_set[snapshot]`, both rebound `test_config.py` cases, the two new `test_ota.py` cases, `test_the_default_agent_makes_no_device_a_bound_one` |
| `_live_binding` reads the default row again | `test_the_lookup_sends_exactly_this_statement`, `test_the_statement_is_the_same_on_a_device_with_no_row`, `test_a_shouted_mac_binds_the_canonical_one` |
| `ALREADY_COVERED` restored (a claim refused while a default agent is set) | seven: both new `test_device_record.py` claim cases, `test_a_claim_binds_a_device_though_a_default_agent_was_set_since`, both parameters of `test_a_claim_naming_no_agent_binds_the_default_agent`, `test_add_device_naming_no_agent_binds_the_default_agent`, the round-2 pairing test |
| D4a's 503 arm restored (refuse while the bindings read is not authoritative) | `test_a_mint_does_not_depend_on_reading_the_bindings` |
| D4a's 409 arm restored (refuse when the minted MAC resolves to agents) | **survives**, see below |
| The boot rule restored in `Config._check_domain` (not an M1 target, run anyway) | `test_agents_no_device_reaches_are_a_deployment_awaiting_a_claim`, `test_agents_no_device_can_reach_still_boot` |

**The surviving mutation.** Restoring D4a's first refusal, `if
bound.names: 409`, changes no test's outcome, and the reason is the
driver, not the assertions: the condition cannot be reached. A minted
MAC is random and locally administered, so it has no binding, and since
M1 a MAC with no binding resolves to no names whatever `default_agent`
says. The refusal could only fire for a minted MAC that happened to
collide with a bound one, which no test can arrange through the
interface. Restored, it is dead code; the mutation that would make it
live is the fallback, which the rows above kill.

### Verification

- `uv run ruff check .`: clean.
- Unit lane, `-n auto --dist loadfile` (start at 48.5 °C):
  `8422 passed, 19 skipped in 977.51s` (`.logs/final-unit.log`).
- Integration lane, `-n auto --dist loadfile` (start at 50.7 °C):
  `358 passed in 222.80s` (`.logs/final-integration.log`).
- The browser lane, through `tests/browser/run.sh` in
  `mcr.microsoft.com/playwright/python:v1.63.0-noble` under Podman
  (`--network host`, the development database on 127.0.0.1): `8 passed
  in 47.03s` (`.logs/browser-lane.log`).
- The generated documents regenerated through their generators
  (`config reference`, `config reference server`, `events reference`,
  `config openapi`, `config cli-reference` into its markers): no diff
  against the committed copies after the last code commit.
- `scripts/check_doc_links.py`: `checked 337 files, 0 failures`;
  `scripts/check_run_use_pages.py`: `checked 37 Run and Use pages, 0
  findings`; `scripts/fold_changelog.py check`: `checked 1 fragments, 0
  failures`.
- `tests/census`: run last, after this section, recorded in the
  hand-back.

Not verified: the smoke lane (the seeds were run only through
`test_smoke_seeds.py`, not in the image), the wheel-level drift checks
CI runs against an installed wheel, and any board: no device was
onboarded against this build.

### PR review round

Reviewed 2026-10-07 by openai/gpt-6-sol, thinking high via codex CLI 0.160.1, read-only sandbox, at commit fc94316c ([the round](https://github.com/rafacm/vinga/pull/632#issuecomment-6033152918)). The fixes are by anthropic/claude-opus-5-5, thinking high, M1's own implementer.

1. **P2: a rename that moved only the default agent promised a device
   check-in.** *Resolution:* `_rename_notice` gives that case
   `DEFAULT_AGENT_UNSERVED_NOTICE` (the install alone), whose sentence
   already describes it, and keeps `RENAME_UNSERVED_NOTICE` for a rename
   that moved a binding; API and CLI tests split the two cases, and the
   default-only test failed on the old code first (`24b5a697`).
2. **P2: device deletion's help and API description promised the
   removed fallback.** *Resolution:* both say a deleted device is
   unbound whatever the default agent; the CLI and OpenAPI references
   regenerated; an untruncated grep found no other statement of the old
   rule beyond the `sessions.device_name` column comment already
   recorded as a follow-up (`cff79346`).
3. **P2: the browser guide said both ways of joining work on every
   server.** *Resolution:* it states that both need onboarding on, that
   a try link also needs a default agent, and that pairing needs none
   when the claim names the agent; the packaged copy regenerated in the
   same commit. M1b rewrites the section for invite links (`7773c570`).

Verification after the round: `uv run ruff check .` clean; the unit lane
(`-n auto --dist loadfile`) `8423 passed, 19 skipped in 1006.25s`; the
generated documents current; link check and Run and Use page check
clean. The integration and browser lanes were not rerun for a notice
choice, two descriptions and a guide paragraph.

## M1b: browsers join by invite

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.291; 2026-10-07.

### What landed

| Plan item (Q11) | Where | Commit |
| --- | --- | --- |
| One vocabulary: `try_links.py` is `invites.py`, `TryLinks` is `Invites`, every reason, sentence and suite says "invite" | `onboarding/invites.py`, `onboarding/__init__.py` (`INVITE_TTL_S`, `INVITE_CAPACITY`, `INVITE_MINTS`), `config/responses.py` (`Invite`), `config/loader.py` (`InviteRefusedError`), `config/api.py` and its two description files, `composition.py`, `app.py`, the page's JavaScript, `tests/unit/test_invite*.py`, `test_invites.py`, `test_config_cli_invite.py` | `Rename try links to invites in the code` |
| The route and its body; the agents travel with the token and are bound at redemption | `POST /api/runtime/invites` with a required `InviteRequest` body (`config/api.py`, `config/responses.py`); `Issuer.issue(agents, store, served)` and `Invites.issue(agents)` / `claim -> Invitation` (`onboarding/invites.py`); `ConfigStore.enroll_device(mac, name, agents)` and `read_agent_names` (`config/store.py`) | `Carry an invite's agents from issuance to binding` |
| The page at `/talk/`, moving its static routes and the `ota_path` reservation | `config/models.py` (`BROWSER_MOUNT_PATH`), `browser/static/urls.js` (its copy of the redeem path), the route inventory | `Serve the browser page at /talk/` |
| `vinga device invite [--agent NAME]...`; `vinga info` reporting only | `config/cli/devices.py` (`INVITE`, `_situated_link`, `_invite_link`), `config/cli/grammar.py` (`_invited_by`, the row, `info`'s two acts), `config/cli/acts.py` and `reach.py` (`Act.declined` and `Refused` removed) | `Add vinga device invite and stop info issuing` |
| The page's joined sentence | `browser/static/page.js` | `Say a redeemed browser joined, not to which agent` |
| The documentation footprint | as listed below | `Name vinga device invite where comments named info`, `Document invite links and the page at /talk/` |
| The fragment | `changelog.d/612-invite-links.md` | `Add the changelog fragment for invite links` |

Design footprint as planned: `onboarding/invites.py` keeps
`try_links.py`'s depth under its new name and gains the bound agents
(the API route stays a body read and one `issue` call); the CLI gains
one verb under an existing noun, and loses two act-level mechanisms
(`Act.declined`, `reach.Refused`) that only `info`'s link needed.

### Deviations from the plan

1. **The identity route was renamed too.** Q11 lists the module, the
   class, the reasons and the page path. The page's identity mint, on
   the onboarding alias, was `/x/<key>/try-identity`, named for the
   page's old address; leaving it would have kept a "try" route behind
   a page called `/talk/`. It is `/x/<key>/browser-identity` now
   (`IDENTITY_SEGMENT`, `browser_identity` in `browser/router.py`), and
   the old segment answers the stock 404 like the other old paths. An
   enrolled browser holds its identity and never calls this route, so
   nothing already joined depends on the old name.
2. **The page's joined sentence changed.** `page.js` told a redeemed
   browser it was "bound to its default agent", which is false for an
   invite that named agents; it now says what the pairing path already
   says, that the browser is a device of this server.
3. **`Act.declined` went, and so did `reach.Refused`.** The brief allows
   dropping `completes`/`declined` where nothing else uses them.
   `declined` had no other user, and `Refused` (the `ConfigError`
   subclass `reach._answer` raised for a validated problem body) existed
   only so `_performed` could tell an API refusal of `info`'s link from
   any other failure; both went, and `_performed` is back to stopping
   at the first refusal, as before #613. `completes` stays: the invite
   still needs the loopback origin only the client knows (D5c).
4. **The invite act lives in `config/cli/devices.py`**, beside the noun
   that owns it, rather than in `deployment.py` where `info`'s act
   lived; it sends the binding's own body (`_binding`), which is
   exactly `{"agents": [...]}`, rather than a second function building
   the same object.
5. **A glossary entry, "Invite link".** Not in the plan's M1b list; the
   concept ships here, so it is named here.

### Resolutions

- **Refusal reasons.** An unknown named agent is a 422 carrying
  `agents-unknown`, the claim's existing reason and status; an unserved
  one is a 409 carrying `agent-not-serving`, the reason an unserved
  agent's prompt read already carries, its docstring widened to say so.
  No `RefusalReason` member was added or renamed: `no-default-agent`
  still has a site (issuance naming none) until M3 renames it. Both
  sentences (`AGENTS_UNKNOWN`, `AGENT_NOT_SERVED`) quote no name, and
  the CLI's existing remedies (`vinga list`, `vinga apply`) follow.
- **Stored and served, both.** A named agent has to be in the store (or
  the redemption's write would not resolve it) and in the installed
  world (or the browser would reach an agent that does not answer).
  The store half reads names alone, through a new
  `ConfigStore.read_agent_names`, rather than an agent read that would
  decrypt stored secrets.
- **The default agent is read at redemption, not frozen at issuance.**
  An invite naming none carries an empty tuple, and redemption binds
  whatever the default is when the browser opens it, read inside the
  write's transaction as before; named agents are what ride with the
  token. That is what "the agent a newly bound device starts with"
  means, and M3's D5 refusal stays at issuance.
- **Names are trimmed and a repeat collapses** (`--agent kids --agent
  kids` binds `kids` once), the shape a binding stores; a blank name is
  simply not an agent the store has, so it meets `agents-unknown`.
- **The body is required.** `{}` or `{"agents": []}` names none; a
  request with no body is a 422. A body lost on the way would otherwise
  bind the browser to the default agent rather than the agents it named.
- **`device invite`'s output.** The link alone on stdout, and one fixed
  line on stderr (`INVITED`) that repeats no agent name. With no origin
  either end can name, it fails with `NO_LINK_ORIGIN` on stderr and an
  empty stdout, rather than printing the sentence where the link would
  be as `info` did: a script holding `$(vinga device invite)` must never
  hold a sentence. The link issued in that case stays live until it
  expires, as `info`'s did.
- **`--agent`'s help states its default** (`(default: the default
  agent)`), which `test_every_command_describes_every_parameter_it_declares`
  requires of every option that takes a value.

### Discoveries

1. **`vinga device delete`'s help said the board "reaches the default
   agent"** afterwards, which M1 made false. Noticed here and left to
   M1's review, which fixed it (`cff79346`, M1's round, finding 2)
   before this milestone was rebased onto it.
2. **What still says "try", by an untruncated grep** (`git grep -i -E
   "/try\b|/try/|try link|try-link|try_link|try-identity|try token|runtime/try"`
   outside `docs/plans`, `docs/features` and `CHANGELOG.md`, 17 lines
   after the rebase onto M1's merge, kept in this worktree's
   `.logs/try-inventory-rebased.txt`): this milestone's own changelog
   fragment, which names the old link and path to say they changed
   (two lines); the M1 ADR's "try links are unchanged for now", a
   record of that decision; conversations migration `1012`'s docstring
   and its upgrade test's, records of #613 that a migration does not
   rewrite; the old-path tests (ten lines); and the browser guide's
   sentence saying a bookmark to `/try/` shows nothing, and its
   packaged copy. No identifier is spelled `try_*`, `TRY_*` or
   `Try*` any more.

### Tests first, and the mutations

Every new test was run red before its code changed (`.logs/c2-red.log`,
`.logs/c4-red.log`), except the old-path test, written with the move
and run red through the two mutations that put the old paths back.
Each mutation was applied once, run, and restored by copy
and `touch` (`.logs/m1b-mutations.log`).

| Mutation | Killed by |
| --- | --- |
| `--agent` ignored at redemption (`enroll_device` handed `()`) | `test_redeeming_binds_exactly_the_agents_the_invite_named`, `test_named_agents_are_bound_though_the_default_was_cleared_since`, `test_a_named_agent_deleted_since_issuance_binds_nothing` |
| The claim hands back no agents (`Invitation()`) | both new `test_invites.py` cases and the three redemption cases above |
| An unserved named agent issued (served check removed) | `test_an_invite_naming_an_agent_this_server_is_not_serving_issues_nothing` |
| An unknown named agent issued (store check removed) | five `test_an_invite_naming_an_agent_that_does_not_exist_issues_nothing` cases, `test_an_agent_served_but_deleted_from_the_store_since_issues_nothing`, both `test_a_refused_invite_quotes_no_name_it_was_sent` cases |
| `info` still issuing (the invite act back in `info`'s acts) | 24 `test_config_cli_info.py` cases, `test_two_runs_against_one_state_are_the_same_bytes` and `test_both_acts_are_answered_by_the_address_the_banner_named` among them |
| The old page path still served (`BROWSER_MOUNT_PATH` back to `/try`) | five `test_the_page_s_old_paths_answer_the_stock_404` cases, `test_a_path_that_is_not_under_the_page_is_allowed[/try/]`, the route inventory, and the page's own cases |
| The old identity segment still served | both `{alias}try-identity` cases of the old-path test, the route inventory, the mint's cases |

No survivor.

### Verification

All on the Raspberry Pi 5, logs in this worktree's `.logs/`. Both lanes
ran with `-n auto --dist loadfile` (four cores, so four workers; `-q`
does not print the count), never the `-n 2` fallback: the unit lane
started at 46.3 °C, the integration runs at 57.9 °C and 55.1 °C.

- `uv run ruff check .`: all checks passed.
- Unit lane: `8472 passed, 19 skipped in 1002.11s (0:16:42)`
  (`.logs/final-unit.log`).
- Integration lane, first run: `2 failed, 356 passed in 919.97s`
  (`.logs/final-integration.log`, the machine shared with another
  lane at load 5). The two were `test_the_lane_ran_every_command_of_the_registration_table`
  (wheel) and `test_the_lane_drove_every_command_of_the_registration_table`
  (live): the new row had no case in either CLI lane, which
  `Drive vinga device invite in both CLI lanes` adds. Second run:
  `360 passed in 223.07s (0:03:43)` (`.logs/final-integration-2.log`).
- The browser lane, through `tests/browser/run.sh` in
  `mcr.microsoft.com/playwright/python:v1.63.0-noble` under Podman
  (`--network host`, the development database on 127.0.0.1): `8 passed
  in 46.16s` (`.logs/browser-lane.log`), the page at `/talk/`, its links
  from `POST /api/runtime/invites`.
- The generated documents regenerated through their generators (the
  domain, server, conversations, metrics-views, events, OpenAPI and CLI
  references) leave no diff after the last code commit, and the CLI
  recipes read from the committed page equal the renderer's.
- `scripts/check_doc_links.py`: `checked 337 files, 0 failures`;
  `scripts/check_run_use_pages.py`: `checked 37 Run and Use pages, 0
  findings`; `scripts/fold_changelog.py check`: `checked 2 fragments, 0
  failures`.
- `tests/census`: run last, after this section is committed, recorded
  in the hand-back.

**After the rebase onto M1's merge** (`git rebase --onto origin/main
fc94316c`, M1 having landed with its review round's three fixes): one
conflict, in this document, where M1's review-round section now ends
M1 and this section follows it. The browser guide merged without a
conflict but kept M1's new paragraph on what each way of joining
needs, written for the try link, so a twelfth commit, `State when an
invite link works in the browser guide`, restates it for invite links
and regenerates the packaged copy. Both census manifests regenerated
to no change. The lanes were run again on the rebased tree; their
lines are in the hand-back.

Not verified: the smoke lane and the image (nothing in the seeds or the
image build changed, and neither was run), the wheel-level drift checks
CI runs against an installed wheel beyond the wheel lane's own case,
and any real browser outside the lane: no person opened an invite link
against this build.

### PR review round

Reviewed 2026-10-07 by openai/gpt-6-sol, thinking high via codex CLI 0.160.1, read-only sandbox, at commit 5fa7d8d6 ([the round](https://github.com/rafacm/vinga/pull/633#issuecomment-6035335387)). The fixes are by anthropic/claude-opus-5-5, thinking high, M1b's own implementer.

1. **P1: a failed browser identity mint could escape as a traceback.**
   `mint()` ran outside `redeem`'s containment, and the
   `browser-identity` route called it bare, with no sanitized boundary
   in the parent app. *Resolution:* `redeem` mints inside the arm that
   already contained store failures (the link is spent, nothing bound,
   one `SPENT_UNENROLLED` warning naming only the class), and the route
   catches the same way, logs a `MINT_FAILED` warning after the handler
   and answers 503 with the fixed `IDENTITY_UNAVAILABLE`.
   `tests/unit/test_mint_failure.py` injects a failing generator whose
   message carries a sentinel, on `redeem` and both routes; all three
   failed first with the sentinel in the escaping chain (`5ebf9b27`).
2. **P2: the browser lane kept an invite token in an exception chain.**
   *Resolution:* `lane.opened` makes the navigation, leaves the handler,
   then raises its fixed error with nothing chained; a plain test proves
   the chain carries no token and failed against the old in-handler
   raise (`e9d980b5`).
3. **P2: three texts still described the old issuer.** *Resolution:*
   the onboarding-off refusal says invite link, the invites route
   description names `vinga device invite` as the client supplying the
   origin, and the coding-agent guide says `info` has one credential to
   filter; the OpenAPI reference regenerated and an untruncated grep
   found only intended matches (`6569ed0b`).

Verification after the round: the unit lane (`-n auto --dist loadfile`)
`8476 passed, 19 skipped in 1089.53s`; the browser lane `10 passed` on
its second run. Its first run errored at setup on every case with a 401
on the lane's own event-stream request, unchanged code passing on the
rerun; another server on the host network answering the lane's port is
the likely cause (two implementers were running lanes at once), not
confirmed. Generators without diff, ruff, link, Run and Use page and
fragment checks clean.

## M3: vinga, the built-in default agent

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.291; 2026-10-07.

### What landed

| Plan item | Where | Commit |
| --- | --- | --- |
| D1, the persona | `knowledge/persona.md`, `knowledge/persona.py` (`persona()` is the persona, a blank line, then the summary verbatim) | `Write vinga's persona in front of the summary` |
| Q1, the table and migration `3005` | `db/schema.py` (`builtin_agent`, `SINGLETON_ID`), `db/migrations/versions/3005_builtin_agent.py`, the four head pins and the CI wheel check | `Add the builtin_agent table and migration 3005` |
| Q1, the name, the synthesis, `builtin_status`, `is_builtin`, the reference rule, the `mcp` pin, Q10's persona through `prompt_for_agent` | `config/models.py` (`BUILTIN_AGENT`, `BuiltinAgentConfig`, `builtin_agent` in `DOMAIN_KEYS`, `DomainConfig` and `DomainSnapshot`, `resolvable_agents`, `BuiltinStatus`, `BuiltinState`, `builtin_status`, `builtin_entry`, `Config.builtin_state`, `Config.is_builtin`), `config/__init__.py` | `Serve vinga as a built-in agent of the served whole`, `Import the persona only when one is assembled` |
| Q1, the descriptor and the `vinga builtin-agent` noun | `config/entities.py`, `examples/builtin-agent.yaml`, `examples/README.md`, `config.example.yaml` | `Describe builtin_agent as an entity kind` |
| Q1, the store, and the refusal to create `agents.vinga` | `config/store.py` (`read_builtin_agent`, `set_builtin_agent`, the singletons read and staged from the registry, `BUILTIN_NAME_RESERVED` in `_stage_entity` and `rename_agent`) | `Store builtin_agent and refuse a new agents.vinga` |
| Q1, the remaining surfaces | `config/views.py`, `config/responses.py`, `config/api.py`, `config/cli/entities.py`, `config/cli/deployment.py`, `config/docgen.py`, `config/diff.py` (`builtin_agent` field), `config/reload.py` (`builtin_changed`) | `Carry builtin_agent through the API, diff and apply` |
| Pin before reshaping | `tests/unit/test_session_prompt.py` (`OPERATOR_PROMPT`) | `Pin an operator agent's assembled prompt` |
| Q5, memory | `memory/store.py` (`read_for_prompt` and `recall` take `agent_scope`) | `Let a memory read leave the agent scope out` |
| Q5, threads | `conversations/threads.py` (`candidates(..., device)`, `Backlog.device`, `Reads.candidates`), `runtime/resumption.py` (built with the session's MAC; `described(..., on_device)`; the backlog's device check) | `Hold a thread search to the device it runs on` |
| Q5, the predicate handed to the tools | `tools/builtin.py` (device-only `remember` schema and scope, `_reachable`, `recall`), `tools/source.py` (`BuiltinTools(..., is_builtin, ...)`), `runtime/pipeline.py` (`_builtin` resolved on the memory policy's line, in the snapshot key, the prompt read, the `Resumption`), `app.py` (the preview) | `Give vinga its device's memory and threads` |
| D6, the event | `events/values.py` (`ProviderStages`, `BuiltinNotServed`), `events/catalog.py` (`GENERATION_CHANNEL`, two variants, `builtin_agent_not_served`), `generation.py` (`said_what_it_serves`), the event baseline, `docs/run/logs-and-traces.md`, `docs/reference/events.md` | `Say when an installed world does not serve vinga` |
| D6, `vinga info` | `config/responses.py` (`BuiltinAgentStatus`, `RuntimeInfo.builtin_agent`), `config/api.py` (`builtin_state` read per request), `app.py`, `config/cli/deployment.py` (`_builtin_line`) | `Report vinga's status live in vinga info` |
| Generated references | `docs/reference/domain-config.md`, `api-openapi.json`, `cli.md`, `events.md`, through their generators | `Regenerate the references for builtin_agent` and the two commits above |
| The suites that hold the domain document's shape | see the commit body | `Follow builtin_agent through the configuration suites` |
| The documentation footprint before the deferred part | `docs/concepts.md` (Agent, Memory, Meta capabilities), `docs/glossary.md` (vinga), `docs/run/configuration.md` (Overriding vinga), `docs/run/security.md`, `docs/run/configuration-api.md`, `docs/architecture/cli-guide.md` (the noun list), the packaged copy | `Document vinga, the built-in agent`, `Regenerate the packaged Use pages`, `Name builtin-agent among the CLI guide's nouns` |
| The fragment | `changelog.d/612-built-in-agent.md` | `Add the changelog fragment for the built-in agent`, `Add the default and invite entries to the fragment` |
| Q4's claim and enrolment arms, D7 (after M1b) | `config/models.py` (`effective_default_agent`), `config/store.py` (`NOTHING_TO_ENROLL_ONTO` gone), `config/api.py` (the clear's notice and acknowledgement), `config/entities.py`, `config/responses.py`, `config/cli/grammar.py`, `config/cli/deployment.py` (`vinga (built in)`) | `Bind a claim naming no agent to vinga by default` |
| D5 (after M1b) | `onboarding/invites.py` (`DEFAULT_AGENT_NOT_SERVED`), `config/responses.py` (the renamed member), `config/cli/reach.py` (its remedy), the API descriptions | `Refuse an invite only when the default is unserved`, `Regenerate the references for D5 and D7` |
| The browser lane's vinga case | `tests/browser/test_browser_client.py` | `Drive vinga as the default through the browser lane` |
| The documentation the deferred part touches | concepts.md, glossary.md, configuration.md, onboarding-a-device.md, the coding-agent guide, the browser guide, `config.example.yaml`, the presets, the packaged copy | `Document vinga as the default and the invite refusal`, `Regenerate the packaged Use pages again` |
| The suites M1b brought | `test_invite_redeem.py`, `test_mint_failure.py` | `Follow the effective default through M1b's suites` |

Design footprint as planned: `config/models.py` holds the name, the
synthesis, the status and the predicate; `config/store.py`,
`tools/builtin.py`, `tools/source.py`, `memory/store.py`,
`conversations/threads.py` and `runtime/resumption.py` are deepened. No
new module, and no new seam: nothing at the device edge knows vinga is
built in.

### The registration inventory

`git grep -c "agent_defaults\|agent-defaults\|AgentDefaults" -- 'vinga-server/src/*.py'`
at `e7a65246`, the commit M3 starts from, untruncated: 15 files, the
same 15 the plan counted at `7e7caa5d`. What each became:

- `config/__init__.py` (2): exports `BuiltinAgentConfig`.
- `config/api.py` (10): `GET` and `PUT /builtin-agent`, and the reload docstring names the overrides.
- `config/cli/deployment.py` (3): the tree's `builtin_agent` line, the apply's `builtin_agent changed` label. `list`, `show` and `export` read the document generically, so export carries the key with no line of its own.
- `config/cli/entities.py` (2): the tree summary for `builtin-agent`. The `vinga builtin-agent show` and `set` commands are generated from the registry, so the noun needs no line here.
- `config/diff.py` (7): `APPLIES["builtin_agent"]` and the `builtin_agent` field of the comparison.
- `config/docgen.py` (1): the reference's sentence on what an apply installs.
- `config/entities.py` (14): the `builtin-agent` descriptor, and the nested shapes' locations.
- `config/models.py` (41): `BuiltinAgentConfig`, `DOMAIN_DESCRIPTIONS`, `DomainConfig`, `DomainSnapshot`, `check_references`.
- `config/reload.py` (3): `builtin_changed`.
- `config/responses.py` (12): the document's description, `ConfigDiff.builtin_agent`, `AgentsReload.builtin_changed`, the apply outcome's section token.
- `config/store.py` (7): read, set, the singletons read and staged from the registry.
- `config/views.py` (5): the masked read and the whole-document view.
- `db/migrations/versions/3001_postgres_domain.py` (4): untouched; its counterpart is the new `3005_builtin_agent.py`.
- `db/schema.py` (3): the `builtin_agent` table and `SINGLETON_ID`.
- `providers/world.py` (2): nothing, as the plan says: it reads the synthesized `config.agents`.

### Deviations from the plan

1. **The synthesis runs after `_check_domain`, not before it.** Q1 orders
   it before. Over the synthesized entry the reference check would
   report a misspelled override twice, under `builtin_agent.<field>` and
   under `agents.vinga.<field>`; after it, the check judges the stored
   half alone and the synthesis builds on references already resolved.
   `test_a_misspelled_override_is_reported_once_at_boot` holds it.
2. **`builtin_status` answers a `BuiltinState(status, stages)`**, not a
   bare token, so `unprovided` carries the stages the event names
   without a second function that would have to agree with the first.
   `Config` asks it once, before it adds the built-in to its own
   `agents`, and keeps the answer (`Config.builtin_state`), because after
   that `agents` holds the synthesized entry and the function would read
   it as a displacing row.
3. **The persona is imported where it is assembled.** Q8 says
   `config/models.py` may reach `knowledge` without breaking #143's
   weight pin, which is true of its weight and not of the pin: the pin
   names every module the configuration client loads, so a top-level
   import moved it by four names. `prompt_for_agent` imports the package
   inside the built-in's branch, and the pin does not move.
4. **The agent scope is left out with `agent_scope=False`**, a keyword,
   rather than said with `None` as the plan phrases it. The first
   argument is still the acting agent, which a lost read is reported for
   (`memory_unreadable` names it), so it cannot become the optional
   owner.
5. **The event is two variants on a channel of its own.**
   `builtin_agent_not_served` is declared once with
   `BuiltinAgentDisplaced` and `BuiltinAgentUnprovided`, one per reason,
   each carrying its reason as a fixed token, on
   `vinga_server.generation`, the logger of the module that installs
   worlds. The stages are a field and not part of the sentence: the
   catalog renders no list into a sentence.
6. **`BuiltinAgentConfig` re-declares its fields** rather than
   subclassing a layer: `AgentDefaults` carries `mcp`, and a subclass
   cannot take a field away. The include check moved into one function,
   `check_prompt_includes`, that both layers call, and a test holds the
   field set to `AgentConfig`'s minus `prompt` and `mcp`.
7. **The refusal to create `agents.vinga` is a sentence and no
   `RefusalReason` token.** Its next step is choosing another name, a
   correction, which is not what that vocabulary is for.
8. **`Resumption` holds the session's MAC** and a search says
   `on_device`, rather than `described` taking the MAC: the pick has to
   be checked against the same board, and the session's board is fixed
   for the life of the object. `Backlog.device` defaults to `None` so
   the existing test doubles build one unchanged.
9. **`AgentsReload.builtin_changed` defaults to `False`**, the
   "absent from an older server" reading `Acknowledgement.applies`
   already takes; `RuntimeInfo.builtin_agent` is nullable for the same
   reason.

### Resolutions

- **The index measurement (Q5): no index.** A temporary, uncommitted
  case seeded the lane's database with 50 devices of 200 vinga threads
  each (10,000 threads, a turn each) and timed
  `threads.candidates(connection, "vinga", "the kettle on this board",
  device)` 20 times after three warm-ups, on this Raspberry Pi 5:
  **median 8.3 ms, max 8.6 ms** held to one device, against the 50 ms
  bar. The plan for the device-filtered scan is a sequential scan over
  the 10,000 rows, 1.9 ms of execution; the rest is the correlated
  opening-turn subquery and the scoring for 200 rows. So there is no
  conversations migration. `.logs/m3-index-measure.log`.
- **`unprovided` and the boot.** An empty deployment boots with the
  built-in unprovided for all four stages, and says so once.
- **The base pin.** `OPERATOR_PROMPT` was captured with the operator
  agent's every block filled and then run, in a throwaway worktree, at
  `e7a65246`: it passed there, so the pin is the prompt as it was before
  M3 touched anything.
- **Two seeding helpers wrote every served agent to the store**
  (`tests/integration/conftest.py`, `test_config_api_runtime.py`), which
  after the synthesis tried to create `agents.vinga` and was refused.
  They write the stored agents and the override; no production code
  path did the same (an inventory of `config.agents` reads in `src/`
  found only consumers of the served agents).

### Discoveries

1. **The lane's `config_with` world serves the built-in agent**, since
   its defaults name every stage, while `base_config` and
   `config_with_agent` do not. Six reload cases that report which agents
   inherit a default layer now name vinga beside the agent they are
   about, which is the inheritance working rather than noise.
2. **An unheld search over one agent's 10,000 threads took a median
   272 ms** in the same measurement. No vinga search is unheld, so it is
   outside M3, but it is what an operator agent with that many threads
   pays today.
3. **Most of the lane's worlds now log `builtin_agent_not_served`** at
   WARNING when their first generation is built, since they leave a
   stage unprovided. No suite asserted the absence of warnings on that
   channel.
4. **The respelling transcript moved by one line**, `builtin_agent: {}`
   in the store dump, edited in place: it is a pre-rename capture, and
   regenerating it would prove nothing.
5. **The CLI reads a reload answer's flags by key**, so a CLI newer than
   its server would refuse an answer with no `builtin_changed`; the
   model's default covers the server side only. Left as it is under the
   pre-release stance.

### Tests first, and the mutations

The model and store tests were written after the code they drive and
held to mutations instead; the session, thread, resumption, event and
info tests were written against code that already existed for the same
reason. Every mutation below was applied once, run, and restored by copy
and `touch`; the log is `.logs/m3-mutations.log`.

| Mutation | Killed by |
| --- | --- |
| The `mcp` pin dropped (the entry inherits `agent_defaults.mcp`) | `test_the_built_in_takes_no_grants_from_the_defaults` |
| `served` answered for a legacy row (the displacement check removed) | `test_a_stored_agent_named_vinga_displaces_the_built_in`, `test_a_blank_legacy_vinga_stays_the_operator_s_agent_with_its_inherited_grants` |
| Both fact scopes passed for vinga's prompt read | `test_vinga_reads_no_agent_memory_of_its_own` |
| The tools never told vinga is built in (`lambda: False` for the predicate) | `test_vinga_s_remember_has_no_scope_to_choose`, `test_a_fact_told_to_vinga_on_one_board_stays_on_that_board`, `test_vinga_reads_no_agent_memory_of_its_own`, `test_vinga_s_search_is_held_to_the_board_it_talks_through` |
| `remember` ignores the device pin | `test_a_fact_told_to_vinga_on_one_board_stays_on_that_board` |
| The numbered tools reach the agent scope | `test_vinga_cannot_reach_an_agent_fact_by_its_number` |
| The recall tool reads the agent scope | `test_vinga_reads_no_agent_memory_of_its_own` |
| The store's prompt read ignores `agent_scope` | `test_a_prompt_read_with_no_agent_scope_reads_the_device_alone` |
| The store's recall ignores `agent_scope` | `test_a_lookup_with_no_agent_scope_finds_the_device_s_facts_alone` |
| The thread filter dropped (a thread on A offered on B) | `test_a_search_held_to_a_device_finds_only_the_threads_begun_there`, `test_a_search_held_to_a_device_with_none_offers_nothing` |
| `Resumption` does not pass the device | `test_a_search_held_to_the_device_asks_the_store_for_that_board`, `test_a_thread_begun_on_this_board_is_resumed` |
| The backlog's device check dropped (driven by an offer a second device's search forged) | `test_an_offer_of_another_board_s_thread_is_refused_at_the_pick` |
| The store's creation refusal dropped | `test_an_agent_cannot_be_created_under_the_built_in_s_name`, `test_a_document_creating_it_is_refused_whole` |
| The creation refusal ignoring the stored state | `test_an_operator_s_legacy_vinga_may_still_be_edited`, `test_a_displaced_deployment_s_export_applies_back_unchanged` |
| The rename refusal dropped | `test_an_agent_cannot_be_renamed_to_it` |
| The comparison never reporting the override | `test_a_pending_built_in_override_is_visible_until_the_apply` |
| No event at a later install | `test_every_installed_world_says_it_again_and_a_served_one_does_not` |
| `info` reading the status once at startup | `test_info_follows_the_built_in_agent_across_applies` |
| The built-in's name no longer always resolving | `test_the_default_and_a_binding_may_name_the_built_in_whether_or_not_it_is_served`, `test_the_names_a_refusal_lists_include_the_built_in` |
| The override's references left unchecked | `test_an_override_naming_no_provider_is_refused_under_its_own_key`, `test_an_override_naming_no_fragment_is_refused_under_its_own_key`, `test_a_misspelled_override_is_reported_once_at_boot` |
| The built-in answered with the stored prompt | `test_the_built_in_is_answered_with_the_build_s_persona`, `test_vinga_replies_under_the_build_s_persona` |
| D5: issuance asking whether a default is stored rather than whether it is served | `test_with_no_default_agent_a_served_built_in_agent_is_the_default`, `test_a_default_agent_written_since_the_boot_is_not_served_until_applied` |
| D5: issuance ignoring the built-in default (comparing the stored default alone) | `test_with_no_default_agent_a_served_built_in_agent_is_the_default` |
| The claim's and the enrolment's effective default answering nothing when unset | `test_a_claim_naming_no_agent_with_no_default_binds_the_built_in_agent` (store and API), `test_with_no_default_agent_the_browser_is_bound_to_the_built_in_agent` |

One mutation was invalid as written and is not counted: replacing the
live read in the route with a literal `served` state raised a
`NameError` (the enum is not imported there), which fails the test for
the wrong reason. The startup-capture mutation above is the valid form
of the same question.

No survivor among the counted mutations. The plan's M3 targets are the
first rows: the `mcp` pin, `served` for a legacy row, both fact scopes
for vinga (killed at the prompt read, at `remember`, at `recall` and at
the numbered tools), the thread filter, and the backlog's device check
driven through `Resumption` with a forged offer.

### Verification

All on the Raspberry Pi 5, logs in this worktree's `.logs/`. Every
lane ran with `-n auto --dist loadfile` (four cores, four workers),
never the `-n 2` fallback: the hottest start was 54.6 °C. M1b's
implementer shared the machine for part of the run, so the timings
are not idle timings.

- `uv run ruff check .`: all checks passed.
- Unit lane, before the rebase, first run (`.logs/unit-2.log`): `14
  failed, 8516 passed, 19 skipped in 1336.68s`; the fourteen were the
  boot announcement in suites that capture every warning and the live
  status in two whole-answer literals, fixed in `Follow the boot
  announcement and live status in suites`.
- Integration lane, before the rebase (`.logs/integration-1.log`): `7
  failed, 351 passed in 331.57s`, fixed in `Drive builtin-agent through
  both CLI lanes`.
- After the rebase and the deferred part, unit (`.logs/final-unit.log`,
  start 46.9 °C): `4 failed, 8584 passed, 19 skipped in 1045.74s`, the
  four being M1b's suites, fixed in `Follow the effective default
  through M1b's suites`; integration (`.logs/final-integration.log`):
  `1 failed, 362 passed in 247.99s`, the stale build cache above.
- **The final tree**, unit (`.logs/final-unit-2.log`, start 51.3 °C):
  `8588 passed, 19 skipped in 1052.20s (0:17:32)`; integration
  (`.logs/final-integration-2.log`, start 53.5 °C): `363 passed in
  229.17s (0:03:49)`.
- The browser lane, `tests/browser/run.sh` in
  `mcr.microsoft.com/playwright/python:v1.63.0-noble` under Podman
  (`--network host`), with the vinga case: `11 passed in 49.46s`
  (`.logs/browser-lane.log`).
- The drift checks, scripted from the workflow's steps (domain and
  server references, events, OpenAPI, the CLI reference and its
  recipes, the conversations schema and the metrics views): all current
  on the final tree. The packaged copy regenerated with no change.
- `scripts/check_doc_links.py`: `checked 337 files, 0 failures`;
  `scripts/check_run_use_pages.py`: `checked 37 Run and Use pages, 0
  findings`; `scripts/fold_changelog.py check`: `checked 1 fragments, 0
  failures`.
- `tests/census`: run last, after this section and the regenerated
  manifests were committed, and reported in the hand-back.

Not verified: the image was not built and the smoke lane was not run;
no board was onboarded against this build, so the persona has been
heard only through the mock model and the browser lane; and the local
lane (a real model answering as vinga) was not run, since M3 adds no
model behavior the local lane measures and M5 is where the gate's
replay lives.

### The rebase onto M1b, and the deferred part

M1b (#633) merged into `main` while the rest of M3 was done, and the
deferred part was done on the rebased branch, as the brief directed.

**The rebase.** `git fetch origin && git rebase origin/main`: 21
commits, all survived (21 before and after, every commit subject
present). One commit conflicted, `Report vinga's status live in vinga
info`, in four files: `app.py`, `config/api.py`,
`config/cli/deployment.py` and `test_config_cli_info.py`. Each was
resolved by keeping `main`'s invite code (the `invites` runtime field
and dependency, the removed try-link renderers in `deployment.py`, the
`onboarding.invites` imports) and adding this branch's lines beside it
(`builtin_state`, `_builtin_state`, the built-in status constants and
`_builtin_line`). No conflict markers were left (grep). The generated
references and the packaged copy were regenerated on the rebased tree
and did not move; the census manifests were regenerated after the last
commit, below.

**D5.** `onboarding/invites.py`'s issuance refusal for an invite
naming no agent is now `DEFAULT_AGENT_NOT_SERVED`, decided by
comparing the effective default (`store.read_default_agent() or
BUILTIN_AGENT`) with the agents of the world installed now. The
`RefusalReason` member is renamed, not added beside the old one:
`NO_DEFAULT_AGENT` / `no-default-agent` became
`DEFAULT_AGENT_NOT_SERVED` / `default-agent-not-served`, and the
client's remedy for it names `vinga info`, the apply and `vinga device
invite --agent <name>`. **The older-client claim was verified**:
`test_an_older_client_quotes_the_server_s_sentence_for_the_new_token`
takes the token out of this client's vocabulary
(`reach._KNOWN_REASONS`, a deliberate reach-in, since what an older
build lacks is exactly that set) and asserts the command prints the
server's sentence and not the new remedy.

**The claim and enrolment arms (Q4).** `models.effective_default_agent`
answers the stored default or vinga. The store's shared device write
binds a claim or an enrolment naming no agent to it, so
`NOTHING_TO_ENROLL_ONTO` and its decision site went. D7 followed: unset
and `default-agent set vinga` mean the same thing, so clearing the
default carries the notice naming vinga would (waiting for the install
while vinga is not served), and every sentence saying a claim then had
to name its agents now says it binds vinga. `vinga info` prints the
unset default as `vinga (built in)`.

**The browser lane's vinga case.**
`test_with_no_default_agent_an_invite_binds_the_browser_to_vinga`
clears the lane's default, opens an invite naming no agent, and
asserts the browser is bound to vinga and heard and answered.

**The documentation those touch:** concepts.md (Binding), the
glossary's default agent, configuration.md (the default, and the
displaced edge: with no default stored, a claim binds to the
operator's agent named vinga until it is renamed),
onboarding-a-device.md (the claim, the invite's refusal), the
coding-agent guide, the browser guide, `config.example.yaml` and the
presets' comments; the references and the packaged copy regenerated;
the fragment gained the two changed behaviors and the Upgrade line's
edges.

Discoveries in the deferred part:

- **Clearing the default now waits for an install on a world that
  does not serve vinga**, which most test worlds are; two notice tests
  and the respelling table's clear entry moved with it, and a
  parametrized test pins both answers.
- **A remedy quoting `--agent` alone failed the guard** that holds
  every backticked invocation in the remedy table to the grammar; it
  quotes the whole `vinga device invite --agent <name>` instead.
- **M1b's own suites assumed a cleared default refuses**: its
  redemption race (D5a) now binds the browser to vinga, and its
  no-second-draw case refuses through an agent the link names that is
  gone by its opening, the remaining refusal that is not a collision.
- **The stale `uv` build cache, as AGENTS.md describes it.** The first
  integration lane after the rebase failed one tier-closure case,
  `device invite` missing from the client install. Confirmed before
  cleaning: the lane's built venvs held `onboarding/try_links.py` (and
  this branch's `3005_builtin_agent.py`), a build cached before the
  rebase. `uv cache clean vinga-server` and the tier-closure file passed
  whole (43 passed).

### PR review round

Reviewed 2026-10-07 by openai/gpt-6-sol, thinking high via codex CLI 0.160.1, read-only sandbox, at commit 7ada8461 ([the round](https://github.com/rafacm/vinga/pull/634#issuecomment-6037651736)). The fixes are by anthropic/claude-opus-5-5, thinking high, M3's own implementer.

1. **P1: a live session could resume another device's thread after a
   legacy `agents.vinga` was deleted.** An offer held from the legacy
   agent's unscoped search survived the apply that installed the
   built-in. *Resolution:* selection checks the device when either the
   agent picking now or the original search is device-scoped, and the
   pipeline drops outstanding offers when the speaking agent's built-in
   status changes between legs. A session test runs the whole sequence
   in one live session (legacy search, apply, pick of another board's
   thread) and asserts the pick refused, the backlog never read and no
   word of the thread in any prompt; it failed first, as did the unit
   test of the selection half. The pipeline's argument to selection
   survives its mutation because the offers are always dropped first,
   so no driver reaches it; it is kept as the defense the finding asked
   for (`750084b7`).
2. **P2: an invite naming `vinga` was refused as unknown.**
   *Resolution:* the store's agent names for issuance are the
   resolvable names, stored agents plus the built-in, the rule
   `check_references` uses, with the served check after it. Issuance
   and redemption with `--agent vinga` are tested served and unserved;
   both failed first with `agents-unknown` (`282a95f8`).
3. **P2: the documentation promised device-specific answers before
   M4.** *Resolution:* concepts, glossary, configuration and the
   changelog fragment say only what vinga's prompt holds today; a grep
   of the diff finds no device-answer claim. The persona itself was
   qualified too (`knowledge/persona.md`): until M4 puts the board's
   facts in the prompt, vinga says it does not know this particular
   board and points to its guide or the operator, since the gate showed
   small models inventing device facts when nothing backs them; a test
   pins the wording and failed first (`dbde7f1e`, `da1f6def`).

Verification after the round: the unit lane (`-n auto --dist loadfile`)
`8592 passed, 19 skipped in 1049.74s`; the integration lane `363
passed`; the drift checks current; ruff, link, Run and Use page and
fragment checks clean; the knowledge tests `16 passed` after the persona
commit.

## M4: the board reaches vinga's prompt

**Attribution:** anthropic/claude-opus-5-5, thinking medium; Claude Code 2.1.295; 2026-10-09.

### What landed

| Plan item | Where | Commit |
| --- | --- | --- |
| The device block carries the board's facts (Q10) | `runtime/prompt.py`: `with_scopes(..., board=None)` and `_device_block`, the text between the introduction and the notes under the one `device` provenance, compared `is not None` | `Carry a board's facts in the prompt's device block` |
| The session reads its board once at open; the pipeline hands `knowledge.board_facts` to `with_scopes` for the built-in | `device/boundary.py` (`RuntimeFactory` gains a seventh argument, the reported type), `device/session.py` (read off `DeviceFacts` at the open, the read the capture manifest makes, kept nowhere), `runtime/pipeline.py` (`bespoke_runtime_factory` and `PipelineRuntime` take `board`; the constructor keeps `knowledge.board_facts(board)` and not the type; `_system_prompt` hands it over when the snapshot key says the speaker is the built-in) | `Hand vinga the facts of the board it speaks through` |
| The vague text | `knowledge.VAGUE_BOARD_FACTS` from M2, unchanged; reached for no check-in, `unknown`, a type with no guide, `readme` and `flashing` | same |
| Tests, the pin, the sentinel | `tests/unit/test_session_builtin_board.py` (new), `test_session_prompt.py` (the operator pin parametrized with an LCD board reported), `test_boundary_contract.py` (the factory is handed the type), `test_runtime_prompt.py` (three assembler cases), `tests/support/sessions.py` (`device_facts` on the builders) | the two commits above and `Test the board's facts in vinga's prompt` |
| M3's persona sentence qualified back | `knowledge/persona.md`: device questions are answered from the facts further down, with the honest decline kept; `test_knowledge.py`'s pin rewritten | `Let vinga answer device questions from its facts` |
| The board string read off a real board | not done on a board; derived from the upstream source instead, below | |
| Documentation footprint | `docs/devices/README.md` (new section, What vinga knows about the device), `docs/devices/browser.md`, `docs/concepts.md` (Agent, observed facts, hardware facts), `docs/glossary.md` (vinga), `docs/run/configuration.md` (Overriding vinga), the packaged copy | `Document that vinga knows the board it speaks through` |
| The fragment | `changelog.d/612-board-in-prompt.md`, one Changed entry, no `Upgrade:` line | `Add the changelog fragment for the board facts` |

Design footprint as planned: `runtime/prompt.py`, `runtime/pipeline.py`
and `device/session.py` deepened, with `device/boundary.py`'s factory
type gaining the argument the crossing needs. No new module and no new
seam; nothing at the device edge knows vinga is built in.

### The board string, from the firmware's source and not off a board

The plan has M4 read the type a real ESP32-S3-Touch-LCD-1.54 reports
off `vinga events` (`ota_check`'s `board`). **That read was not done:
no board was attached to the machine this milestone ran on** (the
Raspberry Pi, which has none), so the verification box for it stays
unchecked for a session with the board on its desk. What the stock
firmware reports was derived from upstream's source instead, in the
vendored clone of 78/xiaozhi-esp32:

- **At the vendored head** (`4632dc51`, 2026-09-20), `board.type` is
  `BOARD_TYPE` (`main/boards/common/wifi_board.cc:267`, inside
  `GetBoardJson`, which `Board::GetSystemInfoJson` puts under `"board"`
  at `main/boards/common/board.cc:168`, the body `main/ota.cc:95` posts
  at check-in). `main/CMakeLists.txt:879-886` sets `BOARD_TYPE` from the
  `"type"` of the board's `config.json`, which for this board
  (`main/CMakeLists.txt:464-465` selects
  `waveshare/esp32-s3-touch-lcd-1.54`) is
  `"type": "esp32-s3-touch-lcd-1.54"`
  (`main/boards/waveshare/esp32-s3-touch-lcd-1.54/config.json:3`); the
  build refuses anything outside `[a-z0-9.-]` (`:898-901`).
- **At v2.4.0** (`5540258a`, the version the board guide was tested on,
  fetched as a tag into the shallow clone for this read),
  `main/CMakeLists.txt:474` sets it directly:
  `set(BOARD_TYPE "esp32-s3-touch-lcd-1.54")`, and
  `main/boards/common/wifi_board.cc:279` writes it the same way.

Both spell `esp32-s3-touch-lcd-1.54`, without the vendor, which M2's
matcher maps to `devices/waveshare-esp32-s3-touch-lcd-1.54.md` by its
`waveshare-` rule, and which
`test_vinga_is_told_the_facts_of_the_board_it_speaks_through[esp32-s3-touch-lcd-1.54]`
drives through a session. The two sibling guides' boards report
`esp32-s3-epaper-1.54` and `esp32-s3-touch-amoled-2.16` by the same
mechanism (their `config.json:3`, and v2.4.0's `CMakeLists.txt:450`,
`:453` and `:360`), so all three reach their guides. The firmware
checks in at every boot (`Application::CheckNewVersion`,
`main/application.cc:373`), which is what the docs' "restarting the
device teaches it" rests on. What a board actually sends could differ
from its source only through a custom build, which vinga does not
ship.

### Deviations from the plan

1. **The board crosses as a seventh `RuntimeFactory` argument.** The
   plan names `device/session.py` and `runtime/pipeline.py` but not
   `device/boundary.py`, whose factory type is the only way the
   session's read reaches the runtime; the record crosses there for the
   same reason. The alternative, the factory closing over
   `DeviceFacts` and reading by MAC, would have left the session out
   and made two readers of one object.
2. **The runtime maps the type at construction, for every agent**,
   rather than when the built-in first speaks: keeping the raw type
   until then would hold an untrusted string in the runtime's state,
   which the sentinel test forbids. The cost is one cached dictionary
   lookup per session; the pages are read once per process.
3. **D3's "a lookup away" is deferred to M5.** D3 has the vague text
   send the answer to the common page, a lookup away; until M5 there is
   no lookup, so after the PR review round the text has the model
   decline what it does not know and point to the guide for the board,
   naming where the guides are without claiming to read them
   (`16e83a46`). M5 is where the common page becomes reachable and the
   text can say so.

No other deviation.

### Resolutions

- **What the prompt preview shows for vinga.** `app._prompt_preview`
  renders "a fresh session with no device", so it carries no board
  text, vague or otherwise, as it carries no device record. Unchanged
  by M4; the preview's description already says it.
- **No heading over the facts.** The facts are the guide's own text,
  opening with its `# ` title, so the model reads which board they are
  about; the vague text says so itself. The persona tells the model
  where they are.
- **The facts follow the agent speaking, not the session.** Decided
  off the prompt snapshot's key (`builtin`), so a handover to vinga
  reads them in and one away reads them out, with no second clock.
- **The capture manifest and the pending table keep the reported type**,
  as they did: see Discoveries.

### Discoveries

1. **Two more pre-existing surfaces carry the reported type** beyond the
   two the plan names (`ota_check.board` and `ota_check_body`): the
   capture manifest's `device.board`, written beside the audio when
   capture is on (`DeviceSession._manifest`), and the pending table's
   bounded `board`, which `vinga device pending list` and its API route
   show (`onboarding/pending.py`, `_fact`). M4 changes neither and adds
   no new one. The sentinel test's state walk skips `DeviceFacts`, the
   in-memory holder the endpoint writes and the manifest reads, and
   names why.
2. **A state walk reaches the log.** The first draft of the sentinel's
   state walk found it in the session's state, through the session's
   logger, its handlers and the capture handler's records. The walk now
   skips the logging machinery, since the log records are hunted
   separately with their two pinned exceptions, and asserts it reached
   the runtime's own board text, so a walk that stopped short fails
   rather than passes.
3. **The browser guide's lead is part of the browser's facts**, so the
   sentence M4 adds there (vinga knows it is a browser) is also in what
   vinga is told: 2,808 characters, within the 3,500 budget.

### Tests first, and the mutations

The assembler tests and the persona pin were written before or
alongside the code they drive, and the persona pin failed against M3's
wording before the persona moved. Every mutation below was applied
once, run, and restored by copy and `touch`; the logs are
`.logs/m4-mutations-prompt.log` and `.logs/m4-mutations-session.log`.

| Mutation | Killed by |
| --- | --- |
| **Plan target:** mapping only one LCD spelling (the vendor-stripped spelling dropped in `knowledge/boards.py`) | the three `test_vinga_is_told_the_facts_of_the_board_it_speaks_through` cases, three `test_a_waveshare_board_is_reached_with_or_without_the_vendor` cases, `test_a_reported_type_is_casefolded_and_stripped` |
| **Plan target:** interpolating the reported type (appended to the facts in the runtime) | `test_the_facts_sit_in_the_device_block_after_its_introduction`, `test_a_reported_board_type_reaches_no_surface_this_feeds` |
| The facts handed to every agent | `test_an_operator_agent_on_a_reporting_board_is_told_nothing_of_it`, `test_a_handover_to_vinga_brings_the_facts_and_one_away_takes_them`, both cases of the operator byte pin, and eleven other `test_session_prompt.py` cases |
| The facts handed to no agent | twelve `test_session_builtin_board.py` cases |
| The runtime keeping the reported string beside the text | `test_a_reported_board_type_reaches_no_surface_this_feeds` |
| The session handing None | `test_the_factory_is_handed_the_board_type_the_device_checked_in_with[True]` |
| The session handing the firmware instead of the board | the same |
| The board dropped from the device block | `test_the_board_s_facts_sit_between_the_introduction_and_the_notes`, `test_the_board_s_facts_reach_a_prompt_with_memory_off_and_no_record` |
| The board placed after the notes | `test_the_board_s_facts_sit_between_the_introduction_and_the_notes` |
| The board passed only when memory is on | `test_the_board_s_facts_reach_a_prompt_with_memory_off_and_no_record` |

No survivor. One observation: the interpolation mutation leaves the
vague-text cases green, since they assert the fixed text is present
rather than that nothing else is; the sentinel test is what holds the
"never the reported string" half, and it caught it.

### Verification

All on the Raspberry Pi 5, logs in this worktree's `.logs/`, both lanes
with `-n auto --dist loadfile`. M6's implementer was running lanes on
the same machine against the same Postgres for part of this, so the
timings are not idle timings; neither lane errored in setup.

- `uv run ruff check .`: all checks passed.
- Unit lane (`.logs/m4-unit-1.log`): `8614 passed, 19 skipped in
  1216.97s (0:20:16)`, first run.
- Integration lane (`.logs/m4-integration-1.log`): `363 passed in
  337.62s (0:05:37)`, first run.
- The drift checks (`.logs/m4-drift.log`), scripted from the workflow's
  steps: domain and server references, conversations schema, metrics
  views, events, OpenAPI, the CLI reference and its recipes, all
  current.
- `scripts/check_doc_links.py .`: `checked 337 files, 0 failures`;
  `scripts/check_run_use_pages.py .`: `checked 37 Run and Use pages, 0
  findings`; `scripts/fold_changelog.py check .`: `checked 1 fragments,
  0 failures`.
- `tests/census`: run last, after this section was committed, and
  reported in the hand-back.

Not verified: **the board string off a real ESP32-S3-Touch-LCD-1.54**
(no board on this machine; derived from source above); vinga answering
a device question by voice on a board, or with a real model (only the
mock model and the recorded prompt); the image and the smoke lane; the
browser lane, since nothing it drives changed beyond the browser
guide's lead, which no browser-lane case reads.

### PR review round

Reviewed 2026-10-09 by openai/gpt-6.1-sol, thinking high via codex CLI 0.162.0, read-only sandbox, runtime 3m34s, at commit d81f91df ([the round](https://github.com/rafacm/vinga/pull/635)). The fixes are by anthropic/claude-opus-5-5, thinking medium, M4's own implementer.

1. **P2: the unknown-board documentation promised a page vinga cannot
   read.** The device page and the fragment said vinga answers device
   questions from the common device page, but this branch sends only
   the vague text, which names that page without carrying it, and no
   lookup is offered until M5. *Resolution:* the device page, concepts
   and the fragment say vinga declines rather than guessing and points
   to the guide for the board; the copy regenerated (`1d83505d`). The
   code half of the finding is `16e83a46`: the vague text itself told
   the model to answer from that page, and now has it decline and
   point to the guide.
2. **P2: the browser does not check in when the page loads.** The page
   checks in inside `start()` (`browser/static/page.js:120`), run when
   Start or Start again is clicked (`:211`), so "reload the page" did
   not teach the server. *Resolution:* verified against `page.js`; the
   device page, concepts and the fragment say the browser checks in
   when Start or Start again is pressed, and the recovery is to press
   it; the browser guide carried no timing; the copy regenerated
   (`b039e4c0`).
3. **P2: M4 ticked while the real-board read is undone.**
   *Resolution:* as the orchestrator resolved, M4 stays ticked and its
   checklist line now states that the string was derived from the
   firmware source (`config.json:3`) and that the read off a real
   ESP32-S3-Touch-LCD-1.54 is still owed (`c1f05c52`).

Verification after the round: the link, Run and Use page and fragment
checks, and `tests/census` last, in the hand-back.
