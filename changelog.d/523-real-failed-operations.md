### Added

- Trace successful and failed recap model calls as `llm` operations without changing reply-round accounting.

### Changed

- Give every logical generation a server-owned correlation id, preserve retained OpenTelemetry sampling state, and represent failed ASR, LLM, TTS and tool work as real error spans with safe `error.type` metadata.
