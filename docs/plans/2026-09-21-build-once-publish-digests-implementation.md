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
| The ordering check, eighteen lines of shell | `image-publish`, the `Whether the moving tag may move` step |
| The checkout the check needs | `image-publish`, `actions/checkout@v7` with `fetch-depth: 0` |
| The moving tag dropped from the tag list when the check says so | `Assemble the manifest, check it, and publish it`, the `tags=()` loop |
| The maintained pages | `vinga-server/README.md` (the moving-tag paragraph in "Choosing an image"), `docs/deployment.md` (the moving-pointer paragraph in "Choosing a tag") |
| The changelog fragment | `changelog.d/490-build-once-publish-digests.md`, a `### Fixed` entry added to M1's file |

No second job, no reconciler, no concurrency group on any publish job,
and nothing walks `main`'s history. The design that did all of that is
in the plan's review rounds, and was cut before this milestone started.

### Deviations from the plan

Two, both small, and one of them reverses a deviation M1 recorded.

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

The check is shell with four branches, so it was tested as shell
rather than read. The step's `run:` body was extracted from the
workflow by `yaml.safe_load` (so the thing under test is the committed
text, not a copy of it), `docker` was replaced on `PATH` by a stub
printing an `imagetools inspect --format '{{json .Image}}'` payload
for a named case, and the script was run in this worktree so that
`git merge-base` and `git cat-file` answered against real objects.
Eight cases, all as intended:

| case | `published` | this run's commit | outcome |
| --- | --- | --- | --- |
| the tag is an ancestor | `HEAD~5` | `HEAD` | moves the tag |
| the tag is a descendant | `HEAD` | `HEAD~5` | `MOVE_MOVING=false`, leaves it |
| the tag is this same commit | `HEAD` | `HEAD` | leaves it |
| the tag is absent | inspect exits 1 | `HEAD` | moves it, "nothing to go backwards over" |
| the config carries no `VINGA_REVISION` | no match | `HEAD` | the same sentence, the same outcome |
| the revision names no commit here | `deadbeefdead` | `HEAD` | moves it, saying so |
| a sibling commit, neither ancestor nor descendant | a `commit-tree` child of `HEAD~3` | `HEAD` | moves it |
| a full 40-character revision rather than twelve | `HEAD~5` in full | `HEAD` | moves it |

Two of those are worth naming. **The same commit leaves the tag
alone**: `git merge-base --is-ancestor` is reflexive, so republishing
the commit a moving tag already points at is read as "not older" and
skipped, which is a no-op either way since the tag already names those
bytes. And **every unreadable answer moves the tag**. An absent tag, a
config without the variable and a revision git cannot resolve all
fall through to publishing, which is the plan's rule ("nothing to go
backwards over") and is the safe direction: the failure mode of a
misread is a tag that moved, not a tag pinned forever by a bad read.

The tag-dropping loop in the assembly step was driven separately, with
`MOVE_MOVING` true, false and unset, for both variants. Unset behaves
as true, which is what the dry and non-main paths need. The slim
variant is the case worth checking rather than the default one: its
moving tag `slim` is a substring of its own dated and `sha-` tags, and
the comparison is an equality on the whole tag rather than a substring
test, so only `ghcr.io/rafacm/vinga-server:slim` is dropped.

**Three mutations, two killed and one survivor.** Reversing the
ancestry arguments flips both the descendant and the ancestor case, so
the test kills it. Deleting `head -n 1` makes the two platforms' equal
revisions arrive as two lines, which `git cat-file` then refuses, so
that is killed too, by the fall-through that sends an unreadable
answer to "move it". The survivor is the `git cat-file -e` guard:
removing it leaves every decision identical, because `merge-base`
exits non-zero on an unknown revision and the `elif` reads that as
false. What the guard buys is the log, not the decision: without it
the step prints `fatal: Not a valid object name deadbeefdead` above
its own sentence. That is worth keeping in a job whose log is public,
and it is recorded here as a finding about the test rather than
dressed up as a behavior the test proves.

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
