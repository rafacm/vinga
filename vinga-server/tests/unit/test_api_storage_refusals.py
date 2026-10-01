"""What a storage refusal over the API answers, and what it logs (#586).

Three routes refuse a write the database would not take with a fixed
sentence and a 500: a memory write, a conversation erasure, and a write
to the stored configuration. The first two end "The details are in the
server's log", and the third names the failure's class in its own
sentence. Each is driven here through the API, with a failure planted
where the route's own boundary meets it.

**The body is the one it always was, byte for byte.** Pinned before the
log line was reshaped, so what a caller receives can be shown not to
move when it is.
"""

import contextlib
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from vinga_server.config.api import build_api
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.secrets import MASTER_KEY_ENV, generate_key
from vinga_server.db import connection_url

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
def refusing_provider_writes() -> Iterator[None]:
    """A trigger refusing every write to the stored providers, with the
    planted value in what it says.

    The configuration store's own boundary is what this route's failure
    has to cross, so the failure is a real one from the database rather
    than a stand-in: the statement runs, the database refuses it, and
    the driver's error carries the trigger's words beside what the
    request bound into the statement.
    """
    url = connection_url(DatabaseConfig()).set(drivername="postgresql")
    holder = psycopg.connect(url.render_as_string(hide_password=False))
    try:
        holder.execute(
            "create function domain.refuse_586() returns trigger language plpgsql as "
            f"$$ begin raise exception 'refused near {PLANTED}'; end $$"
        )
        holder.execute(
            "create trigger refuse_586 before insert or update on domain.providers "
            "for each statement execute function domain.refuse_586()"
        )
        holder.commit()
        yield
    finally:
        holder.execute("drop trigger if exists refuse_586 on domain.providers")
        holder.execute("drop function if exists domain.refuse_586()")
        holder.commit()
        holder.close()


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
