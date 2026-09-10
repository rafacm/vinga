"""The recorded provider entries are per agent

One column comment and nothing else. `sessions.providers` used to hold
the current agent's entries, one per pipeline stage, serialized from the
configured `ProviderConfig` with its secret-shaped values masked. #66
replaced that with the sanitized derivation `session_open` also carries:
per bound agent, per stage, the built provider's name, type, host and
model, and nothing else off an entry at all. So the column holds a map
one level deeper than it did, and what it says about itself follows.

A migration whose whole content is a comment is priced the way 1003 and
1004 are: the comment is committed DDL, so a database migrated by an
earlier build keeps describing itself the old way until something
changes it there, and the baseline-equality test compares column
comments through Alembic's own autogeneration, so the declarations and
the migrated database move together or that test fails. It is
forward-only in effect and it moves no row.

Rows written before this are not rewritten, and that is deliberate: a
session record says what that session was held against, and rewriting
one to a shape it never had would be inventing what an old conversation
ran on. A reader meeting both shapes tells them apart by their depth.

`docs/reference/conversations-schema.md` is rendered from these comments
and regenerates with it.

The old text is spelled out below rather than imported from
`conversations.schema`, for the reason 1003 gives: a migration is a
record of what happened, and one reading its strings out of the current
declaration would rewrite its own history every time that declaration
moved.

Revision ID: 1005_providers_are_per_agent
Revises: 1004_telemetry_names_the_switch
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1005_providers_are_per_agent"
down_revision: str | None = "1004_telemetry_names_the_switch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "record"

BEFORE = (
    "The resolved provider entry per pipeline stage, the same structure "
    "the capture manifest carries. Holds environment variable names, "
    "never credentials."
)

AFTER = (
    "The resolved provider entries this session opened against, by agent "
    "and then by pipeline stage: each one the entry's name, its type, and "
    "the host and model where the type has them. The same structure the "
    "capture manifest carries. Four names off the built provider and "
    "nothing else off its configuration, so no option and no credential "
    "can be in it."
)


def upgrade() -> None:
    op.alter_column(
        "sessions",
        "providers",
        existing_type=sa.JSON(none_as_null=True),
        existing_nullable=True,
        comment=AFTER,
        existing_comment=BEFORE,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.alter_column(
        "sessions",
        "providers",
        existing_type=sa.JSON(none_as_null=True),
        existing_nullable=True,
        comment=BEFORE,
        existing_comment=AFTER,
        schema=SCHEMA,
    )
