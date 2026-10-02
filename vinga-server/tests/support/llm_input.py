"""Telemetry seam used by LLM content unit tests."""

from typing import Any

import pytest

from tests.support.configs import POET_MAC, base_config
from tests.support.sessions import events_of, session_for
from tests.support.telemetry import open_session, start_turn
from vinga_server.config import Config
from vinga_server.device.session import DeviceSession
from vinga_server.events import SessionEvents
from vinga_server.providers.base import ToolCall, ToolDef, ToolResult, Turn
from vinga_server.telemetry import Telemetry

A_CONTEXT = "a-retained-context"

# An exception whose class name is not an identifier, so an event naming
# it as its error refuses to build: the emission is refused and nothing
# is dispatched to telemetry's fold.
Unnameable = type("not a class name", (Exception,), {})


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
        self.tool_snapshots: list[tuple[str, int, dict[str, Any]]] = []
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

    def stage_tool_content(
        self, session: str, invocation: str, position: int, attributes: dict[str, Any]
    ) -> bool:
        del session
        if self.accepts:
            self.tool_snapshots.append((invocation, position, dict(attributes)))
        return self.accepts

    def settle_tool_content(self, invocation: str, position: int) -> bool:
        """As though the fold always consumed what was staged."""
        return any(
            (staged, at) == (invocation, position)
            for staged, at, _ in self.tool_snapshots
        )


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


def traced(
    telemetry: Telemetry,
    llm: Any,
    llm_input: Any,
    config: Config | None = None,
) -> tuple[DeviceSession, SessionEvents]:
    """A real session for the one agent `llm` answers, its events tapped
    by a real exporter whose trace is open on a turn, so a reply driven
    through it hands its content over the production way."""
    session = session_for(
        base_config() if config is None else config,
        POET_MAC,
        {"poet": llm},
        llm_input=llm_input,
    )
    events = events_of(session)
    events.attach(telemetry.session_tap())
    open_session(events, providers={}, conversations=session.session_conversations)
    start_turn(events)
    return session, events


def outcomes(caplog: pytest.LogCaptureFixture) -> list[tuple[str, ...]]:
    """Both outcome events in order, as the fields that distinguish them."""
    return [
        (
            ("exported", record.rounds, record.tool_calls)
            if record.event == "llm_input_exported"
            else ("failed", record.kind, record.reason)
        )
        for record in caplog.records
        if getattr(record, "event", None)
        in {"llm_input_exported", "llm_input_export_failed"}
    ]
