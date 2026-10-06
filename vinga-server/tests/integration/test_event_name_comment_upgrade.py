"""An installed database describes `record.events.name` the way a new one does.

The column's comment is current text in three places: the declaration
in `conversations/schema.py`, the generated
`docs/reference/conversations-schema.md`, and every database a
deployment has already migrated, which carries it as a Postgres column
comment and shows it to an analyst under `\\d+`. The first two follow
the declaration on their own; the third moves only through a migration,
so a deployment upgraded in place would otherwise go on pointing at a
README table that no longer exists, while a fresh one names the
generated event reference.

So the subject is a database stamped at the chain's previous head,
what its comment says there, what the upgrade makes it say, and what
the downgrade puts back. The comment is read with `col_description`,
which is what the database says rather than what a migration file says
it wrote, and the version stamp is asserted at every end, so a fixture
that quietly migrated to head could not make any of it trivially true.

The new text is spelled out here rather than read from the declaration
alone, so a declaration and a migration that moved together to some
other text would still fail; it is compared with the declaration as
well, so the two cannot drift apart either.

The lane rather than the unit suite, for the reason
`test_metrics_views_upgrade.py` gives: the material is a database in a
state no current build produces, made from `blank_database`, since a
migrated template cannot be stamped backwards.
"""

import pytest
from sqlalchemy import text

from tests.support.migrations import downgrade_to, upgrade_to, version_of
from vinga_server.config.models import DatabaseConfig
from vinga_server.conversations import schema
from vinga_server.conversations.store import CONVERSATIONS_CHAIN
from vinga_server.db import read_engine

# The chain's head before the comment moved, which every deployment
# recording before this release is stamped at.
BASELINE = "1010_turns_name_their_utterance"

# The revision that moves it.
REVISION = "1011_events_cite_the_reference"

# What the column said while the server README carried the event table.
OLD_COMMENT = "The event name, from the event vocabulary the README's table defines."

# What it says now.
NEW_COMMENT = (
    "The event name, from the event vocabulary the generated event schema "
    "reference (docs/reference/events.md) defines."
)


def _comment(settings: DatabaseConfig) -> str | None:
    """The column comment on `record.events.name`, as the database holds it."""
    engine = read_engine(settings)
    try:
        with engine.connect() as connection:
            return connection.execute(
                text(
                    "select col_description(attrelid, attnum) from pg_attribute "
                    "where attrelid = to_regclass('record.events') and attname = 'name'"
                )
            ).scalar_one()
    finally:
        engine.dispose()


@pytest.fixture
def at_the_baseline(blank_database: str) -> DatabaseConfig:
    """A database with the conversations chain at the previous head."""
    return upgrade_to(blank_database, CONVERSATIONS_CHAIN, BASELINE)


def test_the_baseline_carries_the_old_comment(at_the_baseline: DatabaseConfig) -> None:
    """The control the two claims below rest on."""
    assert version_of(at_the_baseline, CONVERSATIONS_CHAIN) == [BASELINE]
    assert _comment(at_the_baseline) == OLD_COMMENT


def test_the_upgrade_names_the_generated_reference(at_the_baseline: DatabaseConfig) -> None:
    upgrade_to(at_the_baseline.name, CONVERSATIONS_CHAIN, "head")

    assert _comment(at_the_baseline) == NEW_COMMENT
    assert _comment(at_the_baseline) == schema.events.c.name.comment
    assert version_of(at_the_baseline, CONVERSATIONS_CHAIN) == [REVISION]


def test_the_downgrade_puts_the_old_comment_back(at_the_baseline: DatabaseConfig) -> None:
    upgrade_to(at_the_baseline.name, CONVERSATIONS_CHAIN, "head")
    downgrade_to(at_the_baseline, CONVERSATIONS_CHAIN, BASELINE)

    assert _comment(at_the_baseline) == OLD_COMMENT
    assert version_of(at_the_baseline, CONVERSATIONS_CHAIN) == [BASELINE]
