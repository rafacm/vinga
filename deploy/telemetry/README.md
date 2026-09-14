# Telemetry deployment add-ons

These Compose files add optional telemetry backends to the root trial stack.
They do not change the production deployment artifacts and do nothing unless
an operator composes one explicitly.

- `docker-compose.jaeger.yml` sends vinga directly to Jaeger over OTLP/HTTP
  protobuf and exposes the Jaeger UI on `127.0.0.1:16686`.
- `docker-compose.fanout.yml` sends vinga to the Collector, which masks and
  samples once before forwarding the same attempted trace population to
  Jaeger and Langfuse.
- `collector.yml` is the exact Collector graph used by the fanout deployment
  and its behavioral integration test.
- `.env.example` is copied to `.env` here for Collector-only Langfuse
  credentials. The root `.env` belongs to vinga and must not receive those
  names.

The images are immutable multi-platform pins. They were verified on
2026-09-14 against the upstream release APIs and published OCI indexes:
Jaeger `2.20.0` at
`sha256:46a886260e04002d8f45e213fc39063fa11a50446048fdaa64786fc0840cb9f8`
and Collector Contrib `0.160.0` at
`sha256:799dc6cf12c96192af37b5bdba804da8c10b3bc563b43cb90c3f3c58d9572ad6`.

The worked commands, privacy switches, sampling consequence and verification
procedure live in [the deployment guide](../../docs/deployment.md#telemetry-backends).
