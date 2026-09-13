### Added

- **A stored turn now says which utterance it answers** (#502, M4a).
  The server mints an id when a turn opens, puts it on `turn_started`
  and on the turn's span as `vinga.utterance.id`, and writes it on
  every row that turn records. It is what lets a reader holding a
  stored turn find the trace that turn went out under, which nothing
  could do before: the two sides count turns differently, and neither
  their ordinals nor their millisecond offsets line up. A reply that
  hands over is recorded as two turns on two threads and both carry
  the same id, because both answer one utterance.
- **The `record.turns` table gains an `utterance` column**, added by
  migration `1010_turns_name_their_utterance` and served on the turn
  reads of `/api`. The column is nullable and nothing is backfilled,
  because there is nothing honest to backfill with: a turn recorded
  before this release never had an id, and any value written
  afterwards would be invented. An existing database upgrades and
  keeps every row; what those rows cannot do is name their trace, so
  an artifact belonging to a turn recorded before the upgrade is
  reported unattached rather than filed against a guess. That is the
  same answer the correlation already gives for a trace that has aged
  out of the exporter's retention, so it adds no new state to a reader
  and no branch to the code.
