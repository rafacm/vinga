"""The optional Jaeger and processed-fanout deployment graphs.

These artifacts are an executable boundary contract, not examples whose
shape may drift. The common Collector pipeline makes the only masking and
sampling decisions, then forward connectors hand the same records to two
backend adapters. The tests read that graph as committed so a second sampler,
a missed content alias, or a credential mounted into vinga fails locally.
"""

import re
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[3]
TELEMETRY = REPO / "deploy" / "telemetry"
COLLECTOR_PATH = TELEMETRY / "collector.yml"
DIRECT_PATH = TELEMETRY / "docker-compose.jaeger.yml"
FANOUT_PATH = TELEMETRY / "docker-compose.fanout.yml"

JAEGER_IMAGE = (
    "jaegertracing/jaeger:2.20.0@"
    "sha256:46a886260e04002d8f45e213fc39063fa11a50446048fdaa64786fc0840cb9f8"
)
COLLECTOR_IMAGE = (
    "otel/opentelemetry-collector-contrib:0.160.0@"
    "sha256:799dc6cf12c96192af37b5bdba804da8c10b3bc563b43cb90c3f3c58d9572ad6"
)

CONTENT_ATTRIBUTES = {
    "vinga.turn.input",
    "vinga.turn.output",
    "vinga.turn.legs",
    "gen_ai.system_instructions",
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "vinga.llm.tools",
    "vinga.llm.tool_choice",
    "langfuse.observation.input",
    "langfuse.observation.output",
    "langfuse.observation.metadata.legs",
}
LANGFUSE_ENV = {
    "LANGFUSE_OTLP_ENDPOINT",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
}


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _collector() -> dict[str, Any]:
    return _load(COLLECTOR_PATH)


def _services(path: Path) -> dict[str, Any]:
    return _load(path)["services"]


def test_images_are_versioned_and_immutable() -> None:
    direct = _services(DIRECT_PATH)
    fanout = _services(FANOUT_PATH)

    assert direct["jaeger"]["image"] == JAEGER_IMAGE
    assert fanout["jaeger"]["image"] == JAEGER_IMAGE
    assert fanout["otel-collector"]["image"] == COLLECTOR_IMAGE


def test_the_common_pipeline_owns_policy_before_both_forwards() -> None:
    config = _collector()
    pipelines = config["service"]["pipelines"]
    common = pipelines["traces/common"]

    assert common["processors"] == [
        "transform/content-mask",
        "probabilistic_sampler",
        "batch",
    ]
    assert common["exporters"] == ["forward/jaeger", "forward/langfuse"]
    assert pipelines["traces/jaeger"]["receivers"] == ["forward/jaeger"]
    assert pipelines["traces/langfuse"]["receivers"] == ["forward/langfuse"]

    used = [
        processor
        for pipeline in pipelines.values()
        for processor in pipeline.get("processors", [])
    ]
    assert used.count("probabilistic_sampler") == 1
    assert used.count("transform/content-mask") == 1
    for sink in ("traces/jaeger", "traces/langfuse"):
        assert "probabilistic_sampler" not in pipelines[sink].get("processors", [])
        assert "transform/content-mask" not in pipelines[sink].get("processors", [])


def test_the_common_mask_names_every_content_field_and_alias() -> None:
    mask = _collector()["processors"]["transform/content-mask"]
    statements = mask["trace_statements"][0]["statements"]
    named = {
        match.group(1)
        for statement in statements
        if (match := re.search(r'attributes\["([^"]+)"\]', statement))
    }

    assert named == CONTENT_ATTRIBUTES
    assert all("replace_pattern" in statement for statement in statements)
    assert all('"[email]"' in statement for statement in statements)


def test_backend_adaptation_is_confined_to_the_sinks() -> None:
    config = _collector()
    processors = config["processors"]
    exporters = config["exporters"]
    pipelines = config["service"]["pipelines"]

    jaeger = pipelines["traces/jaeger"]
    assert jaeger["processors"] == ["filter/jaeger", "transform/jaeger"]
    assert processors["filter/jaeger"]["traces"]["span"] == ['name == "capture"']
    assert "^langfuse" in processors["transform/jaeger"]["trace_statements"][0][
        "statements"
    ][0]

    langfuse = pipelines["traces/langfuse"]
    assert langfuse["processors"] == []
    assert exporters["otlphttp/langfuse"]["auth"] == {
        "authenticator": "basicauth/langfuse"
    }
    assert exporters["otlphttp/langfuse"]["headers"] == {
        "x-langfuse-ingestion-version": "4"
    }
    assert "auth" not in exporters["otlphttp/jaeger"]
    assert "headers" not in exporters["otlphttp/jaeger"]


def test_only_the_collector_receives_langfuse_credentials() -> None:
    services = _services(FANOUT_PATH)
    collector = services["otel-collector"]
    vinga = services["vinga"]

    assert collector["env_file"] == [
        {"path": "./deploy/telemetry/.env", "required": True}
    ]
    assert not (set(vinga.get("environment", {})) & LANGFUSE_ENV)
    assert "env_file" not in vinga
    assert "deploy/telemetry/.env" in (REPO / ".gitignore").read_text(
        encoding="utf-8"
    )

    template_names = {
        line.split("=", 1)[0]
        for line in (TELEMETRY / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    assert template_names == LANGFUSE_ENV


def test_vinga_is_always_on_in_both_runnable_paths() -> None:
    for path in (DIRECT_PATH, FANOUT_PATH):
        environment = _services(path)["vinga"]["environment"]
        assert environment["OTEL_TRACES_SAMPLER"] == "always_on"
        assert environment["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/protobuf"
        assert environment["VINGA_SERVER__TELEMETRY__ENABLED"] == "true"

    direct = _services(DIRECT_PATH)["vinga"]["environment"]
    fanout = _services(FANOUT_PATH)["vinga"]["environment"]
    assert direct["VINGA_SERVER__TELEMETRY__REACH"] == "network"
    assert fanout["VINGA_SERVER__TELEMETRY__REACH"] == "internet"
    assert _services(FANOUT_PATH)["otel-collector"]["environment"][
        "TELEMETRY_SAMPLE_PERCENTAGE"
    ] == "100"
