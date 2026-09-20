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

`git grep -n "command-spellings census"` over the whole tree, read in
full rather than through `head`, and split as the plan's finding 5
requires. **The load-bearing claim is the live-page half**, and it is
stated first because it is the half that can be checked and stays
checked. The total is not, and the reason is worth stating rather than
rounding away.

**Live pages: three hits, each named, all three correct.** Two were
written in this milestone and name the specific census inside the
now-named lane: `AGENTS.md:67` and `.github/workflows/docs.yml:8`. The
third, `docs/architecture/cli-guide.md:690`, says a word is "inside the
command-spellings census's reach", a claim about that census in
particular, and it stays singular on purpose. That enumeration is the
complete live set: after the edits, `.claude/skills/implement-issue/SKILL.md`
and `.github/workflows/vinga-server.yml` carry no hit at all, so no
live page still calls the lane one census. This is the claim the sweep
exists to make, and it is falsifiable by re-running the grep and
checking that nothing outside `docs/plans/`, `docs/features/` and
`CHANGELOG.md` appears that is not one of those three.

**Dated execution records: 46 hits as of `c2e291af`**, in the plans,
their implementation companions, `docs/features/` and `CHANGELOG.md`.
The authority taxonomy says they report what was true when they were
written, so not one of them was touched. Six are in this milestone's own
plan and three in this document.

That total is quoted as a reading of one commit rather than as a state,
because **it moves whenever any record mentions the census, this
document included**. The first version of this section said 46 total
and 43 dated, which was true when it was written and false by the time
it was committed: writing the sentence added three matches to the tree
it was counting. Recording a new total here would falsify itself the
same way the moment the review-round section below quotes the phrase
again. A number that cannot be stated stably is stated with its
instability, and the claim that is actually load-bearing, the live-page
classification above, does not depend on it.

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

## PR review round

External adversarial review of PR #540's diff (`main...89f6347a`),
backend codex CLI 0.155.0, model `gpt-5.6-sol`, read-only sandbox,
2026-09-20, runtime 8m18s, posted as
[a comment on the PR](https://github.com/rafacm/vinga/pull/540#issuecomment-5752531430).
Five findings: one P1, three P2, one P3. Verdict: mergeable after the
listed fixes. Four accepted whole, one accepted in half with the other
half rejected and its reasons recorded here.

**1 (P1): the refusal answered with a traceback.** *Accepted in half.*
The facts are right: `tracked` embedded the root in a bare `ValueError`,
`main` left it uncaught, and the census-level test pinned the message
through `match=str(outside)` without ever exercising the command
boundary. So a hand-run `--root /somewhere-else` answered with the frames
of the subprocess call that found out, where the reader wanted the
reason.

*Resolution* (`20947fd6`): the refusal is `Unwalkable`, a `ValueError`
subclass, so `main` can catch this one thing rather than every
`ValueError` the tokenizer might raise on the way; `main` writes the
sentence to stderr and returns 2, argparse's own code for an argument it
will not accept. `test_the_command_refuses_an_unwalkable_root_with_one_sentence`
drives `main` and asserts the nonzero return, the single stderr line,
the empty stdout and the absence of `Traceback`. Watched failing twice:
leaving the refusal uncaught turns it red, and building the refusal
without the root turns it and the census-level test red.

*The sanitization half is rejected, with reasons.* The finding asks for
the path to be removed from the message. This repository's no-leak
contract governs secrets, far-side output and untrusted bytes reaching a
retained surface. The value here is none of those: it is the argument
the developer typed as `--root` on their own command line, in an
instrument under `tests/` that never runs in the server's request path
and reaches no log, no event, no API body and no record, so echoing it
back discloses nothing the reader does not already hold. Naming the root
is also a settled decision of the plan, taken so the refusal cannot read
as a clean tree, and the review offers no security gain to trade against
it. The class docstring states the reasoning where the decision lives.

**2 (P2): every filesystem error was treated as a deleted file.**
*Accepted.* `except OSError` is wider than the settled behavior, which
permits skipping only a tracked path git lists and the working tree does
not have. A permission error or an I/O fault silently removed that
file's reach-ins, which falsifies the manifest header's claim to count
every one of them while rendering a green run, and the deletion test
could not tell the two apart.

*Resolution* (`7081fcfd`): `FileNotFoundError` and nothing wider; every
other read failure propagates. An absent file is the one case where the
census has nothing to count, and the rest are cases where it could not
look. `test_a_tracked_file_that_cannot_be_read_does_not_vanish`
monkeypatches `read_text` rather than arranging a mode of 000, because a
process running as root ignores the mode and the test would pass for the
wrong reason in a container lane; the docstring says so. Watched
failing: restoring the broad catch turns the new test red while the
tracked-but-deleted case stays green, which is exactly the distinction
the finding said was missing.

**3 (P2): the nested-root test passed against the fault it was written
to catch.** *Accepted, and this is the finding worth keeping.* The test
asserted substring membership on the whole render, and every nested
spelling is a substring of the spelling the root above it renders, so
`unit/test_config_cli_rendering.py` sits inside the default root's own
line `tests/unit/test_config_cli_rendering.py  _x  1`. Reproduced
before fixing rather than taken on trust: a `walk` that ignores its root
argument and always reads the whole suite went **2 passed** against both
parametrizations.

*Resolution* (`a077e65a`): `rendered_paths` parses the render's path
column, the expected spelling is compared exactly, and every row of a
root's render must sit inside that root's own subtree, which also rules
out a render that carries the right row among rows from elsewhere.
Watched failing in both directions: hard-coding the full suite turns the
nested-root case red, hard-coding `tests/unit` turns the default-root
case red, and each parametrization now fails for its own fault and no
other.

**4 (P2): the recorded sweep total was already false.** *Accepted, as a
shape change rather than a new number.* The section recorded 46 hits at
a tree that held 49, because writing the sentence added three matches to
what it was counting. Re-running and recording 49 would have been false
again the moment this section quoted the phrase, which it now does
several times.

*Resolution* (`0d6b0edc`): the live-page classification is stated first
as the checked claim, with each of the three hits named, the two live
pages that now carry none named beside them, and the way to falsify it
written down; the dated-record total is quoted as a reading of one named
commit with the reason it cannot be a state. The reviewer's own remedy,
re-running after the final documentation edits, cannot terminate in a
document that is itself part of the corpus being counted, which is why
the disposition diverges from the fix as written while accepting the
finding behind it.

**5 (P3): the lane's own conftest still described one census.**
*Accepted.* `tests/census/conftest.py` said the lane "reads every
tracked file and compares the command spellings" and called that census
"a job whose only test", both false since the reach-in manifest landed
beside it, and this file is where a reader arriving at a lane failure
looks first.

*Resolution* (`c2e291af`): it names both censuses with their manifests,
states the one property they share (neither opens a store) against the
reach that differs (every tracked file for spellings, the tracked Python
under `tests/` for reach-ins), and keeps the #489 history and the reason
the lane exists, with one sentence on why the second census was placed
here and needed no workflow edit.
