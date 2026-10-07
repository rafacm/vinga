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
