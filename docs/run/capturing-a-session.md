# Capturing a session

At the end of this guide you will have recorded a field session as one
stereo WAV of microphone and speaker on a shared timeline, beside the
decisions the server made and what it was configured with, and turned
recording off again.

Every capture key, with its default and bounds, is in the server
configuration reference under
[`server.capture`](../reference/server-config.md#servercapture). The
text record of the same session, which shares its session id, is
[the conversation store](conversation-store.md).

**This records room audio to disk.** It is off by default and off until
`enabled` says otherwise, and a warning at startup plus one line per
recorded session say when it is on. Turn it off again once the
recording has been taken.

```yaml
server:
  capture:
    enabled: false
    dir: /data/captures
    # stop capturing a session after this long
    max_session_s: 900
    # budget for the directory, oldest captures pruned first
    max_total_mb: 2000
    # refuse to start a capture below this much free space
    min_free_mb: 1000
```

The flag is the switch, rather than the presence of the section, so
turning capture off again does not mean deleting the directory and the
budgets along with it: the field workflow is to record, then stop, and
the tuning is worth keeping across that. `dir` is required even while
disabled, so switching on is one word rather than one word and
remembering where it writes. A section that is present but off says so
once at startup, because a configured capture that records nothing is
otherwise a silence to debug.

Because it is one flag, the env layer can do the flip on its own:
`VINGA_SERVER__CAPTURE__ENABLED=true` turns it on for one run without
editing the config the deployment mounts, and dropping the variable
turns it off again. That is usually the least disruptive way to take a
field recording.

It exists because acoustic problems cannot be reproduced in any test
lane. The unit lane feeds synthetic frames and the integration lane
drives a simulator, and both bypass the microphone, the board's echo
cancellation, and the room. Whether a reply interrupts itself turns on
how much of the assistant's own voice survives the board's cancellation
and reaches the endpointer, and no test can tell you that number.

Three files per session, sharing one timeline, and a directory of
per-turn clips beside them:

| File | What it holds |
| --- | --- |
| `<session>.wav` | Stereo 16 kHz s16le. Channel 0 is the microphone as decoded, channel 1 is what was paced out to the speaker. |
| `<session>.jsonl` | Every structured event, plus a `t_ms` offset into the audio, plus dropped frames per second and the endpointer's opinion per frame. |
| `<session>.json` | What the capture was made against: server revision, the firmware the device reported, each agent's resolved providers by name, type, host and model (the four the conversation store keeps, so no option and no credential), and the barge-in thresholds. |
| `<session>.turns/` | Mono 16 kHz clips, two per turn: `<utterance>.heard.wav`, the exact audio the turn's transcription was handed, and `<utterance>.reply.wav`, what was paced out while that turn was answered. |

Stereo rather than two files is the whole point: sample N in both
channels is the same instant, so echo leakage is a measurement (cross
correlate the channels and read off gain and delay) rather than a
guess, and the overlap is directly audible in any audio editor. A
channel that goes quiet is filled with silence rather than compressed,
so nothing slides against the events.

The microphone is captured before the session's own guards, so the
frames a configuration discards (not listening, or `barge_in: false`
during a reply) are in the file anyway. Those are the frames that
explain a misfire.

Storage is 64 kB/s, so a fifteen minute session is about 58 MB of WAV;
the per-turn clips add about half as much again, so the 2000 MB budget
is around six hours of sessions. Whole captures are pruned oldest first,
with their clips, except a session still recording and the newest
finished one, and `capture_over_budget` says so when nothing more can
go; a capture that reaches `max_session_s` is cut there, with
`capture_limit`. Both bounds matter: the model caches share the volume
and grow underneath the budget, so capture declines to start and says
why rather than being the thing that fills the disk.

A capture cut off by a restart stays readable. The WAV header carries
byte counts that are only patched on a clean close, so a truncated file
claims zero length, but everything after the 44 byte header is raw
interleaved PCM and the manifest's `complete: false` says the length has
to come from the file size. Both files are flushed as they are written,
so what is lost is at most the last fraction of a second.

In the field: turn it on, hold sessions in the conditions that actually
break things, and say a marker phrase aloud when something goes wrong.
It is on the WAV, and the `heard` event beside it in the decision track
points at the interesting twenty seconds instead of ten minutes of
scrubbing; with the conversation store on and `text: true`, the phrase
itself is one query away, since both records carry the same session id.
Copy the session's files and its clip directory off after each session;
a field recording is not repeatable.

Nothing here leaves the host unless
[`server.telemetry.export_audio`](../reference/server-config.md#servertelemetry)
is on, in which case a closed session's recording, its manifest and its
clips are also uploaded beside its trace in the telemetry backend
([Exporting traces](logs-and-traces.md#exporting-traces)), staged under
the capture directory until the upload has finished with them.
