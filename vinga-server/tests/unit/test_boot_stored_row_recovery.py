"""What a boot prints when a stored row will not read as configuration
(#507).

`3004_reach_replaces_egress` carries an invalid `reach` across rather
than aborting, and it is right to: the boot is what runs a migration,
and the configuration API an operator would fix the row through is
behind the boot, so an abort locks them out of the one door to the row
that is stopping them. What the migration went on to claim is that the
consequence is bounded to the entry, and that `vinga provider delete`
and `vinga mcp-server delete` reach such a row by identity. That is
true of a running server and false of a boot, which is the case the
migration is about: one `domain.mcp_servers` row whose `reach` is not
one of the three makes this server exit 1 during startup, and there is
nobody to answer either command.

So the boot keeps refusing and says what to do about it. The advice is
printed for ONE class of failure, which is the distinction this
milestone adds: `StorageError` also means a database this server cannot
reach, a migration that failed, a superseded revision and a schema
privilege it does not have, and answering a network problem with
"rebuild from a kept export" would send an operator to destroy a
healthy configuration. The classification is the type and is decided
where the code classifies; nothing here or anywhere else reads a
message to tell the two apart.

The negative cases are therefore the load-bearing half of this suite. A
recovery line appended to every refusal would pass the boot case above
and be exactly the defect this issue reports, one sentence further on.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import insert

from tests.support.problems import refused
from tests.support.stores import planted
from vinga_server import db, serving
from vinga_server.config import boot
from vinga_server.config.api import build_api
from vinga_server.config.boot import load_boot_config
from vinga_server.config.loader import StorageError, StoredConfigUnreadableError
from vinga_server.config.models import DATABASE_ENV_NAMES, DatabaseConfig
from vinga_server.config.secrets import MASTER_KEY_ENV, generate_key, load_keys
from vinga_server.config.store import ConfigStore
from vinga_server.db import open_database, schema
from vinga_server.serving import STORED_CONFIG_RECOVERY

TOKEN = "test-api-token-" + "0123456789abcdef" * 2

# The entry the row is filed under, and the location every refusal about
# it names. Spelled here rather than derived, because what the case
# claims is that the location survives the new branch intact.
ENTRY = "weather"
LOCATION = f"mcp_servers.{ENTRY}"

# The value no build of this project ever wrote, which is the shape the
# issue reports: `reach` is three words, and a restore, a hand edit or
# another build's row can hold a fourth. Distinctive rather than
# plausible, so "the refusal quotes no value" is a claim a substring
# check can actually make.
STORED_REACH = "anywhere-at-all-9f3c"

# The row as a hand edit would leave it. Written as JSON rather than
# through the model, deliberately: `McpServerConfig` refuses this value,
# so a body dumped from a model could never carry it, and what is under
# test is the reader.
BODY = json.dumps({"transport": "stdio", "command": "uvx", "reach": STORED_REACH})

# A port on loopback nothing listens on, which is the cheapest genuine
# connection failure there is: the kernel refuses it immediately, so the
# case about a database that is not there does not wait out a timeout.
NO_BACKEND_PORT = 1

# The sentence a generic storage failure carries. Any sentence at all
# would do, and that is the point of the case: what decides the branch
# is the class, so a `StorageError` that is not the subclass gets no
# recovery whatever it says.
A_GENERIC_FAILURE = "the configuration database could not be read or written (OperationalError)."


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MASTER_KEY_ENV, generate_key())


@pytest.fixture
def store(keys: None) -> Iterator[ConfigStore]:
    engine = open_database(DatabaseConfig())
    try:
        yield ConfigStore(engine, load_keys())
    finally:
        engine.dispose()


@pytest.fixture
def unreadable(store: ConfigStore, monkeypatch: pytest.MonkeyPatch) -> ConfigStore:
    """A deployment holding the one row this milestone is about, and a
    boot with nothing else to read but the defaults."""
    monkeypatch.delenv("VINGA_CONFIG", raising=False)
    planted(store, insert(schema.mcp_servers).values(name=ENTRY, body=BODY))
    return store


@pytest.fixture
def client(keys: None) -> Iterator[TestClient]:
    api: FastAPI = build_api(TOKEN, DatabaseConfig())
    with TestClient(api, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client


def _refusing(monkeypatch: pytest.MonkeyPatch, refusal: Exception) -> None:
    """The database half of a boot failing the way `db/__init__.py`
    fails it.

    A double at the seam the boot opens its database on, because two of
    the negative cases cannot be produced on a lane that owns its
    instance: a role that may not create a schema is a provisioning
    state, not a row. What the double stands in for is the raise site,
    and the refusals it raises are the module's own constants rather
    than sentences respelled here.
    """
    monkeypatch.setattr(boot, "open_database", lambda settings: _raise(refusal))


def _raise(refusal: Exception) -> None:
    raise refusal


# The classification, which is what every branch below reads


def test_an_unreadable_row_is_a_storage_failure_of_its_own_kind(
    unreadable: ConfigStore,
) -> None:
    """The type, asked of the boot path that raises it.

    Both halves in one case because the claim is a distinction: the row
    this build cannot load is the subclass, and it is still a
    `StorageError`, so the API, the reload path and the diff path go on
    catching what they catch.
    """
    with pytest.raises(StoredConfigUnreadableError) as caught:
        load_boot_config()

    assert isinstance(caught.value, StorageError)
    assert LOCATION in str(caught.value)


def test_a_database_that_is_not_there_is_not_that_kind(
    keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the distinction, against a real failure rather
    than a double: an instance that refuses the connection outright.

    This is the case the review's third P1 is about. Without the
    subclass it is indistinguishable from the row above, and an
    operator whose database is behind a network problem would be told
    to rebuild a configuration that is fine.
    """
    monkeypatch.delenv("VINGA_CONFIG", raising=False)
    monkeypatch.setenv(DATABASE_ENV_NAMES["port"], str(NO_BACKEND_PORT))

    with pytest.raises(StorageError) as caught:
        load_boot_config()

    assert not isinstance(caught.value, StoredConfigUnreadableError)


# The boot, which is where the advice is printed


def test_a_reach_no_build_wrote_refuses_the_boot_and_says_what_to_do(
    unreadable: ConfigStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole entry point, from the file half to the refusal on
    stderr, which is where an operator actually meets this.

    Four claims in one case because they are one sentence and a second
    one under it: the boot leaves with 1, the refusal still addresses
    the entry, the value that caused it is not quoted back, and the
    advice names both ways out.
    """
    assert serving.run(None) == 1

    printed = capsys.readouterr()
    assert LOCATION in printed.err
    assert STORED_REACH not in printed.err
    assert STORED_CONFIG_RECOVERY in printed.err
    # Both recoveries, named as tokens rather than as the wording: the
    # export rebuild for a deployment that kept one, and SQL for the
    # restored or hand-edited database that is this issue's own path.
    assert "vinga-server config export" in printed.err
    assert "SQL" in printed.err


def test_a_configuration_failure_that_is_not_a_storage_one_gets_no_recovery(
    keys: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The case that proves the branch is a branch and not a sentence
    appended to everything: a file this loader refuses.

    A domain section left in the file half is the refusal with the
    clearest reason to stay exactly as it is. It already names where the
    key moved to and the command that writes it, and there is nothing
    stored to correct, so advice about rebuilding a database would be
    advice about the wrong half of the configuration.
    """
    path = tmp_path / "vinga.yaml"
    path.write_text("agents:\n  sam:\n    prompt: hi\n")
    monkeypatch.delenv("VINGA_CONFIG", raising=False)

    assert serving.run(str(path)) == 1

    printed = capsys.readouterr()
    assert "moved to the database" in printed.err
    assert STORED_CONFIG_RECOVERY not in printed.err


def test_a_database_that_is_not_there_gets_no_recovery(
    keys: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The negative case with a deployment behind it: the instance is
    down or unreachable, the configuration in it is untouched, and what
    the boot says is what it has always said."""
    monkeypatch.delenv("VINGA_CONFIG", raising=False)
    monkeypatch.setenv(DATABASE_ENV_NAMES["port"], str(NO_BACKEND_PORT))

    assert serving.run(None) == 1

    printed = capsys.readouterr()
    assert db.UNREACHABLE in printed.err
    assert STORED_CONFIG_RECOVERY not in printed.err


@pytest.mark.parametrize(
    "refusal",
    [
        pytest.param(StorageError(db.SCHEMA_NOT_PERMITTED), id="schema-privilege"),
        pytest.param(StorageError(A_GENERIC_FAILURE), id="generic-storage"),
    ],
)
def test_a_storage_failure_that_is_not_a_row_gets_no_recovery(
    keys: None,
    refusal: StorageError,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The remaining two members of the parent class, both of which have
    a remedy of their own and neither of which is a rebuild.

    A schema privilege is a provisioning file to rerun, and its own
    sentence says so; a generic storage failure is whatever the driver
    met, and this build says only that it met one. Appending a rebuild
    to either would be prescribing the most destructive answer to the
    least destructive question.
    """
    monkeypatch.delenv("VINGA_CONFIG", raising=False)
    _refusing(monkeypatch, refusal)

    assert serving.run(None) == 1

    printed = capsys.readouterr()
    assert str(refusal) in printed.err
    assert STORED_CONFIG_RECOVERY not in printed.err


# The reader with a working door, which must not change


def test_the_same_row_read_through_a_running_server_answers_as_it_does_today(
    unreadable: ConfigStore, client: TestClient
) -> None:
    """The whole-configuration read over HTTP, against the row that
    refuses the boot.

    A server that is up has the door: the row IS reachable, a delete
    goes by identity, and telling this caller to rebuild from an export
    would be advice to do something drastic instead of something that
    works. So the 500 it answers is the store's own sentence and gains
    nothing, which is what "the new class is still a `StorageError`"
    has to mean at the surface.
    """
    response = client.get("/config")

    assert response.status_code == 500
    detail = refused(response.json(), 500)
    assert LOCATION in detail
    assert STORED_REACH not in detail
    assert STORED_CONFIG_RECOVERY not in detail
