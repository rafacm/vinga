### Fixed

- **An explicitly empty `--device` no longer reads as no filter** on
  `session list`, `session purge` and `events tail` (#473). An unset
  variable expanding to nothing is the ordinary way to write one, and
  the value used to be dropped before the request left, so the narrowest
  question each flag can ask answered as the widest one: every board's
  sessions, and the whole server's traffic. The value now travels, empty
  included, and meets the API's own MAC refusal. On the purge the
  direction matters most, and it is the one this change also covers
  beyond the report: `session purge --device '' --before DAY` dropped the
  device selector and erased that day from every board rather than from
  the one named, with no undo.
