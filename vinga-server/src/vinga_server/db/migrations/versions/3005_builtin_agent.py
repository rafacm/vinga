"""Add the built-in agent's overrides table

#612 makes vinga, the built-in agent, the default agent of every
deployment. It is composed by the server from the build it ships in and
is never a stored agent, but an operator still chooses its providers,
its voice and the fragments its prompt carries, and those choices live
here: one row, shaped exactly like `agent_defaults`, written and read
the same way (`vinga builtin-agent set`, export, import, apply).

A table of its own rather than an `agents` row named vinga, which was
the first draft and is the reason this is a migration at all: a stored
agent of that name could not be told apart from an operator's agent
that predates the built-in, a blank one least of all, so the overrides
have their own key and any stored `agents.vinga` stays an operator's.

Structural and nothing else, so autogenerate could have written it; it
is written by hand only to carry this docstring, and it matches what
`db/schema.py` declares, which `test_db_autogen` compares.

Nothing is backfilled: an absent row is the empty override, which is
what `read_builtin_agent` answers for it, so every deployment upgrading
into this release reads the same configuration it did, with vinga
inheriting everything from `agent_defaults`.

Revision ID: 3005_builtin_agent
Revises: 3004_reach_replaces_egress
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3005_builtin_agent"
down_revision: str | None = "3004_reach_replaces_egress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "builtin_agent",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.CheckConstraint("id = 'singleton'", name=op.f("ck_builtin_agent_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_builtin_agent")),
        schema="domain",
    )


def downgrade() -> None:
    op.drop_table("builtin_agent", schema="domain")
