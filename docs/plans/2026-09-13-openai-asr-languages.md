# The openai ASR hears several languages, and says which one it heard

Plan for [issue #500](https://github.com/rafacm/vinga/issues/500).
Companion implementation doc:
`2026-09-13-openai-asr-languages-implementation.md`, one section per
milestone, appended in the same change that ticks the milestone
checklist.

## Goal

The `openai` ASR type can be told about one language and never reports
which one it heard, so a pipeline misdetecting language on a large
fraction of short utterances looks healthy on every surface an
operator watches. This plan closes both halves: the type gains a
`languages` list for the household that speaks more than one, it fills
`AsrResult.language` from what the model reports so the detected
language reaches the `heard` event, the conversation record, the
`/api` read surface and the `vinga.asr.language` span attribute that
already exist for it, and `DEFAULT_MODEL` moves to `gpt-transcribe`,
which is the model that reports at all.

Getting there needs one thing the issue does not name: the `openai`
ASR type declares no options model, so there is no write-time refusal
for a cross-field rule to live in and no generated reference for the
field descriptions the issue's Documentation section assumes. The
type joins the #88 conversion first, which is milestone 1.

Local baseline: not applicable. No conversational capability changes.
This is one cloud provider type learning to describe and report
language; the enumerated list in
[the product promises](../architecture/product-promises.md) does not
move, and the local `faster_whisper` type, which already detects,
reports and locks, is untouched.

## What the endpoint actually does

The issue argues from OpenAI's model page. Every claim below was
instead measured against the live endpoint on 2026-09-13 with the
repository's own key, because three of the issue's assumptions turned
out to be wrong and one of them decides a design question. German
speech was synthesized with `tts-1` and transcribed with
`response_format: json`.

| | `gpt-transcribe` | `whisper-1` | `gpt-4o-mini-transcribe` |
| --- | --- | --- | --- |
| accepts `languages` | yes | 400, `invalid_parameter` | 400, "not supported for this model" |
| accepts `language` | yes | yes | yes |
| both together | 400, "cannot be used together" | 400 | 400 |
| reports the language | always, on plain `json` | `verbose_json` only, as `"german"` | never |
| bills in | duration seconds | duration seconds | tokens |

Five findings follow from that, and each one moves a decision below.

**The report is a list of objects, and it arrives on plain `json`.**
The response carries `languages: [{"code": "de"}]`, an ISO 639-1 code
rather than the English name `whisper-1` answers with under
`verbose_json`. No confidence is reported by any model, so
`AsrResult.language_confidence` stays None and the `heard` event's
field stays absent, as it is today.

**A clip with no speech in it answers `languages: []`.** Silence and
laughter both did. An empty list is the endpoint's own spelling of "I
heard no language", which maps onto None without a rule of ours.

**The list never carried more than one entry**, not even for a
genuinely code-switched sentence ("Hallo, ich habe eine Frage. Can you
tell me a joke in English, bitte?" answered `[{"code": "de"}]`). So
the plural is the wire's shape rather than a second value to model,
and `AsrResult.language` stays a single code.

**`languages` is a prior, not a pin, and so is `language` on this
model.** A full German sentence sent with `languages: ["sv"]` came
back correct German and reported `de`, overriding the hint; the same
sentence sent with `language: "sv"` also came back correct German.
Neither spelling forces a decode on `gpt-transcribe`, which is worth
one sentence in the example fragment, because the current fragment
promises that pinning "takes the question away from detection
outright" and that is a fact about the gpt-4o pair rather than about
this model.

**The decisive one: when a single language is given, the report is
that code handed back.** `language: "sv"` on German answered
`languages: [{"code": "sv"}]`. `languages: ["sv"]` did too. With two
hints the model chose between them rather than echoing both, and
chose wrongly on a one-word clip (`languages: ["de", "en"]` on spoken
German "Hallo" transcribed `Hallo.` correctly and still reported
`en`). So a reported code is evidence about what was heard only when
the model was not told a single answer, and reporting it regardless
would put configuration into a metric under the name of a
measurement.

The issue's own failure reproduced exactly, which is the evidence
that the change is worth making: spoken German "Hallo", unhinted,
transcribed `Hello.` and reported `en`; with `languages: ["de", "en"]`
the same clip transcribed `Hallo.`

## The issue's decisions, restated

- **Point 4 is in scope.** `DEFAULT_MODEL` moves to `gpt-transcribe`,
  with a changelog entry, so the behaviour change for deployments that
  never set `model` is communicated rather than discovered. Recorded
  on the issue, 2026-09-12.
- **Point 3 is the one not to drop.** The language hint improves the
  odds; the language report is what lets an operator find out they
  were wrong.
- **`languages` is mutually exclusive with `language`, refused at
  write time**, with a message saying which model wants which. A
  runtime rejection from the vendor is a conversation that fails for
  a reason no log explains.
- **The singular `language` stays** for models that take that instead,
  so older and compatible endpoints are unaffected.
- **Sequenced inside the #502 telemetry overhaul**, after M3 and
  before #496.

## Open questions the issue leaves, resolved

**Does the type need an options model, or will a check in `build`
do?** It needs the model. `build` runs when a provider is constructed,
which is startup or apply; the issue asks for a refusal at *write*
time, and the only write-time gate is
`config/store.py::_written_option_types`, which asks
`checked_options`, which answers None for a type that declares none.
The model also earns three things beyond the refusal: the generated
reference the issue's Documentation section assumes
(`docs/reference/domain-config.md` lists a type's fields only when it
declares them), `vinga schema provider asr openai`, and the printable
half of the URL-credential rule, which today can name no option of
this type because it computes printable names from the declared
model.

**How does a cross-field refusal name both fields without quoting
what was written?** Through `FieldProblemsError`, which
`config/models.py::_error_problems` already unpacks: a model-level
validator's error is located at the model, so several problems arrive
as one error at one location, and this is the mechanism that survives
that. The refusal therefore names `language` and `languages` and the
rule, and never the codes. This is the no-leak lens applied to the one
new refusal the plan adds.

**When is a reported code filled in?** Only when the model was not
told a single language, per the measurement above. Concretely: fill
`AsrResult.language` when neither `language` (configured or hinted)
nor a one-element `languages` was sent. A `languages` list of two or
more is a choice among a declared set, which is a detection within
constraints and is reported. This is not a new rule invented here; it
is the rule `runtime/pipeline.py` already states at the point it
builds the `heard` event, "Only engines that detected carry these; a
mock or a pinned language adds no noise to the record", and the
`AsrResult` docstring's "None when the engine did not detect (pinned,
hinted, or an engine that has no notion of language)". The openai type
is simply the first one for which the rule has teeth.

**What about a list of exactly one?** Refused at write time as well?
No: accepted, sent, and treated as a pin for reporting purposes. A
one-element list is a legitimate way to say "this household speaks
German", it is what an operator migrating from `language` will write,
and refusing it would be a rule about our taxonomy rather than about
the endpoint, which accepts it.

**Does a reported code need validating before it becomes a
`LanguageTag`?** The value type already declines a value that is not a
code, rather than truncating it, and the fill path reads
`model_extra` rather than a declared SDK field, so the plan's tests
plant a malformed code and a non-list and assert the turn survives
with no language rather than raising. A far-side value decides nothing
here except what one field says.

## The smaller decisions

- **The model default has exactly one home, and M1 moves it there.**
  A converted type declares its default on the field:
  `FasterWhisperOptions` says `default="small"` and
  `providers/faster_whisper.py` keeps no constant of its own. So M1
  deletes `openai_asr.DEFAULT_MODEL` rather than leaving it beside the
  field as a second copy, and carries its reasoning into the field's
  description and the comment above it, which is the part worth
  keeping. M3 then edits the field. Two structures that must agree are
  one structure with a bug pending, and a constant the builder no
  longer reads is the version of that bug where the stale one looks
  authoritative.
- **`languages` travels through `extra_body`.** The installed SDK
  (`openai` 2.48.0) has no `languages` parameter on
  `audio.transcriptions.create`, and `gpt-transcribe` is not in its
  `AudioModel` literal either. Both are ordinary: the model already
  travels as a plain string, and `extra_body` is the SDK's declared
  door for a parameter it does not model. Pinning a newer SDK for a
  typed parameter buys nothing and is not done.
- **The report is read off `model_extra`.** `Transcription` is
  `extra="allow"`, so the key is reachable and stays reachable when
  the SDK later declares it. Read defensively: the key may be absent,
  may not be a list, and its entries may not be mappings.
- **`languages` is sent only when set.** An unset option sends no key,
  so `whisper-1` and a self-hosted compatible endpoint are untouched,
  which is what keeps the singular path working for them.
- **No validation that `languages` suits the configured model.** The
  endpoint answers that, differently per model and per vendor, and a
  table of which model takes which parameter is a second copy of
  someone else's product decisions that goes stale silently. What the
  plan owns is the refusal of the combination the API itself calls
  invalid, which is the one that is a fact about the request rather
  than about a model.
- **Precedence is stated, because the validator cannot see the runtime
  hint.** The mutual-exclusion rule is a fact about one written entry,
  and `language_hint` arrives per call from the session. Today
  `pinned = self._language or language_hint`, so an entry with
  `languages` set would put `language` in the same request whenever a
  hint existed, which is exactly the combination the endpoint refuses.
  The order is: a configured `language` wins; then a configured
  `languages`, and while it is set the session hint is not sent at all,
  as either spelling; then the session hint, as `language`, which is
  what happens today. The hint is a suggestion a provider may ignore,
  which the stage contract already says, and an entry that has
  described its household is a better description than a lock another
  engine set. The path is reachable rather than theoretical: the lock
  is session-scoped and survives an agent switch on purpose, so an
  agent transcribing with `faster_whisper` can hand a session over to
  one using this type.
- **The echo retry resends `languages` unchanged.** It is the same
  clip being heard again under the same description; withholding the
  prompt is the point of that retry, and withholding the language
  description too would make the retry a different question.
- **`submitted_ms` is unchanged.** #502 M3 reports it as the ASR usage
  and the backend prices it. Worth recording rather than acting on:
  `gpt-4o-mini-transcribe` bills tokens while `gpt-transcribe` bills
  duration seconds, so the default move makes the existing
  milliseconds-based accounting exactly right for the default model
  rather than an approximation. The Langfuse side of that is a model
  definition in the backend, not code here.

## Module layout

No new module. The change deepens two that exist.

`config/provider_options.py` gains `OpenaiAsrOptions`, the fourth
declared type, with the mutual-exclusion validator. What its callers
stop having to know: that the `openai` ASR type has options at all.
Today every surface that asks what this type accepts gets None and
falls back to passing everything through; after M1 the write path, the
read-back, the schema command, the generated reference and the
credential rule all read one declaration.

`providers/openai_asr.py` keeps its factory and its `transcribe`, and
loses the `OptionsReader` ladder to the model above. It keeps the
temperature range check, and that is a decision rather than an
oversight: the rule is conditional on whether the endpoint is OpenAI
itself, `providers/openai_endpoint.py` is the one home for deciding
that, and `config/provider_options.py` states an import contract with
three committed pins behind it, that it weighs "pydantic and
`config.models` and nothing else: no provider package, no engine, no
database driver, no cryptography". `openai_endpoint` imports
`providers.base` and `providers.kit`, so a model that imported it
would break `test_the_configuration_cli_loads_none_of_this_package`,
and a model that restated its URL rules would be the second home for
them. What the model can own is the shape of a temperature; what it
cannot own is which endpoint's rules apply. So the builder keeps the
range check, after typed validation, which is also where
`elevenlabs_tts.build` keeps the one translation its model cannot do.
The module docstring's third paragraph, which is today a careful
explanation of why this provider cannot report language, is replaced
by what it now does and under which condition.

No seam moves. `AsrResult` already carries the field; the pipeline
already reads it; the telemetry map already names it.

## Milestones

Cut so that the one behaviour change every existing deployment feels,
the default model, sits alone in its own review, and so that no
milestone ships an option the milestone's own default model refuses.
That ordering is the plan review's first finding: `languages` landing
while the default is still `gpt-4o-mini-transcribe` would let an
operator apply a configuration that boots and then fails on the first
transcription of a real conversation.

- [ ] **M1: declare the type's options.** `OpenaiAsrOptions` in
  `config/provider_options.py` carrying today's six options with their
  descriptions, registered in `PROVIDER_TYPES`, and `build` rewritten
  to take the validated model the way `elevenlabs_tts.build` does. The
  endpoint-conditional temperature range check stays in the builder,
  after typed validation. Behaviour-preserving for every configuration
  that boots today, which is a claim M1 has to earn rather than assert:
  refusal wording moves from this module's sentences to the shared
  validation rendering, and the read-back gate tightens. Both are
  pinned before and after per the pin-before-reshaping lens. Design
  footprint: deepens `config/provider_options.py`, adds no seam.
  Documentation footprint: three generated references move together,
  `docs/reference/domain-config.md`, `docs/reference/api-openapi.json`
  and `docs/reference/cli.md`, each through its own generator.
  Changelog: Changed.
- [ ] **M2: report the language the model heard.**
  `transcribe` fills `AsrResult.language` from the response's
  `languages` when nothing told the model a single answer, normalized
  so that anything malformed answers None rather than reaching event
  assembly. Reshapes
  `test_no_language_is_reported_and_no_session_lock_is_asked_for`,
  which is the pin that says today's behaviour, into the pair of pins
  that say the new one. `lock_language` is still never asked for: the
  lock exists to spare a local encoder pass, and there is none here.
  Design footprint: deepens `providers/openai_asr.py`; callers of
  `AsrResult` learn nothing new. Documentation footprint: the module
  docstring's language paragraph; the closing paragraph of
  `examples/asr-openai.yaml`, which today states there is no language
  reporting at all; and two claims in `vinga-server/README.md`, that
  the local engine is the only engine that reports what it heard and
  the "No language is reported back" paragraph. Changelog: Added.
- [ ] **M3: move the default model.** The default becomes
  `gpt-transcribe`, alone, so the one change every unconfigured
  deployment feels is reviewed by itself, and so that the option M4
  adds arrives on a model that accepts it. After M1 the default's one
  home is the `model` field on `OpenaiAsrOptions`, so that is what
  moves. Design footprint: none, one field default. Documentation
  footprint: the three generated references again, since the default
  is rendered into all of them; the example fragment's model
  paragraph, which recommends against `whisper-1` and describes a
  default that has moved; and the `vinga-server/README.md` options
  table's displayed default and its model comparisons, found by
  reading the pages rather than by grepping the model name, since a
  claim can be false without naming it. Changelog: Changed, with the
  compatibility note that a deployment which never set `model` changes
  model, and that a self-hosted compatible endpoint should set `model`
  explicitly if it has not.
- [ ] **M4: the `languages` option.** The list on the model, mutually
  exclusive with `language` through a model validator raising
  `FieldProblemsError`, sent through `extra_body` when set, and
  honoured by the report rule from M2. Design footprint: the
  cross-field rule lands beside the fields it is about, in the model,
  not in the factory. Documentation footprint: the generated
  references carry the field description; `examples/asr-openai.yaml`
  gains the paragraph on when to reach for which spelling, including
  that neither pins a decode on this model; `vinga-server/README.md`'s
  options table gains the row and the prose gains the one-language,
  several-languages and unset cases. Changelog: Added.

## Tests

Reusing the fixtures in `tests/unit/test_providers_openai_asr.py`,
which already has a transport-level `mock_client`, a `form_field`
reader for what was sent in the multipart body, and a `Tap` for
records; nothing new is needed to see a request or a log line.

- **M1**: characterization pins for each refusal the factory raises
  today (missing key, unset key variable, unknown option, non-string
  option, temperature out of range on OpenAI and accepted off it,
  base_url that is not a URL), committed green before the move and
  compared after. The comparison is the point, so the pins assert
  `record.msg` and typed args rather than a normalized rendering.
- **M2**: a response carrying `languages: [{"code": "de"}]` with
  nothing configured fills the field; the same response with
  `language: sv` configured leaves it empty; with a session
  `language_hint` leaves it empty; `languages: []` leaves it empty;
  a malformed payload (a string instead of a list, a list of strings,
  a mapping with no `code`) leaves it empty and raises nothing; the
  value reaches the `heard` event through the pipeline's existing
  path, asserted at the event rather than re-asserted on the result.
- **M3**: `languages` reaches the request body as a list; `language`
  and `languages` together are refused at write time, by field name,
  with neither code in the sentence, the args or the problems, which
  is the no-leak sentinel for this refusal (a code shaped like a
  credential is planted and its absence asserted across sentence,
  `args`, `FieldProblem` paths and both log formats); a one-element
  list is accepted and suppresses the report; a two-element list is
  accepted and does not.
- **M4**: the default is the new model, and an entry that sets `model`
  still sends what it set.

Each new claim is written to fail first and watched failing before it
is made, per the falsify-before-claiming lens, and each commit body
says the check was done. The M2 suppression rule is the one most
likely to pass for the wrong reason, since an empty field is also what
a bug produces, so its tests assert the filled case in the same file
and the mutation that removes the suppression is run and seen to break
them.

## Risks

- **The refusal wording moves in M1.** An operator's muscle memory for
  one sentence changes. Mitigated by pinning before and after, by the
  changelog entry, and by the fact that three types have already made
  this move and the rendering is the one they produce.
- **The report can agree with a wrong hint.** With two or more hints
  the model chooses among them and, on very short clips, chose wrongly
  in measurement. So the report is a signal in aggregate rather than a
  verdict per turn, and the example fragment says so rather than
  promising more than was measured.
- **`gpt-transcribe` may not exist on a compatible endpoint.** M3's
  changelog note tells such a deployment to set `model`. The failure
  it would otherwise meet is NOT a startup error, which this plan
  first claimed and the review corrected: `build` constructs a client
  and speaks to nothing, so an entry naming a model the endpoint does
  not have applies cleanly and fails on the first transcription of a
  real conversation. That is the reason the default moves before the
  option that depends on it, and the reason the changelog note is the
  mitigation rather than a nicety.
- **The SDK may later declare `languages` and `gpt-transcribe`.** Then
  `extra_body` and the string model still work, and the read still
  works because a declared field is reachable by attribute where
  `model_extra` was. Nothing has to move on that day.
- **Measurements here are one vendor on one date.** They are recorded
  in this plan with the shape of the evidence rather than as a claim
  about the vendor's future, and the tests pin our own handling, never
  the endpoint's behaviour.

## Plan review round

External review of commit `2a5ce4e5`, 2026-09-13. Backend codex
(codex-cli 0.154.0), model `gpt-5.6-sol`, sandbox read-only, 979 s
wall clock. Eleven findings, four P1 and seven P2, verdict "ready
after the P1/P2 amendments". Every one was confirmed against the code
before being accepted, and none was rejected; three were confirmed by
running something rather than by reading, and those runs are recorded
with the finding.

**1 (P1). The `languages` milestone lands before the model that
accepts it.** `languages` arrives while the default is still
`gpt-4o-mini-transcribe`, which 400s on it, and the failure is not the
startup failure this plan's risk section claims: `build` only
constructs the client, so an incompatible entry applies successfully
and fails on the first transcription of a real conversation.

*Resolution*: milestones reordered so the default moves before
`languages` arrives, and the risk bullet corrected to say request time
rather than startup. See "Milestones" below.

**2 (P1). A session language hint can make the provider send both
controls.** The validator sees configuration, not the runtime hint.
With `languages` configured and a non-None `language_hint`,
`pinned = self._language or language_hint` puts `language` in the same
request as `languages`, which is the combination the endpoint refuses.
Confirmed reachable: `_asr_language` is session-scoped and
deliberately survives an agent switch (`runtime/pipeline.py:787-791`,
"the speaker does not change on an agent switch"), so a session whose
first agent transcribes with `faster_whisper`, which is the type that
sets `lock_language`, and then hands over to an agent using this type
carries a hint into it.

*Resolution*: precedence stated and tested, including the echo-retry
path. See "The smaller decisions".

**3 (P1). M1 moves ownership of the model default, and the old
milestone 4 edits the owner it obsoleted.** After the conversion the
builder reads `options.model` and the field declares the default, the
way `FasterWhisperOptions` does with `default="small"`; confirmed that
`faster_whisper.py` keeps no `DEFAULT_MODEL` constant at all.
`openai_asr.DEFAULT_MODEL` would be left either unused or as a second
home for one fact.

*Resolution*: the field is the one home, the constant goes in M1, and
the default-move milestone edits the field. See M1 and M3.

**4 (P2). The endpoint-conditional temperature check cannot move into
the options model.** `config/provider_options.py` documents an import
contract ("no provider package, no engine, no database driver, no
cryptography") with three committed pins behind it, and
`providers/openai_endpoint.py`, which owns endpoint classification,
imports `providers.base` and `providers.kit`. Importing it from the
model would break `test_the_configuration_cli_loads_none_of_this_package`
and duplicating its URL rules into the model would break locality.

*Resolution*: the check stays in the builder, after typed validation.
See M1.

**5 (P1). M1 names one generated artifact and CI diffs three.**
Declaring an options model changes `docs/reference/domain-config.md`,
`docs/reference/api-openapi.json` (which carries one component per
declared model, today `LlmOpenaiCompatibleOptions`,
`AsrFasterWhisperOptions`, `TtsElevenlabsOptions`, and whose API
description embeds the sentence listing which types declare one) and
`docs/reference/cli.md` (which renders an "options for asr type
faster_whisper" section per declared model). All three are diffed by
the server workflow.

*Resolution*: all three named in M1's documentation footprint and in
its verification, and again in the default-move milestone.

**6 (P2). The `languages` contract and its wire shape are
underspecified.** Empty lists, invalid strings, duplicates, order and
normalization are unsettled; `LanguageTag` is not an ISO 639-1
validator (confirmed: it accepts `not-a-language` and `de-DE` and
rejects only what fails its syntax); and the SDK does not send a list
as one field. Confirmed by capturing a request through a mock
transport: `extra_body={"languages": ["de", "en"]}` is serialized as
two repeated multipart parts named `languages[]`, so the existing
`form_field` helper, which looks for exactly one part by exact name,
would find nothing and a test built on it would pass while asserting
nothing.

*Resolution*: the contract is settled in "The smaller decisions" and
the tests gain a repeated-part helper. The `languages[]` spelling is
what the live endpoint accepted in this plan's measurements, so it is
recorded as the wire fact rather than treated as an SDK detail.

**7 (P2). The tests do not reach the write-time refusal they
promise.** `build_asr` in the provider tests constructs a provider and
never touches the configuration store; the write gate is in
`config/store.py`. The plan also tested only that both field names
appear, not the issue's requirement that the message says which model
wants which form.

*Resolution*: a store-level write test added to M4's tests, asserting
the refusal happens before persistence, the stored row is unchanged,
and the guidance is present.

**8 (P2). The normalization can still break the turn it claims to
protect.** Confirmed by running it: `LanguageTag("")` and a
forty-character value both raise `EventValueError`, and
`events/assembly.py` constructs `LanguageTag(language)` without
catching, so a malformed `code` reaching the result breaks event
assembly rather than being declined. Reading only `model_extra` is
also not forward-compatible, since a field the SDK later declares
stops being extra.

*Resolution*: the provider normalizes and returns None on anything
that is not exactly one syntactically valid code, reading through
`getattr(response, "languages", None)` so a declared field and an
extra one are the same read. See M2.

**9 (P2). The echo retry has no defined language provenance.**
`_request` answers text only, and the retry can replace the first
response; an implementation could return the retry's text with the
first response's language.

*Resolution*: a request answers one text-and-language observation, and
the retry's pair replaces the first one whole. See M2.

**10 (P2). The read-back tightening is not behaviour-preserving for a
stored row.** `_stored_option_types` validates every stored provider
row on read and its own docstring warns that an entry written before
its type declared a model can hold a key the model refuses. The
spellings of absence today's reader accepts are the compatibility
surface, which is why `FasterWhisperOptions` carries an explicit
`_blank_reads_as_unwritten` validator.

*Resolution*: M1 enumerates the spellings the current reader accepts,
preserves them, adds a stored-row upgrade test and a changelog
compatibility note, and drops the unqualified "behaviour-preserving"
claim.

**11 (P2). Two maintained README claims become false and one table
becomes incomplete.** `vinga-server/README.md` says the local engine
"is the only one that reports which language it heard" and carries a
"**No language is reported back.**" paragraph asserting the fields stay
empty; its options table lists no `languages`. A grep for the model
name in the default-move milestone would not have found any of them.

*Resolution*: named in the documentation footprint of the milestone
that falsifies each.
