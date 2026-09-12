### Added

- **A closed session can still be named by the trace it was exported
  under** (#67, M2). The exporter records each session's trace id when
  its span opens and keeps it past the close that pops the span,
  bounded at the last 64 sessions and evicted oldest first, with
  `Telemetry.trace_of(session)` the whole of the surface. Nothing about
  a running server changes; what it unlocks is the attachment the next
  milestone builds, which can only ask its question after a session
  closed, because a recording's WAV and manifest are only final then.
  The id is spelled the way the wire spells it, which is the spelling
  Langfuse's media API takes back: a live walkthrough established that
  in the milestone before this one, along with the fact that there is
  no attach-by-session-id path at all, so a trace id is the only
  correlation there is to keep. A session the exporter never saw, or
  one that has aged out of the retention, answers nothing rather than
  an invented id.
