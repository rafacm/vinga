"""The switch the numeric columns answer to is named telemetry

Column comments and nothing else. The storage switch that nulls every
measured number and skips the events rows was configured as
`server.conversations.metrics` and the comments spoke of it as
"metrics-off"; #437 renames the switch to `telemetry`, because
"metrics" is reserved for the future aggregation surface and the
content-and-telemetry ADR already names this substance telemetry. The
comments follow the switch. No column changes name or type:
`sessions.metrics` keeps the name it was born under, and only what it
says about itself moves.

A migration whose whole content is comments is priced the way
1003_rename_moves_ownership is: the comment is committed DDL, so a
database migrated by an earlier build keeps speaking the old vocabulary
until something changes it there, and the baseline-equality test
compares column comments through Alembic's own autogeneration, so the
declarations and the migrated database move together or that test
fails. It is forward-only in effect and it moves no row.

`docs/reference/conversations-schema.md` is rendered from these
comments and regenerates with it.

The old texts are spelled out below rather than imported from
`conversations.schema`, for the reason 1003 gives: a migration is a
record of what happened, and one reading its strings out of the current
declaration would rewrite its own history every time that declaration
moved. The new text of each comment is the old text with the three
spellings of the old name replaced, which is exactly what this rename
is, so the replacement table and the old texts together are the whole
record.

Revision ID: 1004_telemetry_names_the_switch
Revises: 1003_rename_moves_ownership
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1004_telemetry_names_the_switch"
down_revision: str | None = "1003_rename_moves_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "record"

# The rename, as the three phrases the comments spelled it in. Applied
# in this order; none of the right-hand sides contains a left-hand
# side, so the order cannot double-apply.
RENAMES: tuple[tuple[str, str], ...] = (
    ("metrics-off", "telemetry-off"),
    ("metrics storage", "telemetry storage"),
    ("metrics switch", "telemetry switch"),
)

# Every column whose comment spoke the old name: its table, its name,
# the type and nullability it already has, and what it said before this
# migration. What it says after is `_renamed` of that text.
COMMENTS: tuple[tuple[str, str, sa.types.TypeEngine, bool, str], ...] = (
    (
        "sessions",
        "duration_s",
        sa.Float(),
        True,
        "How long the session lasted, in seconds. A measured number: null "
        "under metrics-off.",
    ),
    (
        "sessions",
        "metrics",
        sa.Boolean(),
        False,
        "Whether metrics storage was on for this session, so a null number "
        "is distinguishable from a number that was never stored.",
    ),
    (
        "sessions",
        "dropped",
        sa.Integer(),
        False,
        "Records this session lost: events refused at the in-flight bound, "
        "and anything a failed transaction rolled back. Written at close, "
        "so the store records its own incompleteness the way the capture "
        "manifest records `complete`. Zero under metrics-off.",
    ),
    (
        "conversations",
        "incomplete",
        sa.Boolean(),
        False,
        "Whether a write this thread needed was lost, so a resume can say "
        "the record has gaps. Product state rather than telemetry, and "
        "therefore deliberately outside the metrics switch: "
        "`sessions.dropped` is zeroed under metrics-off and this is not. "
        "Written by the durable path, which arrives with the writer's "
        "acknowledgements; false in every thread until then.",
    ),
    (
        "turns",
        "heard_duration_s",
        sa.Float(),
        True,
        "How long the utterance lasted, in seconds. Null under metrics-off.",
    ),
    (
        "turns",
        "language_confidence",
        sa.Float(),
        True,
        "How sure the recognizer was of that language. Null under metrics-off.",
    ),
    (
        "turns",
        "legs",
        sa.JSON(none_as_null=True),
        True,
        "One entry per agent that took part in this turn, `{agent, text, "
        "input_tokens, output_tokens}`, present only when a handover split "
        "the reply. The text half is null under text-off and the token "
        "halves under metrics-off, because a turn's totals blend agents "
        "that may use different models.",
    ),
    (
        "turns",
        "asr_ms",
        sa.Integer(),
        True,
        "Transcription elapsed, in milliseconds. Null where no elapsed was "
        "measured this turn, and under metrics-off.",
    ),
    (
        "turns",
        "first_token_ms",
        sa.Integer(),
        True,
        "Request to first token of the reply, in milliseconds. Null under metrics-off.",
    ),
    (
        "turns",
        "llm_ms",
        sa.Integer(),
        True,
        "The reply's LLM round durations summed, in milliseconds. Null under metrics-off.",
    ),
    (
        "turns",
        "tts_first_audio_ms",
        sa.Integer(),
        True,
        "The reply's first synthesis request to its first audio bytes, in "
        "milliseconds, measured at the provider boundary and deliberately "
        "not at the device. Null when the reply spoke nothing, and under "
        "metrics-off.",
    ),
    (
        "turns",
        "rounds",
        sa.Integer(),
        True,
        "How many LLM rounds the reply took. Null under metrics-off.",
    ),
    (
        "turns",
        "input_tokens",
        sa.Integer(),
        True,
        "Input tokens summed across the turn's rounds; OTel's "
        "`gen_ai.usage.input_tokens`. Null when the provider reported no "
        "usage, and under metrics-off.",
    ),
    (
        "turns",
        "output_tokens",
        sa.Integer(),
        True,
        "Output tokens summed across the turn's rounds; OTel's "
        "`gen_ai.usage.output_tokens`. Null when the provider reported no "
        "usage, and under metrics-off.",
    ),
    (
        "tool_invocations",
        "duration_ms",
        sa.Integer(),
        True,
        "How long the call took, in milliseconds. Null where nothing ran, "
        "as for a refused or a successful handover, and under metrics-off.",
    ),
)


def _renamed(before: str) -> str:
    after = before
    for old, new in RENAMES:
        after = after.replace(old, new)
    return after


def upgrade() -> None:
    for table, column, kind, nullable, before in COMMENTS:
        op.alter_column(
            table,
            column,
            existing_type=kind,
            existing_nullable=nullable,
            comment=_renamed(before),
            existing_comment=before,
            schema=SCHEMA,
        )


def downgrade() -> None:
    for table, column, kind, nullable, before in COMMENTS:
        op.alter_column(
            table,
            column,
            existing_type=kind,
            existing_nullable=nullable,
            comment=before,
            existing_comment=_renamed(before),
            schema=SCHEMA,
        )
