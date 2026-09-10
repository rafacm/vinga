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

### Addressing: `metrics` is its own noun, and the name is a citation

The noun is `metrics`, not `stats`. This is settled by the repository rather
than by preference: the changelog entry for #437, which renamed the storage
switch to `telemetry`, says the rename happened because "it is a storage privacy
switch, `metrics` is reserved for the future aggregation surface". This is that
surface. The views are `metrics_*_daily` and the generated reference is
`metrics-views.md`, so `metrics` already has one meaning here and this uses it.

**Plural, and it addresses no entry**, which puts it with `conversations` and
`events` under the CLI guide's rule: singular when a noun addresses one entry,
plural when it is a collection you only ever ask about as a whole. A day's
aggregate is not an entity with an identity.

**The grammar is `vinga metrics list` and `vinga metrics show <view>`.** The
guide forbids a noun in the verb slot ("a noun in the verb slot reads as a
possessive and hides what the command does"), so `vinga metrics latency` is
excluded however natural it reads, and #223's `agent preview` is the precedent
for taking that rule seriously rather than granting the first exception asked
for. `list` and `show` are core-set verbs, and the view name is a leading
positional, which is identity addressing in the guide's sense.

The view names drop the prefix and suffix they all share: `stage-latency`,
`tokens`, `event-rates`, `sessions`. Kebab-case per the guide, and the help says
which view each is, so the two are visibly the same thing.

On the API: `/metrics` and `/metrics/{view}`, beside `/sessions` and
`/conversations`. Worth one note for a future reader: `/metrics` is
conventionally a Prometheus scrape path, and this is not that. It sits under the
API's bearer token rather than on an unauthenticated scrape port, so the
collision is in spelling only, and a scrape endpoint, if one is ever wanted,
does not belong under `/api` anyway.

### The trend horizon: no snapshots in this issue, and the design recorded so it is not re-derived

The issue calls this its real design work, so this is a decision with reasons
rather than a deferral.

**No snapshot table now.** Three reasons, in order of weight:

1. **The consumers do not exist yet.** The admin UI (#129) and budgets are what
   would say what grain a snapshot needs, and neither is built. Snapshotting the
   wrong grain is more expensive than not snapshotting, because a durable table
   with rows in it is what nobody can change their mind about.
2. **`retention_days` defaults to 90.** There are three months of slack before
   any data ages out of the live views, so deferring costs nothing measurable
   now and buys the information above.
3. **A snapshot would freeze a caveat rather than fix it.** The views already
   say that a rate read outside the events' own retention window is a floor and
   not a measurement, because the database cannot tell zero events from events
   already pruned. A snapshot taken today inherits that and then makes it
   permanent and unlabelled.

**The shape is decided anyway, so this surface does not preclude it**, which is
the same commitment the issue already makes about a per-user key. Responses are
shaped so a snapshot-backed row is indistinguishable from a live one: every row
carries its `day` and its denominators, nothing in the response says "computed
live", and no windowing parameter is defined in terms of retention.

**And the mechanism is recorded, because it is the non-obvious part.** The
server has no periodic scheduler: the retention prune runs at writer start and
after each session close, event-driven. A snapshot writer needs no scheduler
either. At the same hook, if a completed UTC day has no snapshot row, write it
from the views. That is idempotent, needs no new machinery, and its only gap is
a deployment quiet for longer than retention, which is exactly the deployment
with nothing to lose. Filed as a follow-up with this paragraph in it rather than
built here.

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

A deployment with `server.conversations.enabled` off has no `record` schema to
read. That answers honestly rather than failing: the surface reports that the
conversation store is not enabled, in the CLI's fixed-refusal style and as a
documented API status, and never a 500 and never an empty result that reads like
"nothing happened". Telemetry off is the same shape one level down: the views
still exist and their rows report coverage, which is what the views' own
reference already says a measured count means.

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

- Reuse `tests/unit/test_conversations_api.py` and the view tests from #439
  rather than restating their fixtures.
- The windowing bounds: a window larger than the cap is refused with the fixed
  sentence, not silently clamped.
- The storage-switch answers, both levels, asserted as the sentence and the
  status rather than as "it did not crash".
- The per-device rows: two devices in one day, asserted to separate; a session
  with a null `device` asserted not to invent one.
- The generated-artifact drift checks, which CI runs and which a milestone that
  edits a reference by hand fails.

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
