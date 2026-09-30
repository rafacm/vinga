"""A capture taken from a real session, rather than from calls to the
writer.

The unit tests for `capture.py` prove the file format. These prove the
wiring: that the microphone reaches channel 0 before the guards drop it,
that what was paced out reaches channel 1, that the events the session
already logs land in the decision track with offsets that index into the
audio, and that the manifest says what the capture was made against.
"""

import asyncio
import itertools
import json
import logging
import struct
import wave
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from tests.support.configs import (
    BOTH_MAC,
    DEVICE_MAC,
    DEVICE_UUID,
    FRAME_BYTES,
    FRAME_MS,
    base_config,
    config_with_agent,
    world,
)
from tests.support.events import both_formats
from tests.support.providers import ScriptedLlm, built_world
from tests.support.sessions import (
    agent_providers,
    attached_capture,
    call,
    drive_reply,
    end_utterance,
    handshaken,
    plant_utterance,
    start_reply,
    wait_for_reply,
)
from tests.support.sockets import LoopingSocket
from tests.support.stores import memory as lane_memory
from tests.support.wire import (
    collect_reply,
    connect,
    endpoint_silence,
    say_something,
    send_pcm,
    shake_hands,
    speech_pcm,
)
from vinga_server.app import create_app
from vinga_server.audio.opus import OpusEncoder
from vinga_server.capture import CAPTURE_RATE, CaptureStore
from vinga_server.config import Config
from vinga_server.device import recording as recording_module
from vinga_server.device.recording import recordings
from vinga_server.device.session import DeviceSession
from vinga_server.events import SESSION_LOGGER
from vinga_server.protocol import framing
from vinga_server.providers import (
    AsrResult,
    LlmEvent,
    LlmProvider,
    TextDelta,
    ToolChoice,
    ToolDef,
    Turn,
)
from vinga_server.providers.mock import MockAsr
from vinga_server.runtime.pipeline import bespoke_runtime_factory
from vinga_server.tools.mcp import McpServers


def capturing_config(tmp_path: Path, **kwargs: object):
    server: dict[str, object] = {
        "capture": {"enabled": True, "dir": str(tmp_path / "captures")}
    }
    server.update(kwargs)
    return config_with_agent(server=server)


def only_capture(tmp_path: Path) -> tuple[Path, Path, Path]:
    directory = tmp_path / "captures"
    wavs = list(directory.glob("*.wav"))
    assert len(wavs) == 1, f"expected one capture, found {wavs}"
    wav = wavs[0]
    return wav, wav.with_suffix(".jsonl"), wav.with_suffix(".json")


def channels(path: Path) -> tuple[list[int], list[int]]:
    with wave.open(str(path), "rb") as handle:
        raw = handle.readframes(handle.getnframes())
    samples = struct.unpack(f"<{len(raw) // 2}h", raw)
    return list(samples[0::2]), list(samples[1::2])


def events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def loudest(samples: list[int]) -> int:
    return max((abs(sample) for sample in samples), default=0)


def test_nothing_is_recorded_without_a_capture_section(tmp_path: Path) -> None:
    # Recording room audio is the opposite of what the rest of the
    # project promises, so it has to be asked for.
    with TestClient(create_app(config_with_agent())) as client:
        with connect(client) as websocket:
            shake_hands(websocket)
            say_something(websocket)
    assert not (tmp_path / "captures").exists()


def test_a_configured_section_records_nothing_until_it_is_enabled(
    tmp_path: Path,
) -> None:
    # The switch is the flag, not the section, so that turning capture
    # off does not mean deleting the directory and the budgets with it.
    # A section left in a config file must record nothing.
    config = config_with_agent(
        server={"capture": {"dir": str(tmp_path / "captures")}}
    )
    with TestClient(create_app(config)) as client:
        with connect(client) as websocket:
            shake_hands(websocket)
            texts, _ = say_something(websocket)
    assert texts, "the conversation did not run"
    assert not (tmp_path / "captures").exists(), "a disabled section still recorded"


def test_a_session_records_the_microphone_and_the_reply(tmp_path: Path) -> None:
    with TestClient(create_app(capturing_config(tmp_path))) as client:
        with connect(client) as websocket:
            shake_hands(websocket)
            say_something(websocket)

    wav, _, _ = only_capture(tmp_path)
    mic, reply = channels(wav)
    assert loudest(mic) > 0, "the microphone channel is silent"
    assert loudest(reply) > 0, "the reply channel is silent"


def test_the_reply_channel_holds_what_was_paced_out(tmp_path: Path) -> None:
    # Channel 1 is decoded back from the Opus that actually went to the
    # device, so it is what the speaker played rather than what was
    # synthesized. The mock TTS speaks a tone, so its presence is
    # visible as amplitude in the right channel and its absence in the
    # left while nothing is being said into the microphone.
    with TestClient(create_app(capturing_config(tmp_path))) as client:
        with connect(client) as websocket:
            shake_hands(websocket)
            say_something(websocket)

    wav, jsonl, _ = only_capture(tmp_path)
    mic, reply = channels(wav)
    started = next(e for e in events(jsonl) if e["event"] == "speaking_started")
    at = int(started["t_ms"] / 1000 * CAPTURE_RATE)
    # A tenth of a second after the first frame went out, the reply
    # channel is carrying audio.
    window = reply[at : at + CAPTURE_RATE // 10]
    assert loudest(window) > 0, "no reply audio where speaking_started says it began"


def test_the_microphone_is_recorded_even_when_the_guards_drop_it(tmp_path: Path) -> None:
    # The reason capture is hooked before the guards. With barge_in off
    # the session drops mic frames outright while it is speaking, and
    # those are precisely the frames that would explain a misfire.
    asked_ms, over_ms = 300, 900
    config = capturing_config(tmp_path, barge_in=False)
    with TestClient(create_app(config)) as client:
        with connect(client) as websocket:
            shake_hands(websocket)
            encoder = OpusEncoder()
            websocket.send_text(
                json.dumps({"type": "listen", "state": "start", "mode": "realtime"})
            )
            send_pcm(websocket, speech_pcm(asked_ms), encoder)
            endpoint_silence(websocket, encoder)
            # Talking over the reply while it streams, which this
            # configuration discards before it is even decoded.
            send_pcm(websocket, speech_pcm(over_ms), encoder)
            collect_reply(websocket)

    wav, jsonl, _ = only_capture(tmp_path)
    mic, _ = channels(wav)
    dropped = [e for e in events(jsonl) if e["event"] == "frames_dropped"]
    guarded = [e for e in dropped if "barge_in_off" in e["reasons"]]
    assert guarded, f"nothing was dropped by the guard; reasons seen: {dropped}"

    # The claim, and the reason capture is hooked before the guards: the
    # audio the session threw away is in the file anyway. Counted as
    # loud samples, because the frames arrive faster than realtime here
    # and so do not sit where a wall clock would put them; what matters
    # is that they are not missing.
    loud_ms = sum(1 for sample in mic if abs(sample) > 100) / CAPTURE_RATE * 1000
    assert loud_ms > (asked_ms + over_ms) * 0.7, (
        f"only {loud_ms:.0f} ms of microphone audio was recorded out of "
        f"{asked_ms + over_ms} ms spoken; the frames the guard dropped are missing"
    )


def test_the_microphone_is_recorded_before_the_device_asked_to_be_heard(
    tmp_path: Path,
) -> None:
    # The other guard the capture sits in front of. Frames arriving
    # before any `listen start` are dropped as `not_listening`, and the
    # capture holds them anyway.
    spoken_ms = 600
    with TestClient(create_app(capturing_config(tmp_path))) as client:
        with connect(client) as websocket:
            shake_hands(websocket)
            send_pcm(websocket, speech_pcm(spoken_ms), OpusEncoder())

    wav, jsonl, _ = only_capture(tmp_path)
    mic, _ = channels(wav)
    dropped = [e for e in events(jsonl) if e["event"] == "frames_dropped"]
    unheard = [e for e in dropped if "not_listening" in e["reasons"]]
    assert unheard, f"nothing was dropped as not listening; seen: {dropped}"
    loud_ms = sum(1 for sample in mic if abs(sample) > 100) / CAPTURE_RATE * 1000
    assert loud_ms > spoken_ms * 0.7, (
        f"only {loud_ms:.0f} ms of microphone audio was recorded out of "
        f"{spoken_ms} ms spoken; the frames nobody was listening to are missing"
    )


def test_the_decision_track_carries_the_events_with_offsets(tmp_path: Path) -> None:
    with TestClient(create_app(capturing_config(tmp_path))) as client:
        with connect(client) as websocket:
            shake_hands(websocket)
            say_something(websocket)

    wav, jsonl, _ = only_capture(tmp_path)
    recorded = events(jsonl)
    names = [record["event"] for record in recorded]
    for expected in ("session_open", "heard", "speaking_started", "replied"):
        assert expected in names, f"{expected} is missing from the decision track"

    mic, _ = channels(wav)
    audio_ms = len(mic) / CAPTURE_RATE * 1000
    for record in recorded:
        assert record["t_ms"] >= 0
        # Every event indexes into the audio, give or take the frame the
        # capture was closed on.
        assert record["t_ms"] <= audio_ms + FRAME_MS * 2, (
            f"{record['event']} at {record['t_ms']} ms is past {audio_ms:.0f} ms of audio"
        )


def test_the_endpointers_opinion_is_in_the_track(tmp_path: Path) -> None:
    with TestClient(create_app(capturing_config(tmp_path))) as client:
        with connect(client) as websocket:
            shake_hands(websocket)
            say_something(websocket)

    _, jsonl, _ = only_capture(tmp_path)
    vad = [record for record in events(jsonl) if record["event"] == "vad"]
    assert len(vad) > 3, "the endpointer was sampled at decision points only"
    assert max(record["speech_ms"] for record in vad) > 0


def test_the_manifest_says_what_the_capture_was_made_against(tmp_path: Path) -> None:
    config = capturing_config(tmp_path, barge_in_min_speech_ms=321.0)
    with TestClient(create_app(config)) as client:
        with connect(client) as websocket:
            shake_hands(websocket)
            say_something(websocket)

    _, _, manifest_path = only_capture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    # The thresholds verbatim, not a hash: an old capture analysed after
    # they change is misleading unless it states its own.
    assert manifest["barge_in"]["min_speech_ms"] == 321.0
    assert manifest["barge_in"]["enabled"] is True
    # The whole mapping, so a key coming back is a failure rather than
    # something nobody looked for. `refractory_ms` in particular is
    # ABSENT rather than null: a null would claim this session had the
    # gate and left it unbounded, where no key says the server has no
    # such gate at all.
    assert set(manifest["barge_in"]) == {
        "enabled",
        "min_speech_ms",
        "utterance_pre_roll_ms",
    }
    assert manifest["server"]["revision"]
    assert manifest["device"]["mac"] == DEVICE_MAC.lower()
    assert manifest["device"]["client"] == DEVICE_UUID
    assert manifest["agent"] == "assistant"
    # The resolved entries, per bound agent and per stage, from the one
    # derivation `session_open` also carries (#66). Four names and never
    # a configured option, which is what makes it sanitized by
    # construction; the exact model string is among the four, which is
    # what a capture outliving its code needs.
    assert manifest["providers"]["assistant"]["tts"]["type"] == "mock"
    assert manifest["providers"]["assistant"]["asr"]["name"] == "mock"
    assert manifest["capture"]["complete"] is True
    assert manifest["capture"]["sample_rate"] == CAPTURE_RATE
    assert manifest["audio"]["frame_duration_ms"] == FRAME_MS


def test_the_manifest_carries_the_firmware_the_device_reported(tmp_path: Path) -> None:
    # The firmware version is the most load-bearing field in the
    # manifest, because echo cancellation is firmware-side, and the OTA
    # check-in is the only place a device ever states it.
    from tests.support.checkin import SYSTEM_INFO
    from vinga_server.ota import OTA_PATH

    with TestClient(create_app(capturing_config(tmp_path))) as client:
        client.post(
            OTA_PATH,
            json=SYSTEM_INFO,
            headers={"Device-Id": DEVICE_MAC, "Client-Id": DEVICE_UUID},
        )
        with connect(client) as websocket:
            shake_hands(websocket)
            say_something(websocket)

    _, _, manifest_path = only_capture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    assert manifest["device"]["firmware"] == "2.4.0"
    assert manifest["device"]["board"] == "waveshare-esp32-s3-touch-lcd-1.54"


def test_a_device_that_never_checked_in_still_gets_a_capture(tmp_path: Path) -> None:
    # A restarted server has no record of a device that checked in
    # before it, and that must not cost the recording.
    with TestClient(create_app(capturing_config(tmp_path))) as client:
        with connect(client) as websocket:
            shake_hands(websocket)
            say_something(websocket)

    _, _, manifest_path = only_capture(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    assert "firmware" not in manifest["device"]
    assert manifest["device"]["mac"] == DEVICE_MAC.lower()


def test_a_conversation_survives_a_capture_directory_it_cannot_use(
    tmp_path: Path,
) -> None:
    # A recording is worth less than the conversation it is of.
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    config = config_with_agent(
        server={"capture": {"enabled": True, "dir": str(blocked / "captures")}}
    )
    with TestClient(create_app(config)) as client:
        with connect(client) as websocket:
            shake_hands(websocket)
            texts, _ = say_something(websocket)
    assert texts, "the conversation did not survive an unusable capture directory"


@pytest.mark.parametrize("frames", [FRAME_BYTES])
def test_the_two_channels_share_one_timeline(tmp_path: Path, frames: int) -> None:
    # The property the whole file exists for. The microphone is fed for
    # a known stretch before anything is said back, so the reply must
    # start later in the file than the speech did, by about the time it
    # actually took.
    with TestClient(create_app(capturing_config(tmp_path))) as client:
        with connect(client) as websocket:
            shake_hands(websocket)
            say_something(websocket)

    wav, jsonl, _ = only_capture(tmp_path)
    mic, reply = channels(wav)
    assert len(mic) == len(reply), "the channels are different lengths"

    def first_loud(samples: list[int]) -> int:
        for index, sample in enumerate(samples):
            if abs(sample) > 100:
                return index
        raise AssertionError("channel never carried audio")

    speech_at = first_loud(mic) / CAPTURE_RATE * 1000
    reply_at = first_loud(reply) / CAPTURE_RATE * 1000
    assert reply_at > speech_at, "the reply appears before the speech that prompted it"
    started = next(e for e in events(jsonl) if e["event"] == "speaking_started")
    assert abs(reply_at - started["t_ms"]) < 200, (
        f"the reply audio starts at {reply_at:.0f} ms but speaking_started "
        f"says {started['t_ms']:.0f} ms"
    )


# Shaped like something an operator would be horrified to find in a log,
# and planted on both links of an exception chain: what must not reach a
# retained surface is the whole chain, not only its outermost message.
CODEC_SENTINEL = "sk-live-3f9a21c7-never-a-real-credential"
# The same shape as a class name, which `type` accepts for any string:
# a library wrapping a far side's answer can raise an exception whose
# NAME is that answer (the correction `events/__init__.py` records
# beside `_offer`).
CODEC_CLASS_SENTINEL = "sk-live-8e0c4d12-planted-as-a-class-name"

UTTERANCE = b"\x00\x00" * 320


# What a media library raises when it cannot open a codec, where neither
# its name nor its message is anything this server chose.
CodecUnavailable: type[Exception] = type(CODEC_CLASS_SENTINEL, (RuntimeError,), {})


def unopenable_codecs(*args: object, **kwargs: object) -> object:
    """A `CaptureAudio` that will not build.

    Three codec objects open here, and opening one runs PyAV. The
    constructor is the only step of starting a capture that can raise
    for a reason nothing on this side chose, which is what makes it the
    step worth a regression test.
    """
    try:
        raise OSError(f"libopus: no encoder for {CODEC_SENTINEL}")
    except OSError as unopenable:
        raise CodecUnavailable(
            f"could not build the capture codecs for {CODEC_SENTINEL}"
        ) from unopenable


def capturing_session(tmp_path: Path) -> tuple[DeviceSession, LoopingSocket]:
    """A session with a capture store, driven through `run`.

    Through `run` rather than through a test client because what is
    under test is a step inside the guard and what the session holds
    afterwards, and a client hands back no session to ask.
    """
    config = capturing_config(tmp_path)
    captures = CaptureStore(tmp_path / "captures", 900.0, 2000.0, 0.0)
    generations = world(config, providers=built_world(config))
    factory = bespoke_runtime_factory(generations, McpServers({}), lane_memory(), None)
    websocket = LoopingSocket()
    session = DeviceSession(cast(Any, websocket), generations, factory, recordings(captures))
    return session, websocket


def manifest_of(tmp_path: Path) -> dict | None:
    found = list((tmp_path / "captures").glob("*.json"))
    return json.loads(found[0].read_text()) if found else None


async def test_a_capture_whose_codecs_will_not_open_is_released_and_the_session_lives(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting a capture runs a media library, and a library that
    cannot open a codec raises.

    Two things must then be true, and neither was. The capture is
    attached to the session's events before its codecs are built and the
    field the close path releases is assigned only after they are, so a
    failure between the two used to leave an open recording and an
    attached consumer that nothing ever closed. And the exception left
    through `run` untouched, which puts a library's own prose, and
    whatever a chained one carries, in front of whoever is reading the
    process's output.

    So the capture is released where it failed and the conversation goes
    on without a recording. That last part is a deliberate change rather
    than a restoration: a codec failure used to end the session, and
    recording is best-effort everywhere else in this module, including
    in the capture store's own decline ("a conversation is worth more
    than a recording of it").
    """
    session, websocket = capturing_session(tmp_path)
    monkeypatch.setattr(recording_module, "CaptureAudio", unopenable_codecs)

    with caplog.at_level("INFO"):
        task = asyncio.create_task(session.run())
        for _ in range(500):
            await asyncio.sleep(0.01)
            # `_start_capture` has no awaits in it, so a manifest on disk
            # means the whole of it has run: the capture opened, wrote
            # this file, and the construction after it either returned or
            # was handled.
            if manifest_of(tmp_path) is not None and session.runtime is not None:
                break
        else:
            raise AssertionError("the capture never opened")

        # Both hot paths the capture used to sit in, driven after the
        # failure: a mic frame in, and a whole reply out.
        session.listening = True
        encoder = OpusEncoder()
        for packet in encoder.encode(speech_pcm(120)):
            await session._handle_audio(framing.wrap(session.protocol_version, packet))
        await drive_reply(session, UTTERANCE)

        await websocket.close(1000, "goodbye")
        await asyncio.wait_for(task, timeout=5)

    # White-box for both reads, per the note on `attached_capture`: what
    # a released collaborator looks like is that there is nothing left to
    # ask about it.
    assert attached_capture(session) is None, "the events capture was left attached"

    manifest = manifest_of(tmp_path)
    assert manifest is not None
    # The half that says the file was closed rather than abandoned: a
    # capture stranded at the failure keeps the `False` its start wrote.
    assert manifest["capture"]["complete"] is True

    # The warning exactly, as a record: the channel it goes out on (the
    # JSON `logger` field, which a collector filters on), its level, its
    # unrendered sentence and its typed arguments, the session id and
    # nothing from the exception, neither its message nor its class.
    (warning,) = [
        record
        for record in caplog.records
        if "recording could not start" in record.getMessage()
    ]
    assert warning.name == SESSION_LOGGER
    assert warning.levelno == logging.WARNING
    assert warning.msg == "session %s: recording could not start"
    assert warning.args == (session.session_id,)

    written = both_formats(caplog)
    assert f"session {session.session_id}: recording could not start" in written
    assert CODEC_SENTINEL not in written
    assert CODEC_CLASS_SENTINEL not in written
    assert "Traceback" not in written
    printed = capsys.readouterr()
    assert CODEC_SENTINEL not in printed.out + printed.err
    assert CODEC_CLASS_SENTINEL not in printed.out + printed.err


# --- each turn's two clips, from a served session (#496) ---------------
#
# The writer's own suite proves the cut against a schedule it controls.
# These prove the wiring: that a turn's heard clip is the exact bytes
# its ASR was handed, whichever call handed them (the reply's own
# transcription, or the barge-in gate's confirmation the reply reuses),
# that a turn the gate turned away gets none, that a handover's two
# replies under one utterance are one clip, and that what a real reply
# paced out is channel 1 of the WAV between the offsets the manifest
# records.


class HeardAsr(MockAsr):
    """The mock ASR, keeping every buffer it was handed, which is the
    one place outside the pipeline where what the ear heard is visible."""

    def __init__(self) -> None:
        super().__init__(text="hello")
        self.handed: list[bytes] = []

    async def transcribe(
        self, pcm: bytes, sample_rate: int, language_hint: str | None = None
    ) -> AsrResult:
        self.handed.append(bytes(pcm))
        return await super().transcribe(pcm, sample_rate, language_hint)


class SpeaksThenHangs(LlmProvider):
    """A first reply that says one sentence and then hangs until it is
    cancelled, and every later one answering at once."""

    def __init__(self) -> None:
        self.replies = 0
        self.hanging = asyncio.Event()

    async def stream(
        self,
        system: str,
        history: Sequence[Turn],
        tools: Sequence[ToolDef] = (),
        tool_choice: ToolChoice = "auto",
    ) -> AsyncIterator[LlmEvent]:
        self.replies += 1
        if self.replies == 1:
            # The start of a second sentence is what tells the splitter
            # the first one is finished, so the first is spoken while
            # this hangs.
            yield TextDelta("Interrupted now. And")
            self.hanging.set()
            await asyncio.sleep(30)
            return
        yield TextDelta("Answered.")


async def a_served_capture(
    tmp_path: Path,
    config: Config,
    *,
    mac: str = DEVICE_MAC,
    scripts: dict[str, Any] | None = None,
    asr: Any = None,
) -> tuple[DeviceSession, LoopingSocket, asyncio.Task[None]]:
    """A session built the way `ws.py` builds one, recording into a
    capture store, with its engines substituted before it is built, its
    `run` in flight and its hello exchanged."""
    captures = CaptureStore(tmp_path / "captures", 900.0, 2000.0, 0.0)
    stages = {"asr": asr} if asr is not None else None
    generations = world(config, providers=agent_providers(config, scripts, stages))
    factory = bespoke_runtime_factory(generations, McpServers({}), lane_memory(), None)
    websocket = LoopingSocket()
    websocket.headers["device-id"] = mac
    session = DeviceSession(cast(Any, websocket), generations, factory, recordings(captures))
    task = asyncio.create_task(session.run())
    await handshaken(session, websocket)
    return session, websocket, task


async def closed(websocket: LoopingSocket, task: asyncio.Task[None]) -> None:
    await websocket.close(1000, "goodbye")
    await asyncio.wait_for(task, timeout=10)


def turn_clips(tmp_path: Path) -> tuple[Path, list[dict]]:
    """The one capture's turns directory and its manifest's turns."""
    wav, _, manifest_path = only_capture(tmp_path)
    turns = json.loads(manifest_path.read_text())["capture"]["turns"]
    return wav.with_suffix(".turns"), turns


def mono(path: Path) -> bytes:
    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == CAPTURE_RATE
        assert handle.getsampwidth() == 2
        return handle.readframes(handle.getnframes())


def reply_cut(wav: Path, turn: dict) -> bytes:
    """Channel 1 of the finished WAV between a turn's two recorded
    offsets."""
    with wave.open(str(wav), "rb") as handle:
        data = handle.readframes(handle.getnframes())
    right = bytearray(len(data) // 2)
    right[0::2] = data[2::4]
    right[1::2] = data[3::4]
    per_ms = CAPTURE_RATE // 1000
    return bytes(right)[
        int(turn["reply_from_ms"] * per_ms) * 2 : int(turn["reply_to_ms"] * per_ms) * 2
    ]


def samples_of(pcm: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(pcm) // 2}h", pcm))


async def until_speaking(session: DeviceSession, llm: SpeaksThenHangs) -> None:
    """Wait until the first reply is hanging with its sentence going out,
    and then long enough for some of it to have been paced."""
    await asyncio.wait_for(llm.hanging.wait(), 5)
    for _ in range(500):
        if session.speaking_started_at() is not None:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("the first reply never spoke")
    await asyncio.sleep(0.25)


# Two utterances a listener could tell apart, so a clip that is the
# wrong one of them is a failure rather than a coincidence.
FIRST_WORDS = speech_pcm(400)
SECOND_WORDS = bytes(reversed(speech_pcm(300)))


async def test_each_turns_heard_clip_is_what_its_asr_was_handed(tmp_path: Path) -> None:
    """Two ordinary turns: each clip's data chunk is the bytes the ear
    was handed, its length is the turn's `heard.duration_s`, and each
    reply clip is channel 1 of the WAV between its recorded offsets."""
    ears = HeardAsr()
    session, websocket, task = await a_served_capture(
        tmp_path, capturing_config(tmp_path), asr=ears
    )
    start_reply(session, FIRST_WORDS)
    await wait_for_reply(session)
    start_reply(session, SECOND_WORDS)
    await wait_for_reply(session)
    await closed(websocket, task)

    assert ears.handed == [FIRST_WORDS, SECOND_WORDS]
    turns_path, turns = turn_clips(tmp_path)
    wav, jsonl, _ = only_capture(tmp_path)
    started = [e["utterance"] for e in events(jsonl) if e["event"] == "turn_started"]
    heard = [e["duration_s"] for e in events(jsonl) if e["event"] == "heard"]
    assert [turn["utterance"] for turn in turns] == started
    for turn, handed, duration_s in zip(turns, ears.handed, heard, strict=True):
        clip = mono(turns_path / turn["heard"])
        assert clip == handed
        assert round(len(clip) / 2 / CAPTURE_RATE, 2) == duration_s
        assert turn["reply"] is not None, "a turn that answered kept no reply clip"
        reply = mono(turns_path / turn["reply"])
        assert loudest(samples_of(reply)) > 0
        assert reply_cut(wav, turn) == reply


async def test_a_confirmed_barge_in_keeps_the_gates_bytes_as_its_one_clip(
    tmp_path: Path,
) -> None:
    """The interrupting turn never transcribes: it reuses the gate's
    confirmation of its own audio. Its clip is the bytes the gate was
    handed, it is one clip, and the interrupted reply's paced frames stay
    with the turn that sent them."""
    ears = HeardAsr()
    llm = SpeaksThenHangs()
    session, websocket, task = await a_served_capture(
        tmp_path,
        capturing_config(tmp_path, barge_in_min_speech_ms=0.0),
        scripts={"assistant": llm},
        asr=ears,
    )
    start_reply(session, FIRST_WORDS)
    await until_speaking(session, llm)
    plant_utterance(session, SECOND_WORDS)
    await end_utterance(session, endpointed=True)
    await wait_for_reply(session)
    await closed(websocket, task)

    # The reply's own transcription, then the gate's; nothing a third
    # time, which is what "reuses its transcription" means.
    assert len(ears.handed) == 2
    turns_path, turns = turn_clips(tmp_path)
    wav, jsonl, _ = only_capture(tmp_path)
    started = [e for e in events(jsonl) if e["event"] == "turn_started"]
    assert [e["barge_in"] for e in started] == [False, True]
    assert [turn["utterance"] for turn in turns] == [e["utterance"] for e in started]
    interrupted, interrupting = turns
    assert mono(turns_path / interrupted["heard"]) == ears.handed[0]
    assert mono(turns_path / interrupting["heard"]) == ears.handed[1]
    heard_clips = sorted(p.name for p in turns_path.iterdir() if p.name.endswith(".heard.wav"))
    assert len(heard_clips) == 2
    for turn in turns:
        reply = mono(turns_path / turn["reply"])
        assert loudest(samples_of(reply)) > 0
        assert reply_cut(wav, turn) == reply
    assert interrupted["reply_to_ms"] <= interrupting["reply_from_ms"]


async def test_a_barge_in_the_gate_turned_away_keeps_no_clip(tmp_path: Path) -> None:
    """A candidate under the speech floor never starts a turn, so it
    leaves nothing in the turns directory."""
    ears = HeardAsr()
    llm = SpeaksThenHangs()
    session, websocket, task = await a_served_capture(
        tmp_path,
        capturing_config(tmp_path, barge_in_min_speech_ms=5000.0),
        scripts={"assistant": llm},
        asr=ears,
    )
    start_reply(session, FIRST_WORDS)
    await until_speaking(session, llm)
    plant_utterance(session, SECOND_WORDS)
    await end_utterance(session, endpointed=True)
    await closed(websocket, task)

    assert ears.handed == [FIRST_WORDS]
    turns_path, turns = turn_clips(tmp_path)
    assert len(turns) == 1
    (heard,) = [p for p in turns_path.iterdir() if p.name.endswith(".heard.wav")]
    assert mono(heard) == FIRST_WORDS


def zero_crossings(samples: list[int]) -> int:
    return sum(1 for a, b in itertools.pairwise(samples) if (a < 0) != (b < 0))


async def test_a_handover_is_one_reply_clip_with_both_voices_in_order(
    tmp_path: Path,
) -> None:
    """Two replies under one utterance (#502 M4a's 2:1 case): the clip is
    keyed by the utterance, so the poet's audio and then the tutor's are
    one clip and one manifest entry. The two mock voices are an octave
    apart, which is what tells them apart in the decoded audio."""
    poet = ScriptedLlm([["Poet speaking first.", call("switch_agent", agent="tutor")]])
    tutor = ScriptedLlm([["Tutor here now."]])
    config = base_config(
        server={"capture": {"enabled": True, "dir": str(tmp_path / "captures")}}
    )
    session, websocket, task = await a_served_capture(
        tmp_path, config, mac=BOTH_MAC, scripts={"poet": poet, "tutor": tutor}
    )
    start_reply(session, FIRST_WORDS)
    await wait_for_reply(session)
    await closed(websocket, task)

    turns_path, turns = turn_clips(tmp_path)
    _, jsonl, _ = only_capture(tmp_path)
    assert len([e for e in events(jsonl) if e["event"] == "turn_started"]) == 1
    (turn,) = turns
    samples = samples_of(mono(turns_path / turn["reply"]))
    loud = [index for index, sample in enumerate(samples) if abs(sample) > 1000]
    assert loud, "the reply clip is silent"
    tenth = CAPTURE_RATE // 10
    # A tenth of a second into the first voice and a tenth before the end
    # of the last, clear of either onset.
    first = zero_crossings(samples[loud[0] + tenth // 2 : loud[0] + tenth // 2 + tenth])
    last = zero_crossings(samples[loud[-1] - tenth // 2 - tenth : loud[-1] - tenth // 2])
    # 440 Hz crosses zero about 88 times in a tenth of a second, 880 Hz
    # about 176.
    assert first < 130 < last, (first, last)
