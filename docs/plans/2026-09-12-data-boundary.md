# A declared data boundary with a network tier

Plan for [issue #493](https://github.com/rafacm/vinga/issues/493).
Companion implementation doc:
`2026-09-12-data-boundary-implementation.md`, one section per
milestone, appended in the same change that ticks the milestone
checklist.

## Goal

The egress mechanism's behavior is sound and stays; its names face
the wrong audience and its binary forces dishonest declarations at
exactly the deployments the local promise courts. After this issue,
the operator declares a boundary (`server.data_boundary`), a
provider declares a reach (`host | network | internet`), the one
rule is that a reach exceeding the boundary refuses to build with
undeclared still failing closed, and a GPU box running Ollama on
the LAN declares `reach: network` honestly instead of stretching
`egress: false`. The old spellings (`server.local_only`, both
`egress` keys, the class marking) disappear with no aliases, which
is most of why this lands now rather than after a beta.

Local baseline: not applicable. No capability changes; the promise
page's citation updates exactly as
[the enumerated-baseline record](../adr/2026-09-12-the-local-baseline-is-enumerated.md)
anticipated in its consequences ("updates a citation rather than a
promise", naming this issue).

## The issue's decisions, restated

- One vocabulary, two sides, one rule: the operator declares a
  boundary, a provider declares a reach, a reach exceeding the
  boundary (or refusing to state itself while a boundary is
  declared) refuses to build. Undeclared fails closed, the
  hard-won half of #136, preserved exactly.
- `host` is today's `local_only: true`, exactly as strict. The
  class marking becomes `host | network | internet` where the type
  knows and stays undeclarable where it cannot; the operator key on
  such entries becomes `reach: host` or `reach: network` in place
  of `egress: false`. MCP entries and the exporter speak the same
  values.
- Declarations are enforced, behavior is not verified: `network`
  remains an operator assertion the way `egress: false` is today,
  the boundary is not a network sandbox, and this issue must not
  creep toward verification. The #485 promise revision states the
  limit and is this issue's scope guard.
- The old spellings disappear rather than alias; refusal sentences
  get plainer for free, still naming the entry, the type and the
  key, never a value.
- Not named privacy, deliberately: the key names its mechanism, the
  documentation tells the umbrella story.

## Open questions, resolved

### The value set is `host | network | internet`, one enum for both sides

The issue's working set survives contact with the code: the
existing provider refusals already say "off this host" and the MCP
ones "off this network" (`egress.py:29-32` records the distinction
as deliberate), so the values are the words the sentences already
use. One `StrEnum Reach` in the renamed module serves both sides:
a boundary IS a reach (the outermost reach session data may have),
so a second enum would be two structures required to agree. The
ordering the rule needs (`host < network < internet`) has no
counterpart in the tree today (the census confirmed nothing
compares two levels; the current rule is one corner of the
lattice), so it is introduced explicitly as a rank table beside the
enum rather than implied by member order, and a test pins all nine
boundary-times-reach cells of the rule.

### Unbounded is the same enum, and the key's absence means `internet`

`server.data_boundary: host | network | internet`, absent meaning
`internet`, which is today's default in the new vocabulary: session
data may reach the internet is exactly what an undeclared boundary
permits. This resolves the issue's absent-versus-explicit question
with both: the third value exists and is the default, so an
operator may spell the default explicitly, the lattice is uniform
(one comparison, no special unbounded state), and no deployment is
forced to add a key. Under `internet` nothing refuses, matching
today's `local_only: false`; the MCP guard's condition (today
`if config.server.local_only:`) becomes "a boundary narrower than
`internet` is declared".

### The resolve ladder replaces the `None` conflation

The census found the load-bearing subtlety: `egress.py:69` resolves
effective egress as `marked if marked is not None else
config.egress`, where `None` means two different things (a class
that cannot know versus an operator who declared nothing) and the
conflation happens to work only because both defaults are `None`.
The new resolve is explicit about its three states:

- The class marking is `reach: ClassVar[Reach | None]`, `None`
  spelled on exactly the three classes whose base URL decides
  (`openai_compatible` and the openai ASR and TTS), the
  `_UNDECLARED` object sentinel kept for true absence (a class that
  declares nothing at all is a bug refused in any mode, as today at
  `egress.py:104`), and the closed-set identity check refusing
  anything outside `{host, network, internet, None}` (the
  `egress = 0` case keeps its pin).
- The entry key is `reach: Reach | None = None`, lawful only on a
  `None`-marked type (declaring it on a type that knows its own
  answer stays refused in any mode, the `egress.py:62` rule with
  the new spelling). The issue names `host` and `network` as the
  values an operator asserts; `internet` is accepted too, because
  refusing an operator's honest statement of the worst case would
  be the mechanism teaching dishonesty from the other side, and it
  simply refuses under any narrower boundary.
- An entry whose type cannot know and whose operator declared
  nothing fails closed under any boundary narrower than
  `internet`, exactly today's undeclared rule.

Truthiness dies with the booleans: every decision site becomes a
rank comparison or an identity test against enum members, and the
census's list of boolean-arithmetic sites (`egress.py:62, 67, 69,
76, 102, 109, 141, 169-171`, `views.py:546`, `manager.py:781`) is
the checklist the implementation walks.

### Features keep a fixed `internet` reach; the LAN-collector assertion is named follow-up

`check_feature` today takes `egress=True` from all three callers
(telemetry, `export_audio`, `export_transcripts`). Their honest new
declaration is `reach=Reach.INTERNET` fixed: vinga cannot know
where `OTEL_EXPORTER_OTLP_ENDPOINT` or `LANGFUSE_HOST` point, and
there is no per-feature entry to carry an operator assertion. The
consequence is stated rather than hidden: a `network`-bounded
server refuses telemetry even toward a LAN collector. Extending
the provider-entry pattern (an operator `reach` assertion on the
telemetry section) is real and useful and is NOT this issue: it is
a new declaration surface with its own review territory, named in
the implementation doc as follow-up so the decision does not
evaporate. The `check_feature` signature takes the declared reach
and the boundary, so that follow-up changes an argument, not a
shape.

### The module renames with its rule: `boundary.py`

`egress.py` becomes `src/vinga_server/boundary.py`: the one-home
property of #136 is preserved (same three checks, same re-raise
contract, same wording ownership), `EgressRefusal` becomes
`BoundaryRefusal`, and the module docstring keeps its history
paragraph with the rename recorded. What callers stop knowing is
unchanged and stays the module's depth: the composition passes the
parsed boundary through, and no caller decides anything. The
refusal sentences rework to the issue's plainer shape, still
value-free and entry-naming, one per decision site, for example:
`{label}: type "{type}" reaches the internet, but this server's
data boundary is host` for the marked case;
`{label}: this server declares a data boundary, and whether type
"{type}" stays inside it depends on its base_url; declare "reach:
host" or "reach: network" on this entry to state where the
endpoint stays` for the undeclarable case; the MCP pair and the
feature sentence reworked the same way. Every sentence names the
boundary's VALUE deliberately (`host`, `network`): the boundary is
the operator's own declaration, not a value read from an entry, so
speaking it violates nothing, and the plainness the issue asks for
needs it. The full-equality one-home pins (`test_telemetry.py:186`,
`test_transcript_export.py:328`) and the fragment pins move to the
new sentences.

### The old spellings are refused loudly, and the provider-options trap is closed

Three old keys, three refusal shapes, each pinned by a test:

- `server.local_only` under `extra="forbid"` on `ServerConfig`:
  refused as an unrecognized key, the M1-of-#495 pattern, pinned
  with the section-not-key sentence.
- `egress` on an MCP entry: `McpServerConfig` is `extra="forbid"`,
  same shape, pinned.
- `egress` on a provider entry is THE TRAP the census exposed:
  `ProviderConfig` routes unknown keys into provider options
  (`provider_options.py`'s "everything beyond type, api_key_env and
  egress"), so removing the field would let an old `egress: false`
  flow silently into options and reach the provider as a stray
  option, or vanish. The plan closes it explicitly: `egress` joins
  the reserved names the options layer refuses by name with a
  fixed sentence pointing at `reach` (the options layer already
  owns a reserved-key concept for the seven pass-through fields;
  this is one more row, not a mechanism), and the test plants
  `egress: false` on a provider entry and pins the refusal names
  the key and the remedy without echoing the value.

### One milestone, because a half-renamed vocabulary is not releasable

Every merge must leave `main` releasable, and a state where half
the surfaces say `egress` and half say `reach` is a state where the
example configs, the generated references and the enforcement
disagree, so the cutover is one milestone. Its bulk is mechanical
(the census counts ~130 `egress` and ~100 `local_only` sites, most
in tests), and the one behavior addition (the `network` tier and
its rank rule) sits in the renamed module where the review can see
it whole. The documentation footprint lands in the same milestone:
the server README's Security block and per-type mentions, the
promise page's citation line, the observability map's four
refused-under rows, `docs/concepts.md` and `docs/system-overview.md`,
the diagram source and its committed SVG (re-rendered through
plantuml; if no local renderer exists the SVG change is stated as
unverifiable-locally on the PR rather than hand-edited), both
example configs and the seven per-type example YAMLs plus
`examples/README.md`, and the four generated references through
their generators. Historical records (the 2026-08-05 feature doc,
the plans corpus, `CHANGELOG.md`) keep their spellings. The
`cli-respelling.txt` fixture regenerates through its own harness.

## Module layout

- `src/vinga_server/boundary.py` (renamed from `egress.py`):
  `Reach` (StrEnum) with its rank table, `BoundaryRefusal`,
  `check_provider(label, config, provider, boundary)`,
  `check_feature(label, reach, boundary)`,
  `check_mcp_server(label, entry, boundary)`; the resolve ladder
  and every sentence.
- `config/models.py`: `data_boundary: Reach = Reach.INTERNET` on
  the server section (absent means internet); `reach` replacing
  `egress` on `ProviderConfig` and `McpServerConfig`; descriptions
  rewritten to the new vocabulary.
- `providers/base.py` and the nine concrete classes: the marking
  respelled (`reach = Reach.INTERNET` for the two cloud types,
  `Reach.HOST` for the local four and the mocks, `None` for the
  three base-url types).
- `config/provider_options.py`: `egress` as a reserved refused
  name; `reach` joins the non-option field list.
- `providers/world.py`, `tools/mcp/manager.py`, `telemetry.py`,
  `capture_upload.py`, `transcript_export.py`, `app.py`,
  `config/views.py`, `config/reload.py`: call sites respelled, the
  boundary passed where `local_only` was.
- Docs and configs as listed under the milestone decision.

## Tests

- The nine-cell rule table (three boundaries times three effective
  reaches), each cell driven through a real provider build, watched
  red where the old binary disagrees (the new cells:
  `network`-reach under `network` boundary builds;
  `network`-reach under `host` refuses; `internet`-reach under
  `network` refuses).
- The resolve ladder: marked class beats entry key everywhere;
  entry key on a knowing type refused in any mode; undeclared
  fails closed under `host` AND under `network`; `reach: internet`
  on an entry accepted and refused under both narrower boundaries.
- The three old-spelling refusals above, each value-free and
  unchained, the provider-entry one proving the options layer
  refuses rather than swallows.
- The respelled sentences: the moved full-equality one-home pins,
  the fragment pins (`"reach:"` replacing `'"egress: false"'`),
  value-freedom held (a planted base_url absent from every
  sentence).
- MCP: the guard fires under `network` as under `host`; the
  undeclared and declared refusals respelled.
- The existing identity pins (`.egress is False` and kin) move to
  enum-member identity; the closed-set case (`reach = 0` on a
  class) keeps its shape.
- Census, examples coverage, generated-reference drift checks and
  the `cli-respelling` round trip all green after regeneration.

## Risks

- **The sweep's breadth invites a missed site.** The census is the
  inventory and the grep is re-run at the end of implementation
  (`egress` and `local_only` over tracked files, expecting exactly
  the historical-record remainder, listed in the implementation
  doc); the census's known false positives ("regression") are
  named so the check is mechanical.
- **Grammar/refusal territory widens rounds** (the standing
  pattern); the sentence pins and the nine-cell table are written
  with the first commit.
- **The diagram SVG may be locally unrenderable**; stated honestly
  on the PR if so, never hand-edited.
- **`#495`'s flags already cite the boundary in their prose**; the
  models.py descriptions respell in the same sweep, and the
  generated reference follows by construction.

## Milestones

- [ ] **M1: the vocabulary cutover.** Everything above in one
  milestone: `boundary.py` with the `Reach` enum, rank rule and
  sentences; the three config keys respelled with the old ones
  refused (options trap closed); the nine class markings; every
  call site; the test program; both example configs, the seven
  per-type examples, four generated references, the README
  Security block and per-type mentions, the promise citation, the
  observability rows, concepts, system-overview, the diagram
  source and SVG; fragment `changelog.d/493-data-boundary.md`
  (### Changed) naming both renames and the new tier. Design
  footprint: renames `egress.py` to `boundary.py` and deepens it
  with the rank rule; no new seams; callers keep translating, not
  deciding. Documentation footprint as enumerated, each page
  through its owner.

## Plan review round

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-12, runtime 7m40s, reviewing commit 1f101783.
Verdict as received: **not ready** (the explicit-internet semantics
and the import cycle block implementation; the P2 amendments also
required). Findings condensed but faithful; resolutions appended
per amendment.

1. **P1: Explicit `internet` loses the declared-versus-absent
   distinction.** Making absence identical to explicit `internet`
   permits undeclared endpoint-dependent providers under both,
   while the issue requires a provider that will not state its
   reach to fail closed whenever a boundary is declared. Model the
   field as `Reach | None = None`: `None` is no boundary (today's
   behavior); explicit `internet` is a declared boundary under
   which every stated reach fits but an undeclared entry still
   refuses; test the distinction.

2. **P1: The proposed enum location creates a runtime import
   cycle.** `Reach` in `boundary.py` used by `config/models.py`
   while the rule module imports the model types at runtime is
   `config.models -> boundary -> config.models`. Keep `Reach` in
   `boundary.py` and drop the runtime model imports via postponed
   annotations plus `TYPE_CHECKING` (no pass-through enum module);
   preserve the lightweight-import tests.

3. **P2: The old provider key cannot join the existing
   request-field reservation.** The reserved set is OpenAI chat
   request fields enforced only by `OpenaiCompatibleOptions`;
   other types never pass that validator, and listing `egress`
   there would document it falsely. Reject the legacy key at the
   common `ProviderConfig` boundary before `model_extra` becomes
   options, fixed value-free remedy naming `reach`, tested on an
   open-ended entry and an optionless type.

4. **P2: Existing stored domain configuration has no upgrade
   path.** Provider and MCP bodies persist as opaque text and can
   carry `egress`; the new models would reject or misroute those
   rows before the API is even up, and the repository already
   proves domain migrations against pre-upgrade rows. Add a
   forward migration (provider `egress: false/true` to
   `reach: host/internet`; MCP to `reach: network/internet`,
   preserving the host-versus-network distinction) with its
   upgrade test; new writes still reject the legacy key; document
   that a file-backed `server.local_only: true` must become
   `server.data_boundary: host` before the new image starts.

5. **P2: The MCP caller would retain part of the boundary
   policy.** A guard reading "boundary narrower than internet" in
   the manager duplicates the central rule. Invoke
   `check_mcp_server` for every referenced entry, pass the
   optional boundary through, and let `boundary.py` alone decide
   what an absent or declared boundary means.

6. **P2: The feature tests do not exercise the new `network`
   call-site plumbing.** The nine-cell table drives only provider
   construction; a caller still passing a boolean or the default
   boundary would stay green. Add call-site tests for telemetry,
   capture upload and transcript export proving `network` refuses
   before imports, constructors or threads while an absent
   boundary permits construction, plus a composition-root test
   that `data_boundary` reaches each builder unchanged.

7. **P2: New enum-valued inputs lack explicit no-leak tests.**
   Invalid values for the three new fields fail in pydantic
   validation, whose exception data can retain the input. Plant a
   credential-shaped invalid value per field across the real file,
   write and stored-read surfaces, assert both streams and the
   exception chain clean, and use a credential-shaped invalid
   class marking for the closed-set case.

8. **P2: The cutover inventory omits live surfaces still
   publishing the old vocabulary.** Root README's `egress: false`
   import example, the `local-stack.yaml` preset (eight example
   YAMLs, not seven), both diagram READMEs,
   `config/api_descriptions/reload-refused.md`, `config/boot.py`,
   `config/api.py`, `tools/mcp/registry.py`, `capture.py`,
   `tests/integration/test_cli_wheel.py` and the shared test
   helpers. Add them and define the final grep allowlist
   explicitly: historical plans, feature records and changelog may
   keep the words; live docs, examples, source prose, shared
   fixtures and wheel tests may not.

9. **P2: Updating only the promise's citation leaves its
   mechanism false.** The promise page also says every provider
   declares whether it sends data off the host and describes a
   binary refusal, which stops describing three reaches. Preserve
   the promise and the baseline list; rewrite the enforcement
   paragraph for declared reach, ordered boundaries and
   fail-closed endpoint-dependent types; use the precise `host`
   spelling where the citation identifies today's fully local
   configuration.
