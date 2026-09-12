# Observability and conversation-data surfaces

Where may this datum go? Seven surfaces answer it, and this page is the
map of them: what each carries, which need it serves, how long it is
kept and who may read it, and what is true of it in the code today.
[The 2026-08-15 ADR](../adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md)
holds the decision itself and is not restated here; the evidence that
decision was taken on is dated at the foot of this page. The map
changes when the design does.

## On this page

- [The seven surfaces](#the-seven-surfaces): the table this page exists
  for, one row per surface, with its current status.
- [The invariants](#the-invariants): the four rules that decide where
  a new field goes, and that hold whatever the surfaces grow into.
- [Where each piece lands](#where-each-piece-lands): which document
  says what, and what is still open.
- [Decision evidence, gathered
  2026-08-15](#decision-evidence-gathered-2026-08-15): the seven needs
  and the external practice the design was checked against, as they
  were written on the day the decision was taken.

## The seven surfaces

The Serves column numbers the needs in
[the appendix](#the-needs). The Carries column says what class of
thing a surface may hold, never the vocabulary itself: the exact
fields and columns are generated from the declarations and are linked
in the row.

| Surface | Carries | Serves | Retention and access | Status |
| --- | --- | --- | --- | --- |
| **Structured events** (`vinga_server/events/`, the JSON log) | Metadata only: closed field sets, reason tokens from closed sets, trusted identifiers, counts, durations. No conversation text, no far-side bytes, no exception prose. Every variant is in [`reference/events.md`](../reference/events.md) | 1, 5 | Operator log retention (weeks) | **Landed.** Every emission is a typed variant declared in `events/catalog.py`, so a shape that is not declared cannot be constructed at all and the no-leak contract holds by construction rather than by review. Landed twice over since #342: the same emissions are also readable live over `GET /api/runtime/events`, under the same bearer token, which is a second transport over this surface and not a fifth surface. It keeps nothing, it carries the catalogued fields of an event plus a wall-clock stamp and the level's name, which is this row's vocabulary and no more of it than the log already writes, and it is therefore held to this row's no-content contract in full. Need 5 is served rather than merely fed since #439: the `provider_failed` and `barge_in_suppressed` rows this surface writes into the store are counted, against the day's own turns and sessions, by `record.metrics_event_rates_daily` |
| **Conversation store** (the `record` schema) | Content as the system of record: the session spine, the turn timeline, the tool invocations a turn issued and the decision track under them, and the conversation each turn belongs to, which is a durable thread with exactly one agent and may span sessions. Beside them sit the recap checkpoints a thread accrues: one lands where a user consented to a recap of a conversation too long to resume whole, holding what the agent said out loud and the range of turns it read, and every later resume of that thread is rebuilt from it. Every column is in [`reference/conversations-schema.md`](../reference/conversations-schema.md). Audio never enters it | 2, 5 (evals), 7 | `server.conversations.retention_days`, 90 by default, measured against a thread's last activity rather than a session's age: a conversation past the window is deleted whole with its turns and their children, a session's telemetry goes by that session's own age whether or not the session outlives it, and a session record goes once no turn names it any more. On-demand erasure under `/api`, on either entity (`DELETE /api/sessions/{session}`, the selector purge `DELETE /api/sessions`, and `DELETE /api/conversations/{conversation}`, with `vinga session delete`, `vinga session purge` and `vinga conversation delete` in front of them); access-controlled reads under `/api`, one namespace per entity; live read-only SQL as `vinga_ro`, which reaches this schema and not `domain` | **Landed** (#120, threads #190), off unless `server.conversations.enabled` says otherwise, under two independent switches (`telemetry`, `text`). Erasing either entity by name landed with #190's read verbs, and erasure outranks what the store derived: erasing a session takes its turns wherever their conversation is, a title recomputes or is nulled, and a conversation left with no turns is deleted whole; erasing a conversation takes its turns out of whatever sessions they were spoken in and leaves those sessions and their telemetry standing, with a gap in them. Neither ever comes back: a thread a deletion took is refused by the writer rather than recreated by a turn still on its way to it. Need 5's aggregation landed with #439 as four named views in the same schema, added by migration and readable by the same `vinga_ro` role: daily stage-latency percentiles, per-agent token usage attributed leg by leg, provider-failure and barge-in-suppression rates, and the session baseline underneath them, each with its question, its denominator and its telemetry-off behavior in [`reference/metrics-views.md`](../reference/metrics-views.md). Each of the four has a per-device sibling beside it since #440, additive rather than a redefinition, carrying the device a session ran on; the label beside that device is a copy on this side and not a join, because this role is granted here and revoked on `domain`. The readers who are not SQL clients reach all of it over `/api/metrics` and through `vinga metric list` and `vinga metric show`, windowed in whole UTC days and grouped by device on request, which is what #440 landed. Budgets, cost and per-user attribution are not among them and still await users |
| **Capture** (`vinga_server/capture.py`) | Raw audio plus the decision track, three files per session sharing one timeline | 1 (deep diagnosis) | Bounded per session and by a total budget for the directory, oldest captures pruned first | **Landed**, and off unless `server.capture.enabled` is true. The flag is the switch rather than the section, so a field round can stop recording without losing the directory and the budgets. It writes room audio to disk, which is the opposite of what the rest of the project promises, so a server that boots with it on says so once at startup, at WARNING (`capture_enabled`); a session that is being recorded then says which path it is writing to (`capture_started`) |
| **Memory** (the `memory` schema) | Content as what an agent is told to keep, and the only surface here whose content is read back INTO a prompt. Three scopes: an agent's own facts about the person it talks to, a device's notes about the place and the household, shared by every agent bound to that board, and one conversation's ledger of what is currently true in it. Beside the active rows sits a held area: a fact an agent was asked to forget is kept until the conversation that forgot it ends, so the undo it exists for can reach it. Audio never enters it, and neither does a transcript: what lands is what a model chose to store through a tool | 2, 7 | **Facts until they are corrected**, capped per scope and pruned oldest-first at write, with no clock on them: an agent's memory is not telemetry and does not age out. **State and held facts until their thread ends**, which is the conversation record's own retention: a thread's erasure and its retention prune take both in the same transaction as its turns, and a boot sweep heals what no transaction covered. **The operator API is the deletion door**, scope-addressed under `/api/memory` with `vinga memory list`, `vinga memory set` and `vinga memory delete` in front of it: every listing shows orphaned owners, which is what a deleted agent and a deleted device record leave, a rename having moved an agent's rows with it and a board swap having moved a device's, and every deletion through it is a hard delete. No read-only SQL: `vinga_ro` is granted nothing on this schema, so the API is the surface | **Landed** (#314, scopes and editing #83). The schema is unconditional and is migrated at every boot, because an empty table is not a memory; whether a given agent reaches any of it is that agent's own `memory` section, on unless it says otherwise, and one switched off is offered no tool and injected no scope. Storage never leaves the deployment's own database; as prompt content it follows the active LLM provider's egress exactly as the transcript and the persona do, which is what `server.local_only` is the guard for, and a device note therefore reaches the provider of every sibling agent on that board that may remember |
| **Exported traces** (`vinga_server/telemetry.py`, OTLP) | Metadata only, and not its own vocabulary: every span and every span event is derived from the structured-events row above, so this surface can hold nothing that row cannot. A session is one span, each turn a trace of its own linked to it, and inside a turn the stages that took the time: the transcription and how it ended, each generation round, each sentence's synthesis stream, and the paced playback interval. The three a provider ran carry the entry that ran them, under the OpenTelemetry GenAI attribute names for the facts those conventions have a name for. The fields are the ones in [`reference/events.md`](../reference/events.md), under attribute names this module chooses | 1, 5 | **The collector's backend owns retention, and vinga owns none of it.** This surface keeps nothing: spans are queued, batched and sent, and a full queue drops them rather than delaying a reply. How long a trace lives, who may read it and how it is deleted are the receiving backend's policy, configured there and not here. Where it goes and what credentials reach it are the standard `OTEL_EXPORTER_OTLP_*` variables, which are transport configuration and never become span content | **Landed** (#66), and off unless `server.telemetry.enabled` says otherwise. Absent by default, refused under `server.local_only` because sending to a collector is egress like any other, and refused with the extra to install when the packages are missing. It is an `EventTap` on the seam the events package already documents, which is what makes the derivation structural: no emit site moves for it, and it can say nothing `events/catalog.py` does not declare |
| **Exported capture media** (`vinga_server/capture_upload.py`) | Content, and the only surface here that sends any off the host: one closed session's stereo WAV and its JSON manifest, attached to the trace that session was exported under. Exactly those two files. The decision track beside them is a third content-bearing artifact and stays local, and no transcript, no event payload and no identifier from the far side travels either way. What it carries is therefore the capture row above, minus the track, sent to where the exported-traces row already sends metadata | 1 (deep diagnosis, off-host) | **The backend owns retention, and vinga owns none of it.** This surface keeps nothing: a recording is hard-linked aside, uploaded, and the links removed. How long the recording then lives, who may play it and how it is deleted are the receiving deployment's policy, configured there and not here, and a deployment with no policy configured retains indefinitely, which is this project's own recorded caution about self-hosted Langfuse. Where it goes and what credentials reach it are `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`, which the SDK reads and no vinga key holds. Erasure on this side is the operator's act on the backend; deleting a session under `/api` does not reach it | **Landed** (#67), and off unless `server.telemetry.attach_captures` says otherwise, which neither `server.capture` nor `server.telemetry.enabled` implies: room audio leaving the pod is its own decision. With capture off it is a no-op, under `server.local_only` it is refused, and without the `langfuse` extra the boot is refused. It runs on a worker of its own after a session closed, never on the audio path, and every failure is a warning event (`capture_uploaded`, `capture_upload_failed` with a reason from a closed set), because a recording that silently failed to attach would leave a reader with a trace, no audio and no way to learn any was meant to be there |
| **Audit** | Admin and config actions, auth refusals, reload invocations | 4 | Long, append-only, narrow content | **Future.** Nothing writes one today and no issue owns it yet |

## The invariants

Four rules decide where a new field goes. They are the ADR's, restated
as the questions a placement has to answer.

- **What a person said never rides the events.** Metadata on the log,
  content in the store. The line the
  [2026-08-17 amendment](../adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md#amendment-device-descriptors-are-metadata-2026-08-17)
  draws is between the two: what a device says about itself at
  check-in may ride the events once its decision site bounds and
  sanitizes it, and what a person said through the device may not,
  however it was recovered.
- **Restriction is at the source, not at the sink.** A field is
  lawful because it was declared, not because a scrubber failed to
  match it. On the events that is the catalog; on the store it is the
  schema and the two switches.
- **Live and history are two transports over one set of events, not
  two stores.** The admin UI's "what is happening now" is one more
  `EventTap` consumer of the tap #138 built, and the store is a tap
  too. Same events, two transports, no polling. Landed as
  `GET /api/runtime/events` (#342): the hub is that tap, attached to
  both channels at composition, and what it hands a reader is the
  record the log retains and nothing more. A live view keeping its own
  copy would be the retention question answered twice, which is why it
  keeps none: it ends with the reader, and with the server.
- **Every surface answers the retention question.** How long, who can
  see it, can it be deleted: a surface with no policy retains
  forever, which is why the store ships a default window rather than
  a later feature, and why the capture directory has a budget.

## Where each piece lands

- The decision, and why it was taken:
  [the 2026-08-15 ADR](../adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md),
  with its 2026-08-17 amendment on device descriptors.
- The exact vocabulary of the landed surfaces:
  [`reference/events.md`](../reference/events.md) and
  [`reference/conversations-schema.md`](../reference/conversations-schema.md),
  both generated from the declarations and diffed by CI, with
  [`reference/metrics-views.md`](../reference/metrics-views.md) beside
  the second for the named aggregates over it, and, for
  memory, [`reference/api-openapi.json`](../reference/api-openapi.json)
  and [`reference/cli.md`](../reference/cli.md), which are the two
  documents that earn it: nobody but the server reads memory's raw
  tables, so what is published is the addressed surface rather than the
  columns behind it. Nothing on this page repeats a field name or a
  column name, so none of them can go stale here.
- Still open, each with its owner: the audit surface (no issue yet),
  and the household-consent question #120 named and did not close,
  which the seventh surface sharpens rather than answers: a household
  that consented to being recorded for diagnosis has not thereby
  consented to the recording leaving the house, which is why that is a
  flag of its own. The read surface over the aggregates landed with
  #440 and is in the conversation-store row above; the
  LLM-observability exporter and the capture attachment landed with
  #66 and #67 and are the fifth and seventh rows.

## Decision evidence, gathered 2026-08-15

What follows was written on 2026-08-15, when the decision was taken,
and is kept as it was: the seven needs the design balances and the
external practice it was checked against. It is evidence about a
decision, not current guidance, and the map above is what a placement
is held to.

### The needs

Seven, gathered in the 2026-08-15 assessment:

1. **Operational diagnosis.** Enough technical record per session and
   conversation to analyze the steps and fix issues: stage timings,
   provider failures, barge-in decisions, MCP lifecycle.
2. **User transparency.** Enough per-conversation record to show a
   user what happened on their behalf: what was heard, what was
   answered, which MCP service was called and what it returned.
3. **Privacy, retention, and consent.** A household device that hears
   a room, with children as future users: every surface answers "how
   long is this kept, who can see it, can it be deleted", and content
   capture is consent-shaped, never ambient.
4. **Audit.** Admin and config actions, auth refusals, reload
   invocations: a narrow, long-lived, append-only record distinct
   from diagnostics.
5. **Metrics, evaluation, and budgets.** Aggregable usage: latency
   percentiles per stage, token counts per agent and user (the
   product vision's budgets cannot exist without usage records),
   field-test quality signals.
6. **Live view versus history.** "What is happening right now" (the
   admin UI) and "what happened" are different transports over the
   same events, not two stores.
7. **Per-user scoping.** Once family users arrive, a conversation
   record is attributable and access is a policy question the data
   model must make answerable.

Needs 2 and 3 pull against each other, and the resolution is the
design's core: transparency is served from an access-controlled store,
never from logs, so the log surface can hold the no-leak line without
starving the UI.

### The external practice it was checked against

Collected 2026-08-15 (a tavily research pass plus targeted
verification; links below):

- **OpenTelemetry GenAI semantic conventions.** Metadata attributes
  (`gen_ai.operation.name`, `gen_ai.request.model`,
  `gen_ai.usage.input_tokens`, ...) are emitted unconditionally;
  message content is a separate, explicitly opt-in event stream
  (`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`, default
  `no_content`), correlated to spans by id rather than riding them.
  vinga adopts the vocabulary for its usage fields so exporters
  (#66/#67) and budget accounting consume events without mapping.
- **Store-separated LLM observability stacks** (Langfuse, LangSmith,
  Arize Phoenix). Conversation traces live in a purpose-built store
  with masking hooks, deletion APIs, and access control; application
  logs stay diagnostic. Self-hosted caution taken from Langfuse OSS:
  without a configured policy it retains indefinitely, so #120 ships
  retention as configuration with a stated default.
- **Source-side restriction over sink-side scrubbing.** The security
  guidance is unanimous that allowlisted, schema-restricted emission
  is the guarantee and pattern-scrubbing at the sink at most a net;
  #155 (the event registry) is that guarantee made mechanical.
- **Evidence gaps the sources left open**, owned by vinga's own
  design: household/family consent workflows (named open question in
  #120), audit-trail field standards (future issue), and live
  transport choice (decided by the admin UI work, not by this page).

References: OTel GenAI semantic conventions and instrumentation
(opentelemetry.io/blog/2024/otel-generative-ai,
github.com/open-telemetry/semantic-conventions-genai), content-capture
gating (docs.litellm.ai/docs/observability/opentelemetry_v2), sensitive
data handling (opentelemetry.io/docs/security/handling-sensitive-data),
GDPR-shaped pipelines
(oneuptime.com/blog/post/2026-02-06-opentelemetry-pipeline-gdpr-compliant/view),
PII leakage analysis
(systemshardening.com/articles/observability/otel-pii-leakage), Langfuse
self-hosted masking, retention and deletion
(langfuse.com/self-hosting/security/data-masking,
langfuse.com/docs/administration/data-retention,
langfuse.com/docs/administration/data-deletion), store-separation
surveys (arize.com/blog/the-role-of-opentelemetry-in-llm-observability,
patronus.ai/llm-testing/llm-observability).
