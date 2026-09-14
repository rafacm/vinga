"""Telemetry seam used by LLM content unit tests."""

from typing import Any

from vinga_server.providers.base import ToolCall, ToolDef, ToolResult, Turn
from vinga_server.telemetry import Telemetry

A_CONTEXT = "a-retained-context"


class Exported:
    def __init__(
        self,
        contexts: dict[str, Any] | None = None,
        *,
        accepts: bool = True,
        **ignored: Any,
    ) -> None:
        del ignored
        self.contexts = dict(contexts or {})
        self.accepts = accepts
        self.snapshots: list[tuple[str, dict[str, Any]]] = []
        self.discarded: list[str] = []

    def stage_llm_content(
        self, session: str, invocation: str, attributes: dict[str, Any]
    ) -> bool:
        del session
        if self.accepts:
            self.snapshots.append((invocation, dict(attributes)))
        return self.accepts

    def discard_llm_content(self, invocation: str) -> None:
        self.discarded.append(invocation)


def exporting(
    contexts: dict[str, Any] | None = None, **answers: Any
) -> tuple[Telemetry, Exported]:
    held = Exported(contexts, **answers)
    return held, held  # type: ignore[return-value]


def a_turn(
    role: str = "user",
    content: str = "turn the light on",
    calls: "tuple[ToolCall, ...]" = (),
    results: "tuple[ToolResult, ...]" = (),
) -> Turn:
    return Turn(role=role, content=content, tool_calls=calls, tool_results=results)


def a_tool(name: str = "remember", description: str = "Remember a fact.") -> ToolDef:
    return ToolDef(
        name=name,
        description=description,
        input_schema={
            "type": "object",
            "properties": {"fact": {"type": "string"}},
            "required": ["fact"],
        },
    )
