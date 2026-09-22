# An apply's provider-build refusal carries the sentence a boot prints: implementation

Companion to [`2026-09-22-apply-refusal-carries-boot-sentence.md`](2026-09-22-apply-refusal-carries-boot-sentence.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the apply refusal carries the provider-build sentence

An apply whose provider build refuses now answers with the sentence a
server started from the same store prints on stderr before refusing to
start, behind the prefix every refused reload opens with. The fixed
sentence that named four categories and withheld which one is gone.

### What landed

| Piece | Where |
| --- | --- |
| The refusal | `config/reload.py`: `_built` raises `ProviderRefusedError(f"{mcp.RELOAD_REFUSED} {exc}")`; `_PROVIDERS_REFUSED` and the comment block arguing for it are deleted |
| The shape that strips the chain | `config/reload.py`: unchanged, and now load bearing for a second reason. The message is taken as a string inside the `except` arm and the refusal raised after the arm has closed, which is what takes the chain off a `ProviderError` a factory raised from an SDK exception |
| The log line | `config/reload.py`: unchanged, the exception's class name as its one argument, with the comment saying why this surface is the stricter one |
| The docstrings that argued for the old rule | `config/reload.py` (`_built`), `config/loader.py` (`ProviderRefusedError`), `app.py` (`config_reloader`) |
| The contract the change rests on | `providers/base.py`: `ProviderError`'s docstring states that a message names identities and keys and never a stored value, and names the two surfaces that read it |
| The two steering refusals | `providers/openai_tts.py`: `check_steering` names the two option keys whose pairing is wrong instead of quoting the stored `model`; the `gpt-4o` prefix stays interpolated, because it is written in this repository |
| The route description | `config/api_descriptions/reload-refused.md`: which of the two classes the `detail` names a location for |
| The CLI reference | `docs/reference/cli.md`, "When an apply is refused": the compose half, the build half, and that `check` sees only the first because it builds nothing |
| The regenerated reference | `docs/reference/api-openapi.json`, through `uv run vinga-server config openapi`. One line moved, the reload route's 422 description, confirmed by parsing the regenerated document rather than by reading the diff alone |
| The changelog fragment | `changelog.d/487-apply-refusal-names-the-entry.md`, `### Changed`, two entries |

Tests, by claim. Everything in `tests/unit/test_config_reload.py` unless
said otherwise.

| Claim | Where |
| --- | --- |
| A typed option's key and entry are in the sentence and the value planted under it is in neither the sentence nor any rendering of the log | `test_a_typed_options_refusal_names_the_entry_and_the_key` |
| A boundary refusal names the entry and the key, in the boundary module's own sentence, and still chains nothing | `test_an_egress_refusal_leaves_the_running_engines_exactly_as_they_were` |
| An unknown type is refused by rule and by known-set, and the stored type is not quoted back | `test_an_unknown_type_is_refused_without_the_type_being_quoted` |
| A factory that raises is named by entry, type and exception class, and what the library said travels nowhere | `test_a_factory_that_raises_names_the_entry_and_its_class` |
| A `ProviderError` a factory raised from an SDK exception arrives with `__cause__` and `__context__` both `None`, so the sentinel two links behind it reaches nothing | `test_a_factory_raising_its_own_refusal_arrives_with_no_chain` |
| On the wire: the entry and the option key are in the 422 body, and the value written under that key is in neither the body nor any rendering of the log | `test_an_engine_that_will_not_build_names_the_entry_on_the_wire` |
| On the wire: an unset `api_key_env` names the entry and never the reference | `test_an_unset_key_reference_names_the_entry_and_not_the_reference` |
| The warning's argument tuple is the class name alone | `refused_class`, asserted by five of the cases above |
| The two steering refusals are exactly their new sentences and hold no model name | `tests/unit/test_providers_openai_tts.py`, three pins |

### The mutation runs

Every inverted `in` assertion fails against the pre-change tree by
construction, and all of them were watched failing before `_built`
moved: seven cases red in `test_config_reload.py`, six in
`test_providers_openai_tts.py` (three cases, one of them parametrized
over four base-url spellings). The `not in` assertions need a mutation,
and three were performed, watched and reverted.

| Mutation | What caught it |
| --- | --- |
| `registry.py`'s options-model arm interpolating the rejected options: `raise ProviderError(f"{refused} (got {config.options!r})")` | `test_a_typed_options_refusal_names_the_entry_and_the_key` alone, 1 failed 45 passed |
| `OptionsReader.finish` interpolating each unknown option's value beside its name | `test_an_engine_that_will_not_build_names_the_entry_on_the_wire` alone, 1 failed 45 passed |
| `_built` raising `ProviderRefusedError` inside the `except` arm instead of after it | Five cases, 5 failed 41 passed. The pass-through case caught it at `__context__ is None`, which is the link that leads to the SDK exception's sentinel through the `ProviderError`'s own `__cause__` |
| `openai_tts.check_steering` quoting the stored model, which is the pre-change sentence | The three exact-message pins, 6 failed 30 passed |

No mutation survived a test.

### Deviations from the plan

Five, two of them corrections of the plan and three of them placement.

- **The typed-option case does not drive the option readers.** The plan
  says it drives "`registry.py`'s option readers (one composition
  shape, eight sites)". It does not: `faster_whisper` declares an
  options model, so `beam_size` is refused by `validated` and the
  sentence is composed by `config/provider_options.py` and raised at
  `registry.py`'s options-model arm. Measured rather than assumed. The
  reader shape is driven all the same, by the wire case, whose planted
  entry is of type `mock`, which declares no options model and
  therefore refuses through `OptionsReader.finish`. The corrected site
  map is below.
- **`beam_size` is not asserted to be in the log.** The plan's
  typed-option bullet says the key "is in the sentence and in the log",
  which contradicts the section two pages above it and the resolution
  of the review's finding 1: the warning keeps its shape and the
  sentence travels in the answer only. The argued and review-accepted
  position was taken, and what is pinned instead is the warning's
  argument tuple, which is the mechanism that same section names.
- **The `api_key_env` case lives in the file's wire section** rather
  than beside the rotation cases. It is a route case driven through
  `entered_client` and a POST, which is what the plan asks for; the
  section it sits in is the one about what an entry that will not build
  says on the wire, and it reuses that section's `voiced` helper and
  planted entry name instead of growing a second copy of them.
- **Seven cases rather than six, and two of them on the wire.** The
  pre-existing route case asserted that the entry and the option name
  reach nothing, so it had to invert whatever else happened; inverting
  it is the cheapest honest thing to do with it, and it then proves the
  wire for the unknown-option class while the `api_key_env` case proves
  it for the stored-credential class.
- **Separate test functions rather than one parametrized world per
  class.** The classes do not assert the same thing: the boundary
  refusal is composed over no stored value at all, so there is no
  sentinel to plant in it, and the two wire cases assert on a response
  body where the rest assert on an exception. A parametrized shape would
  have carried an unused sentinel field and two unused branches.

### The corrected site map

Which `raise ProviderError(` site each case actually drives, replacing
the plan's list. Driven:

| Case | Site |
| --- | --- |
| Typed option | `registry.py`'s options-model arm, the one that re-raises an `OptionsRefused` |
| Unknown option, on the wire | `OptionsReader.finish`, which is the reader composition shape |
| Boundary | `world.py`'s wrapping of a `BoundaryRefusal` |
| Unset `api_key_env` | `kit.py`'s `resolve_api_key` |
| Factory that raises | `registry.py`'s sanitizing wrapper |
| Factory that raises a `ProviderError` | `registry.py`'s pass-through arm |
| Unknown type | `registry.py`'s type lookup |

Inventoried only, and read line by line rather than counted: the
string, required-string, number, integer, boolean, numbers and mapping
readers (the same composition shape as `finish`), the missing-extra
refusal, the invalid-provider-object refusal, `openai_endpoint.py`'s
`base_url` and API-key rules, `openai_asr.py`'s temperature range,
`openai_tts.py`'s speed range and its two steering refusals,
`elevenlabs_tts.py`'s API-key rule, and `world.py`'s missing-stage
site.

### Discoveries

- **The inventory is 24 and every line is value-free.** Re-run on this
  tree and read in full, not counted. Each sentence interpolates one of:
  the entry label, an option's own key, a rule constant written in this
  repository (a range, an example URL, an extra's name, the known-types
  list), a provider type the registry had already recognized, a failed
  factory's class name, an identity through `models.spoken_identity`, or
  a sentence another module of this repository composed. The two
  `openai_tts.py` steering refusals were the exception and this
  milestone is what fixed them.
- **An options-model refusal's `detail` is multi-line.** It is the
  headline plus one indented line per field problem, which is what a
  boot prints, and it now reaches the 422 body in that shape. Nothing
  downstream objects, and the alternative would have been to reformat a
  sentence this change exists to carry verbatim.
- **A stored entry that will not build cannot be planted before the
  boot reads it.** The `api_key_env` case writes its entry into the
  store after `entered_client` has entered, because an entry present at
  boot refuses the boot instead of the apply. The pre-existing wire case
  makes the same move through the API; this one goes to the store
  directly, since the write path would have its own opinion about a
  reference to a variable nothing sets.

### PR review round, PR #547

External review of [#547](https://github.com/rafacm/vinga/pull/547)'s
diff: codex CLI 0.155.1, model gpt-5.6-sol, read-only sandbox,
2026-09-22, runtime 2m23s, reviewing `origin/main...6826ff82`. Verdict
as received: **mergeable after the listed fix**. One finding, a P2,
adopted.

It is the milestone's own error committed inside its fix, and of a
shape this repository has a name for: prose claiming more than was
measured. The sweep had just demonstrated two classes of refusal that
do not fit the sentence the documentation was written around, and the
documentation was written anyway.

1. **P2: public references promise an option key for refusals that have
   none.** `docs/reference/cli.md` and
   `config/api_descriptions/reload-refused.md` both say a provider-build
   refusal names "the entry, the option key and the rule". The
   unknown-type refusal this milestone's own sweep drives has no option
   key, and the factory-failure refusal names the entry, the provider
   type and the exception's class instead. The generated OpenAPI
   document repeats the guarantee to every reader of the API. Concrete
   fix: describe the answer as naming the entry and the applicable
   key, type, rule or failure class, regenerate
   `docs/reference/api-openapi.json`, and make the same qualification in
   the affected docstrings.

   *Resolution.* Adopted whole, in `ac23af82`. All four public
   sentences and all four docstrings now say the entry, and with it
   whichever that particular refusal has of an option key, a type this
   deployment declares, the rule that was broken, or the class of the
   exception a factory raised, with the point stated explicitly that
   which of them appear is the refusal's own to say and that none of
   them is ever a stored value, an unrecognized provider type included.

   Two places beyond the finding's list carried the same over-claim and
   moved with it, both found by grepping the milestone's own spellings
   rather than by rereading the files the finding named: the two
   section comments in `tests/unit/test_config_reload.py` that state the
   sweep's claim, and the changelog fragment, whose headline promised
   "which entry, which key and which rule refused". No assertion
   changed, so nothing about what is proven moved; what moved is only
   what was claimed. `providers/base.py`'s `ProviderError` gained one
   further correction of the same kind while it was being reworded: the
   identity a refusal names is the entry's label at every site but the
   one that refuses a stage nothing binds, where it is the agent's name.

   Verified: `docs/reference/api-openapi.json` regenerated through
   `uv run vinga-server config openapi`, one line moved and the new text
   parsed back out of the document to confirm it sits on
   `/runtime/config/reload` `post` `422` and nowhere else;
   `uv run ruff check .`, `uv run pytest tests/census -q` (66 passed),
   `python3 scripts/check_doc_links.py .` (261 files, 0 failures),
   `scripts/fold_changelog.py check` (1 fragment, 0 failures), and the
   four touched unit suites (151 passed).
