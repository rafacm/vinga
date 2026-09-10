#!/usr/bin/env python3
"""Wire response latency over vinga session captures.

Usage:
  python3 scripts/wire_latency.py <captures-directory>

Stdlib only, so `python3` is enough and no environment has to be
prepared. It reads the triplet session capture writes (`<session>.wav`
stereo 16 kHz, `<session>.jsonl` decision track, `<session>.json`
manifest) and reports, per turn, how long the server took to put reply
audio on the wire after the user stopped speaking.

What the number is, exactly. Channel 0 is the microphone as decoded and
channel 1 is what was paced out to the device, on one shared timeline,
so the interval between them is the wire path: end of user speech, to
the first reply audio sent. It EXCLUDES downlink transport and device
playback, which is why it is never called perceived latency: it is not
what the person in the room waited for, it is what this server
contributed to it. The script says so in its own output rather than
leaving the caveat in a document nobody reads beside the number.

Its precision, also stated in the output: energy is read in 20 ms
frames and the answer is reported to a tenth of a second, because that
is the resolution the method has. The number answers "800 ms" or
"2.5 s"; it never answers a count of milliseconds, and a reader who
treats it as one is reading noise.

How end of user speech is found. The decision track carries the
endpointer's opinion sampled every frame (`vad` lines with `speech_ms`
and `listening`), so a turn is a run of samples where the endpointer is
counting speech while the session is listening, ending where
`speech_ms` returns to zero or where the samples stop. That gives the
instant the endpointer decided, which is not the instant the user
stopped: the endpointer only decides after its own trailing silence.
The speech end is therefore read from channel 0, as the last frame
carrying speech energy at or before that decision, which puts the
endpointer's hangover inside the measured interval where it belongs.
`heard.duration_s` is used as a consistency bound and never as a
timestamp: it stamps transcription completion, so a speech end outside
the window that event bounds means the pairing is wrong and the turn
reports no number instead of a wrong one.

Every turn gets a line: a measurement, or one of the closed reasons
below saying why no number exists. Nothing is guessed.

  nothing_transcribed        the utterance transcribed to nothing, so
                             no reply was ever going to be sent
  no_transcription_event     no `heard` or `nothing_heard` follows the
                             utterance, so the turn cannot be paired
  no_speech_energy           channel 0 carries no speech energy under
                             the endpointer's own decision
  outside_heard_bound        the speech end falls outside what the
                             transcription event bounds
  reply_already_playing      reply audio was mid-flight at the speech
                             end (a barge-in), so no onset is this
                             turn's
  filler_audio_first         a filler clip played first, so the first
                             audio is the latency mask and not the reply
  no_reply_audio             channel 1 stays silent until the next turn

Exit codes follow `check_doc_links.py`: 0 success, 1 a failure the
caller has to act on (a capture that could not be read, or a directory
with no capture in it), 2 a bad invocation.

Output discipline, also that script's. Captures are numbered in the
directory's sorted order rather than named, and no filename, path,
session id or transcript is ever printed: a capture is a recording of
somebody's room, its filename is content this tool was handed, and the
decision track holds fields this tool has no business republishing.
What reaches the streams is timings, counts and closed tokens from the
literals above. Every failure leaves through one door, `Refusal`, whose
message is a fixed sentence assembled from literals and a capture
number this module generated itself; refusals are raised after their
`except` arm rather than inside it, so no handled exception rides out
on `__context__`.

Cost: the envelope is computed in Python arithmetic rather than numpy,
which is a few seconds for a long capture and no dependency at all.
"""

import argparse
import array
import json
import math
import sys
import wave
from pathlib import Path
from typing import NamedTuple

USAGE = (
    "usage: wire_latency.py <captures-directory>\n"
    "the arguments were not understood; see the module docstring"
)

# The recording format, which is `capture.py`'s and not negotiable
# here: anything else is a file this script cannot interpret.
RATE = 16000
CHANNELS = 2
SAMPLE_BYTES = 2

# The envelope's resolution. Twenty milliseconds is short enough to put
# the fall of an utterance inside one frame at the reported precision
# and long enough that the RMS of a frame means something.
FRAME_MS = 20
FRAME_SAMPLES = RATE * FRAME_MS // 1000

# What counts as sound. A channel's own floor plus a margin, so a noisy
# room and a digitally silent simulator capture are both read on their
# own terms, but never below an absolute level: digital silence and the
# dither a codec leaves behind sit far under anything a voice reaches,
# and a floor derived from a capture that is mostly silence would
# otherwise promote that dither to speech.
FLOOR_PERCENTILE = 0.2
FLOOR_MARGIN_DB = 12.0
ACTIVE_FLOOR_DBFS = -60.0

# How far back from the endpointer's decision the speech energy may
# sit. Beyond this the fall belongs to some earlier utterance.
LOOKBACK_MS = 2000

# How far apart two `vad` samples may be and still belong to one
# utterance. Samples arrive per audio frame while the session listens,
# so a gap this size is the session having stopped listening.
VAD_GAP_MS = 1000

# Slack on the transcription bound. The `heard` event stamps the end of
# transcription, and the speech it describes must lie behind it by no
# more than its own duration plus the time the pipeline took to get
# there.
HEARD_SLACK_MS = 1000

# How long channel 1 must have been silent for a rise to be the start
# of a reply rather than the continuation of one.
QUIET_BEFORE_REPLY_MS = 200

REPORTED_PRECISION_S = 0.1

PRECISION_SENTENCE = (
    "Precision: energy is read in 20 ms frames and the answer is "
    "reported to a tenth of a second. The number answers 800 ms or "
    "2.5 s, never a count of milliseconds."
)

EXCLUSION_SENTENCE = (
    "This is the wire path only. It excludes downlink transport and "
    "device playback, so it is what the server contributed and not "
    "what the room waited."
)

# Every reason a turn can carry instead of a number. Closed: a report
# either names one of these or reports a measurement.
NOTHING_TRANSCRIBED = "nothing_transcribed"
NO_TRANSCRIPTION_EVENT = "no_transcription_event"
NO_SPEECH_ENERGY = "no_speech_energy"
OUTSIDE_HEARD_BOUND = "outside_heard_bound"
REPLY_ALREADY_PLAYING = "reply_already_playing"
FILLER_AUDIO_FIRST = "filler_audio_first"
NO_REPLY_AUDIO = "no_reply_audio"

REASONS = (
    NOTHING_TRANSCRIBED,
    NO_TRANSCRIPTION_EVENT,
    NO_SPEECH_ENERGY,
    OUTSIDE_HEARD_BOUND,
    REPLY_ALREADY_PLAYING,
    FILLER_AUDIO_FIRST,
    NO_REPLY_AUDIO,
)


class Refusal(Exception):
    """A refusal. Its message is always a fixed sentence."""


class _FixedMessageParser(argparse.ArgumentParser):
    """An argument parser that never repeats what was typed.

    Argparse's own error path prints the offending arguments verbatim,
    and the arguments here are paths into somebody's filesystem.
    """

    def error(self, message: str) -> None:
        print(USAGE, file=sys.stderr)
        raise SystemExit(2)


class Turn(NamedTuple):
    """One utterance and what came back, or why nothing did."""

    index: int
    speech_end_ms: float | None
    onset_ms: float | None
    latency_ms: float | None
    reason: str | None


class Utterance(NamedTuple):
    """A run of endpointer samples that were counting speech."""

    start_ms: float
    decided_ms: float


class Track(NamedTuple):
    """What the decision track carries that timings are read from. No
    transcript field exists here, deliberately: nothing in this script
    ever holds one."""

    vad: list[tuple[float, float, bool]]
    heard: list[tuple[float, float]]
    nothing_heard: list[float]
    filler: list[float]


def dbfs(samples: array.array) -> float:
    """One frame's RMS, in dB relative to full scale."""
    if not samples:
        return -math.inf
    total = 0
    for value in samples:
        total += value * value
    rms = math.sqrt(total / len(samples))
    return 20 * math.log10(max(rms, 1e-9) / 32768.0)


def envelopes(path: Path, number: int) -> tuple[list[float], list[float]]:
    """The two channels as per-frame levels, read a frame at a time so
    a long capture never lands in memory whole."""
    problem = None
    mic: list[float] = []
    reply: list[float] = []
    try:
        with wave.open(str(path)) as source:
            if (
                source.getnchannels() != CHANNELS
                or source.getframerate() != RATE
                or source.getsampwidth() != SAMPLE_BYTES
            ):
                problem = f"capture {number} is not a stereo 16 kHz recording"
            elif source.getnframes() <= 0:
                problem = f"capture {number} has no audio, so it has no timeline"
            else:
                while True:
                    raw = source.readframes(FRAME_SAMPLES)
                    if len(raw) < FRAME_SAMPLES * CHANNELS * SAMPLE_BYTES:
                        break
                    block = array.array("h")
                    block.frombytes(raw)
                    if sys.byteorder == "big":
                        block.byteswap()
                    mic.append(dbfs(block[0::2]))
                    reply.append(dbfs(block[1::2]))
    except (OSError, wave.Error, EOFError, ValueError):
        problem = f"capture {number} has unreadable audio"
    if problem is not None:
        raise Refusal(problem)
    return mic, reply


def threshold_of(levels: list[float]) -> float:
    """What counts as sound in this channel: its own floor plus a
    margin, never under the absolute floor."""
    if not levels:
        return ACTIVE_FLOOR_DBFS
    ordered = sorted(levels)
    floor = ordered[min(len(ordered) - 1, int(len(ordered) * FLOOR_PERCENTILE))]
    if not math.isfinite(floor):
        return ACTIVE_FLOOR_DBFS
    return max(floor + FLOOR_MARGIN_DB, ACTIVE_FLOOR_DBFS)


def read_track(path: Path, number: int) -> Track:
    """The decision track, reduced to the timings this script reads.

    Lines that are not objects, and fields that are not numbers, are
    skipped rather than refused: a track is written by a live session
    that may have been killed mid-line, and one unusable line is not a
    reason to refuse the recording. A file that is not text, or a line
    that is not JSON at all, is a malformed track and is refused.
    """
    problem = None
    track = Track(vad=[], heard=[], nothing_heard=[], filler=[])
    try:
        raw = path.read_bytes()
    except OSError:
        problem = f"capture {number} could not be read"
    if problem is not None:
        raise Refusal(problem)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        problem = f"capture {number} has a decision track that is not UTF-8"
    if problem is not None:
        raise Refusal(problem)
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            problem = f"capture {number} has a malformed decision track"
            break
        if not isinstance(record, dict):
            continue
        at = _number(record.get("t_ms"))
        if at is None:
            continue
        name = record.get("event")
        if name == "vad":
            speech_ms = _number(record.get("speech_ms"))
            if speech_ms is not None:
                track.vad.append((at, speech_ms, bool(record.get("listening"))))
        elif name == "heard":
            track.heard.append((at, _number(record.get("duration_s")) or 0.0))
        elif name == "nothing_heard":
            track.nothing_heard.append(at)
        elif name == "filler_played":
            track.filler.append(at)
    if problem is not None:
        raise Refusal(problem)
    return track


def _number(value: object) -> float | None:
    """A JSON number, or None for anything else. `bool` is excluded on
    purpose: it is an `int` in Python and never a timing."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return float(value)


def read_manifest(path: Path, number: int) -> dict:
    """The manifest, checked for the one fact a measurement depends on:
    that the capture was finished, so its timeline is the whole of what
    was recorded."""
    problem = None
    try:
        raw = path.read_bytes()
    except OSError:
        problem = f"capture {number} could not be read"
    if problem is not None:
        raise Refusal(problem)
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        problem = f"capture {number} has a malformed manifest"
    if problem is not None:
        raise Refusal(problem)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("capture"), dict):
        raise Refusal(f"capture {number} has a malformed manifest")
    if manifest["capture"].get("complete") is not True:
        raise Refusal(f"capture {number} was never finished, so its timeline is partial")
    return manifest


def utterances(vad: list[tuple[float, float, bool]]) -> list[Utterance]:
    """The endpointer's utterances: runs of samples counting speech
    while listening, each ending where `speech_ms` returns to zero, the
    samples stop, or the session stopped listening long enough that the
    next sample belongs to another utterance."""
    found: list[Utterance] = []
    start: float | None = None
    last_speaking: float | None = None
    previous: float | None = None
    for at, speech_ms, listening in sorted(vad):
        speaking = listening and speech_ms > 0
        gap = previous is not None and at - previous > VAD_GAP_MS
        if start is not None and (not speaking or gap):
            found.append(Utterance(start, last_speaking if last_speaking else start))
            start = None
        if speaking:
            if start is None:
                start = at
            last_speaking = at
        previous = at
    if start is not None:
        found.append(Utterance(start, last_speaking if last_speaking else start))
    return found


def speech_end_ms(mic: list[float], decided_ms: float, threshold: float) -> float | None:
    """The end of the last frame carrying speech energy at or before the
    endpointer's decision, which is where the user actually stopped."""
    last = min(len(mic) - 1, int(decided_ms // FRAME_MS))
    first = max(0, last - LOOKBACK_MS // FRAME_MS)
    for index in range(last, first - 1, -1):
        if mic[index] >= threshold:
            return (index + 1) * FRAME_MS
    return None


def reply_onset_ms(
    reply: list[float], after_ms: float, until_ms: float, threshold: float
) -> tuple[float | None, str | None]:
    """Where channel 1 next begins to speak, or why that question has no
    answer for this turn."""
    start = max(0, int(after_ms // FRAME_MS))
    end = min(len(reply), int(math.ceil(until_ms / FRAME_MS)))
    needed = QUIET_BEFORE_REPLY_MS // FRAME_MS
    quiet = 0
    index = start - 1
    while index >= 0 and quiet < needed and reply[index] < threshold:
        quiet += 1
        index -= 1
    if index < 0:
        # Nothing before the recording began can have been playing.
        quiet = needed
    for index in range(start, end):
        if reply[index] >= threshold:
            if quiet < needed:
                return None, REPLY_ALREADY_PLAYING
            return index * FRAME_MS, None
        quiet += 1
    return None, NO_REPLY_AUDIO


def _first_between(times: list[float], low: float, high: float) -> float | None:
    for at in sorted(times):
        if low <= at < high:
            return at
    return None


def turns_of(mic: list[float], reply: list[float], track: Track) -> list[Turn]:
    """One report per utterance the endpointer heard, paired with the
    reply onset that follows it and bounded by the next utterance."""
    mic_threshold = threshold_of(mic)
    reply_threshold = threshold_of(reply)
    audio_end_ms = max(len(mic), len(reply)) * FRAME_MS
    found = utterances(track.vad)
    reports: list[Turn] = []
    for number, utterance in enumerate(found, 1):
        after = found[number].start_ms if number < len(found) else audio_end_ms
        reports.append(
            _turn(
                number,
                utterance,
                after,
                mic,
                reply,
                track,
                mic_threshold,
                reply_threshold,
            )
        )
    return reports


def _turn(
    number: int,
    utterance: Utterance,
    next_start_ms: float,
    mic: list[float],
    reply: list[float],
    track: Track,
    mic_threshold: float,
    reply_threshold: float,
) -> Turn:
    """One utterance's report, measured or refused with a reason.

    The order of the questions is the order in which an answer stops
    being possible: an utterance nothing was transcribed from was never
    going to be answered, so its missing reply is not a latency failure
    and is not reported as one.
    """
    heard_at = _first_between(
        [at for at, _ in track.heard], utterance.decided_ms, next_start_ms
    )
    nothing_at = _first_between(track.nothing_heard, utterance.decided_ms, next_start_ms)
    if heard_at is None and nothing_at is not None:
        return Turn(number, None, None, None, NOTHING_TRANSCRIBED)
    if heard_at is None:
        return Turn(number, None, None, None, NO_TRANSCRIPTION_EVENT)
    duration_s = next(duration for at, duration in track.heard if at == heard_at)

    end = speech_end_ms(mic, utterance.decided_ms, mic_threshold)
    if end is None:
        return Turn(number, None, None, None, NO_SPEECH_ENERGY)
    lowest = heard_at - duration_s * 1000 - HEARD_SLACK_MS
    if not lowest <= end <= heard_at + HEARD_SLACK_MS:
        return Turn(number, None, None, None, OUTSIDE_HEARD_BOUND)

    onset, reason = reply_onset_ms(reply, end, next_start_ms, reply_threshold)
    if onset is None:
        return Turn(number, end, None, None, reason)
    if _first_between(track.filler, end, onset + FRAME_MS) is not None:
        return Turn(number, end, onset, None, FILLER_AUDIO_FIRST)
    return Turn(number, end, onset, onset - end, None)


def seconds(ms: float) -> str:
    """A timing at the precision this method has, and no finer."""
    return f"{round(ms / 1000 / REPORTED_PRECISION_S) * REPORTED_PRECISION_S:.1f} s"


def print_capture(number: int, turns: list[Turn]) -> int:
    """One capture's report. Returns how many turns measured."""
    measured = sum(1 for turn in turns if turn.latency_ms is not None)
    print(f"capture {number}: {len(turns)} turn(s), {measured} measured")
    for turn in turns:
        if turn.latency_ms is not None and turn.speech_end_ms is not None:
            print(
                f"  turn {turn.index}: speech ended at {seconds(turn.speech_end_ms)}, "
                f"reply audio began at {seconds(turn.onset_ms or 0.0)}, "
                f"wire response latency {seconds(turn.latency_ms)}"
            )
        elif turn.speech_end_ms is not None:
            print(
                f"  turn {turn.index}: speech ended at {seconds(turn.speech_end_ms)}, "
                f"no number ({turn.reason})"
            )
        else:
            print(f"  turn {turn.index}: no number ({turn.reason})")
    return measured


def analyse(stem: Path, number: int) -> list[Turn]:
    """One capture, from its three files to its turns."""
    read_manifest(stem.with_suffix(".json"), number)
    track = read_track(stem.with_suffix(".jsonl"), number)
    mic, reply = envelopes(stem.with_suffix(".wav"), number)
    problem = None
    try:
        return turns_of(mic, reply, track)
    except (ArithmeticError, ValueError, OverflowError):
        problem = f"capture {number} has timings that do not make sense"
    raise Refusal(problem)


def build_parser() -> argparse.ArgumentParser:
    parser = _FixedMessageParser(
        prog="wire_latency.py",
        description="Wire response latency over vinga session captures.",
    )
    parser.add_argument("captures", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """The one exception boundary. Everything below raises `Refusal`
    and nothing else escapes as a traceback: a traceback prints the
    repr of the locals, and the locals here are the paths and the
    recording this script refuses to echo."""
    args = build_parser().parse_args(argv)
    directory = args.captures
    problem = None
    try:
        listed = sorted(path.with_suffix("") for path in directory.glob("*.wav"))
        readable = directory.is_dir()
    except OSError:
        problem = "the given captures directory could not be read"
        listed, readable = [], False
    if problem is not None or not readable:
        print("the given captures directory could not be read", file=sys.stderr)
        return 2
    if not listed:
        print("no capture was found in the given directory", file=sys.stderr)
        return 1

    failures = 0
    turns = 0
    measured = 0
    for number, stem in enumerate(listed, 1):
        refusal = None
        try:
            reports = analyse(stem, number)
        except Refusal as exc:
            refusal = str(exc)
        except (OSError, UnicodeError):
            refusal = f"capture {number} could not be read"
        if refusal is not None:
            print(refusal, file=sys.stderr)
            failures += 1
            continue
        turns += len(reports)
        measured += print_capture(number, reports)

    print(
        f"\n{len(listed) - failures} capture(s), {turns} turn(s), "
        f"{measured} measured."
    )
    print(PRECISION_SENTENCE)
    print(EXCLUSION_SENTENCE)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
