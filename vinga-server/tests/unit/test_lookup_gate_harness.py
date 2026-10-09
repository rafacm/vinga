"""The #612 lookup gate's harness, driven with a scripted model.

What the harness hands back for a lookup call is what a deployment
hands back (PR #638 review, finding 2): a mangled call gets the
runtime's sentence, and a missing, blank or non-string query the
shipped builtin's refusal, never documentation passages the shipped
tool would not have returned.
"""

from typing import Any

import pytest

from tests.local.lookup_gate import harness
from tests.support.providers import ScriptedLlm, results_of
from vinga_server.providers import ToolCall
from vinga_server.runtime.tool_execution import UNPARSEABLE_ARGUMENTS
from vinga_server.tools import builtin, names

LCD = "devices/waveshare-esp32-s3-touch-lcd-1.54.md"


async def handed(call: ToolCall) -> str:
    """What the model is handed back for one lookup call, through the
    harness's own round loop."""
    script = ScriptedLlm([[call], "Done."])
    await harness.ask(script, "system", harness.offered(), [], "a question", names.SEARCH_DOCS, LCD)
    (result,) = results_of(script)
    return result


@pytest.mark.parametrize(
    "arguments",
    [{}, {"query": ""}, {"query": "   "}, {"query": 2.4}, {"query": ["wake word"]}],
    ids=["missing", "empty", "blank", "numeric", "a list"],
)
async def test_a_query_production_refuses_is_refused_by_the_harness(
    arguments: dict[str, Any],
) -> None:
    call = ToolCall(id="c-1", name=names.SEARCH_DOCS, arguments=arguments)
    assert await handed(call) == builtin.SEARCH_NEEDS_A_QUERY


async def test_a_mangled_call_gets_the_runtime_s_sentence() -> None:
    call = ToolCall(
        id="c-1", name=names.SEARCH_DOCS, arguments={}, malformed_arguments='{"query": '
    )
    assert await handed(call) == UNPARSEABLE_ARGUMENTS


async def test_a_good_query_gets_the_pages() -> None:
    call = ToolCall(id="c-1", name=names.SEARCH_DOCS, arguments={"query": "change wake word"})
    assert "building the firmware with it" in " ".join((await handed(call)).split())
