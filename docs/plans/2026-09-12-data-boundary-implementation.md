# A declared data boundary with a network tier: implementation

Companion to [`2026-09-12-data-boundary.md`](2026-09-12-data-boundary.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions of
the plan's open questions, and discoveries.

## M1: the vocabulary cutover

### Deviations

Five, each with its reason.

**1. The final grep's allowlist is wider than the plan's, and could not
have been narrower.** The plan says the `egress` and `local_only`
tokens "may remain only in `docs/plans/`, `docs/features/` and
`CHANGELOG.md`; any other hit is a missed site". No implementation that
REFUSES the old spellings by name can satisfy that: the refusal
sentence has to contain the word, the migration has to name the key it
translates, and the tests that prove both have to write it. The
allowlist is therefore the plan's three paths plus the places where the
withdrawn word is the SUBJECT of the sentence rather than a live
spelling, enumerated by file and line below so the distinction is
checkable rather than asserted.

**2. The exceed refusal is two sentences rather than one.** The plan
gives one example for "the marked case" and says every sentence may
name the boundary's value. A reach that exceeds the boundary can come
from the class marking or from the operator's `reach` key, and the two
have different remedies: no key on the entry can change a type's own
marking, while an operator's assertion is edited on the entry. So
`check_provider` raises `type "{type}" reaches the {marked}, but this
server's data boundary is {boundary}` for the first (the plan's own
example, and the reach named there is a fact written in this
repository's source) and `this entry declares a "reach" outside this
server's data boundary, which is {boundary}; narrow the entry's reach,
or widen the boundary` for the second, which names no value read from
the entry at all. That keeps the plan's "never a value read from an
entry" literally true and says which key to edit.

**3. The closed-set check refuses a bare `"host"` as well as `0`.** The
plan asks for "the closed-set identity check refusing anything outside
`{host, network, internet, None}`". A `StrEnum` member compares and
hashes equal to its own value, so a class body that wrote `reach =
"host"` would rank correctly through the table today and go on doing so
until the set grows a member spelled differently somewhere. The check
is `isinstance(marking, Reach)`, and the third case is pinned.

**4. The `cli-respelling.txt` fixture was edited rather than
recaptured.** The plan says it "regenerates through its own harness".
Its harness is `VINGA_CAPTURE_RESPELLING=1`, which recaptures the WHOLE
transcript and would bake today's behavior into a record deliberately
captured before the #223 rename. Exactly two lines of it are the old
key (`egress: false`, twice, in the `mcp-server-show` and
`prompt-fragment-show` steps), so the input `_MCP` fragment and those
two lines moved to `reach: network` and nothing else in the transcript
did. The differential still compares the old record against the new
grammar, which is the property the file exists for.

**5. The domain migration test is its own file.** The plan says "in the
`test_domain_upgrade.py` house pattern". It is that pattern, in
`tests/integration/test_reach_upgrade.py`, because `test_domain_upgrade.py`
seeds at `3001_postgres_domain` for its own subject and this one seeds
at `3003_device_record`; `test_device_record_upgrade.py` is the
precedent for one file per migration.

### The final grep and its allowlist

The check, run from the checkout root:

```bash
git grep -nIw -E 'egress|local_only' -- . ':!docs/plans' ':!docs/features' ':!CHANGELOG.md'
```

Word-boundary matching (`-w`), so "regression" cannot match and the
rule is mechanical. Fifty-one lines remain, in seven files, counted at
this milestone's last commit, and every one of them is a place where
the withdrawn word is what the line is about:

| File | Lines | Why it stays |
| --- | --- | --- |
| `changelog.d/493-data-boundary.md` | 3, 4 | The release note, and the plan's allowlist already exempts `CHANGELOG.md`, which this file becomes byte for byte when the fold runs on `main`. Naming the old spelling is the whole job of the entry: an operator reads it to learn what to change their file to. |
| `vinga-server/README.md` | 2103, 2105, 2107, 2109 | The upgrade note the plan asks for: a file is the operator's to edit, so the old spelling has to be named to say what it becomes. |
| `vinga-server/src/vinga_server/boundary.py` | 11, 20, 24, 242 | The module docstring's history paragraph, which the plan asks to keep with the rename recorded, and the note on the deleted MCP guard. |
| `vinga-server/src/vinga_server/config/models.py` | 2255, 2261, 2263 | `REPLACED_PROVIDER_KEY`, its refusal sentence, and the comment saying why the rejection lives at the `ProviderConfig` boundary. The constant IS the string `"egress"`. |
| `vinga-server/src/vinga_server/db/migrations/versions/3004_reach_replaces_egress.py` | 1, 7, 19, 21, 22, 26, 35, 58, 84 | The migration's docstring, its `OLD` constant, and the arm that tells JSON null from every other value. It translates the key, so it names it. |
| `vinga-server/tests/integration/test_reach_upgrade.py` | 6, 49, 65, 66, 67, 72, 73, 74, 80, 185, 198, 249, 255, 273, 339, 342, 369 | The pre-upgrade row bodies, including the malformed shapes, and the assertions that no row keeps the key. |
| `vinga-server/tests/unit/test_providers_boundary.py` | 133, 443, 450, 457, 461, 484, 500, 504, 525, 531, 558, 566 | The old-spelling refusal cases, at the write path and at the model, and one comment. |

Nothing else in the tree carries either token. `docs/reference/` is
generated and came out clean by construction; the committed SVG was
re-rendered and carries neither word. This document and the plan beside
it are excluded by the command, which is the plan's own rule and the
reason the numbers above do not move when this section is edited.

### Discoveries

**The provider-options trap is worse than "a stray option".** The plan
names it, and driving it made the shape concrete: `ProviderConfig` is
`extra="allow"`, so a stale `egress: false` does not fail anywhere. It
becomes a provider option, and a builder that reads its options through
a model ignores what it does not declare, so the operator is left
believing a declaration nothing enforces. Deleting the validator makes
both provider-entry cases red; without them the key is silently
swallowed.

**Three import allowlists had to admit `boundary.py`.** The acyclic
arrangement the review prescribed (the enum in `boundary.py`, the model
imports under `TYPE_CHECKING`) means `config/models.py` imports the
rule module, so every pin that enumerates what a lightweight import
loads gained one name: `tests/support/isolation.py` (the docgen and
server-reference renders), `tests/unit/test_config_entities.py` (the
registry alone) and `tests/unit/test_cli_import_weight.py` (the CLI's
reach). Each is annotated with why the module is safe to be there: it
weighs an enum and a dict and imports nothing of this server at run
time. Those three pins are also the falsification of the no-cycle
claim: a runtime import back would fail them, not merely warn.

**`check_feature`'s fixed `internet` has a consequence worth naming
again.** A `network`-bounded server refuses telemetry, capture upload
and transcript export even toward a collector on its own LAN, because
`OTEL_EXPORTER_OTLP_ENDPOINT` and `LANGFUSE_HOST` are transport
configuration this server hands over without reading. Each builder says
so in its own `_boundary_refusal` docstring.

### Follow-up, named so the decision does not evaporate

**An operator's reach assertion on the telemetry section.** The plan
names this and it is not this issue: it is a new declaration surface
with its own review territory (where the key lives, whether it is one
key or three, what a `capture_upload` assertion means when the two
transports point at different deployments). `check_feature` takes the
declared reach as an argument precisely so that follow-up changes an
argument rather than a shape: the three call sites pass
`Reach.INTERNET` today and would pass the section's own value instead.

### Verification

All from `vinga-server/` unless stated, against Postgres on
`VINGA_DB_PORT=55493` (compose project `vinga-493`, torn down after).

| Command | Result |
| --- | --- |
| `uv run pytest tests/unit -q -n 4 --dist loadfile` | `7154 passed, 19 skipped in 202.88s` |
| `uv run pytest tests/integration -q` | `336 passed in 494.08s` |
| `uv run ruff check .` | `All checks passed!` |
| `uv run mypy` (the events package, scope in `pyproject.toml`) | `Success: no issues found in 5 source files` |
| `uv run python -m tests.unit.test_command_spellings` | manifest rewritten, no diff |
| `python3 scripts/fold_changelog.py check .` (repo root) | `checked 1 fragments, 0 failures` |
| `python3 scripts/check_doc_links.py .` (repo root) | `checked 237 files, 0 failures` |
| `PLANTUML_LIMIT_SIZE=16384 plantuml -tpng -tsvg -failfast2 architecture-overview.puml` | rendered locally, plantuml 1.2026.8 |

The lightweight-import pins the plan names in its module section are in
the unit lane above and are named here because they are the no-cycle
proof: `test_config_docgen.py::test_the_reference_and_the_schema_render_from_the_models_alone`,
`test_server_reference.py::test_the_server_reference_renders_from_the_models_alone`,
`test_onboarding_import_weight.py` and
`test_cli_import_weight.py::test_the_cli_reaches_exactly_this_much_of_the_server`.

### Falsification

Every new claim was watched fail before it was believed. Seven
mutations, none of which survived:

| Mutation | Failures |
| --- | --- |
| `_exceeds` rewritten as the boolean this replaces (any boundary under `internet` refuses anything off the host) | 5, all `network-at-network`: both provider rank tables, the MCP entry-point table, `test_tools_mcp.py`'s own table and its unreferenced-entries case |
| `_exceeds` off by one (`>=`) | 15 |
| `check_mcp_server` fails open on an undeclared entry | 6, including two in the credential-display suite |
| An absent boundary read as `internet` in `check_provider` | 1: the case that distinguishes absent from explicit `internet` |
| The legacy-key validator deleted from `ProviderConfig` | 2: both provider-entry refusal cases |
| The migration leaves an explicit `null` behind | 2 upgrade cases |
| The migration maps an MCP `false` to `host` | 3 upgrade cases, one of them the case that exists for exactly this |

### Unverifiable

Nothing. The plan allows for the diagram SVG being locally
unrenderable; `plantuml` 1.2026.8 and a JDK were present, so both the
SVG and the PNG were re-rendered from the edited source rather than
hand-edited. The renderer stamps its own version into the SVG, which is
the one hunk in that file that is not the new legend.

### PR review round, PR #499

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-12, runtime 5m10s, reviewing `origin/main...404bdc9e`.
Verdict as received: **mergeable after the listed fixes**. Findings
condensed but faithful; one commit per finding, each watched red first.

1. **P1: the migration turned a malformed legacy declaration into
   permissive configuration.** The `else` arm removed `egress` for every
   value that was not JSON `true` or `false`, not just the planned
   `null`, so a stored string, number, array or object that the old
   model refused came out as an undeclared entry, and with no boundary
   declared that entry boots and transmits. Distinguish JSON `null`
   explicitly; preserve any other value as an invalid `reach` so
   sanitized model validation still refuses it, or abort the migration
   value-free. Add malformed-value upgrade cases for both tables and
   prove the upgraded store still refuses them.

   *Resolution.* Adopted, taking the PRESERVE shape. `jsonb_typeof`
   tells JSON null from everything else and null keeps its removal;
   every other value is renamed and carried across, where the new model
   refuses it exactly as the old model refused it under the old name.
   Aborting is the wrong shape here because the boot is what runs the
   migration and the configuration API an operator would fix the row
   through is behind the boot: an abort locks them out of the one door
   to the row that is stopping them, and takes the whole deployment
   down over one entry rather than the entry itself. A row that arrives
   as an invalid `reach` refuses at the surface every other unreadable
   row refuses at, naming the entry and quoting no value, and
   `vinga provider delete` and `vinga mcp-server delete` reach it by
   identity without understanding it. Four malformed shapes on both
   tables, one of them a pasted credential so the refusals are asserted
   value-free through their whole chain. Red first, with the migration
   as it was:

   ```
   FAILED test_a_malformed_legacy_value_is_renamed_rather_than_dropped
   E   KeyError: 'reach'
   FAILED test_the_upgraded_store_still_refuses_a_malformed_legacy_value[listed]
   FAILED ...[nested] FAILED ...[numbered] FAILED ...[pasted]
   E   Failed: DID NOT RAISE ConfigError
   5 failed, 6 passed
   ```

   The second is the finding itself: the upgraded store loaded a row the
   old build would not. Commit `ea9927a7`.

2. **P2: the composition-root case never exercised the composition
   root.** It monkeypatched the three builders and then called those
   patched builders directly, so removing or corrupting the real calls
   in `app._build_composition` would have left it green, contradicting
   its own docstring. Drive `_build_composition` through the existing
   composition harness with collaborators stubbed, then assert the three
   captured boundary arguments; keep the provider-world case for the
   fourth path.

   *Resolution.* Adopted. The app is built and its lifespan entered
   through `entered_app`, and what is asserted is what the composition
   handed the builders while it ran. The stubs answer None, which is
   what each builder answers for an absent section anyway, so nothing
   downstream changes shape; the sentinel for "not called" is the string
   `"unset"` rather than None, so a builder handed an explicit None is
   told apart from one that was never reached. The boundary is `network`
   because the mock providers reach the host and the fourth call site
   has to get through for the composition to reach the three that are
   the case's subject. Watched both ways, with all three
   `boundary=config.server.data_boundary` arguments deleted from
   `_build_composition`:

   ```
   --- OLD composition-root test against the corrupted root ---
   1 passed
   ```

   which is the finding, and the same corruption against the new one:

   ```
   E  AssertionError: assert {'build_telem...ort': 'unset'} ==
      {'build_telem...K: 'network'>}
   E  {'build_transcript_export': 'unset'} != {... <Reach.NETWORK>}
   E  {'build_capture_upload': 'unset'} != {... <Reach.NETWORK>}
   E  {'build_telemetry': 'unset'} != {... <Reach.NETWORK>}
   1 failed
   ```

   Commit `c4b30ac1`.

3. **P2: the old-spelling cases did not prove the promised no-leak
   behavior.** They passed `False` and validated the models directly:
   the MCP one asserted only that some `ValueError` occurred, and the
   provider one that the sentence contained the phrase "not quoted
   back". Pydantic's raw validation message includes the rejected
   input, so neither proved the operator-facing write path, the streams
   or the exception chain clean. Submit a credential-shaped legacy value
   through the real provider and MCP store-write paths and assert
   stdout, stderr, the `ConfigError` and its complete cause and context
   chain carry neither the value nor a traceback; retain both
   provider-type variants to pin the options trap.

   *Resolution.* Adopted whole. Both entry kinds go through the real
   store write with a credential-shaped legacy value, and the assertion
   is the whole operator-facing surface. Both provider-type variants are
   kept, since the options layer could only ever have answered the
   first: its reserved set is enforced by `OpenaiCompatibleOptions`,
   which no other type passes. The model-level refusals stay as two
   cases of their own, because a stored row read back and a file
   fragment reach that validator without a store around them. Red by
   making the refusal quote what the key held:

   ```
   E  assert 'sk-test-0a5...l-credential' not in 'invalid pro...-credential)'
   FAILED ...refuses_the_replaced_key_without_quoting_it[a-type-with-an-options-model]
   FAILED ...refuses_the_replaced_key_without_quoting_it[a-type-with-no-options-model]
   2 failed, 68 passed
   ```

   Only the two new write-path cases go red, and the sixty-eight that
   pass include the model-level refusals: the mutated sentence still
   contains "egress", "reach" and "not quoted back", so every assertion
   this replaces was satisfied by a refusal printing the credential.
   Commit `3620308d`.

4. **P2: the recorded final census was reproducibly false.** The
   section displayed a command and a count the command does not
   produce: it excludes `docs/plans/`, `docs/features/` and
   `CHANGELOG.md`, and `changelog.d/493-data-boundary.md` is none of
   those, so its two lines were found and not recorded. Either add the
   fragment to the justified allowlist and correct the count and table,
   or alter the command and the documented rule so the fragment is
   deliberately excluded.

   *Resolution.* Adopted, taking the ALLOWLIST shape. The fragment IS
   `CHANGELOG.md`: the fold on `main` moves its text there byte for
   byte, and the plan's allowlist already exempts the destination, so an
   exclusion in the command would say the same thing less honestly.
   Naming the old spelling is the whole job of that entry, since an
   operator reads it to learn what to change their file to. The count
   and the table are now what the displayed command prints, fifty-one
   lines in seven files at this milestone's last commit, with every line
   number checked against the command's output rather than transcribed:

   ```
   lines: 51 files: 7
   table matches grep: True
   ```

   The three fix commits above moved the numbers in the migration and
   both test files, which is the other half of why the old table was
   wrong. Commit `fa8f5c5c`.

### Verification after the review round

Re-run whole, from `vinga-server/` unless stated, against Postgres on
`VINGA_DB_PORT=55493` (compose project `vinga-493`, torn down after).

| Command | Result |
| --- | --- |
| `uv run ruff check .` | `All checks passed!` |
| `uv run mypy` (the events package) | `Success: no issues found in 5 source files` |
| `uv run pytest tests/unit -q -n 4 --dist loadfile` | `7156 passed, 19 skipped in 204.42s` |
| `uv run pytest tests/integration -q` | `341 passed in 490.67s` |
| `uv run pytest tests/unit/test_command_spellings.py -q` | `52 passed in 5.83s` |
| `python3 scripts/fold_changelog.py check .` (repo root) | `checked 1 fragments, 0 failures` |
| `python3 scripts/check_doc_links.py .` (repo root) | `checked 237 files, 0 failures` |

The census manifest moved in this round and was regenerated with the
last documentation edit. The drift came from the migration docstring
added for finding 1, which names `vinga provider delete` and
`vinga mcp-server delete` as the way to reach a row that arrives as an
invalid `reach`; `test_the_manifest_is_the_census` was red against the
committed manifest and is green against the regenerated one.
