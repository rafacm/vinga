### Changed

- **A per-device metrics row says what the board was called** (#474).
  The `name` column of the four `metrics_*_by_device_daily` views was
  the literal null in every row; it now reads `sessions.device_name`,
  the label the session recorded when it opened, so an analyst who
  cannot join the configuration (the read-only role is revoked on
  `domain`) no longer has only a MAC to go on. The name is part of what
  makes a row one row: because the recorded name is dated and never
  rewritten, a board renamed inside a window comes back as one row per
  name it was recorded under rather than one series retitled by
  whichever label is latest, and a reader who wants the board whole
  groups on `device`, which survives the rename. The column stays
  nullable and a null is still a group of its own, which is what every
  session recorded before the column existed, and every board nobody
  named, comes back as. Migration `1009_views_read_the_name` replaces
  the four views in place, so nothing standing on them is dropped, and
  no other surface changes shape: `name` was always in the row contract.
