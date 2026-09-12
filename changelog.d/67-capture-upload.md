### Added

- **A closed session's recording can be attached to the trace it was
  exported under** (#67, M3). Behind `server.telemetry.attach_captures`,
  which defaults off and which neither `server.capture` nor
  `server.telemetry.enabled` implies: this sends room audio off the
  host, and that is its own decision. What goes is exactly two files,
  the session's stereo WAV and its JSON manifest; the decision track
  beside them never leaves. With capture off it is a no-op and says so
  once at startup, under `server.local_only` it is refused, and without
  the new `langfuse` extra the boot is refused with the command to type.
  Both published images carry the extra. The upload runs on a worker of
  its own after the session closed, never on the audio path, with a
  30 s request timeout and two retries, and every failure is a warning
  event rather than a failed session. A recording waiting for that
  worker is hard-linked into `upload-staging/` under the capture
  directory, where the capture budget cannot see it; the queue depth
  bounds it, and the next startup sweeps and reports whatever a
  previous run left behind. Retention is then the receiving
  deployment's, which is the seventh surface on the observability map
  and an amendment to the content-and-telemetry ADR. Once both files
  are up, a reference to each is written back onto the session's trace,
  which is what makes the recording playable where the trace is read
  rather than merely stored beside it.
- **Two events say whether a recording reached its trace**, so a
  capture that silently failed to attach cannot leave a reader with a
  trace, no audio and no way to learn any was meant to be there.
  `capture_uploaded` carries the two sizes and how long it took, and
  never a URL or an identifier the far side minted; `capture_upload_failed`
  carries a reason from a closed set of eight, and never the far side's
  words.
