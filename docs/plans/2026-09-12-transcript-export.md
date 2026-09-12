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

That is a contract revision, made deliberately rather than slipped:
`Acknowledgement` today says repeatedly that it speaks for one turn
and nothing else. The class docstring generalizes to "its own
record", and the barrier meaning lives where the barrier is: the
`Close` record and `close_session` document that, because one
writer thread consumes one FIFO queue, a close acknowledgement
settling `True` means every earlier record of the queue has been
resolved, landed or dropped-and-counted, and nothing more. The
"nothing more" is itself part of the contract and part of the
design: a close can commit after an earlier turn was dropped, the
acknowledgement still answers `True`, and the export then carries
exactly what the store holds, which is correct because the store is
the issue's settled source of truth, not the conversation as
spoken. The per-turn docstring sentences that would become false
move with the change. Tests drive both sides: the close transaction
itself failing answers `False`, and an earlier turn
dropped-and-counted under a committed close answers `True` with the
export carrying the stored turns.

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

Delivery is chunked to match: the worker's per-job loop alternates
one page read with one bounded export call of that page's spans,
`TRANSCRIPT_BATCH_TURNS` per request, in order, so an arbitrarily
long session costs bounded memory and bounded per-request work
however many pages it takes. A page's export answering failure ends
the job with `undelivered`: the pages already delivered stand (the
backend shows the leading turns), the failure event on the trace
and in the log is what tells a reader the transcript is truncated
there, and no delivered-count rides the event, per the no-carry
discipline; the truncation is visible where the reader already is,
as the highest exported `vinga.turn.index` beside the failure
event. Tests drive an oversized session (three-plus pages, every
turn present exactly once, ordinals continuous across page
boundaries) and a mid-page failure (leading pages stand,
`undelivered` emitted, the job ends without reading further). A
single turn's stored text has no ceiling of its own here: bounding
what a conversation may store is the store's question, not the
exporter's, and the page bound is what keeps any one request
proportionate.

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

Teardown is ordered and the worker is interruptible, because a job
may lawfully sit 30 s in an acknowledgement wait while the process
shuts down. The composition pushes the exporter's shutdown onto the
exit stack LAST, so it unwinds FIRST, while the store, the event
tap and telemetry are all still up; its join budget is the 5 s
shutdown posture. Inside that budget the worker is interrupted, not
merely joined: `shutdown` sets a stop flag, the acknowledgement
wait polls in `POLL_S` slices watching it (the `capture_upload`
pattern), and a stopped worker emits the final outcome for its
IN-FLIGHT job as well as for everything still queued, all as
`dropped`, whose definition is widened accordingly: the queue bound
turned the job away, or shutdown ended it before completion,
queued or in flight. Only the bounded export call itself is not
interruptible mid-request; its own 30 s ceiling is why the join can
expire, and a late `undelivered` after the join lands in a logger
the worker's own quieting lease still covers, the #67 M3 rule. The
test drives shutdown DURING an acknowledgement wait, not merely
with work queued, and asserts the in-flight job's `dropped` event
was emitted while the tap was still attached.

The retained trace context is captured at admission, not looked up
at export, and the retention itself is sized from configured
capacity. Two holes the fixed 64-entry retention leaves, closed
separately. First, a job queued behind a slow worker could see its
context evicted by later sessions before the worker reached it: so
`session_closed` asks telemetry for the retained context THEN and
stores it in the job, making `no_trace` an admission-time answer an
eviction can no longer change. Second, `_retain` records at session
OPEN and `server.limits.max_sessions` has no upper bound, so a
deployment running more than 64 concurrent sessions would evict a
LIVE session's context before it ever closed: so the retention
bound stops being a constant and becomes `max_sessions` plus the
existing 64 of slack, computed where telemetry is built, which by
construction means no live session's context is evicted by
concurrent opens and the after-close window keeps its current
depth. The resize helps the capture
uploader only incidentally, and the plan claims no more than that:
capture jobs do not pin a context and resolve `trace_of` later on
their own worker, so a blocked capture worker under
`max_sessions > 64` can still find older contexts evicted. That is
the existing surface's existing exposure, narrowed but not closed
here, and closing it (pinning the context into capture jobs) is
the capture uploader's own follow-up, out of this issue's scope.
Tests
drive a capacity above 64 with every session live, and eviction
pressure (64-plus later sessions opening) between a job's admission
and its export.

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

### The read surface: a narrow transcript projection, not the API's query

The first draft moved the route's inline query
(`conversations/api.py:847`) to `threads.py` as a shared home; the
review round showed the two readers do not want the same query. The
route's contract is session-existence validation, cursor and limit
parsing, `id > cursor`, `limit + 1` pagination metadata and nested
tool invocations; the exporter wants none of that and must not read
it (tool arguments and results are content beyond the issue's
authorization). Two different questions are two queries, so nothing
moves and the API route stays untouched.

What the exporter gets instead is its own narrow primitive:
`threads.transcript_rows(connection, session)`, an explicit
projection of exactly the authorized transcript fields (`id`,
`t_ms`, `agent`, `heard`, `reply`, `legs`), ordered by `id`
ascending, read in keyset pages of `TRANSCRIPT_BATCH_TURNS = 256`
(`id > cursor`, the schema's own cursor idiom), with the
session-local ordinal derived from that ordering and carried across
pages. Nothing about a session bounds its turn count (`max_session_s`
bounds elapsed time, not turns), so the page size is what bounds the
database result, the in-memory span collection and each protobuf
payload; the whole-session read the first draft assumed is gone. `threads.Reads`,
the engine-per-call never-raise seam built for callers outside a
request (`threads.py:851`), gains `transcript_rows(session)`
delegating to it, in the same milestone as its only caller. `Reads`
answering `Unreadable` is the exporter's `unreadable` reason; a
raise would quote a DSN, which is why the seam exists. By
construction the read path never selects tool invocations or any
other content-bearing column, which is what the sentinel suite then
proves rather than assumes.

### The span shape, and the two vocabulary rules it extends

One span per turn, named `transcript`, written by a new
`Telemetry.export_transcript(session, context, turns)` beside
`reference_media` and shaped by it: children of the session span
named by the PASSED context via `_continuing`, written after the
session's own spans have ended and exported. The context boundary
is explicit: admission (`session_closed`) obtains the opaque
retained context through a narrow `Telemetry.retained_context(
session)` read, a `None` there is `transcript_export_failed` with
reason `no_trace` decided at admission and never at export, and an
admitted job exports against its captured context however the
retention has moved since. `export_transcript`'s own failure
contract covers only what it owns: stopped acceptance and span
construction answer as a job-level `dropped` (shutdown territory),
and delivery answers `delivered` or `undelivered` per page. Each span carries the session id under both
spellings (grouping), `vinga.turn.index` (the issue's "turn index":
a session-local ordinal, 1-based, derived from the projection's
`id`-ascending ordering, so any session's first exported turn is
index 1, tested on a resumed thread's second session),
`vinga.turn.id` (the schema's database-wide identity, kept
separately because it is what correlates the observation back to
the store's row and the API's cursor), `vinga.turn.t_ms`
and `vinga.agent` (the agent the turn opened with), and the content
in the fields the backend renders: `langfuse.observation.input` for
`heard`, `langfuse.observation.output` for `reply`. Where the
`legs` column is present (a handover split the reply), the per-leg
attribution rides `langfuse.observation.metadata.legs` under an
exact wire encoding: a canonical JSON document (sorted keys, no
extra whitespace) serialized to ONE STRING attribute value, holding
the legs in order, each allowlisted to `agent` and `text`. A string
because OTel span attributes take primitives or homogeneous
primitive arrays, never mappings, and the existing post-close
writes are all string-valued; allowlisted because the token halves
are metadata the generations already carry, and content plus its
attribution is what this observation adds. The unit pin asserts the
exact serialized string, the wire test asserts the protobuf value,
and the walkthrough records how the backend renders it. A turn whose text halves are both null (recorded
before text was on, or nothing spoken) exports no span; a session
whose readable turns number zero exports nothing and emits nothing,
because a trail entry for an empty export would be noise a reader
filters out, and the flag's no-op line at boot already says why
nothing will ever export when that is config's doing.

Spans are timestamped at export time and ordered by
`vinga.turn.index`;
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
- `telemetry.py`: `retained_context(session)` and
  `export_transcript(session, context, turns)` beside
  `reference_media`, sharing `_continuing`; the two new names join
  `AFTER_THE_CLOSE`; the vocabulary-exception note widens by one
  sentence.
- `conversations/threads.py`:
  `transcript_rows(connection, session, after, limit)` (the narrow
  keyset projection) and `Reads.transcript_rows(session, after,
  limit)`; `conversations/api.py` is untouched.
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
- **Unit, threads (M2)**: `transcript_rows` returns exactly the
  projection, ordered by `id`, only the named session's rows,
  keyset paging (`after`/`limit`) with no row repeated or skipped
  across pages, and the ordinal convention; a row family carrying
  tool invocations proves none are selected.
- **Unit, exporter (M2)**: build-nothing cases (recording off three
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
  close latency bounded when the worker is wedged); shutdown during
  an acknowledgement wait (the in-flight job's `dropped` emitted
  within the join budget, tap still attached); sentinel plants in TWO
  families with opposite claims: in-projection sentinels
  (credential-shaped text as `heard`, `reply` and a leg's `text`)
  asserted absent from both log formats, both events' payloads and
  exception chains for every failure family and present only in
  the span attributes and the wire; and out-of-projection
  sentinels, distinct values planted in every content-bearing
  field the row family can hold that the export is NOT authorized
  to read (tool invocation arguments and results, a milestone
  recap's text, the legs' token halves replaced by marker
  numbers), asserted absent from the span attributes, the protobuf
  request, both log formats, event payloads and exception chains,
  which is what proves the projection rather than trusting it;
  session id positional, bounded by `SessionId`.
- **Unit, telemetry (M2)**: `retained_context` answers the context
  after the close and `None` for a never-seen or evicted session;
  a job admitted with a captured context exports correctly after
  the retention has evicted that session (eviction pressure
  between admission and export); `export_transcript` under stopped
  acceptance; the two new events folding through `AFTER_THE_CLOSE`
  from the retention, pinned the way the capture pair's fold is.
- **Unit, store (M2)**: the close acknowledgement settles `True`
  after commit and `False` on drop and on a stopped store; ordering
  (an acknowledged close implies the session's earlier turns
  readable, driven, not assumed).
- **Integration (M2)**: the wire claim, decoded from protobuf a
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
- **Live, recorded not asserted (M2)**: the walkthrough against a
  self-hosted Langfuse (the #67 stack), a multi-turn conversation
  with a handover, the acceptance read back through
  `/api/public/v2/observations`: each turn's text in the rendered
  input/output fields, legs attributed. Failures recorded the way
  #67 M1's were.

## Risks

- **Whether Langfuse renders `langfuse.observation.input`/`output`
  attributes on plain OTLP spans as observation input and output.**
  #67 M1 proved the output and metadata halves live (the media
  token probe); input is the same mechanism. The live walkthrough
  is a MILESTONE GATE, run early in M2 as a probe span before the
  exporter is built around the shape: if either field does not
  render as the acceptance requires, the milestone stops and the
  attribute shape or transport is redesigned until it does. The
  acceptance criterion is settled by the issue and is not amended,
  and no metadata substitution is shipped in its place.
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

- [x] **[M1: rename `attach_captures` to `export_audio`](2026-09-12-transcript-export-implementation.md#m1-rename-attach_captures-to-export_audio)** (PR #497). The
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
- [x] **[M2: the flag, the exporter, the vocabulary, the record](2026-09-12-transcript-export-implementation.md#m2-the-flag-the-exporter-the-vocabulary-the-record)** (PR #498).
  The rendering-gate probe first, its result recorded;
  `export_transcripts` with its prose and refusal order;
  `transcript_export.py`; `threads.transcript_rows` and
  `Reads.transcript_rows`; the `Close`
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
  `Telemetry`, `threads` and `Reads`. Documentation footprint as
  listed, each page through its owner.

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

   *Resolution.* Adopted. The risk now states the walkthrough as a
   milestone gate, run early in the exporter milestone as a probe
   span before the exporter is built around the shape; a rendering
   failure stops the milestone for redesign, the criterion is not
   amendable by this plan, and no substitution ships.

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

   *Resolution.* Adopted; the shared-home milestone dissolved. Two
   readers asking two questions are two queries, so the API route
   stays untouched and the exporter gets its own narrow primitive,
   `threads.transcript_rows(connection, session)` with an explicit
   projection (`id`, `t_ms`, `agent`, `heard`, `reply`, `legs`)
   ordered by `id`, plus `Reads.transcript_rows(session)`, landing
   in the milestone with their only caller. The plan is now two
   milestones (M1 rename, M2 exporter), renumbered throughout.

4. **P2: The legs representation is not a valid OpenTelemetry
   attribute as written.** The column is an array of objects;
   span attributes take primitives or homogeneous primitive arrays,
   and the existing post-close writes are string-valued. Define an
   exact wire encoding (canonical JSON string after allowlisting
   `agent` and `text`), verify the rendering live, pin both the
   protobuf value and the rendered result.

   *Resolution.* Adopted. The span-shape section now fixes the
   encoding: one string attribute holding canonical JSON (sorted
   keys, no extra whitespace) of the legs in order, each
   allowlisted to `agent` and `text`; the unit pin asserts the
   exact string, the wire test the protobuf value, and the
   walkthrough records the rendering.

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

   *Resolution.* Adopted. The worker section now states the
   ordering (the exporter's shutdown pushed last so it unwinds
   first, before the store, tap and telemetry go down) and the
   interruptible protocol (a stop flag polled in `POLL_S` slices
   inside the acknowledgement wait; the in-flight job and the
   queued ones all emit `dropped`, whose definition widened to
   cover shutdown ending a job in flight); the
   shutdown-during-wait case joins the Tests section.

6. **P2: Fixed trace retention cannot support the configurable
   session/backlog bound.** `max_sessions` has no upper bound,
   telemetry retains 64 contexts oldest-evicted, so above 64 live
   sessions, or with completed sessions queued ahead of a slow
   worker, healthy exports become `no_trace`; the drain test never
   requires a value above 64. Pin retained context per admitted job
   or derive a proved retention bound from configured capacity;
   test capacity above 64 under eviction pressure.

   *Resolution.* Adopted, both halves. The retained context is
   captured into the job at admission, so `no_trace` is decided at
   `session_closed` and later eviction cannot change it; and the
   retention bound derives from `server.limits.max_sessions` plus
   the existing 64 of slack where telemetry is built, so a live
   session's context cannot be evicted by concurrent opens. Both
   tests named (capacity above 64, eviction pressure between
   admission and export). The delta round then refuted the clause
   claiming the capture uploader inherits the guarantee; its
   finding 3 below records the honest statement.

7. **P2: Reusing `Acknowledgement` contradicts its existing
   contract.** The class states repeatedly that it speaks for one
   turn and nothing else; the plan uses a close acknowledgement as
   proof that every earlier session record resolved, without naming
   the contract revision. Introduce a documented close/barrier
   semantics or deliberately generalize the class and its
   docstrings; tests must distinguish close-transaction failure
   from earlier turns dropped and counted.

   *Resolution.* Adopted, the generalization branch. The class
   docstring moves from "its own turn" to "its own record"; the
   barrier semantics are documented on `Close` and `close_session`
   where the barrier is, including the stated limit that a
   committed close after a dropped-and-counted turn answers `True`
   and the export carries what the store holds (the store being the
   issue's settled source of truth); both sides are driven by
   tests, and the turn-specific docstring sentences move with the
   change.

8. **P2: The no-leak tests do not seed the newly read out-of-scope
   content.** The shared read includes complete rows and nested tool
   invocations while the sentinels seed only `heard` and `reply`,
   so tool arguments, tool results and leg token halves are
   unproven. Use a narrow projection and plant distinct
   credential-shaped sentinels in every excluded content-bearing
   field the read path can encounter, asserted absent from
   attributes, protobuf requests, both log formats, event payloads
   and exception chains.

   *Resolution.* Adopted, on top of finding 3's narrowed
   projection. The sentinel suite now has two families with
   opposite claims: in-projection sentinels present only in the
   span attributes and the wire, and distinct out-of-projection
   sentinels (tool arguments, tool results, recap text, marker
   token values) planted in the stored rows and asserted absent
   from the attributes, the protobuf request, both log formats,
   event payloads and exception chains.

9. **P2: A global database row ID is not the requested turn
   index.** `turns.id` is a database-wide identity and timeline
   cursor, so a later session begins at an arbitrary number. Export
   an explicit session-local ordinal named as an index with its
   base convention stated and tested; keep the row id separately
   for store correlation.

   *Resolution.* Adopted. The span carries `vinga.turn.index`, a
   1-based session-local ordinal derived from the projection's
   `id`-ascending ordering (any session's first exported turn is
   index 1, tested on a resumed thread's second session), and
   `vinga.turn.id` stays beside it as the store-correlation
   identity.

### Delta re-review

External review: codex CLI 0.154.0, model gpt-5.6-terra, read-only
sandbox, 2026-09-12, runtime 3m05s, reviewing commit 920f8d2c.
Verdict as received: **ready after the P1/P2 amendments**. Findings
condensed but faithful; resolutions appended per amendment.

1. **P1: Whole-session export is not bounded.** The plan calls the
   unpaginated projection safe because "a session's turn count is
   bounded by the session", but `max_session_s` bounds elapsed time,
   not turns, and no turn-count or transcript-byte limit exists, so
   the database result, in-memory span collection, protobuf payload
   and pre-timeout work are unbounded. Say how the exporter bounds
   rows, bytes and spans per delivery and per job (cursor/batch
   protocol, ordering, partial-delivery outcome, oversized-session
   tests), or name a v1 session export limit with its
   operator-visible failure reason.

   *Resolution.* Adopted, the batch protocol. `transcript_rows`
   becomes a keyset page read (`after`, `limit`), the worker
   alternates one page read with one bounded export call at
   `TRANSCRIPT_BATCH_TURNS = 256`, ordinals carry across pages, a
   failed page ends the job with `undelivered` and the delivered
   pages stand, visible as the leading turns beside the failure
   event; the oversized-session and mid-page-failure tests are
   named, and the per-turn text ceiling is stated as the store's
   question, not the exporter's.

2. **P2: Retained-context ownership contradicts the proposed
   telemetry interface.** The amendment captures the context in the
   admitted job, but the span-shape section and module layout still
   define `export_transcript(session, turns)` looking retention up
   at export time and answering `False` on eviction, and the tests
   expect both eviction-pressure success and an evicted-`False`
   contract; these cannot all hold. Admission obtains the context;
   `no_trace` is decided there; admitted jobs pass the opaque
   context to `export_transcript(session, context, turns)`, whose
   failure contract covers only stopped acceptance and delivery.

   *Resolution.* Adopted. The boundary is now explicit everywhere
   the body spoke: admission reads `Telemetry.retained_context(
   session)`, `None` there is `no_trace` decided at admission, the
   job carries the opaque context, `export_transcript(session,
   context, turns)` parents on the passed context and fails only
   on stopped acceptance (job-level `dropped`) or delivery
   (`undelivered`), and the telemetry tests now drive
   post-eviction export success and admission-time `None`.

3. **P2: The retention amendment incorrectly promises the capture
   uploader the new guarantee.** `max_sessions + 64` protects live
   contexts plus 64 closed ones; capture jobs do not pin
   `_Exported` and resolve `trace_of` later on their worker, so a
   blocked capture worker under `max_sessions > 64` can still lose
   older contexts. Remove the inheritance claim or pin the context
   in capture jobs with its own test.

   *Resolution.* Adopted, the removal branch. The retention
   paragraph now states the resize helps the capture uploader only
   incidentally, names the residual exposure (a blocked capture
   worker under `max_sessions > 64`), and marks closing it as the
   capture uploader's own follow-up outside this issue's scope;
   the sol round's resolution 6 note is corrected in place to
   point here.
