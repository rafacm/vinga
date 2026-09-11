# A first-party read over the phase-1 aggregates: implementation

Companion to [`2026-09-11-metrics-read-surface.md`](2026-09-11-metrics-read-surface.md).
One section per milestone, appended in the same change that ticks the
milestone checklist: deviations from the plan, resolutions of its open
questions, and what was discovered on the way.

## M1: the aggregates on the API

PR TBD.

### What landed

`GET /metrics` and `GET /metrics/{view}` on the gated `/api`, registered
from `conversations/api.py` by `config/api.py`'s `_application()` like
the session and thread reads beside them, so a route that is served is a
route the committed document carries.

`GET /metrics` is the registry rather than the store. It lists the four
views in declaration order, each with its alias, its schema-qualified
relation, its question, its denominator sentence, its own telemetry-off
sentence and its full column matrix, and it carries the statements that
hold for all of them. It takes no reader at all and opens no connection,
so it answers the same thing on a deployment that never recorded.

`GET /metrics/{view}` answers one view over one window. The request
contract as implemented:

| parameter | accepts | default | bound |
| --- | --- | --- | --- |
| `since` | a UTC day, `YYYY-MM-DD`, the window begins on it | 30 days before `until` | with `until`, at most 366 days |
| `until` | a UTC day, `YYYY-MM-DD`, the window ends on it | the server's current UTC day | not before `since` |
| `group` | a word from a closed set, `all` today | `all` | closed set |

Both ends are included, so a window of one day spans one day and the
default window is 31 days: the day named and the 30 before it. The cap
is 366, one leap year, and a wider window is **refused rather than
narrowed**: an answer trimmed to fit would be less than what was asked
for while nothing in it said so. The two days the answer used are
repeated in the body, so a caller that sent neither reads the defaults
off what came back instead of recomputing the server's own day.

Rows come back ordered by `day` descending and then by the view's other
key columns ascending with nulls last. An empty window is an ordinary
empty list with its window stated, and so is a deployment that never
recorded: no refusal, no 404.

The refusals are the module's existing rule, a fixed sentence that
quotes nothing back. An unknown view is a 404 saying that `GET /metrics`
lists the ones that are served; a day that is not an extended-form UTC
calendar day, a window whose ends are out of order or too far apart, and
a grouping nothing serves are 422s naming the argument whose rule was
broken. `METRICS_PROBLEMS_INSTEAD` gives this namespace its own 404, 422
and 500 sentences, because nothing here is addressed by an id and
nothing here writes.

### The five findings the review round turned into this milestone

**1. The closed mapping is derived from the registry.** `View.alias`
strips the `metrics_` prefix and the `_daily` suffix every view's name
carries and kebab-cases what is left, and `views.ALIASES` is
`{view.alias: view for view in VIEWS}`. `conversations/api.py:_view()`
is a `dict.get` on it and raises `UnknownEntityError` on a miss. Nothing
else in the request path touches the caller's bytes: the query is built
by `_relation()` from the declaration's own name and column names, so a
value that resolves to no declaration reaches no query builder, no
connection and no log. Deriving the mapping rather than writing it
beside the registry is what stops the servable set drifting from the
declared set, and a test asserts the derivation and the four aliases.

**2. Transport models are in `config/responses.py`.** `MetricCaveats`,
`MetricColumn`, `MetricView`, `MetricViews` and `MetricRows`, beside the
conversation shapes and for the same reason: the CLI in M2 validates an
answer against the shape the API said it would send without importing
FastAPI, SQLAlchemy or the store. `GROUPINGS` lives there too, so the
set a request is held to and the set the document publishes are one
tuple rather than two that must agree.

**3. Conversations-off keeps serving.** Nothing was added to
`ApiRuntime` and no switch state is inferred from stored rows. The reads
take the existing per-request reader, which opens its own connection
through `db.read_engine`, so they work with recording off where there is
no `ConversationStore` to borrow an engine from. Two cases pin it: a
deployment that never recorded answers empty lists on all four views,
and a server composed with recording off (asserting
`app.state.composition.conversations is None`) still serves the rows
planted before the switch moved.

**4. Telemetry-off is asserted per view.** One case writes a session
through the real `ConversationStore` with `telemetry=False` and asserts
all four views in one breath: the latency view produces no row at all,
the event-rate view keeps both denominators and loses both numerators
(so its rate is 0.0, which is a measurement, because the null rule is
about a zero denominator and not a zero numerator), the token view
counts the turn with both sums null, and the baseline view counts the
session with `telemetry_sessions` at zero. Each view's own
`telemetry_off` sentence is what the surface reports, in the listing
body, in the answer body and in the document.

**5. The common limitations are declared metadata.** `views.COMMON` is a
tuple of `Caveats(heading, notes)`, carrying the four reading rules and
the three limits verbatim. `docgen.views_reference()` renders them
instead of spelling them, which is why the committed reference did not
move a byte for that half; `docgen.views_description()` renders them
again, with each view's question and telemetry-off sentence, as the 200
description of `GET /metrics/{view}`; and both routes serve them in
their bodies, which is the third consumer M2's CLI reads them through.
The retention-floor limit, which the round found unreachable from
anywhere but the renderer, is now on the API contract and in every
answer.

### Deviations from the plan

**`group` accepts `all` only, not `all` or `device`.** The plan's
request-contract table lists both, and its M3 delivers the per-device
views, the `group=device` behaviour and the `device` parameter. There
are no per-device relations until that migration lands, so a second
token could be documented but never answered, and a published
vocabulary that always refuses is worse than one that grows. So M1
publishes the parameter with the closed set it can serve, generated from
`GROUPINGS`, and M3 appends to that tuple: the refusal sentence, the
parameter description and the document's own enum are all built from it
and move together. The `device` parameter is M3's for the same reason.

**The ordering is generalized from "day descending, then device
ascending nulls last".** That ordering is not total on the four shipped
views, which have dimensions of their own: the latency view is one row
per day, agent and stage, and the token view one row per day and agent.
So `Column` gained a declared `key` flag, the view's `GROUP BY` said as
a declaration, and the read orders on `day` descending then every other
key column ascending with nulls last. On the shipped views that is
total; once M3's `device` is a key column it is exactly the ordering the
plan names. The reference states each view's keys, so the declaration is
documented rather than merely used.

**A third renderer in `docgen`.** The plan's module layout names no new
module and none was added, but `docgen` gained `views_description()`
beside `reference()` and `views_reference()`. It is the same
responsibility, writing a declaration out for a person, and the
alternative was a second copy of the caveats inside the transport code.
The route's own prose stays its docstring, which is the repository's
rule; the generated block is the operation's `response_description`,
which is where "what this answer means" belongs.

**Two test helpers moved to `tests/support`.** `plant_session`,
`plant_turn` and `plant_event` were local to
`tests/integration/test_conversations_views.py`. A second suite plants
now, so they moved to `tests/support/stores.py` under the repository's
rule that no test module imports another. Nothing about them changed.

### Discoveries

**`_before` and the metrics days are one rule.** The session purge's
`before` selector already parsed an extended-form UTC day, refusing the
`20260815` and `2026-W33-1` spellings `fromisoformat` would otherwise
accept. `since` and `until` need exactly that, so `_utc_day()` is one
home for it and `_before` now reads it rather than repeating it.

**A one-token `Literal` is `const` in JSON Schema, not `enum`.**
Pydantic renders `Literal["all"]` as `{"const": "all"}` and only
switches to `enum` with a second member. The document pin reads either
spelling, so it keeps holding when M3 adds the second grouping.

**The listing needs no 500.** It declares 401 and nothing else, because
it opens no store and cannot fail for a reason that is not the
caller's.

### Verification

- `uv run ruff check .` and `uv run mypy` clean; `uv run pytest
  tests/unit -q -n 4 --dist loadfile` 6232 passed, 19 skipped; `uv run
  pytest tests/integration -q` 282 passed. The lane runs `-n 4` rather
  than `-n auto` on this machine, which exceeds the compose Postgres's
  connection limit.
- `uv run vinga-server conversations views` and `uv run vinga-server
  config openapi` diffed against the committed references, which is what
  CI's two drift checks run.
- The document pins in `tests/unit/test_api_openapi.py`: the two routes,
  every field of the five shapes required, `MetricColumn`'s fields held
  equal to the registry's `Column`, the four parameter descriptions, the
  grouping vocabulary, and the semantic assertion that the
  zero-denominator rule, the retention-floor warning, the
  missing-measurement ambiguity and each view's own question and
  telemetry-off sentence are in the contract a client reads.

### Not done here

M2's CLI and M3's device dimension, as planned. The observability map
still records #440 as open, which M3 closes.
