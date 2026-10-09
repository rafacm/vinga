"""The #612 lookup gate's harness, driven with a scripted model.

What the harness hands back for a lookup call is what a deployment
hands back (PR #638 review, finding 2): a mangled call gets the
runtime's sentence, and a missing, blank or non-string query the
shipped builtin's refusal, never documentation passages the shipped
tool would not have returned.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.local.lookup_gate import harness
from tests.support.providers import ScriptedLlm, results_of
from vinga_server.class_names import UNNAMED_FAILURE
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


# A run that stops says the failure's class name and nothing else (PR
# #638 review, finding 1).

SENTINEL = "REJECTEDINPUTSENTINEL"


def test_a_malformed_runner_address_is_not_repeated_back(tmp_path: Path) -> None:
    """The documented command, run as written, against an address whose
    port is the sentinel: the request library's words about the
    address, and its traceback, are what used to reach stderr."""
    environment = {
        **os.environ,
        "VINGA_LOCAL_OLLAMA": f"http://localhost:{SENTINEL}/v1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    environment.pop("VINGA_LOCAL_LLM_PROVIDER", None)
    command = [
        sys.executable,
        "-m",
        "tests.local.lookup_gate.harness",
        "frozen",
        str(tmp_path / "out.jsonl"),
    ]
    ran = subprocess.run(
        command,
        cwd=Path(harness.__file__).parents[3],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert ran.returncode == 1
    assert SENTINEL not in ran.stdout + ran.stderr
    assert "Traceback" not in ran.stderr
    assert ran.stderr.startswith("the lookup gate stopped: ")
    assert ran.stderr.count("\n") == 1


def test_an_exception_with_an_unsafe_class_name_is_not_repeated_back(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    unsafe = type(f"Bad name {SENTINEL}\nsecond line", (RuntimeError,), {})

    async def failing(*args: Any) -> None:
        try:
            raise ValueError(f"the cause {SENTINEL}")
        except ValueError as cause:
            raise unsafe(f"the message {SENTINEL}") from cause

    monkeypatch.setattr(harness, "run", failing)

    assert harness.main(["frozen", "unused.jsonl"]) == 1
    captured = capsys.readouterr()
    assert SENTINEL not in captured.out + captured.err
    assert captured.err == harness.STOPPED.format(failure=UNNAMED_FAILURE) + "\n"
    assert sys.exc_info() == (None, None, None)
