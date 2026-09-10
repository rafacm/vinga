# Provider-labelled success events: implementation

Companion to
[`2026-09-10-provider-labelled-success-events.md`](2026-09-10-provider-labelled-success-events.md).
One section per milestone, appended in the same change that ticks the
milestone checklist: deviations from the plan, resolutions of its open
questions, and what was discovered on the way.

## M1: the vocabulary

PR [#457](https://github.com/rafacm/vinga/pull/457).

### What landed

`events/catalog.py`: `Heard` and `SentenceSynthesized` each gain
`provider`, `type`, `host` and `model`, declared exactly as `LlmRound`
declares them (`Identifier | Absent = value(default=ABSENT)`), with
`LlmRound`'s atomicity note as a variant `NOTE`. The four sit at the end
of each field list, after the fields that were already there, so no
existing field moved in the generated reference. `TEMPLATE` and `ARGS`
are untouched on both.

`events/assembly.py`: two new builders, `heard` and
`sentence_synthesized`, beside `llm_rounded`, each running its provider
object through `_entry_fields`. Both events used to be constructed
inline at their emit sites with a `lambda` over the variant class; the
emit sites now pass plain values and a provider object and learn nothing
about which value type wraps which argument or that a provider becomes
four values. The module's interface is twelve builders and the fragment.

`runtime/turntaking.py`: a frozen `Confirmation(result, provider)` beside
`Utterance`, `provider` typed `object`. `_gate_barge_in` returns the ear
alongside the result and the latency it already returned, and `Utterance`
gains `asr_provider`, set with `transcript` and `asr_ms`.

`runtime/pipeline.py`: `confirm_transcript` reads `self._providers.asr`
into a local before its await and answers a `Confirmation` built from it;
`_reply` uses `utterance.asr_provider` for a reused transcription and the
snapshot's `providers.asr` for one it ran itself; `_speak_after` passes
the `tts` it already holds to `_sentence_synthesized`, which now takes
it. The field-ownership docstring says that `confirm_transcript` reads
`_providers` before an await a handover can land in.

Tests. `tests/unit/test_event_provider_labels.py` is new and holds the
attribution half: eight identity values, four per stage and no two alike,
asserted by value per record; `host` and `model` absences pinned one at a
time and separately from the all-four-absent case; both sentences pinned
on `record.msg` and the typed `record.args`; and the reused-transcription
race, driven by suspending the confirmation inside the ear, handing over
while it is held, and asserting that the reply that reuses the
transcription names the ear that ran it while the incoming agent's ears
were never called at all. Every assertion in that file runs through the
real runtime path rather than by invoking a builder.
`tests/unit/test_event_surface_pins.py` gains a no-leak sentinel per
event, planting a credential on the provider object beside its identity.
`tests/unit/test_event_assembly.py` holds the two new builders to the
atomicity rule with the three that already carry the quartet.
`tests/unit/test_turntaking.py`'s stand-in orchestrator answers a
`Confirmation` and pins that the ear crosses the gate on the utterance.
`tests/tools/event_baseline.py` plants a model on each stage's entry and
`CARRIED` gains the keys the two paths now produce.

`docs/reference/events.md` regenerated. `CHANGELOG.md` has a dated
`### Added` entry.

### Deviations

- **The baseline drivers plant a model and not a host.** The plan's
  tests section says the two drivers "gain the four fields". They gain
  three: `provider`, `type` and `model`. A mock provider runs in this
  process and reaches no host, which is exactly what `host` is absent
  for, and `llm_round`'s own baseline row has been three fields for the
  same reason since it was written. Planting a host on an in-process
  mock would have put a fact in the row that no configuration of that
  entry could produce. The host-present case is pinned by value in
  `test_event_provider_labels.py` instead, which is where the plan's
  review round put the attribution claims anyway.

- **`_gate_barge_in` returns a four-tuple rather than passing the
  `Confirmation` through.** The plan says the gate "carries the provider
  beside the result and the latency it already carries", which reads
  either way. The `Confirmation` type is what makes result and provider
  atomic at the crossing where the race is, and the gate unpacks it at
  the one line that receives it; threading the type further would have
  made `_handle_utterance` unpack it conditionally in two places to fill
  three `Utterance` fields the plan asks for by name.

- **The rounding of `language_confidence` moved into one place.**
  `_reply` rounded the detected confidence to two decimals twice, once
  for the event and once for the turn record. It now rounds once and
  hands the same number to both. Behaviour-neutral, and it came up
  because the event's construction moved out of that block: leaving the
  rounding at two sites would have left two sites deciding what a
  confidence is.

- **`hand_over_to` is a new white-box helper in `tests/support`.** The
  race pin needs the providers rebound at a chosen instant, while a
  confirmation is suspended inside its ASR call. In production a
  handover is reached from a tool call at a boundary of the reply loop,
  which cannot be aimed at that instant, and a rebinding that lands
  somewhere near it would prove nothing. The activation it calls is the
  production one; the reach is what is white-box, and it is documented as
  such beside the other reach-ins in that module.

- **No other deviation.** The four spellings, the crossing, the
  unchanged sentences, the emit sites holding their own provider, the
  DEBUG level of `sentence_synthesized` and the documentation footprint
  are as the plan states them. Nothing in the plan's open questions was
  left to this milestone to resolve.

### Discoveries

- **The race pin was verified to discriminate.** With the `heard` emit
  temporarily reading `self._providers.asr` instead of the carried ear,
  `test_a_reused_transcription_names_the_ear_that_ran_it` fails and the
  other seven cases in the file pass. The pin fails for the reason it
  exists rather than because the scenario is hard to run.

- **A credential cannot be planted in a mock entry's configuration.**
  `ProviderConfig` refuses inline secrets at validation and the mock
  providers take fixed keyword arguments, so the plan's "plant a
  credential-shaped value in the provider configuration's options" is
  not reachable through a configuration file. The sentinel is planted on
  the built provider object instead, beside the identity the registry
  stamped, which is where a real provider holds the key it
  authenticates with and is the same claim: what the record carries is
  the four names `_entry_fields` reads, never anything else the object
  holds.

- **The baseline harness keeps each driver's records per path.** A row
  in `CARRIED` describes one driver's own run, so `drive_heard` planting
  a model on the ASR entry does not disturb the `heard` records other
  drivers emit on their way to their own decisions.

## M2: the spans

PR [#460](https://github.com/rafacm/vinga/pull/460).

### What landed

`telemetry.py`: `ASR_ATTRIBUTES` and `TTS_ATTRIBUTES` gain the four
provider keys under the correspondence `LLM_ATTRIBUTES` already ships,
and the two stage folds stop letting the retained context speak for the
stage their event answers for. The entry-name attribute has one home,
`_entry_name(stage)`, which the three tables now request their entry
name through and which the fold asks its question against, so the
spelling the session context builds and the spelling a table wants
cannot drift apart. `_speaks_for(stage, spoken)` is that question: it
answers the stage where the event's own attributes carried its entry
name and nothing where they did not, and its answer goes straight into
`_context`'s existing `states` argument. `TTS_STAGE` joins `ASR_STAGE`
and `LLM_STAGE`.

Tests. `tests/unit/test_telemetry_spans.py` gains five cases: the quartet
pinned key by key on the ASR span and on the TTS span, including the
absent `server.address` for an engine running in this process; the
failed transcription naming the ear that failed, which is the outcome
that shares the ASR span; the hybrid guard, which runs a turn on an ear
and a voice differing from the session's own in all four names and
asserts that each stage span carries one provider whole and still
carries every other stage's open-time entries; and the two ways an ASR
outcome names no ear, an empty transcript and a provider the registry
never built, each keeping what the session opened against.
`test_every_stage_span_carries_the_session_context` now states the whole
rule rather than two sample facts: for every stage a span does not
answer for, every fact of that stage's open-time entry is on the span,
and for the stage it does answer for, the entry name is the only
`vinga.provider.<stage>.*` attribute there.

`tests/support/telemetry.py`: `hear` and `synthesize` build through
`assembly.heard` and `assembly.sentence_synthesized` the way `round_done`
already built through `assembly.llm_rounded`, so the quartet's absence
rules on a span are the real ones. Both default to the entry the agent
opened against, derived by `entry_of` from the fixture's own entries
rather than spelled a second time, and both take an `identity` for a
call that ran on something else and an `unbuilt` for a provider the
registry never stamped. `provider_failed` takes the same `identity`.

`CHANGELOG.md` has a dated `### Added` entry.

### Deviations

- **The round span's suppression stays unconditional.** The plan's
  milestone line says both stage folds pass `states` conditionally, and
  both is what landed: `_llm_span` still passes `states=LLM_STAGE`
  outright. The asymmetry is real and is recorded below rather than
  quietly fixed, because changing it is a behaviour change to a merged
  span the plan did not ask for and it falsifies an existing pin.

- **One clause of the observability map was edited after all.** The
  plan says no maintained page is falsified and the exported-traces row
  is deliberately not touched. The row's own list of what a turn holds
  attached "under the OpenTelemetry GenAI attribute names" to the
  generation round alone, which after this milestone reads as though
  only rounds wear them, so the clause now covers the three spans a
  provider ran. Nothing about the surface's contract moved: the row
  still says the vocabulary is derived from the structured events and
  the attribute names are this module's choice, which is what finding 6
  turns on.

- **No other deviation.** The four spellings, the conditional
  suppression, the `provider_failed` case that shares the ASR span, the
  two required pins and the rest of the documentation footprint (no
  generated reference to regenerate, no new maintained page) are as the
  plan states them.

### Discoveries

- **The hybrid pin was verified to discriminate, in both directions.**
  With both folds reverted to `self._context(trace, payload)`, which is
  the table edit alone that review finding 3 warned about,
  `test_no_stage_span_mixes_a_call_s_identity_with_the_session_s_own`
  fails, and so do `test_a_failed_transcription_names_the_ear_that_failed`
  and `test_every_stage_span_carries_the_session_context`; the two
  no-ear cases pass, which is right, since the context is what they
  assert and it is present either way. With the suppression made
  unconditional instead, `test_an_asr_outcome_that_names_no_ear_keeps_the_session_s_own`
  is the one case that fails. So each half of the rule has a pin that
  fails for its own reason.

- **The round span answers for its stage whether or not it named one.**
  `_llm_span` passes `states=LLM_STAGE` unconditionally, so an
  `llm_round` whose quartet is four absences leaves its span with no LLM
  identity at all, which is exactly what the conditional exists to
  prevent on the other two stages. It has no production consequence: a
  registry-built provider always carries an identity, and four absences
  are reachable only from a test double. It is a follow-up rather than a
  rider here, and `test_a_provider_with_no_identity_carries_no_gen_ai_keys`
  is the pin that would have to be amended with it, since the open-time
  context would then supply `vinga.provider.llm.name`.

- **A stage span carries `gen_ai.*` keys now, which the module's own
  prose used to deny.** The comment above `SESSION_ATTRIBUTES` says the
  settled correspondence sits on the round span and that nothing on
  "these two spans" is a GenAI fact; it is about the session and turn
  spans and stays true, and the two stage tables carry the reason they
  now speak that vocabulary beside them. An ear and a voice are
  `gen_ai` providers in the conventions' sense as much as a generator
  is, which is what makes one question answerable with one key set at
  all three stages.
