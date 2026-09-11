"""The tables holding the domain half of the configuration.

One entity is one row, and the row holds three kinds of thing. The
columns that carry identity, because a key has to be selectable and
unique. The `body`, which is the entity's pydantic model dumped as
JSON and validated back through the same model on read: every field
the model declares, and for a pass-through model every extra beside
them, lives there and nowhere else. And, on the two kinds that can
hold one, the `secrets` column, which never carries anything the model
knows about.

No non-key model field has a column of its own. That is the point
rather than an omission: a field used to mean a column, a migration
and two hand-written mapper arms, and the four of them had to agree
about a tri-state or a default that only one of them stated. Adding a
field is now a change to the model, to the entity's example fragment
under `examples/`, and to the two generated reference artifacts, each
rebuilt by its own command.

A field can earn a column back, and the way it earns one is by needing
SQL. The first field something has to filter, join or index on gets a
column through `alembic revision --autogenerate` (runnable through
`vinga_server.db.migrations.autogen`), which reads the metadata below
and writes the candidate migration; the body keeps holding it, and the
column is a derived index rather than a second home for the value.
Nothing needs one today: the four reshaped tables are read whole and
assembled in Python.

The body is `Text` and not `JSON`. A `JSON` column would encode the
already-dumped string a second time, storing a quoted literal that no
`json_extract` can see into and that reads back as a string rather
than an object; `Text` is what `model_validate_json` is handed.

`devices` and `domain_settings` hold no body, and neither is an
omission. A setting row is a scalar read as a JSON value rather than as
a dumped model. A device row is columns all the way, and #449 is the
change that made it so: `id` and `mac` are identity, `name` needs SQL
because its uniqueness is a functional index over a fold, and
`location` has nowhere else to go on a table that has never had a body.
The device lookup path selects `devices.c.agents` by MAC on a
connection that never migrates, which is why `mac` stayed unique and
selectable when it stopped being the key.

Referential integrity lives in the repository rather than in database
foreign keys: validation is single-sourced in the model/repository
layer, the layer the REST API uses too, and a constraint here would
duplicate half of those checks in a second place that knows less about
what a reference means.

Encrypted secrets never sit in a body. Each secret-bearing entity has
its own `secrets` JSON column mapping a credential slot to an
envelope, so replacing an entity does not touch its stored secrets and
a body written by a fragment that cannot carry ciphertext cannot erase
one.
"""

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Index,
    MetaData,
    Table,
    Text,
    text,
)

from vinga_server.config.models import device_name_fold_sql

# Named constraints and indexes, so a later migration can address them.
# A constraint Postgres named for itself is one a migration has to look
# up before it can drop it, and a name that a convention produces is one
# both sides can write down.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}

# The schema these tables live in, carried on the metadata rather than
# arranged with a `search_path`: which schema a table is in is a fact,
# and a fact has one home. It is also the seat of this chain's Alembic
# version table, which is what keeps the two chains apart inside one
# database, and the boundary the read-only analyst role is scoped
# outside of, because the `secrets` columns below are here.
SCHEMA = "domain"

metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)

# The one row agent_defaults may hold. The value is arbitrary and never
# shown; the check constraint on it is what makes the singleton a
# property of the schema rather than a convention in the repository.
AGENT_DEFAULTS_ID = "singleton"

providers = Table(
    "providers",
    metadata,
    # A provider is identified by its stage and its name together: two
    # stages may each define a "local" entry, and they are different
    # providers.
    Column("stage", Text, primary_key=True),
    Column("name", Text, primary_key=True),
    # The dumped ProviderConfig: its declared fields and the
    # pass-through options together, which is what the model itself
    # holds and so what a reader of the row gets back.
    Column("body", Text, nullable=False),
    # Option name to secret envelope, empty by default.
    Column("secrets", JSON, nullable=False, default=dict),
)

mcp_servers = Table(
    "mcp_servers",
    metadata,
    Column("name", Text, primary_key=True),
    # The dumped McpServerConfig. Values in its env and headers are
    # literal strings or today's $VAR reference strings, never
    # envelopes: an encrypted value lives in the secrets column below
    # under its dotted path, which is what keeps the body loadable into
    # McpServerConfig as is.
    Column("body", Text, nullable=False),
    # Dotted path (env.API_TOKEN, headers.Authorization) to envelope.
    Column("secrets", JSON, nullable=False, default=dict),
)

# The shared blocks of prompt text agents include by name: the name a
# layer references, and the dumped PromptFragmentConfig holding the
# text as it was written, because that is what the model is given.
prompt_fragments = Table(
    "prompt_fragments",
    metadata,
    Column("name", Text, primary_key=True),
    Column("body", Text, nullable=False),
)

agent_defaults = Table(
    "agent_defaults",
    metadata,
    Column("id", Text, primary_key=True),
    Column("body", Text, nullable=False),
    CheckConstraint(f"id = '{AGENT_DEFAULTS_ID}'", name="singleton"),
)

agents = Table(
    "agents",
    metadata,
    Column("name", Text, primary_key=True),
    Column("body", Text, nullable=False),
)

# The name of the functional unique index below, written down because
# it is not a name any convention above can produce: the conventions key
# off a column and this index is over an expression.
DEVICE_NAME_INDEX = "uq_devices_folded_name"

# An entity table rather than bare binding rows, so the per-device
# runtime field (#92 stage 1) is an additive column on a row that
# already exists rather than a reshaping. Nothing runtime-shaped is
# built here.
#
# Four of these five are columns rather than a body, and each earned one
# by the rule this file states. `id` and `mac` are identity, and both
# have to be selectable and unique. `name` needs SQL, because uniqueness
# folds case and whitespace and the fold is enforced by the index below
# rather than by a promise in the repository. `agents` predates the body
# convention and is read as a JSON value rather than as a dumped model,
# which is what the file's opening paragraph says about this table.
#
# `location` is the one that did not earn a column and has one anyway,
# and the reason is that there is no body here to put it in: this table
# has never had one, and inventing a body for a single nullable string
# would be a second shape for one row.
#
# Devices get no `Identity()` row id at all, unlike the recorded
# sessions and conversations that share the uuid-hex convention. These
# rows are read whole and assembled in Python, so a cursor id would be a
# column with no reader.
devices = Table(
    "devices",
    metadata,
    # An application-minted uuid hex, so the identity travels through
    # export, import and apply. The MAC used to be the key and is not,
    # because a board can be replaced and its record should not have to
    # be: a row identified by the hardware cannot outlive it. That
    # replacement is `ConfigStore.replace_device` (#449 M4), which
    # rewrites this row's `mac` and moves what that board remembered
    # onto the new address in the same transaction; what the column
    # buys the rest of the time is a record whose identity does not move
    # when its name, its place or its bindings do.
    Column("id", Text, primary_key=True),
    # Still unique and still selectable, deliberately: `_live_binding`
    # selects `agents` by MAC on the connection that never migrates, and
    # that statement is pinned byte for byte
    # (`tests/unit/test_live_binding_pin.py`).
    Column("mac", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("location", Text),
    Column("agents", JSON, nullable=False),
    # Unique on the FOLDED name and not on the name, so `Kitchen
    # Speaker` and `kitchen  speaker` are one name while the row keeps
    # exactly what the operator typed. The repository checks the same
    # fold under the writer lock and answers with a refusal an operator
    # can act on; this index is the invariant standing behind it, which
    # is what makes the promise true for a writer that never asked.
    Index(DEVICE_NAME_INDEX, text(device_name_fold_sql("name")), unique=True),
)

# Domain-level scalars, default_agent being the only one today. A
# key/value table so the next one does not need a migration of its own.
domain_settings = Table(
    "domain_settings",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", JSON, nullable=False),
)

DEFAULT_AGENT_KEY = "default_agent"
