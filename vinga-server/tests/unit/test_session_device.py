"""What a running session knows about the device it is speaking through.

The assembler is `test_runtime_prompt.py` and the record read is
`test_live_device_read.py`; this file is about the clock and the switch,
which are the two things #449's review round found the plan had assumed
rather than designed.

**The clock.** The record is read on the round's own clock, beside the
memory scopes, rather than captured at the activation. An activation can
be an hour of conversation behind, and a device that was moved between
two replies has moved for the second of them. The test that proves it
moves a device through the repository between two rounds of one session
and reads the next prompt, which is the only way to tell a per-round
read from a per-activation one from outside.

**The switch.** `agents.<name>.memory` decides what an agent may
remember and nothing else. A device's name is not a remembered thing,
so an agent that may not remember anything is still told what it is
speaking through, and the reply path reads the record whether or not it
reads memory.

The last section is the no-leak claim, which is a claim about two
different trust classes. The name is the operator's; the location is a
conversation's, from the tool #449's M3 adds onward. Neither reaches a
structured event, either log format or the capture manifest in this
milestone: the MAC is what identifies a device on those surfaces, and a
spoken string on a dated event row would sit on the telemetry surface
with telemetry retention and no per-conversation erasure. The
assertions are absence rather than sanitization, because nothing is
being cleaned on the way anywhere.
"""

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any, cast

import pytest

from tests.support.configs import BOTH_MAC, DEVICE_MAC, POET_MAC, base_config, world
from tests.support.providers import CountingServers, RecordingLlm, ScriptedLlm, built_world
from tests.support.registry import AGENT, STAGES, store_at
from tests.support.sessions import agent_providers, call, run_reply, session_for
from tests.support.sockets import LoopingSocket
from tests.support.stores import memory as lane_memory
from vinga_server import logs
from vinga_server.capture import CaptureStore
from vinga_server.config import Config
from vinga_server.config.models import DatabaseConfig, normalize_mac
from vinga_server.db import read_engine
from vinga_server.device.bindings import DeviceBindings
from vinga_server.device.session import DeviceSession
from vinga_server.memory.store import MemoryScope, MemoryStore
from vinga_server.runtime.pipeline import bespoke_runtime_factory
from vinga_server.runtime.prompt import DEVICE_HEADING, device_introduction
from vinga_server.tools.mcp import McpServers

NAME = "Kitchen Speaker"

LOCATION = "the kitchen"

NOTE = "the kitchen radiator rattles"

OFF: dict[str, object] = {"memory": {"enabled": False}}


def named_config(
    name: str = NAME,
    location: str | None = LOCATION,
    poet: dict[str, object] | None = None,
) -> Config:
    """The lane's world with the poet's board named and placed, and
    whatever memory section the case is about on the poet.

    The record form of the devices map rather than the agent-list
    shorthand, which is what an operator who has named a board has: the
    shorthand names nobody, and a device nobody has named is the case
    the second test below is about.
    """
    device: dict[str, object] = {"agents": ["poet"], "name": name}
    if location is not None:
        device["location"] = location
    return base_config(
        devices={POET_MAC: device, BOTH_MAC: ["poet", "tutor"]},
        agents={
            "poet": {"prompt": "POET", "tts": "tenor", **(poet or {})},
            "tutor": {"prompt": "TUTOR", "tts": "alto"},
        },
    )


# What the model is told


async def test_the_agent_is_told_what_it_is_speaking_through() -> None:
    llm = RecordingLlm()
    session = session_for(named_config(), POET_MAC, {"poet": llm})

    await run_reply(session, "hello")

    (system,) = llm.systems
    assert system == f"POET\n\n{device_introduction(NAME, LOCATION)}"


async def test_a_device_nobody_has_named_sends_the_prompt_it_always_sent() -> None:
    """The byte-equality case from the session's side: the lane's own
    configuration binds its boards with the agent-list shorthand, which
    names nobody, and those sessions send exactly what they sent before
    a device had a record."""
    llm = RecordingLlm()
    session = session_for(base_config(), POET_MAC, {"poet": llm})

    await run_reply(session, "hello")

    assert llm.systems == ["POET"]


async def test_the_notes_about_a_device_sit_under_its_introduction() -> None:
    """One device section, not two. The sentence says what this device
    is and the heading introduces what somebody told it, which is why
    there is no second heading for the model to choose between."""
    store = lane_memory()
    await store.add(MemoryScope.DEVICE, normalize_mac(POET_MAC), NOTE, agent="poet")
    llm = RecordingLlm()
    session = session_for(named_config(), POET_MAC, {"poet": llm}, memory=store)

    await run_reply(session, "hello")

    (system,) = llm.systems
    assert system == (
        f"POET\n\n{device_introduction(NAME, LOCATION)}\n\n{DEVICE_HEADING}\n- {NOTE}"
    )


# The memory switch, which this does not ride


async def test_an_agent_that_may_not_remember_still_knows_its_device() -> None:
    """The finding the plan's review round raised: `_system_prompt`
    returns the cached half early when memory is off, and a device's
    name is not a remembered thing. An agent that may not remember
    anything is still speaking through a named board in a room."""
    store = lane_memory()
    await store.add(MemoryScope.DEVICE, normalize_mac(POET_MAC), NOTE, agent="poet")
    llm = RecordingLlm()
    session = session_for(
        named_config(poet=OFF), POET_MAC, {"poet": llm}, memory=store
    )

    await run_reply(session, "hello")

    (system,) = llm.systems
    # The introduction, and none of the notes the board is carrying.
    assert system == f"POET\n\n{device_introduction(NAME, LOCATION)}"
    assert NOTE not in system and DEVICE_HEADING not in system


async def test_an_agent_that_may_not_remember_reads_no_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the same switch: reading the record is not an
    excuse to read memory. A round trip whose answer is thrown away is a
    cost every round of every reply would pay for nothing."""
    store = lane_memory()
    reads: list[str] = []
    real = MemoryStore.read_for_prompt

    def read(
        self: MemoryStore, agent: str, device: str | None, conversation: str | None
    ) -> Any:
        reads.append(agent)
        return real(self, agent, device, conversation)

    monkeypatch.setattr(MemoryStore, "read_for_prompt", read)
    session = session_for(
        named_config(poet=OFF), POET_MAC, {"poet": RecordingLlm()}, memory=store
    )

    await run_reply(session, "hello")

    assert reads == []


async def test_a_bound_board_nobody_has_named_sends_what_it_always_sent() -> None:
    """The upgrade case, end to end: a board bound through the
    repository carries `Device <mac>` from the moment it is bound, and
    the migration gives every row a deployment already had the same
    default. A prompt that introduced it would tell every agent in every
    deployment that its device is called a MAC address, on every round,
    the morning after this lands.
    """
    a_bound_board()

    config = base_config()
    llm = RecordingLlm()
    scripts = {"poet": llm}
    generations = world(config, providers=agent_providers(config, cast(Any, scripts)))
    bindings = DeviceBindings(generations, read_engine(DatabaseConfig()))
    try:
        session = session_for(
            config,
            POET_MAC,
            cast(Any, scripts),
            generations=generations,
            devices=bindings,
        )
        await run_reply(session, "hello")
    finally:
        bindings.dispose()

    assert llm.systems == ["POET"]


# The clock, which is the round's


def a_bound_board() -> str:
    """A board bound in the lane's database and never named, which is
    what an operator has the moment they bind one and what the
    migration leaves behind on every row a deployment already had.

    Written through the repository rather than composed in Python,
    because the tests under it are about a view with a real engine
    behind it, which is the shape a served deployment has.
    """
    with store_at() as store:
        for stage in STAGES:
            store.set_provider(stage, "mock", {"type": "mock"})
        store.set_agent("poet", dict(AGENT))
        store.bind_device(POET_MAC, ["poet"])
        return store.read_device(POET_MAC).entry.id


def a_named_board(name: str = NAME) -> str:
    """The same board, named the way an operator's `device rename`
    leaves it, and the id its record was minted with."""
    minted = a_bound_board()
    with store_at() as store:
        store.rename_device(POET_MAC, name)
    return minted


async def test_a_device_moved_between_two_rounds_is_moved_for_the_next_reply() -> None:
    """The milestone's own promise, and the one thing here that cannot
    be established by reading the call site: an operator (and, from M3,
    the agent itself) relocates a board while a conversation is
    happening, and the very next reply knows.

    The session is built against a view with a real engine behind it,
    which is the shape `app.py` composes, and the write goes through the
    repository the way every other device write does. The activation
    happened before the write, so a record captured there would answer
    the old location forever; the half is asserted unbuilt for the same
    reason the memory suite asserts it, because a rebuild would be the
    other way this could pass.
    """
    a_named_board()

    config = base_config()
    servers = CountingServers()
    llm = RecordingLlm()
    scripts = {"poet": llm}
    generations = world(config, providers=agent_providers(config, cast(Any, scripts)))
    bindings = DeviceBindings(generations, read_engine(DatabaseConfig()))
    try:
        session = session_for(
            config,
            POET_MAC,
            cast(Any, scripts),
            mcp_servers=servers,
            generations=generations,
            devices=bindings,
        )

        await run_reply(session, "hello")
        with store_at() as store:
            store.relocate_device(POET_MAC, LOCATION)
        await run_reply(session, "where are you")
    finally:
        bindings.dispose()

    assert llm.systems[0] == f"POET\n\n{device_introduction(NAME, None)}"
    assert llm.systems[1] == f"POET\n\n{device_introduction(NAME, LOCATION)}"
    # And the activation's half was never rebuilt to notice it: a
    # rebuild is what asks the registry, and it was asked once.
    assert servers.asked == ["poet"]


async def test_a_renamed_device_is_renamed_for_the_next_reply() -> None:
    """The same clock, for the fact an operator changes rather than a
    conversation: a rename lands in the next prompt and the id under it
    does not move, which is what the record's identity is for."""
    before = a_named_board()

    config = base_config()
    llm = RecordingLlm()
    scripts = {"poet": llm}
    generations = world(config, providers=agent_providers(config, cast(Any, scripts)))
    bindings = DeviceBindings(generations, read_engine(DatabaseConfig()))
    try:
        session = session_for(
            config,
            POET_MAC,
            cast(Any, scripts),
            generations=generations,
            devices=bindings,
        )

        await run_reply(session, "hello")
        with store_at() as store:
            store.rename_device(POET_MAC, "Hallway Speaker")
            after = store.read_device(POET_MAC).entry.id
        await run_reply(session, "and now")
    finally:
        bindings.dispose()

    assert NAME in llm.systems[0]
    assert "Hallway Speaker" in llm.systems[1]
    assert after == before


async def test_a_re_bound_board_does_not_rename_a_conversation_in_flight() -> None:
    """The failure the stable identity exists to prevent, from the
    session's side.

    A conversation attaches to the record standing at its MAC when it
    connects. An operator then deletes that device and binds the same
    board again, which mints a second record at the same address, and
    names it. The conversation still talking is addressed by the
    identity it attached to, so it is told nothing about its device
    rather than told another record's name: the device it was speaking
    through is gone, and the honest reply is silence about it.
    """
    a_named_board()

    config = base_config()
    llm = RecordingLlm()
    scripts = {"poet": llm}
    generations = world(config, providers=agent_providers(config, cast(Any, scripts)))
    bindings = DeviceBindings(generations, read_engine(DatabaseConfig()))
    try:
        session = session_for(
            config,
            POET_MAC,
            cast(Any, scripts),
            generations=generations,
            devices=bindings,
        )

        await run_reply(session, "hello")
        with store_at() as store:
            store.delete_device(POET_MAC)
            store.bind_device(POET_MAC, ["poet"])
            store.rename_device(POET_MAC, "Hallway Speaker")
        await run_reply(session, "and now")

        # And a conversation opening now attaches to the record that is
        # there now, which is what makes this a rule about one
        # conversation rather than about the deployment.
        fresh = RecordingLlm()
        opened = session_for(
            config,
            POET_MAC,
            cast(Any, {"poet": fresh}),
            generations=world(
                config, providers=agent_providers(config, cast(Any, {"poet": fresh}))
            ),
            devices=bindings,
        )
        await run_reply(opened, "hello")
    finally:
        bindings.dispose()

    assert llm.systems[0] == f"POET\n\n{device_introduction(NAME, None)}"
    assert llm.systems[1] == "POET"
    assert "Hallway Speaker" not in llm.systems[1]
    assert fresh.systems == [f"POET\n\n{device_introduction('Hallway Speaker', None)}"]


async def test_the_record_is_read_once_a_round_and_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read on the loop would stop every other conversation in this
    process for the length of a query, once per round of every reply,
    and a second read per round would double what a reply pays for
    knowing where it is."""
    ran: list[int] = []
    real = DeviceBindings.record_now

    def record_now(self: DeviceBindings, attached: Any) -> Any:
        ran.append(threading.get_ident())
        return real(self, attached)

    monkeypatch.setattr(DeviceBindings, "record_now", record_now)
    script = ScriptedLlm([[call("ghost_tool")], "Answered anyway."])
    session = session_for(named_config(), POET_MAC, {"poet": script})

    await run_reply(session, "hello")

    assert len(script.seen) == 2, "the reply did not run two rounds"
    assert len(ran) == 2, "the record was not read exactly once per round"
    assert all(where != threading.get_ident() for where in ran)


async def test_two_devices_talking_at_once_are_each_told_their_own() -> None:
    """One process, two conversations, two boards. The record is read
    per session rather than held anywhere shared, so the replies cannot
    tell each other's device about itself."""
    config = base_config(
        devices={
            POET_MAC: {"agents": ["poet"], "name": NAME, "location": LOCATION},
            BOTH_MAC: {"agents": ["poet"], "name": "Study Speaker", "location": "the study"},
        }
    )
    kitchen = RecordingLlm()
    study = RecordingLlm()
    first = session_for(config, POET_MAC, {"poet": kitchen})
    second = session_for(config, BOTH_MAC, {"poet": study})

    await asyncio.gather(
        run_reply(first, "hello"), run_reply(second, "hello"), run_reply(first, "again")
    )

    assert all(NAME in system and "Study Speaker" not in system for system in kitchen.systems)
    assert all(
        "Study Speaker" in system and NAME not in system for system in study.systems
    )
    assert len(kitchen.systems) == 2 and len(study.systems) == 1


# What never leaves the prompt


# Shaped so a substring check for either cannot match by accident, and
# credential-shaped because that is the paste an operator makes into a
# free-text field and the sentence a person says out loud to a device.
LEAKY_NAME = "sk-name-4f8b2c9e-never-a-real-credential"

LEAKY_LOCATION = "sk-place-7a1d6b3f-never-a-real-credential"


def _written(records: list[logging.LogRecord]) -> str:
    """Every captured record in both shipped formats plus its own
    fields, which is where a structured value that never reaches a
    sentence would still be."""
    text = logging.Formatter(logs.TEXT_FORMAT)
    formatter = logs.JsonFormatter()
    return "".join(
        text.format(record) + str(record.__dict__) + formatter.format(record)
        for record in records
    )


async def test_neither_field_reaches_an_event_or_a_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The two are two trust classes and neither is on a retained
    surface. The name is the operator's and could have gone where
    `board` and `version` go; it does not, because the MAC already
    identifies the device and a second home for a name is a name that
    goes stale at the next rename. The location cannot: it is what
    somebody said out loud, and the structured-events row of
    `docs/architecture/observability-surfaces.md` is metadata only.

    Absence, not sanitization: nothing is being cleaned on the way to
    these surfaces, because nothing takes either value there.
    """
    llm = RecordingLlm()
    with caplog.at_level(logging.DEBUG):
        session = session_for(
            named_config(LEAKY_NAME, LEAKY_LOCATION), POET_MAC, {"poet": llm}
        )
        await run_reply(session, "hello")

    # The model really was told, so this is a test about where the
    # values went rather than about a deployment that carries none.
    (system,) = llm.systems
    assert LEAKY_NAME in system and LEAKY_LOCATION in system
    written = _written(caplog.records)
    assert caplog.records, "nothing was logged, so nothing was checked"
    assert LEAKY_NAME not in written
    assert LEAKY_LOCATION not in written


async def test_neither_field_reaches_the_capture_manifest(tmp_path: Path) -> None:
    """The recording an operator switches on for a hardware problem, and
    the decision track beside it. Both are written from the events, and
    a capture is kept as a file on disk for as long as its retention
    says, which is why a conversation-derived string must never be in
    one."""
    config = base_config(
        server={"capture": {"enabled": True, "dir": str(tmp_path / "captures")}},
        devices={
            normalize_mac(DEVICE_MAC): {
                "agents": ["poet"],
                "name": LEAKY_NAME,
                "location": LEAKY_LOCATION,
            }
        },
    )
    generations = world(config, providers=built_world(config))
    bindings = DeviceBindings.snapshot_only(generations)
    factory = bespoke_runtime_factory(
        generations, McpServers({}), lane_memory(), None, None, bindings
    )
    websocket = LoopingSocket()
    captures = CaptureStore(tmp_path / "captures", 900.0, 2000.0, 0.0)
    session = DeviceSession(cast(Any, websocket), generations, factory, captures)

    task = asyncio.create_task(session.run())
    try:
        for _ in range(500):
            await asyncio.sleep(0.01)
            if session.runtime is not None and list(
                (tmp_path / "captures").glob("*.json")
            ):
                break
        else:
            raise AssertionError("the capture never opened")
        # The record really is reachable from this session, so the
        # absence below is about what the capture writes rather than
        # about a session that knows nothing.
        assert bindings.attachment_for(DEVICE_MAC).record is not None
    finally:
        await websocket.close()
        await task

    # The manifest and the decision track beside it, which are the two
    # text files a capture leaves behind; the audio is the third and
    # carries no field at all.
    written = "".join(
        path.read_text()
        for path in (tmp_path / "captures").iterdir()
        if path.suffix in {".json", ".jsonl"}
    )
    assert json.loads(next((tmp_path / "captures").glob("*.json")).read_text())
    assert LEAKY_NAME not in written
    assert LEAKY_LOCATION not in written
