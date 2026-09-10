# Provider-labelled success events (#450)

## Goal

Give the two success-side stage events, `heard` and `sentence_synthesized`, the
same four provider-identity fields `llm_round` already carries, off the same
seam, so that "TTS latency by provider" and "ASR latency by provider" become
answerable from the event vocabulary instead of only "TTS failures by provider".

Companion implementation doc:
`docs/plans/2026-09-10-provider-labelled-success-events-implementation.md`, one
section per milestone, appended in the change that ticks the milestone.

## The issue's premise, refreshed

#450 was filed against a vocabulary that no longer exists, and the refresh is
recorded on the issue itself rather than only here.

The issue asks for a new success-side TTS event carrying provider, timing and
volume, because at the time the only TTS success signals were `speaking_started`
and `replied`. #66 M1 (`843e7ca0`, PR #442) landed `sentence_synthesized`, which
carries `first_chunk_ms`, the voice's own latency to its first audio chunk
measured before backpressure can bite, and `stream_ms`, the whole stream's
lifetime. The same change gave `heard` an `asr_ms`.

So the timing half of the request is served and the volume half is served by
`replied.sentences` plus `speaking_finished.frames`. What is not served, and is
precisely what makes the dashboard's "by provider" breakdown impossible, is
identity: neither success event says which configured entry produced the audio
or the transcript.

**Therefore this issue is not a new event.** It is four fields on two existing
events. Adding `tts_round` beside `sentence_synthesized` would be two structures
that must agree, which `docs/architecture/design-guide.md` calls one structure
with a bug pending.

The issue's parenthetical, that ASR likely has the same gap and is worth the
same pass, is accepted and is in scope rather than a follow-up. Symmetry across
the three provider stages is the whole point of the change.

## Decisions the issue leaves open, decided here

### The fields are `llm_round`'s four, spelled identically

`provider`, `type`, `host`, `model`, declared exactly as `LlmRound` and
`ProviderFailed` declare them: `Identifier | Absent = value(default=ABSENT)`,
with the same NOTE saying that `provider` and `type` are atomic, `host` is
absent for an engine running in this process and `model` for a type that has
none to name.

They are produced by `assembly._entry_fields`, the existing crossing from a
provider object to the four values, which answers four values or four absences
so that a record naming an entry without a type has nowhere to come from. No new
derivation, and no second spelling of a fact that already has one.

### The sentences do not change

`LlmRound`'s TEMPLATE and ARGS do not render provider, type, host or model;
those are carried payload fields only, and the sentence names the agent, the
round, the duration and the turn count. `Heard` and `SentenceSynthesized` follow
that exactly: four carried fields, `TEMPLATE` and `ARGS` untouched.

This is what makes the change cheap to review. Every existing pin on either
event's `record.msg` and typed `record.args` stays byte-identical, so the "pin
before reshaping" lens is satisfied by construction rather than by a
characterization pass: there is no rendering to preserve because no rendering
moves.

### Nothing is threaded to reach the emit sites

Both sites already hold their provider object.

- TTS: `_synthesize` has `tts` in scope and already hands it to
  `_provider_failed` on the failure arm (`pipeline.py:2828`). The success arm's
  callback becomes `lambda first_chunk_ms, stream_ms: self._sentence_synthesized(index, tts, first_chunk_ms, stream_ms)`.
- ASR: the `heard` emit sits inside the block that ran `providers.asr`
  (`pipeline.py:1373`), so `providers.asr` is in scope at the emit.

A milestone that had to pass a provider down through a call chain would be a
different and larger change; it does not.

### A reused transcription carries the provider that actually ran it

A reply that answers a confirmed barge-in reuses that barge-in's transcription
rather than running ASR again. Two facts about that path decide this design, and
the first draft of this plan had both of them wrong.

`heard.asr_ms` is NOT null on those turns. The confirmation's latency is
measured at the site that runs it and handed over on the `Utterance`, precisely
so that the one interruption an operator cannot otherwise see the ASR cost of
reports a real number. What IS null on those turns is `Turn.asr_ms`, a different
field answering a stricter question: whether THIS turn ran a transcription.

And the provider cannot be read at the emit site. `confirm_transcript` awaits an
ASR call while the reply in flight may run a handover, and a handover rebinds
`self._providers`, so `providers.asr` at the `heard` emit is not necessarily the
provider that produced the transcript being reported. Since `heard.asr_ms`
already reports the confirmation call, reading the provider from the current
binding would put two different calls in the two halves of one record.

So the provenance travels with the result:

- `confirm_transcript` returns a frozen `Confirmation(result, provider)` rather
  than a bare `AsrResult`. `provider` is typed `object`, which is exactly what
  `assembly._entry_fields` takes, so nothing about a provider's own types
  reaches `turntaking` and the seam keeps its stated rule, that the ladder needs
  an answer rather than the machinery producing one.
- `_gate_barge_in` carries the provider beside the result and the latency it
  already carries.
- `Utterance` gains `asr_provider`, set with `transcript` and `asr_ms`, which
  its own docstring already says travel together and are set together.
- A turn that ran its own ASR passes `providers.asr` directly, as before.

The deterministic pin for this is named in the tests section: suspend the
confirmation, hand over, then assert `heard`'s quartet describes the provider
that transcribed rather than the one now bound.

### `sentence_synthesized` keeps its DEBUG level

It is DEBUG and stays DEBUG. Changing an event's level is #66's decision to
revisit, not this issue's.

What that costs an operator building the dashboard is three surfaces with three
different answers, and the plan states all three because getting this wrong is
the most likely way to conclude the event is missing when it is not.

- **The store, the capture and any OTel exporter receive it regardless of any
  threshold.** `_dispatch` offers every emission to every non-log tap before the
  log tap ever sees it, and `ConversationStore.record_event` gates on the
  telemetry switch, on the session being open and on the in-flight bound, never
  on level. A dashboard reading the conversation store therefore sees
  `sentence_synthesized` at any log level.
- **The JSON log needs a DEBUG server log level.** The log tap is an ordinary
  logging call on the session channel, so `server.log_level` decides.
- **The live API and the CLI in front of it need an explicit DEBUG filter.**
  `GET /api/runtime/events` is not a log reader; the live stream carries its own
  default of INFO and drops anything below it, so a reader that names no level
  is given INFO and up. `vinga events tail --level DEBUG` is the asking, and it
  is asking the stream rather than the log.

The first draft of this plan asserted the second and third of these as one
thing and got it wrong, which is recorded in the review round.

### The span attributes are a separate milestone

The OpenTelemetry exporter's stage tables (`ASR_ATTRIBUTES`, `TTS_ATTRIBUTES`)
are a settled correspondence to the GenAI conventions, and extending them is a
different review lens from extending the catalog. It gets its own milestone so
each sits alone in review.

## Module layout

No new modules. The change deepens three that exist.

- `events/catalog.py`: four declarations on each of two variants. The catalog is
  a compatibility surface, so this is the whole of the vocabulary change.
- `events/assembly.py`: `heard` and `sentence_synthesized` gain builders beside
  `llm_rounded`, `llm_retried` and `provider_failure`, each running its provider
  object through `_entry_fields`. What the callers stop having to know: that a
  provider object becomes four values, and that naming an entry without a type
  is a shape nothing may construct. Today both events are built inline at the
  emit site with a `lambda`; moving them into assembly is what puts them on the
  same footing as every other provider-labelled event and keeps `_entry_fields`
  with exactly one class of caller.
- `runtime/pipeline.py`: two emit sites pass their provider to the builder.
- `telemetry.py` (M2): two attribute tables gain the four keys.

Seam: `assembly._entry_fields` is the crossing and it does not move. The
milestone adds callers to it, not a layer beside it.

## Documentation footprint

- `docs/reference/events.md` is generated and changes only through
  `uv run vinga-server events reference > ../docs/reference/events.md`. CI diffs
  the committed copy (`vinga-server.yml:572`).
- `docs/architecture/observability-surfaces.md` row for structured events
  describes the surface's contract, not its field lists, and this change adds no
  new class of value: four trusted identifiers off a validated entry. The row
  is not falsified and is deliberately not edited.
- `docs/glossary.md` names `llm_round` as the event carrying token counts and
  lists event names in a sample; neither claim is falsified.
- `docs/features/2026-08-06-provider-observability.md` is a dated feature record
  of what shipped then, not a live map, so it is not retrofitted.
- The command-spellings census sweeps every tracked file and is staled by line
  moves in files it records. Regenerate with
  `uv run python -m tests.unit.test_command_spellings`, never by hand.
- `CHANGELOG.md` gets a dated `### Added` entry per milestone.

No hand-maintained page's description of current behavior is falsified by M1.

M2 has no generated reference to regenerate: `events_docgen.py` generates the
event vocabulary and its field names, not span attribute mappings. The mapping
is owned by `telemetry.py`'s tables and the span pins beside them, which is
exactly what `docs/architecture/observability-surfaces.md` already says about
that surface, so no page is created for a table that has an owner. That row
stays accurate because M2 adds attribute names under the prefix it already
describes rather than a new class of value.

## Tests

Reusing the assets that exist rather than restating them.

- `tests/unit/test_event_baseline.py` holds every driver to producing the fields
  its path is supposed to carry. The two drivers for these paths gain the four
  fields, which is the completeness claim for this change: the catalog says the
  variants declare them and the driver run says the paths produce them.
- `tests/unit/test_event_catalog.py` and `test_event_docs.py` hold the
  declarations and the generated reference.
- The atomicity rule gets a pin of its own per event, in the shape
  `provider_failed` already has one: a provider the registry never built
  contributes four absences, never an entry name with no type.
- A no-leak sentinel per event: plant a credential-shaped value in the provider
  configuration's options, drive the path, and assert absence from the sentence,
  the typed args, the payload fields and both log formats. `_entry_fields` reads
  four names off a built entry rather than serializing a configuration, so this
  is sanitized by construction; the pin is what says so.
- The sentence non-change is asserted directly: `record.msg` and `record.args`
  for both events, before and after, are the same values.
- M2: the span attribute pins in `tests/unit/test_telemetry_spans.py`, extended
  for the four keys on the ASR and TTS spans.

## Risks

- **The catalog is a compatibility surface.** Adding optional fields to an
  existing variant is additive: a consumer reading by name is unaffected, and a
  row written before this keeps the shape it was written in. The risk is
  spelling a fact a second way, which the decision to reuse `_entry_fields` and
  `llm_round`'s exact four names removes.
- **`_entry_fields` takes `object`.** It is deliberately untyped so that
  nothing about a provider's own types reaches the events package. The
  mitigation is the atomicity pin: a provider it cannot read contributes four
  absences and the record is still well-formed.
- **A rebase against another milestone's regenerated artifact** (the events
  reference, the census manifest) produces a textual merge neither side wrote.
  Regenerate on the rebased tree and prove green before pushing.

## Out of scope, recorded

- #452 suggestion 2, surfacing a detected `language` from the OpenAI verbose
  transcription response, was to ride here and does not. The premise fails:
  `openai_asr.py:28-39` records that the response carries a detected language
  only for `whisper-1` asked for `verbose_json`, as an English name rather than
  an ISO code, with no confidence from any model, which is why the request asks
  for `response_format="json"`. Implementing it means switching format by model
  and mapping names to codes while reporting nothing for the two models the
  example config steers operators toward. That is a design decision with a cost,
  not a rider. Recorded on #450 and #452.
- Provider-broken-down aggregate views. #439's views count by event name; a
  per-provider latency view is a natural follow-up and is not this change.
- Promoting `sentence_synthesized` to INFO, per the decision above.

## Milestones

- [ ] **M1: the vocabulary.** `heard` and `sentence_synthesized` gain
  `provider`, `type`, `host` and `model` off `assembly._entry_fields`, built by
  assembly builders beside `llm_rounded` rather than inline at the emit site,
  with both emit sites passing the provider object they already hold. Sentences
  and arguments unchanged and pinned as unchanged. Baseline drivers, atomicity
  pins and no-leak sentinels per event. Generated events reference regenerated;
  census regenerated if stale; changelog. Design footprint: deepens
  `events/assembly.py` by giving it the two builders that were inline lambdas,
  so the emit sites stop knowing that a provider becomes four values; adds no
  seam and no module.
- [ ] **M2: the spans.** `ASR_ATTRIBUTES` and `TTS_ATTRIBUTES` gain the four
  keys under the settled correspondence: `type` as `gen_ai.provider.name`,
  `model` as `gen_ai.request.model`, `host` as `server.address`, and the
  configured entry name as `vinga.provider.asr.name` and `vinga.provider.tts.name`,
  which is the spelling `_provider_attributes` already uses for what a session
  opened against, so one fact keeps one attribute name wherever it is read from.
  Span pins extended; changelog. Design footprint: deepens `telemetry.py`'s
  existing tables; adds no module and no seam.

## Plan review round

External review of commit `9e1443b4`, backend codex (codex-cli 0.154.0),
model `gpt-5.6-sol`, 2026-09-10. Findings as received, condensed but faithful,
each with its resolution.

### 1 (P1): a reused ASR result can be labelled with the wrong provider

`confirm_transcript` starts an ASR call and awaits it
(`pipeline.py:2993-3007`), while the reply in flight can independently run a
handover that rebinds `self._providers` (`_activate_agent`, which
`pipeline.py:548-560` names as that field's only writer). `Utterance` carries
the result and its latency but not the provider that produced them
(`turntaking.py:61-93`, `231-270`). So the reply that reuses the transcription
would label it with whichever provider is current after the race, not the one
that ran.

The plan should say that the confirmation snapshots its provider and returns
that provenance with the result, that `Utterance` carries result, latency and
provider atomically, and that the reused `heard` builder is given the captured
provider. Add a deterministic test suspending the confirmation while the old
reply hands over, asserting `heard`'s quartet describes the provider that
actually transcribed.

*Resolution*: accepted whole, and it is the finding that changes the shape of
M1. `confirm_transcript` stops returning a bare `AsrResult` and returns a frozen
`Confirmation(result, provider)`; `provider` is typed `object`, which is exactly
what `assembly._entry_fields` takes, so nothing about a provider's own types
reaches `turntaking` and the seam's existing rule ("the ladder needs an answer,
not the machinery that produces one") is kept rather than widened.
`_gate_barge_in` carries the provider alongside the result and the latency it
already carries, and `Utterance` gains `asr_provider` as a fourth field set with
`transcript` and `asr_ms`, which its own docstring already says travel together
and are set together. The race test is added to the milestone's tests, driving a
handover while the confirmation is suspended.

### 2 (P2): the claimed null `asr_ms` contradicts the landed contract

The plan says `asr_ms` is null for a reused barge-in transcription. It is not:
the confirmation's latency is measured at the site that runs it and handed over
on the `Utterance` (`turntaking.py:81-93`, `274-289`), `_reply` reads it
(`pipeline.py:1334-1350`, `1435-1449`), a regression test requires a real value
(`test_turn_lifecycle.py:344-369`), and the generated reference documents it
(`events.md:725`).

*Resolution*: accepted. The plan confused `Turn.asr_ms`, which IS null for a
reused transcription and says "not measured this turn", with `heard.asr_ms`,
which is deliberately less strict and reports what the transcription being
answered cost whoever ran it. The asymmetry the plan claimed does not exist, and
removing it makes finding 1 tighter rather than looser: `heard.asr_ms` already
reports the confirmation call, so `heard`'s provider quartet must report that
same call's provider or the two halves of one record would describe two
different calls.

### 3 (P2): M2 would mix call-time identity with stale open-time context

Both stage-span folds merge `self._context(trace, payload)` before the event's
own attributes (`telemetry.py:1688-1700`, `1788-1800`), and `_context` supplies
all four open-time `vinga.provider.<stage>.*` entries. Mapping the event's
`provider` onto the same `.name` key overwrites the name only, leaving open-time
`type`, `host` and `model` beside call-time data. The LLM span already avoids
this with `states=LLM_STAGE`.

*Resolution*: accepted. `_context`'s own docstring states the governing rule,
that one attribute name may have one source, so this is the codebase's rule
being applied rather than a new one. M2 passes `states` for the stage the span
answers for, and does so conditionally: the open-time context for that stage is
suppressed only when the event actually names an entry, because an event whose
quartet is four absences contributes nothing and suppressing the context would
lose what the session opened against rather than correct it. This also covers
the existing ASR `provider_failed` case, which is a collision M2 would
introduce rather than a live bug: `ASR_ATTRIBUTES` does not map the quartet
today, so no `provider_failed` quartet reaches an ASR span at present. The test
deliberately makes session-open identity differ from call-time identity and
asserts no hybrid appears, and covers an outcome with no quartet.

### 4 (P2): the live API does not carry DEBUG events unqualified

The live stream defaults to INFO independently of the logger and rejects lower
levels (`events/live.py:83-89`, `131-140`), and the API uses that default when
`level` is absent (`config/api.py:1967-1971`, `2122-2129`). `vinga events tail`
is a client of that stream, not a log reader.

*Resolution*: accepted, and the plan's operational note was wrong in the one
place it mattered, since it was written to stop an operator building the
dashboard from getting this wrong. Corrected to three surfaces with three
answers: the store, the capture and any OTel exporter receive DEBUG emissions
regardless of any threshold, because `_dispatch` offers every emission to every
non-log tap before the log tap sees it and `record_event` gates on the telemetry
switch, the session being open and the in-flight bound but never on level; the
JSON log needs a DEBUG server log level; and the live API and the CLI tail in
front of it need an explicit DEBUG filter.

### 5 (P2): the proposed tests prove presence, not attribution

The baseline's `CARRIED` table checks keys and not values
(`test_event_baseline.py:306-336`, `524-595`), the atomicity pin exercises only
a provider with no identity, and the no-leak sentinel exercises options that
should not be read. All would pass with `provider` and `type` swapped, with the
wrong provider object passed, or with TTS labelled from ASR identity.

*Resolution*: accepted. The tests section now requires per-event value
assertions built on four distinct identity values so a swap or a cross-stage
mislabel fails, absence cases for `host` and `model` separately from the
all-four-absent case, and at least one assertion driven through the real runtime
path rather than by invoking a builder directly. The reused-transcription race
from finding 1 is one of these.

### 6 (P3): there is no generated telemetry reference

`events_docgen.py` generates the event vocabulary and its field names, not span
attribute mappings, and the maintained observability map says telemetry uses
attribute names chosen by `telemetry.py`
(`observability-surfaces.md:38`).

*Resolution*: accepted; the claim is deleted. The mapping is owned by
`telemetry.py`'s tables and the span pins beside them, which is what the
observability map already says, and that row stays accurate because M2 adds
attribute names under the prefix it already describes rather than a new class of
value. No new maintained page is created for a table that has an owner.
