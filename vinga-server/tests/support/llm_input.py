"""The one seam an LLM input export reaches, as a thing a lane can
hold.

`llm_input_export.py` reaches exactly one collaborator, a `Telemetry`,
and asks it two questions: the retained context a job is admitted on,
and the bounded write that puts a session's staged rounds onto its
trace. So what is here stands in for that, and a suite drives the REAL
stage, the real byte bound, the real drop accounting, the real bounded
queue, the real daemon worker and the real outcome events with no
OpenTelemetry anywhere.

Nothing here asserts. It returns a seam and a recorder, and the suite
says what it expects.

The recorder is the point rather than the fake. What has to be proved is
exactly what crossed into the span writer, which is a question about
what was HANDED OVER: so it writes down every call.
"""

import threading
from typing import Any

from vinga_server.providers.base import ToolCall, ToolDef, ToolResult, Turn
from vinga_server.telemetry import Delivery, LlmInputRound, Telemetry

# The opaque handle a retained context is, from the exporter's side. It
# never looks inside one, which is the whole of what "opaque" buys, so a
# lane can hand it anything it can recognize again.
A_CONTEXT = "a-retained-context"


class Exported:
    """The telemetry exporter, as the two questions an LLM input export
    asks it.

    Not a `Telemetry`, and typed as one at the call site because that is
    what the module declares: what it uses is `retained_context` and
    `export_llm_input`, and a lane that had to build a real provider to
    answer one handle would be driving OpenTelemetry to test a bound.

    `jobs` is what a case reads back: one entry per bounded write, with
    the session, the context it was given and the rounds that crossed,
    which is how a claim about the bound, the ordinals and what may
    cross is made without a span.
    """

    def __init__(
        self,
        contexts: dict[str, Any] | None = None,
        *,
        answer: Delivery = Delivery.DELIVERED,
        raises: BaseException | None = None,
    ) -> None:
        self.contexts = dict(contexts or {})
        self.jobs: list[tuple[str, Any, list[LlmInputRound]]] = []
        self.asked: list[str] = []
        self._answer = answer
        self._raises = raises
        self._lock = threading.Lock()

    def retained_context(self, session: str) -> Any | None:
        with self._lock:
            self.asked.append(session)
        return self.contexts.get(session)

    def export_llm_input(self, session: str, context: Any, rounds: Any) -> Delivery:
        with self._lock:
            self.jobs.append((session, context, list(rounds)))
        if self._raises is not None:
            raise self._raises
        return self._answer

    @property
    def rounds(self) -> list[LlmInputRound]:
        """Every round of every job, in the order they were written."""
        return [one for _, _, rounds in self.jobs for one in rounds]


def exporting(
    contexts: dict[str, Any] | None = None, **answers: Any
) -> tuple[Telemetry, Exported]:
    """`Exported` under the type the module declares, and itself."""
    held = Exported(contexts, **answers)
    return held, held  # type: ignore[return-value]


def a_turn(
    role: str = "user",
    content: str = "turn the light on",
    calls: "tuple[ToolCall, ...]" = (),
    results: "tuple[ToolResult, ...]" = (),
) -> Turn:
    """One history turn at the provider seam, which is what a staged
    round is assembled out of."""
    return Turn(role=role, content=content, tool_calls=calls, tool_results=results)


def a_tool(name: str = "remember", description: str = "Remember a fact.") -> ToolDef:
    """One tool as the model is told about it, schema and all."""
    return ToolDef(
        name=name,
        description=description,
        input_schema={
            "type": "object",
            "properties": {"fact": {"type": "string"}},
            "required": ["fact"],
        },
    )
