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

### Amendment: the export ladder is policy (2026-09-12)

#495 added the second content escalation, a closed session's turns
onto the trace it was exported under, and that made the shape above
a ladder rather than an exception. Recorded here as policy rather
than as one issue's choice, so the third and fourth escalations are
decided against a rule instead of relitigating the first:

- **Three tiers, and what each may carry.** **Metadata** leaves with
  telemetry at all, is the prerequisite rather than a peer, and is
  never content. **Conversation content** leaves per class behind a
  flag of its own (`export_audio`, `export_transcripts`), each
  defaulting off and implied by nothing above it. **Wire fidelity**,
  the assembled prompt as a model received it and the per-request
  audio as a provider heard it, is deliberately unspecced: each is a
  decision of its own when something needs it. The tier table itself
  lives in
  [the observability map](../architecture/observability-surfaces.md#the-export-ladder),
  where this record keeps its tables.
- **Export follows retention.** What the local surface holds is what
  may leave, never more: the capture directory's files for the first
  escalation and the conversation store's rows for the second. A
  content export is therefore bounded by the switches that decided
  what to keep, and a deployment that stores no text exports none.
- **Erasure does not propagate, and every flag's prose says so.**
  What has left is the receiving deployment's, governed by its
  policy; deleting on this side reaches this side. That is the same
  answer the audio escalation gave and it is now the ladder's, so a
  future tier inherits the obligation to say it rather than
  rediscovering it.
- **Content escalations ride content taps, and the fold stays
  content-free.** A content flag reaches the local artifact (the
  capture's files, the store's rows) and never the emit-to-span fold,
  which continues to carry only what `events/catalog.py` declares. A
  fold-time content tap is rejected policy rather than a deferral. A
  transcript observation is a content tap's delivery vehicle, not the
  fold gaining content.
- **The promise side is rule 5 of the enumerated-baseline record.**
  [That record](2026-09-12-the-local-baseline-is-enumerated.md) says
  the boundary bounds defaults rather than capabilities, and that a
  deliberately enabled content export is lawful when it rides a
  content surface, declares its destination, defaults off and refuses
  under a local boundary. This ladder is the other half of that
  sentence: which channel content may ride and at what fidelity,
  which is this record's subject and not that one's.

In one sentence: content leaves by class, behind a flag of its own,
bounded by what was kept and never through the metadata fold.

### Amendment: the content classes are three under one prefix (2026-09-12)

#502 settles the third content class, and settling it shows that the
tier above it was cutting on the wrong axis. The ladder recorded
earlier the same day has three tiers, the third of them wire fidelity
and deliberately unspecced, and #496 and #501 were each about to add
an `attach_`-prefixed flag against it: one disclosure ladder with two
prefixes and four switches for two classes. Decided, so that the
escalations still to come are decided against a rule rather than
against each other:

- **Three content classes, under one `export_` prefix.**
  `export_audio` carries all recordings, `export_transcripts` the
  dialogue text, and `export_llm_input` the model's assembled
  request. The `attach_` prefix #496 and #501 proposed is
  decommissioned before it ever shipped: a ladder whose rungs are
  spelled two ways is a ladder an operator has to learn twice, and
  the rename that gave the first two classes one vocabulary would
  have bought nothing if the third arrived in the old one.
- **The family rule, recorded once, here.** Every content flag
  defaults off. Where its class has a local surface with a switch of
  its own, that switch being off makes the flag a no-op, said once at
  startup and never a refusal: a deployment that records no room and
  one that stores no text each have nothing to export, which is a
  choice rather than a misconfiguration. That arm is first, which is
  what the two landed builders do. Otherwise the flag requires
  `server.telemetry.enabled` and is refused under a
  `server.data_boundary` narrower than its reach. And it implies
  nothing about its siblings, in either direction. Once, because it
  is one rule three times over and a rule restated per flag is a rule
  that drifts between its restatements; each artifact issue then
  states only its own delta.
- **Artifacts ride their class.** #496's per-utterance clips and
  #501's per-turn reply audio are artifacts of `export_audio` rather
  than flags beside it: they are recordings, and recordings are what
  that switch already decides about. The consequence is written down
  rather than left to be discovered. A version that adds an artifact
  to a class widens what an already-on flag exports, so it is a
  changelog-announced event, stated in the flag's own documentation,
  and never a silent one.
- **A class may contain what a narrower one contains, and
  `export_llm_input` does.** An assembled request holds the dialogue
  as the model saw it, so that class is content-wise a superset of
  `export_transcripts`. The family rule that no flag implies another
  stays about the switches: turning the third on turns neither of
  the others on. What this record states plainly is what each class
  CONTAINS, because an operator reading only the switches would
  otherwise conclude that the third exports less than it does.
- **The third class is the request as vinga assembled it.** It
  contains the system prompt with its memory and know-how blocks,
  the message history as the model was given it, the tool schemas
  offered, the tool arguments the model asked for and the results it
  was handed back, and the tool choice. It does not contain vendor
  framing, generation parameters, the endpoint, any header, or any
  credential. That boundary rather than the bytes on the wire, for
  three reasons: it is the enumeration #502 itself settles, so it is
  that decision implemented rather than a narrowing of it; it is the
  one place where the request exists once rather than once per
  vendor, so the class does not quietly mean different things
  depending on which adapter a deployment runs; and a snapshot taken
  after adapter translation would be a content surface built out of
  an SDK's own call arguments, which is where credentials live, so
  the no-leak contract would then rest on an exclusion list per
  adapter, maintained forever, instead of on a seam that never sees
  one. What that costs is stated too: a parameter that changes a
  reply, a temperature or a token limit, is configuration rather
  than content and is not in this class.
- **Its local surface is the session's own working state, and its
  retention answer is exact.** The two classes above it each export
  from something durable, the capture directory's files and the
  conversation store's rows, so for them "export follows retention"
  reads off a store. This one has no store and vinga builds none: a
  session assembles a request because it is about to make it, and
  that assembly exists locally for as long as the session does. No
  second switch governs that surface, so the family rule's no-op arm
  does not arise for this class: there is no second switch that could
  be off, so the flag's only terms are the telemetry prerequisite and
  the boundary. The
  answer in its own terms is therefore "for the session, then in a
  bounded delivery job until it is delivered or dropped, and nowhere
  after that", which is stricter than either class above it. One
  consequence is recorded rather than left to be discovered: a
  process that dies with exports queued loses them, with no ledger
  to recover from, unlike the capture directory's files and the
  store's rows, which outlive the process that staged them. What
  that costs is bounded, and the bound is why the answer is
  acceptable: a lost export is a missing observation, never a lost
  conversation, because what was said is in the store.
- **The wire-fidelity tier dissolves, and the tiers are two.**
  Metadata is the prerequisite; content leaves by class. What that
  tier described turns out to be a fidelity property cutting ACROSS
  the classes rather than a rung above them: the per-request audio a
  provider heard is an `export_audio` artifact, and the assembled
  request is a class of its own. Keeping it as a third tier would
  have put #496's clips in two places on one ladder, which is two
  structures that must agree with a policy record playing one of the
  parts. The caution that tier carried survives as the superset note
  above. The tables move with the decision and stay in
  [the observability map](../architecture/observability-surfaces.md#the-export-ladder),
  which is where this record keeps its tables.
- **Fine-grained control remains #393's policy layer.** Per device
  and per person is a policy question with a vocabulary of its own,
  deliberately not a deployment boolean: a ladder that grew a switch
  per board would be a policy engine spelled in configuration keys,
  and an operator would then maintain one in each place.

In one sentence: content leaves by class under one `export_` prefix,
every class on the same four terms, and fidelity is what a class
contains rather than a rung above it.

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
