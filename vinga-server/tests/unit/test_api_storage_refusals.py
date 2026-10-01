"""What a storage refusal over the API answers, and what it logs (#586).

Three routes refuse a write the database would not take with a fixed
sentence and a 500: a memory write, a conversation erasure, and a write
to the stored configuration. The first two end "The details are in the
server's log", and the third names the failure's class in its own
sentence. Each is driven here through the API, with a failure planted
where the route's own boundary meets it.

What is held, per route:

- **The body is the one it always was, byte for byte.** Pinned before
  the log line was reshaped and left untouched after, so what a caller
  receives is shown not to have moved.
- **The log names the class of what failed**, which is what "the
  details are in the server's log" promises, rendered through
  `db.failure_name`'s validation so a class whose name is not an
  identifier names nothing but the refusal.
- **Nothing planted travels.** A credential-shaped value sits in the
  failing exception's message, in the statement and parameters it
  carries, in the driver error under it and on its `__cause__`, and is
  hunted in the body, in every log record in both formats and in the
  record objects, and in everything the refusal itself carries.
"""

import contextlib
import logging
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from tests.support.events import only
from tests.support.leaks import chain, renderings
from vinga_server.config.api import build_api
from vinga_server.config.loader import StorageError
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.secrets import MASTER_KEY_ENV, generate_key
from vinga_server.conversations import store as conversation_record
from vinga_server.db import connection_url
from vinga_server.memory import store as memory_store

TOKEN = "test-api-token-" + "0123456789abcdef" * 2

PLANTED = "sk-test-586c0f-never-a-real-credential"

AGENT = "poet"

THREAD = "9f0c1d2e3a4b5c6d7e8f90a1b2c3d4e5"

# The bodies the two fixed sentences are answered with, pinned before
# #586 reshaped what the log says about them. A refusal's body is the
# repository's sentence in the problem shape, and neither changes here.
MEMORY_REFUSAL = (
    b'{"title":"Internal Server Error","status":500,"detail":"memory could not be '
    b'written, and nothing was changed. The details are in the server\'s log",'
    b'"errors":[]}'
)

ERASURE_REFUSAL = (
    b'{"title":"Internal Server Error","status":500,"detail":"the conversation store '
    b'could not be written, and nothing was deleted. The details are in the '
    b'server\'s log","errors":[]}'
)

# And the stored configuration's, which names the class in its sentence
# already (#530), and is pinned so that carrying the class to the log as
# well is shown not to have widened it. `ProgrammingError` is what
# SQLAlchemy raises for an exception a PL/pgSQL trigger raised.
CONFIG_REFUSAL = (
    b'{"title":"Internal Server Error","status":500,"detail":"the configuration '
    b'database could not be read or written (ProgrammingError).","errors":[]}'
)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv(MASTER_KEY_ENV, generate_key())
    return build_api(TOKEN, DatabaseConfig())


@pytest.fixture
def client(api: FastAPI) -> Iterator[TestClient]:
    """Entered, so the lifespan opens the configuration store the third
    route writes through."""
    with TestClient(api, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client


def planted_failure() -> OperationalError:
    """A driver failure holding the planted value everywhere a real one
    keeps one: the DSN the driver quotes, the statement and the values
    bound to it, and the exception's `__cause__`, which is the shape
    #530's sentinel uses."""
    dsn = f"postgresql+psycopg://vinga:{PLANTED}@db.internal:5432/vinga"
    driver = psycopg.OperationalError(f"server closed the connection, connected as {dsn}")
    failure = OperationalError(
        f"DELETE FROM record.turns WHERE heard = '{PLANTED}'", {"heard": PLANTED}, driver
    )
    failure.__cause__ = RuntimeError(f"while writing over {dsn}")
    return failure


def forged_failure() -> SQLAlchemyError:
    """A failure whose class name is not an identifier, and so is not a
    name any line may repeat."""
    forged = type("Forged\nthe store is fine", (SQLAlchemyError,), {})
    failure = forged(f"connected as {PLANTED}")
    failure.__cause__ = RuntimeError(PLANTED)
    return failure


@contextlib.contextmanager
def writing_through(api: FastAPI, seam: str, failure: Exception) -> Iterator[None]:
    """The transaction a route writes in, replaced at the runtime by one
    that fails as it opens.

    The runtime is where both routes take their writer from, request by
    request, so the failure arrives exactly where each route's own
    boundary is, and nothing inside the stores is touched.
    """
    runtime = api.state.api_runtime

    @contextlib.contextmanager
    def failing() -> Iterator[Any]:
        raise failure
        yield  # pragma: no cover - a generator, so a context manager

    api.state.api_runtime = replace(runtime, **{seam: failing})
    try:
        yield
    finally:
        api.state.api_runtime = runtime


@contextlib.contextmanager
def watching(api: FastAPI) -> Iterator[list[Exception]]:
    """Every storage refusal the routes raise, kept so a test can walk
    what it carries. The production handler still answers, so the body
    and the log are the ones a deployment sends."""
    caught: list[Exception] = []
    original = api.exception_handlers[StorageError]

    async def watched(request: Any, exc: Exception) -> Any:
        caught.append(exc)
        return await original(request, exc)

    api.add_exception_handler(StorageError, watched)
    api.middleware_stack = None
    try:
        yield caught
    finally:
        api.add_exception_handler(StorageError, original)
        api.middleware_stack = None


def _holder() -> psycopg.Connection:
    """A connection this suite owns, on nobody's engine, for the
    triggers and the rows planted below."""
    url = connection_url(DatabaseConfig()).set(drivername="postgresql")
    return psycopg.connect(url.render_as_string(hide_password=False))


@contextlib.contextmanager
def refusing(table: str, when: str) -> Iterator[None]:
    """A statement trigger refusing `when` on `table` (schema-qualified),
    with the planted value in what it says.

    The boundary each case is about is inside a store, so the failure is
    a real one from the database rather than a stand-in: the statement
    runs, the database refuses it, and the driver's error carries the
    trigger's words beside what the request bound into the statement.
    A statement trigger rather than a row trigger, so it fires whether
    or not the statement would have touched a row.
    """
    schema_name = table.split(".")[0]
    holder = _holder()
    try:
        holder.execute(
            f"create function {schema_name}.refuse_586() returns trigger language plpgsql "
            f"as $$ begin raise exception 'refused near {PLANTED}'; end $$"
        )
        holder.execute(
            f"create trigger refuse_586 before {when} on {table} "
            f"for each statement execute function {schema_name}.refuse_586()"
        )
        holder.commit()
        yield
    finally:
        holder.execute(f"drop trigger if exists refuse_586 on {table}")
        holder.execute(f"drop function if exists {schema_name}.refuse_586()")
        holder.commit()
        holder.close()


def refusing_provider_writes() -> contextlib.AbstractContextManager[None]:
    return refusing("domain.providers", "insert or update")


def _erasing(client: TestClient) -> Any:
    return client.delete(f"/conversations/{THREAD}")


def _forgetting(client: TestClient) -> Any:
    return client.delete(f"/memory/agents/{AGENT}/facts")


# The bodies, pinned


@pytest.mark.parametrize(
    ("seam", "request_", "body"),
    [
        pytest.param("memory_writes", _forgetting, MEMORY_REFUSAL, id="memory"),
        pytest.param("erasures", _erasing, ERASURE_REFUSAL, id="erasure"),
    ],
)
def test_a_refused_write_answers_the_body_it_always_has(
    api: FastAPI, client: TestClient, seam: str, request_: Any, body: bytes
) -> None:
    with writing_through(api, seam, planted_failure()):
        answer = request_(client)

    assert answer.status_code == 500
    assert answer.content == body


def test_a_refused_configuration_write_answers_the_body_it_always_has(
    client: TestClient,
) -> None:
    with refusing_provider_writes():
        answer = client.put("/providers/llm/claude", json={"type": "anthropic", "model": "m"})

    assert answer.status_code == 500
    assert answer.content == CONFIG_REFUSAL


# What the log says, and what nothing says
#
# One case per route, each asserting both halves together: the one
# event the failure produces names the class of what failed rather
# than the refusal built from it, and the planted value is in no log
# record, no response and nothing the refusal carries. Together because
# they are one claim about one line: a line that named the class by
# quoting the failure would pass the first half alone.


def _nothing_planted(answer: Any, caplog: pytest.LogCaptureFixture) -> None:
    """Not in the body, and not in any record in either format or in the
    record object behind them."""
    assert PLANTED not in answer.text
    assert not [found for found in renderings(caplog) if PLANTED in found]


def _severed(caught: list[Exception]) -> None:
    """And not in the refusal: its text, its arguments, what its
    attributes hold (the cause's class among them) and anything on its
    chain."""
    [problem] = caught
    assert PLANTED not in chain(problem)
    assert problem.__cause__ is None
    assert problem.__context__ is None


@pytest.mark.parametrize(
    ("seam", "request_", "body"),
    [
        pytest.param("memory_writes", _forgetting, MEMORY_REFUSAL, id="memory"),
        pytest.param("erasures", _erasing, ERASURE_REFUSAL, id="erasure"),
    ],
)
def test_a_refused_write_logs_the_class_of_what_failed_and_nothing_planted(
    api: FastAPI,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    seam: str,
    request_: Any,
    body: bytes,
) -> None:
    with writing_through(api, seam, planted_failure()), watching(api) as caught:
        with caplog.at_level(logging.DEBUG):
            answer = request_(client)

    assert answer.content == body
    said = only(caplog, "api_storage_error")
    assert said.getMessage().endswith("(OperationalError)")
    assert said.exc_info is None
    _nothing_planted(answer, caplog)
    _severed(caught)


def test_a_refused_configuration_write_logs_the_class_and_nothing_planted(
    api: FastAPI, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The configuration store's refusal named the class in its body
    already (#530) and its log line named only `StorageError`, so the
    log said less than the response did. The planted value is in the
    trigger's words, which the driver's error and the SQLAlchemy error
    wrapping it both carry, and in the statement's bound body.

    The refusal's chain as well, which is the case that needed it: the
    store translates the failure inside a generator context manager,
    where a plain raise after the handler still takes the failure as its
    `__context__`, because the generator runs while the `with` it serves
    is handling that failure."""
    with refusing_provider_writes(), watching(api) as caught:
        with caplog.at_level(logging.DEBUG):
            answer = client.put(
                "/providers/llm/claude", json={"type": "anthropic", "model": PLANTED}
            )

    assert answer.content == CONFIG_REFUSAL
    said = only(caplog, "api_storage_error")
    assert said.getMessage().endswith("(ProgrammingError)")
    assert said.exc_info is None
    _nothing_planted(answer, caplog)
    _severed(caught)


@pytest.mark.parametrize(
    ("seam", "request_", "body"),
    [
        pytest.param("memory_writes", _forgetting, MEMORY_REFUSAL, id="memory"),
        pytest.param("erasures", _erasing, ERASURE_REFUSAL, id="erasure"),
    ],
)
def test_a_failure_whose_class_cannot_be_named_logs_the_refusal(
    api: FastAPI,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    seam: str,
    request_: Any,
    body: bytes,
) -> None:
    """A class can be given any name, a line break and a sentence after
    it included. The refusal is still answered, with the same body, and
    the line names the refusal's own class rather than a name it may
    not repeat: what the route could classify was that it failed, and
    that is what it says. Per route, because each builds its own
    refusal, and one that spelled the class without the validation
    would raise while building it and lose the body."""
    with writing_through(api, seam, forged_failure()), watching(api) as caught:
        with caplog.at_level(logging.DEBUG):
            answer = request_(client)

    assert answer.content == body
    said = only(caplog, "api_storage_error")
    assert said.getMessage().endswith("(StorageError)")
    assert not [found for found in renderings(caplog) if "the store is fine" in found]
    _nothing_planted(answer, caplog)
    _severed(caught)


# The stores' own classifiers
#
# Three refusals are decided one level further in, inside a store
# function the route's transaction calls, and pass the route's own
# boundary untouched because they are already `ConfigError`s: the memory
# purge an erasure runs, and the two halves of an agent rename beyond
# the configuration itself, its recorded threads and its remembered
# facts. A failure injected at the route's writer never reaches them,
# so each is driven by a trigger on the table its statement writes.


def _a_thread_to_erase() -> None:
    """One thread row, which is all an erasure needs to reach the purge
    of that thread's memory."""
    with _holder() as holder:
        holder.execute(
            "insert into record.conversations "
            "(conversation, agent, device, created_at, last_active_at) "
            "values (%s, %s, %s, %s, %s)",
            (THREAD, AGENT, "aa:bb:cc:dd:ee:ff", "2026-10-01T12:00:00+00:00",
             "2026-10-01T12:00:00+00:00"),
        )


def _an_agent_to_rename(client: TestClient) -> None:
    """The smallest configuration an agent can be written into."""
    for path, body in (
        ("/providers/llm/claude", {"type": "anthropic", "model": "m"}),
        ("/providers/asr/whisper", {"type": "mock"}),
        ("/agent-defaults", {"llm": "claude", "asr": "whisper"}),
        (f"/agents/{AGENT}", {"prompt": "You are a poet."}),
    ):
        assert client.put(path, json=body).status_code == 200, path


def _renaming(client: TestClient) -> Any:
    return client.post(f"/agents/{AGENT}/rename", json={"to": "bard"})


@pytest.mark.parametrize(
    ("table", "when", "prepare", "request_", "sentence"),
    [
        pytest.param(
            "memory.state",
            "delete",
            lambda client: _a_thread_to_erase(),
            _erasing,
            memory_store.PURGE_FAILED,
            id="memory-purge",
        ),
        pytest.param(
            "record.conversations",
            "update",
            _an_agent_to_rename,
            _renaming,
            conversation_record.RENAME_FAILED,
            id="record-rename",
        ),
        pytest.param(
            "memory.facts",
            "update",
            _an_agent_to_rename,
            _renaming,
            memory_store.RENAME_FAILED,
            id="memory-owner-rename",
        ),
    ],
)
def test_a_store_refusal_logs_the_class_of_what_failed_and_nothing_planted(
    api: FastAPI,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    table: str,
    when: str,
    prepare: Any,
    request_: Any,
    sentence: str,
) -> None:
    """The sentence is the inner classifier's own, which is what shows
    the failure was decided there rather than by the route around it."""
    prepare(client)

    with refusing(table, when), watching(api) as caught:
        with caplog.at_level(logging.DEBUG):
            answer = request_(client)

    assert answer.status_code == 500
    assert answer.json()["detail"] == sentence
    said = only(caplog, "api_storage_error")
    assert said.getMessage().endswith("(ProgrammingError)")
    assert said.exc_info is None
    _nothing_planted(answer, caplog)
    _severed(caught)

