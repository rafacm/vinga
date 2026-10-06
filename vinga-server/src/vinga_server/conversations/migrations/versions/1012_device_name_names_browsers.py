"""The device-name column says a browser nobody has named records null

A comment and nothing else: no column, no row, no index and no type
moves. `record.sessions.device_name` said its null covered "a board
nobody has named". A try link binds a browser as `Browser <mac>`, a
placeholder the server mints exactly as it mints `Device <mac>` for a
board (#613), and a session opened on a browser nobody has named
records null the same way. So the column says "a board or a browser".

The declaration in `conversations/schema.py` moved in the same change,
and so did the generated `docs/reference/conversations-schema.md`, but
neither reaches a database that was migrated before it: Postgres keeps
a column comment as the database's own description of itself, and it
moves only when a migration sets it.

The comments are spelled out rather than imported from
`conversations.schema`, for the reason 1003 to 1011 give: a migration
is a record of what happened, and one reading its strings out of the
current declaration would rewrite its own history every time that
declaration moved. `1007_sessions_name_the_device.py` keeps the old
text for the same reason. What holds the declaration and the migrated
database equal is `tests/unit/test_conversations_schema.py`, comments
included; `tests/integration/test_device_name_comment_upgrade.py` is the
upgrade from 1011 and the downgrade back.

Downgrade restores the old text literally, which is the whole of the
inverse.

Revision ID: 1012_device_name_names_browsers
Revises: 1011_events_cite_the_reference
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1012_device_name_names_browsers"
down_revision: str | None = "1011_events_cite_the_reference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "record"

_LEAD = (
    "What that device was called when this session opened, exactly as an "
    "operator wrote it. A copy rather than a join, and the one column here "
    "that is a copy of something next door: `deploy/postgres-init.sql` "
    "grants `vinga_ro` this schema and revokes it on `domain`, so an "
    "analyst grouping sessions by device can reach a name only if this "
    "side carries one. Dated like `agent` beside it and never rewritten, "
    "so a rename splits a per-device series here rather than retitling the "
    "sessions the device already had, and replacing its board does not "
    "touch it either. Null wherever no name is recorded for the session: a "
)

BEFORE = (
    _LEAD + "board nobody has named, a MAC a default agent covers with no record "
    "behind it, and every session that opened before this column existed."
)

AFTER = (
    _LEAD + "board or a browser nobody has named, a MAC a default agent covers with "
    "no record behind it, and every session that opened before this column "
    "existed."
)


def upgrade() -> None:
    op.alter_column(
        "sessions",
        "device_name",
        existing_type=sa.Text(),
        existing_nullable=True,
        comment=AFTER,
        existing_comment=BEFORE,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.alter_column(
        "sessions",
        "device_name",
        existing_type=sa.Text(),
        existing_nullable=True,
        comment=BEFORE,
        existing_comment=AFTER,
        schema=SCHEMA,
    )
