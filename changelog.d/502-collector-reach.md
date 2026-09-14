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
  means the outermost of them.** The traces and the exported
  transcripts ride `OTEL_EXPORTER_OTLP_*` and the recording upload
  rides `LANGFUSE_HOST`, so a collector on your own network beside a
  media host at a vendor is `internet`, and all three features are
  refused rather than the one that would have been caught. It is an
  assertion and not a proof: nothing here reads either endpoint, so a
  deployment that declares `network` and points the endpoint at a
  vendor has contradicted its own configuration and this server cannot
  tell. The refusal names the key the reach came from, beside the
  switch, the reach and the boundary, and still carries no endpoint, no
  host and no credential.
