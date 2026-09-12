### Changed

- **The audio export flag is now `server.telemetry.export_audio`**
  (#495, M1), renamed from `server.telemetry.attach_captures`. The
  telemetry section is a disclosure ladder and its content escalations
  now share one vocabulary: `enabled` sends metadata, `export_audio`
  sends a recording of a room, and each escalation means that if this
  content exists locally it leaves. Nothing about the flag's behavior
  moved: same default of off, same refusal with `server.telemetry.enabled`
  off, same refusal under `server.local_only`, same no-op with capture
  off. There is no alias and no shim, so a configuration file still
  spelling `attach_captures` is refused at boot by the section's
  unknown-key rule, which is what says the switch was renamed rather
  than quietly leaving the audio where it was.
