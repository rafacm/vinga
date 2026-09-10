# A first-party read over the phase-1 aggregates (#440)

## Goal

Serve #439's four named aggregates over the API and the CLI, with bounded
windowing and a per-device dimension, so that the consumers who are not SQL
clients can read them: an operator without psql, the admin UI (#129), and
eventually budget accounting.

Companion implementation doc: `docs/plans/2026-09-11-metrics-read-surface-implementation.md`,
one section per milestone, appended in the change that ticks the milestone.

## What this is not for, stated first

A Grafana board does not need this. `deploy/postgres-init.sql` grants `vinga_ro`
`USAGE` and `SELECT` on the whole `record` schema, and Grafana with a Postgres
datasource is a SQL client, so it can already read `record.metrics_*`,
`record.sessions`, `record.turns` and `record.events` directly. This issue exists
for the readers that cannot speak SQL, which is what the issue itself says.

Recording it because it changes what "done" means: if this surface is ever
harder to use than a `select`, its intended readers are not the ones being
served.

## The two design questions the issue delegates, decided

### Addressing: the noun is `metric`, and the name is a citation

The surface is called metrics, not stats. This is settled by the repository
rather than by preference: the changelog for #437, which renamed the storage
switch to `telemetry`, says the rename happened because "it is a storage privacy
switch, `metrics` is reserved for the future aggregation surface". This is that
surface.

**The CLI noun is singular, `metric`**, because `show` addresses one of them.
The guide's rule is singular when a noun addresses one entry, plural when it is
a collection you only ever ask about as a whole, and a named view is an entry:
`metric show stage-latency` addresses one the way `session show <id>` does. The
first draft of this plan claimed the noun addressed nothing and then gave it an
identity positional, which is the review round's first finding.

**The grammar is `vinga metric list` and `vinga metric show <view>`.** The guide
forbids a noun in the verb slot ("a noun in the verb slot reads as a possessive
and hides what the command does"), so `vinga metric latency` is excluded however
natural it reads, and #223's `agent preview` is the precedent for not granting
that exception to the first command that asks for it. `list` and `show` are
core-set verbs.

On the API: `/metrics` and `/metrics/{view}`. Plural collection, member under
it, which is exactly the shape `/sessions` and `/sessions/{session}` already
have beside a singular CLI noun, so the two surfaces agree rather than diverge.

One note for a future reader: `/metrics` is conventionally a Prometheus scrape
path and this is not that. It sits under the API's bearer token rather than on
an unauthenticated scrape port, so the collision is in spelling only, and a
scrape endpoint does not belong under `/api` anyway.

### The view aliases, and the closed mapping behind them

Four aliases, each dropping the prefix and suffix all the views share:
`stage-latency`, `tokens`, `event-rates`, `sessions`. Kebab-case per the guide.

`{view}` is request-controlled selection of a database relation, and a relation
name cannot be a bound parameter, so **the alias resolves through a closed
mapping derived from the view registry** and the caller's bytes never reach SQL.
Deriving it from the registry rather than writing it beside it is what stops the
set of servable views drifting from the set of declared ones. An unknown alias
gets a fixed refusal that quotes nothing back, which is the rule
`conversations/api.py` already states for this surface.

### The request contract

Stated exactly, because "bounded windowing" was a promise standing in for a
design.

**Query parameters on `GET /metrics/{view}`**, following the conventions the
adjacent listings already use (string-typed, validated with a fixed sentence
that quotes nothing):

| parameter | accepts | default | bound |
| --- | --- | --- | --- |
| `since` | a UTC date, `YYYY-MM-DD`, inclusive | 30 days before `until` | must not precede `until` |
| `until` | a UTC date, `YYYY-MM-DD`, inclusive | the current UTC day | none |
| `group` | `all` or `device` | `all` | closed set |
| `device` | one MAC, normalised as `/sessions` normalises it | absent, meaning every device | only with `group=device` |

The horizon is capped at **366 days**, one leap year, and a window wider than
that is refused rather than clamped, so a caller never receives less than it
asked for while being told it received what it asked for.

**Boundaries are inclusive at both ends and UTC**, matching the views, whose
reference already establishes that a day is a UTC day and says why.

**Ordering is `day` descending, then `device` ascending with nulls last**, which
is total, so a page is reproducible.

**An empty window is an ordinary empty list**, never a refusal and never a 404.
A window with no rows and a deployment that never recorded are the same answer,
for the reason `conversations/api.py` gives about empty shapes.

**`GET /metrics` lists the views** rather than serving data: each alias with its
`question`, its `denominator`, its `telemetry_off` sentence and its columns,
derived from the registry so the listing cannot drift from what `show` serves.

**Response models live in `config/responses.py`**, beside the conversation
shapes, and are imported by both `conversations/api.py` and `config/cli.py`.
That is what lets the CLI validate a response without importing FastAPI,
SQLAlchemy or the store, which is why those shapes live there today.

### The trend horizon: no snapshots, and the constraints any future one must meet

The issue calls this its real design work, so this is a decision with reasons.

**No snapshot table.** Three reasons, in order of weight:

1. **The consumers do not exist.** The admin UI (#129) and budgets are what
   would say what grain a snapshot needs, and neither is built. Snapshotting the
   wrong grain costs more than not snapshotting, because a durable table with
   rows in it is what nobody can change their mind about.
2. **`retention_days` defaults to 90**, so there are three months of slack
   before anything ages out of the live views.
3. **A snapshot would freeze a caveat rather than fix it.** The views already
   say a rate read outside the events' own retention window is a floor and not a
   measurement, because the database cannot tell zero events from events already
   pruned. A snapshot taken today inherits that and makes it permanent and
   unlabelled.

**So this issue serves live views over whatever rows survive the store's
asymmetric retention**, and the surface says so rather than implying the numbers
are complete.

**The shape does not preclude one**, which is the commitment the issue already
makes about a per-user key: rows carry their `day` and their denominators,
nothing in a response says "computed live", and no parameter is defined in terms
of retention.

The first draft went further and sketched a mechanism, riding the retention
prune's existing hook. **That sketch was wrong and is deleted rather than
patched**, which the review round records. `_prune` runs at writer start and
after session close, it **deletes first**, and it does not run at all when
`retention_days <= 0`; recording-off starts no writer. So a quiet deployment
does have something to lose immediately before the startup prune, and old turns
can survive in active conversations whose events are already gone.

What replaces it is the constraint list a future design has to satisfy, so the
next person starts from what was learned rather than from the same sketch:

- It must run **before** destructive pruning, not beside it.
- It must work with recording disabled and with `retention_days` at zero.
- It needs its own retention and its own erasure behaviour, since it would
  outlive the rows it summarizes.
- It must preserve whether a rate was **already only a floor** when it was
  taken, or it will report a floor as a measurement forever.

### The device dimension, decided with the maintainer

The four views gain a per-device breakdown and the read surface carries it.
Rows carry two fields: `device`, the MAC, which is the stable key, and `name`,
the human label, **null until #449's M5 lands** and filled in without this
surface's shape moving. It does not depend on #449: `record.sessions.device`
already holds the MAC.

Why the name has to be denormalised at all, rather than joined: `vinga_ro` is
granted on `record` and **explicitly revoked on `domain`**, so no analyst and no
dashboard can ever reach `domain.devices`. #449's M5 is what puts a copy on the
`record` side.

Cardinality is small: three board models, three units each.

## Behaviour under the storage switches, which the issue makes an acceptance criterion

**Conversations off keeps serving.** Boot migrates the `record` schema whether or
not recording is on, and every read opens its own connection through
`db.read_engine` rather than borrowing the writer's, so the reads work with
recording off, where there is no `ConversationStore` at all. Switching recording
off stops new rows; it does not hide the ones already written.

**A deployment that never recorded gets an ordinary empty result**, not a
refusal and not a 404. This is a deliberate contract stated in
`conversations/api.py` under #283: the distinction a 404 drew was between a file
that existed and one that did not, there is no file, and an empty list is the
honest answer to a question about empty tables. The first draft of this plan
proposed a refusal here, which would have reversed that.

**No switch state is added to `ApiRuntime`** and no current configuration is
inferred from stored rows. If a response ever needs to state a live switch
value, that is a composition-root change with its own design, and this surface
does not need it.

**Telemetry off is per view rather than uniform**, and the surface must not
flatten it: the latency view produces no row at all, while the event-rate view
keeps its denominators and loses its numerators. Each view's own `telemetry_off`
sentence is what the surface reports, which is why it is declared per view.

## Module layout

- `conversations/views.py` holds the view declarations and is where the
  per-device variants are declared, beside the four they mirror. What its
  callers stop having to know is the SQL.
- `conversations/api.py` gains the read routes. No new module: this is the same
  shape as the session and conversation reads beside it.
- `conversations/cli.py` gains the noun and its two verbs.
- The generated artifacts move through their generators only:
  `api-openapi.json`, `cli.md`, `metrics-views.md`.

No new module in any milestone. If one appears, it needs the deletion test
applied to it in the implementation doc.

## Tests

Reusing `tests/unit/test_conversations_api.py` and #439's view tests rather than
restating their fixtures.

- **The request contract, boundary by boundary**: each parameter's default, both
  inclusive ends, a window at the 366-day cap and one past it, a malformed date,
  an unknown `group`, `device` given without `group=device`, the total ordering,
  and an empty window answering as an empty list.
- **No-leak on request-controlled values.** Hostile and control-character values
  sent as `{view}`, `group` and `device` through both the API and the CLI, with
  the assertion that they appear in no response body, no stderr, and no emitted
  record in either log format. This is the pin behind the closed mapping.
- **The switch behaviours, as sentences and statuses** rather than as "it did
  not crash": recording off with prior history, a deployment that never
  recorded, and telemetry off asserted **per view**, since the latency view
  produces no row while the event-rate view keeps denominators and loses
  numerators.
- **The caveats reach both surfaces.** Semantic assertions, not drift checks: a
  drift check proves an artifact matches its generator, never that the generator
  kept anything. The zero-denominator rule, the retention-floor warning, the
  missing-measurement ambiguity and each view's own telemetry-off sentence are
  asserted present on the API descriptions and in the CLI's output.
- **The null-device join.** One session with a null `device` that contributes a
  turn and a counted event, asserted to produce **exactly one** combined row with
  correct denominators and rates. Two of the views combine independently
  aggregated streams with full outer joins, and ordinary equality does not join
  two SQL nulls, so this is what catches three separate null rows.
- **The upgrade.** A database at `1006_metrics_views` migrated forward, with the
  four original views asserted to survive and still answer, since the per-device
  views are additive siblings and not replacements.

## Risks

- **The views' honest caveats can be lost in translation.** Every limit in
  `metrics-views.md` (a rate null when its denominator is zero, retention making
  historical rates a floor, a missing measurement having more than one cause)
  has to survive into the API's field descriptions and the CLI's rendering, or
  the surface reports numbers the SQL would have qualified. Mitigated by
  generating the descriptions from the view declarations where possible, so the
  two cannot drift.
- **`/metrics` collides in spelling with a Prometheus convention.** Noted above;
  no mitigation needed beyond not putting a scrape endpoint under `/api`.

## Milestones

- [ ] **M1: the aggregates on the API.** `/metrics` and `/metrics/{view}` over
  the four phase-1 views, day-grained, with bounded windowing and the
  storage-switch answers. Response models in the server's vocabulary, carrying
  the views' own caveats in their field descriptions. `api-openapi.json` moves
  through its generator. Design footprint: deepens `conversations/api.py`; adds
  no module and no seam.
- [ ] **M2: the CLI in front of it.** `vinga metrics list` and
  `vinga metrics show <view>`, held to `docs/architecture/cli-guide.md`, a
  client of the API like every other verb with `--local` as the break-glass.
  `cli.md` moves through its generator; the census follows. Design footprint:
  deepens `conversations/cli.py`.
- [ ] **M3: the device dimension.** The views gain their per-device variants,
  and the API and CLI gain the grouping, carrying `device` and a `name` that is
  null until #449 M5. Migration on the conversations chain for the new views.
  `metrics-views.md` and both generated references move. Design footprint:
  deepens `conversations/views.py` with declarations beside the four they
  mirror; adds no module.

## Plan review round

External review of commit `fd4e0ef6`, backend codex (codex-cli 0.154.0), model
`gpt-5.6-sol`, 2026-09-11. Verdict as received: **not ready**, five P1 and five
P2. Findings condensed but faithful, each with its resolution. Every P1 was
checked against the code before being accepted; none was rejected.

### 1 (P1): `metric show <view>` makes a plural noun address an entry

The plan calls `metrics` a noun that addresses no entry and then makes `<view>`
a leading identity positional, which is the guide's definition of addressing
one. `session` and `conversation` are singular for exactly that reason.

*Resolution*: accepted. **The noun becomes singular: `vinga metric list` and
`vinga metric show <view>`.** The API paths stay `/metrics` and
`/metrics/{view}`, which is the same collection-and-member shape `/sessions` and
`/sessions/{session}` already use beside a singular CLI noun, so the two agree
rather than diverge. The #437 citation is unaffected: it reserves "metrics" as
the name of the aggregation surface, and one view of it is a metric.

### 2 (P1): M2 targets the wrong CLI and invents a direct-read path

`conversations/cli.py` is the `vinga-server conversations schema|views`
documentation generator and opens nothing. Public API-backed commands live in
`config/cli.py`, whose conversation commands state there is no local-database
path, and no `--local` exists for them.

*Resolution*: accepted, and the plan was wrong twice over. `conversations/cli.py`'s
own docstring says "querying the views live is the API and CLI surface #440
owns", so the module this plan named points at this work as belonging elsewhere.
And `config/cli.py` states the rule the plan would have broken: "a command that
touches the record is a request like every other, and there is no second way
in." M2 deepens `config/cli.py` using its existing `Act`, transport, validation
and registration machinery, and **`--local` is removed from the plan entirely**;
no direct SQL fallback is designed or wanted.

### 3 (P1): the conversations-off behaviour contradicts the running system

The plan claims conversations-off means no `record` schema and proposes a
refusal. Boot migrates that schema whether or not recording is on, reads work
without a writer, and a deployment that never recorded gets ordinary empty
shapes.

*Resolution*: accepted, and the proposed refusal would have reversed a settled
contract. `conversations/api.py` states it as a deliberate change under #283:
"an empty list is the honest answer", and "both work with recording off, where
there is no `ConversationStore` and no engine to borrow." So: **conversations-off
stops new writes and keeps serving whatever aggregate history survives; a
never-recorded deployment returns an ordinary empty result**, rendered by the
CLI's existing empty-result sentence. No switch state is added to `ApiRuntime`
and no current configuration is inferred from stored rows.

### 4 (P1): the request contract is undecided

No parameter names, defaults, bounds, boundary semantics, ordering, empty-result
behaviour, response envelopes, per-device view names, or `GET /metrics` shape.

*Resolution*: accepted; "bounded windowing" was a promise standing in for a
design. Specified in full in "The request contract" below, and the tests section
gains boundary, malformed-value, default, ordering and empty-window cases rather
than only the oversized-window one.

### 5 (P1): dynamic view selection has no closed mapping and no no-leak test

`/metrics/{view}` is request-controlled relation selection, and a relation name
cannot be a bound parameter.

*Resolution*: accepted whole. The path value resolves through a **closed
alias-to-declaration mapping derived from the view registry**, so an unknown
alias never reaches SQL and the set of servable views cannot drift from the set
of declared ones. Unknown views and groupings get fixed sanitized refusals that
quote nothing back, per the rule `conversations/api.py` already states. The
tests send hostile and control-character values through both the API and the
CLI and assert they appear in no response, no stderr and no emitted record.

### 6 (P2): the snapshot follow-up rests on wrong scheduling and retention assumptions

`_prune` runs at writer start and after session close, **deletes first**, and
does not run at all when `retention_days <= 0`; recording-off starts no writer.
So a quiet deployment has something to lose immediately before the startup
prune, and old turns can survive in active conversations whose events are
already gone.

*Resolution*: accepted, and the mechanism paragraph is deleted rather than
patched. The plan overreached by designing a follow-up it had not verified. What
replaces it is the constraint list any future snapshot design has to satisfy: it
must run **before** destructive pruning, work with recording disabled and with
retention zero, carry its own retention and erasure behaviour, and preserve
whether a rate was already only a floor. This issue serves live views over
whatever rows survive the store's asymmetric retention, and says so.

### 7 (P2): response-model ownership is omitted

Conversation response shapes live in `config/responses.py` so the CLI can
validate them without importing FastAPI, SQLAlchemy or the store.

*Resolution*: accepted. The transport models go in `config/responses.py` and are
imported by both `conversations/api.py` and `config/cli.py`, which uses the
existing deep module and adds none. The API-to-CLI contract coverage extends to
them.

### 8 (P2): the caveat-preservation mechanism cannot prove its guarantee

`View` declares `question`, `denominator`, `telemetry_off`, columns and SQL. The
retention-floor limit is hand-written common prose in the reference, so it
cannot be generated into an API or CLI description today. Drift checks prove an
artifact matches its generator, never that the generator kept anything. And
telemetry-off produces no latency row at all while event-rate denominators
survive and numerators vanish, so "rows report coverage" is not uniformly true.

*Resolution*: accepted; "where possible" was doing too much work. The common
limitations move into **declared metadata on the view registry**, with consumers
in docgen, in the OpenAPI descriptions and in the CLI's output, so one home
feeds three surfaces. The tests become semantic rather than structural: assert
the zero-denominator rule, the retention-floor warning, the
missing-measurement ambiguity and **each view's own** telemetry-off behaviour
appear on both first-party surfaces.

### 9 (P2): the null-device test would miss a broken full join

The event-rate and sessions views combine independently aggregated streams with
full outer joins, and ordinary equality does not join two SQL nulls. Asserting
"no device is invented" would pass an implementation emitting three separate
null-device rows.

*Resolution*: accepted, and it is the sharpest finding of the round. Per-device
streams join with **`IS NOT DISTINCT FROM`**, coalescing both the day and the
device keys. The test drives one null-device session that contributes a turn and
a counted event and asserts **exactly one** combined row with correct
denominators and rates.

### 10 (P2): upgrade-safe migration and required documentation are missing

M3 does not say whether views are replaced or additive, nor name the new
relations; the CHANGELOG the issue requires is absent from the milestones; the
observability map still records #440 as open; and the API's hand-authored
overview is embedded into the generated OpenAPI.

*Resolution*: accepted. **The per-device views are additive siblings with names
of their own**, the four shipped contracts are preserved byte for byte, and a
test upgrades a database at `1006_metrics_views` and asserts the originals
survive and still answer. Downgrade behaviour and the analyst grants are stated.
`CHANGELOG.md`, `docs/architecture/observability-surfaces.md` and
`config/api_descriptions/api.md` are named in the milestones that touch them.
