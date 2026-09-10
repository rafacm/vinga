"""The wire latency script's contract, exercised as a subprocess.

The script lives at the repository root (`scripts/wire_latency.py`) and
is run by hand over a field capture, which is a recording of somebody's
room: its output discipline is the server's no-leak standard, so these
tests run the real script the way an operator does and read both
streams whole, the way the link checker's suite from #329 does.

Every capture here is synthetic and built under `tmp_path`: a tone
where audio should be, digital silence where it should not, and a
decision track written line by line. That is what makes the arithmetic
testable at all, since a real capture's timings are wall-clock. The one
test over a capture the server itself produced is the integration
lane's (`tests/integration/test_wire_latency_capture.py`), and it
proves the format rather than the numbers.
"""

import json
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "wire_latency.py"

RATE = 16000
FRAME_MS = 20

# Credential-shaped, and never a value that exists anywhere real. The
# link checker's suite and the drift watch's suite plant the same kind
# of thing for the same reason: a tool that answers a bad input by
# quoting it would republish this wherever its output lands.
SENTINEL = "sk-SENTINEL8f3a1b2c4d5e6f70"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _samples(spans: list[tuple[int, int]], total_ms: int) -> list[int]:
    """A mono channel: a 300 Hz tone inside every span, digital silence
    everywhere else."""
    out = [0] * (RATE * total_ms // 1000)
    for start_ms, end_ms in spans:
        for n in range(RATE * start_ms // 1000, RATE * end_ms // 1000):
            out[n] = int(8000 * math.sin(2 * math.pi * 300 * n / RATE))
    return out


def write_capture(
    directory: Path,
    name: str,
    *,
    mic: list[tuple[int, int]],
    reply: list[tuple[int, int]],
    events: list[dict],
    total_ms: int,
    complete: bool = True,
    frames: int | None = None,
) -> Path:
    """One capture triplet, in the format `capture.py` writes."""
    directory.mkdir(parents=True, exist_ok=True)
    left = _samples(mic, total_ms)
    right = _samples(reply, total_ms)
    with wave.open(str(directory / f"{name}.wav"), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(RATE)
        keep = len(left) if frames is None else frames
        out.writeframes(
            b"".join(
                struct.pack("<hh", left[n], right[n]) for n in range(min(keep, len(left)))
            )
        )
    (directory / f"{name}.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    (directory / f"{name}.json").write_text(
        json.dumps(
            {
                "session": name,
                "capture": {
                    "audio": f"{name}.wav",
                    "events": f"{name}.jsonl",
                    "sample_rate": RATE,
                    "channels": ["microphone", "reply"],
                    "complete": complete,
                },
            }
        ),
        encoding="utf-8",
    )
    return directory


def speech(
    start_ms: int, end_ms: int, listening: bool = True, resets: bool = True
) -> list[dict]:
    """The endpointer counting speech through an utterance, then saying
    it has stopped: `speech_ms` back to zero while still listening,
    which is the fall this script pairs the energy with.

    `resets=False` is the other shape the live producer emits, and the
    commoner one: the endpointer that ends an utterance is reset in the
    same breath, so where the user speaks again straight away the next
    sample is already counting the new speech and no zero is ever
    written.
    """
    track = [
        {
            "event": "vad",
            "t_ms": float(at),
            "speech_ms": float(at - start_ms + FRAME_MS),
            "listening": listening,
            "replying": False,
        }
        for at in range(start_ms, end_ms, FRAME_MS)
    ]
    if resets:
        track.append(
            {
                "event": "vad",
                "t_ms": float(end_ms + FRAME_MS),
                "speech_ms": 0.0,
                "listening": listening,
                "replying": False,
            }
        )
    return track


def heard(at_ms: int, duration_s: float = 1.0) -> dict:
    return {"event": "heard", "t_ms": float(at_ms), "duration_s": duration_s, "asr_ms": 5}


def one_turn(tmp_path: Path) -> Path:
    """The ordinary case: 800 ms of speech, a transcript, and reply
    audio 600 ms after the speech ends."""
    return write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 1000)],
        reply=[(1600, 2200)],
        events=[*speech(200, 1000), heard(1100, 0.8)],
        total_ms=3000,
    )


def quiet_about(done: subprocess.CompletedProcess, *forbidden: str) -> None:
    """Both streams, checked together.

    Always both. A refusal is written to stderr and a report to stdout,
    and which one a leak would land on is a property of the bug rather
    than of the case: a case that checks only the stream it expects the
    failure on cannot see content republished on the other, which is
    what review found here.
    """
    for stream in (done.stdout, done.stderr):
        assert "Traceback" not in stream
        for value in forbidden:
            assert value not in stream


def turn_lines(stdout: str) -> list[str]:
    return [line.strip() for line in stdout.splitlines() if line.strip().startswith("turn ")]


def test_a_turn_is_measured_from_the_speech_fall_to_the_reply_onset(tmp_path: Path) -> None:
    done = run(str(one_turn(tmp_path)))
    assert done.returncode == 0
    assert done.stderr == ""
    assert turn_lines(done.stdout) == [
        "turn 1: speech ended at 1.0 s, reply audio began at 1.6 s, "
        "wire response latency 0.6 s"
    ]
    assert "capture 1: 1 turn(s), 1 measured" in done.stdout
    assert "1 capture(s), 1 turn(s), 1 measured." in done.stdout


def test_the_run_states_its_precision_and_what_it_excludes(tmp_path: Path) -> None:
    done = run(str(one_turn(tmp_path)))
    assert done.returncode == 0
    # The standing precision sentence: the number answers 800 ms or
    # 2.5 s, and says so itself rather than in a document beside it.
    assert "800 ms or 2.5 s, never a count of milliseconds" in done.stdout
    assert "tenth of a second" in done.stdout
    # And the exclusion, which is why this is never called perceived
    # latency.
    assert "excludes downlink transport and device playback" in done.stdout
    assert "wire path only" in done.stdout
    assert "perceived" not in done.stdout


def test_the_endpointer_hangover_lands_inside_the_measured_interval(tmp_path: Path) -> None:
    """The energy fall, not the endpointer's decision, is the speech
    end: the endpointer only decides after its own trailing silence, and
    that silence is part of what the user waited through."""
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 1000)],
        # The endpointer keeps counting for 400 ms after the mic falls.
        reply=[(2000, 2600)],
        events=[*speech(200, 1400), heard(1500, 1.2)],
        total_ms=3000,
    )
    done = run(str(captures))
    assert done.returncode == 0
    assert turn_lines(done.stdout) == [
        "turn 1: speech ended at 1.0 s, reply audio began at 2.0 s, "
        "wire response latency 1.0 s"
    ]


def test_two_turns_each_pair_with_their_own_reply(tmp_path: Path) -> None:
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 1000), (4000, 4600)],
        reply=[(1600, 2200), (5000, 5600)],
        events=[
            *speech(200, 1000),
            heard(1100, 0.8),
            *speech(4000, 4600),
            heard(4700, 0.6),
        ],
        total_ms=7000,
    )
    done = run(str(captures))
    assert done.returncode == 0
    assert turn_lines(done.stdout) == [
        "turn 1: speech ended at 1.0 s, reply audio began at 1.6 s, "
        "wire response latency 0.6 s",
        "turn 2: speech ended at 4.6 s, reply audio began at 5.0 s, "
        "wire response latency 0.4 s",
    ]
    assert "capture 1: 2 turn(s), 2 measured" in done.stdout


def test_two_turns_a_fraction_of_a_second_apart_stay_two_turns(tmp_path: Path) -> None:
    """The shape the live producer actually emits: the endpointer is
    reset the moment it ends an utterance, so the user answering a short
    reply straight away gives two positive samples 200 ms apart with no
    zero between them. What says they are two utterances is the
    transcript that landed in the gap."""
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 1000), (1200, 1800)],
        reply=[(1100, 1180), (2000, 2600)],
        events=[
            *speech(200, 1000, resets=False),
            heard(1060, 0.8),
            *speech(1200, 1800, resets=False),
            heard(1860, 0.6),
        ],
        total_ms=3000,
    )
    done = run(str(captures))
    assert done.returncode == 0
    assert turn_lines(done.stdout) == [
        "turn 1: speech ended at 1.0 s, reply audio began at 1.1 s, "
        "wire response latency 0.1 s",
        "turn 2: speech ended at 1.8 s, reply audio began at 2.0 s, "
        "wire response latency 0.2 s",
    ]


def test_a_long_answer_filling_the_recording_is_still_found(tmp_path: Path) -> None:
    """A reply occupying most of the capture. Read from the whole
    channel, its own level is the twentieth percentile and the threshold
    lands above it, so the recording of one long answer reports no reply
    audio at all. The floor comes from the stretch before the user
    spoke instead, which nothing can be playing in."""
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 400)],
        # 2500 ms of the 3000 ms recording.
        reply=[(500, 3000)],
        events=[*speech(200, 400), heard(460, 0.2)],
        total_ms=3000,
    )
    done = run(str(captures))
    assert done.returncode == 0
    assert turn_lines(done.stdout) == [
        "turn 1: speech ended at 0.4 s, reply audio began at 0.5 s, "
        "wire response latency 0.1 s"
    ]


def test_a_turn_with_no_reply_audio_says_so_rather_than_guessing(tmp_path: Path) -> None:
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 1000)],
        reply=[],
        events=[*speech(200, 1000), heard(1100, 0.8)],
        total_ms=3000,
    )
    done = run(str(captures))
    assert done.returncode == 0
    assert turn_lines(done.stdout) == [
        "turn 1: speech ended at 1.0 s, no number (no_reply_audio)"
    ]
    assert "0 measured" in done.stdout


def test_an_utterance_transcribed_to_nothing_is_not_a_latency_failure(
    tmp_path: Path,
) -> None:
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 1000)],
        reply=[],
        events=[
            *speech(200, 1000),
            {"event": "nothing_heard", "t_ms": 1100.0, "duration_s": 0.8},
        ],
        total_ms=3000,
    )
    done = run(str(captures))
    assert done.returncode == 0
    assert turn_lines(done.stdout) == ["turn 1: no number (nothing_transcribed)"]


def test_an_utterance_with_no_transcription_event_cannot_be_paired(tmp_path: Path) -> None:
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 1000)],
        reply=[(1600, 2200)],
        events=list(speech(200, 1000)),
        total_ms=3000,
    )
    done = run(str(captures))
    assert done.returncode == 0
    assert turn_lines(done.stdout) == ["turn 1: no number (no_transcription_event)"]


def test_an_endpointer_opinion_with_no_audio_under_it_measures_nothing(
    tmp_path: Path,
) -> None:
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[],
        reply=[(1600, 2200)],
        events=[*speech(200, 1000), heard(1100, 0.8)],
        total_ms=3000,
    )
    done = run(str(captures))
    assert done.returncode == 0
    assert turn_lines(done.stdout) == ["turn 1: no number (no_speech_energy)"]


def test_a_speech_end_outside_what_the_transcript_bounds_is_refused(
    tmp_path: Path,
) -> None:
    """`heard` stamps transcription completion, so it bounds the speech
    it describes. A pairing that puts the speech end outside that window
    is wrong, and a wrong number is worse than none."""
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 1000)],
        reply=[(1600, 2200)],
        events=[*speech(200, 1000), heard(5000, 0.8)],
        total_ms=6000,
    )
    done = run(str(captures))
    assert done.returncode == 0
    assert turn_lines(done.stdout) == ["turn 1: no number (outside_heard_bound)"]


def test_a_barge_in_over_a_playing_reply_has_no_onset_of_its_own(tmp_path: Path) -> None:
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(600, 1000)],
        # Playing before the speech ends and still playing after it: the
        # next rise on this channel is not this turn's answer.
        reply=[(200, 2200)],
        events=[*speech(600, 1000), heard(1100, 0.4)],
        total_ms=3000,
    )
    done = run(str(captures))
    assert done.returncode == 0
    assert turn_lines(done.stdout) == [
        "turn 1: speech ended at 1.0 s, no number (reply_already_playing)"
    ]


def test_filler_audio_is_named_rather_than_measured_as_the_reply(tmp_path: Path) -> None:
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 1000)],
        reply=[(1400, 2200)],
        events=[
            *speech(200, 1000),
            heard(1100, 0.8),
            {"event": "filler_played", "t_ms": 1400.0, "clip": 1},
        ],
        total_ms=3000,
    )
    done = run(str(captures))
    assert done.returncode == 0
    assert turn_lines(done.stdout) == [
        "turn 1: speech ended at 1.0 s, no number (filler_audio_first)"
    ]


def test_every_reason_printed_comes_from_the_closed_set() -> None:
    """The reasons are literals in the script and nothing builds one
    from what it read, which is what keeps a reason token from becoming
    a channel for capture content."""
    source = SCRIPT.read_text(encoding="utf-8")
    listed = source.split("REASONS = (")[1].split(")")[0]
    names = [line.strip().rstrip(",") for line in listed.strip().splitlines()]
    assert names == [
        "NOTHING_TRANSCRIBED",
        "NO_TRANSCRIPTION_EVENT",
        "NO_SPEECH_ENERGY",
        "OUTSIDE_HEARD_BOUND",
        "REPLY_ALREADY_PLAYING",
        "FILLER_AUDIO_FIRST",
        "NO_REPLY_AUDIO",
    ]
    for name in names:
        assert f'{name} = "' in source


def test_a_bad_invocation_is_a_sentence_and_exit_two(tmp_path: Path) -> None:
    a_file = tmp_path / "not-a-directory"
    a_file.write_text("", encoding="utf-8")
    for done in (
        run(),
        run(str(tmp_path / "nowhere"), "extra"),
        run(str(tmp_path / "nowhere")),
        run(str(a_file)),
    ):
        assert done.returncode == 2
        assert done.stdout == ""
        assert len(done.stderr.strip().splitlines()) <= 2
        quiet_about(done)


def test_a_bad_invocation_never_repeats_what_was_typed(tmp_path: Path) -> None:
    hostile = tmp_path / SENTINEL
    for done in (run(str(hostile)), run(str(hostile), f"--{SENTINEL}")):
        assert done.returncode == 2
        quiet_about(done, SENTINEL)


def test_a_directory_with_no_capture_in_it_is_exit_one(tmp_path: Path) -> None:
    (tmp_path / "captures").mkdir()
    done = run(str(tmp_path / "captures"))
    assert done.returncode == 1
    assert done.stdout == ""
    assert done.stderr.strip() == "no capture was found in the given directory"
    quiet_about(done)


def test_a_capture_missing_a_file_is_refused_without_naming_it(tmp_path: Path) -> None:
    captures = one_turn(tmp_path)
    (captures / f"{SENTINEL}.wav").write_bytes((captures / "session-a.wav").read_bytes())
    done = run(str(captures))
    assert done.returncode == 1
    quiet_about(done, SENTINEL, "session-a")
    assert "could not be read" in done.stderr
    # The capture beside it still reports: one unreadable recording is
    # not a reason to say nothing about the others.
    assert "wire response latency" in done.stdout


def test_an_unfinished_capture_is_refused_rather_than_measured(tmp_path: Path) -> None:
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 1000)],
        reply=[(1600, 2200)],
        events=[*speech(200, 1000), heard(1100, 0.8)],
        total_ms=3000,
        complete=False,
    )
    done = run(str(captures))
    assert done.returncode == 1
    assert "was never finished" in done.stderr
    assert done.stdout.startswith("\n0 capture(s)")
    quiet_about(done, "session-a")


def test_an_empty_recording_has_no_timeline_to_measure_on(tmp_path: Path) -> None:
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 1000)],
        reply=[(1600, 2200)],
        events=[*speech(200, 1000), heard(1100, 0.8)],
        total_ms=3000,
        frames=0,
    )
    done = run(str(captures))
    assert done.returncode == 1
    assert "no audio" in done.stderr
    quiet_about(done, "session-a")


def test_a_recording_in_another_format_is_refused(tmp_path: Path) -> None:
    captures = one_turn(tmp_path)
    with wave.open(str(captures / "session-a.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(struct.pack("<h", 0) * 1000)
    done = run(str(captures))
    assert done.returncode == 1
    assert "not a stereo 16 kHz recording" in done.stderr
    quiet_about(done, "session-a")


def test_malformed_content_is_refused_without_republishing_it(tmp_path: Path) -> None:
    """Three malformed files, three fixed sentences. What was in them
    reaches neither stream, including the exception context: a JSON
    decoder's message quotes the document it choked on."""
    captures = one_turn(tmp_path)
    track = (captures / "session-a.jsonl").read_text(encoding="utf-8")

    (captures / "session-a.jsonl").write_text(
        track + "{" + SENTINEL + "\n", encoding="utf-8"
    )
    done = run(str(captures))
    assert done.returncode == 1
    assert "malformed decision track" in done.stderr

    (captures / "session-a.jsonl").write_bytes(b"\xff\xfe" + SENTINEL.encode())
    bad_bytes = run(str(captures))
    assert bad_bytes.returncode == 1
    assert "not UTF-8" in bad_bytes.stderr

    (captures / "session-a.jsonl").write_text(track, encoding="utf-8")
    (captures / "session-a.json").write_text("{" + SENTINEL, encoding="utf-8")
    manifest = run(str(captures))
    assert manifest.returncode == 1
    assert "malformed manifest" in manifest.stderr

    for done_run in (done, bad_bytes, manifest):
        quiet_about(done_run, SENTINEL)


def test_a_number_the_parser_refuses_is_still_a_fixed_sentence(tmp_path: Path) -> None:
    """An integer past the interpreter's digit limit is refused by
    `json.loads` as a plain `ValueError`, not as the `JSONDecodeError`
    a reader expects, and its message quotes the digits it choked on."""
    captures = one_turn(tmp_path)
    track = (captures / "session-a.jsonl").read_text(encoding="utf-8")
    oversized = "9" * 20000

    (captures / "session-a.jsonl").write_text(
        track + '{"event": "vad", "t_ms": ' + oversized + "}\n", encoding="utf-8"
    )
    in_track = run(str(captures))
    assert in_track.returncode == 1
    assert "malformed decision track" in in_track.stderr

    (captures / "session-a.jsonl").write_text(track, encoding="utf-8")
    (captures / "session-a.json").write_text(
        '{"capture": {"complete": ' + oversized + "}}", encoding="utf-8"
    )
    in_manifest = run(str(captures))
    assert in_manifest.returncode == 1
    assert "malformed manifest" in in_manifest.stderr

    for done in (in_track, in_manifest):
        quiet_about(done, oversized[:64])


def test_nesting_past_the_recursion_limit_is_still_a_fixed_sentence(
    tmp_path: Path,
) -> None:
    """Deep nesting exhausts the parser's stack and raises
    `RecursionError`, which is not a `ValueError` at all and which an
    unguarded run answers with a traceback thousands of frames long."""
    captures = one_turn(tmp_path)
    track = (captures / "session-a.jsonl").read_text(encoding="utf-8")
    deep = "[" * 200000 + SENTINEL + "]" * 200000

    (captures / "session-a.jsonl").write_text(track + deep + "\n", encoding="utf-8")
    in_track = run(str(captures))
    assert in_track.returncode == 1
    assert "malformed decision track" in in_track.stderr

    (captures / "session-a.jsonl").write_text(track, encoding="utf-8")
    (captures / "session-a.json").write_text(deep, encoding="utf-8")
    in_manifest = run(str(captures))
    assert in_manifest.returncode == 1
    assert "malformed manifest" in in_manifest.stderr

    for done in (in_track, in_manifest):
        quiet_about(done, SENTINEL, "RecursionError")


def test_the_decision_tracks_own_fields_are_never_echoed(tmp_path: Path) -> None:
    """A track carries device ids, conversation ids and whatever an
    event declares. The report is timings and counts, so none of it
    reaches a stream even when the run succeeds."""
    captures = write_capture(
        tmp_path / "captures",
        "session-a",
        mic=[(200, 1000)],
        reply=[(1600, 2200)],
        events=[
            {"event": "session_open", "t_ms": 0.0, "device": SENTINEL},
            *speech(200, 1000),
            {**heard(1100, 0.8), "transcript": SENTINEL},
        ],
        total_ms=3000,
    )
    done = run(str(captures))
    assert done.returncode == 0
    quiet_about(done, SENTINEL, "session-a")


def test_an_unreadable_capture_is_an_os_error_nobody_sees_the_shape_of(
    tmp_path: Path,
) -> None:
    captures = one_turn(tmp_path)
    (captures / "session-a.json").chmod(0o000)
    try:
        done = run(str(captures))
    finally:
        (captures / "session-a.json").chmod(0o600)
    assert done.returncode == 1
    assert done.stderr.strip() == "capture 1 could not be read"
    quiet_about(done, "session-a")


def test_a_partial_line_in_the_track_is_skipped_rather_than_refused(
    tmp_path: Path,
) -> None:
    """A track is written by a live session that can be killed
    mid-write. A line missing its timing is not a reason to refuse the
    recording, so the turn still measures."""
    captures = one_turn(tmp_path)
    track = (captures / "session-a.jsonl").read_text(encoding="utf-8")
    (captures / "session-a.jsonl").write_text(
        '{"event": "vad", "listening": true}\n' + track + '{"event": "heard"}\n',
        encoding="utf-8",
    )
    done = run(str(captures))
    assert done.returncode == 0
    assert "wire response latency 0.6 s" in done.stdout
