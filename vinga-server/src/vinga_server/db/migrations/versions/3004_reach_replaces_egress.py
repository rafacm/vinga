"""Translate stored egress declarations into reach declarations

A data migration and nothing else: no table, column, index or
constraint moves, so there is nothing here for autogenerate to have
written and this file is hand-written whole.

#493 replaced the boolean `egress` key with `reach`, one of host,
network or internet, on provider entries and on MCP entries alike, with
no alias: the new models refuse the old key loudly, which is what keeps
a stale declaration from becoming a provider option nobody enforces.
Provider and MCP bodies persist in this schema as opaque JSON text, so
a deployment upgrading into that release carries rows the new build
would refuse at boot, before the configuration API it would be fixed
through is even reachable. A file is the operator's to edit and the
release notes say so; a row is this migration's to translate.

The translation preserves the distinction the two refusals always drew.
A provider is a library running in this process, and its refusal said
"off this host", so `egress: false` becomes `reach: host`. An MCP
entry's command or URL reaches whatever the machine can, and its
refusal said "off this network", so `egress: false` becomes
`reach: network`. Both spellings of `egress: true` become
`reach: internet`, which is what the old marking asserted and the
widest thing an operator can now say.

An explicitly stored `"egress": null` is the third shape, and it exists
because bodies are written with `exclude_unset=True`: a fragment that
set the key to null keeps it, and a fragment that never mentioned it
does not. Null migrates by REMOVING the key, which is the same state as
absence and loses only the input history that an operator once typed a
null. That is the whole point of touching it: no row may retain the
forbidden spelling, whatever it held.

Forward only, and nothing is lost that a downgrade would want back: an
older build reading `reach` would refuse it for the same reason this
one refuses `egress`, so a reversal would have to re-derive a boolean
from three values and would get `network` wrong in whichever direction
it chose.

Rows with no such key are left alone by the `where`, which matters for
more than speed: an untouched row keeps its column's bytes exactly as
they were written, rather than being rewritten through a JSON round
trip that reorders its keys. That is `3002_drop_max_tokens_secrets`'s
rule and it is this one's.

Revision ID: 3004_reach_replaces_egress
Revises: 3003_device_record
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3004_reach_replaces_egress"
down_revision: str | None = "3003_device_record"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The key that goes and the key that arrives, written once and read by
# both statements below.
OLD = "egress"
NEW = "reach"


def _translation(table: str, local: str) -> str:
    """The update one table's bodies need, with its own reading of what
    `false` meant.

    `local` is what that surface's old refusal called staying put: a
    provider's host, an MCP entry's network. The column is text, so both
    halves cast to compare and to edit, and the `where` keeps the
    statement off every row that never carried the key.
    """
    stays = _object(NEW, local)
    leaves = _object(NEW, "internet")
    return (
        f"update domain.{table} set body = (case "
        f"when body::jsonb -> '{OLD}' = 'false'::jsonb "
        f"then (body::jsonb - '{OLD}') || '{stays}'::jsonb "
        f"when body::jsonb -> '{OLD}' = 'true'::jsonb "
        f"then (body::jsonb - '{OLD}') || '{leaves}'::jsonb "
        f"else body::jsonb - '{OLD}' "
        f"end)::text "
        f"where jsonb_exists(body::jsonb, '{OLD}')"
    )


def _object(key: str, value: str) -> str:
    """One JSON object literal, spelled here rather than inline so the
    braces do not have to be doubled inside an f-string that is already
    carrying quotes of two kinds."""
    return '{"' + key + '": "' + value + '"}'


def upgrade() -> None:
    op.execute(_translation("providers", "host"))
    op.execute(_translation("mcp_servers", "network"))


def downgrade() -> None:
    """Nothing, and not for want of trying.

    A downgrade restores what an upgrade changed, and three values do
    not fit back into two. `network` is the reach the boolean could not
    say, which is why #493 exists; mapping it to either boolean would
    write a declaration the operator never made, in the one direction
    that matters. An older image meeting a database this ran on refuses
    the entries it translated, by exactly the rule this release added
    in the other direction, and says which key it does not recognize.
    """
