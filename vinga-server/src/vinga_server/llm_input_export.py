"""Bounded, opt-in GenAI content attached to its generation."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from vinga_server.boundary import BoundaryRefusal, Reach, check_feature
from vinga_server.config import ConfigError
from vinga_server.config.models import ServerConfig
from vinga_server.events import ServerEvents
from vinga_server.events.catalog import LlmInputExported, LlmInputExportFailed
from vinga_server.events.values import (
    Count,
    LlmInputExportFailure,
    LlmPurpose,
    SessionId,
    Whole,
)
from vinga_server.providers.base import TextDelta, ToolCall, ToolDef, ToolResult, Turn
from vinga_server.telemetry import (
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_SYSTEM_INSTRUCTIONS,
    LLM_TOOL_CHOICE,
    LLM_TOOLS,
    OBSERVATION_INPUT,
    OBSERVATION_OUTPUT,
    Telemetry,
)

logger = logging.getLogger(__name__)
events = ServerEvents(__name__)

LLM_INPUT_KEY = "server.telemetry.export_llm_input"
REPLY = LlmPurpose.REPLY
RECAP = LlmPurpose.RECAP
MAX_CONTENT_BYTES = 256 * 1024
MAX_REQUEST_BYTES = MAX_CONTENT_BYTES
SESSION_BUDGET_BYTES = 4 * MAX_CONTENT_BYTES
MAX_STAGED_ROUNDS = 64

LLM_INPUT_NEEDS_TELEMETRY = (
    "telemetry.export_llm_input is on with telemetry.enabled off; assembled model "
    "content is attached to a trace this server exported, and there is no trace "
    "to attach it to, so switch telemetry.enabled on or telemetry.export_llm_input off"
)
LLM_INPUT_NEEDS_AN_EXPORTER = (
    f"{LLM_INPUT_KEY} is on and no exporter was built, so no generation span can "
    "receive model content; switch server.telemetry.enabled on"
)


def build_llm_input_export(
    config: ServerConfig,
    *,
    telemetry: Telemetry | None,
    boundary: Reach | None = None,
    max_request_bytes: int = MAX_CONTENT_BYTES,
    session_budget_bytes: int = SESSION_BUDGET_BYTES,
    max_rounds: int = MAX_STAGED_ROUNDS,
    shutdown_timeout_s: float = 5.0,
) -> "LlmInputExport | None":
    """Build the collaborator only after its flag and policy checks."""
    del shutdown_timeout_s
    section = config.telemetry
    if section is None or not section.export_llm_input:
        return None
    if not section.enabled:
        raise ConfigError(LLM_INPUT_NEEDS_TELEMETRY)
    if telemetry is None:
        raise ConfigError(LLM_INPUT_NEEDS_AN_EXPORTER)
    try:
        check_feature(LLM_INPUT_KEY, section.reach, boundary)
    except BoundaryRefusal as refusal:
        raise ConfigError(str(refusal)) from None
    return LlmInputExport(
        telemetry=telemetry,
        backlog=config.limits.max_sessions,
        max_request_bytes=max_request_bytes,
        session_budget_bytes=session_budget_bytes,
        max_rounds=max_rounds,
    )


@dataclass
class _Round:
    session: str
    invocation: str
    attributes: dict[str, str]
    size: int
    text: list[str] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)


class LlmInputExport:
    """Pair one neutral request and response before its event fold."""

    def __init__(
        self,
        *,
        telemetry: Telemetry,
        backlog: int,
        max_request_bytes: int = MAX_CONTENT_BYTES,
        session_budget_bytes: int = SESSION_BUDGET_BYTES,
        max_rounds: int = MAX_STAGED_ROUNDS,
        shutdown_timeout_s: float = 5.0,
    ) -> None:
        del backlog, shutdown_timeout_s
        self._telemetry = telemetry
        self._max_content_bytes = max(1, max_request_bytes)
        self._session_budget_bytes = max(1, session_budget_bytes)
        self._max_rounds = max(1, max_rounds)
        self._rounds: dict[str, _Round] = {}
        self._sessions: dict[str, list[str]] = {}
        self._held: dict[str, int] = {}

    def stage_reply(
        self,
        session: str,
        *,
        invocation: str,
        agent: str | None,
        system: str,
        turns: list[Turn],
        tools: list[ToolDef],
        choice: str,
    ) -> None:
        del agent
        self._stage(session, invocation, system, turns, tools, choice)

    def stage_recap(
        self,
        session: str,
        *,
        invocation: str,
        agent: str | None,
        system: str,
        turns: list[Turn],
        tools: list[ToolDef],
        choice: str,
    ) -> None:
        del agent
        self._stage(session, invocation, system, turns, tools, choice)

    def _stage(
        self,
        session: str,
        invocation: str,
        system: str,
        turns: list[Turn],
        tools: list[ToolDef],
        choice: str,
    ) -> None:
        try:
            system_json = _json([{"type": "text", "content": system}])
            input_json = _json([_message(turn) for turn in turns])
            tools_json = _json([_tool(tool) for tool in tools])
            attributes = {
                GEN_AI_SYSTEM_INSTRUCTIONS: system_json,
                GEN_AI_INPUT_MESSAGES: input_json,
                LLM_TOOLS: tools_json,
                LLM_TOOL_CHOICE: choice,
                OBSERVATION_INPUT: input_json,
            }
            size = _size(attributes)
        except Exception:  # noqa: BLE001 - content export never breaks a reply
            self._failed(session, LlmInputExportFailure.DROPPED)
            return
        if size > self._max_content_bytes:
            self._failed(session, LlmInputExportFailure.DROPPED)
            return
        staged = _Round(session, invocation, attributes, size)
        self._rounds[invocation] = staged
        ordered = self._sessions.setdefault(session, [])
        ordered.append(invocation)
        self._held[session] = self._held.get(session, 0) + size
        while ordered and (
            self._held[session] > self._session_budget_bytes
            or len(ordered) > self._max_rounds
        ):
            self._drop(ordered[0])

    def observe(self, invocation: str, event: object) -> None:
        """Admit raw semantic output before speech filtering or splitting."""
        staged = self._rounds.get(invocation)
        if staged is None:
            return
        if isinstance(event, TextDelta):
            staged.text.append(event.text)
        elif isinstance(event, ToolCall):
            staged.calls.append(event)
        else:
            return
        try:
            output = _output(staged.text, staged.calls)
            total = staged.size + len(output.encode("utf-8"))
        except Exception:  # noqa: BLE001 - content export never breaks a reply
            self._drop(invocation)
            return
        if total > self._max_content_bytes:
            self._drop(invocation)

    def finish(self, invocation: str) -> None:
        """Stage the complete pair before the matching event is emitted."""
        staged = self._rounds.pop(invocation, None)
        if staged is None:
            return
        self._remove(staged)
        try:
            output = _output(staged.text, staged.calls)
            attributes = {
                **staged.attributes,
                GEN_AI_OUTPUT_MESSAGES: output,
                OBSERVATION_OUTPUT: output,
            }
            if _size(attributes) > self._max_content_bytes:
                self._failed(staged.session, LlmInputExportFailure.DROPPED)
                return
        except Exception:  # noqa: BLE001 - content export never breaks a reply
            self._failed(staged.session, LlmInputExportFailure.DROPPED)
            return
        if not self._telemetry.stage_llm_content(
            staged.session, invocation, attributes
        ):
            self._failed(staged.session, LlmInputExportFailure.DROPPED)
            return
        events.emit(
            lambda: LlmInputExported(
                session=SessionId(staged.session),
                rounds=Count(1),
                elapsed_ms=Whole(0),
                oversized=Count(0),
                over_budget=Count(0),
                unrenderable=Count(0),
            )
        )

    def session_closed(self, session: str) -> None:
        for invocation in tuple(self._sessions.get(session, ())):
            self._drop(invocation)

    async def shutdown(self) -> None:
        for session in tuple(self._sessions):
            self.session_closed(session)

    def _drop(self, invocation: str) -> None:
        staged = self._rounds.pop(invocation, None)
        if staged is None:
            return
        self._remove(staged)
        self._telemetry.discard_llm_content(invocation)
        self._failed(staged.session, LlmInputExportFailure.DROPPED)

    def _remove(self, staged: _Round) -> None:
        ordered = self._sessions.get(staged.session)
        if ordered is not None:
            if staged.invocation in ordered:
                ordered.remove(staged.invocation)
            if not ordered:
                self._sessions.pop(staged.session, None)
        held = max(0, self._held.get(staged.session, 0) - staged.size)
        if held:
            self._held[staged.session] = held
        else:
            self._held.pop(staged.session, None)

    def _failed(self, session: str, reason: LlmInputExportFailure) -> None:
        events.emit(lambda: LlmInputExportFailed(session=SessionId(session), reason=reason))


def _json(value: Any) -> str:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        encoded.encode("utf-8")
        return encoded
    except UnicodeEncodeError:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str
        )


def _size(attributes: dict[str, str]) -> int:
    return sum(len(value.encode("utf-8")) for value in attributes.values())


def _message(turn: Turn) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    if turn.content:
        parts.append({"type": "text", "content": turn.content})
    parts.extend(_call(call) for call in turn.tool_calls)
    parts.extend(_result(result) for result in turn.tool_results)
    return {"role": turn.role, "parts": parts}


def _output(text: list[str], calls: list[ToolCall]) -> str:
    parts: list[dict[str, Any]] = []
    generated = "".join(text)
    if generated:
        parts.append({"type": "text", "content": generated})
    parts.extend(_call(call) for call in calls)
    return _json([{"role": "assistant", "parts": parts}])


def _call(call: ToolCall) -> dict[str, Any]:
    return {
        "type": "tool_call",
        "id": call.id,
        "name": call.name,
        "arguments": call.arguments,
    }


def _result(result: ToolResult) -> dict[str, Any]:
    return {
        "type": "tool_call_response",
        "id": result.tool_call_id,
        "response": result.content,
        "is_error": result.is_error,
    }


def _tool(tool: ToolDef) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }
