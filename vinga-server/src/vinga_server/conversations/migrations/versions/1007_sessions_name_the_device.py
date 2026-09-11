"""A session says what its device was called

One nullable column and nothing else: no table, no index, no row
rewritten. `sessions.device_name` is what the board was called at the
instant the session opened, beside the MAC that says which board it
was.

A copy of something next door, which every other column here is not,
and it is the grant that makes it necessary rather than redundant.
`deploy/postgres-init.sql` grants `vinga_ro` USAGE and SELECT on this
schema and then explicitly REVOKES both on `domain`, so the analyst
role, and any dashboard reading as it, can never join to
`domain.devices`. A per-device board grouped by MAC is what an analyst
gets unless this side carries the name itself.

Nullable, and there is no backfill. Two reasons, and the first is the
column's whole contract: this is a dated value, like `sessions.agent`
beside it, so it says what was true when the row was written and
nothing rewrites it afterwards. A backfill would stamp the name a
device has NOW onto sessions that opened before the column existed,
which is the one thing the column promises not to do. The second is
that there is nothing honest to stamp anyway: `domain.devices` gained
its `name` in `3003_device_record` on a different chain, and the name
it holds today is either something an operator chose after the fact or
the `Device <mac>` placeholder that migration minted.

So a null here reads as "no name is recorded for this session", and it
covers three real states that a reader treats alike: a board nobody
has named, a MAC a default agent covers with no device record behind
it, and a session that opened before this migration ran. A dashboard
falls back to the MAC for all three, which is what it did for every
session before this column.

The comment is spelled out below rather than imported from
`conversations.schema`, for the reason 1003, 1004 and 1006 give: a
migration is a record of what happened, and one reading its strings
out of the current declaration would rewrite its own history every
time that declaration moved. What holds the two equal is
`tests/unit/test_conversations_schema.py`, which compares the migrated
database with the metadata through Alembic's own autogeneration,
comments included.

Downgrade drops the column, which loses the names recorded since the
upgrade and nothing else: every row's device, agent and timeline are
untouched by both directions.

Revision ID: 1007_sessions_name_the_device
Revises: 1006_metrics_views
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1007_sessions_name_the_device"
down_revision: str | None = "1006_metrics_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "record"

COMMENT = (
    "What that device was called when this session opened, exactly as an "
    "operator wrote it. A copy rather than a join, and the one column here "
    "that is a copy of something next door: `deploy/postgres-init.sql` "
    "grants `vinga_ro` this schema and revokes it on `domain`, so an "
    "analyst grouping sessions by device can reach a name only if this "
    "side carries one. Dated like `agent` beside it and never rewritten, "
    "so a rename splits a per-device series here rather than retitling the "
    "sessions the device already had, and replacing its board does not "
    "touch it either. Null wherever no name is recorded for the session: a "
    "board nobody has named, a MAC a default agent covers with no record "
    "behind it, and every session that opened before this column existed."
)


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("device_name", sa.Text(), nullable=True, comment=COMMENT),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("sessions", "device_name", schema=SCHEMA)
