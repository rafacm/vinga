# Removing the two recurring rebase-conflict classes

Plan for [issue #467](https://github.com/rafacm/vinga/issues/467).
Companion implementation doc:
`2026-09-11-rebase-conflict-classes-implementation.md`, one section
per milestone, appended in the same change that ticks the milestone
checklist.

## Goal

Two files conflict on almost every stacked rebase in this repository,
and each has now caused a recorded loss: the command-spellings
manifest records line numbers, so any line shift anywhere restages
all 1,706 lines of it and a textual merge of two versions is a state
no generator produced; and the dated `CHANGELOG.md` section merges by
matching `###` headings, which silently dropped a merged milestone's
entry from `main` for five merges. This plan removes both conflict
classes rather than documenting their resolution better. The manifest
stops carrying positional data, so an ordinary line shift no longer
touches it; and a branch stops editing `CHANGELOG.md` at all, adding
a fragment file under `changelog.d/` instead, folded into the dated
section by a serialized step on `main` after the merge. A branch that
only ever adds a file cannot lose a sibling's entry, because it never
sees one.

## The issue's decisions, restated

- The existing 38 dated changelog sections are not converted.
  Fragments are for new entries; `CHANGELOG.md` keeps its history and
  grows. Round-tripping history through a generator would invite
  drift and would itself churn the manifest.
- `CHANGELOG.md` stays a committed, readable, hand-checkable file. It
  is appended to once per merge on a branch nobody else writes to,
  never regenerated wholesale.
- The branch side's whole contract is: add a file under
  `changelog.d/`, named for the issue and a slug, and never touch
  `CHANGELOG.md`.
- The fold runs on `main`, after a merge, because serialization is
  what a shared file needs and `main` already provides it.
- The census manifest either carries no positional data or is not
  committed; the issue calls dropping the positions the smallest
  change and probably the right one, and this plan takes it.
- Stacking tooling (item 3 of the issue) is explicitly not depended
  on and is not pursued here; the workflow's retargeting discipline
  already covers the third conflict row.
- Acceptance: a single-milestone change no longer conflicts with a
  sibling on `CHANGELOG.md`; a line shift no longer restages the
  census artifact; any remaining committed generated artifact fails
  loudly on a spliced resolution; AGENTS.md's
  regenerate-rather-than-merge rule points at what enforces it; and
  a merged PR's changelog entry cannot silently be missing from
  `main`.

## Open questions, resolved

### The manifest keeps neither positions nor counts

The issue sketches `class  spelling  count`. The count half is
dropped too, deliberately, because it fails the issue's own test: the
justification is that the manifest should change "only when a
spelling is added, removed or reclassified, which is rare", and a
count changes every time any document quotes an already-known
spelling one more time. Every changelog entry naming a command, and
every two branches each adding one, would bump adjacent counts and
conflict again, which is the churn the issue exists to remove. The
manifest becomes the distinct set of `class  invocation` pairs,
sorted by class then invocation, one line each, under the same
do-not-edit header. It changes exactly when a new spelling enters the
tree, an old one leaves it, or one moves class, and each such change
is one added or removed line that git merges cleanly.

What the manifest loses is per-site review granularity, and that loss
is priced rather than hidden: the census still computes every
`path:line` internally, every guard failure still reports offending
sites with their positions (`Spelling.rendered()` is unchanged as the
diagnostic rendering), and a reviewer who wants the sites for a pair
runs the module. The manifest's standing purpose, a reviewable record
of which spellings exist and what class each was given, survives in
full: a stale spelling entering a document still fails
`test_every_live_spelling_names_a_command_the_tree_has` with
positions in the failure, whether or not the manifest moved.

Not committing the manifest at all (the issue's second option) is
rejected because the committed set is what makes a classification
change reviewable: a document move that silently reclassifies a
live spelling as historical shows up as a diff line in the manifest
and nowhere else, since the guards only constrain the `respell`
class.

### The fold is a workflow, not a documented manual step

The issue's comment names this the real question: a workflow step
that commits to `main` is less forgettable, a manual step adds no bot
commits to a repository that currently has none. The plan takes the
workflow, for the reason the issue's own third comment supplies: the
failure mode being removed is silent loss that survived five merges,
two review rounds and a PR description, so the remedy must not
depend on the person doing the merge remembering a step. The recorded
history of this conflict class is precisely a record of disciplined
people forgetting under load. The costs are named and bounded:

- The bot commit is confined to one workflow
  (`.github/workflows/changelog-fold.yml`), triggered only by a push
  to `main` that touches `changelog.d/**`, writing only
  `CHANGELOG.md` and the fragment deletions, with
  `permissions: contents: write` and nothing else. Deleting the
  workflow reverts the repository to manual folding with the same
  script; nothing else depends on the automation.
- `main` has no branch protection (verified 2026-09-11 via the
  branches API), so the push succeeds; if protection ever arrives,
  the workflow fails loudly rather than folding half.
- A push made with the default `GITHUB_TOKEN` triggers no further
  workflow runs, so there is no fold-loop and also no CI run on the
  fold commit itself. The fold commit is therefore kept trivially
  verifiable by construction: the script moves fragment text
  verbatim, validates the resulting file structure before writing
  (heading order, no conflict markers, every fragment's entry
  present exactly once), and is unit-tested; and after milestone 1
  the fold cannot stale the census, because a fragment and the
  changelog line it becomes carry the same class and the same
  invocation set, so the distinct-pair manifest is unchanged by
  construction.
- Two merges landing close together serialize through the
  workflow-level `concurrency` group (no cancellation); a queued run
  that finds no fragments exits green without committing. The
  checkout uses `ref: main` rather than the triggering SHA, so a
  serialized run folds whatever is currently unfolded.
- The checkout uses `fetch-depth: 0`, stated in the workflow beside
  the reason: the date derivation walks first-parent history to the
  commit that introduced each fragment, a queued fold can meet
  fragments introduced several commits before current `main`, and
  actions/checkout's depth-one default cannot date those. The script
  does not trust the caller to have obeyed: a fragment whose
  introduction commit cannot be found in the available history is a
  fixed-message refusal (exit 1, nothing written), never a silent
  substitution of the workflow's own date, and the refusal is tested
  against a shallow clone of the constructed test repository.

### Fragment format

One file per change, `changelog.d/<issue>-<slug>.md` (the PR number
where no issue exists), containing one or more `### <Class>`
headings from the closed Keep a Changelog six (Added, Changed,
Deprecated, Removed, Fixed, Security), each followed by the entry
text exactly as it should appear in `CHANGELOG.md`: the same list
items, the same bolding conventions, no date header, no `##`
heading. The fold moves the text verbatim, so the fragment is
written in final form and reviewed in final form on the PR, which is
where the entry's own review already happens today. A
`changelog.d/README.md` states the format and is excluded from
folding by name. Towncrier itself is not adopted: its model is
versioned releases and its features (types, per-type templates,
rendering) would all be configured away to reach the dated-section
format; a stdlib script matching `scripts/check_doc_links.py` and
`scripts/upstream_watch.py` in style is smaller than the
configuration would be.

### Which dated section a fragment folds into

The fragment's section date is the committer date of the commit that
brought the fragment onto `main` (first-parent), rendered in that
commit's own recorded offset, which for GitHub rebase merges is UTC.
This is deterministic (the offset is stored in the commit), needs no
midnight special case (a merge just before midnight and a fold just
after agree, because both read the merge commit), and answers the
recorded incident where a session running past midnight had to move
entries into a new section by hand: the section is derived from when
the change landed, not from when the fold ran. Within a section,
classes appear in Keep a Changelog order and entries within a class
in merge order, appended after any entries already folded that day.

### Enforcement, in three places

- **A PR cannot edit `CHANGELOG.md`.** A step in `docs.yml`, gated
  on `pull_request` events, fails when the PR diff touches
  `CHANGELOG.md`. `docs.yml` runs on every PR that touches the file,
  because `CHANGELOG.md` is not in its `paths-ignore` (which mirrors
  the server workflow's paths and gains nothing here). The failure
  message names the remedy: write `changelog.d/<issue>-<slug>.md`.
  The escape hatch for a genuine correction of history (the #450
  restoration is the recorded precedent) is the literal phrase
  `Corrects CHANGELOG history` in the PR body, read from the event
  payload; it is visible in review, and the check's message says so.
  Direct pushes to `main` (which AGENTS.md permits for
  documentation-only changes) are outside the check and outside the
  hazard: they serialize on `main`, so the conflict class this
  removes cannot occur there, and both spellings (a direct
  `CHANGELOG.md` edit, or a fragment the fold workflow then folds)
  remain valid for them.
- **A malformed fragment fails on the PR, not on `main`.** The same
  `docs.yml` job runs the fold script's check mode, which validates
  fragment filenames, headings against the closed six, non-empty
  bodies, and the absence of date headers, without writing anything.
- **A fold that did not run is loud.** The fold workflow runs on
  every push to `main` touching `changelog.d/**`; its failure is a
  red run on `main`. There is no window in which a fragment sits
  unfolded with all runs green except the minutes between merge and
  fold, and a fragment is a tracked file either way: unlike a
  dropped changelog entry, an unfolded fragment is visible in the
  tree, which is the issue's added acceptance criterion satisfied by
  design (a deleted file is a diff anyone can see).

### What already fails loudly, stated rather than re-built

The third acceptance box asks that a spliced resolution of any
remaining committed generated artifact fail loudly. It already does,
and the plan's work here is pointing at it rather than adding
machinery: every artifact under `docs/reference/` is
regenerated-and-diffed by the integration job's drift steps, and the
census manifest is regenerated-and-diffed by
`test_the_manifest_is_the_census` in both workflows, so any spliced
resolution that disagrees with a fresh render on the merged tree is
a red run. A splice that agrees with the fresh render is
indistinguishable from the correct resolution because it is one. The
`.gitattributes` merge-driver option is rejected as the issue
suggests: it is the most machinery for the least benefit and does
not help a web-UI resolution. AGENTS.md's
regenerate-rather-than-merge rule gains the pointer (fourth
acceptance box): the enforcement is the drift checks and the census,
named where the rule is stated.

## Module layout

- `vinga-server/tests/unit/test_command_spellings.py` (M1): the
  manifest rendering aggregates to distinct sorted `class
  invocation` pairs; the census, the guards, the regeneration entry
  point and the diagnostic rendering are unchanged. No new module;
  the change deepens the existing one by shrinking what the
  committed artifact makes callers (and rebasers) know: after it, a
  rebase never learns the manifest exists unless the set of
  spellings itself changed.
- `scripts/fold_changelog.py` (M2): stdlib only, two verbs. `fold`
  reads `changelog.d/`, derives each fragment's section date from
  git, merges entries into `CHANGELOG.md` in class order, deletes
  the fragments, and refuses (exit 1, nothing written) unless its
  own post-conditions hold: every fragment's entry present verbatim
  exactly once, no conflict markers anywhere in the file, the file
  outside the touched sections byte-identical, and the touched
  sections well-formed under the rules below. The post-conditions
  are deliberately not global, because settled history is not
  canonical (2026-09-10 orders Fixed before Changed; 2026-09-06
  carries two Added headings) and a global rule would either reject
  the repository or rewrite what the issue says stays. Legacy
  sections are parsed permissively and never validated, normalized
  or rewritten. A section the fold creates is canonical: one
  heading per class, Keep a Changelog order. A section the fold
  appends into is left as it stands, each entry appended after the
  last entry under the last heading matching its class, and a
  missing class heading inserted in Keep a Changelog order relative
  to the canonical classes present, whatever else the section
  holds; a fixture carries the repository's own duplicate-heading
  and out-of-order legacy shapes and proves them byte-preserved.
  `check` validates fragments without writing. The script inherits
  `check_doc_links.py`'s no-leak contract wholesale, because its
  inputs (fragment bodies and filenames, changelog content, git
  output) are repository-derived text landing in a public CI log:
  every diagnostic is a fixed sentence naming a path-free fact and
  a count, never reproducing fragment text, headings, filenames,
  git stderr, exception text or tracebacks; fragment paths that are
  symlinks or otherwise non-regular files are refused before any
  read; git runs as an argument-list subprocess with both streams
  captured and never re-emitted; and the subprocess suite plants a
  credential-shaped sentinel in a fragment body, a filename, and a
  constructed git failure, asserting its absence from stdout and
  stderr for every refusal family. What its callers stop having to know:
  the fold workflow and anyone folding by hand stop knowing Keep a
  Changelog ordering, section insertion, date derivation and the
  verbatim-move contract; they run one command and read its exit
  code. Deletion test: inlined into the workflow YAML it would be
  untestable and would exist twice (fold and check).
- `.github/workflows/changelog-fold.yml` (M2): checkout `main`,
  run `fold`, commit and push when the script wrote; concurrency
  group without cancellation; `permissions: contents: write`.
- `changelog.d/README.md` (M2): the fragment contract, stated where
  fragments live.
- `.github/workflows/docs.yml` (M2): the PR-gated CHANGELOG.md
  refusal step and the fragment `check` step.

## Tests

- **M1, manifest shape**: regenerate the committed manifest with the
  new rendering in the same change that lands it;
  `test_the_manifest_is_the_census` keeps holding committed bytes to
  a fresh render. New cases: the aggregation is order-independent
  (two files quoting one pair yield one line) and class-splitting (a
  pair quoted under two classes yields two lines). The existing
  guard, option-guard, exemption and classification cases all run
  on the live census and are untouched; the falsification runs the
  lenses ask for are stated per case in the commit that adds them.
- **M2, fold script** (subprocess suite beside
  `tests/unit/test_check_doc_links.py`, the #329 precedent): folding
  one fragment into an existing dated section, into a section that
  does not exist yet (created in date position), two fragments same
  day merging class lists in Keep a Changelog order and merge
  order, a multi-class fragment, verbatim preservation of entry
  bytes, idempotence (a second fold is a no-op exit 0), refusal
  cases each proven to write nothing (unknown heading, empty body,
  date header inside a fragment, an entry that would duplicate one
  already folded, conflict markers anywhere in the changelog), and
  `check` red and green. The date derivation is tested against a
  constructed git history in a temporary repository, not mocked.
- **M2, census**: `changelog.d/` joins `_HISTORICAL_PATHS`, with a
  case proving a fragment's quoted invocation classifies historical,
  and the neutrality property stated at the classification site: a
  fold moves text between two paths of the same class, so the
  distinct-pair manifest cannot change.
- **What CI cannot prove locally is exercised once, honestly**: the
  fold workflow's first live run is milestone 2's own changelog
  entry, written as the repository's first fragment; the PR states
  the box unchecked with the reason, and the fold run on `main`
  after the merge is linked from the implementation doc as the
  verification.

## Risks

- **The fold commit lands on `main` without a CI run** (the
  GITHUB_TOKEN non-triggering rule). Mitigated by construction, not
  hope: verbatim move, self-refusing post-conditions, unit-tested
  script, census-neutral after M1. Residual risk is a script bug
  class its own post-conditions cannot see, and the next PR's docs
  run still sweeps the file.
- **A bot commit on `main` is new for this repository.** Confined,
  reversible, and taken deliberately for the recorded silent-loss
  reason; the maintainer can revert to manual-fold-only by deleting
  one workflow file, and the plan review round is the place to veto
  it.
- **Concurrent folds racing a push.** Serialized by the concurrency
  group; a lost race fails the run loudly and the rerun folds
  cleanly because `fold` is idempotent over already-folded
  fragments.
- **The escape-hatch phrase could rot.** It is pinned by the check's
  own test naming it and by the failure message that quotes it.
- **This plan's own PRs ride the trains they are removing.** M1
  edits `CHANGELOG.md` directly (the last ordinary direct edit,
  before the check exists); M2 must not, and dogfoods the first
  fragment.

## Milestones

- [ ] **M1: the manifest stops recording positions.** The rendering
  aggregates to sorted distinct `class  invocation` pairs;
  regenerated manifest committed in the same change; module
  docstring and `MANIFEST_HEADER` updated; new aggregation cases;
  AGENTS.md's census descriptions (the line-number sentences in the
  rebase-traps section and the CI paragraph) corrected to the new
  shape. Design footprint: deepens the census module, no new seam.
  Documentation footprint: AGENTS.md; the module's own docstring;
  CHANGELOG.md, edited directly for the last time. Server-workflow
  CI (unit lane).
- [ ] **M2: changelog fragments and the fold on `main`.**
  `changelog.d/` with its README; `scripts/fold_changelog.py` with
  its subprocess suite; `changelog-fold.yml`; the two `docs.yml`
  steps (PR CHANGELOG.md refusal with the recorded escape phrase,
  fragment check); `changelog.d/` into `_HISTORICAL_PATHS`;
  AGENTS.md rewritten where it teaches the changelog conflict
  resolution (the recipe shrinks to: fragments cannot conflict;
  keep the marker-count habit for anything else) and where Writing
  conventions state how entries arrive; the implement-issue skill's
  brief bullet moves from "CHANGELOG.md date-based entries" to the
  fragment contract. Design footprint: one new script module (its
  depth sentence above), one workflow. Documentation footprint:
  AGENTS.md, `changelog.d/README.md`,
  `.claude/skills/implement-issue/SKILL.md`; its own changelog
  entry is the first fragment. Both workflows run (server paths via
  the census test change, docs paths via the workflow edits).

## Plan review round

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-11, runtime 4m02s, reviewing commit cdb51bcd.
Verdict as received: **ready after the P1/P2 amendments**. Findings
condensed but faithful; resolutions appended per amendment.

1. **P1: The fold workflow lacks the git history required to derive
   fragment dates.** The workflow says only "checkout `main`";
   existing workflows use actions/checkout's shallow default, and a
   queued fold can meet fragments introduced several commits before
   current `main`, which a depth-one checkout cannot date. The
   temporary-repository test would still pass. Require full history,
   test the insufficient-history failure, and refuse fixed-message
   rather than silently substituting the workflow date.

   *Resolution.* Adopted. The workflow section now requires
   `fetch-depth: 0` with the reason stated in the workflow, and the
   script refuses with a fixed message when a fragment's
   introduction commit is not in the available history, tested
   against a shallow clone of the constructed repository.

2. **P1: A global heading-order post-condition is incompatible with
   the preserved changelog.** Existing history is not canonical:
   2026-09-10 orders Fixed before Changed, and 2026-09-06 carries two
   Added headings. A global check must reject the repository or
   rewrite settled history. Parse legacy sections permissively and
   keep them byte-identical; normalize and check only sections the
   fold touches; add a fixture with the repository's own legacy
   shapes.

   *Resolution.* Adopted. The fold's post-conditions are scoped:
   legacy sections parse permissively and stay byte-identical,
   created sections are canonical, appended-into sections keep
   their standing shape with entries appended under the last
   matching heading, and the fixture carries the repository's own
   duplicate-heading and out-of-order shapes.

3. **P1: The new public-CI parser has no no-leak contract.**
   `check_doc_links.py` treats repository text as untrusted CI-log
   input with fixed diagnostics and a planted-sentinel suite; the
   fold script's inputs (fragment bodies, filenames, git failures,
   changelog content) get neither, and symlink or non-regular
   fragment paths are not rejected before reading. Require a fixed
   error vocabulary that reproduces none of them, symlink rejection,
   argument-list subprocesses with captured git diagnostics, and
   credential-sentinel assertions over both streams for every
   refusal family.

   *Resolution.* Adopted in full. The fold script's module entry
   now states the inherited contract: fixed path-free diagnostics,
   symlink and non-regular refusal before reading, captured git
   streams never re-emitted, and sentinel assertions over stdout
   and stderr planted in a body, a filename and a git failure.

4. **P2: The PR refusal escape hatch is not operationally complete
   or tested.** `docs.yml` uses the default `pull_request` activity
   types, so editing the body to add the advertised phrase starts no
   new check; the Risks section claims a test pins the phrase but
   the Tests section names none; and a git-based diff needs history
   the checkout does not supply. Specify the diff source and its
   requirements, test forbidden, allowed and null-body cases, and
   make body edits regenerate the check.

5. **P2: "Merge order" does not totally order fragments introduced
   by one commit.** Git trees encode no order between files sharing
   an introduction commit. Define introduction-commit order with a
   deterministic filename tie-breaker and test both cases.

6. **P2: The manifest's claimed reviewability exceeds what a
   distinct-set artifact provides.** Removing or reclassifying one
   occurrence produces no diff when another occurrence retains the
   old pair, and a new classification produces none when the pair
   already exists elsewhere. State that only pair-set membership
   changes remain reviewable, accept the invisible cases explicitly,
   and add a test demonstrating the lossy case.

7. **P2: The bot-commit workflow omits required commit and
   write-scope mechanics.** A fresh runner needs a git author, and
   nothing enforces the claimed path confinement. Name the fixed bot
   identity, stage only `CHANGELOG.md` and the validated fragment
   deletions, assert nothing else is dirty, and never use an
   unrestricted `git add -A`.

8. **P3: The promised post-merge verification record requires an
   unnamed follow-up change.** The first live fold cannot run until
   M2 merges, yet the implementation section and the milestone tick
   land together. Name the post-merge documentation update, who
   performs it, and how M2's record carries it.
