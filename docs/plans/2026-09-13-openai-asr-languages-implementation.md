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
fragment as a compatibility note: `model: null` and `base_url: null`
never built, but their refusal arrived when a provider was
CONSTRUCTED, so a row nothing referenced sat unread in the database;
the declaration moves that to load time, where it is a boot refusal for
the whole configuration. And an unknown option is no longer quoted back
by name, which is the answer the three types converted before this one
already give.

### Discoveries

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

**A `ProvidersConfig` is not subscriptable.** The stored-row test was
first written as `providers["asr"]["ears"]` and the section is a model
with a field per stage, so the read is `providers.asr["ears"]`. Noted
because the failure names the type rather than the line's intent.

### Verification

Ruff, the unit lane, the integration lane, and the three drift checks
the server workflow runs, each regenerated and diffed. The claims that
were made were watched failing first: `model: Nonblank` and a
non-optional `temperature` break exactly the parity rows and the
planted rows they are about, a base URL default of `/v2` breaks the
constant pin, a builder passing a literal model breaks the wire case,
and rewording the temperature refusal breaks exactly its row of the
characterization table.
