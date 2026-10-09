### Added

- **vinga, the built-in agent, can look things up.** It alone is
  offered `search_docs`, a search over the concepts page, the glossary
  and the device guides packaged with the build, for what its prompt
  (the board's facts and the concept summary) does not answer, and it
  is told to search before it says it does not know. While it
  searches, its filler, when its `builtin_agent.filler` section is on,
  says one of its phrases at once. How often it searches depends on
  the model: on 2026-10-09, with the same 32 questions,
  `claude-sonnet-5` searched on 13 of the 15 that needed it and
  answered 78% correctly, and Gemma 4 e4b, the local preset's model,
  on 5 of 15 and 50%, missing the 70% it was measured against; on a
  Raspberry Pi 5 the round after a search took longer to start than
  the server waits, so such a turn is expected to be given up with the
  fallback phrase (inferred from a model harness, not observed in a
  running server). `docs/run/llm.md` has the measurements.
  Upgrade: an `mcp_servers` entry named `search_docs` is now refused
  when the configuration is read, since a builtin tool's name is
  reserved; rename the entry.

### Changed

- **A board vinga does not know sends its questions to the lookup.**
  Where the server has not heard which board a device is, vinga now
  searches the common device guide for a question about the device and
  says so when the guide does not cover it, rather than pointing the
  person to a guide; it still never guesses which board it is.
