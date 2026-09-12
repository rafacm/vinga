### Changed

- The fully-local product promise is now an enumerated baseline (a
  complete conversation from wake through reply, end-of-turn
  detection, interruption that stops the reply promptly enough to
  converse, agent memory, tool use) instead of the open-ended "every
  core conversational capability". Quality and latency may differ by
  provider and runtime, runtime-specific capabilities above the
  baseline are explicitly allowed, and the list changes only by
  recorded decision; every plan and feature doc now carries a
  "Local baseline" line stating its consequence. The reasoning is
  recorded in `docs/adr/2026-09-12-the-local-baseline-is-enumerated.md`.
