# Conversation content and telemetry are separate surfaces

**Status:** Accepted (recorded 2026-08-15; the log-surface narrowing
took effect on 2026-08-16, when the conversation store of
[#120](https://github.com/rafacm/samtal/issues/120) landed with it)

## Context

The 2026-08-04 record made the structured JSON log events both the
observability surface and the transcript store, standing in for a
conversation store until one existed. That double duty has a measured
cost. The retained log is governed by the no-leak contract (no secret
or far-side bytes on any kept surface), and a surface that must carry
conversation-adjacent detail keeps colliding with that contract: of
the roughly thirty findings across the external review rounds of the
2026-08-14 refactoring batch (PRs #147 through #154), nineteen were
leak-shaped content on the retained log, each found, fixed, and
re-reviewed by hand.

The industry pattern, verified against the OpenTelemetry GenAI
semantic conventions and the self-hosted LLM observability stacks
(sources collected in the 2026-08-15 research pass, kept in
[../architecture/observability-surfaces.md](../architecture/observability-surfaces.md)): message content and telemetry are different data
classes. The OTel GenAI instrumentations emit metadata attributes
(model, provider, token counts, durations) unconditionally and gate
content behind an explicit opt-in
(`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`, default
`no_content`), carrying content as separate events correlated by
trace id rather than as span attributes. The trace/conversation
stores (Langfuse and peers) hold content as the system of record with
their own masking hooks, deletion APIs, and access control, while
application logs stay diagnostic. Redaction guidance across the
sources is unanimous that source-side restriction (closed schemas,
allowlists) is the guarantee and sink-side scrubbing at most a net.
The needs map, the tier table, and the sources live in
[../architecture/observability-surfaces.md](../architecture/observability-surfaces.md).

Meanwhile #138 built the machinery this decision needs: one emitter
(`samtal_server/events.py`), closed reason-token sets, pin suites over
every emit path, an AST guard, and a consumer tap the store attaches
to.

## Decision

samtal keeps four surfaces, each with its own content class,
retention, and access model:

1. **Structured events** (the log): metadata only. Closed field sets,
   reason tokens from closed sets, identifiers, counts, durations.
   Event field names adopt the OTel GenAI vocabulary where one exists
   (`gen_ai.usage.input_tokens` and kin adapted to the existing field
   style), so exporters (#66/#67) and cost accounting consume them
   without mapping. No conversation text, no far-side bytes, no
   exception message text.
2. **The conversation store** (#120): the system of record for
   content. Turns, tool and MCP calls and their results as
   first-class records, keyed by session and user, with per-user
   access scoping, retention policy, and deletion built in from the
   start.
3. **Capture**: the explicit opt-in rich channel (raw audio plus
   decision track), short-lived, already governed.
4. **Audit**: admin and config actions, auth refusals, reload
   invocations; narrow content, long retention, append-only
   expectations.

The transcript-store role of the JSON logs ended when #120's store
landed, which is what the 2026-08-04 record's follow-up note records.
Events remain a compatibility surface exactly as before;
this record changes what may ride on them, not how they are
versioned. Live views (the admin UI's "what is happening now") are
fed from the event tap, not from a store.

### Amendment: device descriptors are metadata (2026-08-17)

Deciding #155's schema registry surfaced a tension between this
record's "no far-side bytes" and a surface the onboarding work
built deliberately: `ota_check` and its kin retain the board model,
firmware version, and client id a device reports at check-in,
bounded and sanitized at their decision sites, and the operator
workflow leans on them (which board is waiting to be claimed, which
firmware a misbehaving device runs). Decided, as a deliberate
product call rather than a reading of the original text:

- **Bounded device-descriptor metadata is metadata**, in the sense
  surface 1 permits: an identifier-class fact about the endpoint,
  not content that traveled through a conversation. Such a field is
  lawful on the events only where its decision site bounds and
  sanitizes it, and the #155 registry declares exactly which fields
  carry it, with the bounds enforced again at emit.
- **Conversation-derived text remains banned without exception.**
  A transcript, however it was recovered, is content; the one
  standing violation (the `asr_prompt_echo` recovered-transcript
  sentence) is removed by its own narrowing issue as a prerequisite
  to #155's enforcement, not grandfathered by it.

The distinction, in one sentence: what a device says ABOUT ITSELF
at check-in may ride the events once bounded; what a person said
through the device may not.

### Amendment: content may be exported under a flag of its own (2026-09-12)

#67 asked for a closed session's recording to be attached to the
trace that session was exported under, which reads at first like
this record's separation breaking: a recording is content, the
telemetry backend is where metadata goes, and the two were
deliberately kept apart. Decided, again as a product call rather
than a reading of the original text:

- **The separation holds, and it is about the JSON log.** What this
  record separates is the metadata-only event surface from the
  content stores. The events stay metadata-only, the OTLP spans
  derived from them stay metadata-only, and no span gains a
  transcript or a byte of audio. What #67 adds is not content ON a
  span; it is content in a second content-capable store, associated
  with a span by identifier.
- **Exporting content is a decision, so it is a switch.** The
  operator turns on `server.telemetry.export_audio`, which
  defaults off and which neither `server.capture` nor
  `server.telemetry.enabled` implies. The key was recorded here as
  `attach_captures` and renamed by the transcript-export work
  (#495), which gave the ladder's two content escalations one
  vocabulary; the semantics this amendment records did not move with
  the spelling. Recording a room for
  diagnosis and shipping that recording to another deployment are
  two decisions, and a flag that one implied the other would be
  this record's separation broken in the only way that matters.
- **The retention question moves with the content.** Every surface
  answers how long, who can see it, and can it be deleted. This one
  answers by delegating: the receiving deployment's policy governs,
  vinga keeps nothing, and the flag's own reference prose says so in
  those words. A backend with no policy configured retains
  indefinitely, which is the caution the Consequences below already
  drew from Langfuse's OSS tier, now applying to a surface vinga can
  actually put audio on.
- **The household-consent question is sharpened rather than
  answered.** A household that consented to being recorded has not
  thereby consented to the recording leaving the house. That is
  still open, and the flag is where the decision now lives.

In one sentence: content may leave this deployment only through a
switch an operator sets for that purpose, and the metadata surface
stays metadata whatever that switch says.

## Consequences

- The no-leak contract on the events becomes enforceable by
  construction: with no free-text fields, a leak is a schema
  violation rather than a review finding. A follow-up issue
  (schema-declared events) turns the convention into machinery.
- `heard`, `replied`, and `agent_said` lost their text fields when
  the store landed; that is a breaking change to the event surface,
  belongs in the changelog like any other, and is the point.
- The store inherits the obligations the logs carried implicitly:
  retention tiers, right-to-delete, per-user scoping, and the
  household-consent question, which #120's plan must resolve.
- Operator tooling that greps transcripts out of logs migrates to
  the store's query surface; the #22-style latency briefs keep
  working unchanged, since they read metadata the events keep.
- Self-hosting caution, learned from Langfuse's OSS tier: a store
  with no retention policy retains indefinitely by default. #120
  ships retention as configuration with a stated default, not as a
  later feature.
