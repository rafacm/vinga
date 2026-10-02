"""Bounded, opt-in GenAI content attached to its generation or tool span."""

import json
import logging
from collections.abc import Callable, Mapping, Sequence
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
    LlmInputExportKind,
    LlmPurpose,
    SessionId,
)
from vinga_server.providers.base import TextDelta, ToolCall, ToolDef, ToolResult, Turn
from vinga_server.telemetry import (
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_SYSTEM_INSTRUCTIONS,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_RESULT,
    LLM_TOOL_CHOICE,
    LLM_TOOLS,
    Telemetry,
)

logger = logging.getLogger(__name__)
events = ServerEvents(__name__)

LLM_INPUT_KEY = "server.telemetry.export_llm_input"
REPLY = LlmPurpose.REPLY
RECAP = LlmPurpose.RECAP
GENERATION = LlmInputExportKind.GENERATION
TOOL_CALL = LlmInputExportKind.TOOL_CALL
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
) -> "LlmInputExport | None":
    """Build the collaborator only after its flag and policy checks."""
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
    output_size: int = 0
    text: list[str] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)


class LlmInputExport:
    """Pair one neutral request and response before its event fold."""

    def __init__(
        self,
        *,
        telemetry: Telemetry,
        max_request_bytes: int = MAX_CONTENT_BYTES,
        session_budget_bytes: int = SESSION_BUDGET_BYTES,
        max_rounds: int = MAX_STAGED_ROUNDS,
    ) -> None:
        self._telemetry = telemetry
        self._max_content_bytes = max(1, max_request_bytes)
        self._session_budget_bytes = max(1, session_budget_bytes)
        self._max_rounds = max(1, max_rounds)
        self._rounds: dict[str, _Round] = {}
        self._sessions: dict[str, list[str]] = {}
        self._held: dict[str, int] = {}
        # Per session, the round whose tool pairs are being admitted and
        # the bytes admitted for it so far. One entry rather than one
        # per round: a session's rounds run one after another, and a
        # round's calls all finish before the next round is asked, so a
        # pair for a new invocation means the previous round is over.
        self._tool_round: dict[str, tuple[str, int]] = {}

    def stage_reply(
        self,
        session: str,
        *,
        invocation: str,
        agent: str | None,
        system: str,
        turns: list[Turn],
        tools: Sequence[ToolDef],
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
        tools: Sequence[ToolDef],
        choice: str,
    ) -> None:
        if invocation in self._rounds:
            self._failed(session, GENERATION, LlmInputExportFailure.DROPPED)
            return
        try:
            system_json = _json([{"type": "text", "content": system}])
            input_json = _json([_message(turn) for turn in turns])
            tools_json = _json([_tool(tool) for tool in tools])
            attributes = {
                GEN_AI_SYSTEM_INSTRUCTIONS: system_json,
                GEN_AI_INPUT_MESSAGES: input_json,
                LLM_TOOLS: tools_json,
                LLM_TOOL_CHOICE: choice,
            }
            size = _size(attributes)
        except Exception:  # noqa: BLE001 - content export never breaks a reply
            self._failed(session, GENERATION, LlmInputExportFailure.DROPPED)
            return
        if size > self._max_content_bytes:
            self._failed(session, GENERATION, LlmInputExportFailure.DROPPED)
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
        try:
            if isinstance(event, TextDelta):
                added = _utf8_size(event.text)
            elif isinstance(event, ToolCall):
                added = _utf8_size(_json(_call(event)))
            else:
                return
        except Exception:  # noqa: BLE001 - content export never breaks a reply
            self._drop(invocation)
            return
        # The output is written once, under the conventions' key: no alias
        # repeats it, so each delta is charged once. The raw bytes are a
        # lower bound on the rendered JSON, which only adds framing and
        # escapes, so this never drops a pair `finish` would admit; it keeps
        # a long stream O(n), and `finish` weighs the one authoritative value.
        if staged.size + staged.output_size + added > self._max_content_bytes:
            self._drop(invocation)
            return
        staged.output_size += added
        if isinstance(event, TextDelta):
            staged.text.append(event.text)
        else:
            staged.calls.append(event)

    def finish(self, invocation: str, emit: Callable[[], object]) -> None:
        """Hand a round's complete pair to the `llm_round` or
        `provider_failed` event `emit` says.

        The tool path's contract (`stage_tool`), for a generation: the
        pair is completed and staged, `emit` is called exactly once
        whatever happens to the pair, and the handoff is then settled.
        The event folds synchronously, so by the time `emit` returns its
        `llm` span has taken the pair or never will. Only a pair the
        fold wrote onto the span is counted in `rounds`; one the
        emission never delivered (a refused construction) is discarded
        there and then and reported, so no slot waits for shutdown and
        no count claims an attachment that did not happen (#588).

        Called once per logical round, by whichever event closes it: a
        first-token retry re-sends the round under the same invocation
        and finishes nothing, so it stays one round.
        """
        session = self._finish(invocation)
        emit()
        if session is None:
            return
        self._settled(session, GENERATION, self._telemetry.settle_llm_content(invocation))

    def _finish(self, invocation: str) -> str | None:
        """Complete, bound and stage one round's pair, answering its
        session once it is staged, or None where there was none or it
        was dropped and already reported."""
        staged = self._rounds.pop(invocation, None)
        if staged is None:
            return None
        self._remove(staged)
        try:
            output = _output(staged.text, staged.calls)
            attributes = {
                **staged.attributes,
                GEN_AI_OUTPUT_MESSAGES: output,
            }
            if _size(attributes) > self._max_content_bytes:
                self._failed(staged.session, GENERATION, LlmInputExportFailure.DROPPED)
                return None
        except Exception:  # noqa: BLE001 - content export never breaks a reply
            self._failed(staged.session, GENERATION, LlmInputExportFailure.DROPPED)
            return None
        if not self._telemetry.stage_llm_content(
            staged.session, invocation, attributes
        ):
            self._failed(staged.session, GENERATION, LlmInputExportFailure.DROPPED)
            return None
        return staged.session

    def stage_tool(
        self,
        session: str,
        invocation: str,
        position: int,
        arguments: Mapping[str, Any] | str,
        result: str,
        emit: Callable[[], object],
    ) -> None:
        """Hand one tool call's pair to the `tool_call` event `emit` says.

        The pair is staged, `emit` is called exactly once whatever
        happens to the pair, and the handoff is then settled: the event
        folds synchronously, so by the time `emit` returns its tool span
        has taken the pair or never will. Only a pair the fold wrote
        onto a span is counted as exported and charged to the round; one
        the emission never delivered (a refused construction) is
        discarded there and then and reported, so nothing waits for
        shutdown and nothing is claimed that did not happen (#533).
        `invocation` and `position` are the event's own join keys.

        `arguments` is the reserved claim's: what the model asked with,
        not the copy coerced for the far side, encoded the way the
        round's `tool_call` part encodes it so the two copies of one call
        read alike; or the model's raw text where it sent no JSON
        object, the one case the neutral seam keeps text. `result` is
        exactly what the model was handed back.

        Bounded twice, with nothing truncated: a pair over the
        per-request ceiling is dropped whole, and so is one that would
        take a round's attached tool pairs past that same ceiling,
        because a round runs its whole call list at once and each pair
        lands on a span in telemetry's bounded queue.
        """
        staged = self._stage_tool(session, invocation, position, arguments, result)
        emit()
        if staged is None:
            return
        if self._settled(
            session, TOOL_CALL, self._telemetry.settle_tool_content(invocation, position)
        ):
            self._tool_round[session] = (invocation, staged)

    def _stage_tool(
        self,
        session: str,
        invocation: str,
        position: int,
        arguments: Mapping[str, Any] | str,
        result: str,
    ) -> int | None:
        """Render, bound and stage one pair, answering the round's
        attached bytes once it lands, or None where it was dropped and
        already reported."""
        try:
            encoded = arguments if isinstance(arguments, str) else _json(dict(arguments))
            attributes = {
                GEN_AI_TOOL_CALL_ARGUMENTS: encoded,
                GEN_AI_TOOL_CALL_RESULT: result,
            }
            size = _size(attributes)
        except Exception:  # noqa: BLE001 - content export never breaks a reply
            self._failed(session, TOOL_CALL, LlmInputExportFailure.DROPPED)
            return None
        current = self._tool_round.get(session)
        admitted = current[1] if current is not None and current[0] == invocation else 0
        if admitted + size > self._max_content_bytes:
            self._failed(session, TOOL_CALL, LlmInputExportFailure.DROPPED)
            return None
        if not self._telemetry.stage_tool_content(session, invocation, position, attributes):
            self._failed(session, TOOL_CALL, LlmInputExportFailure.DROPPED)
            return None
        return admitted + size

    def _settled(self, session: str, kind: LlmInputExportKind, attached: bool) -> bool:
        """Count one pair its span took, under its own kind, or report
        one it never got: the one ledger rule both kinds settle by.
        Answers whether it was counted."""
        if not attached:
            self._failed(session, kind, LlmInputExportFailure.DROPPED)
            return False
        events.emit(
            lambda: LlmInputExported(
                session=SessionId(session),
                rounds=Count(1 if kind is GENERATION else 0),
                tool_calls=Count(1 if kind is TOOL_CALL else 0),
            )
        )
        return True

    def session_closed(self, session: str) -> None:
        for invocation in tuple(self._sessions.get(session, ())):
            self._drop(invocation)
        self._tool_round.pop(session, None)

    async def shutdown(self) -> None:
        for session in tuple(self._sessions):
            self.session_closed(session)
        self._tool_round.clear()

    def _drop(self, invocation: str) -> None:
        staged = self._rounds.pop(invocation, None)
        if staged is None:
            return
        self._remove(staged)
        self._telemetry.discard_llm_content(invocation)
        self._failed(staged.session, GENERATION, LlmInputExportFailure.DROPPED)

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

    def _failed(
        self,
        session: str,
        kind: LlmInputExportKind,
        reason: LlmInputExportFailure,
    ) -> None:
        events.emit(
            lambda: LlmInputExportFailed(
                session=SessionId(session), kind=kind, reason=reason
            )
        )


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
    return sum(_utf8_size(value) for value in attributes.values())


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


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
        "arguments": (
            call.malformed_arguments
            if call.malformed_arguments is not None
            else call.arguments
        ),
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
