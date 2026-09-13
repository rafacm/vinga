"""A turn says which utterance it answers

One nullable column and nothing else: no table, no index, no row
rewritten. `turns.utterance` is the id the server minted when the turn
opened, which is the name the trace knows that turn by.

It exists because the two sides of a turn count turns differently, and
both are right. The exporter opens one turn span per utterance. This
store writes one row per turn and conversation, so a reply that hands
over is two rows here and one span there. Nothing the two already
shared could bridge that: the ordinals count different things, and the
offsets are stamped at different instants, the span at the moment the
user stopped speaking and `t_ms` at the `heard` that lands after the
ASR stage returns. The measured gap between those two was the ASR
stage itself, hundreds of milliseconds on a real provider. So the two
sides are given one name for the utterance instead, minted once where
the turn begins and written on every row that turn produces.

Nullable, and there is no backfill. There is nothing to backfill WITH:
the id is minted at a turn's open and a turn already recorded never
had one, so any value written here afterwards would be invented. A
null therefore reads as "this row cannot be correlated to a trace",
which covers a turn recorded before this column existed, a store
driven by a suite that mints no utterances, and the turn a session
installs at its first activation before anything has been heard.

An existing database upgrades and keeps every row. What the recorded
compatibility stance licenses is the absence of a backfill, not a
refusal to boot: a pre-upgrade row reads null here and cannot name a
trace, which is the same "no target" answer the correlation already
gives for a context that has aged out of the exporter's retention.
`Telemetry.turn_context` takes the null as readily as a key it has
never seen, so a reader that joins on this column has one no-target
path rather than a legacy branch beside it.

The comment is spelled out below rather than imported from
`conversations.schema`, for the reason 1003, 1004, 1006 and 1007 give:
a migration is a record of what happened, and one reading its strings
out of the current declaration would rewrite its own history every
time that declaration moved. What holds the two equal is
`tests/unit/test_conversations_schema.py`, which compares the migrated
database with the metadata through Alembic's own autogeneration,
comments included.

Downgrade drops the column, which loses the correlation recorded since
the upgrade and nothing else: every row's dialogue, timing and thread
are untouched by both directions.

Revision ID: 1010_turns_name_their_utterance
Revises: 1009_views_read_the_name
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1010_turns_name_their_utterance"
down_revision: str | None = "1009_views_read_the_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "record"

COMMENT = (
    "The utterance this turn answers, as the server minted it when the "
    "turn opened. The name the trace knows the turn by: the exporter "
    "opens one turn span per utterance and retains that span's context "
    "under this id, so a reader holding this row can find the turn's "
    "own trace without counting rows or comparing clocks. A handover "
    "writes two rows here and both carry the same value, because both "
    "answer one utterance; that is the one correlation that survives a "
    "move. Metadata rather than content, and null for a turn no "
    "utterance opened or a row written by a suite of its own."
)


def upgrade() -> None:
    op.add_column(
        "turns",
        sa.Column("utterance", sa.Text(), nullable=True, comment=COMMENT),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("turns", "utterance", schema=SCHEMA)
