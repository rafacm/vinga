"""The assistant's own playback, and what it leaves behind in the ear
that has to hear the answer.

A realtime device streams its microphone through a reply, so everything
the endpointer is fed for ten seconds is the assistant talking, arriving
in the room about 760 ms behind the server. Silero is recurrent: what it
has heard is what it scores the next window against, and a detector
sitting in that much of its own voice scores the user's answer below the
threshold that would otherwise have heard it. The first answer after a
reply is missed and a second, later attempt succeeds, which is the
symptom #70 attributed and #456 fixes.

The claim here is about the wiring, so it is driven through a real
reply: the runtime's own `_reply` is what ends, and what it does on its
way out is what this file is about. The endpointer is a double, because
the mechanism and not the model is what is on trial: a real Silero
missing this audio needs the capture that diagnosed it, and a synthetic
tone tells a real model nothing. What the double reproduces is the one
property that matters, that audio already fed decides what the next
window is heard as.
"""

import asyncio
from typing import Any, cast

import pytest

from tests.support.configs import DEVICE_MAC
from tests.support.sessions import (
    listening_in_realtime,
    session_for,
    start_reply,
    turn_taking,
    wait_for_reply,
)
from tests.support.sockets import OrderedSocket
from tests.support.wire import speech_pcm
from vinga_server.config import Config
from vinga_server.device.boundary import PIPELINE_SAMPLE_RATE
from vinga_server.providers.mock import EnergyEndpointer

pytestmark = pytest.mark.asyncio

# The rate a device streams its microphone at, and the rate this test
# streams at while a reply is going out. Everything below is a whole
# number of these.
FRAME_MS = 20

# How long the assistant's reply takes to pace out of the socket. The
# mock voice's tone length follows the text and the frame pacer sends it
# in real time, so this is the window the echo is fed inside: longer
# than the echo below with room to spare, and short enough not to be
# what this test costs.
REPLY_MS = 1500

# How long the room hands the reply back for. Fed at frame cadence
# rather than in a burst, which is the whole of what makes it echo
# rather than a test outrunning the reply it is talking over.
ECHO_MS = 800

# How much audio this endpointer can carry before it stops hearing
# speech at all. The session #70 diagnosed carried about ten seconds of
# it. What matters here is the ordering: more than the answer below, so
# a cleared detector hears it, and less than the echo above, so an
# uncleared one does not.
DEAFENING_MS = 600

# One 20 ms frame of the assistant's voice as the room returns it: real
# audio, and quiet enough that the endpointer does not call it speech,
# which is what the capture shows (`speech_ms` flat at zero through the
# whole reply while the echo arrived at -20 to -50 dBFS).
ECHO = b"".join(
    (200 if (n // 8) % 2 else -200).to_bytes(2, "little", signed=True)
    for n in range(PIPELINE_SAMPLE_RATE * FRAME_MS // 1000)
)
SILENCE = b"\x00" * len(ECHO)

# What the user says, and the pause after it the endpointer closes the
# utterance on.
ANSWER_MS = 200
TRAILING_SILENCE_MS = 200.0
PAUSE_MS = 240


def spoken_config() -> Config:
    """One agent on mock providers, with a voice whose replies take real
    time to go out. `config_with_agent` builds the same world with the
    default voice, which finishes pacing in a few frames and leaves
    nothing for a room to echo."""
    return Config(
        providers={
            "llm": {"mock": {"type": "mock"}},
            "asr": {"mock": {"type": "mock", "text": "the question"}},
            "tts": {"mock": {"type": "mock", "ms_per_char": 1, "min_ms": REPLY_MS}},
            "vad": {"mock": {"type": "mock"}},
        },
        agents={"assistant": dict.fromkeys(("llm", "asr", "tts", "vad"), "mock")},
        default_agent="assistant",
    )


class CarriesWhatItHeard:
    """The energy endpointer with the one property Silero has and it
    does not: what it has already been fed decides what it makes of the
    next chunk.

    Past `DEAFENING_MS` of audio with no `forget_audio` in between it
    hears nothing at all, which is the shape of the miss rather than its
    magnitude. The accounting underneath is the real endpointer's, so
    what survives a `forget_audio` is not this class's opinion of what
    should.
    """

    def __init__(self) -> None:
        self._inner = EnergyEndpointer(trailing_silence_ms=TRAILING_SILENCE_MS)
        self._carried_ms = 0.0

    def feed(self, pcm: bytes) -> bool:
        self._carried_ms += len(pcm) / 2 / PIPELINE_SAMPLE_RATE * 1000
        # Deaf, not starved: the chunk is still accounted for, at the
        # same length, so only what it is heard as changes.
        heard = bytes(len(pcm)) if self._carried_ms > DEAFENING_MS else pcm
        return self._inner.feed(heard)

    def reset(self) -> None:
        self._inner.reset()
        self._carried_ms = 0.0

    def forget_audio(self) -> None:
        self._carried_ms = 0.0

    def speech_start(self) -> int | None:
        return self._inner.speech_start()

    def speech_ms(self) -> float:
        return self._inner.speech_ms()


def talking() -> tuple[Any, OrderedSocket]:
    """A realtime session on mock providers, its endpointer replaced by
    one that carries what it heard, on a device that counts the frames
    it was sent."""
    socket = OrderedSocket()
    session = session_for(spoken_config(), DEVICE_MAC, websocket=cast(Any, socket))
    listening_in_realtime(session)
    turn_taking(session).endpointer = CarriesWhatItHeard()
    return session, socket


async def until(ready: Any, complaint: str) -> None:
    """Wait for something the reply task has to reach, on the loop this
    test shares with it. A wait that never ends is the test failing with
    its own sentence."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while loop.time() < deadline:
        if ready():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(complaint)


async def feed(session: Any, frame: bytes, duration_ms: int) -> None:
    """Mic frames, through the edge's own way in, as fast as they will
    go. Nothing else is running while this is called, so how long it
    takes carries no claim; `echo_through` below is the one that does.
    """
    for _ in range(duration_ms // FRAME_MS):
        await session.runtime.audio(frame)
        await asyncio.sleep(0)


async def echo_through(session: Any, duration_ms: int) -> None:
    """The room feeding the reply back while that reply is still going
    out of the socket.

    Paced at frame cadence, because that is what makes it concurrent
    with anything: a burst of the same bytes finishes in under a
    millisecond, before the pacer's next frame, and would leave a test
    that fed a reply's worth of echo into a reply that never got a turn
    to send any of it.

    The assertion is per frame rather than once at the end, for the same
    reason: what poisons a recurrent detector is being fed the
    assistant's own audio for the WHOLE of a reply, so a feed that
    outran the reply and finished into a silent session would be pinning
    something else.
    """
    for _ in range(duration_ms // FRAME_MS):
        assert session.runtime.replying(), "the reply ended before the echo did"
        await session.runtime.audio(ECHO)
        await asyncio.sleep(FRAME_MS / 1000)


async def test_the_first_answer_after_a_reply_is_heard() -> None:
    """The regression, end to end.

    A reply runs while the room feeds its echo back, and the moment it
    ends the user answers the question it asked. Without the reset at
    the end of the reply the endpointer is still sitting in four seconds
    of the assistant's own voice, hears nothing, and the answer is lost:
    `speech_ms` stays at zero, no utterance ever ends, and the session
    goes on listening as if nobody had spoken.
    """
    session, socket = talking()
    endpointer = cast(CarriesWhatItHeard, turn_taking(session).endpointer)

    start_reply(session, speech_pcm(320))
    # Not merely scheduled: frames of this reply are on the wire, which
    # is the only state in which a room has anything to echo back.
    await until(
        lambda: session.speaking_started_at() is not None,
        "the reply never started speaking",
    )

    sent = socket.frames
    await echo_through(session, ECHO_MS)
    # Concurrent, and measured rather than asserted from the shape of
    # the code: the device was still being sent this reply's audio while
    # the microphone was handing its echo back.
    assert socket.frames > sent, "no reply audio went out while the echo came in"
    # The premise: the echo is not speech, so nothing about this reply
    # looks like a barge-in. What it is, is audio the detector carries.
    assert endpointer.speech_ms() == 0.0
    await wait_for_reply(session)

    await feed(session, speech_pcm(FRAME_MS), ANSWER_MS)
    assert endpointer.speech_ms() == ANSWER_MS, "the answer was not heard"
    await feed(session, SILENCE, PAUSE_MS)

    # Heard, ended, and being answered.
    assert session.runtime.replying(), "the answer never became a turn"
    await session.runtime.drain(5.0)
