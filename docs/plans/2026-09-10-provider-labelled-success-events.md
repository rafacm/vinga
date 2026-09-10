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

### `heard` names the configured entry even when the transcription was reused

A reply that answers a confirmed barge-in reuses that barge-in's transcription
rather than running ASR again, which is why `asr_ms` is null on those turns:
"not measured this turn" rather than somebody else's wait.

The provider fields are deliberately NOT null there. `asr_ms` is a measurement
and belongs to the call that made it; the provider is a fact about which entry
the ASR stage is bound to for this agent, and the reused transcription came out
of that same entry, because both call sites read `providers.asr`. So the fields
are filled on every `heard`, and the asymmetry with `asr_ms` is intended and is
stated in the field notes.

### `sentence_synthesized` keeps its DEBUG level

It is DEBUG and stays DEBUG. Changing an event's level is #66's decision to
revisit, not this issue's, and the level does not block the dashboard this issue
exists for: `_dispatch` offers every emission to every non-log tap before the
log tap ever sees it, and `ConversationStore.record_event` gates on the
telemetry switch, the session being open and the in-flight bound, never on
level. So the store, the capture and `GET /api/runtime/events` carry
`sentence_synthesized` at any log floor. The log-side asking is
`vinga events tail --level DEBUG`, which the catalog already documents.

This is worth stating because it is the one thing an operator building the
dashboard could get wrong, and because it was checked rather than assumed while
diagnosing #455.

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
M2 likewise: the telemetry surface's own reference is generated.

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
