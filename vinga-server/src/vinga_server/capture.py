"""Recording a session to disk so it can be analysed offline.

`barge_in` misfiring (#28) is an acoustic defect. Nothing in the test
lanes can reproduce it: the unit lane feeds synthetic frames and the
integration lane drives a simulator over a websocket, and both bypass
the microphone, the board's echo cancellation, and the room. The
parameter that decides whether the assistant interrupts itself is how
much of its own voice survives the board's echo cancellation and reaches
the endpointer, and that number is unknown. Tuning against an invented
figure gives a fix that tests clean and fails on the street.

What was missing was not another test but the recording that lets the
tests be written against reality. Three files per session:

- `<session>.wav`, stereo 16 kHz s16le. Channel 0 is the decoded
  microphone as received, channel 1 is what was actually paced out to
  the speaker. Stereo rather than two files because alignment then
  costs nothing: sample N in both channels is the same instant, so echo
  leakage becomes a measurement (cross-correlate the channels, read off
  gain and delay) rather than a guess, and the overlap is directly
  audible in any audio editor.
- `<session>.jsonl`, the decision track: every structured event the
  session already emits, plus a `t_ms` offset that indexes into the WAV,
  plus the one thing the logs do not carry: the endpointer's opinion
  sampled continuously rather than only where it decided something. The
  frames dropped before the decode used to be the second such thing and
  are an ordinary event now (`frames_dropped`), counted by the emitter
  and read here through the tap like everything else.
- `<session>.json`, the manifest: what the capture was made against,
  because a capture outlives the code that made it.

And beside them, one directory of per-turn clips (#496),
`<session>.turns/`, holding mono 16 kHz clips for every turn the
session started: a heard clip, and, when reply audio was paced, a reply
clip.

- `<utterance>.heard.wav`, the exact bytes the turn's ASR was handed,
  written in one piece when the turn starts. Not a cut of channel 0:
  that channel is the capture's own decode of every frame, the guarded
  ones included, and holds no record of where a turn's audio began (the
  endpointer's pre-roll, a merged utterance's two halves), so a word
  error rate measured on a slice of it would measure the slicer too.
- `<utterance>.reply.wav`, what was paced out while that turn was being
  answered: channel 1 of the WAV over the turn's reply window, written
  as the channel places it, silence in its gaps included. The window
  opens when the turn starts and closes when the next one does, at the
  capture's limit, at a write failure or at the close, so a barge-in's
  interrupted reply keeps its last frames and the turn that interrupted
  it starts clean. The manifest records the span on the WAV's own
  timeline, which is what lets anyone holding the three files reproduce
  the clip without trusting it.

A directory rather than more top-level files because the store treats
every top-level `*.wav` as a capture of its own. The directory is part
of its capture: counted against the budget and pruned with the rest.

Everything is stamped against the session's monotonic origin, so the
three files share one timeline.

This writes room audio to disk, which is the opposite of what the rest
of the project promises. It is off unless a directory is configured, and
says so on every session it records.
"""

import builtins
import contextlib
import json
import logging
import os
import shutil
import stat
import struct
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from vinga_server.capture_upload import (
    BUILDING_PREFIX,
    CaptureUpload,
    safe_name,
    staging_root,
)
from vinga_server.events import ServerEvents
from vinga_server.events.catalog import (
    CaptureBelowFloor,
    CaptureDirectoryUnusable,
    CaptureFailed,
    CaptureFilesUnopenable,
    CaptureLimit,
    CaptureOverBudget,
    CapturePruned,
    CaptureStarted,
    CaptureUploadAbandoned,
)
from vinga_server.events.values import (
    CaptureWrite,
    ClassName,
    ConfiguredPath,
    Count,
    Real,
    SessionId,
    SessionIds,
    SessionList,
)

events = ServerEvents(__name__)

# For the one thing this module says that is not an event: an utterance
# id it was handed and would not use, which no catalog value can carry
# because the one value there is to name is the one being refused.
logger = logging.getLogger(__name__)

# When this process began, which is what tells a job THIS run staged
# from one a previous run left behind.
#
# Read at import rather than at the sweep, because sequential lifespans
# in one process share it and that is the point: a prior lifespan's
# worker may still be finishing a job the next lifespan's sweep would
# otherwise adopt and delete underneath it. Wall clock rather than
# monotonic, because what it is compared against is a directory's mtime.
_PROCESS_STARTED = time.time()

# The rate both channels are written at, which is the rate the input
# side of the pipeline runs at. The reply is resampled down to it so
# that one sample index means one instant in both channels.
CAPTURE_RATE = 16000
CAPTURE_CHANNELS = 2
SAMPLE_BYTES = 2
FRAME_BYTES = CAPTURE_CHANNELS * SAMPLE_BYTES

# A canonical PCM WAV header is 44 bytes, and everything after it is raw
# interleaved samples. Two of its fields are byte counts that can only
# be known at the end, so they are written as placeholders and patched
# on a clean close.
WAV_HEADER_BYTES = 44

# How far behind the present the interleaved writer stays before
# committing samples to the file. Both channels are stamped when their
# audio arrives, so anything still to come belongs after the cursor;
# this is slack for the two arriving in either order within one turn of
# the event loop.
FLUSH_LAG_S = 0.25

MB = 1024 * 1024

# Where a session's per-turn clips live, beside its three files, and what
# each one is called inside it. One clip is one channel.
TURNS_SUFFIX = ".turns"
HEARD_SUFFIX = ".heard.wav"
REPLY_SUFFIX = ".reply.wav"
CLIP_CHANNELS = 1


def _wav_header(data_bytes: int, channels: int) -> bytes:
    """A 44 byte canonical PCM header at the capture rate. `data_bytes`
    is a placeholder when the length is not known yet."""
    block = channels * SAMPLE_BYTES
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_bytes,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        channels,
        CAPTURE_RATE,
        CAPTURE_RATE * block,
        block,
        8 * SAMPLE_BYTES,
        b"data",
        data_bytes,
    )


def interleave(left: bytes, right: bytes) -> bytes:
    """Two equal-length s16le mono buffers as one stereo buffer.

    Byte slice assignment rather than a per-sample loop: a quarter of an
    hour is fourteen million samples, and this runs inside a session.
    """
    if len(left) != len(right):
        raise ValueError("channels must be the same length to interleave")
    out = bytearray(len(left) * 2)
    out[0::4] = left[0::2]
    out[1::4] = left[1::2]
    out[2::4] = right[0::2]
    out[3::4] = right[1::2]
    return bytes(out)


class _Channel:
    """One side of the stereo file, buffered until the writer commits.

    Audio is placed by when it arrived rather than by how much has been
    written before it, so a gap in one channel becomes silence rather
    than sliding everything after it out of time with the other channel
    and with the events.
    """

    def __init__(self) -> None:
        self.pending = bytearray()
        # The frame index just past the last audio placed in this
        # channel. Where contiguous audio continues from.
        self.next_frame = 0

    def add(self, pcm: bytes, at_frame: int, start_frame: int) -> None:
        """Place `pcm` at `at_frame`, padding any gap with silence.
        `start_frame` is what index the pending buffer begins at."""
        offset = (at_frame - start_frame) * SAMPLE_BYTES
        end = offset + len(pcm)
        if len(self.pending) < end:
            self.pending.extend(bytes(end - len(self.pending)))
        self.pending[offset:end] = pcm
        self.next_frame = at_frame + len(pcm) // SAMPLE_BYTES

    def take(self, frames: int) -> bytes:
        """The first `frames` frames, silence-padded, removed."""
        want = frames * SAMPLE_BYTES
        if len(self.pending) < want:
            self.pending.extend(bytes(want - len(self.pending)))
        out = bytes(self.pending[:want])
        del self.pending[:want]
        return out


class _ReplyClip:
    """One turn's reply clip: channel 1 over the turn's window, written as
    the channel places it.

    Fed the same audio at the same frame index the channel was, so the
    clip is that channel's span byte for byte by construction, gaps
    padded with the same silence. The file is opened at the first audio
    of the window, so a turn that spoke nothing leaves no file, and its
    header is patched when the window closes. Anything placed past the
    capture's limit is dropped here as the close drops it from the WAV.
    """

    def __init__(self, path: Path, limit_frame: int) -> None:
        self.path = path
        self._limit_frame = limit_frame
        self._file: BinaryIO | None = None
        self._data_bytes = 0
        # The frame the clip begins at on the WAV's timeline, and the
        # one just past its end. None until the first audio.
        self.from_frame: int | None = None
        self.to_frame: int | None = None

    def place(self, pcm: bytes, at: int) -> None:
        """`pcm` placed at frame `at`, which is never before the end of
        what was placed last: the channel's own rule."""
        end = min(at + len(pcm) // SAMPLE_BYTES, self._limit_frame)
        if end <= at:
            return
        if self._file is None:
            self._file = self.path.open("wb")
            self._file.write(_wav_header(0, CLIP_CHANNELS))
            self.from_frame = self.to_frame = at
        assert self.to_frame is not None
        block = bytes((at - self.to_frame) * SAMPLE_BYTES) + pcm[: (end - at) * SAMPLE_BYTES]
        self._file.write(block)
        # For the reason the WAV is flushed as it goes.
        self._file.flush()
        self._data_bytes += len(block)
        self.to_frame = end

    def close(self) -> None:
        """Patch the header and let the file go. Idempotent."""
        clip, self._file = self._file, None
        if clip is None:
            return
        try:
            clip.seek(0)
            clip.write(_wav_header(self._data_bytes, CLIP_CHANNELS))
        finally:
            clip.close()


def _builtin_class(failure: BaseException) -> ClassName:
    """The nearest class in a failure's ancestry that is Python's own
    builtin of that name, which is what a capture says failed.

    Checked by identity against `builtins` rather than by `__module__`,
    which a class may set to anything. Every exception descends from
    `BaseException`, so there is always an answer."""
    for kind in type(failure).__mro__:
        if getattr(builtins, kind.__name__, None) is kind:
            return ClassName(kind.__name__)
    return ClassName(BaseException.__name__)


def _offset_ms(frame: int | None) -> float | None:
    """A frame index on the `t_ms` timeline, exactly: a frame is 1/16 ms,
    so the value needs no rounding and `ms * 16` is the frame again."""
    return None if frame is None else frame * 1000 / CAPTURE_RATE


class SessionCapture:
    """One session's three files, and its turns' clips.

    Writes are best effort by construction: a capture that fails must
    never take a conversation down with it, so every I/O path here
    catches, logs once, and disables itself.
    """

    def __init__(
        self,
        directory: Path,
        session_id: str,
        opened_at: float,
        manifest: dict[str, Any],
        max_session_s: float,
        on_close: "Callable[[str], None] | None" = None,
    ) -> None:
        self._session_id = session_id
        self._opened_at = opened_at
        self._max_session_s = max_session_s
        self.wav_path = directory / f"{session_id}.wav"
        self.jsonl_path = directory / f"{session_id}.jsonl"
        self.manifest_path = directory / f"{session_id}.json"
        self.turns_path = directory / f"{session_id}{TURNS_SUFFIX}"
        self._manifest = dict(manifest)
        # Every turn this capture kept clips for, in the order the turns
        # started, each with its reply clip; and the reply clip whose
        # window is open, if any. Listed in the manifest at close.
        self._turns: list[tuple[str, _ReplyClip]] = []
        self._window: _ReplyClip | None = None
        self._wav: BinaryIO | None = None
        self._events: TextIO | None = None
        self._mic = _Channel()
        self._reply = _Channel()
        # Where the pending buffers begin, and how much is on disk.
        self._start_frame = 0
        self._data_bytes = 0
        self._stopped = False
        # The furthest an event has landed, so the audio can be padded
        # out to cover it rather than leaving offsets past the end.
        # Starts below zero to mean "no events yet", so that a capture
        # with none is not padded to cover an event it never had.
        self._event_frame = -1
        self._on_close = on_close
        # Guards close() against being re-entered from an event written
        # while it is closing.
        self._closing = False

    def start(self) -> None:
        self._wav = self.wav_path.open("wb")
        self._wav.write(_wav_header(0, CAPTURE_CHANNELS))
        self._events = self.jsonl_path.open("w", encoding="utf-8")
        # Written now rather than at close, because the pod being stopped
        # mid-session is plausibly the session most worth looking at, and
        # a capture with no manifest cannot be interpreted at all.
        self._write_manifest(complete=False)

    def _write_manifest(
        self,
        complete: bool,
        duration_s: float | None = None,
        turns: list[dict[str, Any]] | None = None,
    ) -> None:
        payload = dict(self._manifest)
        payload["capture"] = {
            "audio": self.wav_path.name,
            "events": self.jsonl_path.name,
            "sample_rate": CAPTURE_RATE,
            "channels": ["microphone", "reply"],
            # False in a file left behind by a pod that was stopped, so
            # the analysis side knows the WAV header is stale and the
            # length has to come from the file size.
            "complete": complete,
        }
        if duration_s is not None:
            payload["capture"]["duration_s"] = round(duration_s, 3)
        # Only at close, as the duration is: the manifest written at open
        # says nothing about turns, and a pod stopped mid-session leaves
        # clips the manifest does not list, which `complete: false`
        # already tells the analysis side to expect.
        if turns is not None:
            payload["capture"]["turns"] = turns
        self.manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def _at(self, now: float) -> float:
        return now - self._opened_at

    @property
    def _limit_frame(self) -> int:
        """The frame the session limit falls on, which is where the WAV
        and every clip cut from it end."""
        return int(self._max_session_s * CAPTURE_RATE)

    def _frame_of(self, now: float) -> int:
        return max(0, int(self._at(now) * CAPTURE_RATE))

    def _expired(self, now: float) -> bool:
        return self._at(now) >= self._max_session_s

    def _disable(self, doing: CaptureWrite, exc: BaseException) -> None:
        """Say the write failed, stop recording, and close what is open."""
        self._failed(doing, exc)
        with contextlib.suppress(Exception):
            self.close()

    def _failed(self, doing: CaptureWrite, exc: BaseException) -> None:
        """Say a write failed, and stop recording: whatever closes the
        capture after this writes `complete: false`."""
        # The class name and never the exception (the PR #153 review).
        # Every caller here catches a bare `Exception` around a write,
        # so what arrives is whatever the filesystem, the wave module or
        # a JSON encoder raised, and those messages carry the path they
        # tripped on, the bytes they choked on, or the value they could
        # not encode. Handing the object itself as a `%` argument was
        # worse than rendering it: `Emission.args` is deliberately not
        # copied for a tap, so a consumer was given the live exception,
        # its chain and everything the chain closes over.
        #
        # And not even the class that was raised, but the nearest one
        # Python itself defines (#496's review): `type` accepts any
        # identifier as a class name, so a raised class's own name is a
        # string somebody else chose. Read before the thunk, which then
        # holds a name rather than the exception.
        failure = _builtin_class(exc)
        events.emit(
            lambda: CaptureFailed(
                session=SessionId(self._session_id),
                reason=doing,
                failure=failure,
            )
        )
        self._stopped = True

    def microphone(self, pcm: bytes, now: float) -> None:
        """Mic audio as decoded, before any of the session's guards."""
        self._add(self._mic, pcm, now)

    def reply(self, pcm: bytes, now: float) -> None:
        """Audio as paced out to the device, at the capture rate."""
        self._add(self._reply, pcm, now)

    def _add(self, channel: _Channel, pcm: bytes, now: float) -> None:
        if self._stopped or self._wav is None or not pcm:
            return
        if self._expired(now):
            self._finish_at_limit()
            return
        at = max(channel.next_frame, self._frame_of(now), self._start_frame)
        try:
            channel.add(pcm, at, self._start_frame)
            # The reply clip is fed here, with the frame the channel
            # just used, rather than cut from the WAV at close: this is
            # the only place the placement is known, and a cut at close
            # would read the reply spans back on the session loop.
            if channel is self._reply and self._window is not None:
                self._window.place(pcm, at)
            self._flush(self._frame_of(now) - int(FLUSH_LAG_S * CAPTURE_RATE))
        except Exception as exc:  # noqa: BLE001 - capture never breaks a session
            self._disable(CaptureWrite.AUDIO, exc)

    def _flush(self, up_to_frame: int) -> None:
        assert self._wav is not None
        frames = up_to_frame - self._start_frame
        if frames <= 0:
            return
        block = interleave(self._mic.take(frames), self._reply.take(frames))
        self._wav.write(block)
        # Flushed as it goes, because the whole recovery story depends on
        # it: a pod stopped mid-session leaves whatever reached the file,
        # and anything still in a userspace buffer is simply lost. At
        # four writes a second this costs nothing worth counting.
        self._wav.flush()
        self._data_bytes += len(block)
        self._start_frame = up_to_frame

    def utterance_audio(self, utterance: str, pcm: bytes, now: float) -> None:
        """A turn began, answering `pcm`: the exact bytes its ASR is
        handed, or was, where a confirmed barge-in already transcribed
        them. At the pipeline's rate, which is the capture's.

        Written in one piece as the turn's heard clip, and the turn's
        reply window opened in place of the last one, which closes here:
        whatever is paced from now on answers this utterance.

        The id becomes a file name, so it is held to the uploader's name
        rule and refused otherwise, said once without the value. The
        server mints hex, so nothing real is turned away. A refused turn
        still closes the window before it, since a turn did begin; its
        reply belongs to no clip."""
        if self._stopped or self._wav is None:
            return
        if self._expired(now):
            self._finish_at_limit()
            return
        try:
            self._close_window()
        except Exception as exc:  # noqa: BLE001 - capture never breaks a session
            self._disable(CaptureWrite.AUDIO, exc)
            return
        if not safe_name(utterance):
            with contextlib.suppress(Exception):
                logger.warning(
                    "session %s: an utterance id this server did not mint reached "
                    "the capture, so no clip was kept for it",
                    self._session_id,
                )
            return
        try:
            self.turns_path.mkdir(exist_ok=True)
            with (self.turns_path / f"{utterance}{HEARD_SUFFIX}").open("wb") as heard:
                heard.write(_wav_header(len(pcm), CLIP_CHANNELS) + pcm)
        except Exception as exc:  # noqa: BLE001 - capture never breaks a session
            self._disable(CaptureWrite.AUDIO, exc)
            return
        self._window = _ReplyClip(
            self.turns_path / f"{utterance}{REPLY_SUFFIX}", self._limit_frame
        )
        self._turns.append((utterance, self._window))

    def _close_window(self) -> None:
        window, self._window = self._window, None
        if window is not None:
            window.close()

    def _turn_entries(self) -> list[dict[str, Any]]:
        """The manifest's `capture.turns`: one entry per turn in start
        order, its clips named inside `<session>.turns/`, and the
        reply clip's span on the WAV's `t_ms` timeline, from its first
        frame to just past its last, so cutting channel 1 at those two
        offsets reproduces it. A turn that spoke nothing has nulls."""
        return [
            {
                "utterance": utterance,
                "heard": f"{utterance}{HEARD_SUFFIX}",
                "reply": None if reply.from_frame is None else reply.path.name,
                "reply_from_ms": _offset_ms(reply.from_frame),
                "reply_to_ms": _offset_ms(reply.to_frame),
            }
            for utterance, reply in self._turns
        ]

    def _finish_at_limit(self) -> None:
        """End a capture that has run as long as it is allowed to. The
        conversation carries on; only the recording stops."""
        if self._closing:
            return
        events.emit(
            lambda: CaptureLimit(
                session=SessionId(self._session_id),
                limit_s=Real(self._max_session_s),
            )
        )
        self.close()

    def event(self, payload: dict[str, Any], now: float) -> None:
        """One line of the decision track: the event as logged, plus
        where it lands in the audio.

        Subject to the same limit as the audio. The audio is clamped to
        it on close, so an event written past it would be an offset with
        no audio under it, which is the one thing the decision track
        promises not to be."""
        if self._stopped or self._events is None:
            return
        if self._expired(now):
            self._finish_at_limit()
            return
        self._write_event(payload, now)

    def _write_event(self, payload: dict[str, Any], now: float) -> None:
        """The write itself, without the limit check, so the last
        records a closing capture emits are not turned away by the very
        limit that is closing it.

        The offset is derived from a frame index rather than from the
        clock, and that index is clamped to the limit the audio is
        clamped to. Both halves of the guarantee then come from one
        number: every offset in the track indexes into the WAV, by
        construction rather than by every caller remembering to.
        """
        if self._events is None:
            return
        frame = min(self._frame_of(now), self._limit_frame)
        record = {"t_ms": round(frame / CAPTURE_RATE * 1000, 1), **payload}
        # An event's offset is only useful if it indexes into the audio,
        # and a session can be open through stretches with no decodable
        # audio at all. Remembering where the last one landed is what
        # lets close() pad the file out to cover it.
        self._event_frame = max(self._event_frame, frame)
        try:
            self._events.write(json.dumps(record, default=str) + "\n")
            # For the same reason the audio is flushed: the events
            # leading up to a hard stop are the ones worth having.
            self._events.flush()
        except Exception as exc:  # noqa: BLE001 - capture never breaks a session
            self._disable(CaptureWrite.EVENT, exc)

    def vad(self, speech_ms: float, listening: bool, replying: bool, now: float) -> None:
        """The endpointer's opinion, sampled every frame rather than only
        where it decided something. This is what turns "barge-in fired
        wrongly" into "the endpointer classified 340 ms of the
        assistant's own voice as speech starting at 12.7 s"."""
        self.event(
            {
                "event": "vad",
                "session": self._session_id,
                "speech_ms": round(speech_ms, 1),
                "listening": listening,
                "replying": replying,
            },
            now,
        )

    def close(self) -> None:
        """Finish the files. Patching the WAV header is what makes a
        capture that ended cleanly self-describing; one that did not is
        still every byte of audio it managed to write, and the manifest
        says which it is."""
        if self._wav is None and self._events is None:
            self._closing = True
            if self._on_close is not None:
                self._on_close(self._session_id)
                self._on_close = None
            return
        self._closing = True
        wav, events = self._wav, self._events
        self._wav = self._events = None
        # A reply clip still open is finished first, and a failure to
        # finish it (its header patch, or the close under it) is a
        # write failure like any other: said, and the manifest below
        # then says the capture is not complete, rather than listing a
        # clip with a stale header under `complete: true`. Said after
        # the suite rather than in it, so nothing the report does can
        # carry the exception along as its context. A capture already
        # stopped by a failure has said so once, and says nothing more.
        unfinished: BaseException | None = None
        try:
            self._close_window()
        except Exception as exc:  # noqa: BLE001 - capture never breaks a session
            unfinished = exc
        if unfinished is not None and not self._stopped:
            self._failed(CaptureWrite.AUDIO, unfinished)
        unfinished = None
        if wav is not None:
            with contextlib.suppress(Exception):
                # Out to the furthest of the audio and the last event.
                # An event's offset has to index into the file, and a
                # session can be open through stretches with no
                # decodable audio at all, so the quiet is written as
                # silence rather than left as a timeline the events
                # point past the end of. Bounded by the session limit,
                # which is what already bounds one capture's size.
                # `_event_frame + 1`, not `_event_frame`: a sample at
                # index N only exists once N+1 frames are written, and
                # `t_ms` is rounded to a tenth of a millisecond, which
                # can round up. One frame at this rate is 0.0625 ms
                # against a worst-case rounding of 0.05 ms, so the extra
                # frame covers both. Without it an event landing on the
                # last frame pointed one sample past the end.
                end = max(
                    self._mic.next_frame, self._reply.next_frame, self._event_frame + 1
                )
                self._start_frame = min(end, self._limit_frame)
                frames = self._start_frame - (self._data_bytes // FRAME_BYTES)
                if frames > 0:
                    block = interleave(self._mic.take(frames), self._reply.take(frames))
                    wav.write(block)
                    self._data_bytes += len(block)
                wav.seek(0)
                wav.write(_wav_header(self._data_bytes, CAPTURE_CHANNELS))
            with contextlib.suppress(Exception):
                wav.close()
        if events is not None:
            with contextlib.suppress(Exception):
                events.close()
        with contextlib.suppress(Exception):
            self._write_manifest(
                complete=not self._stopped,
                duration_s=self._data_bytes / FRAME_BYTES / CAPTURE_RATE,
                turns=self._turn_entries(),
            )
        # The store stops protecting this capture from pruning, and
        # checks the budget now that its final size is known.
        if self._on_close is not None:
            with contextlib.suppress(Exception):
                self._on_close(self._session_id)
            self._on_close = None


def sweep_upload_staging(directory: Path) -> None:
    """Say what a previous run left staged for upload, and remove it.

    A function over a directory rather than a method on the store, and
    the round's third finding is what made it one. A store is only built
    where capture is ENABLED, and the uploader's builder runs ahead of it
    and can refuse; between them, every configuration this sweep exists
    for reached neither. A boundary-refused boot and an extra-less boot
    refuse before any store is constructed, and a configured-but-disabled
    capture constructs no store at all, so staged room audio stayed on
    disk in exactly the four configurations an operator chose to stop
    exporting in. It answers to the capture SECTION now: the section
    names a directory, the directory is swept, and whether anything is
    being recorded into it is a separate question asked afterwards.

    Removing the section parks this with the rest of the capture
    machinery, which is the one configuration that leaves the directory
    untouched and is stated in the flag's own reference prose.

    One sanitized event per job before its links go, because a restart
    must not be the thing that silently discards the only record that an
    upload never happened. Nothing is retried: a retry store would be a
    durability promise this flag does not make, and the event is the
    honest ledger.

    A job younger than this process is skipped. Sequential lifespans in
    one process share a staging directory, and a prior lifespan's worker
    may still hold a job in flight; adopting it would mean deleting a
    pair out from under an upload that is happening.
    """
    root = staging_root(directory)
    try:
        jobs = sorted(path for path in root.iterdir() if path.is_dir())
    except OSError:
        return
    for job in jobs:
        try:
            if job.stat().st_mtime >= _PROCESS_STARTED:
                continue
        except OSError:
            continue
        # A name beginning with a dot is a staging that never committed,
        # so there was never a job to abandon: the links go without a
        # word.
        if not job.name.startswith(BUILDING_PREFIX):
            _abandoned(job.name)
        with contextlib.suppress(OSError):
            shutil.rmtree(job)


def _abandoned(session: str) -> None:
    """One leftover job, said before its links go.

    A function of its own rather than a thunk inside the loop above, for
    the reason the loop cannot: a lambda built in a loop reads whatever
    the variable holds when it is called, and a parameter is the honest
    way to hand it one value.
    """
    events.emit(lambda: CaptureUploadAbandoned(session=SessionId(session)))


class CaptureStore:
    """The capture directory: what may be started, and what is kept.

    `/data` is the only writable path in a deployment and it also holds
    agent memory and the model caches, so filling it does not degrade
    capture, it breaks those. Hence both a budget for this directory and
    a floor on free space: a total-size cap does not protect against the
    caches growing underneath it.
    """

    def __init__(
        self,
        directory: Path,
        max_session_s: float,
        max_total_mb: float,
        min_free_mb: float,
        uploads: CaptureUpload | None = None,
    ) -> None:
        self.directory = directory
        self._max_session_s = max_session_s
        self._max_total_mb = max_total_mb
        self._min_free_mb = min_free_mb
        # Sessions recording right now. Pruning must not unlink a file
        # that still has a writer behind it.
        self._active: set[str] = set()
        # Where a closed session's recording goes next, when a
        # deployment asked for that (#67). Optional in the sense every
        # collaborator here is: None is a deployment that did not ask,
        # it is compared `is not None`, and nothing on this class's own
        # paths needs it to exist.
        self._uploads = uploads

    def _free_mb(self) -> float:
        return shutil.disk_usage(self.directory).free / MB

    def _captures(self) -> list[Path]:
        return sorted(self.directory.glob("*.wav"), key=lambda p: p.stat().st_mtime)

    def _total_mb(self) -> float:
        """Every regular file under the directory, its turns and the
        upload staging included, counted once per inode.

        Once per inode because staging is hardlinks: a staged pair and
        the capture it came from are one set of blocks while both names
        exist, and still blocks on the disk after a prune has unlinked
        the capture's name while the upload waits. Counting names would
        count the pair twice in the first case, and a walk that skipped
        staging would lose it in the second. Symlinks are not followed
        and not counted: nothing here makes one, and a planted one must
        not make a file elsewhere count against this budget."""
        seen: set[tuple[int, int]] = set()
        total = 0
        for root, _, names in os.walk(self.directory):
            for name in names:
                with contextlib.suppress(OSError):
                    found = os.lstat(os.path.join(root, name))
                    identity = (found.st_dev, found.st_ino)
                    if stat.S_ISREG(found.st_mode) and identity not in seen:
                        seen.add(identity)
                        total += found.st_size
        return total / MB

    def prune(self) -> list[str]:
        """Drop whole captures, oldest first, until the directory is
        inside its budget. All three files go together, and the turns
        directory with them: part of a capture is not a capture.

        What it never touches is the upload staging, which the budget
        counts: a backlog of staged jobs over budget is said by the
        warning below rather than hidden, and drains as the uploads
        finish.

        Two are never dropped. A session still recording, because its
        descriptors are open and unlinking underneath it would leave the
        session writing to a file nobody can find. And the newest
        finished one, because a budget smaller than a single session
        would otherwise delete the recording that was just taken, which
        is the one somebody went out to make.
        """
        removed: list[str] = []
        captures = self._captures()
        protected = set(self._active)
        if captures:
            protected.add(captures[-1].stem)
        candidates = [path for path in captures if path.stem not in protected]
        while candidates and self._total_mb() > self._max_total_mb:
            oldest = candidates.pop(0)
            for path in (oldest, oldest.with_suffix(".jsonl"), oldest.with_suffix(".json")):
                with contextlib.suppress(OSError):
                    path.unlink()
            with contextlib.suppress(OSError):
                shutil.rmtree(self.directory / f"{oldest.stem}{TURNS_SUFFIX}")
            removed.append(oldest.stem)
        if removed:
            events.emit(
                lambda: CapturePruned(
                    sessions=SessionIds(tuple(removed)),
                    removed=Count(len(removed)),
                    budget_mb=Real(self._max_total_mb),
                    listed=SessionList.of(tuple(removed)),
                )
            )
        over = self._total_mb()
        if over > self._max_total_mb:
            events.emit(
                lambda: CaptureOverBudget(
                    total_mb=Count(round(over)),
                    used=Real(over),
                    budget_mb=Real(self._max_total_mb),
                )
            )
        return removed

    def finished(self, session_id: str) -> None:
        """A capture closed. It stops being protected, whatever is going
        to be uploaded is put out of the prune's reach, and the budget
        is checked now that its final size is known: without this a
        single session that overran would sit there until some later
        session happened to start.

        The staging is HERE and ahead of the prune, which is the one
        ordering that works. This is where a capture's files become
        final, and it is also where they become prune candidates, so any
        later moment is a moment a capture can already have been unlinked
        by a session under budget pressure. It does not enqueue: this
        fires for a capture that ended early at its duration limit or
        after a write failure too, while the conversation carries on.
        """
        self._active.discard(session_id)
        if self._uploads is not None:
            self._uploads.stage(
                session_id,
                self.directory / f"{session_id}.wav",
                self.directory / f"{session_id}.json",
            )
        with contextlib.suppress(OSError):
            self.prune()

    def session_closed(self, session_id: str) -> None:
        """A session ended, and whatever was staged for it may go.

        Called from the device session's own close ordering rather than
        from anything here, because nothing here knows: `finished()`
        above means the files are final, which happens mid-conversation
        for an early-finished capture. This is the only signal that the
        conversation is over.
        """
        if self._uploads is not None:
            self._uploads.session_closed(session_id)

    def open(
        self, session_id: str, opened_at: float, manifest: dict[str, Any]
    ) -> SessionCapture | None:
        """Begin a capture, or answer None having said why not.

        Declining is a warning rather than a failure: an operator who
        turned capture on wants to know it is not recording, and a
        conversation is worth more than a recording of it.
        """
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.prune()
            free_mb = self._free_mb()
        except OSError as raised:
            # Bound to an ordinary local first: `except ... as` unbinds
            # its name when the block ends, and the thunk below is built
            # here and called inside the emitter's guard.
            failure = raised
            events.emit(
                lambda: CaptureDirectoryUnusable(
                    session=SessionId(session_id),
                    failure=ClassName.of(failure),
                    directory=ConfiguredPath(self.directory),
                )
            )
            return None
        if free_mb < self._min_free_mb:
            events.emit(
                lambda: CaptureBelowFloor(
                    session=SessionId(session_id),
                    free_mb=Count(round(free_mb)),
                    free=Real(free_mb),
                    floor_mb=Real(self._min_free_mb),
                )
            )
            return None
        capture = SessionCapture(
            self.directory,
            session_id,
            opened_at,
            manifest,
            self._max_session_s,
            on_close=self.finished,
        )
        self._active.add(session_id)
        try:
            capture.start()
        except OSError as raised:
            failure = raised
            self._active.discard(session_id)
            events.emit(
                lambda: CaptureFilesUnopenable(
                    session=SessionId(session_id), failure=ClassName.of(failure)
                )
            )
            return None
        events.emit(
            lambda: CaptureStarted(
                session=SessionId(session_id), path=ConfiguredPath(capture.wav_path)
            )
        )
        return capture


class DeviceFacts:
    """What a device told the OTA endpoint about itself, kept until the
    session it is about to open asks for it.

    The firmware version is arguably the most load-bearing field in a
    capture manifest, because echo cancellation is firmware-side, and
    `ota.reply.check_version` is the only place the device ever states
    it. Bounded, so a server that many devices check in with does not
    accumulate them forever.
    """

    def __init__(self, limit: int = 256) -> None:
        self._limit = limit
        self._facts: OrderedDict[str, dict[str, str]] = OrderedDict()

    def record(self, mac: str, firmware: str, board: str) -> None:
        self._facts[mac] = {"firmware": firmware, "board": board}
        self._facts.move_to_end(mac)
        while len(self._facts) > self._limit:
            self._facts.popitem(last=False)

    def get(self, mac: str | None) -> dict[str, str]:
        if mac is None:
            return {}
        return dict(self._facts.get(mac, {}))
