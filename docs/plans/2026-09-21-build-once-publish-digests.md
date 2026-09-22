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

A second experiment closed half of the topology question the first one
left open. Two single-platform builds, pushed by digest separately and
then merged by one `imagetools create`, produce an index with four
entries: one `linux/amd64` manifest, one `linux/arm64` manifest, and
two `attestation-manifest` entries. That is the same shape
`ghcr.io/rafacm/vinga-server:latest` carries today, read back with
`imagetools inspect --raw` on the live tag. So merging two indexes
preserves both platforms and both attestations.

It does not show that each attestation is associated with the right
subject, that no nested or duplicate platform index crept in, or that
the configs say what they should, and an alpine image cannot show
those for this repository's Dockerfile anyway. Those are properties of
the real artifact, so they are asserted on the real artifact rather
than inferred. `image-publish` reads the assembled index back and
requires all four:

- exactly one manifest for each expected platform, and no others;
- for each, an attestation manifest whose
  `vnd.docker.reference.digest` names **that** platform manifest;
- no nested index and no duplicate platform entry;
- both platform configs carrying the expected `VINGA_REVISION` and
  `VINGA_VARIANT`.

**The order it runs in is the whole of whether it works**, and the
first two attempts at stating that order both specified something that
cannot run.

The mechanism is settled by a local check rather than by reading the
flags: `imagetools create --dry-run --metadata-file <f>` exits 0 and
**writes no file**, while a real `create` writes one carrying
`containerimage.descriptor.digest`. So there is no way to learn the
dry-run index's digest, and any design that compares it to the pushed
one is not implementable. That comparison is dropped.

What replaces it is validating the same four properties twice, which
needs no parent digest and is executable in both places:

1. **Before any tag exists**, against the dry-run index.
   `imagetools create --dry-run` prints it; its entries are resolved
   individually with `imagetools inspect "$IMAGE@<entry-digest>"`,
   raw for the manifests and `--format '{{json .Image}}'` for the
   configs. This works precisely because the per-platform manifests
   were pushed by digest before anything was tagged, so every entry is
   already addressable.
2. **After the push**, against **every** final tag this job creates,
   not one of them: the dated tag and the `sha-` tag, each resolved
   and each required to carry the same validated topology. The
   reconciler trusts the `sha-` tag, so checking only the dated one
   would check the tag nothing depends on.

A failure in phase 2 leaves an immutable tag behind, which is a red
run somebody sees, and the moving tag is protected from it separately
by the reconciler validating its candidate.

The stronger alternative was verified and not taken: push the
assembled index under a run-scoped staging tag, validate that, then
create the final tags from it, which works and preserves the index
digest exactly (checked locally: three tags, one digest). It closes
the same hole as reconciler-side validation and costs a second tag
namespace to name, race and prune, so it is recorded here as the
option to reach for if the reconciler's validation ever proves
insufficient.

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
`needs: [unit, integration, image]`, and `image-promote` follows it.

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
  `cancel-in-progress: false`. It is a **reconciler, not a publisher
  of its own commit**: see below.

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
cancelled`.

The evidence that carries this is the run's own record, run
`34632623405`, and not the missing tag, which on its own would also be
consistent with a later deletion or with some other failure:

- `GET /actions/runs/34632623405/jobs` returns an **empty job list**.
  Not a failed job, not a cancelled job, none at all. Nothing ran, so
  nothing failed, and the image job never started.
- `created_at` and `run_started_at` are both `18:19:29Z`, and
  `updated_at` is `18:33:59Z`, one second after `f943bc6`'s run was
  created at `18:33:58Z`. It sat pending for fourteen minutes and was
  terminated at the moment the next push entered its group.

`d6d76dd1` is an ancestor of `origin/main`, and
`ghcr.io/rafacm/vinga-server:sha-d6d76dd` does not exist while
`sha-2f9675f`, `sha-f943bc6` and `sha-623f170` all do. With the empty
job list, the tag's absence needs no deletion to explain it: the job
that would have created it never started. A merged commit on `main`
has no image, and no run went red to say so.

The workflow's own comment that "Merges to main run to completion,
however many of them queue up" has been false since it was written.

Displacing a pending `image-promote` would not be harmless if the job
promoted its own commit, and the second review round is where that
became clear. Replacement follows **eligibility**, not commit order.
For commits A < B < C, A can be promoting while C finishes its gates
and becomes pending, and a slower B can then become eligible and
displace C. B is newer than A, so an ancestry check waves it through,
and the moving tag settles on B while C, the newest gated commit,
never gets it. The tag has not gone backwards; it has stopped
following `main`, permanently, with no run red.

### image-promote reconciles, it does not publish its own commit

So `image-promote` does not ask "should I promote my commit". Holding
its per-variant group, it fetches `origin/main` and considers the
commits **between the moving tag's current revision and the tip**,
newest first, promoting the first one that carries a `sha-` tag whose
index passes validation, whichever run produced it.

That works because of what publishing a `sha-` tag already means.
`image-publish` runs only after the unit lane, the integration lane
and every image job have passed, so "the newest commit on `main`
carrying a `sha-` tag" is exactly "the newest gated image". The walk
order supplies the ordering guarantee, so there is no separate
ancestry check to get wrong and no read-then-write window to reason
about.

Three properties follow, and they are why this shape rather than a
smarter group:

- **Idempotent and invocation-independent.** Any surviving promote
  computes the same answer, so displacement is harmless for a reason
  instead of by assertion.
- **Self-healing.** A moving tag left stale by an earlier
  displacement is corrected by the next promote that runs. Both the
  current design and this plan's first draft left it stale forever.
- **It needs no digest artifacts**, because it addresses images by
  name, across runs. That is also why the promotion source cannot be a
  digest carried as a job output: by design this job publishes images
  its own run did not build.

The promotion itself is one more
`docker buildx imagetools create`, copying an index rather than
building anything.

### What the reconciler needs in order to be right

The ancestry check this section used to specify is gone with the
design that needed it. A run no longer asks whether its own commit is
newer than the published one, so `git merge-base --is-ancestor` is not
used at all, and the AGENTS.md trap about ancestry across a rebase
merge stops being something this workflow has to reason about. That is
a real simplification and not just a move: one fewer wrong answer
available.

What the reconciler needs instead is four things.

- **History and a current tip.** `fetch-depth: 0` and a fetch of
  `origin/main` before the walk. A shallow checkout has no history to
  walk, and a stale tip would promote something that is no longer the
  newest.
- **A bound that is a distance, not a constant, and a no-op when the
  walk finds nothing.** The previous draft said a walk that found no
  tagged commit should fail the run. Measuring killed that rule: of
  the last 45 commits on `main`, four carry a `sha-` tag, and there
  are runs of 22 and 13 that do not, because a documentation-only push
  does not match this workflow's `paths` and so never builds an image
  at all. A fixed bound with a failure at the end of it would fire on
  ordinary weeks.

  The walk therefore spans the commits from the moving tag's current
  revision to the tip, which is short by construction and usually one.
  Finding nothing newer than what is published is the **normal case**
  and is a quiet no-op. A hard cap of 200 commits exists only for the
  case below, and reaching it fails loudly.

- **Stated behavior when history is rewritten.** If the moving tag's
  revision is not in `origin/main`'s history, something force-pushed
  under the tag and "the commits since it" has no meaning. The
  reconciler then considers the newest 200 commits of the current
  history, promotes the newest tagged one, and reports that it took
  that path. The documentation guarantee is scoped to match, since
  after a rewrite "older" has no single meaning.

- **Validation of the candidate before promoting it.** A `sha-` tag
  exists because `image-publish` created it, and `image-publish` can
  create it and then fail its own post-push assertion, so tag
  existence is not proof the publication completed. The reconciler
  runs the same topology and config assertions against the candidate
  index and refuses a candidate that fails them, walking on to the
  next. That is what makes the moving tag safe whatever the publish
  side did, which matters more than the immutable tags because the
  moving tag is the one a careless deployment follows.
- **An idempotent exit.** If the moving tag already resolves to the
  same index as the chosen commit's `sha-` tag, the job does nothing
  and says so. That is what makes a second promote against an
  unchanged `main` a no-op, which is the property the whole design
  leans on and is cheap to check on a dispatch.
- **Nothing read from the moving tag except for that comparison.** The
  moving tag is an output of this system, never an input to its
  decision. The decision comes from `main` and from which `sha-` tags
  exist, both of which are facts a displaced run and a surviving run
  agree on.

### The revision becomes twelve characters, and both immutable tags carry it

`type=raw,value={{date 'YYYY-MM-DD-HHmm'}}` gives two commits
publishing inside the same minute the same "immutable" tag, and the
later registry write wins. Serialization plus a six-minute publish
makes that unreachable today; M1 cuts the publish to seconds and M2
permits overlap, so it becomes reachable exactly when merges burst.

The plan's first two answers to this were both wrong, and the second
was wrong in a way worth recording. It argued that embedding the
revision in the dated tag would raise its residual to the `sha-` tag's
seven-character one. A composite tag collides only when **both** parts
collide, which is strictly less likely than either alone; a
conjunction is not a replacement. The argument was constructed to
defend a conclusion rather than derived, which is the same failure as
claiming more than was measured, wearing reasoning's clothes.

So the real constraint was never the dated tag. It is the width of the
revision, which both immutable tags depend on, and which is a
pre-existing defect this plan surfaces rather than creates: at seven
hexadecimal characters, two commits sharing a prefix is on the order
of 2e-3 at a thousand commits and grows with the square.

**The revision becomes twelve hexadecimal characters.** It is derived
once and used in four places that already have to agree:

- `VINGA_REVISION` in the image's `ENV`, which `/healthz` reports;
- the `sha-` tag;
- the dated tag, which becomes `YYYY-MM-DD-HHmm-<revision>`, composite
  and back to minute resolution, since the revision now carries the
  uniqueness that seconds were only ever added to supply;
- the reconciler's lookup.

The existing workflow step that asserts the `sha-` tag ends in the
revision the build reports extends to cover the new width, so the four
stay one value rather than four that must agree. Collision falls to
roughly 1e-9 at a thousand commits, which is the order of assumption
git itself makes when it abbreviates, and at that point "never reused"
is an honest thing for the maintained pages to keep saying.

This was confirmed with the maintainer before being adopted, because
it is user-visible: `/healthz` changes what it reports and both
maintained pages change their example tags.

`image-publish` also refuses reuse, on both immutable tags: if either
already resolves and names a digest other than the one being
published, the job fails rather than overwriting. That is enforcement
against **sequential** reuse and it is a read before a write, so it
does not close the concurrent case; with a twelve-character revision
the concurrent case needs two commits sharing twelve hex characters
and publishing at once, and the residual is recorded here rather than
in a user-facing page.

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
- **M1, the revision width and both tag formats, in both pages and
  the server README's variant table.** Every example tag moves:
  `2026-08-03-1200` becomes `2026-08-03-1200-3f9362a1b2c3` and
  `sha-3f9362a` becomes `sha-3f9362a1b2c3`, in the variant table, in
  `docs/deployment.md`'s "Pin an immutable tag" paragraph, and in the
  "finish minutes apart" passages that quote a pair of them. The
  pages call these tags immutable and never reused, and the twelve
  character revision is what lets that sentence stay as written
  rather than be reworded; the dependency runs that way round and
  the milestone must not split them.
  `vinga-server/README.md` also documents what `/healthz` reports, so
  wherever a seven-character revision appears as an example of that,
  it moves too. The inventory is a grep for the literal example
  revisions across the tracked tree, run whole and not through
  `head`, and its output is what the milestone works from.
- **M2, both pages.** The moving-tag paragraphs gain one sentence for
  the guarantee the reconciler makes explicit: on ordinary
  fast-forward history a moving tag never moves to an older commit's
  image. The scope clause is part of the sentence, not a footnote,
  because after a force-push "older" has no single meaning and the
  reconciler's stated behavior there is different. This strengthens
  rather than weakens the existing advice not to deploy from a moving
  tag, and must not be written in a way that reads as permission to.
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

- **Locally**: `actionlint` (v1.7.7, verified clean against the four
  workflows as they stand today, so a new finding is the change's) and
  a YAML parse. The mechanism itself has been verified against a
  throwaway registry and all three experiments are reproducible: the
  attestation difference between the index digest and the platform
  manifest digest, the two-platform merge preserving four index
  entries, and `--dry-run` printing that index without pushing.
- **On a branch, before merging**: `gh workflow run vinga-server.yml
  --ref <branch>`, which after M1 exercises every step up to and
  including phase 1 of the validation, against real pushed digests. It
  is the gate for each milestone and the run is linked on its PR.
  **What it cannot reach**, stated because two earlier drafts claimed
  otherwise: a dispatch creates no tag, so phase 2 does not run, and
  it never runs `image-promote`, so nothing about the reconciler is
  exercised by it.
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
- **Main-only, and unchecked until a merge exercises them**: phase 2
  of the validation, the reconciler's idempotence (a second promote
  against an unchanged `main` is a no-op), and its repair of a moving
  tag left stale. A previous draft called these provable on a
  dispatch. They are not, because a dispatch creates no tag and never
  runs the promote job, and claiming a gate that cannot run is worse
  than having none, since it stops anybody looking for a real one.
  M2's implementation-doc section records them unchecked with this
  reason and ticks them from the first merges.

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
  [unit, integration]` moves from the build to the publish. The dated
  tag gains seconds, `YYYY-MM-DD-HHmmss`, and the job refuses to reuse
  either immutable tag when it already names different bytes. The
  index topology is validated in two phases, against the `--dry-run`
  index resolved by digest before anything is tagged, then re-checked
  against the tag afterwards. Documents the two "finish
  minutes apart" passages and the new tag format.
- [ ] **M2: validation overlaps across main pushes; the moving tag
  alone stays ordered.** The workflow-level concurrency group stops
  serializing `main` (each push gets its own group) and keeps
  cancelling superseded pull-request runs. Publication splits:
  `image-publish` keeps the immutable tags and takes no group at all,
  so it cannot be displaced while pending; a new `image-promote` moves
  the moving tag in an ordered, non-cancelling group per variant. It
  reconciles rather than publishing its own commit: `fetch-depth: 0`,
  fetch `origin/main`, consider the commits between the moving tag's
  revision and the tip newest first, and promote the first whose
  `sha-` tag exists and whose index passes the same validation
  `image-publish` runs, whichever run produced it. Finding nothing is
  a no-op, not a failure. A 200-commit cap covers the force-push case,
  whose behavior is stated rather than left to happen. That is
  idempotent, self-healing and independent of which run survives
  displacement. Corrects the workflow's false comment about merges
  running to completion, and documents the guarantee in the two
  moving-tag passages.
- [ ] **M3: image-affecting pull requests build and smoke
  automatically.** `image` loses `if: github.event_name !=
  'pull_request'` and the comment explaining the exemption, and on a
  pull request builds with `load: true` and pushes nothing, so a fork
  PR is covered with no token and leaves no registry trace.
  `image-publish` and `image-promote` do not run on a pull request.
  `workflow_dispatch` stays.

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
