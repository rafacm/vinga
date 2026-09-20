### Changed

- The test lanes' per-test cleanup now holds one database connection per worker process instead of opening and closing one for every test. The full unit suite drops from a 122.1 s median to about 114.5 s on a fourteen-core development machine, and the run makes roughly 7,400 fewer connections. What the cleanup does is unchanged: it still runs for every test in a lane that provisions storage, so nothing can write without being cleared afterwards.
