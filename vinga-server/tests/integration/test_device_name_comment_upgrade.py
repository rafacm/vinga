"""An installed database describes `record.sessions.device_name` the way a new one does.

The column's comment says what its null covers, and since a try link's
`Browser <mac>` became a reserved placeholder (#613) that is a board or
a browser nobody has named. The declaration and the generated
`docs/reference/conversations-schema.md` follow on their own; a
database a deployment already migrated carries the comment as Postgres
DDL and moves only through a migration.

So the subject is a database stamped at the chain's previous head, what
its comment says there, what the upgrade makes it say, and what the
downgrade puts back, read with `col_description` and with the version
stamp asserted at every end, as `test_event_name_comment_upgrade.py`
does for the revision before this one.

The new text is spelled out here as well as compared with the
declaration, so a declaration and a migration that moved together to
some other text would still fail.
"""

import pytest
from sqlalchemy import text

from tests.support.migrations import downgrade_to, upgrade_to, version_of
from vinga_server.config.models import DatabaseConfig
from vinga_server.conversations import schema
from vinga_server.conversations.store import CONVERSATIONS_CHAIN
from vinga_server.db import read_engine

# The chain's head before the comment moved.
BASELINE = "1011_events_cite_the_reference"

# The revision that moves it.
REVISION = "1012_device_name_names_browsers"

# The part of the comment that both texts share.
LEAD = (
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

# What the column said while only a board's placeholder was reserved.
OLD_COMMENT = (
    LEAD + "board nobody has named, a MAC a default agent covers with no record "
    "behind it, and every session that opened before this column existed."
)

# What it says now.
NEW_COMMENT = (
    LEAD + "board or a browser nobody has named, a MAC a default agent covers with "
    "no record behind it, and every session that opened before this column "
    "existed."
)


def _comment(settings: DatabaseConfig) -> str | None:
    """The column comment on `record.sessions.device_name`, as the database holds it."""
    engine = read_engine(settings)
    try:
        with engine.connect() as connection:
            return connection.execute(
                text(
                    "select col_description(attrelid, attnum) from pg_attribute "
                    "where attrelid = to_regclass('record.sessions') "
                    "and attname = 'device_name'"
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


def test_the_upgrade_names_browsers(at_the_baseline: DatabaseConfig) -> None:
    upgrade_to(at_the_baseline.name, CONVERSATIONS_CHAIN, REVISION)

    assert _comment(at_the_baseline) == NEW_COMMENT
    assert _comment(at_the_baseline) == schema.sessions.c.device_name.comment
    assert version_of(at_the_baseline, CONVERSATIONS_CHAIN) == [REVISION]


def test_the_downgrade_puts_the_old_comment_back(at_the_baseline: DatabaseConfig) -> None:
    upgrade_to(at_the_baseline.name, CONVERSATIONS_CHAIN, REVISION)
    downgrade_to(at_the_baseline, CONVERSATIONS_CHAIN, BASELINE)

    assert _comment(at_the_baseline) == OLD_COMMENT
    assert version_of(at_the_baseline, CONVERSATIONS_CHAIN) == [BASELINE]
