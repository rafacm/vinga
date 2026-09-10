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

from typing import Any, cast

import pytest

from tests.support.configs import DEVICE_MAC, config_with_agent
from tests.support.sessions import (
    listening_in_realtime,
    session_for,
    start_reply,
    turn_taking,
    wait_for_reply,
)
from tests.support.sockets import RecordingSocket
from tests.support.wire import speech_pcm
from vinga_server.device.boundary import PIPELINE_SAMPLE_RATE
from vinga_server.providers.mock import EnergyEndpointer

pytestmark = pytest.mark.asyncio

# How much audio this endpointer can carry before it stops hearing
# speech at all. The session #70 diagnosed carried about ten seconds of
# it; three is enough to drive here and leaves the answer below well
# inside what a cleared detector can take.
DEAFENING_MS = 3000

# One 20 ms frame of the assistant's voice as the room returns it: real
# audio, and quiet enough that the endpointer does not call it speech,
# which is what the capture shows (`speech_ms` flat at zero through the
# whole reply while the echo arrived at -20 to -50 dBFS).
ECHO = b"".join(
    (200 if (n // 8) % 2 else -200).to_bytes(2, "little", signed=True)
    for n in range(PIPELINE_SAMPLE_RATE * 20 // 1000)
)
FRAME_MS = 20
SILENCE = b"\x00" * len(ECHO)

# What the user says, and the pause after it the endpointer closes the
# utterance on: 400 ms of speech, then past the 700 ms trailing window.
ANSWER_MS = 400
PAUSE_MS = 760


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
        self._inner = EnergyEndpointer()
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


def talking() -> Any:
    """A realtime session on mock providers, its endpointer replaced by
    one that carries what it heard."""
    session = session_for(config_with_agent(), DEVICE_MAC, websocket=RecordingSocket())
    listening_in_realtime(session)
    turn_taking(session).endpointer = CarriesWhatItHeard()
    return session


async def feed(session: Any, frame: bytes, duration_ms: int) -> None:
    """Mic frames, through the edge's own way in. None of these awaits
    suspends unless the utterance ends, so audio fed before a reply is
    waited out really did arrive before it."""
    for _ in range(duration_ms // FRAME_MS):
        await session.runtime.audio(frame)


async def test_the_first_answer_after_a_reply_is_heard() -> None:
    """The regression, end to end.

    A reply runs while the room feeds its echo back, and the moment it
    ends the user answers the question it asked. Without the reset at
    the end of the reply the endpointer is still sitting in four seconds
    of the assistant's own voice, hears nothing, and the answer is lost:
    `speech_ms` stays at zero, no utterance ever ends, and the session
    goes on listening as if nobody had spoken.
    """
    session = talking()
    endpointer = cast(CarriesWhatItHeard, turn_taking(session).endpointer)

    start_reply(session, speech_pcm(320))
    await feed(session, ECHO, DEAFENING_MS + 1000)
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
