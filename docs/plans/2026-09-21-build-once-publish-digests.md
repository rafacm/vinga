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

**Scope:** cut back after five review rounds, on 2026-09-22, at the
maintainer's call. The rounds converged on a correct design that was
out of proportion to the problem: a second publish job, a reconciler
walking `main`'s history, a two-phase index validation and a widened
revision, none of which saved any time and all of which protected a
moving tag the documentation already says not to deploy from. What
remains is the issue: build each architecture once, publish the tested
digests, let validation overlap, and run the image lane on pull
requests. The rounds are kept below as the record, and
["The review rounds, and what was cut afterwards"](#the-review-rounds-and-what-was-cut-afterwards)
says exactly what left.

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

The three exports write the same scope key, so for a **future** run
only the last one's index survives. That is as far as these timings
reach, and no further: within the same job, the amd64 export completes
before the arm64 build imports that scope, and the arm64 export
completes before the publish imports it, so a later step in the same
run can consume an export before its index is overwritten. Export
duration was measured; cache-hit provenance was not. Whether the
earlier exports have a same-job reader is open, and M1 measures it
rather than assuming either answer.

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

On the events that publish or assemble, `push` and
`workflow_dispatch`, each build runs once with
`outputs: type=image,...,push-by-digest=true,name-canonical=true,push=true`
and nothing else. The smoke then does `docker pull "$IMAGE@$DIGEST"`
and tags it locally, so what the smoke lane exercises is the bytes
that were pushed, fetched by the digest that will be published. That
is the issue's "provably what was smoked" made literal rather than
transitive.

**A pull request pushes nothing.** It publishes nothing, so it needs
no digest: it builds with `load: true` and smokes the loaded image,
which is what the job does today. This is one expression on the build
step rather than a second structure, and the smoke steps after it are
identical either way, because they read a local tag in both cases.

Three things fall out of that and are the reason it is the right shape
rather than a concession. A pull request from a fork has a read-only
token and now needs none, so M3 covers every pull request rather than
same-repository ones. No registry credential is ever available to fork
code. And pull requests leave no untagged versions in GHCR, which was
a cost the plan had accepted and no longer pays.

What a pull request gives up is exercising manifest assembly.
`workflow_dispatch` still does it in full, and dispatch is already this
plan's pre-merge gate for every milestone.

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
only output is the image exporter.**

A second experiment closed the topology question for the shape this
plan actually publishes. Two single-platform builds, pushed by digest
separately and then merged by one `imagetools create`, produce an
index with four entries: one `linux/amd64` manifest, one `linux/arm64`
manifest, and two `attestation-manifest` entries. That is the same
shape `ghcr.io/rafacm/vinga-server:latest` carries today, read back
with `imagetools inspect --raw` on the live tag.

So `image-publish` asserts that shape on what it assembled: **both
expected platforms present, and an attestation manifest for each**.
One check, run on the assembled index.

That is deliberately not the elaborate version. A review round
proposed validating four properties in two phases, before and after
tagging, against every tag, including each attestation's subject
association and both configs' revision and variant. Each assertion was
individually reasonable and the whole was cut on proportion: today's
publish validates **nothing** and has never produced a malformed
index, so the failure being defended against has no instances. The
one failure mode this change genuinely introduces, the exporter
silently reporting a platform manifest instead of an index and
dropping provenance, is prevented **by construction** rather than by
assertion, because the build never gets a second output. The check
above exists to catch that construction being undone, which is the
thing that could plausibly happen, and it fails loudly when it is.

The local experiments are what they are:
evidence that the exporter choice matters. This check is what
validates the topology.

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

The intended effect is that a run's amd64 job imports an index written
by the previous run's amd64 job, rather than one whose last writer was
a two-platform publish build. **That is a hypothesis, not a
conclusion.** Splitting the scope also stops each architecture seeing
the other's export, and the timings behind this plan say nothing about
whether anything was gaining from that. The arm64 build is where it
would show, since it imports last today.

M1 therefore measures rather than asserts: the arm64 build's duration
and its cached-versus-executed step counts on a **warm** run, before
and after. If the arm64 build gets slower, the scopes merge back to
one per variant and the milestone records the number that said so.
Cold-start on the first run after the key changes is expected and is
not the measurement.

**Not taken, deliberately: moving the export to
`type=registry`.** GHCR registry cache is usually faster to export
than the GitHub Actions cache service, and 79.7s is the largest single
item left on the critical path after M1. It is not taken because M1
already changes the scope key, which cold-starts the cache once; doing
both at the same time means the first run after M1 cannot attribute
its numbers to either. M1's verification reports the measured export
time, and that number is what should decide it, as its own change.

The report's own caution is what this is: measure subsequent cache hit
rates before deciding which exports to remove, since an export that
looks redundant may be the one later runs hit. The plan's first draft
quoted that caution while doing the opposite, and the review round
caught it.

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
`needs: [unit, integration, image]`.

The invariant this preserves has to be stated precisely, because the
plan's first draft stated it wrongly ("nothing reaches the registry")
and the review round was right to refuse that. On a push to `main`,
**content-addressed manifests may reach GHCR before the test lanes
finish**, and **no tag of any kind, moving or immutable, is created
until the unit lane, the integration lane and every image job have
passed**. Those are different sentences and only the second one is
true.

The gap between them is what an untagged manifest is: unreachable by
name, resolved by no deployment, and not what any of the three
documented pull commands names. A `main` push whose tests then fail
leaves one behind, which is the accepted price of building before the
gates rather than after them. Pull requests contribute none of this,
since finding 3's remedy stops them pushing at all.

What is bought is 453s of critical path, against runner minutes that
are free on a public repository.

### The publish job runs on push and dispatch, dry on everything but main

`docker buildx imagetools create` takes `--dry-run`, which resolves the
sources and prints the manifest it would push without pushing
anything. `image-publish` therefore runs on `workflow_dispatch` as
well as on a push, assembling the real manifest from the real digests
and pushing nothing, and only a push to `main` passes the tags and
drops the flag. It does not run on a pull request, which has no
digests to assemble.

This is the file's existing philosophy applied to the step that
replaces the one it was written for: the `Tags` step is already
deliberately ungated, so "a dispatch run prints exactly what a push to
main would publish". Without it, M1's entire publishing half would
first execute on `main`, which is the one place the workflow is not
allowed to be wrong.

### The moving tag is ordered by a check, not by a group

M2 narrows the workflow-level `concurrency` so it no longer serializes
`main`: a pull request keeps
`${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress`,
and a push appends the run id so each one gets a group of its own.

**Removing that group is what fixes the live defect**, and it is worth
being clear that nothing else is needed for it. A concurrency group
holds one running member and one pending member, and a third arrival
replaces the pending one whether or not `cancel-in-progress` is set.
That is not a hazard this plan must avoid introducing, it is a defect
running today, and the 2026-09-11 burst contains the evidence: a
fourth run the issue does not mention,
`2026-09-11T18:19:29Z d6d76dd push completed cancelled`.

The evidence is the run's own record, run `34632623405`, not the
missing tag, which alone would also be consistent with a later
deletion:

- `GET /actions/runs/34632623405/jobs` returns an **empty job list**.
  Not a failed job, not a cancelled one, none at all. Nothing ran, so
  nothing failed, and the image job never started.
- `created_at` and `run_started_at` are both `18:19:29Z`, and
  `updated_at` is `18:33:59Z`, one second after `f943bc6`'s run was
  created at `18:33:58Z`. It sat pending for fourteen minutes and was
  terminated when the next push entered its group.

`d6d76dd1` is an ancestor of `origin/main` and
`ghcr.io/rafacm/vinga-server:sha-d6d76dd` does not exist, while
`sha-2f9675f`, `sha-f943bc6` and `sha-623f170` all do. With the empty
job list, that absence needs no deletion to explain it. A merged
commit on `main` has no image and no run went red to say so, and the
workflow's own comment that "Merges to main run to completion, however
many of them queue up" has been false since it was written.

Once each push has its own group, nothing is ever pending, nothing is
displaced, and every merged commit gets its image. **No second job and
no ordered group are added**, because the thing they would protect is
the thing the group removal already fixed.

### What orders the moving tag, and what that is worth

What remains is that two overlapping runs could both move a moving
tag, and the later writer might be the older commit. The issue names
both remedies and this plan takes the second: "an ordered,
non-cancelling group **(or an equivalent ordering check, such as
refusing to move a tag over a newer commit's image)**".

So `image-publish` reads the revision of what the moving tag points at
before moving it:

```
docker buildx imagetools inspect "$IMAGE:$MOVING" --format '{{json .Image}}'
```

That returns the per-platform configs including `VINGA_REVISION` from
the image's own `ENV` (verified against
`ghcr.io/rafacm/vinga-server:latest`, which reports
`VINGA_REVISION=a81608d` for both platforms). If that revision is a
descendant of this run's commit, this run is the older one and leaves
the moving tag alone, publishing its immutable tags as normal. The
job checks out with `fetch-depth: 0`, since depth 1 has no history and
every ancestry question would answer wrong. A moving tag that is
absent, or whose config carries no `VINGA_REVISION`, means there is
nothing to go backwards over: the run proceeds and says so.

**What this is worth, and what it is not, priced rather than
asserted.** The check is a read before a write and there is no group,
so two publishes inside the same few seconds can both see the old
revision and both proceed, and the moving tag ends at whichever wrote
last. The consequence is that `latest` can sit one commit behind for
as long as it takes the next push to publish. It cannot point at
ungated bytes, because every run publishes only after its own gates.

That residual is acceptable because of what a moving tag is for, which
both maintained pages already say: "the tags to pull when trying the
server and **the wrong ones to deploy from**". Closing it completely
needs an ordered group, which needs the publish split in two so the
immutable tags cannot be displaced, which needs a reconciler to make
displacement safe. That machinery was designed, reviewed over three
rounds and then cut: it is roughly five times the code, it protects a
tag nobody should deploy from against being briefly stale, and it buys
no wall time. The design is recorded in the review rounds below and
`image-promote` is the name to bring back if a moving tag ever needs
to be exact.

### The dated tag gains seconds

`type=raw,value={{date 'YYYY-MM-DD-HHmm'}}` gives two commits
publishing inside the same minute the same "immutable" tag, and the
later registry write wins. Serialization plus a six-minute publish
makes that unreachable today; M1 cuts the publish to seconds and M2
permits overlap, so it becomes reachable exactly when merges burst,
and that reachability is something this plan creates rather than
inherits.

The dated tag therefore becomes `YYYY-MM-DD-HHmmss`, keeping its
variant suffix. It keeps what the tag means, the moment the build
happened, and takes the collision back to needing two commits to
finish every lane and the assembly **within the same second**. It is
a user-visible format change and lands in the documentation
footprint.

### The revision widens to twelve characters

The `sha-` tag is seven characters, so two commits sharing that prefix
publish under the same supposedly immutable tag. This is pre-existing
rather than something the issue creates, and it was nearly deferred to
its own issue on two arguments that both turned out to be wrong.

**The risk was overstated, and the corrected number is the weaker
argument for fixing it.** The first estimate put it "on the order of
2e-3 at a thousand commits", which computed the birthday bound over
*commits*. A push publishes one image, not one per commit, and this
workflow has had **186 push runs on `main` in the project's lifetime**
(`actions/workflows/vinga-server.yml/runs?event=push&branch=main`).
Against 16^7 that is:

| published images | collision chance | when, at ~3.7 publishes a day |
| --- | --- | --- |
| 186 | **0.006%** | today |
| 1,000 | 0.19% | ~9 months |
| 2,000 | 0.74% | ~18 months |
| 6,800 | 8.3% | ~5 years |

So it is about 1 in 15,500 today and not urgent, and it is not
negligible on a two-to-five year view. At twelve characters, 6,800
images gives 0.000008%.

**The cost was overstated too, and that is the real argument.** Review
round 4 recorded `DOCKER_METADATA_SHORT_SHA_LENGTH` as "not taken",
because this session could not verify the variable against the pinned
action version and a tag scheme should not rest on an unverifiable
mechanism. That caution was right in form and wrong in fact: the
variable is documented in `docker/metadata-action`'s own README, which
uses **12 as its example value**, and the action's tracker carries an
issue titled "Tag's sha hash is not long enough in the hash collision
case". This is the ecosystem's own knob for exactly this problem, not
a scheme invented here, and twelve is the Linux kernel's convention
for a durable abbreviated reference. This repository's git already
abbreviates to eight under `core.abbrev=auto`.

With the variable available, `type=sha` stays and the change is three
lines:

- `REVISION` becomes `${GITHUB_SHA:0:12}`;
- the metadata step gets `env: DOCKER_METADATA_SHORT_SHA_LENGTH: 12`;
- the existing step that asserts the `sha-` tag ends in the revision
  the build reports needs **no change at all**, because it already
  compares against `$REVISION`, so it guards the new width for free.

That is three lines in the block M1 is already rewriting, and the
documentation examples that move are the paragraphs M1 is already
editing. Deferring it would mean touching the same three lines and the
same paragraphs twice, which is why it rides M1 rather than becoming
its own issue.

One caveat, from the action's tracker: widening is treated as a
breaking change there, because tag names change shape. Nothing in this
repository consumes a `sha-` tag programmatically, and the existing
tags keep existing, so it costs nothing here.

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
                  ├─> image-publish (matrix: variant)
image (matrix: variant x arch) ─┘   assembles, tags, builds nothing
  amd64: build, push by digest, pull back, smoke
  arm64: build, push by digest, import check
```

`image` runs on push, pull_request and workflow_dispatch after M3.
`image-publish` runs on push and workflow_dispatch, with `--dry-run`
on everything but a push to `main`. Three jobs, which is one more than
today.

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
- **M2 deepens `image-publish` rather than adding a module beside
  it.** The ordering check goes in the only job that moves a tag. An
  earlier draft of this plan added a second job and a reconciler here;
  the deletion test is what removed them, since inlining the ordering
  check back into `image-publish` makes it shorter and no harder to
  read.
- **M3 adds nothing.** It is one `if:` deleted and a paths list; the
  whole of what makes it affordable was built by M1.

## Documentation footprint

Two maintained pages and `AGENTS.md` describe today's behavior in ways
this work falsifies. The pages are in the "maintained maps and
explanations" class of `docs/README.md` and `AGENTS.md` is in the
"guidelines" class, which outranks them; both describe the system as
it is now and are corrected when it moves.

- **M1, `vinga-server/README.md` §Choosing an image.** "**Pair the two
  variants by their SHA tag, not their dated one.** They are built by
  separate jobs that finish minutes apart, so one commit can produce
  `2026-08-06-1048` and `2026-08-06-1047-slim`." After M1 the two
  variants are published by jobs that start together and assemble a
  manifest in seconds, so the dated tags will usually agree. The
  advice to pair by SHA stays correct and stays the advice; its stated
  reason stops being true and is corrected. The same section's "each
  has passed the unit, integration, and smoke lanes" gains the
  stronger fact M1 creates: the published bytes are the smoked bytes,
  by digest.
- **M1, `docs/deployment.md` §Choosing a tag.** Carries the same
  "built by separate jobs that finish minutes apart" reason and gets
  the same correction. It summarizes the server README and links it,
  so the correction goes to the README and this page keeps pointing at
  it.
- **M1, both tag formats, in both pages and the variant table.**
  `2026-08-03-1200` becomes `2026-08-03-120015`,
  `2026-08-06-1047-slim` becomes `2026-08-06-104715-slim`, and
  `sha-3f9362a` becomes a twelve-character example, in the variant
  table's example tags, in `docs/deployment.md`'s "Pin an immutable
  tag" paragraph, and in the "finish minutes apart" passages that
  quote a pair of them. `vinga-server/README.md:3327` also shows a
  revision as `/healthz` output ("from the image tagged `sha-9fd3de5`
  reports `9fd3de5`"), and that pair must stay equal, which is the
  whole point of the sentence.

  The inventory is a grep for `sha-[0-9a-f]\{7\}` and for the literal
  dated examples across the tracked tree, run whole and not through
  `head`. Measured at plan time it is **9 literals in 4 files**:
  `vinga-server/README.md` (3), `vinga-server/tests/unit/test_doctor.py`
  (2, fixture strings in a fake OTA response rather than real tags),
  and two dated feature docs under `docs/features/`. **The feature
  docs do not move**: they record what was true when they were
  written, which is the historical-record class, not a maintained
  description of current behavior.
- **M1 and M3, `AGENTS.md`.** Its CI summary says "A third job,
  `image`, builds and smokes both image variants on everything but a
  pull request". M1 falsifies the first half (it becomes a
  variant-by-architecture matrix plus a publish job) and M3 the
  second. Each half is corrected in the milestone that breaks it.
- **M2, both pages.** The moving-tag paragraphs gain one sentence for
  what the ordering check buys: a moving tag is not moved to an older
  commit's image. Written as what the check does rather than as a
  guarantee, because the check is a read before a write with no lock
  behind it, and the residual is in this plan rather than on a
  user-facing page. It must strengthen, and must not be written so as
  to read as permission to deploy from a moving tag.
- **M2, `.github/workflows/vinga-server.yml` L52-54.** "Never on a
  push to main ... Merges to main run to completion, however many of
  them queue up" is false today, and `d6d76dd` is the counterexample.
  The comment is rewritten to say what per-push groups actually
  guarantee. A comment is not a maintained page, but it is the
  load-bearing explanation of the block it sits on, and leaving it
  would leave the next reader with the belief that cost this
  repository an image.
- **M3, the maintained pages: nothing.** The server README's
  smoke-lane section says "CI runs it against the image it just
  built", which stays true when pull requests run it too, and no page
  claims the image job skips pull requests.

The generated references under `docs/reference/` are untouched:
nothing here changes a CLI command, a configuration field, the API or
an event.

## Verification

This is a workflow-only change, so the honest statement of what can be
verified where matters more than usual.

- **Locally**: `actionlint` (v1.7.7, verified clean against the four
  workflows as they stand today, so a new finding is the change's) and
  a YAML parse. The mechanism itself has been verified against a
  throwaway registry and all three experiments are reproducible: the
  attestation difference between the index digest and the platform
  manifest digest, the two-platform merge preserving four index
  entries, and `--dry-run` printing that index without pushing.
- **On a branch, before merging**: `gh workflow run vinga-server.yml
  --ref <branch>`, which after M1 exercises every step including the
  manifest assembly and its index assertion, against real pushed
  digests, under `--dry-run`. It is the gate for each milestone and
  the run is linked on its PR. **What it cannot reach**, stated
  because earlier drafts claimed otherwise: a dispatch creates no tag,
  so nothing about tag assignment or the ordering check is exercised
  by it.
- **On `main`, after merging**: the first push is the only thing that
  can exercise the real tag move. M1's implementation-doc section
  records the measured job durations and cache-export times of that
  run against the table above, including if they are worse. It also
  records the cache-hit comparison finding 4 asks for, from the
  **second** push rather than the first, since the first runs against
  a cold scope key by construction.
- **Not verifiable before merging, and not claimed**: that a burst
  behaves. Two overlapping runs cannot show it, because displacement
  needs a third, and the second round sharpened the case further: what
  has to happen is that a **newer commit becomes pending before an
  older commit becomes eligible**, which is the order that defeated
  the previous design. Three merges inside one run's duration is the
  setup; the assertions are that all three commits get their dated and
  `sha-` tags, and that the moving tag ends at the newest of them
  whichever run moved it last. M2's section records this unchecked
  with the reason. It can be provoked rather than waited for, by
  merging M3 and a documentation commit in quick succession once M2 is
  on `main`, and that is the intended discharge.
- **Main-only, and unchecked until a merge exercises it**: the
  ordering check skipping a moving tag whose image is newer. A
  dispatch creates no tag and takes the publish's dry path, so it
  cannot reach it, and claiming a gate that cannot run is worse than
  having none. M2's implementation-doc section records it unchecked
  with this reason.

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
- **Dispatch runs leave untagged versions in GHCR**, four per run.
  Pull requests no longer do. Storage is free for a public package and
  nothing resolves an untagged manifest, so this is clutter rather
  than cost, and dispatches are rare. Accepted, with the remedy named
  if the package listing becomes hard to read: a scheduled pruning of
  untagged versions. Not built now.
- **A `main` push whose tests then fail leaves an untagged manifest
  behind.** That is the accepted price of building before the gates
  rather than after them, and it is named under the invariant above
  rather than hidden here.
- **`--dry-run` could diverge from the real push.** It resolves the
  same sources and produces the same manifest; what it does not
  exercise is the registry write. The attestation assertion described
  above runs against the assembled manifest in both modes, so the
  failure this plan most wants to catch is caught dry.

## Milestones

Rewritten after the scope reduction. Where this list and the decisions
above disagree, the decisions are right and this list is a bug.

- [x] **[M1: build each architecture once, publish the tested digests](2026-09-21-build-once-publish-digests-implementation.md#m1-build-each-architecture-once-publish-the-tested-digests)** (PR [#544](https://github.com/rafacm/vinga/pull/544)).

  *Building.* `image` gains an `arch` matrix dimension and loses its
  publishing half, becoming four jobs. Each builds once with the image
  exporter **alone** (never a second `type=docker` output, which
  changes the reported digest from the index to the platform manifest
  and drops provenance), pushes by digest on `push` and
  `workflow_dispatch`, and records `containerimage.digest` as an
  artifact. The amd64 jobs pull that digest back and run the existing
  smoke against it, unchanged. Cache scopes become `variant-arch`,
  exported exactly once each. `needs: [unit, integration]` moves off
  `image` and onto `image-publish`.

  *Publishing.* A new `image-publish` job assembles the manifest with
  `docker buildx imagetools create`, builds nothing and configures no
  cache. It runs on `push` and `workflow_dispatch` only, not on a pull
  request, and passes `--dry-run` on everything but a push to `main`.
  It asserts the assembled index carries both expected platforms and
  an attestation manifest for each.

  *Identity.* The dated tag becomes `YYYY-MM-DD-HHmmss`, keeping its
  variant suffix. `REVISION` becomes `${GITHUB_SHA:0:12}` and the
  metadata step gets `DOCKER_METADATA_SHORT_SHA_LENGTH: 12`, so
  `type=sha` renders `sha-<12>`; the step asserting the tag ends in
  the revision the build reports is unchanged and guards the new
  width for free.

  *Documenting.* Both "finish minutes apart" passages, both tag
  formats wherever they appear as examples, and the first half of
  `AGENTS.md`'s CI summary.

- [x] **[M2: validation overlaps across main pushes; the moving tag is
  ordered by a check](2026-09-21-build-once-publish-digests-implementation.md#m2-validation-overlaps-across-main-pushes-the-moving-tag-is-ordered-by-a-check)** (PR TBD). The workflow-level concurrency group stops
  serializing `main`, each push getting its own group, and keeps
  cancelling superseded pull-request runs. That alone is what stops a
  merged commit losing its image. `image-publish` checks out with
  `fetch-depth: 0` and, before moving a moving tag, reads the
  `VINGA_REVISION` of the image that tag points at and leaves the tag
  alone when that revision is a descendant of this run's commit,
  publishing its immutable tags regardless. No second job and no
  concurrency group are added. Corrects the workflow comment at
  L52-54, and documents what the check buys in the two moving-tag
  passages.

- [ ] **M3: image-affecting pull requests build and smoke
  automatically.** `image` loses `if: github.event_name !=
  'pull_request'` and the comment explaining the exemption, and on a
  pull request builds with `load: true` and pushes nothing, so a fork
  PR is covered with no token and leaves no registry trace.
  `image-publish` does not run on a pull request. `workflow_dispatch`
  stays. Corrects the second half of `AGENTS.md`'s CI summary.

## The review rounds, and what was cut afterwards

Five external rounds produced 27 findings and every one was accepted;
they are recorded below in full, as received, with a resolution note
under each. **Read them as history rather than as the specification.**
After round 5 the plan was cut back on proportion, and three things
those rounds designed are no longer in it: the `image-publish` /
`image-promote` split, the reconciler that walked `main`'s first
parents to promote the newest gated commit, and the two-phase
four-property index validation. The twelve-character revision went
with them, to the follow-up above.

Each of those was a correct answer to a real finding. What none of
them had was a price against not being there, and the answer turned
out to be: roughly five times the workflow code, no wall time, and the
thing protected was a moving tag being briefly stale, against pages
that already say not to deploy from one. The findings were right about
their mechanisms and the mechanisms were not worth having, which is
the proportion test applied one level further out than the rounds were
asked to look. The sections below are kept intact because the design
they converged on is the one to bring back if a moving tag ever has to
be exact, and because the reasoning is worth more than the conclusion.

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

## Plan review round 2

Re-review at `57bf28f5` on 2026-09-21, same backend and model
(codex, `gpt-5.6-sol`, read-only), runtime 187s. The prompt asked
per-finding whether each amendment actually closed its finding or only
read better, and asked specifically for defects the amendments
themselves introduced.

Round 1's findings **3, 4 and 5 came back closed**, and **1 closed for
immutable publication**. Five findings, three of them P1, and two of
the three are against the amendments rather than the original plan.

### 1 (P1): the reuse refusal has a read-then-write race

`image-publish` is ungrouped, so two runs can choose the same second,
both observe the tag absent, and both push different indexes. Seconds
reduce the probability; they do not "remove the collision class", and
a read-before-write check does not enforce immutability under
concurrent publishers.

*Resolution*: the criticism of the claim is accepted in full and the
claim is corrected; the remedy is not adopted, on a measurement the
finding does not have. "Removes the collision class" was wrong and
comes out. What the refusal does is turn a silent overwrite into a red
run, which narrows rather than enforces, and the residual is two
publishers choosing the same value in the same instant.

The remedy proposed is to make the dated tag intrinsically unique by
embedding the revision. That does not reach intrinsic uniqueness
either, because the revision here is seven characters, which is
finding 3 of this round: it would replace one residual with the same
residual the `sha-` tag already carries. Ranking the two is what
decides it. A dated-tag collision needs two commits to complete unit,
integration, every image job and the assembly **within the same
second**. A `sha-` collision needs two commits anywhere in the
repository's history to share a seven-character prefix, which at a
thousand commits is on the order of 0.2 percent and rises with the
square. The second is already accepted as the cost of a
seven-character tag; making the dated tag depend on it too would move
the dated tag's residual **up**, not down.

So: seconds stay, the refusal stays and is described as what it is,
and the plan states the residual and this ranking rather than claiming
enforcement. If the residual ever needs closing, both tags close
together by widening the revision, which is the one lever under both.

### 2 (P1): a displaced promote is not necessarily older than the run that displaces it

Concurrency replacement follows eligibility, not commit order. For
commits A < B < C: A can be promoting while C finishes its gates and
becomes pending, and slower B can then become eligible and displace C.
B passes the ancestry check against A and advances the tag to B,
leaving C, the newest gated commit, unpublished under the moving tag.
The defect is displacement order, not the check's read-then-write
window, and "the survivor's gates later fail" is not the relevant
counterexample, because a run whose promote entered the group has
already passed its gates.

*Resolution*: accepted, and the remedy is adopted. This breaks the
"harmless by construction" claim exactly as the prompt invited it to,
and the break is real: the moving tag would not go backwards, but it
would stop following `main` and stay stale at B with no run red.

`image-promote` becomes a **reconciler rather than a publisher of its
own commit**. Holding its per-variant group, it fetches `origin/main`,
walks it from the tip, and promotes the first commit whose `sha-` tag
exists, whichever run produced it, stopping after a bounded number of
commits. Because `image-publish` pushes the `sha-` tag only after the
unit lane, the integration lane and every image job have passed, "the
newest commit on `main` with a `sha-` tag" is precisely "the newest
gated image", and no separate ancestry check is needed: the walk order
supplies it.

That makes the job idempotent and independent of which run invoked it,
so any surviving promote converges on the same answer and displacement
becomes harmless for a reason rather than by assertion. It also
self-heals: a moving tag left stale by an earlier displacement is
corrected by the next promote that runs, which the current design and
the previous amendment both left permanently stale.

The verification gains the case the finding names, which is not the
one the previous round added: a newer commit must become pending
**before** an older commit becomes eligible.

### 3 (P1): seven-character `sha-` tags are neither collision-proof nor unambiguous promotion sources

Two commits sharing the seven-character prefix get the same supposedly
immutable tag; ungrouped publishers can overwrite it, and a promote
can then copy bytes belonging to the other commit.

*Resolution*: accepted as a defect, with the tag width kept and the
consequence made loud instead. The reuse refusal added for the dated
tag applies to **both** immutable tags, so a prefix collision fails
the run rather than overwriting an existing image, which also removes
the "promote copies the other commit's bytes" path: the colliding
commit never publishes.

The width stays seven because three things are already built on it and
agree by construction: `VINGA_REVISION` in the image's own `ENV`, the
`sha-` tag, and the existing workflow step that asserts the two match.
Widening is a coherent change and a larger one, and it is the single
lever that would also close finding 1's residual, so the plan records
it as the named remedy with its trigger (an actual collision, which
now announces itself as a red run) rather than taking it speculatively
here. The alternative the finding offers, promoting from a digest
carried as a job output, cannot work with finding 2's reconciler,
which by design addresses images from runs other than its own and so
must address them by name.

### 4 (P2): the topology assertion's executable ordering is unspecified

`imagetools create --tag` must push before the tag can be read back,
so a post-push assertion detects a malformed index only after the
immutable tags exist; and `--dry-run` prints an index but creates no
tag from which `.Image` can read both platform configs. The amendment
listed the right properties and no mechanism that checks them before
publication in both modes.

*Resolution*: accepted and adopted as specified. Validation is two
phases. First `imagetools create --dry-run`, whose raw index is parsed
and whose entries are then resolved **by digest** against the same
repository, which works because the per-platform manifests were pushed
by digest before any tag existed: `imagetools inspect "$IMAGE@<digest>"`
reaches every platform manifest and every config without a tag. All
four properties are checked there. Only then does the tagged push run,
and afterwards the tag is inspected again and required to resolve to
the same index digest the dry run validated.

This is strictly better than what the amendment said and costs one
extra inspect. It also makes the dispatch gate genuinely equivalent to
the push gate for this check, which was the amendment's stated
intention and not something it achieved.

### 5 (P2): the live-defect claim has not excluded deletion or another cancellation cause

A cancelled run plus an absent tag is consistent with displacement but
does not establish that the image job never ran or that the tag was
never created; later package cleanup would look the same.

*Resolution*: accepted as stated, and closed by measurement rather
than by softening the claim. The run is `34632623405`. Its
`GET /actions/runs/34632623405/jobs` returns **an empty job list**: not
a failed job, not a cancelled job, none at all. `created_at` and
`run_started_at` are both `2026-09-11T18:19:29Z` and `updated_at` is
`2026-09-11T18:33:59Z`, which is one second after `f943bc6`'s run was
created at `18:33:58Z`.

So the run sat pending for fourteen minutes without starting a single
job and was terminated at the moment the next push entered its group.
That excludes both alternatives the finding raises: nothing failed,
because nothing ran; and the tag's absence needs no deletion to
explain it, because the job that would have created it never started.
The claim stands as written, and the plan now cites the empty job list
and the timestamp coincidence rather than the tag's absence alone,
which is the evidence that actually carries it.

## Plan review round 3

Re-review at `3ec504ef` on 2026-09-21, codex with `gpt-5.6-sol`,
read-only, runtime 201s. The prompt asked per finding whether round
2's amendments closed it, told the reviewer which two amendments had
changed the design and invited it to break them, and asked it to judge
the two remedies that had been declined **on their reasoning rather
than their conclusion**. That last instruction is what produced the
round's most valuable finding, against an argument of mine that was
simply wrong.

Round 2's finding 5 came back closed. The other four came back open,
with eight findings, four of them P1.

Three facts were established by experiment and measurement while
resolving these, and each one changed a decision:

- **`imagetools create --dry-run --metadata-file` writes nothing.**
  Verified locally: exit 0, no file. A real `create` does write it,
  carrying `containerimage.descriptor.digest`. So the round's finding
  4 is right that the dry-run index digest is not obtainable, and the
  comparison the previous amendment specified is not executable.
- **A tag created from another tag preserves the index digest
  exactly.** Staging under one tag, then creating two more from it,
  gave all three the same digest, so validate-then-tag is executable.
- **Most `main` commits legitimately have no image.** In the last 45
  commits on `main`, four have a `sha-` tag, and there are runs of 22
  and 13 consecutive commits without one, because a documentation
  push does not trigger this workflow at all. This falsifies a rule
  the previous amendment had introduced.

### 1 (P1): a failed phase-2 assertion leaves a `sha-` tag the reconciler trusts

Phase 2 pushes the immutable tags and only then asserts. If the
assertion fails the tag already exists, and a later reconciler walking
by tag existence alone can promote that publication, so "a `sha-` tag
means every gate passed" is false.

*Resolution*: accepted. Closed by making the reconciler validate what
it is about to promote rather than trusting a name: before moving the
moving tag it runs the same topology and config assertions against the
candidate index, and refuses a candidate that fails them. That closes
it for the moving tag whatever the publish side did, which is the
property that matters, since the moving tag is what a careless
deployment follows. An immutable tag left behind by a red publish
remains, and is a red run somebody sees; the plan says that rather
than implying otherwise. The reviewer's staging-reference remedy was
verified to work and is recorded as the stronger option, not taken
because reconciler-side validation closes the same hole without a
second tag namespace to create, name, race and prune.

### 2 (P1): the dated-tag collision argument is mathematically backwards

Appending the revision does not replace the same-second residual with
the prefix residual. A composite `timestamp-revision` tag collides
only when **both** collide, which is strictly less likely than either.
"Would move the dated tag's residual up" is wrong.

*Resolution*: accepted without reservation. The argument was wrong,
and it was mine, written to justify a conclusion rather than derived.
A conjunction is not a replacement, and stating it as one is the same
error as claiming more than was measured, in a form that looks like
reasoning.

The conclusion goes with it. The dated tag becomes
`YYYY-MM-DD-HHmm-<revision>`, composite, and the argument for it is
the reviewer's: it narrows the collision domain to the conjunction.
Minute resolution returns, since the revision now carries the
uniqueness and seconds were only ever there to do that job.

### 3 (P1): the documentation is still planned to claim immutability the design does not provide

Round 2 conceded that concurrent publishers can both see an absent tag
and overwrite each other, while the documentation footprint kept
"immutable and never reused" as an unconditional guarantee.

*Resolution*: accepted, and closed by finding 6's remedy rather than
by weakening the documentation. With a 12-character revision in both
immutable tags, a collision requires two commits sharing twelve hex
characters, on the order of 1e-9 at this repository's size, which is
the same order of assumption git itself makes when it abbreviates. At
that point "never reused" is an honest thing to write, the reuse
refusal enforces it against sequential reuse, and the residual is
named in the plan rather than in the user-facing pages. Had the width
stayed at seven, the pages would have had to be reworded instead, and
the plan says so explicitly so the dependency between the two is not
lost.

### 4 (P1): phase 1 cannot obtain the digest phase 2 compares

Parsing and reserializing the dry-run index does not yield its digest,
and the plan named no mechanism that would.

*Resolution*: accepted; verified; the comparison is removed. The local
check above shows `--dry-run --metadata-file` writes no file at all,
so the previous amendment specified something that cannot run. The
digest comparison is dropped and replaced by validating the **same
four properties twice**: once against the dry-run index, whose entries
are resolvable by digest because the per-platform manifests were
pushed before any tag existed, and once against each final tag after
the push. Neither validation needs a parent digest, both are
executable with commands the plan now names, and the second one
catches anything the push could have changed.

### 5 (P2): dispatch cannot execute the claimed two-phase validation or the reconciler verification

Dispatch creates no tag and never runs `image-promote`, so the
post-tag phase and the claims that idempotence and stale-tag repair
are "provable on a dispatch" are not executable.

*Resolution*: accepted; both claims were false and are corrected
rather than rescued. Dispatch runs phase 1 only. Phase 2, the
reconciler's idempotence and its stale-tag repair are **main-only
checks**, recorded in the verification section as such, unchecked
until a merge exercises them, with the reason. The previous round
added the idempotence check as a cheap pre-merge reassurance and it
was not one; claiming a gate that cannot run is worse than having no
gate, because it stops anybody looking for a real one.

### 6 (P2): the seven-character remedy defers a cheap fix until after it breaks a publication

Coordinating `VINGA_REVISION`, the tag and its assertion is exactly
what a workflow-only plan can do, and "wait for a collision" is not a
sound trigger for an avoidable namespace defect.

*Resolution*: accepted, and adopted after asking the maintainer,
because the change is user-visible: `/healthz` reports the revision
and both maintained pages show example tags. **The revision becomes 12
hexadecimal characters**, derived once and used in four places that
already have to agree, `VINGA_REVISION` in the image's `ENV`, the
`sha-` tag, the dated tag's suffix and the reconciler's lookup, with
the existing workflow step that asserts tag and revision are equal
extending to cover it. Collision falls from roughly 2e-3 to roughly
2e-9 at a thousand commits. This is the finding that also closes 2 and
3, which is why it is worth its own milestone footprint rather than a
line.

### 7 (P2): the reconciler's bound and history-rewrite behavior are not decided

The bound is never given or derived, and force-push behavior is
undefined while the documentation footprint proposes an unconditional
"never moves to an older commit's image".

*Resolution*: accepted, and measuring it found that the previous
amendment's rule was wrong rather than merely unspecified. It said a
walk that finds no tagged commit fails the run. In the last 45 commits
on `main` only four carry a `sha-` tag, with runs of 22 and 13
without, because a documentation-only push does not match this
workflow's `paths` and so never builds an image. A fixed bound with a
failure at the end of it would fire on ordinary weeks.

The walk is therefore bounded by **distance from what is already
published**, not by a constant: candidates are the commits between the
moving tag's current revision and the tip, newest first, and the first
one carrying a validated `sha-` tag wins. Finding none is the **normal
case** and is a quiet no-op, not a failure, because it means nothing
newer than the published image has produced one yet. A hard cap of 200
commits remains only for the case where the published revision is not
an ancestor of the tip, and reaching it fails loudly.

That case is the force-push one, and it is now stated: if the moving
tag's revision is not in `origin/main`'s history, history was
rewritten under the tag, the reconciler promotes the newest tagged
commit in the current history within the cap, and it reports that it
did so. The documentation guarantee is scoped to match, "never moves
to an older commit's image on ordinary fast-forward history", because
after a rewrite "older" no longer has a single meaning.

### 8 (P2): phase 2 does not say that every final tag must be checked

M1 creates dated and `sha-` tags, and the reconciler trusts the
latter, but the assertion named only "the tag".

*Resolution*: accepted, one word for one word. Every final tag this
job creates, the dated one, the `sha-` one and the moving one when it
is written, is resolved after assignment and required to equal the
validated index. With a 12-character revision there are two immutable
tags per publish and the check is a loop, not a special case.

## Plan review round 4

Re-review at `b73ce98f` on 2026-09-22, codex with `gpt-5.6-sol`,
read-only, runtime 236s. The prompt named the four things round 3 had
changed and asked the reviewer to attack those hardest, to hunt for
contradictions left by fourteen amendment commits, and to say plainly
whether someone outside these conversations could implement the plan
as written.

**Every round-3 finding came back closed on the design**, and the
verdict says the build-once and validation design is coherent and the
~500s projection is supportable as a projection from the measured
critical paths. What is still open is the plan as a **contract**: its
milestone list and parts of its algorithm section had not caught up
with three rounds of amendments, which the verdict says plainly is
enough for an implementer to build the wrong tag format, the wrong
event scope or the wrong history walk.

That is the right place for a fourth round to land, and it is a
failure mode worth naming: fourteen amendments that each corrected a
decision left the sections that *restate* those decisions behind, and
a plan is read by its milestone list more often than by its reasoning.

### 1 (P1): the milestone contract still instructs the superseded design

M1 still said seconds in the dated tag, `image-publish` running on
every event, that it "moves the tags", and phase 2 checking "the tag"
singular. None of those survived rounds 2 and 3, the moving tag now
belongs to M2, and the twelve-character revision was in no milestone
at all despite the footprint saying it must not be split from the tag
changes.

*Resolution*: accepted in full. Both milestones are rewritten from the
settled design rather than patched, and the revision widening is
assigned explicitly to M1 with its documentation. This is the finding
that most justified a fourth round: everything it names was decided
correctly somewhere else in the document and instructed wrongly here.

### 2 (P1): the reconciler cannot both start at the moving tag and treat it as no input

The range is defined as the commits between the moving tag's revision
and the tip, and the force-push branch turns on whether that revision
is in `origin/main`, while the requirements said nothing is read from
the moving tag except the idempotence comparison. Nothing said how the
revision is extracted from a multi-platform index, whether the two
platform configs must agree, or what happens when the tag is absent,
malformed, or still carries a seven-character revision from before
this change.

*Resolution*: accepted; the contradiction is mine and the sentence
that created it was written for a design that no longer exists. The
moving tag is now an explicit, validated input to range selection,
with the reading specified: inspect its index, require one config per
expected platform and one common `VINGA_REVISION` of 7 or 12
hexadecimal characters, and resolve it to a unique commit. The
bootstrap cases are stated rather than implied, and the seven
character case is one of them, because the first promote after M1
lands necessarily reads a tag written by the old scheme.

### 3 (P2): "derived once" does not say how a twelve-character tag is produced

`REVISION` is `${GITHUB_SHA:0:7}` in the workflow while
`docker/metadata-action` independently generates
`type=sha,format=short`, and the existing step only detects
disagreement afterwards. Changing the first does not stop the second
producing a seven-character tag, and nothing said how the same value
reaches the dated tag.

*Resolution*: accepted, and it is the finding most likely to have cost
an implementation cycle: "derived once" described an intention with no
mechanism, and the assertion I leaned on detects disagreement rather
than creating agreement.

`type=sha` is dropped. Both immutable tags are generated as `type=raw`
from the one `REVISION` the job already computes, so there is one
value and two tags rendered from it, and "derived once" becomes
literally true instead of aspirational. The existing equality
assertion stays as a guard, which is all it ever was. The reviewer's
other option, `DOCKER_METADATA_SHORT_SHA_LENGTH=12`, is not taken:
this session cannot verify that environment variable's behavior
against the pinned action version, and a mechanism that cannot be
checked before it runs is the wrong one to build a tag scheme on.

### 4 (P2): "newest first" is undefined when the range contains merge commits

A plain revision walk over `published..origin/main` reaches commits
through every merge parent, so a tagged commit from merged or
reintroduced history could be selected although it is not a position
on `main`'s own sequence. The repository rebase-merges by convention,
but the plan makes an unconditional guarantee and explicitly handles
rewritten history, so convention does not define the algorithm.

*Resolution*: accepted. The walk is specified as **first-parent**,
from the tip toward the published revision, including merge commits
themselves and excluding their side histories, with the same rule
applied to the newest 200 commits on the force-push path. The
reviewer's note about a tip whose image job is still running is
adopted as written, because it states the correct behavior and the
reason: that commit is skipped for this invocation, and its own
promote, or any later surviving one, reconciles once its immutable tag
exists. That is the self-healing property doing its job rather than an
edge case needing separate handling.

### 5 (P2): a superseded dispatch claim survives in the reconciler requirements

One sentence still called idempotence "cheap to check on a dispatch",
which round 3 had already recorded as false and corrected in the
verification section.

*Resolution*: accepted. The sentence is replaced with the settled
rule. Worth recording rather than fixing silently: this is the second
time this exact claim has had to be removed, having been corrected in
one section while surviving in another, which is what a plan amended
fourteen times does when a correction is applied where it was found
rather than everywhere it appears.

## Plan review round 5

Re-review at `3f587647` on 2026-09-22, codex with `gpt-5.6-sol`,
read-only, runtime 152s. The prompt gave this round one job, whether a
competent implementer who had read only this plan and the repository
could build the three milestones correctly, and explicitly ruled
design improvements and extra hardening out of scope, since four
rounds of those had already converged.

Three findings, and the first verdict that is not "not ready":
**ready after the P1/P2 amendments**. It also records no finding
against the measurement sections, and confirms that no later amendment
falsified the measured values or the labelled ~500s projection.

### 1 (P1): the slim variant's immutable tags are unspecified

The rewritten M1 gave the immutable tags as `sha-<revision>` and
`YYYY-MM-DD-HHmm-<revision>` with no variant suffix, while the
documentation footprint and the README preserve `sha-...-slim` and
`...-1047-slim`. An implementer would render identical tags for both
variants, and the two publishers would race or trip the reuse refusal
instead of publishing.

*Resolution*: accepted; this is a defect the milestone **rewrite**
introduced, one commit earlier, by restating a decision more crisply
than it was true. `matrix.suffix` exists today on both immutable tags
(`.github/workflows/vinga-server.yml` L1601-1602) and on the assertion
at L1621, and dropping it was not a decision anybody took. M1 now says
the suffix stays on both tags and shows all four spellings, and the
reconciler's lookup is stated as per variant, since it resolves a
suffixed name.

Worth recording for its shape rather than its size: rounds 1 to 4
found defects in the design and this one found a defect in the
document's account of a design that was already right. A rewrite is an
edit like any other and gets the same scrutiny, which is exactly why
the round after a rewrite is not optional.

### 2 (P2): the burst verification cannot create the runs it needs

The verification proposed provoking the three-run case by merging M3
and a documentation commit in quick succession. This workflow's
`paths` do not match an ordinary documentation change, which runs
`docs.yml` instead, so that commit creates no run here and cannot
enter the promotion group.

*Resolution*: accepted, and it is the same fact as the measurement two
sections earlier in this very plan, which found 22 consecutive `main`
commits with no image precisely because documentation pushes do not
trigger this workflow. Measuring something and then writing a
verification that contradicts it is a failure to carry a finding
across a document. The discharge is now three pushes that each touch a
watched path, arranged so the newest run's promote becomes pending
before an older one becomes eligible, which is the ordering the case
actually turns on.

### 3 (P2): the footprint says M3 changes no documentation

`AGENTS.md` says "A third job, `image`, builds and smokes both image
variants on everything but a pull request". M1 falsifies the first
half and M3 the second, and the footprint listed neither.

*Resolution*: accepted. `AGENTS.md` is in the **guidelines** class of
the authority taxonomy, which outranks the maintained maps, so it was
the worst page to have missed and the footprint's own framing
("beyond what the generated-reference drift checks already catch")
should have caught it. Each half is corrected in the milestone that
breaks it. The footprint's opening sentence, which counted three
maintained pages, is corrected with it.
