"""The tool a room moves its device with.

`set_device_location` is the one write a conversation may make to a
device record (#449, M3). A person says "you have been moved to the
office", the agent calls it, and the record the conversation attached to
says the office from the very next round on. The trust stance is the
issue's and is stated in the tool's own description: any voice in the
room may move a device, because being in the room is already what
talking to it takes.

Four claims:

- **It writes through the repository**, addressed by the record this
  conversation attached to rather than by the MAC that record stands at.
  What follows is that every rule about what a stored location may be is
  the rule an operator's command meets, and that the write lands on the
  record this conversation has been speaking through.
- **It is ordered.** Two of these in one round decide each other, so the
  loop runs them one at a time in the order the model issued them
  (`names.ORDERED_TOOL_NAMES`). Run concurrently, which of two places a
  device ends up in would be decided by which transaction reached the
  domain writer lock first.
- **It refuses in sentences a person can act on.** The repository's
  refusals are written for an operator at a command line and name
  commands, documents and fields; what comes back here is the tool
  layer's own closed vocabulary, with nothing the repository was handed
  and nothing a driver said in it.
- **A device with no record is refused rather than given one.** Minting
  a device record is an operator's act, and a room that could mint one
  by talking could give this server a device nobody installed.

The prompt half of the same fact, a device moved between two rounds
being moved for the next reply, is `test_session_device.py`. What is
here is the write that moves it.
"""

import asyncio
import contextlib
import logging
import threading
from collections.abc import Iterator
from typing import Any, cast

import pytest

from tests.support.config_cli import chain
from tests.support.configs import POET_MAC, base_config, world
from tests.support.events import both_formats
from tests.support.providers import ScriptedLlm
from tests.support.registry import AGENT, STAGES, store_at
from tests.support.sessions import agent_providers, call, run_reply, session_for
from tests.support.stores import holding_the_write_lock, the_lock_held
from vinga_server.config.loader import StorageError
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.store import ConfigStore
from vinga_server.db import open_database, read_engine
from vinga_server.device.bindings import DeviceBindings
from vinga_server.device.placement import DevicePlacements
from vinga_server.device.session import DeviceSession
from vinga_server.tools import builtin

NAME = "Kitchen Speaker"

OFFICE = "the office"

LANDING = "the landing"

# A board nothing has bound, which the lane's `default_agent` covers.
# The case the plan calls out by name: a device a default agent stands
# behind has no record at all, so there is nothing to write a place to.
UNBOUND_MAC = "aa:bb:cc:dd:ee:09"

# A location shaped so a substring hunt for it cannot match by accident,
# and shaped as this field's worst real value: a URL carrying a
# credential, said out loud into a microphone or transcribed out of one.
CREDENTIAL = "https://example.invalid/room?api_key=pw-m3-41c7de92-never-real"

# And an ordinary place, spelled so a substring hunt for it cannot match
# by accident: what a person actually says is "the office", and nothing
# could be asserted absent about that.
SENTINEL = "the office at 9f2c41de-never-a-real-room"

# How long a parked write waits for a second one to arrive before
# deciding none is coming. Long enough that a concurrent round really
# would overtake, short enough to pay once per ordered case.
OVERTAKE_S = 0.25


# --- the lane's database, and a session wired the way a server is -----


@contextlib.contextmanager
def placements() -> Iterator[DevicePlacements]:
    """What a server hands the runtime: the repository over the domain
    half, on an engine whoever built it disposes, which in a server is
    the application's lifespan."""
    engine = open_database(DatabaseConfig())
    try:
        yield DevicePlacements(ConfigStore(engine))
    finally:
        engine.dispose()


def a_named_board(mac: str = POET_MAC, name: str = NAME) -> str:
    """A board bound and named in the lane's database, and the id its
    record was minted with.

    Written through the repository rather than composed in Python,
    because everything here is about a view with a real engine behind
    it, which is the shape a served deployment has.
    """
    with store_at() as store:
        for stage in STAGES:
            store.set_provider(stage, "mock", {"type": "mock"})
        store.set_agent("poet", dict(AGENT))
        store.bind_device(mac, ["poet"])
        store.rename_device(mac, name)
        return store.read_device(mac).entry.id


def a_default_agent() -> None:
    """The other half of the unbound case: an agent every device with no
    binding of its own reaches, and no row at all for the board that
    then talks."""
    with store_at() as store:
        for stage in STAGES:
            store.set_provider(stage, "mock", {"type": "mock"})
        store.set_agent("poet", dict(AGENT))
        store.set_default_agent("poet")


def stored_location(mac: str = POET_MAC) -> str | None:
    with store_at() as store:
        return store.read_device(mac).entry.location


def said(script: ScriptedLlm) -> list[str]:
    """What the model was handed back, in the order it asked."""
    return [
        result.content
        for turns, _, _ in script.seen
        for turn in turns
        for result in turn.tool_results
    ]


@contextlib.contextmanager
def _submissions() -> Iterator[list[str]]:
    """Every location the repository was actually handed, in order.

    White-box on purpose and about one thing: whether a value the tool
    could have judged for itself was submitted to the layer that owns
    the judgement. Nothing else here reads it.
    """
    seen: list[str] = []
    real = ConfigStore.relocate_device_by_id

    def relocate(self: ConfigStore, device: str, location: str) -> Any:
        seen.append(location)
        return real(self, device, location)

    with pytest.MonkeyPatch.context() as patching:
        patching.setattr(ConfigStore, "relocate_device_by_id", relocate)
        yield seen


@contextlib.contextmanager
def a_session(
    script: ScriptedLlm, mac: str = POET_MAC, device_access: Any = None
) -> Iterator[DeviceSession]:
    """A session wired the way `app.py` wires one: a live view with a
    real engine over the device rows, and, unless a case is about its
    absence, the repository behind the tool that writes them."""
    config = base_config()
    scripts = {"poet": script}
    generations = world(config, providers=agent_providers(config, cast(Any, scripts)))
    bindings = DeviceBindings(generations, read_engine(DatabaseConfig()))
    try:
        yield session_for(
            config,
            mac,
            cast(Any, scripts),
            generations=generations,
            devices=bindings,
            device_access=device_access,
        )
    finally:
        bindings.dispose()


# --- the write itself -------------------------------------------------


async def test_a_place_the_agent_is_told_is_written_to_the_record() -> None:
    """The milestone in one case: a person says the device has moved and
    the record says so afterwards, through the repository rather than
    through any statement of this tool's own."""
    minted = a_named_board()
    script = ScriptedLlm(
        [[call("set_device_location", location=OFFICE)], "I have noted that."]
    )

    with placements() as writing, a_session(script, device_access=writing) as session:
        assert await run_reply(session, "you are in the office now") == [
            "I have noted that."
        ]

    assert stored_location() == OFFICE
    # And the rest of the record is where it was: a relocation moves the
    # place and nothing else, including the identity the conversation
    # addressed it by.
    with store_at() as store:
        record = store.read_device(POET_MAC).entry
    assert record.id == minted
    assert record.name == NAME


async def test_the_confirmation_names_the_place_on_one_line() -> None:
    """The confirmation carries the place, because what the model does
    with a result is speak and one that named no place would leave it
    guessing whether its own words landed, on one line, the way every
    memory confirmation quotes what it wrote.

    The row keeps exactly what was sent, padding and all, for the reason
    a device name is stored as typed: the fold is for uniqueness and
    this field has none. So the two strings are the same string today,
    and what is pinned here is the one difference that is observable,
    which is the normalization.
    """
    a_named_board()
    script = ScriptedLlm(
        [[call("set_device_location", location="  the   office ")], "Noted."]
    )

    with placements() as writing, a_session(script, device_access=writing) as session:
        await run_reply(session, "you are in the office")

    (answer,) = said(script)
    assert answer == builtin.MOVED.format(location=OFFICE)
    assert stored_location() == "  the   office "


async def test_the_write_addresses_the_record_the_conversation_attached_to() -> None:
    """The failure the stable id was minted to prevent, from the write
    side.

    A conversation attaches to the record standing at its MAC. An
    operator then deletes that device and binds the same board again,
    which mints a second record at the same address. The conversation in
    flight is then told it has moved. Addressed by MAC, that write lands
    on a record this conversation has never spoken through; addressed by
    the id, it refuses, and the new record is untouched.
    """
    a_named_board()
    script = ScriptedLlm(
        [[call("set_device_location", location=OFFICE)], "I could not."]
    )

    with placements() as writing, a_session(script, device_access=writing) as session:
        with store_at() as store:
            store.delete_device(POET_MAC)
            store.bind_device(POET_MAC, ["poet"])
        await run_reply(session, "you are in the office now")

    assert said(script) == [f'the tool "set_device_location" failed: {builtin.NO_DEVICE_RECORD}']
    assert stored_location() is None


async def test_the_write_runs_off_the_event_loop() -> None:
    """A synchronous write on the loop would hold every other
    conversation in this process for the length of a transaction that
    takes the domain writer lock first."""
    a_named_board()
    ran: list[int] = []
    real = ConfigStore.relocate_device_by_id

    def relocate(self: ConfigStore, device: str, location: str) -> Any:
        ran.append(threading.get_ident())
        return real(self, device, location)

    script = ScriptedLlm([[call("set_device_location", location=OFFICE)], "Noted."])
    with pytest.MonkeyPatch.context() as patching:
        patching.setattr(ConfigStore, "relocate_device_by_id", relocate)
        with placements() as writing, a_session(script, device_access=writing) as session:
            await run_reply(session, "you are in the office now")

    assert ran and all(where != threading.get_ident() for where in ran)


# --- two in one round, which is why it is an ordered tool -------------


@contextlib.asynccontextmanager
async def the_first_write_held_until_a_second_finishes() -> Any:
    """The first relocation held until a second one has FINISHED, and a
    record of when each of them ran.

    The shape `test_session_tools.py` uses for the memory writes, at the
    seam the tool loop awaits, with one thing changed and it is the
    thing that makes this a proof. Releasing the first as soon as the
    second ARRIVED left the two real writes racing for the domain lock
    afterwards: unordered, the second could still take it last and leave
    the right answer standing, so the assertion passed sometimes and the
    regression went unnoticed. A flaky proof reads exactly like a proof.

    So a second call runs its write to completion before the first is
    let go. Unordered, the two overlap and the first one commits last,
    which is the wrong place every time; ordered, no second call ever
    arrives while the first is running, so the first waits out the bound
    and they run in the model's order. The timeline is recorded as well,
    because "these two never overlapped" is the claim itself rather than
    a consequence of it.
    """
    finished = asyncio.Event()
    started = 0
    running = 0
    overlapped = False
    real = DevicePlacements.relocate

    async def relocate(self: DevicePlacements, device: str, location: str) -> str:
        nonlocal started, running, overlapped
        started += 1
        mine = started
        if mine == 1:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(finished.wait(), OVERTAKE_S)
        running += 1
        overlapped = overlapped or running > 1
        try:
            written = await real(self, device, location)
        finally:
            running -= 1
        if mine > 1:
            finished.set()
        return written

    with pytest.MonkeyPatch.context() as patching:
        patching.setattr(DevicePlacements, "relocate", relocate)
        yield lambda: overlapped


async def test_two_places_in_one_round_land_in_the_model_s_order() -> None:
    """A person really does say "you have been moved to the office, no,
    the landing" in one breath, and what has to be true afterwards is
    the landing.

    Run concurrently, the two writes take the domain writer lock in
    whatever order the pool hands the connections out, and the office
    would stand about half the time. `set_device_location` is in
    `ORDERED_TOOL_NAMES` for exactly this.

    What makes the difference observable is holding the first write
    until a second has finished its own: unordered, the first then
    commits last and leaves the office every time, and ordered, no
    second write is ever in flight to hold it. The overlap is asserted
    beside the answer, because not overlapping is the property and the
    stored place is only its consequence.
    """
    a_named_board()
    script = ScriptedLlm(
        [
            [
                call("set_device_location", location=OFFICE),
                call("set_device_location", location=LANDING),
            ],
            "The landing it is.",
        ]
    )

    with placements() as writing, a_session(script, device_access=writing) as session:
        async with the_first_write_held_until_a_second_finishes() as overlapped:
            await run_reply(session, "you are in the office, no, the landing")

    assert stored_location() == LANDING
    # And they never ran at the same time, which is the claim itself:
    # the answer above would be the right one by luck in a round that
    # let them race and happened to commit in the model's order.
    assert not overlapped()
    # And both were answered, in the order the model asked: a round that
    # ran them one at a time still hands the model one result per call.
    assert said(script) == [
        builtin.MOVED.format(location=OFFICE),
        builtin.MOVED.format(location=LANDING),
    ]


# --- the place is conversation text, and stays off every retained
# --- surface -----------------------------------------------------------


async def test_a_place_a_room_said_reaches_no_event_and_no_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The half of the plan's fifth finding this milestone owes.

    A location an agent writes originates from a person, so it is
    conversation-derived content, and the observability map's
    structured-events row is metadata only: a spoken string on a dated
    event row would sit on the telemetry surface with telemetry
    retention and no per-conversation erasure, unrewritten by any later
    correction. What identifies a device on those surfaces is its MAC,
    which is a trusted identifier and is there already.

    Absence rather than sanitization, because nothing takes this value
    to those surfaces at all: the round emits a `tool_call` event, which
    names the tool and says where the name came from, and that is the
    whole of what the event surface learns about this call.
    """
    a_named_board()
    script = ScriptedLlm(
        [[call("set_device_location", location=SENTINEL)], "Noted."]
    )

    with caplog.at_level(logging.DEBUG):
        with placements() as writing, a_session(script, device_access=writing) as session:
            await run_reply(session, "you have moved")

    # It was written, so this is a claim about a value that really
    # travelled rather than about one refused on the way in.
    assert stored_location() == SENTINEL
    assert SENTINEL not in both_formats(caplog)
    # And the call itself is on that surface under its name, which is
    # what makes the absence above a decision rather than an accident of
    # nothing having been emitted at all. `both_formats` renders each
    # record's structured half as well as its sentence, so a location on
    # an `extra` field would be found here.
    assert "set_device_location" in both_formats(caplog)


# --- the refusals, as what the agent says -----------------------------


async def test_a_device_a_default_agent_covers_is_refused_a_place() -> None:
    """The plan's own case. A default agent stands behind every board
    with no binding of its own, so a board can be served, talked to and
    have no record at all. Creating one is an operator's act: a room
    that could mint a record by talking could give this server a device
    nobody installed.
    """
    a_default_agent()
    script = ScriptedLlm(
        [[call("set_device_location", location=OFFICE)], "I cannot record that."]
    )

    with placements() as writing:
        with a_session(script, mac=UNBOUND_MAC, device_access=writing) as session:
            assert await run_reply(session, "you are in the office now") == [
                "I cannot record that."
            ]

    (answer,) = said(script)
    assert answer.endswith(builtin.NO_DEVICE_RECORD)
    # What a person is told is what to do about it, and what they are
    # not told is a command to run: whoever is in the room has no
    # command line.
    assert "vinga-server" not in answer


async def test_a_server_that_keeps_no_writable_records_says_so() -> None:
    """The other absence, and a different sentence because it is a
    different fact: a server composed from a configuration it was handed
    will not gain a writable device record while this conversation is
    happening, and nobody in the room can change that.

    Offered all the same, for the reason the two conversation tools are:
    an agent with no such tool answers "you have been moved" with "all
    right" and changes nothing.
    """
    a_named_board()
    script = ScriptedLlm(
        [[call("set_device_location", location=OFFICE)], "I cannot do that here."]
    )

    with a_session(script) as session:
        await run_reply(session, "you are in the office now")

    (answer,) = said(script)
    assert answer.endswith(builtin.PLACEMENT_UNAVAILABLE)
    assert stored_location() is None
    # The offer is still there, which is the whole point of answering
    # with a sentence rather than with nothing.
    assert "set_device_location" in [tool.name for tool in script.seen[0][1]]


async def test_a_call_with_no_place_at_all_never_reaches_the_repository() -> None:
    """The one refusal this layer keeps, and it is about the CALL rather
    than about a place: a missing argument is not a string, and the
    repository has no opinion on something that is not one. Nothing is
    submitted, so nothing is refused."""
    a_named_board()
    script = ScriptedLlm([[call("set_device_location")], "Where am I?"])

    with _submissions() as submitted:
        with placements() as writing, a_session(script, device_access=writing) as session:
            await run_reply(session, "you have moved")

    (answer,) = said(script)
    assert answer.endswith(builtin.LOCATION_NEEDS_A_PLACE)
    assert submitted == []


async def test_a_place_that_holds_nothing_is_refused_by_the_rule_that_owns_it() -> None:
    """Whitespace goes to the repository like any other string, and
    comes back as the sentence a room can act on.

    The point is the path rather than the answer. What counts as blank
    is `fold_device_name`, in the model that owns it and behind the
    database index written over it; a copy of that rule in the tool
    layer would be a second definition, furthest from its owner, and
    agreeing with it today is not the same as being it. So the value
    travels, the repository refuses it with a type, and the type is
    translated where the vocabulary lives.

    Both halves are asserted, because either alone passes for the wrong
    reason: the sentence alone would pass for a guard that never
    submitted anything, and the submission alone would pass for a
    refusal in somebody else's words.
    """
    a_named_board()
    blank = "\u00a0 \t "
    script = ScriptedLlm([[call("set_device_location", location=blank)], "Where am I?"])

    with _submissions() as submitted:
        with placements() as writing, a_session(script, relocations=writing) as session:
            await run_reply(session, "you have moved")

    (answer,) = said(script)
    assert answer.endswith(builtin.LOCATION_NEEDS_A_PLACE)
    assert submitted == [blank]
    assert stored_location() is None


async def test_a_place_the_repository_refuses_is_answered_as_a_place_problem(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The repository's own refusal, translated.

    A location that is a URL carrying a credential is refused by the
    repository in a sentence written for an operator: it says the value
    is stored as written and read back on every surface, and tells them
    to write a location rather than an address. A person who just said
    where a speaker is cannot act on any of that, and the refusal holds
    the rejected value behind it, which for this field is something
    somebody said out loud.

    So the sentence is this layer's own, and neither the value nor the
    repository's wording reaches the model, the logs or the chain.
    """
    a_named_board()
    script = ScriptedLlm(
        [[call("set_device_location", location=CREDENTIAL)], "I could not note that."]
    )

    with caplog.at_level(logging.DEBUG):
        with placements() as writing, a_session(script, device_access=writing) as session:
            await run_reply(session, "you have moved")

    (answer,) = said(script)
    assert answer.endswith(builtin.LOCATION_NOT_A_PLACE)
    assert CREDENTIAL not in answer
    assert CREDENTIAL not in both_formats(caplog)
    # And nothing of the repository's own sentence came with it: that
    # one names a remedy only an operator has.
    assert "stored exactly as it was written" not in answer
    assert stored_location() is None


async def test_a_refusal_carries_nothing_of_the_one_it_translates() -> None:
    """The same value one layer down, where the rule that produced this
    shape was written: a refusal raised inside a handler keeps the
    exception it was handling, and a configuration refusal can hold the
    whole rejected fragment behind it. So the sentence is chosen in the
    arm and raised outside it, and what travels is a `ValueError` with
    nothing attached in either direction.

    Asserted structurally as well as by hunting the value, because the
    hunt alone would pass for a refusal that happens to quote nothing
    today and would go on passing when one starts to.
    """
    minted = a_named_board()

    with placements() as writing:
        with pytest.raises(ValueError) as caught:  # noqa: PT011
            await writing.relocate(minted, CREDENTIAL)

    assert str(caught.value) == builtin.LOCATION_NOT_A_PLACE
    assert CREDENTIAL not in chain(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


async def test_a_database_that_will_not_answer_is_not_a_place_problem() -> None:
    """A storage failure and a value the repository refused are both
    `ConfigError`s, and only the order of the arms that catch them tells
    them apart.

    What it costs to get that wrong is a room being told the place it
    named is not a place, which is wrong about the world and something
    nobody can act on: saying it differently will not fix a database.
    """
    minted = a_named_board()

    with placements() as writing, pytest.MonkeyPatch.context() as patching:
        patching.setattr(
            ConfigStore,
            "relocate_device_by_id",
            lambda *args: (_ for _ in ()).throw(StorageError("the database said no")),
        )
        with pytest.raises(ValueError) as caught:  # noqa: PT011
            await writing.relocate(minted, OFFICE)

    assert str(caught.value) == builtin.PLACEMENT_FAILED


async def test_a_contended_database_is_answered_as_something_to_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another writer holding the domain chain's advisory lock: an
    operator applying a document, a second process, the configuration
    API. The write waits out the lock timeout and refuses retryably,
    which is a sentence a person can act on, because asking again in a
    moment is exactly what will work."""
    a_named_board()
    script = ScriptedLlm(
        [[call("set_device_location", location=OFFICE)], "Ask me again in a moment."]
    )

    with holding_the_write_lock(monkeypatch):
        with placements() as writing, a_session(script, device_access=writing) as session:
            with the_lock_held():
                assert await run_reply(session, "you are in the office now") == [
                    "Ask me again in a moment."
                ]

    (answer,) = said(script)
    assert answer.endswith(builtin.PLACEMENT_BUSY)
    assert stored_location() is None
