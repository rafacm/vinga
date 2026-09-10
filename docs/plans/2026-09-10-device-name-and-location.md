# Device name and location (#449)

## Goal

Turn a device from a MAC-keyed list of agent bindings into a record with a
stable identity, a required human name and an optional location, surface both
into the agent's per-turn context so a reply can be device- and place-aware, and
give the agent a tool to relocate the device it is speaking through.

Companion implementation doc:
`docs/plans/2026-09-10-device-name-and-location-implementation.md`, one section
per milestone, appended in the change that ticks the milestone.

## The issue's decisions, restated and not re-litigated

Settled across three comments on #449. Restated here because the plan is what a
fresh session reads, not because any of it is open.

- **`id` is an application-minted uuid hex**, `Text NOT NULL UNIQUE`, following
  the `sessions.session` and `conversations.conversation` convention rather than
  the `BigInteger Identity()` row id those tables also carry. A database-assigned
  integer cannot travel in a config document through import, diff and apply, so
  it cannot be a device's identity. `agent_defaults.id` is not a precedent: it is
  a singleton latch with a `CheckConstraint` pinning it to a constant.
- **Devices get no `Identity()` row id at all.** `db/schema.py` argues a field
  earns a column by needing SQL; these tables are read whole and assembled in
  Python, so a cursor id would be a column with no reader.
- **The MAC is not the id.** This reverses the earlier "id defaults to the MAC"
  line, which the issue withdraws.
- **`mac` is demoted to `NOT NULL UNIQUE`** and stays queryable, deliberately:
  `_live_binding` selects `devices.c.agents` by MAC and that path must stay
  byte-identical.
- **`name` is required and free-form.** Spaces and punctuation are allowed
  because the agent speaks the name aloud and a slug reads badly in speech.
- **Name uniqueness folds case and whitespace**: lowercase, trim both ends,
  collapse internal runs. The unique index is on the FOLDED form, not on
  `lower(name)` alone. The stored value is exactly what the operator typed.
- **The backfill name is `Device <full mac>`.** Full rather than truncated: the
  leading octets are the vendor OUI and are shared across a fleet, and a
  collision would be a migration failure on real data.
- **`location` is nullable and not unique.** Two devices in one room is normal.
- **`owner` is deferred**, not modelled now. Ownership rides the free-text name
  until a people concept exists to own it properly.
- **The config file's devices map stays keyed by MAC**, with `id` and `name` as
  fields. Keying by name was rejected: a rename would read to the differ as a
  removal plus an addition, so apply would drop the record and mint a new `id`,
  orphaning per-device memory and history, which is the exact outcome the stable
  id exists to prevent.
- **Config back-compat is a value-shape union** absorbed in
  `normalize_device_bindings`, already a `mode="before"` validator, so import,
  diff, apply, the JSON Schema and the generated reference all inherit it from
  one place.
- **The migration is `3003_*` on the domain chain**, currently at `3002`.
- **The migration writes frozen literals** rather than importing the live
  default-name rule. Stated here so a review round does not flag the duplication:
  a migration is a historical record of what ran, and importing a rule that can
  later change would make an old migration reproduce a new behaviour.

## The issue's open question, resolved

**Does boot refuse to serve an unmigrated database?** It does not refuse; it
migrates. `open_database` calls `open_at`, which builds the engine, creates the
schema if absent and runs the chain to head, and `config/boot.py` opens the
domain half that way before serving. So the connection `db/schema.py` describes
as one that never migrates always reads a database some boot has already brought
to head.

That matters for this change specifically, and the answer is the permissive one:
the migration may add `NOT NULL` columns without stranding the lookup path,
because the lookup path never sees a pre-migration schema in a served
deployment. The lookup's own statement stays byte-identical regardless, which is
the stronger guarantee and is what the milestone pins.

## Smaller decisions the issue leaves open, decided here

### The fold has one home and the index reads it

The fold (lowercase, strip, collapse internal whitespace) is a rule two places
must apply: the unique index in the database and the CLI's conflict refusal
before it writes. Two structures that must agree are one structure with a bug
pending, so the fold is a single function in the config models, the index is
expressed over the same expression, and the CLI refusal calls the function.

The migration is the deliberate exception, per the decision above: it writes the
expression as a frozen literal, and the milestone's tests pin that the frozen
literal and the live function agree TODAY, so a future divergence is a failing
test rather than a silent one.

### `location` is written through the same repository path as everything else

The tool does not reach the database. It calls the same domain repository write
the CLI calls, so validation, refusals and the reload semantics are single
sourced, which is the rule `db/schema.py` states for referential integrity and
the reason the REST API and the CLI already share that layer.

### The tool writes location and nothing else

`set_device_location` takes one argument and addresses no device: it writes the
location of the device the conversation is on, which the runtime already knows
from the turn context. The issue's permission question ("any voice in the room
could relocate a device") is answered as the issue suggests, the same trust
boundary as talking to the device at all, and that stance is written into the
tool's own description rather than left implicit.

Name is deliberately NOT settable by the tool. The mutability split is the
design's core: identity an operator manages, context a conversation may change.

### The device block in the prompt is a deepening, not a new block

`runtime/prompt.py` already assembles a device scope block with its own heading
for what is remembered about the device and its household. Name and location
join that block rather than opening a second one: they are facts about the same
device, the block already exists, and a second heading would make the model
choose which one to believe.

## Module layout

- `db/schema.py`: the `devices` table gains `id`, `name`, `location`; `mac`
  stops being the primary key.
- `db/migrations/versions/3003_*.py`: the migration.
- `config/models.py`: the device record model, the fold, and the widened
  `normalize_device_bindings`.
- `config/store.py`: the repository reads and writes for the record. What its
  callers stop having to know: that a device is three columns and a JSON list
  rather than a list.
- `config/cli.py` and `config/entities.py`: `vinga device` gains the name and
  location writes, held to `docs/architecture/cli-guide.md` (noun first, verb
  second, leading positionals as identity addressing).
- `runtime/prompt.py`: the device block carries the two facts.
- `tools/builtin.py` and `tools/names.py`: the new tool and its name.

No new module: every one of these exists and gains a responsibility it already
owns the neighbourhood of. The record model is the one thing that could argue
for its own file, and it does not: it is a device, and the device's other facts
are already in `config/models.py`.

## Documentation footprint

- `docs/reference/domain-config.md` and the JSON Schema are generated and change
  only through their generators; CI diffs the committed copies.
- `docs/reference/cli.md` is generated; the new verbs land through the generator.
- `config.example.yaml` moves in the same change as the schema, per AGENTS.md.
- `vinga-server/examples/` gains or updates the device example.
- `docs/concepts.md` describes what a device is and is hand-maintained; the
  promotion from a MAC-keyed binding to a record with an identity falsifies its
  current description and it is updated in M1.
- `docs/glossary.md` gains `device record`, `device name` and `device location`
  if the terms are not already there, checked rather than assumed.
- The command-spellings census sweeps every tracked file and new CLI verbs stale
  it; regenerate with `uv run python -m tests.unit.test_command_spellings`.
- `CHANGELOG.md` per milestone.

## Tests

- **The lookup path is characterized before it moves.** `_live_binding`'s
  statement and its answer are pinned green before the schema change and
  byte-unchanged after. This is the "pin before reshaping" lens and this
  milestone is the reason it exists: the device lookup is the path a board
  depends on to be served at all.
- **The fold**: a table of pairs that must collide (`Kitchen  Speaker` vs
  `kitchen speaker`, leading and trailing space) and pairs that must not, driven
  through the live function AND asserted against the database's own index by
  attempting the insert.
- **The frozen literal agrees with the live rule**: the migration's expression
  and the function produce the same folded value across the same table.
- **The migration on real-shaped data**: rows in the pre-migration shape,
  migrated, asserted to carry `Device <full mac>` and to be unique.
- **Config back-compat**: the bare agent-list shorthand and the record form both
  parse, normalize to the same record, and survive an import, diff and apply
  round trip with the `id` preserved across a name change, which is the property
  the MAC key exists to protect.
- **No-leak**: a device name is operator-authored free text that reaches the
  prompt, logs and CLI output. Plant a credential-shaped value and a value with
  control characters; assert the log and event surfaces carry neither, using
  `bounded_descriptor`'s existing rule where a descriptor is rendered.
- **The tool**: writes through the repository, refuses what the repository
  refuses, and addresses only the current device, pinned by attempting to write
  while two devices exist.

## Risks

- **The lookup path is load-bearing for serving a board at all.** Mitigated by
  the characterization pin above and by keeping the statement unchanged.
- **A migration that adds a `NOT NULL UNIQUE` column to a populated table can
  fail on real data.** The backfill uses the full MAC, which is unique by
  construction because `mac` is already unique, so the index cannot be violated
  by the backfill itself. The risk that remains is an operator who has already
  hand-written a colliding name, which cannot happen because no name column
  exists before this migration.
- **The prompt gains operator-authored free text.** It is already true of agent
  prompts and fragments, so the surface is not new, but the device name reaches
  the prompt without an operator necessarily thinking of it as prompt text. The
  no-leak tests cover the retained surfaces; the prompt itself is the operator's
  own text by construction.

## Milestones

- [ ] **M1: the device record.** Schema, migration `3003`, the fold with one
  home, the repository reads and writes, the widened
  `normalize_device_bindings` absorbing the value-shape union, the CLI writes,
  the generated references and `config.example.yaml`, `docs/concepts.md`, the
  glossary, changelog. `_live_binding` characterized before and unchanged after.
  Design footprint: deepens `config/store.py`, whose callers stop knowing a
  device is columns; adds no module and no seam.
- [ ] **M2: the agent knows where it is.** Name and location join the existing
  device block in `runtime/prompt.py`, carried from the turn context the runtime
  already resolves from the MAC. Design footprint: deepens `runtime/prompt.py`'s
  device block; no new block and no new seam, since a second heading would make
  the model choose which to believe.
- [ ] **M3: the agent can move the device.** `set_device_location`, writing
  through the same repository path the CLI uses, scoped to the device the
  conversation is on, with the trust stance written into the tool description.
  Design footprint: deepens `tools/builtin.py`; the tool reaches the repository
  rather than the database, so no second write path exists to disagree.

## Plan review round

External review of commit `9026ba7c`, backend codex (codex-cli 0.154.0), model
`gpt-5.6-sol`, 2026-09-10. Verdict as received: **not ready**, five P1 and five
P2. Findings condensed but faithful, each with its resolution. Two were taken to
the maintainer as scope questions; both are answered below.

### 1 (P1): the stable id is minted but is never made the identity of memory or history

Device memory is keyed by MAC (`memory/scopes.py`, `memory/schema.py`), recorded
sessions store the MAC (`conversations/schema.py`), and `MemoryContext` receives
the MAC. So the settled requirement that memory and history survive a board
replacement is not delivered by a domain-only change. The reviewer asks for
memory-chain and record-chain migrations translating MAC to uuid, updated
runtime context and readers, and a test of an actual MAC swap.

*Resolution*: the finding is right that a domain-only change does not deliver
it, and wrong about what delivering it costs. Probed rather than accepted:

**History is already correct and must not be rewritten.** `rename_agent`'s
docstring settles this for the exactly analogous case: "`turns.agent`,
`sessions.agent`, `sessions.agents` and the agent names inside event fields are
dated rows saying what was true when they were written, and nothing rewrites
them." A session row's MAC says which board was physically connected at the
time, which a later swap does not falsify. The settled design's own list is
"name, location, agent bindings, and any per-device memory", and history is not
in it. So no record-chain migration, and no change to what a session stores.

**Memory rides along by the pattern that already exists.** `rename_owner`
already takes a `MemoryScope`, so it is not agent-specific, and
`config/store.py` already orchestrates the three-schema move in one transaction
for an agent rename. A device MAC replacement is the same shape with
`MemoryScope.DEVICE`. That needs no uuid in the memory schema, no cross-chain
data migration and no re-keying, so the cross-chain ordering hazard the finding
raises does not arise.

**What it does need is the operation itself**, which the plan had left as "CLI
writes". Maintainer decision: it lands in this issue as **M4** rather than a
follow-up, because the stable id's whole justification is surviving a swap, and
shipping the id with nothing exercising that property ships a justification
nothing demonstrates. The swap test the finding asks for is M4's, and it is the
sharper version of the id-preservation test the plan already wanted.

### 2 (P1): the validator-only compatibility claim does not cover import or repository writes

`ConfigStore.apply` decomposes devices through `_change`, `_bound` and
`_DeviceBinding`, and bind and claim use `_binding`; none passes a device value
through `DomainConfig` as a record. A legacy list cannot normalize to the same
record as an object carrying an existing uuid unless staging consults the
current row, and minting a uuid inside a pydantic validator would break parsing
determinism and apply idempotence.

*Resolution*: accepted whole, and it is the finding that most changes M1. The
plan's "import, diff, apply, the JSON Schema and the generated reference all
inherit it from one place" was true of parsing and false of everything that
writes. Every device ingress is named explicitly in M1 and changed explicitly:
`bind`, the pending claim, `apply`/import, the API writes and stored-row
loading. **Minting moves out of the validator entirely**: the validator
normalizes shape only, and the uuid is minted in the repository under the domain
writer lock, where the current row can be consulted, so a stored id always wins
over an absent one and re-applying the same document is a no-op. That is what
makes apply idempotent, which a random default in a parser cannot be.

### 3 (P1): M2 cannot deliver metadata through the prompt path described

`_live_binding` selects only `agents`, `DeviceBindings` resolves only names, the
prompt device block receives only rendered memory, and `_system_prompt` skips
the whole scope assembly when memory is disabled. So name and location are
neither in the turn context nor guaranteed to reach an agent with memory off.

*Resolution*: accepted. The plan assumed a metadata path that does not exist and
assumed the block is always assembled, and both are wrong. M2 gains an explicit
read from MAC to `{id, name, location}` in the same snapshot the binding is
resolved from, and the device facts are assembled independently of the memory
switch, since a device's name is not a remembered thing and an agent with memory
off still has to know what it is speaking through. The tests named are empty
device memory, memory disabled, concurrent sessions, and a location changed
between rounds.

### 4 (P1): the location tool has no implementable composition or concurrency path

Built-ins are offered and dispatched by `tools/source.py`, whose constructor has
a `MemoryStore` and no domain repository; the app owns no long-lived domain
write store for conversations; database writes are synchronous while runtime
database work is moved off the event loop; and the new write must join
`ORDERED_TOOL_NAMES`, since two location writes in one round are order-sensitive.

*Resolution*: accepted whole. M3's module list named `tools/builtin.py` and
`tools/names.py` and stopped there, which is the definition of a milestone that
has not been designed. It now names `tools/source.py`, the runtime factory and
pipeline wiring, and app lifecycle ownership of a domain write engine with its
disposal; states that the synchronous write is dispatched off the event loop the
way other runtime database work is; and adds the tool to `ORDERED_TOOL_NAMES`.
Tests: two location calls in one round, and contention against another writer.

### 5 (P1): the no-leak design names a sanitizer that does not do what is claimed, and misses where location comes from

`bounded_descriptor` removes non-printables, trims and truncates; it does not
remove credential-bearing text. More importantly, an agent-set location
originates from a person, so it is conversation-derived content, and the
observability contract forbids what a person said from structured events. The
plan discussed only operator-authored name and said it reaches logs.

*Resolution*: accepted, and the classification is the part that matters. The two
fields are two trust classes and the plan treated them as one.

Maintainer decision, taken after probing what the contract actually forbids:
**neither field reaches any structured event or the capture manifest.** Events
and the manifest keep the MAC, which is a trusted identifier, exactly as today.
`location` cannot go there because it is conversation text and the
structured-events row says metadata only. `name` could, since far-side
descriptors like `board` and `version` already reach `session_open` through
`bounded_descriptor` with a cap, but it does not: the MAC already identifies the
device, so putting the name on every session row would give one fact a second
home and let it go stale after a rename. A reader wanting to display a name
joins the device record.

So `bounded_descriptor` is out of the plan's no-leak story, because nothing is
being sanitized onto a retained surface. The tests instead assert absence: drive
a session and a tool call with a credential-shaped name and a credential-shaped
location, and assert neither appears in any event payload, either log format,
the capture manifest, a refusal sentence, or an exception chain, including the
tool-failure path and the rejected-value path.

### 6 (P2): creation, default-covered devices, clearing location and hardware replacement are unspecified

`bind` and the pending claim create rows from MAC plus agents; a default agent
admits a MAC with no device row at all; the new schema requires a name; and
`set_device_location` assumes a writable record exists.

*Resolution*: accepted. M1 states the grammar and behaviour for bind, claim,
rename, location set and location clear, and M4 for MAC replacement. Decisions:
a created or claimed record takes the `Device <full mac>` default name rather
than requiring one at the call site, so no existing flow gains a mandatory
argument; a nullable location gets an explicit clearing verb and its test; and
the tool refuses, with a spoken reason, for a default-covered MAC with no row,
since minting a device record is an operator act and not a conversational one.

### 7 (P2): name uniqueness at the CLI is neither race-safe nor shared by all writers

The API, import, claim and repository callers bypass CLI logic, and letting the
index catch a conflict yields the generic sanitized database failure rather than
the promised refusal.

*Resolution*: accepted. The plan put the check in the wrong layer. Folded-name
uniqueness is enforced **in the repository while holding the domain writer
lock**, on every creation and rename path, with the database index kept as the
invariant behind it; the typed conflict is what the API and CLI both render.
Tests: import conflicts, concurrent renames, creation conflicts, and a
self-rename that changes nothing.

### 8 (P2): one fold function used by Python and by the SQL index is not implementable as written

Python string operations and a Postgres expression are different
implementations whose whitespace behaviour can diverge, particularly on Unicode
whitespace, and the plan's examples cover only ordinary spaces.

*Resolution*: accepted; the plan's "one home" was aspiration rather than design.
The fold is defined exactly: lowercase by Unicode simple case folding, strip and
collapse runs of the Unicode whitespace class. Python and SQL get separate,
declared renderings, and their equivalence is proved against Postgres over a
shared corpus that includes non-breaking space, tab, newline, ideographic space
and the Turkish dotted and dotless i. The migration keeps its frozen literal and
the corpus covers it too, so a divergence is a failing test rather than a silent
one.

### 9 (P2): the advertised import/diff test cannot observe what it claims

`config_diff` represents devices as `LiveKind(applies=CHECK_IN)` and performs no
device comparison, so it cannot report a changed record or prove an id survived.

*Resolution*: accepted, and the plan cited the differ as evidence for something
it cannot produce. Devices stay live-only; the differ contract is not expanded,
which would drag the generated response schema with it for no consumer. Id
preservation is tested directly by reading the row before and after the
repository and API operations, which is the stronger test anyway since it
observes the id rather than a report about it.

### 10 (P2): the migration ignores writers from the previous running image

After migration, an older still-running process keeps upserting only `mac` and
`agents` through `_device_row`, violating the new `NOT NULL` constraints.

*Resolution*: accepted as a real gap in the plan, and answered by a decision the
repository has already taken rather than by staging the schema. The one-replica
topology ADR (#316) means a rolling two-version overlap is not a supported
deployment shape, so the answer is to state that and test it rather than to add
database defaults for a writer that should not exist. The plan says explicitly
that the upgrade is stop-then-migrate, and the migration test covers an
old-shape write attempted after the upgrade, asserting it is refused rather than
silently accepted.

### 11 (P3): the documentation footprint names an artifact that does not exist

`docs/reference/` contains no standalone JSON Schema; the committed API contract
is `api-openapi.json`, which device routes would stale along with `cli.md` and
`domain-config.md`.

*Resolution*: accepted; the claim is corrected. The footprint now names
`domain-config.md`, `cli.md` and `api-openapi.json` as the generated artifacts
that move. `events.md` and `conversations-schema.md` do NOT move, which is a
consequence of finding 5's resolution: no event gains a field and no stored
column changes, so neither reference is stale. `observability-surfaces.md` stays
accurate for the same reason.
