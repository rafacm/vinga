# The reach-in census becomes a manifest: implementation

Companion to
[`2026-09-20-reach-in-manifest.md`](2026-09-20-reach-in-manifest.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the reach-in census becomes a manifest

### What landed

| Piece | Where |
| --- | --- |
| The tracked-file enumeration | `vinga-server/tests/tools/reach_ins.py`: `tracked`, and `walk` reading from it |
| The rendering | the same file: `MANIFEST_HEADER` and `manifest_of` |
| The manifest | `vinga-server/tests/census/reach-ins.txt`, 183 pairs carrying 355 sites |
| The drift test, the pins and the regeneration entry | `vinga-server/tests/census/test_reach_ins.py`, twelve tests |
| The lane is two censuses, not one | `AGENTS.md` (the workflow paragraph and the rebase section), `.github/workflows/docs.yml` and `.github/workflows/vinga-server.yml` (each file's header, the comment block above the step, and the step name), `.claude/skills/implement-issue/SKILL.md` (the subagent brief and the CI-shapes paragraph) |
| The rule points at its enforcement | `docs/architecture/design-guide.md`, "The interface is the test surface" |
| The changelog fragment | `changelog.d/531-reach-in-manifest.md`, `### Added` |

### No deviations from the plan

Every part the plan specified landed as specified. The numbers it
predicted are the numbers the manifest carries: 183 distinct
`(path, name)` pairs, 355 sites, 118 names, 75 files, 425 `self`/`cls`
accesses excluded. The one place a deviation was plausible is the shape
of the four tracked-file tests, and it is recorded below as a choice
rather than as a departure.

### The enumeration swap was checked for identity, not for plausibility

The plan's claim that only the enumeration moves is the kind of claim
that is easy to assert and cheap to check, so it was checked: the full
`--json` census was rendered with the committed `rglob` walk and with
the tracked-file walk and the two files diffed. Byte-identical. That is
the whole of the evidence that `relative_to(root.parent)`, the `*.py`
filter and the site ordering are untouched, and it is stronger than any
test in the lane, because it compares every one of the 355 sites rather
than a sample of them.

`--root tests/unit` still renders `unit/test_config_cli_rendering.py`,
and `--root /tmp` now raises `ValueError: not a directory of the
checkout: /tmp` where it used to report a clean tree.

### The file-set tests use a throwaway checkout, and why

The plan asks for four tracked-file cases and a tracked-but-deleted
one. Two of them, the default root and a nested root, have to run
against the real tree, because what they pin is the rendering this
repository's own manifest depends on; they are one parametrized test
that renders each root from `vinga-server/` and again from a temporary
working directory and asserts the two renders are equal, which is the
`git -C` property stated as an equality rather than as a path spelling.

The other three cannot run against the real tree honestly. An untracked
file under `tests/`, and a tracked file removed from disk, are states a
test would have to create inside the suite it is measuring, racing the
drift test in the same lane. So they run against a throwaway checkout
in `tmp_path`: `git init`, write the files, `git add`. No commit is
needed, because `git ls-files` reads the index. The mechanism under test
is exactly the one the real tree exercises, and the mutation results
below show the tests are not weaker for it.

### Falsification

Each claim was watched red before it was made, and the tree watched
green again after every restore. Seven mutations, all of them reverted:

| Mutation | What went red |
| --- | --- |
| A count hand-edited in `reach-ins.txt` | `test_the_manifest_is_the_census` |
| A count-free render, the `command-spellings.txt` shape | seven tests, including `test_a_site_leaving_a_pair_another_site_keeps_moves_the_line` and the drift test |
| The old `sorted(root.rglob("*.py"))` walk | `test_an_untracked_file_does_not_change_the_render` and `test_a_root_outside_the_checkout_is_refused_by_its_name` |
| `read_text` without the `OSError` skip | `test_a_tracked_path_that_is_not_on_disk_is_skipped` |
| An ambient `git ls-files -- <root>` in place of `git -C <root> ls-files` | both parametrizations of `test_a_root_renders_the_paths_it_always_has_from_anywhere` |
| The line number folded into the manifest key | `test_a_site_moving_within_its_file_moves_nothing` |
| The `self`/`cls` exclusion removed | `test_the_receivers_the_census_excludes_stay_out_of_the_manifest` |

No mutation survived its test. The third one is worth reading twice: it
went red for the untracked-file case and for the out-of-checkout
refusal, which is the pair of properties the enumeration swap exists
for, and it is the reason the untracked-file test is a claim rather
than a restatement of what the code already did.

The second one is the milestone's design claim under test. A count-free
render is the shape the precedent uses and the shape the plan measured
as catching 17 of 28 rather than 28 of 28, and it takes seven tests
down here, so the count column is held by the suite rather than only by
the plan.

### The documentation sweep, read in full

`git grep -n "command-spellings census"` after the edits: 46 hits, read
in full rather than through `head`, and split as the plan's finding 5
requires.

Three are on live pages and all three are correct. Two were written in
this milestone and name the specific census inside the now-named lane,
in `AGENTS.md` and in `.github/workflows/docs.yml`. The third,
`docs/architecture/cli-guide.md:690`, says a word is "inside the
command-spellings census's reach", which is a claim about that census in
particular and stays singular on purpose.

The other 43 are dated execution records: the plans, their
implementation companions, `docs/features/` and `CHANGELOG.md`. The
authority taxonomy says they report what was true when they were
written, so none of them was touched. Nine of the 43 are in this
milestone's own plan, which describes the state the edits changed and is
a record of it.

No live page still calls the lane one census: after the edits,
`.claude/skills/implement-issue/SKILL.md` and
`.github/workflows/vinga-server.yml` carry no hit at all.

### Verification

- `uv run ruff check .`: all checks passed.
- `uv run pytest tests/census -q`: 64 passed, which is the spellings
  census's 52 and the reach-in census's 12.
- `uv run pytest tests/unit -q`: 7,391 passed, 19 skipped, in 712 s.
- `uv run pytest tests/integration -q`: 346 passed, in 332 s.
- `uv run python scripts/check_doc_links.py .`: 255 files, 0 failures,
  which is 254 plus this document.
- `uv run python scripts/fold_changelog.py check .`: 1 fragment, 0
  failures.
- The command-spellings census was run after the documentation edits and
  was already current: no spelling a document quotes moved, so its
  manifest needed no regeneration.

The one thing not verifiable here is the plan's fourth risk. The
manifest was generated on darwin, and the first CI run on Linux against
it is the real test of cross-platform agreement; the sort is on `str`,
which is codepoint order and locale-independent, so the expectation is
that it agrees, but the expectation is not the evidence.
