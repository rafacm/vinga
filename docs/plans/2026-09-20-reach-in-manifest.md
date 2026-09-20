# The reach-in census becomes a manifest

Plan for [#531](https://github.com/rafacm/vinga/issues/531), M1 only.
Its companion is
`docs/plans/2026-09-20-reach-in-manifest-implementation.md`, one
section per milestone, appended in the same change that ticks the
milestone.

**Scope.** M1 alone. M2 (the duplicated helpers go home to
`tests/support`) is independent of everything and is not queued. M3
(the re-sweep) is gated on #482 and #488 M1, whose extractions are
expected to retire a large share of it, and the issue declines to
estimate it before they land. Neither is touched here.

**Local baseline:** not applicable. Nothing here changes a
conversational capability. The whole change is a generated artifact
under `tests/` and the test that diffs it; a deployment reaches none
of it.

**Cheapest alternative:** a single-number ceiling assertion,
`assert sites() <= 355`, about ten lines and no committed artifact. It
was measured against the manifest over 400 revisions of `tests/` and
**catches every change the manifest catches**, so this plan does not
claim the manifest catches more. What the manifest buys is that the
change arrives under a name: a ceiling's diff reads `355 -> 356` and
the reviewer has to run the tool to find out what landed, which is the
review moment #531 exists to create. The measurement, including the
blind spot the ceiling turned out not to have, is the section below.

## The measurement this plan starts from

Taken 2026-09-20 on `a7a2d545`, with one instrument across all of
history: today's `tests/tools/reach_ins.py` read every revision of
`tests/*.py` straight out of the git objects, so no result depends on
what the tool looked like at the time.

**Today's census.** 355 reach-in sites over 118 names across 75 files,
with 425 `self`/`cls` accesses excluded. Those 355 sites occupy **183
distinct `(path, name)` pairs**; 73 pairs carry more than one site and
cover 245 of them. So **172 of the 355 sites, 48%, share a pair with
another site.**

**Three candidate shapes, over 400 revisions that touch `tests/`**
(399 consecutive comparisons; the census went 295 sites to 355 across
them, and 371 comparisons show no census change at all, so 28 are
changes at all):

| Shape | Catches | Cost |
| --- | ---: | --- |
| Single-number ceiling | **28 / 28** | ten lines, one number |
| Manifest of `path  name  count` | **28 / 28** | render, drift test, 183-line artifact, regeneration discipline |
| Manifest of `path  name`, the `command-spellings.txt` shape | **17 / 28** | the same as above |

Three things follow, and the first two are the reason this plan is not
the issue as filed.

**The count-free shape is refuted, so this manifest diverges from its
own precedent.** `command-spellings.txt` deliberately records the
distinct set of `class  invocation` pairs and nothing else, and
`test_a_site_leaving_a_pair_another_site_keeps_moves_nothing` pins
that blind spot as accepted. Copying it here would miss 11 of the 28
observed changes, because a second reach-in for a name a file already
reaches for is the common case rather than the rare one: 48% of
current sites are exactly that. The divergence is one column, it costs
no positions, and without it M1 would be the weakest of the three
shapes while looking like the safest.

**The ceiling has no blind spot to point at.** The obvious argument for
a manifest is the one-in-one-out swap, where a site is added and
another removed and the total does not move. There were **zero** such
revisions in 400. The argument is sound in principle and was worth
nothing in three months of practice, and this plan says so rather than
quoting it as a benefit.

**So the manifest is justified by naming, not by catching.** #531's
own sentence is that the next reach-in should arrive "as a diff line
with a justification beside it". A number that goes from 355 to 356 is
a diff line, but it names nothing, and the reviewer who wants to know
what arrived has to run the tool and compare by hand, which is the
step nobody took for the +119% the issue documents. A manifest line
reading `tests/unit/test_x.py  _foo  1` is the review moment itself.
There is no cheaper shape that names what changed; that is the whole
of what this milestone buys, and it is bought at one generated file.

**Churn, since a committed artifact invites the question.** The
manifest would have moved on 28 of 399 test-touching comparisons, 7%.
It records no positions, so it is untouched by a line shift anywhere in
the tree.

## What is settled and not re-litigated

From the issue:

- **M1 freezes, it does not reduce.** The manifest lands at whatever
  the census reports when it merges, and this milestone claims no
  reduction at all. Reduction is M3's, after #482 and #488 M1.
- **The manifest records no positions.** A change that only moves a
  line leaves it alone, so it moves when the set moves and git merges
  it cleanly. The rule from `command-spellings.txt` carries over
  unchanged; only the aggregation differs, and it differs by counts
  and not by positions.
- **Regenerating on a rebased tree rather than splicing a textual
  merge** is the rule, the same as for the spellings census.
- **The instrument is not the gap.** `tests/tools/reach_ins.py` stays
  the census. This milestone adds enforcement around it.

## Open questions, resolved

### Where the manifest lives

`vinga-server/tests/census/`, beside `command-spellings.txt`.

The lane exists for exactly this and says so in its own conftest: it
declares no storage, which is what let #489 take the Postgres service
out of `docs.yml`. `reach_ins.py` imports nothing but the standard
library, so it is an honest citizen of that lane. Both workflows
already run `uv run pytest tests/census -q`, so the manifest arrives
covered by CI on every change, documentation-only ones included,
**with no workflow edit at all**.

The alternative, `tests/unit/`, is where the spellings manifest used
to live and is where #489 moved it out of, for the reason that a test
opening no store should not sit in a lane that provisions one.
Putting a second such test back there would undo that decision four
days after it landed.

### What the manifest records

One line per distinct `(path, name)` pair, with the site count:

```
tests/unit/test_doctor.py  _checks  3
```

Sorted by path and then by name, explicitly, so the order is a
property of the manifest rather than of the walk that produced it.
Counts and not positions: a count moves only when the number of
reaches actually changes, and is unmoved by a reformat, an import
shuffle, or any edit above the site. The receiver (`session` in
`session._opened_at`) is deliberately **not** recorded: it is lexical
rather than semantic, the tool's own docstring says the census does
not resolve receivers, and including it would split one pair into
several whenever a test renamed a local.

### Whether the census is deterministic enough to diff

Yes, and it is made so rather than found so. Two full JSON runs are
byte-identical today. The manifest sorts explicitly, so it does not
inherit determinism from `rglob`, from `git ls-files` ordering, or
from `Counter.most_common`'s tie-breaking. Sorting is on `str`, which
is codepoint order and locale-independent.

### The file set: a latent trap fixed in passing

`walk()` enumerates with `Path.rglob`, where the spellings census uses
`git ls-files` precisely so "an untracked scratch file cannot change
the answer". The two sets are identical today, 302 files each, so this
is latent rather than live; but a drift test on an `rglob` walk turns
any untracked `tests/scratch.py` into a red run that blames the
manifest. The walk moves to `git ls-files -z -- <root>`, which from
`vinga-server/` renders paths exactly as the walk does today
(`tests/census/conftest.py`), verified against the current output.

### Whether the tool moves into the census lane

No. `tests/tools/reach_ins.py` stays where it is, and
`tests/census/test_reach_ins.py` imports it.

The module is quoted by path or by its `-m` invocation in five places
across four dated records: three times in the `#210` governance
implementation doc, once in the session-split implementation doc and
once in `CHANGELOG.md`. Those are dated execution records, which the
authority taxonomy says report what was true when they were written
and are not rewritten when the code moves on. Moving the module would
falsify records that may not be corrected into agreement with it, to
save nothing.

## Module layout, and what each part hides

**`tests/tools/reach_ins.py` deepens.** It gains `manifest_of(sites)`,
the rendering, and its walk moves to the tracked file set. The tool
owns its own census and how that census reads, so the drift test and
the regeneration entry point cannot disagree about the shape: two
structures that must agree are one structure with a bug pending, and
here they become one function two callers share.

**`tests/census/test_reach_ins.py` is new.** What its callers stop
having to know: where the manifest lives, and that a committed copy is
only trustworthy if something re-renders it. It holds
`test_the_manifest_is_the_census`, the aggregation tests that pin what
the shape keeps and what it throws away, and the `__main__`
regeneration entry that writes the file, so regenerating is
`uv run python -m tests.census.test_reach_ins` from `vinga-server/`,
the same spelling as the spellings census that AGENTS.md already
documents.

**`tests/census/reach-ins.txt` is new**, generated, with the header
saying what generates it, how to regenerate it and what it aggregates
away, in the shape `command-spellings.txt`'s header uses.

No new module is added beside an existing one to forward to it; the
deletion test is why the rendering goes in the tool rather than into a
third file between them.

## Tests

Reusing the spellings census's own test assets as the model, since
what is being built is the second instance of a pattern this
repository already has one of.

- **`test_the_manifest_is_the_census`**: the committed file equals a
  fresh render. This is the drift test and the milestone's point.
- **Aggregation, pinned both ways.** Two sites at one `(path, name)`
  pair are one line reading 2, and reversing the input renders
  byte-identically. One name reached in two files is two lines. A site
  moving within a file, which changes only its line, moves nothing.
  **A site leaving a pair another site keeps DOES move the line**,
  which is the one pin that states the divergence from
  `command-spellings.txt` as a deliberate property rather than an
  accident.
- **The excluded receivers stay excluded**: `self._x` and `cls._x` do
  not reach the manifest, which the tool already tests at the census
  level and the manifest must not undo.
- **The tracked-file switch**: an untracked file under `tests/` does
  not change the render. Written to fail first against the `rglob`
  walk, which is what makes it a claim rather than a restatement.
- **Determinism**: the render sorts, pinned by feeding shuffled input
  and comparing renders.

Falsification: each of these is written to break its claim and watched
failing before the claim is made, and the commit body says so. The
drift test in particular is watched failing against a hand-edited
manifest, since a drift test that has never been red is a drift test
nobody has checked. The count column is watched failing against a
count-free render, because that is the property the measurement above
bought and a test that passes either way would not hold it.

## Risks

- **The manifest lands stale between its render and the merge.** Any
  PR merging in between that adds or removes a reach-in makes the
  committed copy wrong, and CI says so. Mitigated by regenerating on
  the rebased tree immediately before merge, which is the standing
  rebase rule for the spellings manifest and now for this one.
- **A new conflict class on rebases.** The repository has one
  generated manifest today and its resolution rule is written down in
  AGENTS.md; a second doubles the surface. Mitigated by the shape:
  no positions, one line per pair, and a measured 7% of test-touching
  commits move it at all. The AGENTS.md rebase section is updated in
  this milestone to name both manifests rather than one.
- **The count column is read as a target.** The manifest freezes 355
  sites and claims no reduction, so a reader could take a green run as
  approval of the number. Mitigated in the manifest header and the
  module docstring, which state that the file records what is there
  and that the reduction is #531 M3's, after #482 and #488 M1.
- **The census disagrees with itself across platforms.** Not observed,
  and the sort makes it structural rather than incidental, but the
  first CI run on Linux against a manifest generated on darwin is the
  real test of it and is called out in the PR's verification.

## Documentation footprint

- **`AGENTS.md`**, guidelines class. Its rebase section names
  `vinga-server/tests/census/command-spellings.txt` as "the one that
  remains" and gives its regeneration command; with a second manifest
  in the lane that sentence is false. The workflow paragraph calls the
  lane's work "the command-spellings census" in the singular twice.
  Both are corrected here, in the same change.
- **`.github/workflows/docs.yml` and `.github/workflows/vinga-server.yml`**:
  the step is named "Command-spellings census" in both and runs the
  whole `tests/census` lane. The step name is corrected to name the
  lane rather than one of its two censuses. No `paths` or `run` line
  changes, which is the point of the placement decision.
- **`docs/architecture/design-guide.md`**, guidelines class, "The
  interface is the test surface". It states the rule the census
  measures and does not currently say that the rule is enforced. One
  sentence pointing at the manifest, since the guide is where a reader
  meets the rule.
- **No generated reference moves**, and nothing under `docs/reference/`
  is touched: this milestone changes no command, no config key and no
  event.
- **A `changelog.d/531-reach-in-manifest.md` fragment** under
  `### Added`.

The command-spellings census itself is run after the documentation
edits, since a documentation change can stale it.

## Milestones

- [ ] **M1: the reach-in census becomes a manifest.** `reach_ins.py`
  gains `manifest_of` and walks the tracked file set;
  `tests/census/test_reach_ins.py` holds the drift test, the
  aggregation pins and the regeneration entry;
  `tests/census/reach-ins.txt` is committed at whatever the census
  reports. AGENTS.md's rebase section and both workflow step names
  stop naming one census where there are two, and the design guide
  points at the enforcement. Freezes 355 sites over 118 names across
  75 files; reduces nothing.

M2 and M3 of #531 are out of this plan's scope, so #531 stays open
when this merges.

## Plan review round

Reviewed by codex `gpt-5.6-sol` (codex-cli 0.155.0, `--sandbox
read-only`) on 2026-09-20 against commit `3cae5dff`, the plan as first
committed. Runtime 15m45s, 175,742 tokens. The prompt reproduced the
measurement script in full and asked the reviewer to audit the method
rather than accept the numbers, and to argue for the ceiling as a P1 if
it disagreed with the choice the maintainer had already made.

Verdict as received: **ready after the P1/P2 amendments**. The
deletion-test lens found no pass-through module in the proposed layout;
the blockers were the measurement, the breadth of the evidence claims,
and omitted interface and documentation work.

### Finding 1 (P1): the load-bearing experiment does not model the proposed ceiling

The plan offers `assert sites() <= 355` as the cheapest alternative and
claims it catches 28 of 28, but the script defines `ceiling_sees = t1
!= t0`, which models an **exact-count pin against the immediately
preceding revision**, not a persistent `<=` ceiling. A real `<=`
ceiling accumulates headroom whenever the count falls, so it catches
fewer. The reviewer reproduced the raw counts (28 manifest changes, 25
rises, 3 falls, 11 count-only, 17 pair-set) and reported that a real
ceiling starting at 295 and raised only when it fails catches **22 of
28**, with an observed maximum of 361. Its recommendation: compare
against either the real ceiling, reporting its weaker coverage, or an
exact-count pin `assert sites() == 355`, which is the honest ten-line
alternative that does catch all 28. The manifest can still win, on
unnamed headroom, on naming the pair, and on net-zero detection, but
implementation should not begin while the central comparison is false.

### Finding 2 (P2): the sample supports a 14-day adjacent-commit claim, not "three months" or PR-level behavior

The 400 commits run from `3410ec0e` (2026-09-06) to `aa8ed3ba`
(2026-09-20), fourteen days rather than the three months the plan
claims, and the window begins **after** #210's reduction from 440 to
162, which is exactly where a ceiling would accumulate headroom. The
constant-total predicate itself is correct for adjacent commits. But
this repository rebase-merges and every milestone's intermediate
commits survive, while CI and review judge branch tips, so a separate
add commit and remove commit appear as a rise and a fall even when the
reviewed PR is net-zero: PR-level swaps are unmeasured. The 7% figure
is commit-level artifact churn and is not a measurement of
rebase-conflict probability.

### Finding 3 (P2): the 48% statistic is mislabeled and does not explain the 11-of-28 result

The arithmetic reproduces, but **245 sites (69%) share a pair with
another site**, while 172 (48%) is the count of occurrences *beyond the
first* of each pair. The plan says 48% "share a pair with another
site", which is the wrong statistic for that sentence. Separately, the
current-tree concentration and the 11 historical count-only transitions
are two different measurements and the plan uses them as if one
explained the other.

### Finding 4 (P2): the tracked-file change leaves `walk(root)` and `--root` undefined

`walk(root)` renders paths relative to `root.parent` and the CLI
publicly accepts an arbitrary `--root`. Replacing the enumeration with
`git ls-files -z -- <root>` specifies neither a stable git working
directory, nor `*.py` filtering, nor path normalization, nor the
behavior for a root outside the checkout. The single untracked-file
test would not preserve the existing interface. Wanted: the
repository-relative path calculation defined, the `*.py` restriction
and rendered paths retained, out-of-repository roots decided
explicitly, and tests that invoke the default root and a nested root
**from a different working directory**.

### Finding 5 (P2): the documentation footprint misses live workflow guidance

Beyond the pages the plan names, `.claude/skills/implement-issue/SKILL.md`
still tells a subagent that `tests/census` is the command-spellings
census and gives only its regeneration command, and both workflow files
describe the whole lane as that single census in the comments
immediately above the command that collects the directory. Renaming
only the step names leaves live operational guidance incomplete, and
the edits need a complete search for singular references afterwards.
