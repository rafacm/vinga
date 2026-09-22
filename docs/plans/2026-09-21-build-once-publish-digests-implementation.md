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
