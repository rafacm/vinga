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
rule is mechanical. Forty-two lines remain, in six files, and every
one of them is a place where the withdrawn word is what the line is
about:

| File | Lines | Why it stays |
| --- | --- | --- |
| `vinga-server/README.md` | 2103, 2105, 2107, 2109 | The upgrade note the plan asks for: a file is the operator's to edit, so the old spelling has to be named to say what it becomes. |
| `vinga-server/src/vinga_server/boundary.py` | 11, 20, 24, 242 | The module docstring's history paragraph, which the plan asks to keep with the rename recorded, and the note on the deleted MCP guard. |
| `vinga-server/src/vinga_server/config/models.py` | 2255, 2261, 2263 | `REPLACED_PROVIDER_KEY`, its refusal sentence, and the comment saying why the rejection lives at the `ProviderConfig` boundary. The constant IS the string `"egress"`. |
| `vinga-server/src/vinga_server/db/migrations/versions/3004_reach_replaces_egress.py` | 1, 7, 19, 21, 22, 26, 36, 62 | The migration's docstring and its `OLD` constant. It translates the key, so it names it. |
| `vinga-server/tests/integration/test_reach_upgrade.py` | 6, 49, 65, 66, 67, 72, 73, 74, 185, 191, 209, 275, 278 | The pre-upgrade row bodies and the assertions that no row keeps the key. |
| `vinga-server/tests/unit/test_providers_boundary.py` | 134, 444, 451, 458, 465, 473, 476, 481, 495, 497 | The three old-spelling refusal cases and one comment. |

Nothing else in the tree carries either token. `docs/reference/` is
generated and came out clean by construction; the committed SVG was
re-rendered and carries neither word.

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
