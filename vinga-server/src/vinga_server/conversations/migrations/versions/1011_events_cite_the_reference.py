"""The event-name column names the generated event reference

A comment and nothing else: no column, no row, no index and no type
moves. `record.events.name` used to say its vocabulary was the one "the
README's table defines", and the server README no longer carries that
table: the index of events moved to the logs and traces task guide, and
what each event carries has been the generated event schema reference
since the declarations became the catalog. So the column now names the
reference, which is the document generated from the same declarations
the events are emitted from.

The declaration in `conversations/schema.py` moved in the same change,
and so did the generated `docs/reference/conversations-schema.md`, but
neither reaches a database that was migrated before it: Postgres keeps
a column comment as the database's own description of itself, and it
moves only when a migration sets it. Without this revision an upgraded
deployment would go on describing the column by a table that is gone,
while a fresh one described it correctly.

The comments are spelled out rather than imported from
`conversations.schema`, for the reason 1003 to 1010 give: a migration
is a record of what happened, and one reading its strings out of the
current declaration would rewrite its own history every time that
declaration moved. `1002_conversation_threads.py` keeps the old text
for the same reason. What holds the declaration and the migrated
database equal is `tests/unit/test_conversations_schema.py`, comments
included; `tests/integration/test_event_name_comment_upgrade.py` is the
upgrade from 1010 and the downgrade back.

Downgrade restores the old text literally, which is the whole of the
inverse.

Revision ID: 1011_events_cite_the_reference
Revises: 1010_turns_name_their_utterance
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1011_events_cite_the_reference"
down_revision: str | None = "1010_turns_name_their_utterance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "record"

BEFORE = "The event name, from the event vocabulary the README's table defines."

AFTER = (
    "The event name, from the event vocabulary the generated event schema "
    "reference (docs/reference/events.md) defines."
)


def upgrade() -> None:
    op.alter_column(
        "events",
        "name",
        existing_type=sa.Text(),
        existing_nullable=False,
        comment=AFTER,
        existing_comment=BEFORE,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.alter_column(
        "events",
        "name",
        existing_type=sa.Text(),
        existing_nullable=False,
        comment=BEFORE,
        existing_comment=AFTER,
        schema=SCHEMA,
    )
