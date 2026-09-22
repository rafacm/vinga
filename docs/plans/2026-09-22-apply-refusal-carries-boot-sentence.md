# An apply's provider-build refusal carries the sentence a boot prints

Plan for [#487](https://github.com/rafacm/vinga/issues/487), as re-cut
on 2026-09-22. Its companion is
`docs/plans/2026-09-22-apply-refusal-carries-boot-sentence-implementation.md`,
one section per milestone, appended in the same change that ticks the
milestone.

**Local baseline:** not applicable. A refusal's wording changes no
conversational capability.

**Cheapest alternative:** none. This is the one-function change. The
four-milestone vocabulary the issue carried until the re-cut (a bounded
name type, closed failure tokens, a problem-type transport, per-surface
display rules) was the expensive alternative, and the re-cut recorded on
the issue why each of its parts is either already in the tree under
another name or aimed at a harm its surface cannot suffer.

## Goal

An operator whose `apply` is refused because a provider would not
build learns from the answer which entry, which key and which rule
refused, in the words a server started from the same store would print
before refusing to start. Today the answer is
`_PROVIDERS_REFUSED` in `config/reload.py`: the four categories of
thing that could have refused, a sentence saying which is withheld, and
an instruction to start a second server. `check` was added for the
compose-time refusals (#443) and deliberately builds no provider, so
this is the one class of stored-state refusal that neither the answer
nor `check` diagnoses.

## What is settled and not re-litigated

- **The sentence is the provider layer's own.** `_built` in
  `config/reload.py` catches a `ProviderError` whose message a boot
  prints verbatim on stderr (`serving.py`, the `ConfigError,
  ProviderError` arm) and substitutes the fixed sentence. After this
  plan it carries the message. No new vocabulary, no token, no second
  composition.
- **Values stay out; identities and keys go in.** The issue's audit of
  every `ProviderError` raise site (24 today, backed by the grep in
  Verification) found each sentence interpolates one of: the entry
  label, which `config/entities.py::provider_label` composes and
  `models.spoken_identity` escapes; the option reader's own `key`
  argument, which is code; an unknown key, spoken through the strip; a
  provider type the registry has already recognized (the unknown-type
  refusal says the type is not quoted back); the server's own data
  boundary; a factory failure's class name. The exception is
  `providers/openai_tts.py`, whose two model-shape refusals quote the
  stored `model` option verbatim, and this plan fixes them.
- **The problem-type token is #488 M4's**, where its one consumer is.
  Exception class names stay on the event surface. Neither is touched
  here.
- **`check` keeps its scope.** The re-cut asked whether `check` should
  grow a provider-build phase once the answer is actionable. It should
  not: `check` is the boot's read and stops before anything is built,
  which its docstring lists as what it does not do, and a provider
  build loads local models and opens network clients. The answer now
  covers the gap `check` was leaving, and the CLI reference says which
  refusals each one diagnoses.

## The smaller decisions

### The sentence keeps the reload's prefix

`ProviderRefusedError` carries `f"{mcp.RELOAD_REFUSED} {exc}"`: the
prefix every refused reload already opens with ("the reload was refused
and nothing was changed:"), then the provider layer's sentence. The
shape is the one `_read` in the same module composes for a compose
refusal, so the two phases of one apply refuse in one voice, and the
prefix is what tells an operator reading the answer that nothing was
swapped, which the provider sentence alone does not say.

### Composed after the handler closes, as today

`_built` keeps its shape: the message is taken inside the `except` arm
as a string, and the typed refusal is raised after the block, so
`__cause__` and `__context__` stay `None`. The existing pins on both
stay byte-unchanged. What the arm holds is a `ProviderError` whose
message is value-free by the audit above; what it must not hold is the
chain behind it, since a factory that raised inside the provider layer
may have been holding an SDK exception, and `registry.py` already
reports that by class name only.

### The log line stays class-only

The warning keeps naming the exception class and nothing else. The
retained log is the strictest of the surfaces this refusal touches:
the observability surfaces page says structured events carry no
exception prose, and `logs.py` renders an ordinary record into that
same retained JSON log. A boot's stderr and an API answer are the
sanitized diagnostic channels; the log is metadata. So the sentence
travels in the answer and nowhere else, and the sentinel test pins the
warning's argument tuple as the class name alone, so a later edit that
adds the sentence as an argument is a red test rather than a review
finding.

### The two `openai_tts.py` refusals name the option, not the model

`model "{model}" ignores option "speed"; describe the pace in
"instructions" instead` becomes `option "speed" is ignored by the
model named by option "model"; describe the pace in "instructions"
instead`, and the `instructions` sentence becomes `option
"instructions" is ignored by the model named by option "model"; it is
read by the gpt-4o speech models, and "speed" is what this
one takes` (the prefix constant stays interpolated, as today). A model
name is a stored option value, and the rule for this surface is that a
refusal names the key and never the value; quoting the model was the
one place the surface broke it. The three existing `match=` pins on
the trailing substring are replaced by exact-message assertions, so a
degraded wording is caught and not only a leak, and each gains an
assertion that the configured model string is absent.

### Words that become false, and where they live

Five places state that the answer names no location, and each moves in
this milestone:

- `_built`'s docstring and the comment inside its `except` arm
  (`config/reload.py`).
- `ProviderRefusedError`'s docstring (`config/loader.py`), which says
  the entry, type and option are "stored values that a refusal over
  HTTP must not carry".
- `config_reloader`'s docstring (`app.py`), which calls it "the apply's
  own fixed sentence".
- The `reload-refused` route description
  (`config/api_descriptions/reload-refused.md`), which says the
  `detail` is fixed and names no location and lists an unbuildable
  engine among the reasons; after this plan the compose-time reasons
  keep that sentence and the provider-build reason names its location.
  This is a generated-reference input, so `docs/reference/api-openapi.json`
  is regenerated through `uv run vinga-server config openapi`.
- The "When an apply is refused" section of `docs/reference/cli.md`,
  which now says two things: a stored half that will not compose is
  refused without a location and `check` is where the location is
  said; a stored half whose provider will not build is refused with the
  location in the answer, in the sentence a boot would print, and
  `check` will not see it because it builds nothing.

## Design footprint

One module deepened, `config/reload.py`: its callers stop having to
know that a refused build's diagnosis lives in a second server's
stderr. No seam is added and no module is created. `providers/base.py`'s
`ProviderError` docstring gains the contract this plan relies on, that
a message names identities and keys and never a stored value, so the
next raise site reads the rule where the type is declared.

## Documentation footprint

- `docs/reference/cli.md`, the "When an apply is refused" section
  (hand-written reference prose per the authority taxonomy in
  `docs/README.md`).
- `docs/reference/api-openapi.json`, regenerated.
- `changelog.d/487-apply-refusal-names-the-entry.md`, `### Changed`.
- Nothing under `docs/architecture/`: the observability surfaces page
  lists the API body as a sanitized channel and says nothing about this
  sentence. The root README makes no claim about apply refusals.

## Tests

The claim is one sentence long, so the proof is a sentinel sweep and
not a new test module. Stated at its true width: **for each
representative refusal class of the provider-build surface, a stored
world whose values carry a credential-shaped sentinel is refused with a
`detail` that names the entry, the key and the rule, and the sentinel
reaches neither the answer nor the log.** The sweep is a regression
proof for the composition sites it drives; the whole-surface claim
rests on the manual inventory of all 24 raise sites named under
Verification, read line by line, and the plan does not call six cases
an automated proof of the other eighteen. The sites each case drives:
the typed-option case drives `registry.py`'s option readers (one
composition shape, eight sites); the boundary case drives
`boundary.py`; the `api_key_env` case drives `kit.py`; the two factory
cases drive `registry.py`'s wrapping and pass-through arms; the
unknown-type case drives `registry.py`'s type lookup. Not driven and
inventoried only: the unknown-option, required-string and mapping
readers (the same composition shape as the typed-option case), the
missing-extra refusal, the `openai_endpoint.py` and `openai_asr.py`
range and shape rules, the invalid-provider-object refusal, and
`world.py`'s missing-stage and boundary-wrapping sites.

The classes, with the asset each reuses (all in
`tests/unit/test_config_reload.py` unless said otherwise):

- **An option of the wrong type.** The existing typed-options case
  plants a sentinel as `beam_size` and asserts that neither the value
  nor the key travels. The key assertion inverts: `beam_size` is in the
  sentence and in the log, the sentinel is in neither, and the chain is
  still empty.
- **A boundary refusal.** The existing `reach: host` case asserts
  `voice` is absent from the sentence. It inverts: `providers.tts.voice`
  is named, and the sentence is the boundary module's own.
- **An unset `api_key_env`.** New case beside the rotation cases:
  `api_key_env` naming a variable that is not set, with a sentinel as
  the variable's name, so the answer names the entry and not the
  reference, which is the rule `kit.py` states.
- **A factory that raises.** The mock that refuses to build is what
  `tests/integration/test_startup_failure.py` pins the boot sentence
  with (`providers.llm.mock: the mock provider would not build
  (ValueError)`); the same construction raises with a sentinel in its
  message, and the answer carries the class name and not the words.
- **An unknown type.** A stored type spelled as a sentinel, refused
  with the type not quoted back.
- **A factory that raises a `ProviderError` of its own, from an SDK
  exception.** `registry.py` passes a factory-raised `ProviderError`
  through unchanged (`except (ProviderError, ConfigError): raise`),
  which `test_providers.py` pins as intentional, so such an error
  reaches `_built` carrying whatever it was raised `from`. The case
  registers a factory that raises a value-free `ProviderError` from an
  SDK-like exception whose message holds the sentinel, applies, and
  asserts the refusal's `__cause__` and `__context__` are `None`, the
  sentinel is absent from the answer and from every record rendering,
  and the value-free sentence is what the answer carries. This is the
  case that proves `_built`'s delayed string extraction is what strips
  the chain, rather than assuming it.

Absence from the log is asserted over
`tests.support.leaks.renderings(caplog)`, never over `caplog.text`
alone: both shipped formatters call `record.getMessage()`, which hides
an argument the message did not use, and `renderings` renders every
record three ways, both formats and the object behind them
(`record.__dict__`, `record.args`, the exception fields). The same
sweep pins the warning's `args` as the one-tuple of the class name.

One of these runs through the API (`entered_client` and a POST to the
reload route, as the rotation cases do), asserting on
`refused_body(...)` and `refused.text`, so the sentence is proven on
the wire and not only on the exception. The rest run at
`ConfigReload.apply()` where the existing cases live, since the route
passes `ProviderRefusedError` through unchanged (`app.py`,
`config_reloader`) and the wire case proves that once.

**Falsify before claiming.** Every inverted `in` assertion fails
against the current tree by construction and is watched failing. The
`not in` assertions need a mutation: one sentence in `registry.py`
temporarily interpolates the rejected value, and the sweep is run to
show which case catches it; the mutation is reverted, and the commit
body says the check was done. The `openai_tts.py` pins are mutated the
same way, by restoring the quoted model.

## Risks

- **A future raise site quotes a value.** The sweep covers the classes
  the surface has today, not a site written tomorrow. Mitigation is
  the contract in `ProviderError`'s docstring and the sweep's shape,
  which is one parametrized world per class and cheap to extend; the
  reach-in census and the sentinel lens in review are what catch the
  next site, as they caught `openai_tts.py` in the re-cut.
- **The CLI reference edit stales the command-spellings census.** The
  section quotes `vinga-server config check`; the edit must not start
  or stop quoting a command without regenerating the manifest. Run
  `tests/census` after the edit.
- **The regenerated OpenAPI document moves more than the one
  description.** It should not, since only `reload-refused.md` changes;
  the milestone diffs the regenerated file and reports anything else
  that moved rather than committing it unread.

## Milestones

- [ ] **M1: the apply refusal carries the provider-build sentence
  (PR TBD).** `_built` raises `ProviderRefusedError` with the reload
  prefix and the `ProviderError`'s message, the log line carries the
  message beside the class name, `_PROVIDERS_REFUSED` and the four
  docstrings and comments that argue for it move to the new rule, the
  two `openai_tts.py` refusals stop quoting the model, the sentinel
  sweep above lands with its inverted pins, the `reload-refused`
  description and the CLI reference say which refusals each surface
  diagnoses, the OpenAPI document is regenerated, and the changelog
  fragment records the changed answer. Design footprint: `config/reload.py`
  deepened; no new module. Documentation footprint: as listed above.

## Verification

- `uv run ruff check .`, `uv run pytest tests/unit -q`,
  `uv run pytest tests/integration -q`, `uv run pytest tests/census -q`,
  all from `vinga-server/`.
- The raise-site inventory the settled decision rests on, run untruncated:
  `grep -rn "raise ProviderError(" src/vinga_server/providers | wc -l`
  is 24 at `19f7122e` (the plan's earlier 25 counted the class definition in
  `providers/base.py`, matched by a grep on `ProviderError(` without
  the `raise`; no site was added or removed). The milestone re-runs
  the command and reads every line rather than the count, which is
  the inventory and not the proof.
- `uv run vinga-server config openapi > ../docs/reference/api-openapi.json`
  and a diff showing only the reload route's description moved.
- The mutation runs named under Tests, stated in the commit bodies.

## Plan review round

Reviewed 2026-09-22 by codex (`codex-cli 0.155.1`, model `gpt-5.6-sol`,
read-only sandbox, 193 s) at commit `19f7122e`. Six findings, verdict
"ready after the P1/P2 amendments". Condensed but faithful.

1. **P1: the warning prose would violate the retained JSON-log
   contract.** The plan adds the whole `ProviderError` sentence as a
   logging argument. `observability-surfaces.md` says structured events
   carry no exception prose, and `logs.py` renders ordinary records
   into the retained JSON log. Boot stderr and an API response are
   sanitized diagnostic channels; the retained log has the stricter
   metadata-only contract, and the issue asks for the sentence in the
   refusal, not in the log. Keep the warning class-only, exactly as
   today, and drop the "one diagnosis, three surfaces" claim.

   *Resolution*: accepted. The section is rewritten as "The log line
   stays class-only": the warning keeps its shape, the sentence
   travels in the answer only, and the sweep pins the warning's
   argument tuple as the class name alone.

2. **P2: the log sentinel assertion does not inspect the retained
   `LogRecord` arguments.** The existing pins use `caplog.text`, and the
   `logged()` helper adds only the shipped formatter output; both
   formatters call `record.getMessage()` and can hide unused or
   transformed arguments. `tests/support/leaks.py` documents this trap
   and inspects `record.__dict__`, `record.args` and the exception
   fields. Require `tests.support.leaks.renderings(caplog)` or an
   equivalent, and if finding 1 is accepted, pin the warning's argument
   tuple as class-name-only.

   *Resolution*: accepted. The Tests section requires
   `tests.support.leaks.renderings(caplog)` for every log assertion in
   the sweep, and the warning's `args` tuple is pinned.

3. **P2: the factory case misses the pass-through path for a
   `ProviderError` with a chain.** `registry.py` reconstructs a
   chainless `ProviderError` from an ordinary factory exception, but
   its `except (ProviderError, ConfigError): raise` passes a
   factory-raised `ProviderError` through unchanged, which
   `test_providers.py` confirms is intentional. The plan's factory case
   exercises the sanitizing wrapper, not a `ProviderError` carrying an
   SDK exception in its chain. `_built`'s delayed string extraction
   should remove that chain, but nothing proves it. No `ExceptionGroup`
   construction exists on the sequential `build_world` path. Add an
   apply-level case whose factory raises a safe `ProviderError` from an
   SDK-like exception holding the sentinel, and assert the chain is
   empty and the sentinel absent from the response and from every
   record representation.

   *Resolution*: accepted. A sixth case is added under Tests, a
   factory raising its own `ProviderError` from an SDK-like exception,
   asserting the empty chain and the sentinel's absence from the
   answer and every record rendering.

4. **P2: the 25-site inventory is stale and its verification command
   cannot pass.** At `19f7122e` the exact command yields 24. Record the
   current baseline, explain the difference if material, and require
   reading the full output rather than treating the count as the proof.

   *Resolution*: accepted. The count is 24 at `19f7122e`; the 25 came
   from a grep on `ProviderError(` that matched the class definition,
   not from a site that has since gone. Both places in the plan now
   say 24, and the verification names the full output as the
   inventory.

5. **P2: five category tests are not the promised whole-surface
   sweep.** The 24 sites also include unknown option names, missing
   required strings, a malformed `base_url`, a missing extra,
   model-specific range rules, an invalid provider object, a missing
   stage binding and provider-marking failures. The registry mutation
   proves detection at one composition site only. Either give a
   site-to-test matrix covering every raise composition, including the
   pass-through path, or narrow the claim to representative category
   regression tests plus a manual inventory. Do not call five cases a
   whole-surface automated proof.

   *Resolution*: accepted, by narrowing. The Tests section now states
   the claim at its true width, names which raise sites each case
   drives and which are inventoried only, and the whole-surface claim
   rests on the 24-line inventory read in full.

6. **P3: the replacement `openai_tts.py` sentence is malformed.**
   `the model option "model" names ignores option "speed"` is not
   grammatical and the existing pins match only the trailing
   substring, so they would not catch it. Specify a value-free sentence
   such as `option "speed" is ignored by the model named by option
   "model"; describe the pace in "instructions" instead`, with an
   exact-message assertion beside the absence check.

   *Resolution*: accepted. Both sentences are specified in full and
   the three pins become exact-message assertions beside the absence
   check.
