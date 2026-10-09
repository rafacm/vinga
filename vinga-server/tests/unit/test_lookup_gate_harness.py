"""The #612 lookup gate's harness, driven with a scripted model.

What the harness hands back for a lookup call is what a deployment
hands back (PR #638 review, finding 2): a mangled call gets the
runtime's sentence, and a missing, blank or non-string query the
shipped builtin's refusal, never documentation passages the shipped
tool would not have returned.
"""

import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from tests.local.lookup_gate import harness
from tests.support.providers import ScriptedLlm, errors_of, results_of
from vinga_server.class_names import UNNAMED_FAILURE
from vinga_server.providers import ToolCall, Turn
from vinga_server.providers.openai_llm import OpenAiCompatibleLlm
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


# A call to a tool the harness did not offer is answered as a session
# answers it, never as if it ran: a model that handed the conversation
# to an agent this device does not reach used to be told "Done.".


async def answered(*calls: ToolCall) -> list[tuple[str, bool]]:
    """What the model is handed back for one round of calls, through the
    harness's own round loop, with whether each was an error."""
    script = ScriptedLlm([list(calls), "Done."])
    await harness.ask(script, "system", harness.offered(), [], "a question", names.SEARCH_DOCS, LCD)
    return list(zip(results_of(script), errors_of(script), strict=True))


async def test_a_switch_to_an_agent_the_device_does_not_reach_is_refused() -> None:
    call = ToolCall(id="c-1", name=names.SWITCH_AGENT, arguments={"agent": "music"})
    assert await answered(call) == [
        ('this device is not bound to agent "music" (bound to: vinga)', True)
    ]


async def test_a_second_switch_in_one_round_is_refused_as_the_session_refuses_it() -> None:
    first = ToolCall(id="c-1", name=names.SWITCH_AGENT, arguments={"agent": "music"})
    second = ToolCall(id="c-2", name=names.SWITCH_AGENT, arguments={"agent": "vinga"})
    (_, (text, is_error)) = await answered(first, second)
    assert text.startswith("this conversation has already been handed over once")
    assert is_error


async def test_a_name_nobody_offered_is_no_such_tool() -> None:
    call = ToolCall(id="c-1", name="play_music", arguments={"playlist": "mine"})
    assert await answered(call) == [('there is no tool called "play_music"', True)]


async def test_a_mangled_call_to_a_name_nobody_offered_gets_the_runtime_s_sentence() -> None:
    call = ToolCall(id="c-1", name="play_music", arguments={}, malformed_arguments="{")
    assert await answered(call) == [(UNPARSEABLE_ARGUMENTS, True)]


async def test_an_offered_tool_is_still_answered_with_the_fixed_line() -> None:
    call = ToolCall(id="c-1", name=names.NEW_CONVERSATION, arguments={})
    assert await answered(call) == [(harness.STUBBED, False)]


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


# An authenticated OpenAI-compatible endpoint (a hosted runner): the key
# comes from `VINGA_LOCAL_LLM_API_KEY` and goes in the request alone.

KEY = "sk-ollama-0123456789abcdefKEYSENTINEL9876543210"


class Endpoint:
    """A chat-completions endpoint on loopback that records what it was
    sent and answers each request from `replies` in turn: a reply text
    as a one-chunk stream, or `REFUSE`, a 401 whose body repeats the
    request's Authorization header, as the worst server would."""

    REFUSE = object()

    def __init__(self, replies: list[object]) -> None:
        self.received: list[tuple[str, bytes]] = []
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 (http.server's name)
                body = self.rfile.read(int(self.headers["Content-Length"]))
                authorization = self.headers.get("Authorization", "")
                endpoint.received.append((authorization, body))
                reply = replies[min(len(endpoint.received), len(replies)) - 1]
                if reply is Endpoint.REFUSE:
                    payload = json.dumps(
                        {"error": {"message": f"invalid key: {authorization}"}}
                    ).encode()
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                chunk = {
                    "id": "c",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "m",
                    "choices": [{"index": 0, "delta": {"content": reply}, "finish_reason": "stop"}],
                }
                payload = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def endpoint() -> Iterator[Endpoint]:
    served = Endpoint(["Paris."])
    yield served
    served.close()


async def asked(llm: Any) -> None:
    """One round of the harness's own request through `llm`."""
    async for _ in llm.stream("system", [Turn("user", "Hello.")], harness.offered(), "auto"):
        pass
    await llm.close()


@pytest.fixture
def compatible(monkeypatch: pytest.MonkeyPatch, endpoint: Endpoint) -> None:
    """The OpenAI-compatible path, aimed at the endpoint, with nothing
    else set."""
    monkeypatch.setattr(harness, "OLLAMA", endpoint.url)
    for name in (harness.API_KEY_ENV, harness.PASSTHROUGH_ENV, "VINGA_LOCAL_LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("VINGA_LOCAL_LLM_MODEL", raising=False)


@pytest.mark.usefixtures("compatible")
async def test_with_neither_variable_set_the_request_is_the_local_one(endpoint: Endpoint) -> None:
    """Byte for byte what the harness sent local Ollama before the key
    and the options could be set: the construction as it stood, side
    by side with today's."""
    llm, model = harness.provider()
    await asked(llm)
    await asked(
        OpenAiCompatibleLlm(
            base_url=endpoint.url,
            model="gemma4:e4b",
            max_tokens=None,
            api_key=None,
            timeout_s=harness.WARM_UP_S,
            passthrough={"temperature": 0, "seed": 42, "reasoning_effort": "none"},
        )
    )

    (today, before) = endpoint.received
    assert model == "gemma4:e4b"
    assert today == before
    assert KEY not in today[0]


@pytest.mark.usefixtures("compatible")
async def test_a_key_set_goes_in_the_authorization_header(
    endpoint: Endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(harness.API_KEY_ENV, KEY)
    llm, _ = harness.provider()
    await asked(llm)

    ((authorization, body),) = endpoint.received
    assert authorization == f"Bearer {KEY}"
    assert KEY.encode() not in body


@pytest.mark.usefixtures("compatible")
async def test_the_options_set_replace_the_default_whole(
    endpoint: Endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(harness.PASSTHROUGH_ENV, '{"temperature": 0, "reasoning_effort": "low"}')
    llm, _ = harness.provider()
    await asked(llm)

    ((_, body),) = endpoint.received
    sent = json.loads(body)
    assert (sent["temperature"], sent["reasoning_effort"]) == (0, "low")
    assert "seed" not in sent


def test_options_that_are_not_an_object_stop_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(harness.PASSTHROUGH_ENV, '["low"]')
    with pytest.raises(TypeError):
        harness.passthrough()


def test_a_key_reaches_no_output_of_a_run_that_fails(tmp_path: Path) -> None:
    """The documented command with a credential-shaped key, against an
    endpoint that answers the warm-up and the first question and then
    refuses with the key in its error body: the key is sent, and
    reaches neither stdout, stderr, nor the answers written."""
    served = Endpoint(["Hello.", "An answer.", Endpoint.REFUSE])
    out = tmp_path / "out.jsonl"
    environment = {
        **os.environ,
        "VINGA_LOCAL_OLLAMA": served.url,
        harness.API_KEY_ENV: KEY,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    for name in (harness.PASSTHROUGH_ENV, "VINGA_LOCAL_LLM_PROVIDER"):
        environment.pop(name, None)
    try:
        ran = subprocess.run(
            [sys.executable, "-m", "tests.local.lookup_gate.harness", "frozen", str(out)],
            cwd=Path(harness.__file__).parents[3],
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        served.close()

    assert [authorization for authorization, _ in served.received] == [f"Bearer {KEY}"] * 3
    assert ran.returncode == 1
    assert ran.stderr.startswith("the lookup gate stopped: ")
    assert "Traceback" not in ran.stderr
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1
    assert KEY not in ran.stdout + ran.stderr + out.read_text(encoding="utf-8")
