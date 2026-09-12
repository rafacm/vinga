# Telemetry overhaul: a three-class export ladder, complete and priceable traces

Plan for [issue #502](https://github.com/rafacm/vinga/issues/502).
Companion implementation doc:
`2026-09-12-telemetry-overhaul-implementation.md`, one section per
milestone, appended in the same change that ticks the milestone
checklist.

## Goal

After #66, #67 and #495 a trace backend shows a vinga session as
grouped per-turn traces with stage timings and token counts, the
session's recording under one flag and its turns under another. The
2026-09-12 live trace review against Langfuse project `vinga-cloudlab`
(every finding verified against traces from revision `9251c18`) found
three gaps and one naming decision waiting to be taken:

- **The configuration story was about to fork.** #496 and #501 each
  proposed an `attach_`-prefixed flag of its own, which would have
  given one disclosure ladder two prefixes and four switches for two
  content classes.
- **The traces are incomplete in ways the domain vocabulary already
  answers.** A board's name never reaches a span, MCP tool calls are
  invisible because the backend ingests no span events, the prompt's
  provenance by block never leaves the log, and the after-close spans
  carry three attributes under bare names that belong to nothing.
- **Two of the three stages cannot be priced.** Only `llm` carries
  usage the backend can cost, so the per-session cost of a
  conversation is the generation half of it and nothing else (about
  1.40 over the review's thirty-day window, with ASR and TTS reading
  zero because they report no usage at all rather than because they
  are free).
- **The third content class had no name and no home.** "What the model
  actually saw" was the ladder's unspecced wire-fidelity tier, and
  both #496's audio clips and a future prompt export were being
  designed against it separately.

This plan settles the ladder as policy (M1), completes the trace
metadata (M2), makes all three stages priceable (M3), builds the
post-close infrastructure two later issues both need (M4), and lands
the third content class (M5).

Local baseline: not applicable. No conversational capability changes.
M5 adds a content-export feature, lawful under rule 5 of
[the enumerated-baseline record](../adr/2026-09-12-the-local-baseline-is-enumerated.md)
exactly because it declares its destination, defaults off and refuses
under a boundary narrower than its reach; M4b widens where "its reach"
may point without touching what the boundary means. The enumerated
list does not move.

## The issue's decisions, restated

These are settled on #502 and in the decisions appended to it on
2026-09-12. They are restated so the milestones can be read against
them, and they are not re-litigated here.

- **Three content classes, one `export_` prefix.** `export_audio`
  (all recordings), `export_transcripts` (dialogue text),
  `export_llm_input` (the model's assembled request). The `attach_`
  prefix proposed by #496 and #501 is decommissioned before it ever
  shipped.
- **Artifacts ride their class.** #496's per-utterance clips and
  #501's per-turn reply audio are artifacts of `export_audio`, not
  flags beside it. A version that adds an artifact to a class widens
  what an already-on flag exports, and that is a changelog-announced
  event stated in the flag's own documentation.
- **The family rule is recorded once, in the ADR.** Every content flag
  defaults off, requires `server.telemetry.enabled`, is refused under
  a `server.data_boundary` narrower than its reach, and implies
  nothing about its siblings. Each artifact issue then states only its
  delta.
- **`export_llm_input` is content-wise a superset of
  `export_transcripts`**, because an assembled request contains the
  dialogue as the model saw it. The ADR says so plainly; the family
  rule that no flag implies another stays about the switches.
- **M3 prices what is known and calculates nothing.** Spans carry raw
  usage units; backend model definitions are entered only where a real
  list price exists. A stage without a real rate shows usage and no
  cost.
- **M5 exports exactly what the model saw**, tool arguments and
  results included. The #495 transcript exclusion of tool invocations
  stands for transcripts; this class is the assembled request, which is
  its whole point. What "exactly" bounds is settled under "the fidelity
  boundary" below: the request as vinga assembled it, which is the
  enumeration the issue itself gives (system prompt, memory, tool
  schemas, message history).
- **Fine-grained control is #393's policy layer**, deliberately not
  deployment booleans.
- **The sequence overrides the previously agreed queue** (#487 M1 then
  #484): M1, M2, M3, then #500, then M4, then #496, then #501, then
  M5. #500, #496 and #501 are their own issues with their own plans;
  this plan owns the five milestones only, and says where each of the
  three lands between them.

## Premises checked before planning

Three of the issue's own statements were checked against the merged
code before any milestone was scoped. Two were exact; one was not, and
the correction changes what M3 contains.

**`heard.duration_s` exists. TTS characters do not.** The issue says
M3's two facts are "both facts the catalog already measures:
`characters` on the spoken events, `duration_s` on `heard`". The
second is true (`catalog.py` `Heard.duration_s`, a `Real`). The first
is not: the only `characters` fields in the catalog are on
`prompt_assembled` and on the three `sentence_withheld` variants.
`sentence_synthesized` carries `index`, `stream_ms`, `first_chunk_ms`
and the provider quartet, and no size at all. So M3 is not purely an
exporter change: it adds one declared `Count` field to
`SentenceSynthesized` and passes the sentence's length at the emit
site (`pipeline.py` `_speak_after` already holds the sentence;
`_sentence_synthesized` does not receive it). The field is
content-free by construction, being a count, and goes through the
catalog's own declaration machinery like any other.

**The after-close spans' bare names come from a shared helper.**
`_after_the_close` builds its attributes with `_event_attributes`,
which is also what every span EVENT uses, and which deliberately keeps
the catalog's own field names. So the `vinga.` respelling M2 asks for
cannot be a catalog change and cannot be a change to that helper
without renaming every span event's attributes at the same time. It is
a table of its own for the after-close path, in the shape of the
tables that already exist (`SESSION_ATTRIBUTES` and its siblings).

**`prompt_assembled` is emitted once per agent, not once per turn,
and the first one is emitted before the session span exists.** Its
docstring says "assembled and cached", and it is emitted where the
know-how half is built rather than per round. So an attribute written
only onto the turn span that happens to be open when the event arrives
would appear on one turn per agent per session and be absent from
every later turn, which is not the token-provenance question anyone
wants answered. M2 retains the sources per agent in the session's
trace state and stamps them on every turn span that agent speaks,
which is exactly the mechanism `_provider_context` already uses for
the provider quartet.

The ordering is worse than that, which the plan review found and the
code confirms. `PipelineRuntime.__init__` calls
`_activate_agent(self._agents[0])`, which emits `prompt_assembled` for
the initial agent, and `DeviceSession.run` constructs the runtime
before the hello exchange and well before it emits `session_open`.
`_span_event` returns without writing when `self._sessions` has no
entry for a session, so today the initial agent's `prompt_assembled`
reaches no trace at all: not as an attribute, not even as the span
event it is supposed to be. That is an existing gap this milestone
closes rather than a new problem it creates, and the ordinary case is
the one it affects, since most sessions have exactly one agent.

So the fold holds what it cannot yet place. A `prompt_assembled` whose
session has no span is kept in a bounded pending map, oldest evicted
first, exactly as `capture_started` already is and for the same reason
(a held event whose session never opens is a refused session, and the
hold is a buffer rather than a record); `_open_session` claims what is
waiting for it and folds it into the retained per-agent sources before
the session span is even handed back. The constant is
`PENDING_PROMPTS`, a sibling of `PENDING_CAPTURES` rather than a reuse
of it, because the two holds are cleared by different events and a
shared bound would make one starve the other. Moving the emission
after `session_open` was the alternative and is rejected: the event's
position in the log is a fact about when the prompt was assembled, and
the exporter is the surface with the ordering problem.

## Open questions, resolved

### The wire-fidelity tier dissolves into the classes

The ladder recorded on 2026-09-12 has three TIERS: metadata,
conversation content, and wire fidelity ("the assembled prompt as a
model received it and the per-request audio as a provider heard it,
deliberately unspecced"). The ladder this issue settles has three
CONTENT CLASSES. They are not the same three, and M1 has to say which
survives.

The tiers stay two, and wire fidelity stops being a tier. Metadata is
the prerequisite; content leaves by class. What was the wire-fidelity
tier turns out to be a fidelity property that cuts ACROSS the classes
rather than a rung above them: the per-request audio a provider heard
is an `export_audio` artifact (#496) and the assembled request is its
own class (`export_llm_input`, M5). Keeping it as a third tier would
mean #496's clips sat in two places on the same ladder, which is the
"two structures that must agree" trap with a policy record playing one
of the parts.

What the amendment keeps from that tier is its caution, restated as
the class-difference note: a higher-fidelity class may contain what a
lower one contains, and `export_llm_input` does contain the dialogue.

### The third class's local surface is the session's own working state

"Export follows retention: what the local surface holds is what may
leave, never more" is the ladder's second clause, and `export_audio`
and `export_transcripts` each answer it by naming a local store (the
capture directory, the conversation store). `export_llm_input` has no
store behind it and this plan does not build one: the conversation
record holds turns, not assembled requests, and a schema that held
every request a session made would be a retention decision nobody has
taken.

The answer is that the session's own working state is the local
surface. A session assembles the request because it is about to make
it; that assembly exists locally for as long as the session does, it
is exported once at the close, and nothing retains it afterwards. So
the clause holds in its own terms (what leaves is what was held) and
the retention question is answered by "for the session, and then
nowhere", which is stricter than either class above it. M1 records
this, because M1 gates M5 and a class whose retention answer is
invented in its implementation milestone is the thing the ADR exists
to prevent.

### A TOOL span replaces the `tool_call` span event, it does not join it

#67's first walkthrough established that Langfuse ingests no span
events at all, which is why `_after_the_close` chose a span. The same
finding is what makes MCP calls invisible today. M2 folds `tool_call`
into a child span of the turn span, built retrospectively from
`duration_ms` the way every stage span is built (`_before`).

The span event goes away for this event rather than staying beside the
span. Two carriers of one fact on one trace is the locality rule
broken in the one module that has been most careful about it, a
backend that DOES ingest span events would show each call twice, and
the span carries strictly more (it has an extent). The three variants
stay one fold: `tool_call` is one declared event name, and
`_attributes` already skips a table key the payload does not carry, so
one table serves `tool` (builtin), `entry` (MCP) and neither
(unnamed).

Whether the backend renders it as a TOOL observation rather than a
plain span is a question about the backend, not about vinga, and it is
answered by the M2 live gate rather than guessed here. The plan's
position is to spell the fact in the conventions' own vocabulary
first: `gen_ai.operation.name` = `execute_tool` is the GenAI
conventions' name for exactly this, so it goes on the span and the
gate records what the backend does with it. If the gate shows the
backend needs its own directive, `langfuse.observation.type` is added
beside it and the implementation doc records the finding, in the shape
of the `session.id` alias: one fact, a second spelling for one reader,
recorded as such.

### `prompt_assembled.sources` lands flattened, not as a blob

`PromptSources` is a mapping of provenance token to character count,
and span attributes take primitives or homogeneous primitive arrays
and never mappings. Both existing answers to that are in the module:
`_provider_attributes` flattens into one attribute per fact, and
`TRANSCRIPT_LEGS` encodes canonical JSON into one string.

Flattening wins here for the reason the provider context gives in its
own comment: a JSON blob is present and unqueryable, which is the same
as absent for the question the attribute exists to answer. The
question here is "how much of this prompt came from where", which is a
number per block that a reader charts. The key space is bounded by the
operator's own configuration rather than by anything a far side sends
(the five declared provenance forms, with configured names inside
three of them), so the attribute-key cardinality is bounded by the
same thing that bounds the provider keys.

The spelling is `vinga.prompt.sources.<token>` with the token's `:`
separators written as `.`, so `instructions:house` becomes
`vinga.prompt.sources.instructions.house`. `prompt_assembled.characters`
goes on beside them as `vinga.prompt.characters`: it is the total the
blocks sum to, it is one line, and without it the parts have no
denominator. That is one attribute past the issue's letter and it is
named here so the review can reject it.

### The usage attributes are `gen_ai.usage.*` with vinga's own units

The GenAI conventions name token counts and nothing else, so there is
no convention-blessed spelling for "characters synthesized" or
"seconds of audio transcribed". Calling either one tokens would be
false in the way this module refuses to be false elsewhere
(`stream_ms` is not named synthesis latency because it is not).

M3 writes `gen_ai.usage.output_characters` on the TTS span and
`gen_ai.usage.input_seconds` on the ASR span: the conventions'
namespace and direction words, with the unit stated in the name rather
than implied. The input/output halves are read the way the conventions
read them, from the model's point of view: a voice is given text and
produces audio, so its billable text is output; an ear is given audio,
so its audio is input.

Whether the backend lifts an unrecognized `gen_ai.usage.*` key into
its own usage details is a fact about the backend and is the M3 live
gate's first question. The #67 walkthrough recorded that
`gen_ai.usage.input_tokens` and `output_tokens` arrive parsed into
`usageDetails`; nothing recorded says what happens to a key outside
that pair. If they are dropped, the fallback is the backend's own
`langfuse.observation.usage_details` attribute carrying canonical JSON,
which is the same shape of second spelling for one reader that
`session.id` already is, added beside the conventions' name and never
instead of it. The gate decides, and the implementation doc records
the answer with the observation JSON that shows it.

### "A real list price" admits a unit conversion and nothing else

The decision says model definitions are entered only where a real list
price exists, and never an estimated or plan-dependent rate. Two
boundary cases come up immediately and are decided here:

- **A published per-minute price entered as a per-second price is
  admissible.** It is the same number in the unit the span reports,
  exact and reversible, with the published figure quoted beside it in
  the implementation doc. Nothing is estimated: 0.006 per minute is
  0.0001 per second.
- **A model billed in units vinga does not observe gets no price.**
  A speech model priced per audio token, when what the span carries is
  seconds, would need a tokens-per-second assumption, which is exactly
  the estimate the decision refuses. That stage shows usage and no
  cost, and the implementation doc says which models are in that
  position and why.

Credit-based and plan-dependent vendors (ElevenLabs' credits) get no
price for the same reason. Local engines (Piper, faster-whisper) get
none because there is no list price to enter, which is a true answer
rather than a gap.

### M4 ships as two pull requests

The issue's M4 is three things: bounded turn-trace-id retention, the
capture-job context pinning named as a follow-up in #495's plan, and
the operator reach assertion named as a follow-up in #493's
implementation doc. The first two are one mechanism and its second
caller, content-free and internal. The third is a new declaration
surface with its own territory: where the key lives, whether it is one
key or three, and what an assertion means when the trace transport and
the media transport point at different deployments. #493's own
implementation doc says so in those words.

So M4 delivers as M4a (retention and pinning) and M4b (the reach
assertion), each its own branch, PR and review round, and the issue's
M4 box is ticked when both have merged. Mixing them would put a boot
refusal's semantics in the same diff as a retention bound, which is
the "behavior changes sit alone in review" rule broken for the
convenience of a checklist.

### "Every span" is an enumeration, and the name rides the pinned context

`vinga.device.name` on every span is not one table entry. Spans are
built in more places than the attribute tables reach, and the ones
outside them are exactly the ones a reader of a closed session's trace
looks at. The enumeration, which the milestone owns and the tests
assert one by one:

| Constructor | How it gets the name today |
| --- | --- |
| `_open_session` | `SESSION_ATTRIBUTES` |
| `_open_turn` and the stage spans | the retained identity (`CONTEXT_ATTRIBUTES`) |
| the tool span M2 adds | the retained identity |
| `reference_media` | nothing: it builds its attributes by hand |
| `_after_the_close` | nothing: `_event_attributes` off the payload |
| `_transcript_spans` | nothing: it builds its attributes by hand |

So the name joins the retained identity rather than any one table, and
the post-close writers read it from the pinned context they already
hold. That is the locality answer as well as the correctness one: a
post-close writer that went back to the configuration for a board's
name would be reading a value that may have been renamed since the
session ran, and the store's own session row deliberately keeps the
name as it was written.

Two details the tests pin. The name is the bounded copy the
`session_open` payload carries, so nothing unsanitized reaches a span
by this route. And a board nobody has named contributes NO attribute
rather than a null one, which is the rule `_attributes` already keeps
for an absent value and the difference between "this board has no name"
and "this span forgot to say".

### The post-close seam is addressed by a pinned context, not by a session

The pinning M4a promises cannot be a field added to a capture job. The
capture uploader does not carry a context at all: it looks its session
up twice on its own worker, `trace_of(job.session)` before the upload
and `reference_media(job.session, ...)` after it, and both lookups
consult the retention at the moment they run. Pinning a context into
the job would leave both windows exactly where they are.

So the addressing changes rather than the job. `retained_context` stays
the one admission-time pin, and the two operations take the pinned
handle instead of a session id: `trace_of(context)` answers the spelled
trace id and `reference_media(context, references)` writes the media
span. The session-keyed spelling of both goes away rather than staying
beside them, which is what makes this a deepening: after M4a there is
one way to address a trace after its session closed, and a caller that
did not pin at admission cannot accidentally get an answer that depends
on when it asked. Both have exactly one production caller today
(`capture_upload.py`) plus one test double, so the change is a
signature and its two call sites rather than a migration.

The eviction windows are then tested where they actually are: a job
admitted before sixty-four later sessions open still resolves its trace
id, and a job whose upload completes after that pressure still writes
its reference. Two cases, because they are two windows, and both fail
against today's code.

### A turn's context is pinned with its session's, under a per-session cap

#496 and #501 both need the trace a TURN was exported under, and a turn
trace is a root trace of its own linked to the session, so the session's
retained context does not address it. The contract:

- **What identifies it.** The turn's session-local ordinal, which is
  what the turn span already carries as `vinga.turn.index` and what
  both later issues have in hand when they stage an artifact. Not a
  span object: what crosses stays opaque, as it does today.
- **When it is captured.** At the turn's open, the same instant the
  session's own context is captured at `_open_session`. Not at the
  close, because a turn that a barge-in or a failure ended early still
  ran an ASR stage whose clip #496 wants.
- **Who pins it.** Nobody pins a turn context separately. A session's
  turn contexts live in that session's retained entry, and
  `retained_context(session)` hands the whole bundle over at admission,
  so one pin at the close carries the session and every turn under it.
  That is what makes the retention question answerable at all: a
  turn-keyed map of its own would need its own eviction policy and
  would age out under exactly the pressure the session pin was built to
  survive.
- **The bound.** `RETAINED_TURNS` per session, oldest dropped first,
  which is a per-session cap and NOT derived from `max_sessions`: the
  configured capacity bounds concurrent sessions and says nothing about
  how many turns one of them takes, and the review is right that a
  single long session would otherwise grow without limit. Total
  exposure is therefore the session bound times this one, and the
  retained object is two identifiers rather than a span, so the cap can
  be generous without being unbounded.
- **What a session past the cap does.** Its oldest turns lose their
  target, and the issue that wanted one says so with the closed reason
  it already has for a missing trace (`no_trace`), per artifact. An
  artifact with no target is reported, never attached to the session
  trace as a consolation: a clip filed under the wrong observation is
  worse than a clip that says it could not be filed.

### M4b is one key on the telemetry section, asserting every destination

The three questions #493's implementation doc left open are answered
here rather than in the milestone, because they are the milestone.

**One key, on the section that owns the exports.**
`server.telemetry.reach`, taking the `Reach` vocabulary the MCP entries
already declare in (`host`, `network`, `internet`), absent by default.
Not three keys: a reach is a property of where a transport points, and
splitting it per content class would let an operator assert something
about audio that is untrue of transcripts riding the same endpoint.

**Absent means `internet`, which is exactly today's behavior.** The
three call sites pass a fixed `Reach.INTERNET` now, so a deployment
that upgrades into this key and does not set it is refused and admitted
in precisely the cases it was before. The key widens; it never narrows
by default.

**One assertion covers every destination the section sends to**, and
the semantics are the outermost of them, which is the same shape
`server.data_boundary` itself has. Two transports exist: the OTLP
endpoint that traces and transcripts ride, and the Langfuse REST host
the capture upload uses. An operator whose collector is on the LAN and
whose media host is a vendor has asserted `internet`, because that is
the outermost reach of what this section sends, and the refusal then
applies to all three features rather than to the one that would have
been caught. That is the honest direction to round in: an assertion
that admitted the LAN case while audio left for a vendor would be the
boundary broken by a key meant to describe it.

**It is an assertion, not a proof**, and it is documented in those
words beside the key, the way the promises page already says of the
whole mechanism (it "admits declarations, not behavior"). An operator
who points `OTEL_EXPORTER_OTLP_ENDPOINT` at a vendor after declaring
`network` has lied to their own configuration, and vinga cannot tell.

**Refusal ordering is unchanged and the sentence gains one fact.**
Each builder still calls `check_feature` before it constructs anything,
in the order it does today; what changes is the second argument, from
the fixed `Reach.INTERNET` to the section's declared reach. The
existing sentence names the switch, the reach and the boundary and
carries no endpoint; it keeps all of that and names
`server.telemetry.reach` as the declaration the reach came from, so an
operator reading a refusal can see which of their own statements
produced it. No endpoint, no host and no credential is rendered, which
is the rule this sentence already keeps.

### The staged LLM input is bounded per session, oldest dropped first

A session's rounds are not bounded by anything the server controls
(a long conversation with a talkative tool loop makes many), and each
staged request is the whole assembled prompt, so an unbounded stage is
a slow leak in the object a session holds for its life. The bound is a
round cap per session with the oldest dropped first, which is the
posture `PENDING_CAPTURES` and `RETAINED_TRACES` already take here and
for the same reason. The export's own event carries how many rounds
went and how many were dropped, so a reader with a truncated export
learns that it is truncated from the trace rather than by counting.

Per-turn delivery (export each round as its turn ends, bounding the
stage to one turn) was considered and is rejected: the issue settles
delivery as post-close on the #495 bounded seam, and a per-turn
delivery would put an export on the audio path's own worker cadence,
which is the thing every content escalation here has been careful to
stay off.

### The fidelity boundary is the request vinga assembled

`LlmProvider.stream(system, turns, tools, tool_choice)` is a neutral
seam: each adapter then translates those four values into its vendor's
own message and tool shapes and adds what the vendor needs beside them
(the model, the limits, the stream options, whatever passthrough the
entry configured). So a request staged at that seam is one translation
short of the bytes on the wire, and this plan's first draft called it
byte-faithful, which it is not.

The class is the request as vinga assembled it, and the plan, the ADR
and the flag's own prose say that in those words. Concretely it
contains the system prompt with its memory and know-how blocks, the
message history as the model was given it, the tool schemas offered,
the tool arguments the model asked for and the results it was handed
back, and the tool choice. It does not contain vendor framing, the
generation parameters, the endpoint, any header, or any credential.

That boundary is chosen rather than conceded, for three reasons. It is
the enumeration the issue itself gives for this class (system prompt,
memory, tool schemas, message history), so it is the settled decision
implemented precisely rather than narrowed. It is the one place where
the request exists once rather than once per vendor, so the class does
not silently mean different things depending on which adapter a
deployment runs. And a snapshot taken after adapter translation would
be a content surface built out of an SDK's own call arguments, which is
where credentials live: the no-leak contract would then depend on an
exclusion list per adapter, maintained forever, instead of on a seam
that never sees one.

What it costs is stated rather than hidden: a model parameter that
changes a reply (a temperature, a token limit) is not in this class.
Those are configuration rather than content, the generation span
already carries the model identity as `gen_ai.request.model`, and an
issue that needs the vendor's own body is a decision of its own with
its own credential review.

### The M5 module is its own, and the seam is one more bounded call

`transcript_export.py` reads the conversation store post hoc. The LLM
input has no store to read, so M5's module owns a live stage as well
as a post-close delivery, which is a different responsibility on a
different clock. It is `llm_input_export.py` beside it rather than a
second half of the transcript exporter.

Its depth sentence: a caller that holds one of these stops having to
know that an assembled request is bounded, that it is held per session
and dropped at the close whatever happened, that content never reaches
the emit fold, and how a bounded OTLP delivery reports its own
failure; it hands over what it is about to send a model, and asks
nothing else.

The `Telemetry` seam gains one method, `export_llm_input`, in the
shape `export_transcript` already has: a private tracer, spans
collected in memory, one bounded delivery call, a `Delivery` answer.
The seam type is a new frozen dataclass (`LlmInputRound`) alongside
`TranscriptTurn`, for the same reason that one exists: what crosses is
a stated type, not a store row and not a provider object.

## Module layout and design footprint

| Milestone | Deepens | Adds | What a caller stops having to know |
| --- | --- | --- | --- |
| M1 | the content-and-telemetry record, the observability map | nothing | (documentation) |
| M2 | `telemetry.py` (four tables, one fold, one retained fact) | nothing | that a tool call, a board's name and a prompt's provenance reach a trace at all |
| M3 | `events/catalog.py`, `events/assembly.py`, `runtime/pipeline.py`, `telemetry.py` | nothing | that a voice and an ear report usage the way a generator does |
| M4a | `telemetry.py` (retention generalized), `capture_upload.py` | nothing | that a post-close job's trace context can age out under it |
| M4b | `config/models.py`, `boundary.py`'s callers | nothing | that a collector on the LAN is reachable without declaring the internet |
| M5 | `telemetry.py` (one method, one seam type), composition | `llm_input_export.py` | the sentence in "The M5 module is its own" above |

No milestone adds a layer that forwards its arguments, and no
milestone's only description of itself is "beside an existing module".
M2, M3 and M4a are deepenings by construction: they add facts and a
fold to the module that already owns the fold, and the alternative
(a second exporter that knows the same vocabulary) is the parallel
vocabulary #66 was explicitly built to avoid.

## The live gates

Every milestone that changes what a trace carries is verified against
a real backend before its PR is opened, not only against unit
assertions about attribute dictionaries. The rig is the same each
time and is recorded once here:

- A server run locally from the milestone's worktree against the
  development Postgres, on a configuration with real providers
  (`openai` ASR, `openai_llm`, `openai_tts`) and
  `server.telemetry.enabled` plus whichever export flags the gate
  needs, with `OTEL_EXPORTER_OTLP_*` pointed at the Langfuse project
  `vinga-cloudlab` (EU cloud) and `LANGFUSE_*` in the environment.
  Credentials come from the shell environment and never from a
  configuration file, which is what the telemetry surface's own rules
  already require.
- One conversation held through the xiaozhi-sdk device simulator, the
  same simulator the integration and smoke lanes drive.
- The resulting observations read back through the Langfuse MCP
  (`listObservations`, `getObservation`, `queryMetrics`), and the
  answers quoted into the implementation doc as JSON rather than
  paraphrased.

Per milestone the gate asks:

- **M2**: does a turn trace carry `vinga.device.name`; does a tool
  call appear as an observation at all, and under which type; do the
  flattened prompt sources arrive as metadata on every turn of an
  agent; do the after-close spans carry the `vinga.`-prefixed names.
- **M3**: does an unrecognized `gen_ai.usage.*` key reach
  `usageDetails`; do the ASR and TTS observations arrive as
  `GENERATION`; does a model definition entered through `createModel`
  price them; and the issue's stated acceptance, that the per-session
  per-stage cost query returns nonzero rows for `asr`, `llm` and
  `tts_stream`.
- **M4a**: nothing to see in a backend beyond a capture still
  attaching; the gate is the unit and integration pressure cases, and
  the live run is a regression check that #67's attachment still
  works.
- **M4b**: a server bounded at `network` with an asserted LAN reach
  boots and exports; the same server without the assertion still
  refuses. Run against a local collector rather than the cloud, since
  that is the case the key exists for.
- **M5**: does an assembled request arrive rendered as an
  observation's input, with tool arguments and results present, on the
  trace the session was exported under.

Unverifiable steps are stated as unverified. A gate that cannot run
(no collector, a backend outage) leaves its PR box unchecked with the
reason, and does not become a claim.

## Tests

Existing assets are reused rather than restated: the telemetry unit
suite's fake tracer and emission drivers, the events package's
catalog-drift and rendering pins, the capture-upload and
transcript-export suites' worker and drain harnesses, the integration
lane's simulator conversations, and the sentinel pattern for planted
credential-shaped values.

What is new per milestone:

- **M2**: one case per new attribute asserting the exact name and
  value on the exact span; a case that a second turn by the same agent
  still carries the retained prompt sources; a case driving the
  PRODUCTION ordering, a `prompt_assembled` emitted before
  `session_open` and claimed by it, which fails against today's code
  because the event is dropped; a case that the pending hold evicts
  oldest-first and that a session that never opens leaves nothing
  behind; a case that a `tool_call`
  produces a span and NO span event; a case that an unnamed call
  carries neither `tool` nor `entry`; a case pinning the after-close
  attribute names, written to fail against the bare names; one case per
  span constructor in the enumeration asserting the device name, plus
  the unnamed-board case asserting the attribute is absent rather than
  null.
- **M3**: a catalog-drift case for the new `characters` field and its
  rendering; an emit-site case that the character count is the
  sentence's own length; usage attribute cases on both spans; a case
  that an absent measurement contributes no attribute rather than a
  zero.
- **M4a**: the two eviction windows as two cases, a job admitted
  before sixty-four later sessions open still resolving its trace id
  and a job whose upload completes after that pressure still writing
  its reference, both of which fail against today's code; a
  many-turns-in-one-session case driving past `RETAINED_TURNS` and
  asserting that the oldest turn reports no trace while the newest
  still resolves; and a case that a turn context is captured at the
  turn's open rather than its close, driven by a turn a barge-in ended.
- **M4b**: refusal and admission cases per feature at each reach, the
  absent-key case pinning that today's behavior is unchanged (which is
  the upgrade proof), a case that one asserted reach governs all three
  features rather than the one it was written for, and a sentinel case
  that no refusal sentence renders an endpoint, a host or a credential
  however the environment is set.
- **M5**: the sentinel suite over the staged content (a planted
  credential-shaped value in a tool result must reach the export and
  must NOT reach any log, event or span outside it, which is the
  inverse assertion from the usual one and is stated as such); the
  bound's drop accounting; the drain and shutdown cases in the shape
  `transcript_export.py`'s already take; a case that the flag off
  stages nothing at all rather than staging and discarding.

Every new claim is written to fail first and watched failing, and the
commit body says the check was done. Where a proof is about ordering
under concurrency it is run repeatedly and the count stated; where it
is straight-line logic one run is the honest proof and more is noise.

## Risks

- **The backend's usage mapping may not admit vinga's units** (M3).
  Mitigated by the gate asking before the exporter is built around the
  answer, and by the recorded fallback.
- **A tool span's retrospective construction can misplace a call in
  time** if `duration_ms` and the emission's stamp disagree. Mitigated
  by using the same `_before` helper every stage span already uses, so
  the failure mode is the known one rather than a new one.
- **M5 holds content in memory for a session's life.** Mitigated by
  the bound, by the flag defaulting off (nothing is staged when it is
  off), and by the sentinel suite pinning that the content reaches
  exactly one surface.
- **M4b's key is a new declaration surface** and could grow into a
  second boundary system. Mitigated by keeping it an assertion that
  narrows `check_feature`'s existing argument rather than a new rule,
  and by the plan review being asked about it specifically.
- **The sequence interleaves three other issues.** Mitigated by
  keeping each milestone's branch stacked on the previous milestone's
  rather than on an interleaved issue's, and by rebasing onto `main`
  after each merge.

## Documentation footprint

- **M1**: `docs/adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md`
  (a fourth amendment), `docs/architecture/observability-surfaces.md`
  (the export-ladder section: the tier table becomes two tiers and a
  class table, and the class-widening rule lands beside it). No
  changelog fragment: nothing an operator can observe changes.
- **M2**: `docs/reference/events.md` only if the catalog moves (it
  does not in M2); the observability map's exported-traces row gains
  the tool span in its description of what the surface holds.
  Fragment `changelog.d/502-trace-completeness.md` (### Added).
- **M3**: `docs/reference/events.md` through its generator (the new
  field), the observability map's row, and the implementation doc's
  price table. Fragment `changelog.d/502-usage-accounting.md`
  (### Added).
- **M4a**: none beyond the implementation doc; the mechanism is
  internal. No fragment: nothing observable changes.
- **M4b**: `docs/reference/server-config.md` through its generator,
  both example configs, the observability map's retention-and-access
  columns for the three exporting surfaces, and
  `vinga-server/README.md` where the boundary's refusals are
  described. Fragment `changelog.d/502-collector-reach.md`
  (### Added).
- **M5**: `docs/reference/server-config.md` through its generator,
  both example configs, the observability map (a ninth surface row and
  the class table), the ADR's class note cited rather than restated.
  Fragment `changelog.d/502-export-llm-input.md` (### Added).

Every milestone that edits, moves or adds a document runs
`tests/unit/test_command_spellings.py` before its PR and regenerates
the manifest with its own generator when stale.

## Milestones

- [ ] **M1: the ADR amendment**. The fourth amendment to the
  content-and-telemetry record: three content classes under one
  `export_` prefix, the family rule stated once, artifacts riding
  their class, class widening as a changelog-announced event, the
  superset note about `export_llm_input`, the third class's local
  surface and its retention answer, and the wire-fidelity tier
  dissolved with its caution kept. The observability map's
  export-ladder section rewritten to match, since that is where this
  record keeps its tables. Documentation only. Design footprint: no
  module moves. Documentation footprint as listed above.
- [ ] **M2: trace completeness**. `vinga.device.name` on every span in
  the enumeration above, carried by the retained identity and read from
  the pinned context by the three post-close writers that build their
  attributes by hand; a `tool_call` fold building a
  child span of the turn span with `gen_ai.operation.name`, replacing
  the span event; prompt sources retained per agent and stamped
  flattened on every turn span with the total beside them; an
  after-close attribute table giving `elapsed_ms`, `audio_bytes` and
  `manifest_bytes` their `vinga.` names. Live gate recorded. Design
  footprint: four tables and one fold on the module that owns folds,
  one retained fact beside the provider context.
- [ ] **M3: cost accounting**. `characters` declared on
  `SentenceSynthesized` and passed at the emit site;
  `gen_ai.usage.output_characters` on the TTS span and
  `gen_ai.usage.input_seconds` on the ASR span; Langfuse model
  definitions entered through the MCP for every model with a real list
  price, with the prices and their sources quoted in the
  implementation doc and the priceless ones named. Acceptance: the
  per-session per-stage cost query returns nonzero rows for `asr`,
  `llm` and `tts_stream`. Design footprint: one declared field through
  the catalog's own machinery, two table entries.
- [ ] **M4a: post-close retention and pinning**. Turn-level trace
  context captured at each turn's open into its session's retained
  entry, under the per-session `RETAINED_TURNS` cap settled above;
  `trace_of` and `reference_media` re-addressed from a session id to
  the pinned context, their session-keyed spellings removed, and the
  capture uploader pinning at admission the way the transcript exporter
  does, which closes the exposure #495's plan named and declined.
  Design footprint: the retention deepened in place and one addressing
  mode instead of two, with the two call sites the change reaches.
- [ ] **M4b: the operator's collector reach**. The reach assertion
  #493's implementation doc named, in the shape settled under "M4b is
  one key on the telemetry section": `server.telemetry.reach` in the
  `Reach` vocabulary, absent meaning `internet` so an upgrade changes
  nothing, one assertion covering every destination the section sends
  to and meaning the outermost of them, `check_feature` taking it
  instead of a fixed `Reach.INTERNET` at its three call sites, and the
  refusal sentence naming the declaration without naming an endpoint.
  Design footprint: one field and an argument at three existing call
  sites, no new rule.
- [ ] **M5: `export_llm_input`**. The third class: the flag with its
  prose and refusal order, `llm_input_export.py` staging the assembled
  request per round under a stated bound, `Telemetry.export_llm_input`
  and `LlmInputRound` on the #495 bounded seam, delivery post-close as
  an observation rendered through `langfuse.observation.input`, two
  outcome events with a closed reason set, the sentinel suite, and the
  observability map's ninth surface. Design footprint: the new module
  with its depth sentence, one method and one seam type on
  `Telemetry`.

The issue's own M4 box is ticked when M4a and M4b have both merged.
#500 lands between M3 and M4a, #496 between M4b and M5, and #501
between #496 and M5, each under its own plan.

## Plan review round

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-12, runtime 6m02s, reviewing commit 58ddecef.
Verdict as received: **not ready** (the M5 fidelity seam, the initial
provenance ordering and the M4b configuration contract each need a
decision before implementation; the P2 amendments make the milestones
testable and operationally honest).

A note on the round itself, because it cost two runs. The first two
attempts at this review exhausted their context reading the four large
files the prompt named and produced no findings at all, exiting 0 with
an empty answer. The round below ran against a prompt that pastes the
load-bearing excerpts inline and tells the reviewer to consult the
large files only through `grep` and a narrow window. An empty review is
not a clean review, and a reviewer that exits 0 with nothing to say has
not said nothing.

Findings condensed but faithful; resolutions appended per amendment.

1. **P1: M5 cannot provide wire-faithful requests at the proposed
   seam.** The plan calls the export "exactly what the model saw" and
   "byte-faithful" while staging what the caller passes to
   `LlmProvider.stream`, which is neutral `system`, `Turn`, `ToolDef`
   and `tool_choice` values. Both adapters then translate those into
   different message and tool structures and add model, limits, stream
   options and passthrough fields, so an `LlmInputRound` is not the
   request the provider sent. Define the fidelity boundary precisely:
   either drop the wire-fidelity language, or add a provider-side
   snapshot after adapter translation, stating which transport fields
   (authorization headers above all) are excluded and testing each
   adapter's snapshot against the real SDK arguments.

   *Resolution.* Adopted, first branch. The wire-fidelity language is
   gone and a new section, "the fidelity boundary is the request vinga
   assembled", states exactly what the class contains and what it does
   not, why that boundary is the issue's own enumeration rather than a
   narrowing of it, and what it costs. The provider-side snapshot is
   rejected with a reason the review's own evidence supplies: a content
   surface built from an SDK's call arguments puts the no-leak contract
   behind a per-adapter exclusion list, and the seam that never sees a
   credential is the one to build on.

2. **P1: initial prompt provenance is emitted before a telemetry
   session exists.** `PipelineRuntime.__init__` calls `_activate_agent`,
   which emits `prompt_assembled`, and the runtime is constructed in
   `DeviceSession.run` before the hello exchange and well before
   `SessionOpen`. `_span_event` drops an event whose session has no
   entry, so the initial agent's provenance, the ordinary case, cannot
   be retained by the proposed fold. Say either that pre-open values
   are held in a bounded pending structure claimed by `_open_session`,
   or that the event moves after `session_open`, and test with the
   production ordering rather than a synthetic event after an open
   trace.

   *Resolution.* Adopted, first branch, and confirmed against the code
   before adopting: `PipelineRuntime.__init__` line 851 emits through
   `_activate_agent`, and `DeviceSession.run` constructs the runtime at
   line 497 against a `session_open` emitted at line 565. The premise
   section now records the ordering and the consequence, that the
   initial agent's provenance reaches no trace at all today. The fold
   holds a pre-open `prompt_assembled` in a bounded `PENDING_PROMPTS`
   map claimed by `_open_session`, the shape `capture_started` already
   has; moving the emission is rejected, because where the event sits
   in the log is a fact about when the prompt was assembled. The test
   list gains the production-ordering case and the eviction case.

3. **P1: M4b leaves its central configuration decision unresolved.**
   The plan names "where the key lives, whether it is one key or three,
   and what an assertion means when the trace transport and the media
   transport point at different deployments" as M4b's territory and
   then never answers any of it. Select the exact schema and semantics
   before implementation: the key or keys, defaults, which transports
   each assertion covers, behavior when `export_audio` uses a different
   `LANGFUSE_HOST`, refusal ordering, and the value-free error text.

   *Resolution.* Adopted, and answered in a section of its own. One
   key, `server.telemetry.reach`, in the `Reach` vocabulary the MCP
   entries already use; absent means `internet`, which is what the
   three call sites pass today, so an upgrade is byte-identical. One
   assertion covers every destination the section sends to and means
   the outermost of them, so the mixed case (LAN collector, vendor
   media host) is `internet` and refuses all three features rather than
   admitting the one that would have been caught. The refusal keeps its
   ordering and its value-free sentence and names the declaration the
   reach came from. The key is documented as an assertion rather than a
   proof, in the promises page's own words.

4. **P2: capture pinning cannot use the existing retained-context seam
   as claimed.** The opaque context can only be passed to
   `export_transcript`. Capture upload does two later session-key
   lookups instead, `trace_of(job.session)` before uploading and
   `reference_media(job.session, ...)` after, and neither accepts a
   pinned context, so pinning into `_Job` alone fixes neither eviction
   window. Specify the API change, and force eviction independently
   before the upload lookup and between upload completion and reference
   writing.

   *Resolution.* Adopted, and confirmed against the code: the two
   lookups are `capture_upload.py` lines 733 and 752, and neither takes
   a context. The addressing changes rather than the job.
   `retained_context` stays the one admission-time pin and both
   operations take the pinned handle, with the session-keyed spellings
   removed rather than left beside them, so after M4a there is one way
   to address a trace after its session closed. Both have one
   production caller and one test double, so the change is a signature
   and its call sites. The two windows are two test cases.

5. **P2: turn-trace retention has no implementable bound or addressing
   contract.** M4a promises a bound "derived from the configured
   capacity", but session capacity bounds concurrent sessions and not
   turns per session, and one long session can create arbitrarily many
   turn traces. State what identifies a turn trace, when its context is
   captured, who pins it, and the bound, plus what happens when one
   live session exceeds it and how #496 and #501 avoid losing an
   artifact's target. Add pressure tests for many turns in one session.

   *Resolution.* Adopted. The contract is written out: a turn is
   addressed by its session-local ordinal, its context is captured at
   the turn's open, it lives in its session's retained entry so the one
   pin at the close carries every turn under it, and the bound is a
   per-session `RETAINED_TURNS` cap rather than anything derived from
   `max_sessions`, which the review is right cannot bound turns. A
   session past the cap loses its oldest targets and the artifact says
   `no_trace` rather than being filed under the session trace. The
   many-turns case is in the test list.

6. **P2: "device name on every span" omits existing manually
   constructed spans.** `reference_media`, `_transcript_spans` and the
   after-close outcome path each build their attributes separately from
   the tables, and the promised tests would not prove the every-span
   requirement. Enumerate every span constructor, carry the sanitized
   nullable name in the retained context so post-close writers do not
   re-read mutable configuration, and assert absence rather than a null
   attribute for an unnamed device.

   *Resolution.* Adopted in full. The plan now carries the enumeration
   as a table of span constructors and how each one gets the name,
   which makes the three that build their attributes by hand
   (`reference_media`, `_after_the_close`, `_transcript_spans`) visible
   rather than implied. The name joins the retained identity and the
   post-close writers read it from the pinned context, for the
   correctness reason the review gives and for a second one: a board
   renamed after a session ran must not change what that session's
   spans say. The tests are one case per constructor plus the
   absent-not-null case.

7. **P2: TTS characters are classified in the wrong usage direction.**
   The plan says a voice is given text and then maps that consumed text
   to `gen_ai.usage.output_characters`. At the TTS model boundary the
   sentence is input and the audio is output, so the spelling reverses
   the interpretation used for LLM tokens and ASR audio. Use
   `gen_ai.usage.input_characters`, and make the price definition and
   the cost query use the same direction.

8. **P2: the M5 round-count cap does not bound memory.** Each retained
   item is a whole prompt with history, tool schemas, arguments and
   results, and none of that has a stated byte ceiling, so a fixed item
   count bounds cardinality rather than memory. Define a byte bound and
   say whether an oversized request is dropped, truncated or replaces
   older entries; truncation contradicts fidelity, so dropping whole
   requests with explicit accounting is the consistent choice. Test one
   oversized request as well as more rounds than the cap.

9. **P2: M5 omits model invocations and required lifecycle wiring.**
   The footprint names `telemetry.py`, composition and the new module,
   but not `runtime/pipeline.py` or `device/session.py`, which hold the
   only points where requests can be staged and post-close work
   enqueued. There are two call shapes, the tool loop and recap
   summarization, and the first-token watchdog can send the same
   logical round twice. Name every wiring change, and decide whether an
   observation is a logical round or a physical attempt, covering the
   ordinary, tool-follow-up, recap, retry, failed, cancelled, close and
   shutdown paths.

10. **P2: backend pricing is mutable external state with no deployment
    or upgrade story.** Entering model definitions through a live MCP
    changes the development project and not an operator's self-hosted
    backend, and nothing makes those definitions reproducible,
    idempotent, versioned or discoverable, so a deployed server can emit
    usage correctly while every cost reads zero. Say whether model
    creation is product-managed or operator-managed, and either
    document a repeatable procedure and qualify the acceptance
    criterion, or name the provisioning mechanism, its credentials, its
    idempotency and why a server startup may mutate a backend.

11. **P2: M4a incorrectly claims its capture fix is not observable.**
    Its purpose is to stop admitted capture jobs from becoming
    `no_trace` under eviction pressure, which changes whether a
    recording appears on the trace and which outcome event is emitted.
    Add a `### Fixed` fragment.

12. **P3: the stated M5 retention answer is factually too short.** M1
    is to record that assembled requests exist "for the session, and
    then nowhere", but the close hook moves staged requests into a
    worker job, so the content outlives the session in process memory,
    possibly past the bounded shutdown wait. Say so, and say that a
    crash loses queued exports with no recoverable ledger, unlike
    capture staging and transcript source rows.
