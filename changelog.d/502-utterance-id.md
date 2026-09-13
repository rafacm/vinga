### Changed

- **A stored turn now says which utterance it answers** (#502, M4a).
  The server mints an id when a turn opens, puts it on `turn_started`
  and on the turn's span as `vinga.utterance.id`, and writes it on
  every row that turn records. It is what lets a reader holding a
  stored turn find the trace that turn went out under, which nothing
  could do before: the two sides count turns differently and neither
  their ordinals nor their millisecond offsets line up. A reply that
  hands over is recorded as two turns on two threads and both carry the
  same id, because both answer one utterance.
- **The `record.turns` table gains an `utterance` column**, added by
  migration `1010_turns_name_their_utterance`, and it is served on the
  turn reads of `/api`. **An existing conversations database is not
  carried across this release.** The column is nullable and nothing is
  backfilled, because there is nothing to backfill with: a turn already
  recorded never had an id, and any value written afterwards would be
  invented. A deployment that keeps its database will find every turn
  recorded before the upgrade reading `null` there, and artifacts
  belonging to those turns cannot be correlated to their traces.
