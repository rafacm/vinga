# Langfuse as an optional telemetry backend, with capture attachment

Plan for [issue #67](https://github.com/rafacm/vinga/issues/67).
Companion implementation doc:
`2026-09-12-langfuse-backend-implementation.md`, one section per
milestone, appended in the same change that ticks the milestone
checklist.

## Goal

The #48 field-test workflow needed the trace, the transcripts and the
audio side by side, and #66 delivered only the first two off-host.
After this issue, a Langfuse deployment (self-hosted or the managed
offering, only endpoint and credentials differing) shows a vinga
session as one Langfuse session of per-turn traces with stage spans
and token counts, and, behind a separate default-off flag, a closed
session's capture WAV and manifest attached to that session's trace,
playable in the UI. Layer 1 is configuration plus whatever attribute
aliases Langfuse's ingestion actually keys on, verified live rather
than assumed; layer 2 is the one new vinga surface, an uploader that
runs off the audio path, survives every failure as a warning, and is
priced as what it is: room audio deliberately leaving the pod under a
flag that neither capture nor telemetry implies.

## The issue's decisions, restated

- Two layers, deliberately separate. Layer 1 needs no vinga code
  beyond #66 except mapping tweaks, which belong in the #66 span
  attributes and are recorded as findings. Layer 2 is the
  vinga-specific code: WAV and manifest attached to the session
  trace after `session_closed`, off the audio path, upload failure a
  warning and never a session failure.
- The `langfuse` Python SDK is an optional extra
  (`vinga-server[langfuse]`), the `[otel]` pattern, never core.
- Layer 2 has its own flag, `server.telemetry.attach_captures`,
  default false. Capture on plus telemetry on must not imply
  recordings leave the pod. Flag on with capture off is a no-op.
- Where Langfuse runs is not this issue's business: endpoint and
  credentials only, nothing assuming a particular deployment,
  nothing the managed offering does not provide or the reverse.
- From the issue's standing comment: exporters are optional taps on
  the content side, never additions to the metadata-only JSON log
  surface; each declares egress and `server.local_only` refuses to
  build one.
- Acceptance as written: session grouping with per-turn traces and
  `gen_ai` token counts; the handover span event followable;
  attached WAV playable plus manifest; blackholed-endpoint failure
  verified; the server boots with neither extra installed; both
  example configs document the flags; a changelog entry (which is a
  `changelog.d/` fragment under the #467 regime).

## Premise corrections, recorded up front

Two sentences in the issue's comment are false against the merged
code, and the plan builds on the code:

- The #66 exporter consumes nothing from the events table. It is an
  in-process `EventTap` on the live emit seam
  (`telemetry.py`, `device/session.py:262`, `app.py:277`) and never
  opens a database connection, so this issue's uploader is not "the
  events table's first real consumer" either way.
- The events table already has real consumers: the metrics views
  read it (`conversations/views.py`), the API counts it, erasure
  deletes from it.

Neither changes what this issue builds; both are recorded so the
plan is reviewed against the repository rather than the comment.

## Open questions, resolved

### Layer 1's mapping is verified live, and the aliases are findings

The repository records zero facts about which attributes Langfuse's
OTLP ingestion keys sessions, users or trace names on; the only
Langfuse facts on record are about masking, retention and deletion
(`docs/architecture/observability-surfaces.md:148-175`). The plan
therefore does not assert the mapping. Milestone 1 stands up a local
self-hosted Langfuse (its own compose file, on the operator's
machine, nothing committed that names a deployment), points the #66
exporter at its OTLP endpoint through the same environment variables
the SDK already reads (`OTEL_EXPORTER_OTLP_ENDPOINT`,
`OTEL_EXPORTER_OTLP_HEADERS` carrying the Basic pk:sk pair, exactly
the #66 credential posture: a second home in vinga config for facts
the SDK reads is two homes that can disagree,
`config/models.py:791-796`), drives a multi-turn simulator
conversation with a handover, and records what renders: whether
traces group into a session, what the session view keys on, whether
`gen_ai.usage.*` shows as token counts on generations, and how the
handover span event reads. The walkthrough record lands in the
implementation doc the way #66's Jaeger walkthrough did, including
what failed first.

The expected finding, stated so the review can attack it: Langfuse
documents session grouping off a `langfuse.session.id` (or the
generic `session.id`) span attribute and user grouping off
`langfuse.user.id`/`user.id`, which #66's vocabulary
(`vinga.session.id`) deliberately does not spell. If the walkthrough
confirms it, the aliases are added to the exporter's literal
attribute tables (`SESSION_ATTRIBUTES`, `CONTEXT_ATTRIBUTES` in
`telemetry.py`) as second spellings of facts every span already
carries: the session id aliased for grouping, and the agent aliased
as a tag rather than as a user, because a Langfuse user is the
person speaking and vinga does not know who that is; conflating
agent with user would poison any later voiceprint work with wrong
semantics. No alias is added that the walkthrough does not prove
necessary, and each lands with the unit pin the existing attribute
tables carry plus a wire assertion in the stub-receiver integration
suite. The aliases are unconditional attributes of every export:
they are inert metadata under any other backend, and a
Langfuse-shaped mode switch would be a second vocabulary for one
fact.

### Layer 2's seam: the capture close callback, not an event tap

Three facts the census established make the obvious design (an
event tap on `session_closed`) wrong, and the plan says so rather
than discovering it in review:

- The capture triplet is only final after `session_closed`: the
  close ordering in `device/session.py:617-654` emits the event at
  step 3 and patches the WAV header, closes the JSONL and writes the
  final manifest at step 5 (`SessionCapture.close()`). An uploader
  keyed on the event reads a placeholder header and a manifest still
  saying `complete: false`.
- No capture-finished event exists in the catalog at all.
- By `session_closed` the exporter has already popped the session
  trace (`telemetry.py:1616-1617`), and nothing anywhere retains a
  trace id.

A fourth fact sharpens the seam further, from the review round: a
capture also finishes early, at `max_session_s`
(`capture.py:278-314`) and on a write failure (`capture.py:246-265`),
both reaching `CaptureStore.finished()` while the device session
carries on, so `finished()` alone is not a session-close signal
either. The design therefore separates the two facts it conflated.
`CaptureStore` keeps `finished()` as what it is (the files are
final) but the staging happens THERE, before `finished()` hands the
files to `prune()`: `finished()` itself becomes prune-candidacy, so
the only moment the pair is guaranteed both final and still on disk
is inside that callback, and the delta round proved a
session-close-time staging loses a duration-limit capture to an
intervening prune. So the uploader's hook has two halves. At
files-final it stages the pair atomically (a complete capture only:
a write-failure capture, whose manifest says `complete: false` and
whose WAV may be unpatchable, is never uploaded, and its session
close records `capture_upload_failed` with the closed-set reason
`incomplete` instead, since attaching a recording the manifest
disowns would present broken evidence as evidence). At
`session_closed(session)`, a new session-level call invoked from
the device session's own close ordering immediately after
`self._capture_audio.close()` (step 5), the retained staged job is
enqueued. Both halves compare `is not None` per the honest-seams
lens and are wired by composition in `app.py` when the uploader
exists. An early-finished capture is therefore staged the moment
its files are final and enqueued only when its session closes, and
the tests drive both early paths (duration-limit, write failure) to
prove no upload starts before the session's close AND that a prune
storm between the early finish and the close cannot erase the
staged pair (the hardlinks survive the triplet's unlink by
construction, which is the property the test pins).

How the media request names its trace is a fact about Langfuse the
repository does not hold, so it is discovered before it is designed:
milestone 1's live walkthrough includes the media-correlation
questions alongside the mapping ones. What identifier format the
media API takes and whether it is the OTel trace id; what happens
when media arrives before the trace is ingested (the batch exporter
can hold a session's spans up to five seconds past close,
`telemetry.py:159-162`, so the upload can easily win the race), and
whether an upsert, a retry-after, or a refusal answers; and whether
any attach-by-session-id path exists at all. Milestone 2 is designed
from those recorded answers. The mechanism below is the hypothesis
M1 tests, stated so the walkthrough has something to falsify, not a
commitment: `Telemetry` records (session id, trace id) when the
session span opens and retains it in a bounded FIFO map past the
close pop (size 64, oldest evicted), with
`Telemetry.trace_of(session) -> str | None` the whole surface, and
the uploader bounding any arrives-before-ingestion window with a
short bounded retry whose shape M1's findings set. A correlation
that cannot be established is a `capture_upload_failed` with reason
`no_trace`, never a silent success: an upload that lands somewhere a
reader cannot find from the trace would recreate the gap this issue
closes, so session-id-only metadata is not called an attachment
unless the walkthrough proves Langfuse renders it as one. The
alternative, carrying the trace id on an event payload, would put a
correlation identifier into the catalog and every consumer's
vocabulary for one reader's benefit, and stays rejected.

### The prune race: staging by hardlink

`CaptureStore.prune()` runs at every capture close and open and
deletes whole triplets oldest-first (`capture.py:472-514`), so the
files the uploader wants can be unlinked mid-upload by a later
session under budget pressure. The uploader therefore stages before
it queues: inside the `session_closed` hook, it hardlinks exactly
two files, the WAV and the manifest, into a staging directory
beside the capture dir (`<capture.dir>/upload-staging/`), the same
filesystem by construction, no copy, no measurable close-path time.
The JSONL decision track stays local: the issue authorizes the WAV
and the manifest, the JSONL is a third content-bearing artifact it
never names, and the wire test asserts exactly two attachments with
their MIME types (a finalized WAV header, a manifest whose
`complete` is true) and that no request ever carries the JSONL.

Staging is transactional: the two links land under a temporary name
and are committed together, a partial staging rolls back to zero
links with the failure event, and a job the queue rejects
(overflow) has its links removed at the rejection, in the same
breath as the `dropped` event. Shutdown abandons whatever is
queued: the worker's bounded join expires, and what remains staged
is handled at the next open of the capture directory. The sweep is
`CaptureStore`'s, not the uploader's, deliberately: the delta round
showed a next boot with the flag off, capture off, `local_only` on
or the extra removed never constructs the uploader, and staged room
audio would then persist silently in exactly the configurations an
operator chose to stop exporting. So `CaptureStore` startup, which
opens the directory in every capture-configured boot, sweeps
`upload-staging/`: each job is its own subdirectory (which is also
what makes the two-link commit atomic), and the sweep emits one
sanitized `capture_upload_failed` (reason `abandoned`) per job
before removing it, so a restart cannot silently discard the only
record that an upload never happened. A boot with capture itself
absent leaves the directory untouched, which is stated in the
reference prose (removing the capture section parks the sweep with
the rest of the capture machinery). Within one process, sequential
lifespans hand ownership the way telemetry's lease does: a prior
lifespan's expired worker may still hold an in-flight job, so the
sweep skips jobs younger than the process and the new worker never
adopts another lifespan's job. Nothing is persisted for
retry, deliberately, because a retry store would be a durability
promise this flag does not make and the failure event is the honest
ledger. Tests assert the staging directory's exact contents after
partial staging, overflow, a timed-out upload and a restart. The
staged bytes count toward the same disk the budget watches and the
budget cannot see them; that limitation is bounded by the queue
depth and the sweep, and stated in the flag's reference prose
rather than hidden.

### The uploader runs where telemetry's shutdown runs

A dedicated daemon worker thread over a bounded best-effort
backlog, and the bound is honest about what it cannot promise: the
queue admits `server.limits.max_sessions` jobs beyond whatever is
in flight, because a routine shutdown closes every live session
concurrently and a healthy redeploy of a full server must not
deterministically drop any of THOSE, while jobs from earlier
sessions may still occupy the backlog when that drain begins, and a
backlog that deep means the endpoint has been failing for a while;
a job the bound rejects is dropped with its warning event, which is
the drop stated rather than hidden. The Tests section carries the
drain case this implies. The worker follows the
`telemetry.py:1391-1463`
precedent stated in the plan because the reasons are not guessable:
a daemon thread of its own rather than `asyncio.to_thread`, because
the default executor is joined at exit and a wedged upload would
hold the process open; bounded joins at shutdown with a warning on
expiry; nothing on the session-serving path ever waits on it
(`Telemetry.flush()`'s own documented rule). Every request the
worker makes carries a finite timeout (30 s, the export-timeout
posture) and a bounded retry policy (two retries with backoff, then
the failure event), because the blackhole failure mode is a request
that is accepted and never answered
(`tests/integration/test_telemetry_hardening.py`'s definition): with
no ceiling, no `capture_upload_failed` could ever fire and a bounded
shutdown join would merely abandon the job silently. The blackhole
test asserts the three latencies separately: the session closes
unaffected (bounded), the failure event fires within the
timeout-plus-retries budget, and shutdown completes within its own
bound. Layer 2 reuses `httpx`,
already a core dependency, for nothing: the upload goes through the
`langfuse` SDK per the issue's settled extra decision, imported
lazily, with client construction deferred into the worker's first
job rather than the builder, so a pinned SDK that validates its
environment at construction cannot turn missing credentials into a
boot failure; every construction exception is contained as a
sanitized upload failure, the same fixed sentences as any other. No
SDK symbol escapes the module and it imports clean without the
extra. And the SDK's own voice is contained the way the OTel
substrate contains its SDK (`telemetry.py:31-46`, the `_QUIETING`
lease): before the client is constructed, a quieting lease is taken
over the `langfuse` logger namespace and the HTTP stack it drives,
held until the worker has genuinely stopped, including past a
bounded-shutdown expiry (a late failure after the join must still
land in a quieted logger, the exact case the OTel lease exists
for), and restored safely across sequential lifespans. The
fake-import unit seam cannot certify any of that, so the
integration suite (which has the extra) gains a real-SDK
late-failure sentinel case: a planted credential in the SDK's
environment, an endpoint that fails after shutdown's bound, both
streams and both log formats asserted clean.

### Configuration, credentials and refusals

`TelemetryConfig` grows one field: `attach_captures: bool = False`,
`extra="forbid"` intact, description carrying the operator warning
the issue demands (capture on and telemetry on do not imply this;
room audio leaving the pod is its own decision). Credentials follow
the #66 posture and the SDK's own environment:
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, read
by the SDK, never config keys and never printed; the server-half
`EnvName` reference pattern is deliberately not used because there
is no value for vinga to read even by reference, matching the
`VINGA_DB_PASSWORD` docstring reasoning (`models.py:598-605`). The
two transports are therefore configured independently, OTLP through
`OTEL_EXPORTER_OTLP_*` and media through `LANGFUSE_*`, and pointed
at different deployments or projects both succeed while the
recording lands where the trace's reader will never look. That
invariant, same deployment and same project for both variable
families, is documented in the flag's generated-reference prose and
both example configs' commented blocks, and sits on the live
walkthrough's checklist so M3's record proves it was held rather
than assumed.

The order of decisions is the contract, because the issue's no-op
and the refusals would otherwise contradict:
`build_capture_upload(config.server, *, telemetry, local_only)`
receives the whole server section, and its first act resolves
capture. `server.capture` absent, or present with `enabled: false`,
returns `None` after one value-free info line: the issue says flag
on with capture off is a no-op, an operator mid-toggle is not a
misconfiguration, and none of the checks below run in that case,
so a capture-off deployment boots identically with or without the
extra, the telemetry section or `local_only`. Only when capture and
`attach_captures` are both effectively enabled do the refusals
apply, all `ConfigError` inside the builder per the #66 shape, each
with a fixed value-free sentence and no chaining, in this order:

- `server.telemetry.enabled` off (or the section absent) refuses:
  the attachment names a trace, and there is no trace to name.
  Cross-field, in the `ConversationsConfig` `model_validator` style
  where the shape allows it, otherwise in the builder with the same
  sentence discipline.
- `server.local_only: true` refuses via
  `check_feature("server.telemetry.attach_captures", egress=True,
  local_only)` before any import, construction or thread, the
  caller-half contract `egress.py:134-139` states.
- The missing `langfuse` extra refuses with the
  `NEEDS_THE_OTEL_EXTRA` sentence shape, naming
  `uv sync --extra langfuse`, no ImportError chained.
- Missing `LANGFUSE_*` variables are not a boot refusal either,
  deliberately, and the reason is stated: the SDK owns those
  variables and their validation, a boot check would be a second
  parser over another library's contract, and the failure surfaces
  as the first upload's warning event, which the blackholed-endpoint
  test proves harmless. The review may attack this; the
  counter-position (fail fast at boot) costs a vinga-side contract
  over SDK environment names that can drift with the SDK.

### What the upload writes back: two catalog events first

The catalog-first discipline (#66 M1): `capture_uploaded`
(session, plus sizes and elapsed ms; never a URL, never an id from
the far side that could carry a credential) and
`capture_upload_failed` (session, plus a reason from a closed set:
`unreachable`, `refused`, `too_large`, `no_trace`, `dropped`,
`staging_lost`, `abandoned`, `incomplete`; never the exception's words, classes rendered per
the no-leak lens). Both join `events/catalog.py`, the generated
events reference, and the exporter's APPROVED table by derivation.
They are the field-test trail: a capture that silently failed to
attach would recreate exactly the gap this issue exists to close.

They land in M3 rather than M2, with the emit sites: every variant the
catalog declares has to be produced by a driver's run
(`tests/unit/test_event_baseline.py`), and a milestone PR merges to
`main` on its own, so a declaration whose uploader is still being
written would sit unproducible on `main` for a whole milestone. M2's
record carries the declarations as designed.

### The boundary this crosses, stated rather than slipped

The recorded architecture says spans carry metadata and never
transcripts or audio (`telemetry.py:11-17`), and the content and
telemetry separation ADR keeps content in its own store. Layer 2
does not put audio on spans; it puts audio in a second
content-capable store whose retention vinga then delegates, which is
exactly the recorded Langfuse caution ("without a configured policy
it retains indefinitely", `observability-surfaces.md:148-153`). The
plan treats that as a documentation obligation, not a code question:
`docs/architecture/observability-surfaces.md` gains exported
capture media as its seventh surface (the page already declares
six, exported traces and audit among them): heading, count,
contents link, table row and the still-open owner line at ~88-90
all move (what it carries, who reads it, what retention
governs it: the Langfuse deployment's own policy, named as the
operator's to configure), and the ADR
`2026-08-15-content-and-telemetry-are-separate-surfaces.md` gains an
addendum recording that an operator may deliberately export capture
content to an external observability store under a default-off flag,
which extends rather than breaks the separation: the JSON log
surface stays metadata-only, and the flag is the recorded decision
point. The flag's generated-reference prose carries the same two
sentences an operator needs (this ships room audio; retention is the
backend's).

### The extra rides both image variants, like otel

`langfuse` joins `default` and `slim` (`Dockerfile:75-81`), because
`otel` set the precedent that observability extras ride both and a
variant split would make `attach_captures` a feature that works or
refuses depending on which image an operator happened to pull. The
full pin list the census enumerated moves: `pyproject.toml` extras
and dev group, `tiers.py` (a named field plus the import-name map;
the `langfuse` distribution's import subtrees written out), the
tier-closure suite (isolated env fixture, closure comparison, bite
negative, cross-tier negatives), the wheel suite (Requires-Dist
gate, bare-install absence, no-undeclared-extra), the Dockerfile
variant case, and the workflow's per-image import checks.

## Module layout

- `src/vinga_server/capture_upload.py`, new module: the staging,
  queue, worker, SDK construction and upload flow behind
  `build_capture_upload(config, *, telemetry, local_only) ->
  CaptureUpload | None`, mirroring `build_telemetry`'s
  build-nothing/refuse split. What callers stop knowing: the
  composition wires one callback into `CaptureStore` and one
  shutdown into the exit stack, and knows nothing of hardlinks,
  queues, SDK sessions or media APIs. Deletion test: inlined into
  `telemetry.py` it would double a 2019-line module with a second
  seam (a store client, not an event tap) whose dependencies,
  failure surface and extra are all different; inlined into
  `capture.py` it would put egress and credentials into a module
  that today never leaves the host.
- `telemetry.py`: the attribute aliases (M1 findings) and the
  bounded `trace_of` retention (M2), each a few lines deep in the
  existing tables and lifecycle.
- `events/catalog.py`: the two events (M3, with the emit sites the
  baseline suite holds every declaration to; M2's record says why).
- `config/models.py`: the `attach_captures` field and cross-field
  refusal; generated server reference, both example configs.
- `device/session.py` and `app.py`: composition wiring only.

## Tests

- **Unit, uploader**: build-nothing cases (flag off, section
  absent); the three refusals value-free and unchained; the no-op
  path; the staged pair created on `session_closed` and consumed;
  queue overflow drops with the `dropped` event; the `no_trace`
  failure on an evicted id; sentinel plants in the two untrusted
  input families, a credential-shaped `LANGFUSE_SECRET_KEY` and a
  hostile manifest field, asserted absent from both log formats,
  both events' payloads and exception chains for every failure
  family; the session id is not a sentinel, because both new events
  deliberately carry `session` as a declared identifier, so its
  assertion is positional instead: it appears only in the declared
  identifier positions and stays bounded by `SessionId`, the
  contract the generated events reference already documents; the
  SDK faked at the import seam the way `_import_sdk` is, with the
  real-SDK logging case living in the integration suite; and the
  drain case: a full `max_sessions` set of sessions closing
  concurrently with the backlog already occupied, every job
  accounted for as uploaded or dropped-with-event, none lost
  silently.
- **Unit, telemetry**: `trace_of` present after close, evicted
  after 64 later sessions, absent when telemetry never saw the
  session; alias attributes on the wire tables' unit pins.
- **Integration**: the stub-receiver suite asserts the aliases
  arrive spelled as recorded; a blackholed endpoint (the
  `test_telemetry_hardening.py` pattern) proves a session closes
  unaffected with the warning event emitted and bounded shutdown;
  the tier-closure and wheel suites gain the `langfuse` rows; an
  end-to-end case with capture on and a fake Langfuse media
  endpoint (an in-process HTTP stub, the `Receiver` precedent)
  proving the staged pair uploads after the real close ordering
  and the staging directory empties.
- **Live, recorded not asserted**: the two walkthroughs (M1 traces,
  M3 attachment playable in the UI) land in the implementation doc
  with their failures, the Jaeger-walkthrough precedent; each is a
  Verification box a PR can honestly check only by linking the
  record.

## Risks

- **The mapping is external and may not need what the plan
  expects**: M1 is sequenced first so the aliases are findings, and
  an empty finding (grouping works untouched) deletes that half of
  M1 rather than shipping speculative attributes.
- **SDK weight and behavior under `filterwarnings = ["error"]`**:
  any deprecation in the pinned SDK fails every lane; the extra's
  lower bound is chosen at a current release and the tier-closure
  suite isolates the blast radius.
- **The staging bytes are invisible to the capture budget**: stated
  in the reference prose; bounded by the queue depth and the boot
  sweep.
- **Credential territory**: every round on this chain widens
  (#66's M2 went four passes); the sentinel suite is written with
  the first commit of the uploader, not after.
- **The uploader's first CI run is a discovery round** (#283's
  calibration for new environment mechanisms); priced, not feared.

## Milestones

- [x] **[M1: the mapping, verified against a live Langfuse](2026-09-12-langfuse-backend-implementation.md#m1-the-mapping-verified-against-a-live-langfuse)** (PR #479). The
  local walkthrough with the #66 exporter as merged; findings
  recorded; the proven-necessary aliases added to the attribute
  tables with unit pins and wire assertions; the acceptance's
  session-grouping, gen_ai and handover criteria checked live and
  recorded. Design footprint: deepens the exporter's vocabulary
  tables, no new seam. Documentation footprint: the implementation
  doc's walkthrough record; `docs/reference/events.md` untouched;
  a `changelog.d/` fragment.
- [ ] **M2: the correlation.** `trace_of` with
  its bounded retention, recorded at the session span's open, spelled
  by the SDK's own `format_trace_id` and kept past the close pop. The
  two catalog events moved to M3, where their emit sites are: the
  baseline suite refuses a declared variant no driver's run produces,
  and a milestone PR merges on its own, so declaring them here would
  put an unproducible declaration on `main` for the whole of M3. The
  declarations as designed are recorded in the implementation doc.
  Design footprint: one narrow read surface on `Telemetry`.
  Documentation footprint: the implementation doc; fragment.
- [ ] **M3: the uploader and the vocabulary.** `capture_upload.py` with the staging,
  queue, worker and SDK flow; the two catalog events with their closed
  reason set, the generated events reference and the README index rows,
  the exporter's APPROVED derivation picking them up by construction;
  the `attach_captures` field, refusals
  and cross-field rule; the `[langfuse]` extra with the full pin
  list; composition wiring; the sentinel and hardening suites; the
  generated server reference and both example configs; the
  observability-surfaces seventh-surface row with its count and
  owner-line moves, and the ADR addendum; the live
  attachment walkthrough recorded; fragment. Design footprint: the
  new module with its depth sentence above; one injected callback
  seam on `CaptureStore`. Documentation footprint as listed, each
  page through its owner.

## Plan review round

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-12, runtime 4m46s, reviewing commit 7b25e452.
Verdict as received: **ready after the P1/P2 amendments**. Findings
condensed but faithful; resolutions appended per amendment.

1. **P1: Capture-off configurations contradict the required
   no-op.** The plan refuses on telemetry-off, local_only and the
   missing extra unconditionally, then calls capture-off a no-op;
   the builder signature receives no capture state. Resolve capture
   first: absent or disabled returns None with the informational
   no-op before any other check; the three refusals apply only when
   capture and attachment are both effectively enabled.

   *Resolution.* Adopted. The refusals section now leads with the
   decision order: the builder takes the whole server section,
   resolves capture first, returns None with the info no-op before
   any other check, and applies the three refusals only when
   capture and attachment are both effectively on.

2. **P1: `CaptureStore.finished()` is not a session-close seam.**
   A capture closes early at `max_session_s` and on write failure,
   both invoking `finished()` while the session continues; the true
   ordering closes capture after `session_closed`. Add an explicit
   session-level finalization call after `SessionCapture.close()`;
   keep early-finished paths but do not enqueue until the device
   session closes; test duration-limit and write-failure captures
   upload never-early.

   *Resolution.* Adopted. The seam section now separates the two
   facts: `finished()` stays files-final, a new
   `CaptureStore.session_closed(session)` runs from the device
   session's close ordering after `SessionCapture.close()`, the
   uploader hooks that, and both early-finish paths are tested to
   upload never-early.

3. **P1: Media-to-trace correlation is assumed before it is
   verified.** M2 commits to retaining an OTel trace id and to a
   session-id-only downgrade while the media walkthrough sits in
   M3; the batch exporter can delay ingestion past the media
   request; nothing proves the media API accepts an OTel trace id,
   upserts an un-ingested trace, or attaches by session id at all.
   Move media correlation into the initial live discovery; record
   the identifier format and the arrives-before-ingestion behavior;
   design M2 after; bound any ordering retry; a missing correlation
   is `capture_upload_failed`, and session-only metadata is not
   called an attachment unless proven.

   *Resolution.* Adopted. Media correlation joins M1's live
   discovery with the three questions spelled out; M2 is designed
   from the recorded answers with the current mechanism demoted to
   the hypothesis under test; a failed correlation is
   `capture_upload_failed` with reason `no_trace`; the downgrade
   claim is withdrawn unless the walkthrough proves the rendering.

4. **P1: The blackholed-endpoint test cannot emit the warning it
   claims.** A blackhole accepts and never answers; without a
   finite request timeout and retry ceiling the media call never
   returns and no failure event fires; a bounded join only saves
   shutdown. Define the timeout and retry policy; verify against an
   accept-and-never-answer receiver; assert session-close latency,
   failure-event latency and shutdown latency separately.

   *Resolution.* Adopted. The worker section fixes a 30 s request
   timeout and a two-retry ceiling, and the blackhole test asserts
   the three latencies separately against an
   accept-and-never-answer receiver.

5. **P2: Queue depth four loses captures during an ordinary
   redeploy.** Eight sessions is the default limit and shutdown
   closes them concurrently, so a healthy upgrade can enqueue eight
   finished captures and deterministically drop several. Size
   admission against `server.limits.max_sessions` or make the
   staged jobs the durable queue; test a maximum-sessions
   simultaneous drain accounting for every job.

   *Resolution.* Adopted. Queue admission is sized from
   `server.limits.max_sessions` at build, and the tests gain a
   maximum-sessions simultaneous drain accounting for every job.

6. **P2: Staging cleanup and restart behavior are incomplete.**
   Nothing removes links on partial staging, on a dropped enqueue,
   or on shutdown-abandoned work, and the boot sweep discards the
   only upload-safe links without a per-capture failure record.
   Make staging transactional with rollback; clean rejected jobs'
   links immediately; define shutdown and restart behavior (persist
   enough to retry, or one sanitized failure per abandoned job
   before cleanup); assert directory contents after partial
   staging, overflow, timeout and restart.

   *Resolution.* Adopted. Staging is transactional with rollback,
   rejected jobs clean their links with the `dropped` event, the
   boot sweep emits one `abandoned` failure per leftover before
   cleaning (no retry store, deliberately, with the reason stated),
   and the tests assert the directory's exact contents across all
   four states.

7. **P2: The plan expands egress from two attachments to the full
   triplet.** The settled scope is WAV plus manifest; the staging
   hardlinks all three and the test says "staged triplet uploads".
   The JSONL decision track stays local; stage and upload exactly
   two files; the wire test asserts exactly two attachments, MIME
   types, a finalized WAV header, a final manifest, and no JSONL
   request.

   *Resolution.* Adopted. The staging and the upload carry exactly
   the WAV and the manifest, the JSONL stays local with the reason
   stated, and the wire test asserts two attachments, the MIME
   types, the finalized header, the complete manifest and the
   absence of any JSONL request.

8. **P2: Missing credentials cannot reliably be deferred with
   construction in the builder.** If the pinned SDK validates
   credentials at construction, boot fails, contradicting the
   first-upload-failure policy. Verify the SDK's behavior; defer
   client construction into the worker's first job and contain
   every construction exception as a sanitized upload failure, or
   adopt and test a fixed value-free boot refusal.

   *Resolution.* Adopted, first option: client construction is
   deferred into the worker's first job, every construction
   exception contained as a sanitized upload failure, and the
   pinned SDK's construction behavior is verified and recorded
   during M3.

9. **P2: Third-party logging is not contained by the design.** The
   OTel substrate quiets its SDK's logger namespace before
   construction and holds the lease until outstanding work truly
   ends; the plan names no equivalent for the Langfuse SDK and its
   HTTP stack, and a faked import seam cannot certify real SDK
   logging. Guard the real namespaces before construction, retain
   past a bounded-shutdown expiry, restore across sequential
   lifespans, and add a real-SDK late-failure sentinel test.

   *Resolution.* Adopted. The worker section takes the `_QUIETING`
   lease shape over the `langfuse` namespace and its HTTP stack
   before construction, holds it past a bounded-shutdown expiry and
   across lifespans, and the integration suite gains the real-SDK
   late-failure sentinel case.

10. **P2: The proposed hostile-session-id leak assertion is
    impossible.** Both new events deliberately carry `session`, and
    the policy treats a bounded session id as a trusted identifier.
    Plant secret sentinels only in credential and manifest-content
    inputs; assert session ids appear only in declared identifier
    positions and stay bounded by `SessionId`.

    *Resolution.* Adopted. Sentinels plant only in credentials and
    manifest content; the session id gets a positional assertion
    bounded by `SessionId` instead of an absence claim.

11. **P2: Configuration does not state that both transports must
    target the same project.** OTLP env and `LANGFUSE_*` env are
    independent; pointed at different projects, both succeed and
    the recording does not accompany the trace. Document the
    same-deployment-same-project invariant in both example configs
    and the generated reference, and put it on the walkthrough
    checklist.

    *Resolution.* Adopted. The credentials section states the
    invariant with its failure shape, both example configs and the
    generated reference carry it, and it joins the walkthrough
    checklist.

12. **P3: The documentation surface count is already six.** The
    page declares six surfaces including exported traces and audit.
    Exported capture media is the seventh; update heading, count,
    table and the still-open owner line.

    *Resolution.* Adopted; the plan now says seventh everywhere and
    names the heading, count, contents link, table and owner-line
    moves.

### Delta re-review

External review: codex CLI 0.154.0, model gpt-5.6-terra, read-only
sandbox, 2026-09-12, runtime 2m31s, reviewing commit 0600859b.
Verdict as received: **ready after the P1/P2 amendments**. Findings
condensed but faithful; resolutions appended per amendment.

1. **P1: Early-finalized captures can be pruned before the new
   `session_closed` seam stages them.** `SessionCapture.close()`
   reaches `CaptureStore.finished()`, which immediately prunes, so
   a duration-limit or write-failure capture becomes a prune
   candidate while its session continues, refuting resolution 2
   combined with 6. Stage atomically at the files-final callback
   before pruning can see the files; retain without enqueuing until
   `session_closed`; define the write-failure capture's
   disposition; the early-path tests must prove both no early
   upload and that an intervening prune cannot erase the staged
   pair.

   *Resolution.* Adopted. Staging moves to the files-final callback
   itself, ahead of prune-candidacy; enqueue stays at
   `session_closed`; a write-failure capture is never uploaded and
   its session records the new closed-set reason `incomplete`; the
   early-path tests pin both properties, including hardlink
   survival through an intervening prune.

2. **P2: The abandoned-job sweep is not reachable in valid
   next-boot configurations.** The builder returns before all later
   work when the uploader is off, disabled, local_only or
   extra-less, so leftover staged room-audio links persist
   silently. Recovery belongs to `CaptureStore` startup, whenever
   the capture directory is opened, uploader or no uploader;
   per-job staging so the sweep identifies one job and emits one
   sanitized `abandoned` event; specify fresh-process versus
   sequential-lifespan ownership.

   *Resolution.* Adopted. The sweep is `CaptureStore` startup's,
   running whenever the capture directory opens regardless of the
   uploader's existence; jobs are per-job subdirectories (which is
   also the atomic commit); the capture-absent case is stated; and
   sequential lifespans neither adopt nor double-sweep another
   lifespan's in-flight job.

3. **P2: `max_sessions` does not bound queued jobs, and the
   promised drain test is absent from the Tests section.** Jobs
   from already-closed sessions can occupy the queue when a full
   server drains. Define the queue as a bounded best-effort
   backlog, reserve capacity for live sessions or state the drop
   honestly, and put the max-drain-with-occupancy test in the Tests
   section.

   *Resolution.* Adopted. The queue is a bounded best-effort
   backlog admitting `max_sessions` beyond what is in flight, the
   possible drop of stale backlog is stated with its event, and the
   max-drain-with-occupancy case is in the Tests section with
   every-job accounting.
