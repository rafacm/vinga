# Transcript export as the third optional telemetry layer

Plan for [issue #495](https://github.com/rafacm/vinga/issues/495).
Companion implementation doc:
`2026-09-12-transcript-export-implementation.md`, one section per
milestone, appended in the same change that ticks the milestone
checklist.

## Goal

After #67, a trace backend shows a vinga session as grouped per-turn
traces with stage timings and token counts, and, under a flag, the
session's recording attached; what a reader still cannot see there is
what was said. This issue adds the third rung of the disclosure
ladder: with `server.telemetry.export_transcripts` on, a closed
session's trace gains one observation per recorded turn carrying the
turn's user text and reply text, read post hoc from the conversation
store, with leg attribution where a handover split the reply. The
`attach_captures` flag is renamed `export_audio` in the same issue so
the ladder's two content escalations share one vocabulary, and the
export-ladder policy (metadata, conversation content, wire fidelity)
is recorded as an amendment to the content-and-telemetry record
rather than left as one issue's choice.

Local baseline: not applicable. No conversational capability changes;
this is a content-export feature, lawful under rule 5 of
[the enumerated-baseline record](../adr/2026-09-12-the-local-baseline-is-enumerated.md)
exactly because it declares its destination, defaults off, and
refuses under a local boundary. The enumerated list does not move.

## The issue's decisions, restated

- **The `server.telemetry` section is a disclosure ladder, and the
  naming lands here.** `enabled` stays the master switch (metadata
  leaves; a prerequisite, not a peer, which is why it is not spelled
  `export_metadata`). `attach_captures` renames to `export_audio`
  with identical semantics; the old key is refused by
  `extra="forbid"` with the schema's usual loudness, no alias
  machinery, priced as cheap only while nothing deploys against it.
  The new flag is `export_transcripts`. Both escalations mean: if
  this content exists locally, it leaves.
- **The source is the conversation store, not the live pipeline.**
  Transcripts export post hoc from what the store recorded, through
  the post-close span mechanism #67 M3 built (the retained trace
  context; delivery is refined by this plan's review round from the
  shared span queue to a bounded export call, because the queue
  cannot answer for the failure event the issue requires). A
  content-bearing
  tap feeding the generation spans at fold time is rejected for this
  issue and, by this plan's ADR amendment, as policy: the emit/span
  fold seam stays content-free.
- **Conversation-level text only.** User text and reply text per
  turn, with leg attribution. The assembled LLM request and
  per-request audio clips are out of scope; wire fidelity is its own
  future decision per tier.
- **Erasure does not propagate, and the flag's prose says so.**
  Exported text outlives `vinga session delete`, the #67 audio
  precedent; retention is the backend's own policy.
- **Optionality layered like #67's**: default false, refused under
  `server.local_only`, requires `server.telemetry.enabled`, a no-op
  when conversation text storage is off (absent, disabled, or
  `text: false` means nothing to export, not an error). Capture is
  irrelevant to this flag either way. The refusal spells
  `server.local_only` today and adopts #493's vocabulary when that
  rename lands; nothing here bakes the old spelling anywhere beyond
  the flag's own refusal site.
- **Per-turn observations into the session's trace**, parented for
  the grouping the backend keys on. Failure never touches the
  session: the #67 outcome-event pattern (closed reason set, events
  on the trace and in the log, bounded work off the audio path)
  applies as written.
- **Global for v1**; per-device export policy is named follow-up work
  riding #393's device-row flags, recorded in the issue so the
  decision does not evaporate.

## Open questions, resolved

### The rename is its own leading milestone

It is a mechanical sweep with a wide, content-free diff (the field
and its docstring, `ATTACH_KEY` and two refusal sentences, sixteen
test sites, both example configs, the regenerated reference, the
observability map's row, the content-and-telemetry amendment's
spelling, two build-file comments), and mixing it into the flag's
milestone would bury the one behavior change of this issue under a
hundred respellings. Leading rather than trailing because the new
flag's prose, refusal ordering and tests are then written against
the final vocabulary once instead of twice. The census found no
alias machinery in `config/loader.py` and the issue settles that
none is added.

The sweep's documentation rule: pages that state current behavior
(the observability map's row, the 2026-09-12 amendment in the
content-and-telemetry ADR, both example configs) move to the new
spelling, with the amendment noting the rename in one clause so the
record stays honest about what it was recorded under; historical
records (the #67 plan and implementation doc, `CHANGELOG.md`'s
already-folded entry) keep the spelling they shipped with, because
they describe the repository on their date.

### Per-turn export happens at session close, not at each turn's close

Three reasons, each sufficient. The issue's settled source is the
store, post hoc, and at a turn's close the turn's row is an enqueued
write that may not have committed. The retained-context mechanism
(`_continuing`, `telemetry.py:1472`) holds the session span's
identity and nothing per-turn, so turn-time export would either
grow per-turn retention bookkeeping (unbounded within a session) or
put content assembly on the conversation path, and the parent the
issue names is the session span either way. And one export per
session is one store read and one span batch, where per-turn export
is N of each for the same rendered result.

What session-close export must then own is the census's asymmetry:
`ConversationStore.close_session` (`store.py:1114`) enqueues a
`Close` control record and returns nothing, while the capture
uploader's `session_closed` hook fires synchronously afterwards, so
an exporter triggered at the same point can read before the writer
commits. The mechanism: `Close` gains the `Acknowledgement` handle
the `Milestone` record already carries (`records.py:191`), settled
by the writer after the close's transaction commits, and
`close_session` returns it (today's callers ignore a return of
`None` and keep compiling; the device session forwards it). The
writer is one thread consuming one FIFO queue, so the close's
acknowledgement landing implies every earlier record of that session
landed or was dropped-and-counted, which is exactly the
read-your-writes guarantee the export needs. The worker waits on it
with a bound of its own (30 s, the request-timeout posture; the
writer's own durability wait is far shorter, so a bound this loose
fires only when the store is genuinely wedged), and a `False` answer
is the closed set's `unrecorded`: the store may have dropped the
close, stopped, or timed out, all of which mean the export may not
assume the turns are readable, and per the `Acknowledgement`
docstring the three are deliberately not told apart.

### The transcript travels as OTLP spans; no SDK, no extra, no staging, and delivery is a bounded call with an answer

The shape #67's uploader has (staging hardlinks, a Langfuse REST
client, presigned PUTs, a boot sweep) exists because audio bytes
travel over a second transport with credentials of its own. A
transcript travels as spans: #67 M1 established that this backend
ingests spans and renders `langfuse.observation.*` fields, M3's
`reference_media` already writes a post-close span into the retained
session context, and the `AFTER_THE_CLOSE` fold does the same for
the outcome events. So the transcript exporter needs no `[langfuse]`
extra, no second credential family and no staging directory.

What it does NOT ride is the shared `BatchSpanProcessor` queue,
because that queue cannot answer for delivery: it drops on
saturation and swallows collector failure, `force_flush` reports
only that the flush finished, and the issue's acceptance requires an
unreachable backend to surface as a warning event. So the transcript
spans are built and delivered as one bounded call with a result.
`Telemetry.export_transcript(session, context, turns)` builds the
turn spans on a private tracer bound to the same resource and
collected in memory rather than queued, and hands the batch to a
dedicated OTLP exporter instance: the same exporter class the #66
substrate constructs, through the existing `_Sdk` seam, from the
same `OTEL_EXPORTER_OTLP_*` environment, so there is still one
transport vocabulary and one credential family. The instance is
constructed lazily at the worker's first job, on the worker thread,
where it is the only user, and a construction failure is a contained
delivery failure, never a boot event. The call's bound is the
export-timeout posture (30 s) with the exporter's own internal
bounded retry as the whole retry policy; `SpanExportResult` decides
the answer: `delivered`, or the closed set's new `undelivered`
(export failure or timeout; deliberately not told apart further,
because the result is binary and a sentence must never carry the far
side's words). Before constructing the instance the worker takes a
`quieting.py` lease over the OTel SDK namespaces, held in its own
`finally` past a bounded-shutdown expiry, the #67 M3 pattern: a late
export failure must not print an endpoint or header through a
namespace telemetry has already un-quieted.

The blackholed-endpoint integration case is therefore the #67
pattern verbatim: an accept-and-never-answer receiver, with three
latencies asserted separately (the session closes unaffected within
its bound, `transcript_export_failed` with reason `undelivered`
fires within the timeout budget, shutdown completes within its own
bound).

Nothing is persisted, so there is no boot sweep and no `abandoned`
reason; a process that dies with an export queued loses a transcript
export and nothing else, and the turns themselves stay in the store,
re-exportable by any future surface. The two outcome EVENTS still
fold through the shared queue best-effort, which is honest: the log
is their surface of record and the trace copy is a courtesy, the
#67 posture.

### A sibling module, not a generalized post-close worker

The deletion test the issue asks for, answered: folded into
`capture_upload.py`, the transcript exporter would put a store
reader and a span writer into a module whose vocabulary is
hardlinks, media APIs and SDK containment, and every one of the
capture module's hard-won properties (staging transactionality, the
quieting lease, the classification off typed errors) is machinery
transcripts do not need; folded into `telemetry.py` it would put a
database engine and a writer-acknowledgement wait into a
2000-line module whose rule is that it consumes emissions and
retained contexts, never stores. What the two post-close surfaces
genuinely share is already shared where it belongs: `_continuing`,
the retention, and `AFTER_THE_CLOSE` live in `telemetry.py` and are
name-agnostic (the census confirmed both writers go through them).
The worker-and-bounded-queue shape repeats as a pattern, not as
code: extracting it would be a layer forwarding its arguments, the
design guide's pass-through.

So: `src/vinga_server/transcript_export.py`, a daemon worker thread
over a queue bounded at `server.limits.max_sessions` (the #67 drain
argument holds unchanged: a routine shutdown closes every live
session concurrently), lazy start at the first job, bounded
shutdown join on the exit stack, jobs rejected by the bound dropped
with their failure event. The worker's per-job flow: wait bounded on
the close acknowledgement; read the session's turns through the
store's read seam; ask `Telemetry` to write the spans; emit the
outcome event.

### What a resumed conversation exports: this session's turns, by the store's own membership

The presumption in the issue, proven by schema: `turns.session`
(`schema.py:395`) records which session each turn belongs to, and
the schema's own comment says session and conversation are two
readings of one set of rows. The export reads by session, so a
resumed conversation's earlier turns, which belong to an earlier
session (and were exportable when that session closed, under
whatever the flag said then), never re-export. The test drives a
resumed thread across two sessions and asserts the second export
carries exactly the second session's turns.

### The read surface: the session-turns query gets one home

`GET /api/…/sessions/{id}/turns` already reads exactly what the
export wants, as an inline query in `conversations/api.py:847`. The
query moves to `threads.py` as `session_turns(connection, session)`
with the API route as its first caller (a behavior-preserving move,
pinned by the route's existing contract tests plus a
byte-identical-response pin), and `threads.Reads`, the
engine-per-call never-raise seam built for callers outside a request
(`threads.py:851`), gains a `session_turns(session)` method in the
milestone that has a caller for it. That is the locality rule
applied: one home for "a session's turns, oldest first", read by the
API and the exporter from the same place. `Reads` answering
`Unreadable` is the exporter's `unreadable` reason; a raise would
quote a DSN, which is why the seam exists.

### The span shape, and the two vocabulary rules it extends

One span per turn, named `transcript`, written by a new
`Telemetry.export_transcript(session, turns) -> bool` beside
`reference_media` and shaped by it: children of the retained session
span via `_continuing`, written after the session's own spans have
ended and exported, `False` when the exporter never saw the session,
the retention evicted it, or `stop_accepting` has run, and a `False`
reported as `transcript_export_failed` with reason `no_trace`, never
a silent success. Each span carries the session id under both
spellings (grouping), `vinga.turn.id` (the schema's own monotonic
turn identity, which is the issue's "turn index"), `vinga.turn.t_ms`
and `vinga.agent` (the agent the turn opened with), and the content
in the fields the backend renders: `langfuse.observation.input` for
`heard`, `langfuse.observation.output` for `reply`. Where the
`legs` column is present (a handover split the reply), the per-leg
attribution rides `langfuse.observation.metadata.legs` as the
column's JSON with the token halves left out (they are metadata the
generations already carry; content and its attribution are what this
observation adds). A turn whose text halves are both null (recorded
before text was on, or nothing spoken) exports no span; a session
whose readable turns number zero exports nothing and emits nothing,
because a trail entry for an empty export would be noise a reader
filters out, and the flag's no-op line at boot already says why
nothing will ever export when that is config's doing.

Spans are timestamped at export time and ordered by `vinga.turn.id`;
no synthetic conversation-time timestamps, because a span claiming
to have happened at `t_ms` would be the one dishonest fact on a
surface whose value is being checkable against the store.

This extends the stated `telemetry.py` vocabulary exception
(nothing it writes may say what `catalog.py` does not declare; the
media reference is the recorded exception): transcript content is
the second exception, stated in the same module note, lawful only
because `export_transcripts` is on, exactly as the media token is
lawful only under `export_audio`.

### The events: a sibling pair, and why the #67 pair does not generalize

The census settled it: `CaptureUploaded`/`CaptureUploadFailed` are
generically shaped but worded for a recording throughout (class
names, both templates, `audio_bytes`/`manifest_bytes`, the enum's
member docstrings), and widening them would trade two honest
sentences for one vague one. What generalizes is the machinery,
which already has: the fold routes both pairs through
`AFTER_THE_CLOSE` and `_after_the_close` unchanged.

New channel `TRANSCRIPT_EXPORT_CHANNEL =
"vinga_server.transcript_export"` (a channel is the emitting
module's name). Two declarations, inheriting the #67 pair's
no-carry rules (no URL, no far-side identifier, no exception
message):

| Variant | Level | Template |
| --- | --- | --- |
| `TranscriptsExported` | INFO | `session %s: %d turn transcripts exported to its trace in %d ms` |
| `TranscriptExportFailed` | WARNING | `session %s: transcripts not exported to its trace (%s)` |

`TranscriptsExported` carries `session: SessionId`,
`turns: Count`, `elapsed_ms: Whole`. `TranscriptExportFailed`
carries `session` and `reason` from a new closed set
`TranscriptExportFailure` in `events/values.py`, five members with
their decision sites: `unrecorded` (the close acknowledgement
answered `False`: dropped, stopped or timed out, deliberately not
told apart), `unreadable` (the store's read seam answered
`Unreadable`), `no_trace` (no retained trace context for the
session), `undelivered` (the bounded export answered failure or
timed out), `dropped` (the queue bound turned the job away, or
shutdown ended it before completion). No `abandoned`: nothing
persists. Both
events join `AFTER_THE_CLOSE` so the trail reaches the trace, the
#67 confirmation-round lesson applied on day one rather than found
in review. Both land in the same milestone as the worker that emits
them (the baseline suite refuses a declaration no driver produces,
the M2-to-M3 lesson of #67).

### Configuration, refusals and their order

`TelemetryConfig` grows `export_transcripts: bool = False`,
`extra="forbid"` intact, the description carrying the erasure and
retention boundary in its own prose (exported text outlives
`vinga session delete`; retention is the backend's policy) plus the
no-implication warning (telemetry on and text storage on do not
imply transcripts leave). The cross-field rule is the builder's, not
a validator's, for the reason the #67 delta round proved and
`models.py:806-823` now documents; the `BOOT_REFUSALS` comment
already explains the registry's scope and needs no new row.

`build_transcript_export(config.server, *, telemetry, database,
local_only) -> TranscriptExport | None`, the decision order the
contract, mirroring `build_capture_upload`:

1. **Recording first.** `server.conversations` absent, disabled, or
   `text: false` answers `None`; with the flag on, one value-free
   info line naming the two keys (the acceptance's boot line); with
   the flag off too, nothing to explain and nothing said.
2. **The flag.** Off answers `None` silently.
3. **Telemetry.** `export_transcripts` on with `enabled` off (or the
   section absent) refuses: `ConfigError`, fixed value-free sentence
   (`TRANSCRIPTS_NEED_TELEMETRY`), nothing chained.
4. **Egress**, through
   `check_feature("server.telemetry.export_transcripts", egress=True,
   local_only)`, the standing sentence, before any thread.

No extra step: there is no SDK. No credential step: there is no
second transport. Composition in `app.py` builds it beside the
capture uploader, hands it to the device session the way
`CaptureStore` is handed, and puts its bounded shutdown on the exit
stack; the device session's close ordering calls it immediately
after the captures hook, forwarding the acknowledgement
`_stop_recording` now returns. All injected seams compare
`is not None`.

### The ADR amendment records the ladder as policy

A third amendment to
`docs/adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md`,
beside #67's, recording the three-tier export ladder as policy
rather than this issue's choice: **metadata** (always with
telemetry, never content), **conversation content** (per-class
flags, `export_audio` and `export_transcripts`, export follows
retention: what the store or capture holds is what may leave), and
**wire fidelity** (the assembled prompt, per-request audio, each a
future decision of its own, deliberately unspecced). Content
escalations ride content taps (the capture store's files, the
conversation store's rows) while the emit/span fold seam stays
content-free at every tier, so a fold-time content tap is rejected
policy, not a deferral; a transcript span is a content tap's
delivery vehicle, not the fold gaining content. The tier table
itself extends `docs/architecture/observability-surfaces.md`, where
the record keeps its tables, alongside the page's new eighth
surface (exported transcripts: what it carries, who reads it, what
retention governs it), which moves the page's title count, the
"On this page" line, the table and the where-each-piece-lands
bullets, the seven-to-eight sweep whose six-to-seven twin the #67
round caught. Rule 5 of the enumerated-baseline record is the
promise-side half this completes, and the amendment cites it.

## Module layout

- `src/vinga_server/transcript_export.py`, new module: the queue,
  worker, acknowledgement wait, store read and outcome events
  behind `build_transcript_export(...) -> TranscriptExport | None`.
  What callers stop knowing: the composition wires one call into
  the session's close ordering and one shutdown onto the exit
  stack, and knows nothing of writer acknowledgements, read seams,
  retained trace contexts or span vocabulary. Deletion test: argued
  under "a sibling module" above.
- `telemetry.py`: `export_transcript(session, turns)` beside
  `reference_media`, sharing `_continuing`; the two new names join
  `AFTER_THE_CLOSE`; the vocabulary-exception note widens by one
  sentence.
- `conversations/threads.py`: `session_turns(connection, session)`
  (the moved query) and `Reads.session_turns(session)`;
  `conversations/api.py` keeps the route and loses the inline
  query.
- `conversations/store.py` and `records.py`: `Close` carries an
  `Acknowledgement`; `close_session` returns it; the writer settles
  it where it settles the milestone's.
- `events/catalog.py`, `events/values.py`: the pair, the closed
  set, the channel.
- `config/models.py`: the `export_transcripts` field (M3) and the
  `attach_captures` to `export_audio` rename (M1); generated server
  reference, both example configs.
- `device/session.py` and `app.py`: composition wiring only.

## Tests

- **Unit, rename (M1)**: the existing capture-upload and
  config-example suites respelled; one new case pinning that the
  old key is refused (`extra="forbid"` naming `attach_captures`);
  the reference regenerated and diffed by the standing drift check.
- **Unit, threads (M2)**: the moved query pinned behavior-identical
  through the route's existing contract tests plus a response pin
  committed green before the move and byte-unchanged after.
- **Unit, exporter (M3)**: build-nothing cases (recording off three
  ways, flag off) and the info line's presence exactly when the
  flag is on; the two refusals value-free and unchained; the
  decision order (recording-off with `local_only` on boots); a
  multi-turn session exporting one span per turn with the attribute
  set pinned, legs present exactly on the handover turn, both id
  spellings; the resumed-conversation case (second session exports
  only its own turns); null-text turns skipped and the empty
  session silent; the five failure reasons each driven at its
  decision site (a settled-`False` acknowledgement, an `Unreadable`
  read, a missing retained context, a failing export seam, a full
  queue); the drain case
  (`max_sessions` concurrent closes with the backlog occupied,
  every job accounted for as exported or dropped-with-event); the
  close ordering (nothing enqueued before `session_closed`, session
  close latency bounded when the worker is wedged); sentinel plants
  (credential-shaped text as `heard`/`reply`) asserted absent from
  both log formats, both events' payloads and exception chains for
  every failure family, and present only in the span attributes;
  session id positional, bounded by `SessionId`.
- **Unit, telemetry (M3)**: `export_transcript` `True`/`False`
  contract (never-seen, evicted, stopped); the two new events
  folding through `AFTER_THE_CLOSE` from the retention, pinned the
  way the capture pair's fold is.
- **Unit, store (M3)**: the close acknowledgement settles `True`
  after commit and `False` on drop and on a stopped store; ordering
  (an acknowledged close implies the session's earlier turns
  readable, driven, not assumed).
- **Integration (M3)**: the wire claim, decoded from protobuf a
  `Receiver` collected: a real device conversation with a handover,
  transcripts arriving as spans in the session trace with input,
  output and legs spelled as recorded, and the sentinel present in
  exactly the span attributes and nowhere else on the wire's event
  spans; the blackholed endpoint (an accept-and-never-answer
  receiver, three latencies asserted separately: session close,
  the `undelivered` failure event within the timeout budget,
  shutdown within its own bound); a wedged-store case proving the
  session closes unaffected within its bound and the `unrecorded`
  event fires within the wait's budget.
- **Live, recorded not asserted (M3)**: the walkthrough against a
  self-hosted Langfuse (the #67 stack), a multi-turn conversation
  with a handover, the acceptance read back through
  `/api/public/v2/observations`: each turn's text in the rendered
  input/output fields, legs attributed. Failures recorded the way
  #67 M1's were.

## Risks

- **Whether Langfuse renders `langfuse.observation.input`/`output`
  attributes on plain OTLP spans as observation input and output.**
  #67 M1 proved the output and metadata halves live (the media
  token probe); input is the same mechanism and the walkthrough
  proves it before the milestone claims it. If rendering fails, the
  content moves to the metadata field family, which the probe
  proved, and the acceptance's "rendered input/output fields"
  criterion is amended transparently on the PR.
- **Content territory widens every round** (five issues running);
  the sentinel suite is written with the exporter's first commit,
  and the review chain is priced as sol plus a terra delta minimum,
  with M3 expecting the #67-shaped narrowing passes.
- **The acknowledgement changes a store record.** `Close` is a
  control record on a hot writer path; the change is
  additive (a handle today's callers do not receive), the writer
  settles exactly where it settles milestones, and the store's
  existing drain tests hold it.
- **A 30 s acknowledgement wait per job serializes a wedged store's
  backlog.** Accepted: the queue is bounded, the drop event is the
  honest ledger, and a store wedged for minutes is a louder problem
  than late transcripts.

## Milestones

- [ ] **M1: rename `attach_captures` to `export_audio`.** The
  sweep as scoped under "the rename is its own leading milestone":
  field, key constant, sentences, sixteen test sites, both example
  configs, regenerated reference, observability map row, ADR
  amendment spelling with the rename clause, workflow and
  pyproject comments; the old-key refusal pin; census checked,
  regenerated if stale; fragment
  `changelog.d/495-export-audio-rename.md` (### Changed). Design
  footprint: renames on existing modules, no new seam. Documentation
  footprint: the pages above, each through its owner; generated
  reference only through its generator.
- [ ] **M2: the session-turns query gets one home.** The inline
  `api.py` query moves to `threads.py` as `session_turns`, the
  route calls it, the response pinned byte-identical; no `Reads`
  method yet (its caller arrives in M3). Design footprint: deepens
  `threads.py` as the home of thread and session reads; `api.py`
  loses implementation knowledge. Documentation footprint: none
  staled (an internal move; the API contract is pinned unchanged),
  stated per the plan rule; fragment not needed, no observable
  change, and the changelog records notable changes only.
- [ ] **M3: the flag, the exporter, the vocabulary, the record.**
  `export_transcripts` with its prose and refusal order;
  `transcript_export.py`; `Reads.session_turns`; the `Close`
  acknowledgement; `Telemetry.export_transcript` and the fold
  additions; the two events, closed set, channel, drivers,
  regenerated events reference and README index rows; generated
  server reference and both example configs; the
  observability-surfaces eighth surface and tier table; the ADR
  amendment; composition wiring; the sentinel, hardening and drain
  suites; the live walkthrough recorded; fragment
  `changelog.d/495-transcript-export.md` (### Added). Design
  footprint: the new module with its depth sentence, one returned
  acknowledgement on an existing seam, one method each on
  `Telemetry` and `Reads`. Documentation footprint as listed, each
  page through its owner.

## Plan review round

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-12, runtime 6m11s, reviewing commit 38c2550c.
Verdict as received: **not ready** (the delivery design cannot
satisfy the required unreachable-backend outcome, and the plan
reserved permission to weaken a settled acceptance criterion).
Findings condensed but faithful; resolutions appended per amendment.

1. **P1: The OTLP queue cannot report the required
   backend-unreachable failure.** The issue requires a warning event
   when the backend is unreachable; the plan treats
   `BatchSpanProcessor` enqueueing as delivery, `reference_media`
   itself returns `True` at `span.end()` while saturation drops
   silently, the closed set holds no unreachable member, and the
   blackholed-endpoint integration case is missing. Define a
   delivery mechanism producing a bounded per-job result from OTLP
   export (queue rejection and collector failure included) without
   blocking the session path, add the closed reason and the
   blackhole test, or change the transport design.

   *Resolution.* Adopted; the transport half changed. Transcript
   spans no longer ride the shared `BatchSpanProcessor`: they are
   built on a private tracer, collected in memory, and delivered by
   one bounded call to a dedicated OTLP exporter instance (same
   class, same `_Sdk` seam, same environment; lazily constructed on
   the worker thread), with `SpanExportResult` deciding a new
   closed reason `undelivered` and the exporter's internal bounded
   retry as the whole retry policy. The worker takes a quieting
   lease over the OTel namespaces past shutdown expiry. The
   blackhole integration case joins the Tests section with three
   latencies asserted separately. The outcome events keep riding
   the shared queue best-effort, stated as such: the log is their
   surface of record.

2. **P1: The plan explicitly permits violating the settled
   input/output requirement.** The risk section says a failed
   rendering moves content to metadata and amends the acceptance
   criterion on the PR; the issue's decisions are not open to
   amendment by this plan. Make the live walkthrough a milestone
   gate: if either field does not render, stop and redesign, never
   substitute or amend.

3. **P2: The proposed shared session-turn query is not the query
   the API currently owns.** The route also validates session
   existence, parses cursor and limit, applies `id > cursor`,
   fetches `limit + 1`, builds pagination metadata and nests tool
   invocations; the planned `session_turns(connection, session)`
   cannot express that contract, and the exporter needs none of it.
   Specify a narrow row-read primitive with an explicit projection
   and ordering; the API keeps its validation, pagination and
   nesting; the exporter receives only the authorized transcript
   fields.

4. **P2: The legs representation is not a valid OpenTelemetry
   attribute as written.** The column is an array of objects;
   span attributes take primitives or homogeneous primitive arrays,
   and the existing post-close writes are string-valued. Define an
   exact wire encoding (canonical JSON string after allowlisting
   `agent` and `text`), verify the rendering live, pin both the
   protobuf value and the rendered result.

5. **P2: Shutdown can tear down the worker's dependencies while a
   30-second job is still running.** A job may wait 30 s on the
   store acknowledgement, telemetry's shutdown allowance is five
   seconds, exit-stack unwinding can stop the store and telemetry
   while the daemon still waits, and an in-flight job is not queued
   so the stated `dropped` accounting does not cover it. State exact
   teardown ordering and an interruptible worker protocol; both
   queued and in-flight waits terminate within the join budget and
   emit their final outcome while the store, tap and telemetry are
   still available; test shutdown during an acknowledgement wait.

6. **P2: Fixed trace retention cannot support the configurable
   session/backlog bound.** `max_sessions` has no upper bound,
   telemetry retains 64 contexts oldest-evicted, so above 64 live
   sessions, or with completed sessions queued ahead of a slow
   worker, healthy exports become `no_trace`; the drain test never
   requires a value above 64. Pin retained context per admitted job
   or derive a proved retention bound from configured capacity;
   test capacity above 64 under eviction pressure.

7. **P2: Reusing `Acknowledgement` contradicts its existing
   contract.** The class states repeatedly that it speaks for one
   turn and nothing else; the plan uses a close acknowledgement as
   proof that every earlier session record resolved, without naming
   the contract revision. Introduce a documented close/barrier
   semantics or deliberately generalize the class and its
   docstrings; tests must distinguish close-transaction failure
   from earlier turns dropped and counted.

8. **P2: The no-leak tests do not seed the newly read out-of-scope
   content.** The shared read includes complete rows and nested tool
   invocations while the sentinels seed only `heard` and `reply`,
   so tool arguments, tool results and leg token halves are
   unproven. Use a narrow projection and plant distinct
   credential-shaped sentinels in every excluded content-bearing
   field the read path can encounter, asserted absent from
   attributes, protobuf requests, both log formats, event payloads
   and exception chains.

9. **P2: A global database row ID is not the requested turn
   index.** `turns.id` is a database-wide identity and timeline
   cursor, so a later session begins at an arbitrary number. Export
   an explicit session-local ordinal named as an index with its
   base convention stated and tested; keep the row id separately
   for store correlation.
