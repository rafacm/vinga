### Added

- Attach acknowledged conversation text and per-agent handover legs to the original `turn` root, and attach complete model input and raw generated output to each actual `llm` span when the corresponding off-by-default content flag is enabled.

### Changed

- Widen `server.telemetry.export_llm_input` to disclose generated model output, including text withheld from speech, and limit each turn or generation content projection to 256 KiB.
- Treat `transcripts_exported` and `llm_input_exported` as attachment and normal OTLP enqueue outcomes rather than backend acknowledgements. Ordinary telemetry exporter health now owns downstream delivery.
- Keep direct-to-Langfuse rendering through aliases derived from the canonical turn and GenAI content attributes. Saved views that select the old `transcript` or `llm_input` span names must select `turn` or `llm` instead.

### Removed

- Remove the separate `transcript` and `llm_input` spans, their private exact-delivery transport, the `undelivered` outcome, transcript row index, database id and relative-time attributes, and the session-parent fallback for unaddressable transcript rows. Per-agent attribution remains on `vinga.turn.legs`.
