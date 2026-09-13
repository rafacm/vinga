# The openai ASR hears several languages: implementation

Companion to
[`2026-09-13-openai-asr-languages.md`](2026-09-13-openai-asr-languages.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: declare the type's options

The `openai` ASR type joins the #88 conversion. `OpenaiAsrOptions`
carries today's six options, the table registers it, and `build` takes
the validated instance the way `elevenlabs_tts.build` does. The two
rules that are about the endpoint rather than about a value stay in the
builder.

### What landed

| Piece | Where |
| --- | --- |
| The model, six fields with the fragment's factual sentence on each | `vinga-server/src/vinga_server/config/provider_options.py`: `OpenaiAsrOptions`, registered as the `asr` `openai` entry of `PROVIDER_TYPES` |
| The builder, taking the validated instance | `vinga-server/src/vinga_server/providers/openai_asr.py`: `build(label, config, options)`, `DEFAULT_MODEL` deleted, the `OptionsReader` ladder gone, the module docstring saying where the contract lives and what did not move |
| The refusal table, before and after | `vinga-server/tests/unit/test_providers_openai_asr.py`: every refusal the factory can raise, pinned as the whole sentence, with the accepted table beside it |
| The parity table and the type's own section | `vinga-server/tests/unit/test_provider_options.py`: `OPENAI_ASR_PARITY`, the defaults, the absent blank-spelling list, the two rules the model does not hold, the no-leak plant, and the published fields |
| The stored-row upgrade | `vinga-server/tests/unit/test_config_store.py`: every legacy spelling planted as a row and booted, and the one spelling that is not preserved pinned as a load refusal |
| The three generated references | `docs/reference/domain-config.md`, `docs/reference/api-openapi.json`, `docs/reference/cli.md`, each through its own generator |
| The fourth statement of which types are declared | `vinga-server/examples/README.md`, which is prose and is held by a case rather than generated |
| The committed body | `vinga-server/tests/unit/data/domain-bodies/provider/openai-asr-options.json`, written out rather than sparse |
| The changelog fragment | `changelog.d/500-openai-asr-options-model.md`, two entries under Changed |

### Deviations from the plan

None. The plan's M1 bullet names six options, the registration, the
builder rewrite, the temperature check staying in the builder, the
constant's deletion, the read-back pricing and the three generated
references, and each is in the table above.

One thing the plan allowed for did not turn out to be needed, which is
recorded as a discovery below rather than as a deviation: this type
needs no `_blank_reads_as_unwritten` list.

### Resolutions the plan left to this milestone

**Which spellings of absence the reader accepted, enumerated rather
than assumed.** Read off `registry.OptionsReader` call by call:

| Option | The call | Absent | `""` | `null` | An int where a float is read |
| --- | --- | --- | --- | --- | --- |
| `model` | `string(key, default)` | the default | passed on as a blank | answered None, which the builder's own assertion caught | refused |
| `base_url` | `string(key, default)` | the default | passed on, then refused by `parse_base_url` | as `model` | refused |
| `language` | `string(key)` | None | passed on, and falsey where the provider reads it | None | refused |
| `prompt` | `string(key)` | None | as `language` | None | refused |
| `temperature` | `optional_number(key)` | None | refused | None | taken as a float |
| `timeout_s` | `number(key, default)` | the default | refused | refused | taken as a float |

Every spelling in that table that built today builds now, which is
what the parity rows and the planted stored rows say between them.

**What is deliberately not preserved**, and it is in the changelog
fragment as a compatibility note: every stored `openai` ASR row the
model refuses is now a boot refusal, whether or not any agent names it.
The plan said the unknown-key half was already refused at build; the PR
review round corrected that and the plan carries the correction, so
this section states the wider fact rather than the narrow one it was
first written with. `finish()` runs inside a factory and a factory runs
only for a referenced entry (`providers/world.py::build_world` walks
`config.agents`), so before the declaration an unreferenced row could
hold anything: an unknown key, a null where a number belongs, a number
where a string belongs. All of them load-refuse now. And an unknown
option is no longer quoted back by name, which is the answer the three
types converted before this one already give.

### Discoveries

**A malformed code does not break the turn, and the plan's reason for
normalizing was wrong.** This is the correction the PR review round's
finding 3 forced, and it is worth stating plainly because the
milestone inherited the claim rather than inventing it: the plan said a
bad code would break event assembly in the middle of a transcribed
turn. It does not. The site hands `SessionEvents.emit` a thunk exactly
so that construction happens inside the guard, and that emitter's
docstring says so: "a construction failure is telemetry's problem
rather than the reply's". `_built` answers None and `emit` answers the
instant with nothing dispatched.

Measured, by taking the normalization back out and running the
malformed set: every case that carries a code leaves no `heard`
emission at any consumer and logs `construction_failed` on the session
channel, and the transcription itself answers normally. The suite
notices independently, which is worth recording: `tests/conftest.py`
fails any test whose run produced an event-schema refusal unless it
asked for the `refusals_are_expected` fixture, so the unnormalized path
is red twice over.

What a malformed code really costs is two things, and they are what the
prose now says. The turn loses its whole `heard` event, and with it the
duration, the `asr_ms` and the submitted audio that event carries,
because one optional far-side field was malformed. And the turn record
has no guard and no value type: `heard_utterance` assigns the string,
`conversations/store.py` writes it into a nullable `Text` column, and
the `/api` turn model publishes it as a bare `str | None`
(`config/responses.py`), so an unnormalized code reaches a durable row
and a read surface over it with nothing checking it on the way. The second half is not in the review's finding and is
the stronger of the two: a dropped event is a gap, a stored far-side
string is a value nothing downstream can tell from one this server
minted. Both are a poor price for a field whose absence means only that
the language was not learned, which is the claim the code, the plan and
this document now make instead of the one they made.

**This type needs no blank-spelling validator, and that is a property
of the reader rather than of the options.** Two of the other three
converted types carry `_blank_reads_as_unwritten` because their readers
ended an option with `or <default>` or read a section through a call
that answered an empty mapping for a missing key. This reader did
neither: every blank it accepted it passed ON, and a blank behaved as a
blank downstream (`model: ""` reached the request as an empty model id;
`language: ""` and `prompt: ""` are falsey where the provider reads
them, which is what absence does there). So the fields hold what was
written, and `test_this_asr_type_has_no_blank_spelling_of_an_absent_option`
asserts the values and `model_fields_set`, so a later hand adding the
list this type does not need fails rather than passes quietly.

**Four refusals moved and four did not, and the split is the design
read off a diff.** What moved to the shared validation rendering is
every fact about a VALUE: an option this type does not declare, and a
type the model refuses. What stayed in the builder is every fact about
the ENDPOINT or the environment: the missing key, the unset variable,
the `base_url` that cannot be classified, and the temperature range,
which is OpenAI's own and therefore conditional on the endpoint being
OpenAI. The characterization table was committed green first and then
watched changing, which is what made the split visible rather than
asserted.

**Declaring the type makes its example fragment a checked document.**
`test_every_documented_option_of_a_typed_type_installs` selects the
fragments whose `type:` is a declared one, uncomments every documented
key and installs the result, so `examples/asr-openai.yaml` joined that
set on this milestone. It passed unchanged, which is worth recording
because it is the case that would have caught a fragment documenting a
key the model does not declare.

**A factory-time refusal is not a boot-time refusal, which is what
the plan got wrong.** `OptionsReader.finish()` refuses an unknown
option, but only where a factory runs, and `build_world` builds only
the stages the configured agents reference. So the sentence the plan
carried, that such a row "cannot boot today either", held for a
referenced entry and for no other. Measured rather than argued: with
the declaration removed from the table, an unreferenced row holding
`beam_size: 1`, `timeout_s: null` and `language: 5` loads and hands
those three keys back. The plan now records the correction as a
correction, the changelog names the wider surface, and the refusal test
is parameterized across it, with the unknown key as the case that
proves the correction rather than the assumption.

**A declared type owes a committed body, and the suite says so
without being told which type.** `test_every_declared_type_has_a_body_of_its_own`
reads the declared set off the registry and holds it against the
fixtures under `tests/unit/data/domain-bodies/provider/`, so declaring
this type failed that case until the fixture existed. Worth recording
because it is the shape the #88 batch aimed for: the assertion travels
with the declaration rather than with a list somebody has to remember
to extend.

**A `ProvidersConfig` is not subscriptable.** The stored-row test was
first written as `providers["asr"]["ears"]` and the section is a model
with a field per stage, so the read is `providers.asr["ears"]`. Noted
because the failure names the type rather than the line's intent.

### PR review round, PR #512

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-13, runtime 6m58s, reviewing main...3384d3ee. Verdict
as received: **mergeable after the listed fixes**. Two findings, one
adopted whole and one adopted with a stated partial rejection, each
fixed in a commit of its own.

1. **P2: the upgrade notes and tests understate which legacy rows now
   block boot.** The plan claimed an unknown option "cannot boot today
   either" because `OptionsReader.finish()` refuses it at build time.
   False for an unreferenced entry: `providers/world.py::build_world`
   walks `config.agents` and resolves each agent's four stages, so a
   provider row no agent names was never constructed and `finish()`
   never saw it. Such a row booted. After this milestone every stored
   row is validated on read, so any model-invalid legacy `openai` ASR
   row is a boot refusal, not only the two nulls the changelog named.

   *Resolution.* Adopted, and the error was the plan's rather than the
   implementation's: the reasoning came from the plan's own amendment
   for the plan review's finding 10, which got the existence of the
   tightening right and its scope wrong. Corrected in `1e0aa98b` as a
   correction that quotes the sentence it replaces, since the plan is
   a record; the changelog fragment widened in `3f83f7df` to name
   every refused shape with the recovery path unchanged; and the
   stored-row test parameterized in `04d2fcbc` over seven cases
   (`model: null`, `base_url: null`, `timeout_s: null`, `language: 5`,
   `temperature: "warm"`, an unknown key, and a credential-shaped
   unknown key), each asserting what the refusal must say and each
   asserting the planted secret and the invented key name absent from
   the whole chain. Falsified by taking the declaration back out of
   `PROVIDER_TYPES`: six of the seven then fail with
   `DID NOT RAISE StorageError`, and the pre-milestone behaviour was
   reproduced directly, an unreferenced row holding `beam_size: 1`,
   `timeout_s: null` and `language: 5` loading and handing all three
   keys back.

   *Partial rejection, on one requested case.* The review asked for an
   unknown secret-shaped key as a case for the new gate. A
   credential-shaped key never reaches this type's model:
   `_check_no_inline_secrets` refuses it on `ProviderConfig` itself,
   which every type passes through before its own contract is
   consulted, so that row is refused identically with and without this
   milestone and is the one case of the seven that still passes when
   the declaration is removed. It is kept, because it proves the more
   dangerous rule reaches the row first and quotes nothing of it, but
   an ordinary invented key (`beam_size`) was added beside it and that
   is the case carrying the proof. The table's comment says so, so the
   credential-shaped case cannot later be read as evidence it cannot
   give.

2. **P3: the new no-leak test's docstring describes the opposite
   unknown-key policy.** It said an unknown key "is deliberately named
   back", which is the pre-conversion answer and the opposite of what
   this milestone establishes a few hundred lines above it, stale text
   carried across the move.

   *Resolution.* Adopted, fixed in `e7028896`. The docstring now says
   the sentinel is planted in a declared field's rejected value and
   points at the unknown-option case and the refusal table for the
   name-withholding half, naming the claim it replaces.

### Verification

Ruff, the unit lane, the integration lane, and the drift checks the
server workflow runs, each regenerated and diffed: the domain
reference, the server reference, the OpenAPI document, the CLI page
through its marker-preserving recipe, and the recipes inside it
against their own renderer.

One honest note about how the unit lane was run here. Serially it is
green (7260 passed, 19 skipped). Distributed the way CI runs it,
`-n auto --dist loadfile`, this machine's Postgres drops connections
under the worker count: every failure in those runs is
`psycopg.OperationalError: server closed the connection unexpectedly`,
the set differs run to run, none of it overlaps this milestone's
territory, and each one passes when re-run on its own. That is a fact
about this machine rather than about the change, and it is recorded
rather than presented as a green run.

The claims that
were made were watched failing first: `model: Nonblank` and a
non-optional `temperature` break exactly the parity rows and the
planted rows they are about, a base URL default of `/v2` breaks the
constant pin, a builder passing a literal model breaks the wire case,
and rewording the temperature refusal breaks exactly its row of the
characterization table.

## M2: report the language the model heard

`transcribe` fills `AsrResult.language` from the response's `languages`
list, where the request named no single language, and declines
anything that is not exactly one syntactically valid code.

### What landed

| Piece | Where |
| --- | --- |
| The hearing pair one request answers, transcript and language together | `vinga-server/src/vinga_server/providers/openai_asr.py`: `_Hearing`, returned by `_request` and by `_retry_without_prompt`, so the retry replaces both halves or neither |
| The suppression, derived from the value the request sent | the same module: `single` is computed once, put on the wire as `language`, and read back to decide whether a reported code is evidence |
| The normalization, asked of the type the code becomes | the same module: `_reported_language` and `_code_of`, answering None for every malformed shape |
| The module docstring's language paragraph, replaced by what the provider now does | the same module's docstring |
| The pins that say the new behaviour | `vinga-server/tests/unit/test_providers_openai_asr.py`: the filled case, the three suppressed cases, the blank that suppresses nothing, the empty list, the eight malformed shapes down the emission and record path, the retry's provenance and all five discarding outcomes |
| The two README claims this falsifies | `vinga-server/README.md`: the local engine's remaining wins, and the paragraph that said no language is reported |
| The example fragment's closing paragraph | `vinga-server/examples/asr-openai.yaml` |
| The changelog fragment | `changelog.d/500-asr-language-report.md`, one entry under Added |

### Deviations from the plan

None in substance. Two shapes differ from the plan's prose and neither
changes what is claimed:

- The plan lists the configured case and the hinted case as two tests.
  They are one parameterized case with three ids (`configured`,
  `hinted`, `both`), because the rule is one rule about what the
  request named and the third id is the combination the plan's
  precedence decision is about.
- Two tests are here that the plan's list does not name: the confirmed
  echo and the empty retry, each asserting that a discarded hearing
  answers no language. They are the other half of the provenance claim,
  and they were the cases that failed under the provenance mutation
  beside the recovered one.

### Resolutions the plan left to this milestone

**What "was told a single language" means, in terms the request can
answer.** The plan states the rule over what was SENT rather than over
what was configured, and that distinction has teeth here: a blank
`language` is a spelling M1 preserved, and the request has always put
no field on the wire for it. So the suppression is read off the value
the request actually carried, computed once as `single` and used twice,
rather than off `self._language` beside it. An entry with
`language: ""` therefore gets the report, which is correct, because the
model was told nothing.

The two spellings happen to coincide today, since
`pinned = self._language or language_hint` already collapses a blank to
None, and that is exactly why the case is pinned rather than left to
the reading: `test_a_blank_language_names_nothing_and_suppresses_nothing`
asserts both halves at once, that no `language` part is sent and that
the report survives, and a suppression written over the configuration
(`self._language is not None`) fails it along with the hinted case.

**Where the syntax check lives.** In the provider, and asked of
`LanguageTag` itself rather than of a pattern restated here.
`events/catalog.py::_named` already asks `EventName` the same way and
for the same reason: the value becomes that type downstream, so a
second expression of the rule is a bug pending. The catch is narrowed
to `EventValueError`, which is what that type raises and nothing else
does.

**How far the malformed cases are asserted.** Down the path production
takes: the event through `SessionEvents.emit` with the thunk
`runtime/pipeline.py` hands it, and the record through
`TurnUnderway.heard_utterance` beside it, which is the pair of calls
the pipeline makes in that order. Not through `assembly.heard` alone,
which is what this milestone first did and what the PR review round
corrected: the builder is not the deciding surface, the guard around it
is. See the discovery below for what a malformed code actually costs
and how it was measured.

### Discoveries

**The default model reports nothing, so M2 changes no unconfigured
deployment until M3.** The plan's measurement table says it and the
consequence only shows up in the prose: `gpt-4o-mini-transcribe`, still
the default here, answers no `languages` at all. So every page this
milestone edits says which models answer rather than promising a
report, and the code needs no rule for it: a response carrying no key
leaves the field empty through the same path a malformed one does.

**The report is a rate, not a verdict, and the honest example is the
unhinted one.** The plan's sharpest caveat, a two-hint request choosing
wrongly on a one-word clip, is about an option M4 adds, so quoting it
now would document something an operator cannot yet write. The caveat
that applies today is the issue's own failure: spoken German "Hallo"
transcribed `Hello.` and reported `en`, which is the report agreeing
with the mishearing rather than catching it. That is what the three
documentation surfaces say.

**The feature doc is not updated, and that is the taxonomy rather than
an omission.** `docs/features/2026-08-06-openai-asr.md` still says this
provider does not detect language.
[`docs/README.md`](../README.md) puts `features/` under dated execution
records, which "report what was true when they were written and are not
rewritten when the code moves on". The inventory that found it, and that
found nothing else outside the three pages this milestone edits and the
changelog:

```bash
git grep -n -E "reports which language|No language is reported|does not detect language|no usable language|language_detect|reports no language|language fields stay" -- '*.md' '*.yaml' '*.yml'
```

### Verification

Ruff, the unit lane and the integration lane, each run from
`vinga-server/`. No generated reference moves in this milestone: the
declaration and the default, which are what the three drift checks
render, are M1's and M3's.

Every claim was watched failing first, against four mutations of the
merged implementation:

| Mutation | What broke |
| --- | --- |
| Never report (`_Hearing(text, None)`) | the filled case and the recovered one |
| Report unconditionally (the suppression removed) | all three suppressed cases |
| The naive read (`reported[0]["code"]`) | all seven malformed shapes that carry a key, and the empty list. Down the production path each one loses its whole `heard` event to the emitter's guard, logs `construction_failed`, and lands the far side's string in the turn record, which is what the normalization is actually for |
| The language kept beside the text across the retry | the provenance case and both discarding ones |
| The suppression written over the configuration (`self._language is not None`) | the blank-language case and the hinted one |
| The retry's text recombined with the first hearing's language | the skipped, asyncio-timeout and SDK-timeout discards (added in the review round; the confirmed echo and the empty retry already failed under the mutation above) |

## M3: move the default model

The default transcription model becomes `gpt-transcribe`, alone, so the
one change every unconfigured deployment feels is reviewed by itself.
After M1 the default has one home, the `model` field's own `default=`,
so the code half is one line; the documentation half is the milestone.

### What landed

| Piece | Where |
| --- | --- |
| The default, on the field that owns it, with the comment and the description that argued for the model it replaced | `vinga-server/src/vinga_server/config/provider_options.py`: `OpenaiAsrOptions.model` |
| The pins that say what an entry sends, with and without a model of its own | `vinga-server/tests/unit/test_providers_openai_asr.py`: `test_the_model_on_the_wire_is_the_default_or_the_one_that_was_named`, two ids, and `tests/unit/test_provider_options.py`'s defaults case |
| The three generated references, each through its own generator | `docs/reference/domain-config.md`, `docs/reference/api-openapi.json`, `docs/reference/cli.md` |
| The maintained pages that described the old default | `vinga-server/README.md`: the options table, a new paragraph after the comparison tables, the language-hint paragraph and the language-report paragraph; `vinga-server/examples/asr-openai.yaml`: the model paragraph, the two claims about what pinning `language` does, and the report paragraph; and the module docstring's language paragraph |
| The changelog fragment | `changelog.d/500-asr-default-model.md`, two entries under Changed |

### Deviations from the plan

None in substance. One edit arrives a milestone early, deliberately and
recorded here rather than smuggled: the plan puts "neither spelling
pins a decode on this model" in M4's documentation footprint, beside
the option M4 adds. But the claim it corrects, the example fragment's
promise that naming a language "takes the question away from detection
outright", is a fact about the gpt-4o pair, so it becomes false for an
unconfigured deployment on THIS milestone rather than on M4. Correcting
it here is what keeps the page true after the change that falsifies it;
M4 still owns the paragraph about when to reach for which spelling,
which needs the option to exist.

The README gained one paragraph the plan's footprint does not name, for
the same reason: its four measurement tables are all of models that are
no longer the default, and a page whose only numbers describe something
an operator no longer gets by default is misleading without a sentence
saying so.

### Resolutions the plan left to this milestone

**What the example fragment's commented `model:` should be.** It showed
`gpt-4o-transcribe` as the interesting alternative to a default that
was its smaller sibling. It now shows `gpt-4o-mini-transcribe`, which
is the value that keeps exactly what a deployment had before this
milestone, and the changelog entry names the same one. A commented key
in a fragment is not decoration: `test_every_documented_option_of_a_typed_type_installs`
uncomments every one and installs the result.

**Whether `config.example.yaml` moves.** It does not: the file names no
transcription model anywhere, and the provider entries it documents
carry no `model` key for this stage. Checked by reading it rather than
inferred.

**Whether the cost section moves.** It does not, and the reason is
worth recording because the milestone's own facts pass close to it. The
table of definitions worth entering already carries `gpt-transcribe`
with its published per-minute price, and the bullet explaining that the
gpt-4o pair deliberately gets none is still true of those two models.
Nothing on that page said "the default" about either. What did change
is the accuracy of the accounting, which is a fact rather than an edit:
`gpt-transcribe` bills duration seconds where `gpt-4o-mini-transcribe`
bills audio tokens, and the `asr` span reports `submitted_ms`, so #502
M3's milliseconds-based cost accounting is now exactly right for the
default model rather than an approximation of it. No telemetry code
moved for that.

### Discoveries

**The existing default pin could not have caught this rename, and that
is the shape of a test that agrees with anything.** M1 left
`test_the_declared_default_model_is_the_one_on_the_wire`, which asserted
`form_field(request, "model") == OpenaiAsrOptions.model_fields["model"].default`.
That is the right claim about the builder, that it reads the field
rather than a constant, and no claim at all about the value: renaming
the default to anything keeps it green. The replacement names
`gpt-transcribe` on the wire and asserts the field equals that same
literal in the same case, so the builder claim survives with the value
claim beside it, and the second id, an entry naming `whisper-1`, is the
one that is independent of the default. That second id passed before
the default moved and after it, which is what says it measures the
override rather than the default.

**A description reaches two of the three generated documents in full.**
The CLI reference renders only a field description's first sentence
(`model: str  (default: "gpt-transcribe")` and then one line), where the
domain reference and the OpenAPI component carry the whole string. So a
description rewritten for an operator is read by two of the three, and
the sentence that has to survive the trim is the first one. Read off
this milestone's own diff rather than from the generator.

**The README's model measurements are all of models nobody gets by
default now.** Four tables, latency on the desk, latency on the board,
accuracy under white noise and accuracy in the room, every one taken on
the gpt-4o pair or `whisper-1`. A grep for the old model name does find
them, since they name it in their column headers, and that is exactly
what makes them the interesting case: a grep says the name is there and
says nothing about the tables being the page's only numbers, or about
the model they measure no longer being the one an operator gets. Read
as a page rather than as a set of matches, they are a section that
misleads without lying. The answer here is the honest one rather than
the impressive one: a paragraph saying the columns were not re-run
against the new default, and pointing at what IS known about it.

**M2's own changelog fragment says "until the default moves", and it
stays as written.** A fragment's text is final by contract, the fold
moves it byte for byte, and both entries land in the same dated section
where the M3 entry says the default moved. Amending a merged
milestone's fragment to keep a forward reference tidy would be editing
a record for style.

### PR review round, PR #514

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-13, runtime 5m22s, reviewing main...93bd1eb1. Verdict
as received: **mergeable after the listed fixes**. Three findings, all
P2, all adopted, each fixed in a commit of its own. They are one
failure repeated three times, which is worth naming rather than
numbering: a claim written one step wider than the evidence behind it.

1. **The hint-versus-pin claim was scoped to one model and the pages
   stated it generally.** Both pages said no model this type reaches
   treats `language` as a hard pin. Two measurements stand behind that
   sentence, the gpt-4o one this repository already carried and the
   plan's own on `gpt-transcribe`, which says "this model" and means
   it. Generalized, it also spoke for `whisper-1`, which nobody
   measured, and for every compatible endpoint, which this project
   cannot speak for at all.

   *Resolution.* Adopted in `3ba4ce3b`. Both pages now name the two
   measured models, date the new measurement, and say that the
   unmeasured cases decide for themselves. The advice does not move:
   pinning for a non-English deployment is still what the field session
   earned.

2. **"And nothing else" was false in this branch's own diff.** The
   fragment said pinning a gpt-4o model gives up the language report
   and nothing else, while the changelog beside it records a different
   billing unit and the README records that the new default's latency
   and accuracy were never compared against the old one's.

   *Resolution.* Adopted in `90136255`. The fragment says what naming
   `gpt-4o-mini-transcribe` keeps, whole: the same transcription, the
   measured latency and accuracy, per-audio-token billing, and no
   language report. The field's own comment carried the same over-claim
   in fewer words and was corrected with it.

3. **The changelog promised a language to configurations that suppress
   it.** It said a deployment that never set `model` starts carrying a
   language, while M2 suppresses the report on any request that named a
   single language, and the shipped fragment leaves `model` unset with
   `language: sv` active. Verified by running rather than by reading:
   an entry of exactly that shape sends `gpt-transcribe` with
   `language=sv` and answers `AsrResult.language` None, with the
   transcript intact.

   *Resolution.* Adopted in `2fbaddeb`. The entry now says the report is
   filled only where the request named no single language, names the
   shipped fragment as an entry that therefore reports nothing, and says
   what to leave unset to get one.

**The example fragment's `language: sv`, examined and kept.** The
review's third finding is also a question about the fragment, since
those two lines are the configuration most operators copy and they
teach the one combination in which M2's work does nothing. Kept active,
for a reason now recorded beside it: the pinning advice was earned on a
real device, where unpinned far-field Swedish came back as
English-shaped nonsense, and a wrong transcript costs a turn where a
missing report costs a number. A shipped example that taught the first
failure in order to buy the second would be a bad trade. What was
actually missing is that the trade was invisible at the line that makes
it, stated only in the closing paragraph a reader reaches last. So the
option now says it suppresses the report, says why it is set anyway,
and gives the one honest way to have both: comment it out for a while
on a deployment whose transcripts already look right, read the codes
that arrive, and pin afterwards. Nothing in the advice itself moved.

### Verification

Run from `vinga-server/` with `PYTHONDONTWRITEBYTECODE=1` outside
pytest. `uv run ruff check .` clean; `uv run mypy` clean; the unit lane
serially green (7283 passed, 19 skipped); the integration lane green
(341 passed);
and the five drift checks the server workflow runs, each with the
workflow's own recipe: the domain reference, the server reference
(regenerated and unchanged, which is the expected answer for a page
that renders no provider type), the OpenAPI document, the CLI page
through its marker-preserving rebuild, and the recipes inside it
against their own renderer. `scripts/check_doc_links.py` and
`scripts/fold_changelog.py check` both clean, and the command-spellings
census unchanged by the documentation edits.

The distributed lane (`-n auto --dist loadfile`) was not run. It fails
on this machine for a reason unrelated to any change, recorded in M1's
own verification: Postgres drops connections under the worker count and
every failure is `psycopg.OperationalError`. Not chased and not
claimed.

Every one of those was run again on the tree the review round left,
with the same answers: 7283 passed and 19 skipped, 341 passed, five
drift checks clean, links and fragments clean. The review's third
finding was settled by running rather than by reading, in a throwaway
case since deleted: an entry with no `model` and `language: sv`, the
shipped fragment's own shape, puts `gpt-transcribe` and `language=sv`
on the wire and answers a transcript with no language beside it.

Both claims were watched failing first, before the default moved: the
wire case reported `gpt-4o-mini-transcribe` where `gpt-transcribe` was
asserted, and the defaults case failed on the same string. The entry
naming `whisper-1` passed at that point too, which is the evidence that
the override case is not carried by the default.
