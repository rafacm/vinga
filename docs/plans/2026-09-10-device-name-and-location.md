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
