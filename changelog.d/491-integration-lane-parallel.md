### Changed

- **The CI integration lane runs in parallel too** (#491). The
  workflow's integration step gained ` -n auto --dist loadfile`, the
  same two tokens the unit step has carried since #254, so there is now
  one way this repository runs a pytest lane in CI. The integration
  lane was the one nobody had ever distributed, and it had quietly
  become the critical path: measured from the GitHub API at `c999d0dc`,
  job start to job completion, the three runs before this change were
  10m57s, 10m56s and 10m36s of integration against 8m43s, 8m58s and
  8m57s of unit. Locally, on a 14-core machine at the same commit, the
  lane goes from 495.34s serial to 130.66s at four workers (CI's runner
  width) and 92.36s at fourteen, with the same 346 tests passing at
  every width. CI wall time is the longer of the two lanes, so the
  honest saving is the roughly two minutes by which integration
  exceeded unit; the seven and a half minutes of runner time it stops
  burning is the larger number and the one that buys nothing on the
  clock. `loadfile` keeps a whole file on one worker, so the expensive
  module-scoped fixtures (the six throwaway installs in
  `test_tier_closure.py`, the wheel build and installed environment in
  `test_cli_wheel.py`) are still paid once per file and intra-file
  order is exactly what it was. No test changed, and local runs are
  unchanged and serial:
  `uv run pytest tests/integration -q -n auto --dist loadfile` joins
  the unit spelling in both command blocks as the way to reproduce the
  lane. The workflow's two comments that still described this as the
  shorter lane, and gave that as the reason the drift checks and the
  wheel migration ride on it, are corrected.
