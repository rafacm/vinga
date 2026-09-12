### Added

- **A closed session's turns can be exported to the telemetry backend**
  (#495, M2), behind `server.telemetry.export_transcripts`, which is off
  by default. With it on, each closed session's trace gains one
  observation per recorded turn carrying what was heard and what was
  replied, with per-agent attribution where a handover split the reply,
  read post hoc from the conversation store rather than from the live
  pipeline. It is the third rung of the telemetry section's disclosure
  ladder: `enabled` sends metadata, `export_audio` sends a recording of
  a room, and this sends what was said, each its own decision and none
  of them implied by the one above it. Two boundaries an operator has to
  know before switching it on, and the flag's own description says both:
  **exported text outlives erasure here**, so deleting a session or a
  conversation on this side reaches nothing that already left, and
  retention is then the backend's, which retains indefinitely unless it
  was configured; and **telemetry being on and conversation text being
  stored do not imply that the text leaves.** Conversation-level text
  exactly: the assembled model request, the tool arguments and results
  and the per-request audio never go. It needs no extra and no second
  credential, because the turns travel as spans over the
  `OTEL_EXPORTER_OTLP_*` transport the traces already use. With
  `server.conversations` absent, off, or storing no text it is a no-op
  said once at startup; with `server.telemetry.enabled` off the boot is
  refused; under `server.local_only` it is refused. The export runs on a
  worker of its own after the session closed, never on the audio path,
  and every outcome is an event: `transcripts_exported` with how many
  turns went and how long it took, or `transcript_export_failed` with a
  reason from a closed set of five (`unrecorded`, `unreadable`,
  `no_trace`, `undelivered`, `dropped`).
