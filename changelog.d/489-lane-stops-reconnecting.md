### Changed

- The test lanes' per-test cleanup now holds one database connection per worker process instead of opening and closing one for every test. Measured on a fourteen-core development machine: the full unit suite drops from a 122.1 s median to about 114 s, and the run opens 5,552 connections where it used to open 13,067, which is 0.75 per test rather than 1.76. What the cleanup does is unchanged: it still runs for every test in a lane that provisions storage, so nothing can write without being cleared afterwards.
