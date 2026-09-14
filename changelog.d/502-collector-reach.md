### Added

- **A deployment can now say where its telemetry collector is** (#502,
  M4b). `server.telemetry.reach` takes the same `host`, `network` and
  `internet` vocabulary a provider and an MCP entry declare in, and it
  is the reach the data boundary weighs the three exporting features
  against: tracing, the transcript export and the recording upload. A
  server with `data_boundary: network` and a collector on that network
  can now export by saying so, which it could not before: the three
  features passed a fixed `internet`, because nothing here reads
  `OTEL_EXPORTER_OTLP_ENDPOINT` or `LANGFUSE_HOST`, so a LAN collector
  was refused exactly as a vendor was.
- **Leaving it out means `internet`, which is exactly today's
  behaviour.** A configuration that upgrades into this release and does
  not write the key is admitted and refused in precisely the cases it
  was before: the key widens what a boundary allows, and never narrows
  it.
- **One assertion covers every destination the section sends to, and it
  means the outermost of them.** There are three: the traces and the
  exported transcripts ride `OTEL_EXPORTER_OTLP_*`; the recording
  upload's REST calls go to `LANGFUSE_HOST`; and the recording's bytes
  go to the presigned upload URL that host answers with, which is
  whatever object storage your backend is configured with. Any one of
  the three outside your network makes the honest answer `internet`,
  and all three features are then refused rather than the one that
  would have been caught. **So a LAN collector and a LAN Langfuse are
  not enough to declare `network`**, unless that Langfuse's object
  storage stays on your network too; if you cannot say where your
  backend stores media, you have not got a `network` deployment to
  declare.
- **It is an assertion and not a proof**, and the third destination is
  why that is not a formality: nothing here reads the OTLP endpoint or
  the Langfuse host, and the upload target does not exist until the
  backend names it, one request before the bytes go. A deployment that
  declares `network` and then points the endpoint at a vendor, or runs
  a LAN Langfuse backed by cloud object storage, has contradicted its
  own configuration and this server cannot tell. The refusal names the
  key the reach came from, beside the switch, the reach and the
  boundary, and still carries no endpoint, no host and no credential.
