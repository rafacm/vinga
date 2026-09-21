# Build each architecture once, publish the tested digests

Plan for [#490](https://github.com/rafacm/vinga/issues/490). Its
companion is
`docs/plans/2026-09-21-build-once-publish-digests-implementation.md`,
one section per milestone, appended in the same change that ticks the
milestone.

**Local baseline:** not applicable. Nothing here changes a
conversational capability. The whole change is how CI builds, smokes
and publishes an image that is byte-for-byte the one it builds today;
a deployment reaches none of it.

**Cheapest alternative:** replace only the `Publish` step's rebuild,
leaving the single `image` job intact: push the two already-loaded
images under per-arch scratch tags and assemble the manifest from
them. Measured against the same run, that removes the publish
rebuild's 359s and nothing else, taking the default variant's job from
781s to roughly 470s and the whole main run from 1241s to roughly
930s. This plan's job split takes the same run to roughly 500s,
because it also removes the arm64 build from the serial path (158s),
collapses three cache exports into one per scope (409.7s to 79.7s on
the critical path) and stops the builds waiting on the test lanes
(453s). The split buys roughly 430s more than the cheapest change,
which is the whole of its justification.

## What the issue measured, and what measuring again adds

The issue's four structural claims were re-verified at `a81608d` and
all four still hold, at the lines its own comment records. What the
measurement adds is three numbers that move where the work should go.

Everything below is from run
[35617743274](https://github.com/rafacm/vinga/actions/runs/35617743274)
(`a81608d`, 2026-09-21), job durations from the Actions API and step
internals from the job log.

### The dominant cost is the cache export, not the rebuild as such

The default variant's `image` job ran 781s. Its three
`docker/build-push-action` steps break down like this:

| Step | Total | of which GHA cache export |
| --- | --- | --- |
| Build the amd64 image | 145s | 79.7s |
| Build the arm64 image | 158s | 62.6s |
| Publish | 359s | **267.4s** |

That is **409.7s of 781s, 52% of the job, spent exporting BuildKit
cache**, three times, all into `scope=default`. The issue predicted
3m22s of export inside the publish; it is now 4m27s there plus 2m22s
before it.

The three exports write the same scope key, so only the last one's
index survives. The first two (142.3s every run) are therefore not
merely redundant, they are overwritten: nothing ever reads them. That
is what "one exporter per arch-variant scope" is worth, and it is
worth more than the issue expected.

The rest of the issue's account of the publish is exactly right. The
log shows `#22 [linux/arm64 builder 5/10] RUN uv sync ... DONE 50.3s`
inside the `Publish` step: the arm64 dependency installation running a
third time, under QEMU, as described. The push itself is cheap: layers
5.3s, three manifests 3.4s, 25.9s for the whole image export.

### The queue delay is real and rare

Across the 39 `push` runs of this workflow on `main` since
2026-09-11, the delay from run creation to the first job starting was
**2 to 4 seconds on 36 of them**. The only queueing in the sample is
the three-run burst of 2026-09-11 that the issue itself measured:
682s, 368s, 333s, from merges at 18:05, 18:33 and 18:52.

This does not refute M2, and M2 stays in scope as filed (confirmed
2026-09-21). It prices it: the delay appears when merges land inside
one run's duration of each other, which is exactly the shape this
repository's own pipeline produces when a stack of milestone PRs
merges back to back, and is absent the rest of the time. M1 shortens
the run, which shrinks the window in which a burst can collide, and
M2 removes what remains of it. M2's second value is not a speed one
and does not vary with cadence: it turns an invariant that is
currently an accident of workflow-wide serialization into a check that
states itself.

### A lever the issue does not name is worth more than either

`image` carries `needs: [unit, integration]`
([L1077](https://github.com/rafacm/vinga/blob/a81608d3/.github/workflows/vinga-server.yml#L1077)).
The unit lane ran 453s in this run, so the image work does not begin
until roughly 7.5 minutes into a run whose total is 1241s. Nothing
about building or smoking an image depends on the test lanes having
passed; what depends on them is **publishing**. Moving `needs` from
the build to the publish preserves the property that matters (nothing
reaches the registry that did not pass every gate) and takes 453s off
the critical path, which is more than the publish rebuild and the
queue delay put together.

This is a decision the issue leaves open rather than a scope change:
it changes when the existing work runs, not what runs or what is
published.

### Where the time goes after M1

Projected from the measured components above, default variant:

| | today | after M1 |
| --- | --- | --- |
| amd64 build | 145s (79.7s export) | 145s, in parallel with everything |
| pull the pushed digest back | n/a | ~50s |
| smoke | ~100s | ~100s |
| arm64 build | 158s, serial | 158s, parallel, off the critical path |
| publish | 359s | ~40s, builds nothing |
| waiting on the test lanes | 453s | 0s for the build, still gating the publish |
| **whole main run** | **1241s** | **~500s** |

These are projections from measured parts, not a measurement. M1's
verification is the first main run after it merges, and the
implementation doc records what that run actually did, including the
case where it does worse.

## Decisions

### The published bytes are pulled back and smoked, not exported twice

Each build runs once with
`outputs: type=image,...,push-by-digest=true,name-canonical=true,push=true`
and nothing else. The smoke then does `docker pull "$IMAGE@$DIGEST"`
and tags it locally, so what the smoke lane exercises is the bytes
that were pushed, fetched by the digest that will be published. That
is the issue's "provably what was smoked" made literal rather than
transitive.

The obvious alternative is one build with two exporters, `type=image`
plus `type=docker`, which loads locally and pushes in a single pass
and would save the pull. **It was tried, it works, and it must not be
used here.** Against a local registry with buildx 0.37.1:

- With `push-by-digest` alone, `containerimage.digest` is the OCI
  **index** digest, and the index carries both the platform manifest
  and the provenance attestation manifest.
- Adding a second `type=docker` output changes the reported
  `containerimage.digest` to the bare **platform manifest** digest.
  Nothing warns. A manifest assembled with
  `docker buildx imagetools create` from that digest contains one
  platform manifest and **no attestation**.

Confirmed both ways by assembling from each digest and reading the raw
index back: the index digest yields two entries, one of them
`vnd.docker.reference.type: attestation-manifest`; the manifest digest
yields one. Today's `Publish` step pushes attestation manifests (the
log shows two exported), so taking the two-output shortcut would
silently drop provenance from every published image, which is the
groundwork #317 is waiting on. The pull costs roughly 50s of the
critical path; provenance is not for sale at that price.

The corollary is a rule the implementation must not drift from:
**publish from `containerimage.digest` as reported by a build whose
only output is the image exporter.** Pinned by a check in the publish
job that the assembled index contains an attestation manifest per
platform, so the trap cannot return silently.

### One job, matrix over variant and architecture

`image` keeps its `strategy.matrix` and gains an `arch` dimension, so
it becomes four jobs: `{default,slim} x {amd64,arm64}`. The smoke
steps, and the database and uv setup they need, carry
`if: matrix.arch == 'amd64'`.

The rejected alternative is two jobs, one per architecture. It reads
better at the top of the file and duplicates the build step, its
`build-args`, its cache configuration and its digest handling into two
places that must agree with nothing to enforce it. "Two structures
that must agree are one structure with a bug pending" applies
directly, and the build step is the one structure here that must not
drift, since the whole issue is about what got built. The file's own
idiom already gates steps on the matrix (`if: matrix.variant == 'slim'`
appears four times today), so the arch gates are the same move, not a
new one.

The accepted cost is roughly nineteen `if: matrix.arch == 'amd64'`
lines. Named here so a reviewer reads them as a decision rather than
an accident.

### Cache scope becomes `variant-arch`, exported once

`cache-from`/`cache-to` become
`type=gha,scope=${{ matrix.variant }}-${{ matrix.arch }}`, written by
exactly one step, and the publish job configures no cache at all
because it builds nothing.

A run's amd64 job then imports an index written by the previous run's
amd64 job, which is better targeted than today, where the amd64 build
imports an index whose last writer was the two-platform publish
build.

**Not taken, deliberately: moving the export to
`type=registry`.** GHCR registry cache is usually faster to export
than the GitHub Actions cache service, and 79.7s is the largest single
item left on the critical path after M1. It is not taken because M1
already changes the scope key, which cold-starts the cache once; doing
both at the same time means the first run after M1 cannot attribute
its numbers to either. M1's verification reports the measured export
time, and that number is what should decide it, as its own change.

The report's caution applies and is honored: this milestone removes
only exports that are provably overwritten within the same job, not
exports that a later run might hit.

### Native arm64 runners: evaluated, not adopted

The issue asks for this to be evaluated in M1. The evaluation is that
after the split it buys no wall time. The arm64 build is 158s against
the amd64 job's projected ~345s, so arm64 finishes first and is off
the critical path; removing QEMU from a job that is not the pole
shortens nothing. The repository is public, so `ubuntu-24.04-arm`
would cost nothing in minutes, and the real thing it would buy is a
**native arm64 smoke**, which today does not exist at all (arm64 gets
an extras import and nothing more). That is a coverage question rather
than a speed one, it is a larger change than this milestone, and it
belongs in its own issue. Recorded here so the ask is discharged with
a number rather than left implied.

### Builds stop waiting on the test lanes; the publish does not

`image` drops `needs: [unit, integration]`. `image-publish` carries
`needs: [unit, integration, image]`, so the invariant is unchanged:
nothing is published unless both lanes passed. What changes is that a
commit whose tests will fail also builds an image, which costs runner
minutes on a public repository, where they are free, and buys the
critical path 453s.

### The publish job runs on every event, dry on everything but main

`docker buildx imagetools create` takes `--dry-run`, which resolves the
sources and prints the manifest it would push without pushing
anything. The publish job therefore runs on pull requests and
dispatches too, assembling the real manifest from the real digests and
pushing nothing, and only a push to `main` passes the tags and drops
the flag.

This is the file's existing philosophy applied to the step that
replaces the one it was written for: the `Tags` step is already
deliberately ungated, so "a dispatch run prints exactly what a push to
main would publish". Without it, M1's entire publishing half would
first execute on `main`, which is the one place the workflow is not
allowed to be wrong.

### Publication splits by what needs ordering

M2 narrows the workflow-level `concurrency` so it no longer serializes
`main`: a pull request keeps
`${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress`,
and a push appends the run id so each one gets a group of its own.

The serialization that remains is placed by asking which tag actually
needs it, and the answer is only the moving one. So publication splits
in two:

- **`image-publish`** assembles the manifest and pushes the immutable
  dated and `sha-` tags. It takes **no concurrency group**, because a
  group is exactly what could displace it.
- **`image-promote`** moves the moving tag and nothing else, in a
  group of `publish-${{ matrix.variant }}` with
  `cancel-in-progress: false`.

The split is what makes the design safe rather than the group being
non-cancelling, and the reason is a semantic of GitHub Actions that is
easy to read past: a group holds one running member and one pending
member, and a third arrival **replaces the pending one** whether or not
`cancel-in-progress` is set. Anything whose output is per-commit and
irreplaceable must therefore not be in a group at all.

**This is a live defect today, not a hazard the plan avoids
introducing.** The current workflow-level group has the same
semantics, and the 2026-09-11 burst contains a fourth run the issue
does not mention: `2026-09-11T18:19:29Z d6d76dd push completed
cancelled`, queued behind the 18:05 run and replaced when the 18:33
one arrived. `d6d76dd1` is an ancestor of `origin/main` and
`ghcr.io/rafacm/vinga-server:sha-d6d76dd` does not exist, while
`sha-2f9675f`, `sha-f943bc6` and `sha-623f170` all do. A merged commit
on `main` has no image, and no run went red to say so. The workflow's
own comment that "Merges to main run to completion, however many of
them queue up" has been false since it was written.

Displacing a pending `image-promote` is harmless by construction: the
moving tag is meant to end up at the newest commit, and the newest run
is the one that survives displacement.

### The moving tag will not go backwards, and the check says so

Job-level ordering is necessary and not sufficient, because GitHub
does not promise that two queued promotions run in commit order.
Before moving a tag, `image-promote` reads the revision of what that
tag currently points at:

```
docker buildx imagetools inspect "$IMAGE:$MOVING" --format '{{json .Image}}'
```

That returns the per-platform configs, including
`VINGA_REVISION=<short sha>` from the image's own `ENV` (verified
against `ghcr.io/rafacm/vinga-server:latest`, which reports
`VINGA_REVISION=a81608d` for both platforms). If that revision is a
descendant of this run's commit, this run is the older one and leaves
the moving tag alone. Its immutable tags were pushed by
`image-publish` already and are unaffected.

Three details that are the whole of whether this works:

- `image-promote` checks out with `fetch-depth: 0`. The default depth
  of 1 has no history and every ancestry question would answer wrong.
- `git merge-base --is-ancestor` is the right tool **here** and is the
  wrong tool in the case AGENTS.md warns about. That warning is about
  branches across a rebase merge, where hashes are rewritten. Both
  commits here are commits on `main`, so ancestry is genuine. The
  distinction goes in the step's comment, because the warning is more
  memorable than its scope.
- A moving tag that does not exist, or whose config carries no
  `VINGA_REVISION`, means there is nothing to go backwards over: the
  run proceeds and says so.

### No new promise, no new record

M2 preserves a property the workflow has today rather than creating
one, so it adds no product promise and no ADR. It makes the property
checkable where it is currently a side effect of serializing
everything, and the two maintained pages that describe the moving tags
gain a sentence saying what the tag now guarantees.

## The job graph after all three milestones

```
unit ─────────────┐
integration ──────┤
                  ├─> image-publish ──> image-promote
image (matrix: variant x arch) ─┘       (matrix: variant, both)
  amd64: build, smoke                   publish: immutable tags, no group
  arm64: build, import check            promote: the moving tag, ordered group
```

`image` runs on push, pull_request and workflow_dispatch after M3.
`image-publish` runs on push and workflow_dispatch, with `--dry-run`
on everything but a push to `main`. `image-promote` runs only on a
push to `main`, since it exists to move a tag and there is no dry
version of that worth running.

## Design footprint

The modules here are workflow jobs and the seam between them is a
digest, which is the point of the issue.

- **M1 adds one seam and one module.** The seam is the per-arch image
  digest, carried between jobs as an upload-artifact named
  `digests-<variant>-<arch>`. It replaces an implied crossing (the
  publish rebuilding from a cache it hopes is warm and shares with the
  build) with a stated one: a content address. The new module is
  `image-publish`, and what its callers stop having to know is how an
  image was built: it takes digests and tags and assembles a manifest,
  and could not rebuild if it wanted to, because it has no context and
  no builder.
- **M1 deepens `image`.** It stops being a job that builds, smokes and
  publishes, and becomes a job that proves one architecture of one
  variant. The publishing half leaves it entirely.
- **M2 adds `image-promote` and shrinks what ordering costs.** The new
  module's one responsibility is moving a tag, and what its callers
  stop having to know is how ordering is achieved: everything upstream
  of it runs unordered. It passes the deletion test because inlining
  it back into `image-publish` is precisely the shape that loses a
  merged commit's image, which is the defect the round found. This is
  the issue's own sentence read one level sharper: the ordering
  guarantee is needed by the moving tag, not by the publish, and
  certainly not by everything.
- **M3 adds nothing.** It is one `if:` deleted and a paths list; the
  whole of what makes it affordable was built by M1.

## Documentation footprint

Three maintained pages describe today's behavior in ways this work
falsifies. All three are in the "maintained maps and explanations"
class of `docs/README.md`, so they describe the system as it is now
and are corrected when it moves.

- **M1, `vinga-server/README.md` §Choosing an image.** "**Pair the two
  variants by their SHA tag, not their dated one.** They are built by
  separate jobs that finish minutes apart, so one commit can produce
  `2026-08-06-1048` and `2026-08-06-1047-slim`." After M1 the two
  variants are published by jobs that start together and assemble a
  manifest in seconds, so the dated tags will usually agree. The
  advice to pair by SHA stays correct and stays the advice; its
  stated reason stops being true and is corrected. The same section's
  "each has passed the unit, integration, and smoke lanes" gains the
  stronger fact M1 creates: the published bytes are the smoked bytes,
  by digest.
- **M1, `docs/deployment.md` §Choosing a tag.** Carries the same
  "built by separate jobs that finish minutes apart" reason and gets
  the same correction. It summarizes the server README and links it,
  so the correction goes to the README and this page keeps pointing
  at it.
- **M2, both pages.** The moving-tag paragraphs gain one sentence for
  the guarantee the ordering check makes explicit: a moving tag never
  moves to an older commit's image. This strengthens rather than
  weakens the existing advice not to deploy from a moving tag, and
  must not be written in a way that reads as permission to.
- **M2, `.github/workflows/vinga-server.yml` L52-54.** "Never on a
  push to main ... Merges to main run to completion, however many of
  them queue up" is false today, and `d6d76dd` is the counterexample.
  The comment is rewritten to say what the split actually guarantees:
  immutable tags for every merged commit, because nothing that
  produces them sits in a group, and a moving tag that only ever moves
  forward. A comment is not a maintained page, but it is the load
  bearing explanation of the block it sits on, and leaving it would
  leave the next reader with the belief that cost this repository an
  image.
- **M3: nothing.** The server README's smoke-lane section says "CI
  runs it against the image it just built", which stays true when
  pull requests run it too. No page claims the image job skips pull
  requests.

The generated references under `docs/reference/` are untouched:
nothing here changes a CLI command, a configuration field, the API or
an event.

## Verification

This is a workflow-only change, so the honest statement of what can be
verified where matters more than usual.

- **Locally**: `actionlint` if available, and a YAML parse. The
  mechanism itself has already been verified locally against a
  throwaway registry, and the two experiments are reproducible:
  push-by-digest plus `imagetools create` assembling a tagged index,
  and the attestation difference between the index digest and the
  platform manifest digest.
- **On a branch, before merging**: `gh workflow run vinga-server.yml
  --ref <branch>`, which after M1 exercises every step including the
  manifest assembly under `--dry-run`. This is the gate for each
  milestone, and the run is linked on its PR.
- **On `main`, after merging**: the first push is the only thing that
  can exercise the real tag move. M1's implementation-doc section
  records the measured job durations and cache-export times of that
  run against the table above, including if they are worse.
- **Not verifiable before merging, and not claimed**: that a burst
  behaves. The round is explicit that two overlapping runs are not the
  case to check, because the displacement needs a third; the case is
  **three merges inside one run's duration**, where the assertions are
  that all three commits get their dated and `sha-` tags, and that the
  moving tag ends at the newest of them. M2's section records this
  unchecked with the reason. It can be provoked rather than waited
  for, by merging M3 and a documentation commit in quick succession
  once M2 is on `main`, and that is the intended discharge.

The `tests/census` lane is run before each PR: the command-spellings
census sweeps every tracked file, and this work edits documentation
that quotes commands.

## Risks

- **The publishing half first runs for real on `main`.** Mitigated by
  the `--dry-run` publish on dispatch, which exercises the assembly,
  the digest artifacts and the tag computation against real pushed
  digests; only the final push differs. Residual risk is the push
  itself, which is the one command `--dry-run` skips.
- **The first run after M1 has a cold build cache**, because the scope
  key changes. It will be slower than the table predicts and slower
  than today. The measurement that matters is the second run, and the
  implementation doc reports both so the number is not quietly taken
  from the wrong one.
- **Digests pushed on pull requests and dispatches leave untagged
  versions in GHCR**, four per run after M3. Storage is free for a
  public package and nothing resolves them, so this is clutter rather
  than cost. Accepted, with the remedy named: a scheduled pruning of
  untagged versions, if and when the package listing becomes hard to
  read. Not built now.
- **A pull request from a fork gets a read-only token and cannot push
  by digest**, so M3 would fail on one. The repository has zero forks
  today and GitHub gates a first-time contributor's run behind
  approval anyway, so this is hypothetical. Recorded rather than
  pre-solved; the remedy if it arrives is to build without pushing on
  a fork head.
- **`--dry-run` could diverge from the real push.** It resolves the
  same sources and produces the same manifest; what it does not
  exercise is the registry write. The attestation assertion described
  above runs against the assembled manifest in both modes, so the
  failure this plan most wants to catch is caught dry.

## Milestones

- [ ] **M1: build each architecture once, publish the tested digests.**
  `image` gains an `arch` matrix dimension and loses its publishing
  half; each of the four jobs builds once with the image exporter
  alone, pushes by digest, and records
  `containerimage.digest` as an artifact. The amd64 jobs pull that
  digest back and run the existing smoke unchanged against it. A new
  `image-publish` job assembles the multi-arch manifest with
  `docker buildx imagetools create`, moves the tags, builds nothing
  and configures no cache; it runs on every event and passes
  `--dry-run` on everything but a push to `main`, and asserts the
  assembled index carries an attestation manifest per platform. Cache
  scopes become `variant-arch`, exported exactly once each. `needs:
  [unit, integration]` moves from the build to the publish. Documents
  the two "finish minutes apart" passages.
- [ ] **M2: validation overlaps across main pushes; the moving tag
  alone stays ordered.** The workflow-level concurrency group stops
  serializing `main` (each push gets its own group) and keeps
  cancelling superseded pull-request runs. Publication splits:
  `image-publish` keeps the immutable tags and takes no group at all,
  so it cannot be displaced while pending; a new `image-promote` moves
  the moving tag in an ordered, non-cancelling group per variant,
  checks out with `fetch-depth: 0`, and leaves the tag alone when its
  current image is a descendant of this run's commit. Corrects the
  workflow's false comment about merges running to completion, and
  documents the guarantee in the two moving-tag passages.
- [ ] **M3: image-affecting pull requests build and smoke
  automatically.** `image` loses `if: github.event_name !=
  'pull_request'` and the comment explaining the exemption;
  `image-publish` keeps its main-only tag move and runs dry on the
  pull request. `workflow_dispatch` stays.

## Plan review round

Reviewed at `27d12b0f` on 2026-09-21. Backend codex, model
`gpt-5.6-sol`, `--sandbox read-only`, runtime 184s. The prompt carried
the plan, the reading list, the issue body, and the commands behind
every measurement the plan rests on, so the method could be audited
rather than only the conclusions. Verdict as received: **not ready**.

Six findings, recorded as received.

### 1 (P1): the proposed concurrency group can silently discard publish jobs

GitHub Actions permits one running and one pending member per
concurrency group. When a third publish becomes ready it replaces the
pending one even with `cancel-in-progress: false`, so in the
three-merge burst M2 exists to handle, the middle commit's publish is
cancelled and it never receives its dated and `sha-` tags. The plan
promised "publishing its immutable tags regardless" without
establishing that the job runs at all. The plan must verify a
three-run overlap, not a two-run one.

*Resolution*: accepted, and verifying it found that this is a **live
defect in the current design rather than a hazard M2 would
introduce**. The workflow-level group has the same one-running,
one-pending semantics today. In the 2026-09-11 burst the issue
measures, `gh api` lists a fourth run the issue does not mention:
`2026-09-11T18:19:29Z d6d76dd push completed cancelled`, queued behind
the 18:05 run and replaced when the 18:33 one arrived. `d6d76dd1`
("Regenerate the spellings census on the rebased tree") is an ancestor
of `origin/main`, and `ghcr.io/rafacm/vinga-server:sha-d6d76dd` does
not exist, while `sha-2f9675f`, `sha-f943bc6` and `sha-623f170` all
do. A merged commit on `main` has no image, and no run went red to say
so.

The amendment is to split publication by what actually needs ordering.
`image-publish` assembles the manifest and pushes the **immutable**
dated and `sha-` tags, with no concurrency group at all, so it can
never be displaced while pending. `image-promote` moves the **moving**
tag alone, in an ordered non-cancelling group per variant. A displaced
`image-promote` is then harmless by construction: the moving tag is
supposed to end up at the newest commit, and the newest run is exactly
the one that survives displacement. This is a sharper reading of the
issue's own sentence than the plan had: the ordering guarantee is
needed by the moving tag, not by the publish.

The workflow comment at L52-54, "Merges to main run to completion,
however many of them queue up", is false and has been. Correcting it
joins M2's documentation footprint.

### 2 (P1): concurrent publication makes the minute-resolution tag mutable

`type=raw,value={{date 'YYYY-MM-DD-HHmm'}}` gives two commits
publishing inside the same minute the same dated tag, and the later
registry write wins. Today serialization plus a six-minute publish
makes this practically impossible; M2 permits overlap and M1 cuts the
publish to seconds, so the collision becomes reachable. Both
maintained pages call dated tags immutable and never reused.

*Resolution*: accepted. The dated tag gains seconds,
`YYYY-MM-DD-HHmmss`, which keeps what the tag means (when the build
happened) and removes the collision class rather than shrinking it.
The publish additionally refuses to reuse a dated tag: if the tag
already resolves and its digest differs from the one being published,
the job fails loudly rather than overwriting. This repository's stated
preference is that a guarantee is enforced rather than documented, and
the check is five lines. The tag-format change is user-visible, so it
joins M1's documentation footprint in both pages, alongside the
example tags in the server README's variant table.

### 3 (P1): M3 does not implement automatic PR coverage for forks

M1 requires the image exporter to push to GHCR; M3 then removes the PR
exclusion, and a fork PR has a read-only token, so it fails. The issue
asks for image-affecting pull requests to build and smoke, not for
same-repository ones, and explicitly offers "carried as a build
artifact" as the route the plan rejected without pricing.

*Resolution*: accepted, with a different remedy than the one proposed,
and the plan is better for it. **Pull requests stop pushing by digest
at all.** A pull request publishes nothing, so it needs no digest: the
build loads locally and the smoke runs against that, exactly as today.
Push-by-digest runs on `push` and `workflow_dispatch` only, which are
the events that publish or dry-run the assembly.

This resolves the finding completely (a fork PR builds and smokes with
no token and no credentials reaching fork code), and it also retires
two things the plan had accepted as costs: the accumulation of
untagged GHCR versions from pull requests, and most of finding 5's
exposure. The artifact route was priced before being set aside:
`imagetools create` cannot read a local OCI archive, so it would need
`skopeo` or `crane`, neither preinstalled, plus roughly 2 to 4 GB of
artifact traffic per run to move images that no longer need moving.

The cost is that a pull request no longer exercises manifest assembly.
`workflow_dispatch` still does, and dispatch is already the plan's
pre-merge gate.

### 4 (P2): the cache-export conclusion is wider than the evidence

The plan said the first two same-scope exports are overwritten and
"nothing ever reads them". But the amd64 export completes before the
arm64 build imports the same scope, and that export completes before
the publish imports it, so a later step in the same job can consume an
export before its index is overwritten. The timing method measured
export duration and never inspected cache-hit provenance.

*Resolution*: accepted without reservation. This is the recurring
error this repository has a note about, prose claiming more than was
measured, and the reviewer is right about the mechanism: a same-job
reader exists and was never checked for. The claim narrows to what the
timings support, that same-scope exports overwrite one another **for
future runs**, and the words "provably overwritten" and "nothing ever
reads them" come out. The `variant-arch` split becomes a stated
hypothesis rather than a conclusion, and M1's verification gains a
cache-hit measurement on a warm run: the arm64 build's duration and
its imported-layer count before and after, so the split is judged on
hit provenance rather than on export duration alone. If the arm64
build gets slower, the scopes merge back and the milestone says so.

### 5 (P2): moving builds ahead of tests changes the registry gate

The plan said "nothing reaches the registry" unless both lanes pass
and called the invariant unchanged, while each architecture job pushes
an addressable digest before either lane has passed. Only tag
assembly remains gated.

*Resolution*: accepted; the sentence was wrong as written. Finding
3's remedy removes the pull-request half of the exposure entirely, and
what remains is stated precisely instead of being called unchanged:
on a push to `main`, content-addressed manifests may reach GHCR before
the test lanes finish, and **no tag of any kind, moving or immutable,
is created until the unit lane, the integration lane and every image
job have passed**. An untagged manifest is unreachable by name and is
not what any deployment resolves. A `main` push whose tests then fail
leaves an untagged manifest behind, which is the accepted cost, named
here rather than in a risks list, since it is the invariant's actual
shape.

### 6 (P2): the attestation experiment does not validate the real assembly shape

The experiment generalized from a one-layer Alpine build and assembled
one source digest at a time. The real publication merges two
single-platform indexes from a multi-stage Dockerfile, and counting
"an attestation per platform" can miss a malformed or mis-associated
one.

*Resolution*: accepted, and the acceptance check the reviewer proposes
is adopted verbatim in preference to the plan's weaker one. Part of
the topology gap was closed after the plan was committed, by a second
experiment: two single-platform builds pushed by digest separately,
then merged with one `imagetools create`, produce an index with four
entries, one `linux/amd64` manifest, one `linux/arm64` manifest and
two `attestation-manifest` entries, which is the same shape
`ghcr.io/rafacm/vinga-server:latest` carries today (verified by
`imagetools inspect --raw` on the live tag). That closes "does merging
two indexes preserve both platforms and both attestations" and leaves
the reviewer's other three assertions open, so the check asserts all
of them: one manifest per expected platform, each attestation's
`vnd.docker.reference.digest` naming its own platform manifest, no
nested or duplicate platform index, and both configs carrying the
expected `VINGA_REVISION` and variant. It runs in both the real and
the `--dry-run` publish, so a dispatch catches the failure before a
merge does. The reviewer's framing is kept: the local experiments show
the exporter choice matters, and the acceptance check is what
validates the topology.
