# Build each architecture once, publish the tested digests: implementation

Companion to
[`2026-09-21-build-once-publish-digests.md`](2026-09-21-build-once-publish-digests.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: build each architecture once, publish the tested digests

### What landed

| Piece | Where |
| --- | --- |
| The `arch` matrix dimension, four jobs | `.github/workflows/vinga-server.yml`, `image.strategy.matrix` |
| One build per job, the image exporter as its only output | the same job, `Build the ${{ matrix.arch }} image` |
| The pull-back and the local tag the smoke reads | `Pull the pushed image back` |
| The seam, one digest file per architecture | `Record the digest` and `Upload the digest`, artifact `digests-<variant>-<arch>` |
| Cache scope `variant-arch`, written once per scope | the build step's `cache-from`/`cache-to` |
| The nineteen `if: matrix.arch == 'amd64'` gates | the smoke steps, the database, the uv setup and the three cleanups |
| `needs: [unit, integration]` off the build | `image` has no `needs` |
| The publish, which builds nothing | the new `image-publish` job |
| The index check, in both modes | `Assemble the manifest, check it, and publish it` |
| The dated tag's seconds and the twelve-character revision | `The revision this build is` in both jobs, `DOCKER_METADATA_SHORT_SHA_LENGTH` and `type=raw` in `Tags` |
| The maintained pages | `vinga-server/README.md` (the `/healthz` equality paragraph, the variant table, "Pair the two variants"), `docs/deployment.md` ("Pin an immutable tag", the `.env` example), `AGENTS.md` (the CI summary's first half) |
| The tag scheme where a deployment meets it | `deploy/docker-compose.production.yml`, `deploy/k8s/deployment.yaml` |
| The changelog fragment | `changelog.d/490-build-once-publish-digests.md`, `### Changed` |

### Deviations from the plan

Five, none of which changes what the milestone does.

**A labels step joins the build job, which the plan does not mention.**
An OCI label lives in the image config, and the image config is written
by the build, so a manifest assembled afterwards cannot add one. Today
the labels reach the published image because `docker/metadata-action`
feeds the `Publish` step's `labels:`, and that step is gone. Without a
metadata step in the build job the published images would silently stop
carrying `org.opencontainers.image.source`, which is what ties the GHCR
package to this repository. So `image` gains a `Labels` step whose tags
are ignored and whose labels go to the build, which is the shape
`docker/build-push-action`'s own multi-platform recipe uses for exactly
this reason. The two metadata steps are not two structures that must
agree: they compute different outputs from the same GitHub context.

**`docker pull` needs `--platform`.** The plan writes the pull-back as
`docker pull "$IMAGE@$DIGEST"`. The index pushed by an arm64 build holds
one platform entry, and docker resolves an index against the host
platform unless told otherwise, so the arm64 job's pull would ask for a
`linux/amd64` entry that is not there. The step passes
`--platform "linux/${{ matrix.arch }}"`.

**QEMU is installed on the arm64 jobs alone**, `if: matrix.arch ==
'arm64'`, which is one gate the plan's count of nineteen does not
include. An amd64 build on an amd64 runner needs no binfmt handler, and
installing one unconditionally was free only while one job built both
architectures.

**`image-publish` sets up buildx**, although the plan describes it as
having no builder. `imagetools` is a registry client and the job passes
no context and configures no cache, so the description still holds;
the action is there because it is what the documented merge-job recipe
does, and a current buildx is what `imagetools create` is exercised
against.

**`image-publish` checks nothing out**, which the plan implies and does
not state, and that required a job-level
`defaults.run.working-directory: .`: the workflow-level default names
`vinga-server`, a directory a job without a checkout does not have.

### The documentation inventory was wider than the plan measured

The plan measured the footprint as nine literals in four files. Re-run
whole on the tree at `36db7378`, `git grep -n "sha-[0-9a-f]\{7\}"`
returns fourteen lines, of which five are the plan quoting itself. The
remaining eight are `vinga-server/README.md` (3),
`vinga-server/tests/unit/test_doctor.py` (2) and two dated feature docs
(3, in `2026-08-06-build-revision.md` and
`2026-08-06-slim-image-variant.md`). Eight rather than nine, in the same
four files, so the plan's inventory is one out and points at the right
places.

What it misses is a second class its grep could not see. The tag format
appears as a **scheme** rather than as a dated literal in two deployment
artifacts: `deploy/docker-compose.production.yml` says "Pin an
immutable tag: `YYYY-MM-DD-HHmm` or `sha-<revision>`" in a comment and
again inside the message a missing `VINGA_IMAGE` prints, and
`deploy/k8s/deployment.yaml` carries the same sentence. Both are
maintained operator-facing text, both are falsified by the seconds, and
both moved with the pages.

`vinga-server/tests/unit/test_doctor.py` keeps its seven characters
deliberately. Its two `sha-3f9362a` strings are a fixture for what a
**far-end** server's OTA description says, asserted nowhere by width,
and a far-end server may well be an older build whose tag was seven
characters. The feature docs keep theirs for the reason the plan gives:
they record what was true when they were written.

### The index check asserts the association, not a count

The plan's cut-back text asks for "both expected platforms present, and
an attestation manifest for each". Counting attestations would satisfy
the first half of that sentence and not the second, so the check reads
each attestation entry's `vnd.docker.reference.digest` and requires it
to name the platform manifest it belongs to. That is what round 1's
finding 6 asked for, minus the three assertions the scope reduction
cut.

It was exercised before it was believed, against three hand-built
indexes: the four-entry shape (two platform manifests, two attestations
naming them) passes; the same index with the attestations removed fails
naming both platforms; an index with one platform manifest and its
attestation fails naming the missing platform. Exit codes 0, 1, 1.

### What could not be verified here, and is not claimed

This is a workflow-only change, so most of it is only observable on a
runner.

- **Unverified: that the workflow runs at all.** `actionlint` and a
  YAML parse are the whole of what a checkout can say. No dispatch was
  triggered, because this milestone's branch cannot push.
- **Unverified: the push-by-digest exporter, the pull-back and the
  assembly.** The plan's own experiments against a throwaway registry
  are the evidence that the mechanism works; nothing in this milestone
  re-ran them, and the exact step sequence committed here has never
  executed.
- **Unverified: `docker tag "$IMAGE@$DIGEST" vinga-server:ci-<arch>`
  after a pull by digest.** It rests on docker recording the repo
  digest of a pulled image, which is ordinary behavior and was not
  demonstrated.
- **Unverified: the measurements M1 is supposed to report.** The plan
  requires the first main run's job durations and cache-export times
  against its projection table, and the arm64 build's cached-versus-
  executed comparison from the **second** push rather than the first,
  since the first runs against a cold scope key by construction. Both
  belong to a run that has not happened. They are M1's verification and
  this section is incomplete until they are recorded here, including
  the case where the numbers are worse and the `variant-arch` scopes
  merge back to one per variant.

### One thing to check before merging that the plan does not mention

The job's matrix names change, so its GitHub check names change with
them: `image (default)` and `image (slim)` become `image (default,
amd64)`, `image (default, arm64)`, `image (slim, amd64)` and `image
(slim, arm64)`, and `image-publish (default)` and `image-publish
(slim)` are new. If any of the old names is configured as a required
status check on `main`, that setting points at a job that will never
report again and would block every merge. Nothing in the repository
records what the branch protection requires, so this was not checked
from here.

### Measured on a runner: the projection held

Discharges the first of the two obligations above.
[Dispatch run 35697656584](https://github.com/rafacm/vinga/actions/runs/35697656584)
against this branch is green in every job, both `image-publish` jobs
included, so the whole structure has run: build once per architecture
with the image exporter alone, push by digest, pull back, smoke the
pulled bytes, assemble the manifest and check its topology. Only the
final tag push is unreached, being gated on a push to `main`.

| job | duration | started |
| --- | --- | --- |
| unit | 477s | +0s |
| integration | 200s | +0s |
| image (default, amd64) | 260s | +0s |
| image (default, arm64) | 281s | +2s |
| image (slim, amd64) | 181s | +0s |
| image (slim, arm64) | 183s | +0s |
| image-publish (default) | 19s | +480s |
| image-publish (slim) | 20s | +480s |
| **critical path** | **500s** | |

Against the plan's baseline, run `35617743274` on `main` at
`a81608d`: 1241s wall, of which the default variant's image job alone
was 781s. The plan projected "~500s" and the measured figure is 500s.
The publish is the sharpest number in it: **19s against the 359s
`Publish` step it replaces**, because it assembles a manifest rather
than building a third time.

Two things this run does not say, recorded so the numbers are not read
wider than they are.

**The cache was cold**, because the scope key changed from `<variant>`
to `<variant>-<arch>`, so the image jobs are at their pessimistic
worst here and a warm run should be faster. That is also why this run
cannot discharge the second obligation, the arm64 cached-versus-
executed comparison, which needs the second push after the merge.

**The critical path is now the unit lane**, 477s of the 500s, with
every image job finishing inside it. So the `variant-arch` scope
question is no longer a wall-clock question at all: even a large
regression in image build time would be invisible until it exceeded
the unit lane. The scopes stay split on the reasoning in the plan,
and the warm measurement is still worth recording, but it decides a
number nobody is waiting on any more. Anyone coming here to make CI
faster should read #489 and #537 rather than this milestone.

### The branch-protection question above, answered

`main` is **unprotected** and has no required status checks
(`repos/rafacm/vinga/branches/main` reports `"protected": false` with
an empty `required_status_checks.contexts`), so the matrix rename
breaks nothing. Recorded rather than deleted, because the question was
the right one to ask and the answer is a fact about this repository
that the next renaming change will want.

## M2: validation overlaps across main pushes; the moving tag is ordered by a check

### What landed

| Piece | Where |
| --- | --- |
| A group per push, and the pull request's cancelling group kept | `.github/workflows/vinga-server.yml`, the workflow-level `concurrency` block |
| The comment that claimed the opposite, rewritten around its counterexample | the block above it, L38-72 |
| The ordering check, which moves a moving tag only on positive knowledge | `image-publish`, the `Whether the moving tag may move` step |
| The checkout the check needs, and the fetch that refreshes it | `image-publish`, `actions/checkout@v7` with `fetch-depth: 0`, and `git fetch origin main` inside the check |
| The moving tag dropped from the tag list when the check says so | `Assemble the manifest, check it, and publish it`, the `tags=()` loop |
| The maintained pages | `vinga-server/README.md` (the moving-tag paragraph in "Choosing an image"), `docs/deployment.md` (the moving-pointer paragraph in "Choosing a tag") |
| The changelog fragment | `changelog.d/490-overlap-and-tag-order.md`, `### Fixed` |

No second job, no reconciler, no concurrency group on any publish job,
and nothing walks `main`'s history. The design that did all of that is
in the plan's review rounds, and was cut before this milestone started.

### Deviations from the plan

Three. Two are small; the third reverses a rule the plan states,
on the review evidence recorded below.

**The per-run group covers every event that is not a pull request,
not only a push.** The plan says "a pull request keeps
`${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress`,
and a push appends the run id". It says nothing about
`workflow_dispatch`, which shares the same group today and carries the
same defect: a second dispatch of one ref queues behind the first, and
a third replaces the queued one. The expression is written as "a pull
request keeps the group it had; everything else appends the run id",
which leaves the pull-request group byte-identical to the old one and
closes the dispatch case for free. Writing it as the plan's literal
two cases would have left a known displacement in the one event this
repository uses to gate a milestone before merging it.

**An unreadable answer leaves the moving tag alone, where the plan
says it should proceed.** The plan's rule is that "a moving tag that is
absent, or whose config carries no `VINGA_REVISION`, means there is
nothing to go backwards over: the run proceeds and says so". As first
implemented that was read one step wider, to every case the check
could not resolve, and the PR review round below showed the family it
lets in: a registry that fails to authorize, one that times out, a
response that does not parse, and a commit published after this run
checked out all look exactly like an absent tag, and every one of them
moved the tag backwards. The rule is now inverted. Only two outcomes
move a moving tag: the registry positively reporting it absent, and a
single resolvable revision this commit is newer than. The plan is
wrong on this point rather than under-specified, and the reason it is
wrong is that it priced the absent case and not the unreadable one.

**`image-publish` checks out after all**, which reverses M1's fifth
recorded deviation ("`image-publish` checks nothing out"). The
ordering check is an ancestry question and git is what answers it, so
the job takes `actions/checkout@v7` with `fetch-depth: 0`. The
job-level `defaults.run.working-directory: .` M1 added stays and is
still right, for a different reason than it was added for: the
workspace now exists, and every step in this job is a registry or git
operation at the repository root rather than a server one. Its comment
says that instead.

### The check was driven as logic, against this repository's commits

The check is shell with seven outcomes, so it was tested as shell
rather than read. The step's `run:` body is extracted from the
workflow by `yaml.safe_load`, so the thing under test is the committed
text and not a copy of it. `docker` is replaced on `PATH` by a stub
that prints an `imagetools inspect --format '{{json .Image}}'` payload,
or fails with a named registry message, for each case; `git` is the
real one, running in this worktree against real objects, with a second
stub on `PATH` for the two cases where the fetch has to fail.

The table below is the decision table after the review round, which
changed nine of these rows. Seventeen cases, all as designed:

| case | what the registry does | this run's commit | outcome |
| --- | --- | --- | --- |
| the tag is an ancestor | reports `HEAD~5` | `HEAD` | moves it |
| the tag is a descendant | reports `HEAD` | `HEAD~5` | leaves it |
| the tag is this same commit | reports `HEAD` | `HEAD` | leaves it |
| a sibling, neither ancestor nor descendant | reports a `commit-tree` child of `HEAD~3` | `HEAD` | moves it |
| a full 40-character revision | reports `HEAD~5` in full | `HEAD` | moves it |
| the tag does not exist | `ERROR: ...: not found` | `HEAD` | moves it |
| the manifest is unknown | `MANIFEST_UNKNOWN: manifest unknown` | `HEAD` | moves it |
| the token cannot authorize | `insufficient_scope: authorization failed` | `HEAD` | **leaves it**, warning |
| the registry times out | `context deadline exceeded` | `HEAD` | **leaves it**, warning |
| the pull is denied | `denied: denied` | `HEAD` | **leaves it**, warning |
| it fails saying nothing | exit 1, no output | `HEAD` | **leaves it**, warning |
| the response does not parse | `not json at all` | `HEAD` | **leaves it**, warning |
| the config carries no revision | a config without the variable | `HEAD` | **leaves it**, warning |
| the two platforms disagree | two different revisions | `HEAD` | **leaves it**, warning |
| the revision names no commit here | reports `deadbeefdeadbe` | `HEAD` | **leaves it**, warning |
| the fetch fails, revision resolvable | reports `HEAD~5` | `HEAD` | moves it, warning about the fetch |
| the fetch fails, revision unknown | reports `deadbeefdeadbe` | `HEAD` | leaves it, two warnings |

Three of those are worth naming. **The same commit leaves the tag
alone**, because `git merge-base --is-ancestor` is reflexive; the
outcome is a no-op either way, since the tag already names those
bytes. **A failed fetch is a warning rather than a verdict**: a
revision that still resolves is answerable whatever the fetch did, and
one that does not falls into the case below it, so the two fetch rows
differ only in what they were asked about. And **nothing the registry
returns is echoed in any of the seventeen**: the revision is matched
against hex, used, and never printed, and each sentence is fixed.

The tag-dropping loop in the assembly step was driven separately, with
`MOVE_MOVING` true, false and unset, for both variants. Unset behaves
as true, which only matters if the check step were ever skipped. The
slim variant is the case worth checking rather than the default one:
its moving tag `slim` is a substring of its own dated and `sha-` tags,
and the comparison is an equality on the whole tag rather than a
substring test, so only `ghcr.io/rafacm/vinga-server:slim` is dropped.

**Five mutations, all five killed**, each by a named row above:

| mutation | killed by |
| --- | --- |
| the ancestry arguments reversed | the ancestor and descendant rows both flip |
| the not-found match widened to `denied\|authoriz\|deadline` | the auth-failure and denied rows move the tag |
| `move` initialised to `true` | every warning row moves the tag |
| `sort -u` dropped | the ancestor row sees two identical lines, reads them as no single revision, and stops moving |
| the `git cat-file -e` guard dropped | the unknown-revision row moves the tag |

The last of those is the finding this round changed. Before the
rewrite, deleting that guard changed no decision at all, because
`merge-base` exits non-zero on an unknown revision and the old `elif`
read that as "not newer, so move"; the guard bought a sentence in the
log and nothing else, and the first version of this section recorded
it as a survivor. It is load-bearing now, and the reason is exactly
the review's: the two paths it separates used to have the same
outcome, and that shared outcome was the defect.

### What could not be verified here, and is not claimed

- **Unverified: that either change behaves on a runner.**
  `actionlint` and a YAML parse are the whole of what a checkout can
  say about a workflow. No dispatch was triggered from this branch.
- **Unverified, and unverifiable before a merge: the ordering check
  skipping a real moving tag.** The step is gated on a push to `main`,
  because that is the only event that moves a tag, so a dispatch run
  takes the dry path and never reaches it. The plan says this in its
  verification section and it is repeated here rather than left
  implied: the first push to `main` after this merges is the first
  execution of the step against a real registry, and the one thing
  that has never run is `imagetools inspect --format '{{json .Image}}'`
  against `ghcr.io/rafacm/vinga-server:latest` on a runner. The plan
  verified that format against the live tag at plan time, which is the
  evidence that it reports `VINGA_REVISION`; the stub above stands in
  for it here.
- **Unverified: that a burst behaves.** Displacement needs three runs,
  and what has to happen is that a newer commit becomes pending before
  an older commit becomes eligible. Nothing on a branch can produce
  that. The intended discharge is the plan's: merge M3 and a
  documentation commit in quick succession once this is on `main`, and
  check that all of the commits get their dated and `sha-` tags and
  that the moving tag ends at the newest of them.
- **Not claimed: that the moving tag is always at the newest commit.**
  The check is a read before a write with no lock behind it. Two
  publishes in the same instant can both see the old revision, so
  `latest` can sit a commit behind until the next push publishes. That
  residual is in the plan, and the two maintained pages say what the
  check does rather than promising a guarantee.
- **Unverified, and a named residual: the not-found match.** The one
  failure the check reads as an answer is a registry message matching
  `not found`, `manifest unknown` or `MANIFEST_UNKNOWN`. Those are
  what a stub produced here, not what GHCR was observed to say,
  because nothing in this milestone spoke to a registry. The match is
  narrow on purpose, so the failure direction is a tag left alone
  rather than a tag moved wrongly, and the residual is that a first
  publish into an empty package may need its moving tag created by
  hand. It announces itself: that path logs a warning either way.
  Both moving tags exist today, so this cannot be reached by the next
  push.

## PR review round, M2 (PR #545)

External review of the PR diff, relayed here rather than fetched: this
session has no `gh`, so the findings below are recorded from the text
of [the review comment](https://github.com/rafacm/vinga/pull/545#issuecomment-5772751527)
as it was passed on, and the backend and model are not recorded
because they did not reach this worktree. Verdict as received: **not
mergeable**. Six findings, four P1. Five accepted, one refuted with
evidence.

Two of them are worth reading before the list, because they are the
round's real result. The first falsified a sentence in my own
milestone report, which is the kind of claim this repository has a
standing note about. The second and third are one defect wearing two
symptoms, and what they broke is not the mechanism but the rule
underneath it: the check asked whether it had a reason to refuse,
when what it needed was a reason to proceed.

### 1 (P1): the concurrency expression falls through on a pull request

`${{ github.workflow }}-${{ github.ref }}${{ github.event_name ==
'pull_request' && '' || format('-{0}', github.run_id) }}` does not do
what it reads as. GitHub treats the empty string as falsy, so on a
pull request `true && ''` is falsy and the expression takes the `||`
branch and appends the run id anyway. Every pull-request run therefore
gets a unique group, `cancel-in-progress` can never fire, and that is
a regression against today's behaviour and against what the comment
above the block says.

*Resolution* (`8bbc2600`): accepted, verified against the committed
file, and fixed by writing both alternatives out in full, so nothing
depends on how an empty string is treated:
`github.event_name == 'pull_request' && format('{0}-{1}', github.workflow, github.ref) || format('{0}-{1}-{2}', github.workflow, github.ref, github.run_id)`.
A pull request gets the string it has always had.

Worth recording for its own sake: my M2 report stated that "a pull
request's group string is byte-identical to the old one". It was not,
and nothing in the milestone could have caught it, because a workflow
expression is evaluated by GitHub and neither `actionlint` nor a YAML
parse looks inside one. The claim was made from reading the
expression, which is exactly the altitude at which this pitfall is
invisible.

### 2 (P1): a `fetch-depth: 0` checkout is still a snapshot

The history is fetched as of the checkout, so a commit published by a
run that started afterwards is not in this clone. `git cat-file` calls
it unknown, the check falls through to moving the tag, and that is
precisely the backwards move it exists to prevent.

### 3 (P1): every registry failure is indistinguishable from an absent tag

With no `pipefail` and stderr discarded, an authentication failure, a
timeout, a registry outage, a malformed response and a genuinely
absent tag all produce the same empty value, and all of them permit
the move.

*Resolution* for both (`7598dade`): accepted, and taken as one defect
rather than two patches, because they are the same defect: the check
moved the tag on the absence of a reason not to, and there are many
ways to reach that absence. It is inverted. `move` starts false and
exactly two paths set it: the registry positively reporting the tag
absent, or an answer holding one hex revision that names a commit in
this history, after a fresh `git fetch origin main`, that this commit
is not older than. Every other outcome leaves the tag and says why.

Two constraints shaped it. None of this can fail the job, because a
registry blip costing a commit its dated and `sha-` tags would be the
very defect M2 exists to remove, so each refusal is a warning and the
immutable tags publish regardless. And the not-found match is narrow,
so an unrecognised message is a registry that did not answer; the cost
is that a first publish into an empty package may need its moving tag
by hand, which is named in the verification section above.

This reverses the plan's stated rule for an unreadable revision, and
the deviation is recorded as one in M2's deviation list rather than
folded in quietly. The decision table and the mutation run were
re-driven against the rewritten step; nine of the seventeen rows
changed, and the mutation that used to survive is now killed by one of
them.

### 4 (P1): far-side bytes reach a public log

`$published` is interpolated into the refusal sentences, and the
dry-run index is `cat`-ed to the log before anything validates it.
Both are far-side bytes on a public surface, which the no-leak
contract forbids whether or not these particular bytes look harmless.

*Resolution* (`07a9b7e0`): accepted. The interpolations went with
finding 2 and 3's rewrite, which prints fixed sentences and never the
revision. The unconditional `cat` is dropped, and the index check
prints a summary after its assertions instead: the entry count it
counted, and the two platform names it was looking for, both values
this workflow chose rather than values the registry sent. After the
assertions rather than before, because a summary of an unvalidated
document describes whatever it was handed. Re-exercised against four
hand-built indexes: 0, 1, 1, 1.

### 5 (P2 as received, refuted): the PR edits `CHANGELOG.md`

*Resolution*: **rejected, with evidence.** This PR changes six files
and `CHANGELOG.md` is not among them. What happened is that the fold
workflow pushed `e3988d36` ("Fold the changelog fragments into their
sections") to `main` at 07:24:37Z, between the branch's rebase and the
review's fetch, and `git merge-base --is-ancestor e3988d36
origin/feature/490-m2-overlap` confirms that commit is already in this
branch's history. The review diffed against a stale `main` and
attributed `main`'s own commit to the branch. Confirmed here from the
worktree: `git diff --name-only` against the merge base returns
`.github/workflows/vinga-server.yml`, `changelog.d/490-overlap-and-tag-order.md`,
`docs/deployment.md`, the plan, the implementation doc and
`vinga-server/README.md`. The fragment stays as written.

Recorded rather than dropped because the failure mode generalises: a
repository with a bot that commits to `main` will produce this class
of finding again, and the cheap check is the merge base rather than
the file list.

### 6 (P2): the pages promise more than a read before a write can give

`vinga-server/README.md` and `docs/deployment.md` say two simultaneous
merges "cannot rewind" the moving tag. The implementation does not
provide that, and the plan explicitly accepts the race where both runs
read the old tag and the older one writes last.

*Resolution* (`12c80dc4`): accepted. Both pages now say what the check
does, that it is a check rather than a lock, and where that leaves a
moving tag: on the older commit until the next push moves it on. The
advice each paragraph exists to give is untouched and still leads,
since a moving tag is the wrong one to deploy from either way. The
changelog fragment carried the same overclaim and took the same
correction, and gained the cases where the check now declines to move.

### What the round says about the milestone

Four P1 findings against 33 lines of shell, and the report that
accompanied them claimed one thing that was false and one thing that
was weaker than stated. The common shape is that both bad claims were
made by reading rather than by running: the concurrency expression was
never evaluated by GitHub, and the failure modes of `imagetools
inspect` were never enumerated, only the success path and one failure.
The decision table above now has a row per failure mode because the
round showed the cost of not having one.

#### Second review round: one finding

Reviewed again at `561f68bc` after the rewrite, same backend and model,
runtime 2m00s. One P1, verdict **mergeable after the listed fix**.

**An ancestry-check error was treated as permission to move the tag.**
`git merge-base --is-ancestor` answers 0 for yes and 1 for no, and
anything above 1 means it could not answer. The rewrite's
`elif ...; else move=true` collapsed the third outcome into the
second, which is the same defect the rewrite had just fixed one level
up, surviving one level down: an operational failure read as evidence.
Git's own diagnostic also reached the log, and on that path it would
have been the only far-side text there.

*Resolution*: accepted. The status is captured and the three outcomes
are three branches, only the middle one setting `move`, and the
diagnostic is dropped rather than logged.

Driven through the committed step with `git` stubbed to return each
status in turn: 0 leaves the tag, 1 moves it, 128 leaves it with a
fixed warning and no trace of the stub's `fatal:` text in the output.
Mutated by widening the middle test from `-eq 1` to `-ne 0`, which
puts the error case back to moving the tag, so the case can fail and
is not decoration.

The finding is worth keeping for its shape rather than its size. The
first round's rewrite established the rule that the tag moves only on
positive knowledge, and then implemented it with a two-way test on a
three-way answer. A rule and its implementation can disagree in a
single line, and the review that catches it has to read the line
rather than the rule.
