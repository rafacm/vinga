### Fixed

- **An exported transcript now hangs under the turn it describes**
  (#506). With `server.telemetry.export_transcripts` on, a closed
  session's turns went out as observations on the session's own trace,
  while the turn that spoke them was a separate, wordless trace: a
  reader got the stage timings on one trace and the dialogue on
  another, with no field on either naming the other. Each transcript is
  now a child of its turn's `turn` span, inside that turn's own trace,
  and carries `vinga.utterance.id` so a reader holding a stored row and
  a reader holding an observation name the same turn. A handover's two
  rows answer one utterance and therefore land under the one turn span.
  A turn the exporter can no longer address keeps the parent it had
  before, the session span: a row recorded before utterances existed,
  an utterance no turn span was opened for, and a turn evicted past the
  exporter's per-session turn retention. Every observation still
  carries the session under both spellings, so a saved query built on
  those keeps matching; one built on the transcripts sharing the
  session's trace id does not.
