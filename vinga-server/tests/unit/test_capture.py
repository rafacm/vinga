"""Recording a session to disk, and what makes a recording usable.

The point of a capture is alignment: without lining up what the
microphone heard against what the speaker was playing against what the
server decided, an echo-triggered barge-in cannot be told from a genuine
one, and that distinction is the whole question in #28. So the
assertions here are mostly about time: that a sample index means the
same instant in both channels, that an event's `t_ms` indexes into the
audio, and that a gap in one channel becomes silence rather than sliding
everything after it.
"""

import json
import logging
import os
import struct
import time
import wave
from pathlib import Path

import pytest

from tests.support.events import both_formats, every_format, fields_of
from tests.support.stores import CAPTURE_MANIFEST as MANIFEST
from tests.support.stores import (
    a_capture_with_a_turn,
    capture_files,
    date,
    store,
    tone,
)
from vinga_server import capture as capture_module
from vinga_server.capture import (
    CAPTURE_RATE,
    FRAME_BYTES,
    MB,
    WAV_HEADER_BYTES,
    CaptureStore,
    DeviceFacts,
    SessionCapture,
    interleave,
)
from vinga_server.events import SessionEvents


def read_channels(path: Path) -> tuple[list[int], list[int]]:
    """The two channels, as sample lists."""
    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 2
        assert handle.getframerate() == CAPTURE_RATE
        assert handle.getsampwidth() == 2
        raw = handle.readframes(handle.getnframes())
    samples = struct.unpack(f"<{len(raw) // 2}h", raw)
    return list(samples[0::2]), list(samples[1::2])


def test_interleave_puts_the_channels_in_the_right_order() -> None:
    left = struct.pack("<hh", 1, 2)
    right = struct.pack("<hh", -1, -2)
    assert struct.unpack("<hhhh", interleave(left, right)) == (1, -1, 2, -2)


def test_interleave_refuses_channels_of_different_lengths() -> None:
    # The failure would be a file where one channel is silently shifted
    # against the other, which is the one thing a capture must not be.
    with pytest.raises(ValueError, match="same length"):
        interleave(b"\x00\x00", b"\x00\x00\x00\x00")


def test_the_microphone_and_the_reply_land_on_their_own_channels(tmp_path: Path) -> None:
    opened = time.monotonic()
    capture = store(tmp_path).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.microphone(tone(200, 1000), opened)
    capture.reply(tone(200, -1000), opened)
    capture.close()

    mic, reply = read_channels(capture.wav_path)
    assert set(mic[: CAPTURE_RATE // 10]) == {1000}
    assert set(reply[: CAPTURE_RATE // 10]) == {-1000}


def test_a_sample_index_is_the_same_instant_in_both_channels(tmp_path: Path) -> None:
    # The whole reason for stereo. The reply starts half a second after
    # the microphone does, and that offset has to survive to disk as
    # exactly half a second, because echo leakage is read off the delay
    # between the channels.
    opened = time.monotonic()
    capture = store(tmp_path).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.microphone(tone(1000, 1000), opened)
    capture.reply(tone(500, -1000), opened + 0.5)
    capture.close()

    mic, reply = read_channels(capture.wav_path)
    assert set(mic[:CAPTURE_RATE]) == {1000}
    # Silence until the half second mark, then the reply, to within a
    # sample or two of rounding.
    assert set(reply[: CAPTURE_RATE // 2 - 2]) == {0}
    assert set(reply[CAPTURE_RATE // 2 + 2 : CAPTURE_RATE - 2]) == {-1000}


def test_a_gap_becomes_silence_rather_than_sliding_the_timeline(tmp_path: Path) -> None:
    # A channel that goes quiet must not compress: if the audio after a
    # gap moved earlier, every event after it would point at the wrong
    # place, which is worse than a missing recording.
    opened = time.monotonic()
    capture = store(tmp_path).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.microphone(tone(100, 1000), opened)
    capture.microphone(tone(100, 2000), opened + 1.0)
    capture.close()

    mic, _ = read_channels(capture.wav_path)
    assert set(mic[: CAPTURE_RATE // 10]) == {1000}
    assert set(mic[CAPTURE_RATE // 5 : CAPTURE_RATE - 2]) == {0}
    assert set(mic[CAPTURE_RATE + 2 : CAPTURE_RATE + CAPTURE_RATE // 10 - 2]) == {2000}


def test_an_events_offset_indexes_into_the_audio(tmp_path: Path) -> None:
    opened = time.monotonic()
    capture = store(tmp_path).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.microphone(tone(2000, 1000), opened)
    capture.event({"event": "heard", "duration_s": 1.0}, opened + 1.25)
    capture.close()

    lines = [json.loads(line) for line in capture.jsonl_path.read_text().splitlines()]
    heard = next(line for line in lines if line["event"] == "heard")
    assert heard["t_ms"] == pytest.approx(1250, abs=1)
    # And that offset is inside the audio that was recorded.
    mic, _ = read_channels(capture.wav_path)
    assert len(mic) > int(heard["t_ms"] / 1000 * CAPTURE_RATE)


def test_the_endpointers_opinion_is_sampled_not_just_its_decisions(tmp_path: Path) -> None:
    # What turns "barge-in fired wrongly" into "the endpointer
    # classified 340 ms of the assistant's own voice as speech".
    opened = time.monotonic()
    capture = store(tmp_path).open("s1", opened, MANIFEST)
    assert capture is not None
    for i in range(5):
        capture.vad(speech_ms=i * 60, listening=True, replying=i > 2, now=opened + i * 0.06)
    capture.close()

    vad = [
        json.loads(line)
        for line in capture.jsonl_path.read_text().splitlines()
        if json.loads(line)["event"] == "vad"
    ]
    assert [record["speech_ms"] for record in vad] == [0, 60, 120, 180, 240]
    assert [record["replying"] for record in vad] == [False, False, False, True, True]


def test_dropped_frames_are_counted_per_second_with_their_reason(tmp_path: Path) -> None:
    """Per second rather than per frame: the guards drop whole seconds at
    a time, and what explains a misfire is the rate.

    Driven through the emitter, because that is where the counting
    happens since #66: the capture used to keep a counter of its own and
    write its own record, and what reaches the track now is the typed
    `frames_dropped` emission every other tap is offered. The record the
    track keeps is the same fact in the same fields, with the base an
    ordinary emission carries in front of them.
    """
    opened = 0.0
    now = [0.0]
    capture = store(tmp_path).open("s1", opened, MANIFEST)
    assert capture is not None
    emitter = SessionEvents("s1", clock=lambda: now[0])
    emitter.opened_at = opened
    emitter.attach_capture(capture)
    for index in range(10):
        now[0] = 0.1 * index
        emitter.dropped("barge_in_off")
    for index in range(3):
        now[0] = 1.1 + 0.1 * index
        emitter.dropped("not_listening")
    # The session's close path is what flushes the second a session ends
    # inside, while the capture is still attached.
    now[0] = 1.5
    emitter.flush_dropped()
    capture.close()

    dropped = [
        json.loads(line)
        for line in capture.jsonl_path.read_text().splitlines()
        if json.loads(line)["event"] == "frames_dropped"
    ]
    assert dropped[0]["second"] == 0
    assert dropped[0]["reasons"] == {"barge_in_off": 10}
    assert dropped[-1]["second"] == 1
    assert dropped[-1]["reasons"] == {"not_listening": 3}
    # The base every emission carries, which is what the track gained by
    # reading one declaration instead of writing its own record.
    assert dropped[0]["session"] == "s1"
    assert dropped[0]["device"] is None


def test_the_manifest_exists_before_the_session_ends(tmp_path: Path) -> None:
    # A pod stopped mid-session is plausibly the session most worth
    # looking at, and a capture with no manifest cannot be interpreted
    # at all.
    opened = time.monotonic()
    capture = store(tmp_path).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.microphone(tone(100), opened)

    manifest = json.loads(capture.manifest_path.read_text())
    assert manifest["barge_in"] == {"enabled": True}
    assert manifest["capture"]["complete"] is False
    assert manifest["capture"]["sample_rate"] == CAPTURE_RATE

    capture.close()
    assert json.loads(capture.manifest_path.read_text())["capture"]["complete"] is True


def test_a_capture_cut_off_mid_session_is_still_readable(tmp_path: Path) -> None:
    # The deploy strategy detaches the volume and stops the pod, so a
    # capture in progress is simply cut. The header then still claims
    # zero, and everything after the 44 bytes is raw PCM, so the audio
    # is recoverable from the file size.
    opened = time.monotonic()
    capture = store(tmp_path).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.microphone(tone(2000, 1234), opened)
    capture.microphone(tone(500, 1234), opened + 2.0)
    # The pod goes: the descriptors are gone and nothing patches the
    # header. Whatever reached the file is all there is, which is why
    # the writer flushes as it goes rather than buffering.
    # White-box for both files this capture holds: the failure under
    # test is the process going away with its descriptors, which is what
    # leaves a stale WAV header behind, and no public call closes a file
    # without also finishing the recording properly. Closing them out
    # from under the writer is the pod being killed.
    capture._wav.close()  # type: ignore[union-attr]
    capture._events.close()  # type: ignore[union-attr]

    raw = capture.wav_path.read_bytes()
    assert raw[:4] == b"RIFF"
    # The header is stale, which is what the manifest's complete: false
    # tells the analysis side to expect.
    assert struct.unpack("<I", raw[40:44])[0] == 0
    assert json.loads(capture.manifest_path.read_text())["capture"]["complete"] is False

    audio = raw[WAV_HEADER_BYTES:]
    assert len(audio) > 0
    assert len(audio) % FRAME_BYTES == 0
    samples = struct.unpack(f"<{len(audio) // 2}h", audio)
    assert set(samples[0::2]) == {1234}


def test_capture_declines_when_the_volume_is_nearly_full(tmp_path: Path) -> None:
    # Declining is the point: /data also holds agent memory and the
    # model caches, and capture must not be the thing that fills it.
    huge = store(tmp_path, min_free_mb=10_000_000.0)
    assert huge.open("s1", time.monotonic(), MANIFEST) is None


def test_the_directory_is_pruned_oldest_first_to_stay_inside_its_budget(
    tmp_path: Path,
) -> None:
    keeper = store(tmp_path, max_total_mb=0.5)
    opened = time.monotonic()
    for index in range(4):
        capture = keeper.open(f"s{index}", opened, MANIFEST)
        assert capture is not None
        # A quarter megabyte each, so the budget holds about two.
        capture.microphone(tone(4000), opened)
        capture.close()
        # Distinct mtimes, so "oldest" is well defined on a fast disk.
        for suffix in (".wav", ".jsonl", ".json"):
            path = capture.wav_path.with_suffix(suffix)
            if path.exists():
                import os

                os.utime(path, (opened + index, opened + index))

    keeper.prune()
    left = sorted(path.stem for path in keeper.directory.glob("*.wav"))
    assert left, "pruning must not empty the directory"
    assert "s0" not in left, "the oldest capture should have gone first"
    assert "s3" in left, "the newest capture should have survived"
    # All three files of a pruned capture go together.
    for stem in ("s0",):
        assert not (keeper.directory / f"{stem}.jsonl").exists()
        assert not (keeper.directory / f"{stem}.json").exists()


def test_a_capture_stops_at_its_own_time_limit(tmp_path: Path) -> None:
    opened = time.monotonic()
    capture = store(tmp_path, max_session_s=1.0).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.microphone(tone(500, 1000), opened)
    capture.microphone(tone(500, 1000), opened + 2.0)
    capture.close()

    mic, _ = read_channels(capture.wav_path)
    assert len(mic) < CAPTURE_RATE * 2, "audio past the limit was still recorded"


def test_a_write_that_fails_does_not_take_the_session_with_it(tmp_path: Path) -> None:
    opened = time.monotonic()
    capture = store(tmp_path).open("s1", opened, MANIFEST)
    assert capture is not None
    # White-box, same reason: a write that fails needs a file that
    # cannot be written to, and nothing public makes one.
    capture._wav.close()  # type: ignore[union-attr]
    # No exception: a conversation is worth more than a recording of it.
    capture.microphone(tone(100), opened)
    capture.event({"event": "heard"}, opened)
    capture.close()


def test_device_facts_survive_from_the_ota_check_to_the_session() -> None:
    facts = DeviceFacts()
    facts.record("aa:bb:cc:dd:ee:ff", "2.4.0", "waveshare")
    assert facts.get("aa:bb:cc:dd:ee:ff") == {"firmware": "2.4.0", "board": "waveshare"}
    assert facts.get("00:00:00:00:00:00") == {}
    assert facts.get(None) == {}


def test_device_facts_do_not_grow_without_bound() -> None:
    facts = DeviceFacts(limit=3)
    for index in range(5):
        facts.record(f"aa:bb:cc:dd:ee:{index:02x}", "2.4.0", "board")
    assert facts.get("aa:bb:cc:dd:ee:00") == {}
    assert facts.get("aa:bb:cc:dd:ee:04") != {}


def test_the_audio_covers_the_last_event_even_with_nothing_to_record(
    tmp_path: Path,
) -> None:
    # A review finding. An offset that points past the end of the file
    # is not an index into it, and a session can be open through
    # stretches with no decodable audio at all: a device that connects,
    # says nothing, and drops has only its own open and close events.
    opened = time.monotonic()
    capture = store(tmp_path).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.event({"event": "session_open"}, opened)
    capture.event({"event": "session_closed"}, opened + 3.0)
    capture.close()

    mic, reply = read_channels(capture.wav_path)
    assert len(mic) == len(reply)
    assert len(mic) >= 3 * CAPTURE_RATE - 2, "the audio stops before the last event"
    assert set(mic) == {0}, "silence is what a session with no audio recorded"


def test_padding_to_the_last_event_stops_at_the_session_limit(tmp_path: Path) -> None:
    opened = time.monotonic()
    capture = store(tmp_path, max_session_s=1.0).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.event({"event": "session_open"}, opened)
    capture.event({"event": "late"}, opened + 60.0)
    capture.close()

    mic, _ = read_channels(capture.wav_path)
    assert len(mic) <= CAPTURE_RATE + 2, "a stray late event stretched the file"


def test_events_stop_at_the_limit_too(tmp_path: Path) -> None:
    # A review finding. The audio is clamped to the limit on close, so
    # an event written past it would be an offset with no audio under
    # it, which is the one thing the decision track promises not to be.
    opened = time.monotonic()
    capture = store(tmp_path, max_session_s=1.0).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.event({"event": "session_open"}, opened)
    capture.event({"event": "much_later"}, opened + 3600.0)
    capture.close()

    recorded = [json.loads(line) for line in capture.jsonl_path.read_text().splitlines()]
    assert [record["event"] for record in recorded] == ["session_open"]

    mic, _ = read_channels(capture.wav_path)
    audio_ms = len(mic) / CAPTURE_RATE * 1000
    for record in recorded:
        assert record["t_ms"] <= audio_ms


def test_every_offset_indexes_into_the_audio_even_at_the_limit(tmp_path: Path) -> None:
    # A review finding, and the general form of the previous one: a
    # record stamped with the clock can land past the limit the audio
    # was clamped to. Derived from a clamped frame index now, so the
    # guarantee holds for every record by construction rather than by
    # each caller remembering. It used to be driven with a dropped-frame
    # aggregate, which the capture no longer counts (#66); what it is
    # about was never the aggregate but the clamping, so any two records
    # either side of the limit drive it.
    opened = time.monotonic()
    capture = store(tmp_path, max_session_s=0.05).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.event({"event": "early"}, opened + 0.01)
    capture.event({"event": "late"}, opened + 0.075)
    capture.close()

    mic, _ = read_channels(capture.wav_path)
    audio_ms = len(mic) / CAPTURE_RATE * 1000
    recorded = [json.loads(line) for line in capture.jsonl_path.read_text().splitlines()]
    assert recorded, "nothing was recorded at all"
    for record in recorded:
        assert record["t_ms"] <= audio_ms, (
            f"{record['event']} at {record['t_ms']} ms is past {audio_ms:.1f} ms of audio"
        )


def test_the_audio_covers_the_frame_an_event_lands_on(tmp_path: Path) -> None:
    """The off-by-one under the guarantee, pinned without a clock.

    A sample at index N only exists once N+1 frames are written, and
    `t_ms` is rounded to a tenth of a millisecond, which can round up.
    An event landing on what was the last frame therefore pointed one
    sample past the end. This drives `now` explicitly and writes no
    dropped-frame aggregate, so it does not depend on how long the test
    itself took to run, which is how the original slipped through.
    """
    # The origin is zero rather than a clock reading on purpose. Adding
    # a fraction of a millisecond to a monotonic value in the tens of
    # thousands loses the last bit, so `now - opened` comes back a
    # hair short and the frame floors one low. That wobble is harmless
    # in a 16 kHz recording and fatal to an exact assertion, and it is
    # what made the first version of this test pass or fail on what the
    # machine clock happened to read.
    opened = 0.0
    at_frame = 7
    capture = store(tmp_path).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.event({"event": "only"}, at_frame / CAPTURE_RATE)
    capture.close()

    mic, reply = read_channels(capture.wav_path)
    assert len(mic) == at_frame + 1, "the audio stops on the frame the event is at"
    assert len(mic) == len(reply)

    (record,) = [json.loads(line) for line in capture.jsonl_path.read_text().splitlines()]
    audio_ms = len(mic) / CAPTURE_RATE * 1000
    assert record["t_ms"] <= audio_ms


def test_a_capture_with_no_events_is_not_padded(tmp_path: Path) -> None:
    # The other side of it: covering the last event must not invent a
    # frame for a capture that never had one.
    opened = time.monotonic()
    capture = store(tmp_path).open("s1", opened, MANIFEST)
    assert capture is not None
    capture.close()
    mic, _ = read_channels(capture.wav_path)
    assert mic == []


def test_a_capture_still_recording_is_never_pruned(tmp_path: Path) -> None:
    # A review finding. Unlinking underneath an open descriptor leaves
    # the session writing to a file nobody can find.
    keeper = store(tmp_path, max_total_mb=0.01)
    opened = time.monotonic()
    live = keeper.open("live", opened, MANIFEST)
    assert live is not None
    # Two writes, the second past the flush lag, so there is really
    # audio on disk for a prune to find.
    live.microphone(tone(2000), opened)
    live.microphone(tone(100), opened + 3.0)
    assert live.wav_path.stat().st_size > 10_000, "nothing was flushed to prune"

    later = keeper.open("later", opened, MANIFEST)
    assert later is not None
    assert live.wav_path.exists(), "a capture still recording was pruned"
    live.close()
    later.close()


def test_the_budget_is_checked_again_when_a_capture_closes(tmp_path: Path) -> None:
    # A review finding. Checking only at open leaves a session that
    # overran sitting there until some later session happens to start.
    keeper = store(tmp_path, max_total_mb=0.2)
    opened = time.monotonic()
    for index in range(3):
        capture = keeper.open(f"s{index}", opened, MANIFEST)
        assert capture is not None
        capture.microphone(tone(3000), opened)
        capture.close()
        import os

        for suffix in (".wav", ".jsonl", ".json"):
            path = capture.wav_path.with_suffix(suffix)
            if path.exists():
                os.utime(path, (opened + index, opened + index))

    # No new session opened after the last one, and the directory is
    # still inside its budget.
    left = sorted(path.stem for path in keeper.directory.glob("*.wav"))
    assert left == ["s2"], f"the budget was not enforced on close: {left}"


def test_the_newest_capture_survives_a_budget_smaller_than_a_session(
    tmp_path: Path,
) -> None:
    # Deleting the recording somebody just went out to make, because it
    # is bigger than a misconfigured budget, is the worst thing this
    # could do.
    keeper = store(tmp_path, max_total_mb=0.001)
    opened = time.monotonic()
    capture = keeper.open("only", opened, MANIFEST)
    assert capture is not None
    capture.microphone(tone(3000), opened)
    capture.close()
    assert capture.wav_path.exists(), "the only capture was pruned away"


def test_a_capture_that_never_started_is_not_a_capture(tmp_path: Path) -> None:
    # SessionCapture is inert until start(), so a failure to open leaves
    # no half-written files behind.
    capture = SessionCapture(tmp_path, "s1", time.monotonic(), MANIFEST, 900.0)
    capture.microphone(tone(100), time.monotonic())
    capture.close()
    assert not capture.wav_path.exists()


# --- each turn's two clips (#496) --------------------------------------
#
# Beside the session's three files, a capture keeps two mono clips per
# turn in `<session>.turns/`: what the turn's ASR was handed, and what
# was paced out while the turn was being answered. The first arrives in
# one piece through `utterance_audio`; the second is cut from channel 1
# as it is placed, so the claims below are all about that cut agreeing
# with the channel, frame for frame, over a span the test works out for
# itself from what it paced rather than reading back off the capture.
#
# The clock is driven by hand and every instant is an exact binary
# fraction of a second, so a frame index is an exact product and the
# expected spans are arithmetic rather than tolerances.


def wav_parts(path: Path) -> tuple[int, int, int, bytes]:
    """A WAV's channel count, rate, sample width and data, read through
    its header, so a header that was never patched reads as no data."""
    with wave.open(str(path), "rb") as handle:
        return (
            handle.getnchannels(),
            handle.getframerate(),
            handle.getsampwidth(),
            handle.readframes(handle.getnframes()),
        )


def reply_channel(path: Path) -> bytes:
    """Channel 1 of the finished session WAV, as mono s16le bytes."""
    channels, _, _, data = wav_parts(path)
    assert channels == 2
    right = bytearray(len(data) // 2)
    right[0::2] = data[2::4]
    right[1::2] = data[3::4]
    return bytes(right)


def cut(channel: bytes, from_ms: float, to_ms: float) -> bytes:
    """The span of a mono channel between two offsets on the `t_ms`
    timeline, which is what anyone holding the three files would do
    with a manifest entry."""
    per_ms = CAPTURE_RATE // 1000
    return channel[int(from_ms * per_ms) * 2 : int(to_ms * per_ms) * 2]


def silence(frames: int) -> bytes:
    return bytes(frames * 2)


def turns_of(capture: SessionCapture) -> list[dict]:
    return json.loads(capture.manifest_path.read_text())["capture"]["turns"]


def clip_names(capture: SessionCapture) -> list[str]:
    if not capture.turns_path.exists():
        return []
    return sorted(path.name for path in capture.turns_path.iterdir())


def a_turn_recorder(
    tmp_path: Path, **options: float
) -> tuple[SessionCapture, SessionEvents, list[float]]:
    """A capture attached to a session's events the way a served session
    attaches one, on a clock the test moves."""
    now = [0.0]
    capture = store(tmp_path, **options).open("s1", 0.0, MANIFEST)
    assert capture is not None
    emitter = SessionEvents("s1", clock=lambda: now[0])
    emitter.opened_at = 0.0
    emitter.attach_capture(capture)
    return capture, emitter, now


def frame(seconds: float) -> int:
    return int(seconds * CAPTURE_RATE)


def expected_clips(schedule: list[tuple[str, float, object]]) -> dict[str, tuple[int, int, bytes]]:
    """What each turn's reply clip should be, worked out from the
    schedule alone: a turn's window opens when it starts and closes when
    the next one does, and each reply chunk is placed at its own instant
    or just past the chunk before it, whichever is later, with silence in
    any gap. Chunks paced while no window is open belong to no clip.

    Answers `{utterance: (from_frame, to_frame, bytes)}`."""
    clips: dict[str, tuple[int, int, bytes]] = {}
    window: str | None = None
    channel_end = 0
    for kind, at, what in schedule:
        if kind == "turn":
            window = str(what)
            continue
        pcm = bytes(what)  # type: ignore[arg-type]
        placed = max(frame(at), channel_end)
        channel_end = placed + len(pcm) // 2
        if window is None:
            continue
        if window not in clips:
            clips[window] = (placed, placed, b"")
        start, end, data = clips[window]
        clips[window] = (start, channel_end, data + silence(placed - end) + pcm)
    return clips


def play(
    capture: SessionCapture,
    emitter: SessionEvents,
    now: list[float],
    schedule: list[tuple[str, float, object]],
) -> None:
    for kind, at, what in schedule:
        now[0] = at
        if kind == "turn":
            emitter.utterance_audio(str(what), tone(20, 7))
        else:
            capture.reply(bytes(what), at)  # type: ignore[arg-type]


def test_a_reply_clip_is_channel_one_over_the_span_its_turn_paced(tmp_path: Path) -> None:
    """The reply clip is a cut of channel 1, and the cut is checked
    against a span this test derived from what it paced.

    The schedule carries every shape the plan names: audio before any
    turn (no clip), a chunk arriving before the one ahead of it has
    finished (placed after it, as the channel places it), a gap inside
    a reply (silence), and a barge-in: `u2`'s utterance ended at 1.0625 s, which
    is the instant its `turn_started` is stamped with, while the reply
    it interrupted was still being paced until 1.185 s. Those last
    frames are `u1`'s, and a cut between consecutive `turn_started`
    stamps would have handed them to `u2`. `u3` begins while `u2`'s
    last chunk is still playing, so each clip is bounded by where the
    channel placed the audio, not by when it arrived. The last turn's
    reply is still open at close, so the close is what finishes its
    file.
    """
    capture, emitter, now = a_turn_recorder(tmp_path)
    schedule: list[tuple[str, float, object]] = [
        ("reply", 0.125, tone(100, 111)),
        ("turn", 0.5, "u1"),
        ("reply", 0.625, tone(200, 1000)),
        # Arriving before the chunk ahead of it has finished, the way a
        # paced batch does when it lands a little early: the channel
        # places it after that chunk, and so must the clip.
        ("reply", 0.6875, tone(40, 1003)),
        ("reply", 1.0, tone(100, 1001)),
        ("reply", 1.125, tone(60, 1002)),
        ("turn", 1.25, "u2"),
        # Placed from 1.375 s to 1.775 s, so it is still playing when
        # `u3` begins at 1.75 s, and `u3`'s first chunk arrives before
        # it ends: the channel places that chunk after it, and the clip
        # has to start where the channel put it rather than where the
        # chunk arrived.
        ("reply", 1.375, tone(400, 2000)),
        ("turn", 1.75, "u3"),
        ("reply", 1.765625, tone(50, 3000)),
    ]
    play(capture, emitter, now, schedule)
    capture.close()

    expected = expected_clips(schedule)
    assert sorted(expected) == ["u1", "u2", "u3"]
    channel = reply_channel(capture.wav_path)
    turns = turns_of(capture)
    assert [turn["utterance"] for turn in turns] == ["u1", "u2", "u3"]
    for turn in turns:
        start, end, data = expected[turn["utterance"]]
        assert turn["reply"] == f"{turn['utterance']}.reply.wav"
        # The recorded offsets are the derived span, exactly.
        assert turn["reply_from_ms"] == start * 1000 / CAPTURE_RATE
        assert turn["reply_to_ms"] == end * 1000 / CAPTURE_RATE
        channels, rate, width, clip = wav_parts(capture.turns_path / turn["reply"])
        assert (channels, rate, width) == (1, CAPTURE_RATE, 2)
        # The clip is what was paced in that span, silence and all ...
        assert clip == data
        # ... and it IS channel 1 of the finished WAV between the two
        # offsets the manifest records, which is the check anyone
        # holding the three files can make without trusting the clip.
        assert cut(channel, turn["reply_from_ms"], turn["reply_to_ms"]) == clip

    # The interrupted reply's last frames are the interrupted turn's.
    u1 = wav_parts(capture.turns_path / "u1.reply.wav")[3]
    assert u1.endswith(tone(60, 1002))
    assert struct.pack("<h", 1002) not in wav_parts(capture.turns_path / "u2.reply.wav")[3]
    # And the audio paced before any turn is in no clip.
    for name in ("u1", "u2", "u3"):
        samples = set(struct.unpack_from("<h", tone(1, 111)))
        clip = wav_parts(capture.turns_path / f"{name}.reply.wav")[3]
        assert not samples & set(struct.unpack(f"<{len(clip) // 2}h", clip))


def test_the_window_closes_at_the_capture_limit(tmp_path: Path) -> None:
    """A reply that runs past the limit is cut where the WAV is cut, and
    a turn that starts past it is the capture ending, not a clip."""
    capture, emitter, now = a_turn_recorder(tmp_path, max_session_s=2.0)
    now[0] = 0.5
    emitter.utterance_audio("u1", tone(20, 7))
    # 250 ms placed from 1.875 s runs 125 ms past the two second limit.
    capture.reply(tone(250, 500), 1.875)
    now[0] = 2.5
    emitter.utterance_audio("u2", tone(20, 8))
    capture.close()

    (turn,) = turns_of(capture)
    assert turn["utterance"] == "u1"
    assert turn["reply_from_ms"] == 1875.0
    assert turn["reply_to_ms"] == 2000.0
    clip = wav_parts(capture.turns_path / "u1.reply.wav")[3]
    assert clip == tone(125, 500)
    channel = reply_channel(capture.wav_path)
    assert len(channel) == frame(2.0) * 2, "the WAV is cut at the limit"
    assert cut(channel, turn["reply_from_ms"], turn["reply_to_ms"]) == clip
    assert clip_names(capture) == ["u1.heard.wav", "u1.reply.wav"]


def test_the_manifest_lists_every_turn_in_start_order(tmp_path: Path) -> None:
    """One entry per turn, in the order the turns started, and a turn
    that spoke nothing says so with nulls rather than being left out.
    The manifest written at open says nothing about turns."""
    capture, emitter, now = a_turn_recorder(tmp_path)
    assert "turns" not in json.loads(capture.manifest_path.read_text())["capture"]
    now[0] = 0.25
    emitter.utterance_audio("u1", tone(20, 7))
    now[0] = 0.5
    emitter.utterance_audio("u2", tone(20, 7))
    capture.reply(tone(100, 900), 0.625)
    now[0] = 1.0
    emitter.utterance_audio("u3", tone(20, 7))
    capture.close()

    assert turns_of(capture) == [
        {
            "utterance": "u1",
            "heard": "u1.heard.wav",
            "reply": None,
            "reply_from_ms": None,
            "reply_to_ms": None,
        },
        {
            "utterance": "u2",
            "heard": "u2.heard.wav",
            "reply": "u2.reply.wav",
            "reply_from_ms": 625.0,
            "reply_to_ms": 725.0,
        },
        {
            "utterance": "u3",
            "heard": "u3.heard.wav",
            "reply": None,
            "reply_from_ms": None,
            "reply_to_ms": None,
        },
    ]
    assert clip_names(capture) == [
        "u1.heard.wav",
        "u2.heard.wav",
        "u2.reply.wav",
        "u3.heard.wav",
    ]


def test_the_heard_clip_is_the_bytes_it_was_handed(tmp_path: Path) -> None:
    """Mono, 16 kHz, 16 bit, and its data chunk byte for byte what came
    across, with a header that says how long it is."""
    capture, emitter, now = a_turn_recorder(tmp_path)
    pcm = bytes(range(256)) * 25
    now[0] = 0.5
    emitter.utterance_audio("u1", pcm)
    capture.close()

    raw = (capture.turns_path / "u1.heard.wav").read_bytes()
    assert len(raw) == WAV_HEADER_BYTES + len(pcm)
    assert raw[WAV_HEADER_BYTES:] == pcm
    assert wav_parts(capture.turns_path / "u1.heard.wav") == (1, CAPTURE_RATE, 2, pcm)


UNMINTED = "../../outside-0TURNCLIP-SENTINEL"


def test_an_utterance_id_this_server_did_not_mint_writes_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The id becomes a file name, so a separator or a traversal must not
    reach the filesystem. Refused under the uploader's own name rule, said
    once without the value, and the window of the turn before it still
    closes: reply audio after it belongs to no clip."""
    capture, emitter, now = a_turn_recorder(tmp_path)
    now[0] = 0.5
    emitter.utterance_audio("u1", tone(20, 7))
    capture.reply(tone(100, 900), 0.625)
    with caplog.at_level(logging.WARNING):
        now[0] = 1.0
        emitter.utterance_audio(UNMINTED, tone(20, 7))
    capture.reply(tone(100, 901), 1.125)
    capture.close()

    assert [turn["utterance"] for turn in turns_of(capture)] == ["u1"]
    assert clip_names(capture) == ["u1.heard.wav", "u1.reply.wav"]
    assert wav_parts(capture.turns_path / "u1.reply.wav")[3] == tone(100, 900)
    written = sorted(
        str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*") if path.is_file()
    )
    assert written == [
        "captures/s1.json",
        "captures/s1.jsonl",
        "captures/s1.turns/u1.heard.wav",
        "captures/s1.turns/u1.reply.wav",
        "captures/s1.wav",
    ]
    (refused,) = [
        record
        for record in caplog.records
        if record.name == "vinga_server.capture" and record.levelno >= logging.WARNING
    ]
    assert refused.levelno == logging.WARNING
    assert refused.msg == (
        "session %s: an utterance id this server did not mint reached the "
        "capture, so no clip was kept for it"
    )
    assert refused.args == ("s1",)
    assert "SENTINEL" not in both_formats(caplog)


def test_a_capture_stopped_by_a_write_failure_writes_no_more_clips(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A clip write that fails disables the capture the way any capture
    write failure does, and nothing is written for a turn after it."""
    capture, emitter, now = a_turn_recorder(tmp_path)
    # Where the clips go is taken by a file, so the first clip cannot be
    # written.
    capture.turns_path.write_bytes(b"in the way")
    with caplog.at_level(logging.WARNING):
        now[0] = 0.5
        emitter.utterance_audio("u1", tone(20, 7))
    now[0] = 1.0
    emitter.utterance_audio("u2", tone(20, 7))
    capture.close()

    (failed,) = [r for r in caplog.records if getattr(r, "event", None) == "capture_failed"]
    assert fields_of(failed)["reason"] == "write audio"
    manifest = json.loads(capture.manifest_path.read_text())
    assert manifest["capture"]["complete"] is False
    assert manifest["capture"]["turns"] == []
    assert capture.turns_path.read_bytes() == b"in the way"


# Shaped like a credential, and planted on both halves of a failure a
# capture might be tempted to render: the message, and the class name,
# which `type` accepts as any identifier at all.
HEADER_SENTINEL = "sk_live_0REPLYHEADER_SENTINEL"
HeaderUnwritable: type[OSError] = type(HEADER_SENTINEL, (OSError,), {})


def test_a_reply_clip_that_cannot_be_finished_marks_the_capture_incomplete(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing a reply window patches the clip's header, and that write
    can fail like any other. It is a capture write failure: said once,
    as `capture_failed` naming nothing the failure carried, and the
    capture closes the rest of the way with a manifest that says it is
    not complete, rather than listing a clip with a stale header under
    `complete: true`."""
    capture, emitter, now = a_turn_recorder(tmp_path)
    now[0] = 0.5
    emitter.utterance_audio("u1", tone(20, 7))
    capture.reply(tone(100, 900), 0.625)
    header = capture_module._wav_header

    def unwritable(data_bytes: int, channels: int) -> bytes:
        # White-box, deliberately: a disk that fails on exactly the
        # header patch is the failure under test, and nothing public
        # makes one. The session WAV's own header is left alone, so what
        # fails is the clip's and nothing else.
        if channels == 1:
            raise HeaderUnwritable(f"no space left writing {HEADER_SENTINEL}")
        return header(data_bytes, channels)

    monkeypatch.setattr(capture_module, "_wav_header", unwritable)
    with caplog.at_level(logging.DEBUG):
        capture.close()

    failed = [r for r in caplog.records if getattr(r, "event", None) == "capture_failed"]
    assert len(failed) == 1, "the failure was not said, or said more than once"
    assert fields_of(failed[0])["reason"] == "write audio"
    # The nearest class Python itself defines, never the one raised.
    assert fields_of(failed[0])["failure"] == "OSError"
    manifest = json.loads(capture.manifest_path.read_text())
    assert manifest["capture"]["complete"] is False
    # The close went the rest of the way: the WAV is finished and the
    # turn is listed, for a reader the manifest has told to trust the
    # files over it.
    assert [turn["utterance"] for turn in manifest["capture"]["turns"]] == ["u1"]
    assert wav_parts(capture.wav_path)[0] == 2
    rendered = both_formats(caplog) + every_format(caplog)
    assert HEADER_SENTINEL not in rendered
    assert "no space left" not in rendered
    assert "Traceback" not in rendered


def test_a_capture_already_stopped_says_its_failure_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reply clip whose first write fails stops the capture, and the
    close that follows cannot finish that clip either. That is one
    failure of one capture, and it is said once."""
    capture, emitter, now = a_turn_recorder(tmp_path)
    now[0] = 0.5
    emitter.utterance_audio("u1", tone(20, 7))
    header = capture_module._wav_header

    def unwritable(data_bytes: int, channels: int) -> bytes:
        # White-box, for the reason the case above gives.
        if channels == 1:
            raise HeaderUnwritable(f"no space left writing {HEADER_SENTINEL}")
        return header(data_bytes, channels)

    monkeypatch.setattr(capture_module, "_wav_header", unwritable)
    with caplog.at_level(logging.DEBUG):
        capture.reply(tone(100, 900), 0.625)
        capture.close()

    failed = [r for r in caplog.records if getattr(r, "event", None) == "capture_failed"]
    assert len(failed) == 1
    assert json.loads(capture.manifest_path.read_text())["capture"]["complete"] is False
    assert HEADER_SENTINEL not in both_formats(caplog) + every_format(caplog)


def test_no_capture_attached_keeps_no_clip(tmp_path: Path) -> None:
    """The session that is not recording pays one `is None` and writes
    nothing anywhere."""
    emitter = SessionEvents("s1", clock=lambda: 0.5)
    emitter.utterance_audio("u1", tone(20, 7))
    assert list(tmp_path.iterdir()) == []


def test_a_pruned_capture_takes_its_turns_with_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Five parts go together now. And a `.wav` planted inside a turns
    directory is not a capture of its own: were it one, it would be the
    newest and the one protected, and the real newest would be pruned."""
    keeper = store(tmp_path, max_total_mb=1_000.0)
    opened = time.time()
    captures = []
    for index in range(4):
        captures.append(a_capture_with_a_turn(keeper, f"s{index}"))
        date(captures[-1], opened + index)
    planted = captures[3].turns_path / "zzz.wav"
    planted.write_bytes(bytes(1000))
    os.utime(planted, (opened + 10, opened + 10))

    # Tight enough that only about one capture fits.
    cheap = CaptureStore(keeper.directory, 900.0, 0.15, 0.0)
    with caplog.at_level(logging.INFO):
        cheap.prune()

    pruned = [
        tuple(fields_of(record)["sessions"])  # type: ignore[arg-type]
        for record in caplog.records
        if getattr(record, "event", None) == "capture_pruned"
    ]
    assert pruned and "zzz" not in pruned[0]
    assert "s0" in pruned[0]
    assert not captures[0].turns_path.exists(), "a pruned capture left its clips behind"
    assert captures[3].wav_path.exists(), "the newest capture was pruned"
    assert planted.exists()


def test_the_budget_counts_the_clips(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """The total the budget is checked against is every file the
    capture wrote, its clips included, and it is the number the warning
    reports."""
    keeper = store(tmp_path, max_total_mb=0.001)
    with caplog.at_level(logging.WARNING):
        capture = a_capture_with_a_turn(keeper, "s1")

    expected = sum(path.stat().st_size for path in capture_files(capture))
    (over,) = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "capture_over_budget"
    ]
    assert over.args[0] == expected / MB  # type: ignore[index]
