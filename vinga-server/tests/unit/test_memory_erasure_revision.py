"""The memory store's erasure revision: what moves it and what does not
(#536, decision 7, amended by the plan's third review round).

A conversation keeps its prompt's memory snapshot for as long as the
key it was built under holds, and the erasure revision is the one part
of that key an operator moves. Only a hard deletion of a fact publishes
it: the four erase routes of the memory API when they removed
something, and the model's own `forget` with `permanently` set. Every
other write leaves it alone, which is what keeps them from costing a
live conversation its prompt cache, and is what they pay for by being
seen from the next conversation instead.

Each case reads the revision of the store the routes publish into
before and after one write, and names the write; the API's own runtime
is handed that store's `erased`, the way the composition root hands it.
"""

import asyncio
import datetime as dt
import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.support.stores import memory
from vinga_server.config.api import build_api
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.secrets import MASTER_KEY_ENV, generate_key, load_keys
from vinga_server.config.store import ConfigStore
from vinga_server.conversations.records import TurnRecord
from vinga_server.conversations.store import ConversationStore
from vinga_server.db import open_database
from vinga_server.memory.store import MemoryScope

TOKEN = "test-api-token-" + "5e1f0c2d3b4a6978" * 2

AGENT = "poet"

BOARD = "aa:bb:cc:dd:ee:ff"


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """The master key, before anything opens the database, because the
    API derives its keys when its lifespan opens the engine."""
    monkeypatch.setenv(MASTER_KEY_ENV, generate_key())


@pytest.fixture
def api(keys: None) -> FastAPI:
    """The operator API with its hard deletions published into the
    lane's memory store, which is the store every session in this lane
    reads its prompt from."""
    application = build_api(TOKEN, DatabaseConfig())
    application.state.api_runtime.memory_erased = memory().erased
    return application


@pytest.fixture
def client(api: FastAPI) -> Iterator[TestClient]:
    with TestClient(api, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client


def told(scope: MemoryScope, owner: str, fact: str) -> int:
    return asyncio.run(memory().add(scope, owner, fact, agent=AGENT))


def moved_by(write: object) -> int:
    """How far one write moved the revision."""
    before = memory().erasures
    assert callable(write)
    write()
    return memory().erasures - before


def ok(response: object) -> None:
    status = getattr(response, "status_code", None)
    assert status == 200, getattr(response, "text", response)


# --- the four routes that publish ------------------------------------


def test_erasing_one_agent_fact_publishes_once(client: TestClient) -> None:
    number = told(MemoryScope.AGENT, AGENT, "the door code is 4321")

    assert moved_by(lambda: ok(client.delete(f"/memory/agents/{AGENT}/facts/{number}"))) == 1


def test_erasing_one_device_note_publishes_once(client: TestClient) -> None:
    number = told(MemoryScope.DEVICE, BOARD, "the spare key is under the mat")

    assert moved_by(lambda: ok(client.delete(f"/memory/devices/{BOARD}/facts/{number}"))) == 1


def test_erasing_an_agent_s_whole_memory_publishes_once(client: TestClient) -> None:
    told(MemoryScope.AGENT, AGENT, "one")
    told(MemoryScope.AGENT, AGENT, "two")

    assert moved_by(lambda: ok(client.delete(f"/memory/agents/{AGENT}/facts"))) == 1


def test_erasing_a_board_s_whole_memory_publishes_once(client: TestClient) -> None:
    told(MemoryScope.DEVICE, BOARD, "one")

    assert moved_by(lambda: ok(client.delete(f"/memory/devices/{BOARD}/facts"))) == 1


# --- an erasure that removed nothing ---------------------------------


def test_an_erasure_that_found_nothing_publishes_nothing(client: TestClient) -> None:
    """An addressed fact that is not there is a 404, and an owner with
    nothing stored is erased of nothing; neither costs a live
    conversation a re-read."""
    missing = client.delete(f"/memory/agents/{AGENT}/facts/987654321")
    assert missing.status_code == 404

    assert moved_by(lambda: client.delete(f"/memory/agents/{AGENT}/facts/987654321")) == 0
    assert moved_by(lambda: ok(client.delete(f"/memory/agents/{AGENT}/facts"))) == 0
    assert moved_by(lambda: ok(client.delete(f"/memory/devices/{BOARD}/facts"))) == 0


# --- the operator writes that reach the next conversation instead -----


def test_a_correction_through_the_api_publishes_nothing(client: TestClient) -> None:
    number = told(MemoryScope.AGENT, AGENT, "the user is vegetarian")

    assert (
        moved_by(
            lambda: ok(
                client.put(
                    f"/memory/agents/{AGENT}/facts/{number}", json={"fact": "the user is vegan"}
                )
            )
        )
        == 0
    )


def test_clearing_a_conversation_s_ledger_publishes_nothing(client: TestClient) -> None:
    thread = uuid.uuid4().hex
    asyncio.run(memory().set_state(thread, "scene", "the tavern", agent=AGENT))

    assert moved_by(lambda: ok(client.delete(f"/memory/conversations/{thread}/state"))) == 0


def test_a_device_rename_and_relocation_through_the_api_publish_nothing(
    client: TestClient,
) -> None:
    engine = open_database(DatabaseConfig())
    try:
        store = ConfigStore(engine, load_keys())
        store.set_agent(AGENT, {"prompt": "POET"})
        store.bind_device(BOARD, [AGENT])
    finally:
        engine.dispose()

    renamed = {"to": "Kitchen"}
    assert moved_by(lambda: ok(client.post(f"/devices/{BOARD}/rename", json=renamed))) == 0
    assert (
        moved_by(
            lambda: ok(client.put(f"/devices/{BOARD}/location", json={"location": "the hall"}))
        )
        == 0
    )


def test_a_thread_erasure_publishes_nothing(client: TestClient) -> None:
    """A thread's erasure takes its ledger and its held facts with its
    turns, through its own listener; a live conversation on another
    thread has nothing of it in its snapshot to drop."""
    thread = uuid.uuid4().hex
    session = uuid.uuid4().hex
    recorder = ConversationStore(
        DatabaseConfig(), now=lambda: dt.datetime.now(dt.UTC), retention_days=0
    )
    recorder.start()
    try:
        recorder.open_session(
            session,
            100.0,
            {
                "started_at": "2026-10-04T10:00:00+00:00",
                "server": {"version": "0.1.0", "revision": "abc1234"},
                "device": {"mac": BOARD, "client": "test"},
                "protocol": "1",
                "agent": AGENT,
                "agents": [AGENT],
                "providers": {"llm": {"name": "mock", "type": "mock"}},
            },
        )
        recorder.record_turn(
            session,
            TurnRecord(at=101.0, conversation=thread, agent=AGENT, heard="hi", reply="Hello."),
        )
    finally:
        recorder.stop()
    asyncio.run(memory().set_state(thread, "scene", "the tavern", agent=AGENT))

    assert moved_by(lambda: ok(client.delete(f"/conversations/{thread}"))) == 0


# --- the model's own writes ------------------------------------------


def test_the_model_s_soft_forget_publishes_nothing() -> None:
    """A soft forget is held for the undo, and the model already reads
    the change as its own tool result; nothing else needs telling."""
    number = told(MemoryScope.AGENT, AGENT, "the user is vegetarian")
    thread = uuid.uuid4().hex

    assert (
        moved_by(
            lambda: asyncio.run(
                memory().forget(MemoryScope.AGENT, AGENT, number, thread, agent=AGENT)
            )
        )
        == 0
    )


def test_the_model_s_permanent_forget_publishes_once() -> None:
    """Round three's first amendment: a permanent forget is a SQL
    DELETE, the hard deletion the operator routes make, so it publishes
    the same revision once its transaction committed, and every live
    conversation holding the fact drops it at its next leg."""
    number = told(MemoryScope.AGENT, AGENT, "the door code is 4321")
    thread = uuid.uuid4().hex

    assert (
        moved_by(
            lambda: asyncio.run(
                memory().forget(
                    MemoryScope.AGENT, AGENT, number, thread, agent=AGENT, permanently=True
                )
            )
        )
        == 1
    )


def test_a_permanent_forget_that_found_nothing_publishes_nothing() -> None:
    thread = uuid.uuid4().hex

    def refused() -> None:
        with pytest.raises(ValueError):
            asyncio.run(
                memory().forget(
                    MemoryScope.AGENT, AGENT, 987654321, thread, agent=AGENT, permanently=True
                )
            )

    assert moved_by(refused) == 0
