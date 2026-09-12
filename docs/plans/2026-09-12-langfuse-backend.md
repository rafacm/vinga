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

So the uploader attaches where the files become final:
`CaptureStore.finished()` (`capture.py:516-523`), the one real
"the triplet is finished" seam, which today only prunes. The store
gains an optional `on_finished` callback (injected, compared
`is not None` per the honest-seams lens), wired by composition in
`app.py` when the uploader exists. The uploader receives the
session id and the triplet paths.

The trace id crosses from telemetry through a new, deliberately
narrow read surface: `Telemetry` records (session id, trace id) when
the session span opens and retains it in a bounded FIFO map past the
close pop (size 64, oldest evicted; a capture uploads within
seconds of its closing session, and an eviction miss downgrades the
attachment to session-id-only metadata with a warning event rather
than an error). `Telemetry.trace_of(session) -> str | None` is the
whole surface. The alternative, carrying the trace id on an event
payload, would put a correlation identifier into the catalog and
every consumer's vocabulary for one reader's benefit.

### The prune race: staging by hardlink

`CaptureStore.prune()` runs at every capture close and open and
deletes whole triplets oldest-first (`capture.py:472-514`), so the
files the uploader wants can be unlinked mid-upload by a later
session under budget pressure. The uploader therefore stages before
it queues: inside `finished()`'s callback, on the close path, it
hardlinks the three files into a staging directory beside the
capture dir (`<capture.dir>/upload-staging/`), which is the same
filesystem by construction and costs no copy and no measurable
close-path time. Uploads read the staged links and unlink them when
done; boot sweeps the staging directory of leftovers older than the
process (the memory boot-sweep precedent), so a crash cannot
accumulate them. The staged bytes count toward the same disk the
budget watches, and the budget cannot see them; the honest answer is
the sweep plus the bounded queue below, and the limitation is stated
in the flag's reference prose rather than hidden.

### The uploader runs where telemetry's shutdown runs

A dedicated daemon worker thread with a bounded queue (size 4;
a fifth finished capture before the first uploads is dropped with a
warning event, since captures are minutes long and a backlog that
deep means the endpoint is down), the `telemetry.py:1391-1463`
precedent stated in the plan because the reasons are not guessable:
a daemon thread of its own rather than `asyncio.to_thread`, because
the default executor is joined at exit and a wedged upload would
hold the process open; bounded joins at shutdown with a warning on
expiry; nothing on the session-serving path ever waits on it
(`Telemetry.flush()`'s own documented rule). Layer 2 reuses `httpx`,
already a core dependency, for nothing: the upload goes through the
`langfuse` SDK per the issue's settled extra decision, and the SDK
is imported lazily inside the builder exactly as `_import_sdk()`
gates OTel, so no symbol escapes and the module imports clean
without the extra.

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
`VINGA_DB_PASSWORD` docstring reasoning (`models.py:598-605`).

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
`staging_lost`; never the exception's words, classes rendered per
the no-leak lens). Both join `events/catalog.py`, the generated
events reference, and the exporter's APPROVED table by derivation.
They are the field-test trail: a capture that silently failed to
attach would recreate exactly the gap this issue exists to close.

### The boundary this crosses, stated rather than slipped

The recorded architecture says spans carry metadata and never
transcripts or audio (`telemetry.py:11-17`), and the content and
telemetry separation ADR keeps content in its own store. Layer 2
does not put audio on spans; it puts audio in a second
content-capable store whose retention vinga then delegates, which is
exactly the recorded Langfuse caution ("without a configured policy
it retains indefinitely", `observability-surfaces.md:148-153`). The
plan treats that as a documentation obligation, not a code question:
`docs/architecture/observability-surfaces.md` gains the uploader as
a sixth surface row (what it carries, who reads it, what retention
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
- `events/catalog.py`: the two variants (M2).
- `config/models.py`: the `attach_captures` field and cross-field
  refusal; generated server reference, both example configs.
- `device/session.py` and `app.py`: composition wiring only.

## Tests

- **Unit, uploader**: build-nothing cases (flag off, section
  absent); all four refusals value-free and unchained; the no-op
  path; staging hardlinks created on `finished` and consumed;
  queue overflow drops with the `dropped` event; `no_trace`
  downgrade on an evicted id; sentinel plants (a credential-shaped
  `LANGFUSE_SECRET_KEY`, a hostile manifest field, a hostile
  session id) asserted absent from both log formats, both events'
  payloads and exception chains for every failure family; the SDK
  faked at the import seam the way `_import_sdk` is.
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
  proving the staged triplet uploads after the real close ordering
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

- [ ] **M1: the mapping, verified against a live Langfuse.** The
  local walkthrough with the #66 exporter as merged; findings
  recorded; the proven-necessary aliases added to the attribute
  tables with unit pins and wire assertions; the acceptance's
  session-grouping, gen_ai and handover criteria checked live and
  recorded. Design footprint: deepens the exporter's vocabulary
  tables, no new seam. Documentation footprint: the implementation
  doc's walkthrough record; `docs/reference/events.md` untouched;
  a `changelog.d/` fragment.
- [ ] **M2: the correlation and the vocabulary.** `trace_of` with
  its bounded retention; the two catalog events with their closed
  reason set; generated events reference; the exporter's APPROVED
  derivation picks them up by construction. Design footprint: one
  narrow read surface on `Telemetry`; catalog growth in the
  existing shape. Documentation footprint: the generated events
  page through its generator; fragment.
- [ ] **M3: the uploader.** `capture_upload.py` with the staging,
  queue, worker and SDK flow; the `attach_captures` field, refusals
  and cross-field rule; the `[langfuse]` extra with the full pin
  list; composition wiring; the sentinel and hardening suites; the
  generated server reference and both example configs; the
  observability-surfaces sixth row and the ADR addendum; the live
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

4. **P1: The blackholed-endpoint test cannot emit the warning it
   claims.** A blackhole accepts and never answers; without a
   finite request timeout and retry ceiling the media call never
   returns and no failure event fires; a bounded join only saves
   shutdown. Define the timeout and retry policy; verify against an
   accept-and-never-answer receiver; assert session-close latency,
   failure-event latency and shutdown latency separately.

5. **P2: Queue depth four loses captures during an ordinary
   redeploy.** Eight sessions is the default limit and shutdown
   closes them concurrently, so a healthy upgrade can enqueue eight
   finished captures and deterministically drop several. Size
   admission against `server.limits.max_sessions` or make the
   staged jobs the durable queue; test a maximum-sessions
   simultaneous drain accounting for every job.

6. **P2: Staging cleanup and restart behavior are incomplete.**
   Nothing removes links on partial staging, on a dropped enqueue,
   or on shutdown-abandoned work, and the boot sweep discards the
   only upload-safe links without a per-capture failure record.
   Make staging transactional with rollback; clean rejected jobs'
   links immediately; define shutdown and restart behavior (persist
   enough to retry, or one sanitized failure per abandoned job
   before cleanup); assert directory contents after partial
   staging, overflow, timeout and restart.

7. **P2: The plan expands egress from two attachments to the full
   triplet.** The settled scope is WAV plus manifest; the staging
   hardlinks all three and the test says "staged triplet uploads".
   The JSONL decision track stays local; stage and upload exactly
   two files; the wire test asserts exactly two attachments, MIME
   types, a finalized WAV header, a final manifest, and no JSONL
   request.

8. **P2: Missing credentials cannot reliably be deferred with
   construction in the builder.** If the pinned SDK validates
   credentials at construction, boot fails, contradicting the
   first-upload-failure policy. Verify the SDK's behavior; defer
   client construction into the worker's first job and contain
   every construction exception as a sanitized upload failure, or
   adopt and test a fixed value-free boot refusal.

9. **P2: Third-party logging is not contained by the design.** The
   OTel substrate quiets its SDK's logger namespace before
   construction and holds the lease until outstanding work truly
   ends; the plan names no equivalent for the Langfuse SDK and its
   HTTP stack, and a faked import seam cannot certify real SDK
   logging. Guard the real namespaces before construction, retain
   past a bounded-shutdown expiry, restore across sequential
   lifespans, and add a real-SDK late-failure sentinel test.

10. **P2: The proposed hostile-session-id leak assertion is
    impossible.** Both new events deliberately carry `session`, and
    the policy treats a bounded session id as a trusted identifier.
    Plant secret sentinels only in credential and manifest-content
    inputs; assert session ids appear only in declared identifier
    positions and stay bounded by `SessionId`.

11. **P2: Configuration does not state that both transports must
    target the same project.** OTLP env and `LANGFUSE_*` env are
    independent; pointed at different projects, both succeed and
    the recording does not accompany the trace. Document the
    same-deployment-same-project invariant in both example configs
    and the generated reference, and put it on the walkthrough
    checklist.

12. **P3: The documentation surface count is already six.** The
    page declares six surfaces including exported traces and audit.
    Exported capture media is the seventh; update heading, count,
    table and the still-open owner line.
