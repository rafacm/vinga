"""Which agent and which thread every emission names, pinned.

A session's active pair (the agent talking, the thread it is talking
on) is written by the transitions and read by every emitter on both
sides of the device boundary. These pins hold what each emission says
about it, as typed payload values rather than as rendered sentences, so
that moving where the pair lives is checked against what was said
before the move and not against what the move meant to say.

Two kinds. The first drives every transition a session has in one
sequence (connect, a handover, the handover back, a new conversation,
a resume) and pins every pair an emission carried, in order. The second
holds the two readers that take the pair after an await a transition
can land in, the edge's paced send and the filler runner, each
suspended on a gate while the pair moves under it, and pins what the
emissions after the gate say. Today each of those reads the pair as it
stands at the emit site, and that is what is pinned: an emitter that
took the pair on entry instead would name the agent that was talking
before the gate, which is a different record of the same session.

Nothing here is about whether that is the right attribution. It is the
attribution the server makes, written down before anything moves.
"""

import asyncio
import logging
import re
from typing import Any, cast

import pytest

from tests.support.boundary import FakeDevice, filler_runner
from tests.support.configs import BOTH_MAC, OUTPUT_RATE, base_config
from tests.support.events import fields_of, only
from tests.support.providers import ScriptedLlm
from tests.support.sessions import (
    call,
    device_session,
    hand_over_to,
    run_reply,
    session_for,
    talking,
    talking_thread,
)
from tests.support.stores import StoredThreads, a_backlog, a_candidate
from vinga_server.conversations import threads
from vinga_server.device.boundary import DeviceOutput, PlayableAudio
from vinga_server.events import SessionEvents
from vinga_server.events.values import FallbackReason
from vinga_server.filler import FallbackClip, FillerClips

# A stored thread in the shape the runtime mints, which the resume at
# the end of the sequence moves onto.
GALAXY = "1f0c1d2e3a4b5c6d7e8f90a1b2c3d4e5"

MINTED = re.compile(r"^[0-9a-f]{32}$")

# Every payload key that names half of a pair.
PAIR_KEYS = (
    "agent",
    "conversation",
    "from_agent",
    "to_agent",
    "from_conversation",
    "to_conversation",
)


def pairs_named(caplog: pytest.LogCaptureFixture) -> list[tuple[str, dict[str, str]]]:
    """Every event that named any half of a pair, with those fields and
    nothing else, in emission order. A thread the runtime minted is
    renamed by its first appearance (`T1`, `T2`, ...), since the value
    is a fresh uuid every run and what is pinned is which thread, not
    which bytes; the stored thread keeps its own name."""
    names: dict[str, str] = {GALAXY: "GALAXY"}
    said: list[tuple[str, dict[str, str]]] = []
    for record in caplog.records:
        fields = fields_of(record)
        if "event" not in fields:
            continue
        named = {key: str(fields[key]) for key in PAIR_KEYS if key in fields}
        if not named:
            continue
        for key, value in named.items():
            if key.endswith("conversation"):
                if value not in names:
                    assert MINTED.match(value), f"{key} is not a minted id: {value}"
                    names[value] = f"T{len(names)}"
                named[key] = names[value]
        said.append((str(fields["event"]), named))
    return said


async def test_every_transition_leaves_the_pair_its_emissions_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Connect on the poet's first thread, hand over to the tutor's,
    hand back to the poet's first (continued, not minted again), start
    a new one, and resume a stored one. Every emission on the way names
    the pair standing when it was said, and each move's own event names
    both sides of it."""
    poet = ScriptedLlm(
        [
            [call("switch_agent", agent="tutor")],
            "Back with you.",
            [call("new_conversation")],
            "New topic.",
            [call("resume_conversation", description="the galaxy")],
            [call("resume_conversation", conversation=GALAXY)],
            "Right, galaxies.",
        ]
    )
    tutor = ScriptedLlm(["Tutor here.", [call("switch_agent", agent="poet")]])
    store = StoredThreads(
        found={"poet": threads.Candidates(matched=True, found=(a_candidate(GALAXY),))},
        held={GALAXY: a_backlog(GALAXY, said=[("what is out there", "Galaxies.")])},
    )
    config = base_config(server={"conversations": {"enabled": True, "resumption": True}})

    with caplog.at_level(logging.DEBUG):
        session = session_for(
            config, BOTH_MAC, {"poet": poet, "tutor": tutor}, threads=store
        )
        for said in ("the tutor please", "back to the poet", "something else", "the galaxy"):
            await run_reply(session, said)

    poet_first = {"agent": "poet", "conversation": "T1"}
    tutors = {"agent": "tutor", "conversation": "T2"}
    fresh = {"agent": "poet", "conversation": "T3"}
    resumed = {"agent": "poet", "conversation": "GALAXY"}
    assert pairs_named(caplog) == [
        # Connect: the first agent's thread is minted at its activation.
        ("prompt_assembled", poet_first),
        ("llm_round", poet_first),
        # The handover, and the tutor's own thread minted with it.
        ("prompt_assembled", tutors),
        (
            "handover",
            {
                "from_agent": "poet",
                "to_agent": "tutor",
                "from_conversation": "T1",
                "to_conversation": "T2",
            },
        ),
        ("llm_round", tutors),
        ("llm_round", tutors),
        # The handover back continues the poet's first thread.
        ("prompt_assembled", poet_first),
        (
            "handover",
            {
                "from_agent": "tutor",
                "to_agent": "poet",
                "from_conversation": "T2",
                "to_conversation": "T1",
            },
        ),
        ("llm_round", poet_first),
        # A new conversation says nothing of its own; the round after
        # it is the first emission on the new thread.
        ("llm_round", poet_first),
        ("llm_round", fresh),
        # The search and the selection, then the resumed thread.
        ("llm_round", fresh),
        ("tool_call", fresh),
        ("llm_round", fresh),
        ("conversation_resumed", {"conversation": "GALAXY"}),
        ("llm_round", resumed),
    ]


# --- the edge's paced send ----------------------------------------------


class GatedSocket:
    """A websocket whose first frame is held until the test releases it,
    and which says when that frame has arrived, so a handover can land
    at exactly the instant the pacer is inside its delivery."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.frames: list[bytes] = []
        self.arrived = asyncio.Event()
        self.release = asyncio.Event()

    async def send_text(self, text: str) -> None:
        self.texts.append(text)

    async def send_bytes(self, data: bytes) -> None:
        self.arrived.set()
        await self.release.wait()
        self.frames.append(data)


async def test_speaking_started_names_the_pair_standing_when_the_first_frame_lands(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The edge stamps `speaking_started` after the pacer has delivered
    the reply's first frame, and a handover can land while that
    delivery is held. The event names whoever is talking when it is
    said, which here is the agent the handover moved to, on its own
    thread."""
    socket = GatedSocket()
    session = device_session(base_config(), BOTH_MAC, websocket=socket)
    before = (talking(session), talking_thread(session))

    with caplog.at_level(logging.INFO):
        sending = asyncio.create_task(session.send_audio(PlayableAudio([b"first-frame"])))
        await socket.arrived.wait()
        hand_over_to(session, "tutor")
        after = (talking(session), talking_thread(session))
        socket.release.set()
        await sending

    assert before[0] == "poet"
    assert after[0] == "tutor"
    assert after[1] != before[1]
    started = fields_of(only(caplog, "speaking_started"))
    assert (started["agent"], started["conversation"]) == after


# --- the filler runner ----------------------------------------------------

# A quarter second of clip at the device's own rate, so the resampling
# in the middle changes nothing and the clip is several frames.
CLIP = b"\x11\x22" * (OUTPUT_RATE // 4)

DELAY_MS = 10.0
# Comfortably past the delay: a fire that was going to happen has.
FIRED_S = 0.05


def clips_for(*phrases: str) -> FillerClips:
    return FillerClips(
        delay_ms=DELAY_MS,
        phrases=phrases,
        clips=tuple(CLIP for _ in phrases),
        sample_rate=OUTPUT_RATE,
    )


FILLERS = {"poet": clips_for("Hmm."), "tutor": clips_for("Let me think.")}


class Floor:
    """The floor as the fire-time stand-down reads it, set by the test."""

    def __init__(self, speech_ms: int = 0, paused: bool = False) -> None:
        self.speech = speech_ms
        self.paused = paused

    def speech_ms(self) -> int:
        return self.speech

    @property
    def output_paused(self) -> bool:
        return self.paused


async def fired_after_a_handover(
    caplog: pytest.LogCaptureFixture, floor: Floor
) -> tuple[FakeDevice, Any]:
    """Arm the mask with the poet talking, let the timer start, hand
    over to the tutor while it runs, and let it fire. Answers the device
    and the pair the handover left."""
    device = FakeDevice()
    runner, pair = filler_runner(
        SessionEvents("pair-attribution"),
        cast(DeviceOutput, device),
        FILLERS,
        ("poet", "tutor"),
        floor,
    )
    with caplog.at_level(logging.INFO):
        runner.arm()
        # One turn of the loop: the fire task has started and is inside
        # its delay, which is the window a handover lands in.
        await asyncio.sleep(0)
        moved = pair.activate("tutor")
        await asyncio.sleep(FIRED_S)
        await runner.settle()
    return device, moved


async def test_a_fire_names_the_pair_standing_when_it_fires(
    caplog: pytest.LogCaptureFixture,
) -> None:
    device, moved = await fired_after_a_handover(caplog, Floor())

    played = fields_of(only(caplog, "filler_played"))
    assert (played["agent"], played["conversation"]) == (moved.agent, moved.conversation)
    assert moved.agent == "tutor"
    assert device.sent, "the fire played nothing"


async def test_a_fire_into_speech_names_the_pair_standing_when_it_fires(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, moved = await fired_after_a_handover(caplog, Floor(speech_ms=300))

    skipped = fields_of(only(caplog, "filler_skipped"))
    assert skipped["reason"] == "user_speaking"
    assert (skipped["agent"], skipped["conversation"]) == (moved.agent, moved.conversation)


async def test_a_fire_into_a_confirmation_names_the_pair_standing_when_it_fires(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, moved = await fired_after_a_handover(caplog, Floor(paused=True))

    skipped = fields_of(only(caplog, "filler_skipped"))
    assert skipped["reason"] == "barge_in_pending"
    assert (skipped["agent"], skipped["conversation"]) == (moved.agent, moved.conversation)


class HeldDisplay(FakeDevice):
    """A device that holds the failure phrase's display send open until
    the test releases it, and says when it has arrived."""

    def __init__(self) -> None:
        super().__init__()
        self.arrived = asyncio.Event()
        self.release = asyncio.Event()

    async def sentence_started(self, text: str) -> None:
        self.arrived.set()
        await self.release.wait()
        await super().sentence_started(text)


async def test_a_fallback_says_the_phrase_it_began_with_and_names_the_pair_it_ends_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The phrase is looked up once, on entry, by the agent talking
    then; the record is written after the deliveries, and names the pair
    standing when it is written. A handover landing while the display
    send is held therefore shows the poet's words and attributes them
    to the tutor, which is what the server does today."""
    device = HeldDisplay()
    runner, pair = filler_runner(
        SessionEvents("pair-attribution"),
        cast(DeviceOutput, device),
        {},
        ("poet", "tutor"),
        Floor(),
        {
            "poet": FallbackClip(phrase="The poet is sorry.", clip=CLIP, sample_rate=OUTPUT_RATE),
            "tutor": FallbackClip(
                phrase="The tutor is sorry.", clip=CLIP, sample_rate=OUTPUT_RATE
            ),
        },
    )

    with caplog.at_level(logging.INFO):
        speaking = asyncio.create_task(runner.speak_fallback(FallbackReason.REPLY_FAILED))
        await device.arrived.wait()
        moved = pair.activate("tutor")
        device.release.set()
        await speaking

    assert ("sentence", "The poet is sorry.") in device.calls
    record = fields_of(only(caplog, "reply_fallback"))
    assert record["reason"] == "reply_failed"
    assert (record["agent"], record["conversation"]) == (moved.agent, moved.conversation)
