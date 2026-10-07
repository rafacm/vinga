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
