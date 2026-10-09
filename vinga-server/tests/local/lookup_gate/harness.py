"""The #612 lookup gate's model run: vinga's prompt, vinga's tools and
the real lookup, against a real model, one question set at a time.

    VINGA_LOCAL_LLM_MODEL=gemma4:e4b uv run python -m tests.local.lookup_gate.harness \
        frozen .logs/gate-frozen.jsonl

An OpenAI-compatible endpoint that asks for a key, a hosted runner
for one, gets it from `VINGA_LOCAL_LLM_API_KEY`, read only when set
and never printed; a model that refuses or ignores one of the default
options gets its own from `VINGA_LOCAL_LLM_PASSTHROUGH`, a JSON object
sent in place of the default `{"temperature": 0, "seed": 42,
"reasoning_effort": "none"}`. With neither set, the request is the
local Ollama one, byte for byte.

What it sends is what vinga is sent on the LCD-1.54 board, short of the
pipeline around it: the persona, the sentence about the lookup and
the concept summary (`knowledge.persona()`), the board's facts
(`knowledge.board_facts`), and the tools `BuiltinTools` offers the
built-in agent on a device bound to it alone, with the lookup among
them, plus the board's own volume tool. The request goes through the
server's own provider (`OpenAiCompatibleLlm`) at temperature 0 and a fixed seed,
with thinking off, round after round as the runtime's tool loop runs
them (`MAX_TOOL_ROUNDS`, the last with no tools allowed). The lookup is
the real one; every other tool answers a fixed line, since what is
measured is whether the model looks up and answers from what it found.

The device block's introduction and memory section are left out (a
fresh device with no name and nothing remembered), which is the one
way this prompt differs from the session's.

Each answer is written as one JSON line, with the round timings: the
first byte of each round, how long the round after a lookup took to
start answering, and the tokens each round reported.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tests.local.lookup_gate import scoring
from vinga_server import knowledge
from vinga_server.class_names import failure_name
from vinga_server.providers import StreamStarted, TextDelta, ToolCall, ToolResult, Turn, Usage
from vinga_server.providers.base import ToolDef
from vinga_server.providers.openai_llm import OpenAiCompatibleLlm
from vinga_server.runtime.pipeline import MAX_TOOL_ROUNDS
from vinga_server.runtime.tool_execution import UNPARSEABLE_ARGUMENTS
from vinga_server.tools import builtin
from vinga_server.tools.source import BuiltinTools

BOARD = "esp32-s3-touch-lcd-1.54"

OLLAMA = os.environ.get("VINGA_LOCAL_OLLAMA", "http://127.0.0.1:11434/v1")

# Per question, all rounds together: the gate's later cap.
QUESTION_CAP_S = 360.0

# The warm-up's own bound: the cold read of the shared prefix.
WARM_UP_S = 1_800.0

# The OpenAI-compatible path's key, for an endpoint that asks for one.
# Unset, the request carries the SDK's placeholder, as local Ollama's
# always has.
API_KEY_ENV = "VINGA_LOCAL_LLM_API_KEY"

PASSTHROUGH_ENV = "VINGA_LOCAL_LLM_PASSTHROUGH"

DEFAULT_PASSTHROUGH = {"temperature": 0, "seed": 42, "reasoning_effort": "none"}


VOLUME = ToolDef(
    name=scoring.VOLUME_TOOL,
    description="Set the volume of the audio speaker, 0 to 100.",
    input_schema={
        "type": "object",
        "properties": {"volume": {"type": "integer", "minimum": 0, "maximum": 100}},
        "required": ["volume"],
    },
)

STUBBED = "Done."


def offered() -> list[ToolDef]:
    """vinga's tools on a device bound to it alone, the lookup among
    them since `BuiltinTools` offers it to the built-in agent, and the
    board's volume tool. Every name once: Ollama accepts a list naming
    one tool twice and Anthropic's API refuses it, and the first gate
    runs of M5 sent the lookup twice before that refusal showed it."""
    source = BuiltinTools(
        agents=["vinga"],
        memory=None,  # type: ignore[arg-type]
        timeout_s=10.0,
        context=None,  # type: ignore[arg-type]
        remembers=lambda: True,
        is_builtin=lambda: True,
    )
    tools = [*source.snapshot("vinga"), VOLUME]
    assert len({tool.name for tool in tools}) == len(tools), "a tool offered twice"
    return tools


def system() -> str:
    """vinga's persona and the board's facts, as the device block ends
    with them."""
    return f"{knowledge.persona()}\n\n{knowledge.board_facts(BOARD)}"


def answer_lookup(call: ToolCall, guide: str | None) -> str:
    """What a deployment answers this lookup call with: the runtime's
    sentence for arguments that never parsed as an object, and
    otherwise the shipped `search_docs` builtin, which refuses a missing,
    blank or non-string query with its own sentence. The harness
    measures what the tool does, not a friendlier copy of it."""
    if call.malformed_arguments is not None:
        return UNPARSEABLE_ARGUMENTS
    return builtin.search_docs(call.arguments, guide)


async def ask(llm, prompt, tools, history, text, lookup_name, guide):
    """One question, through every round it takes."""
    turns = [*history, Turn("user", text)]
    calls: list[scoring.Call] = []
    rounds = []
    answer = ""
    looped = timed_out = False
    started = time.monotonic()
    after_lookup = False
    try:
        for index in range(MAX_TOOL_ROUNDS):
            choice = "none" if index == MAX_TOOL_ROUNDS - 1 else "auto"
            began = time.monotonic()
            first_byte = first_text = None
            text_out: list[str] = []
            made: list[ToolCall] = []
            usage: Usage | None = None
            remaining = QUESTION_CAP_S - (began - started)
            async with asyncio.timeout(remaining):
                async for event in llm.stream(prompt, turns, tools, choice):
                    now = time.monotonic() - began
                    if isinstance(event, StreamStarted):
                        first_byte = now
                    elif isinstance(event, TextDelta):
                        if first_text is None and event.text.strip():
                            first_text = now
                        text_out.append(event.text)
                    elif isinstance(event, ToolCall):
                        made.append(event)
                    elif isinstance(event, Usage):
                        usage = event
            rounds.append(
                {
                    "first_byte_s": first_byte,
                    "first_text_s": first_text,
                    "elapsed_s": time.monotonic() - began,
                    "after_lookup": after_lookup,
                    "calls": [call.name for call in made],
                    "input_tokens": None if usage is None else usage.prompt_tokens,
                    "output_tokens": None if usage is None else usage.completion_tokens,
                    "cached_tokens": None if usage is None else usage.cached_prompt_tokens,
                }
            )
            if not made:
                answer = "".join(text_out)
                break
            if index == MAX_TOOL_ROUNDS - 1:
                looped = True
                answer = "".join(text_out)
                break
            results = []
            after_lookup = False
            for call in made:
                malformed = call.malformed_arguments is not None
                calls.append(scoring.Call(call.name, dict(call.arguments), malformed))
                if call.name == lookup_name:
                    after_lookup = True
                    content = answer_lookup(call, guide)
                elif call.name == scoring.VOLUME_TOOL:
                    content = "true"
                else:
                    content = STUBBED
                results.append(ToolResult(tool_call_id=call.id, content=content))
            turns.append(Turn("assistant", "".join(text_out), tool_calls=tuple(made)))
            turns.append(Turn("tool", "", tool_results=tuple(results)))
    except TimeoutError:
        timed_out = True
    return (
        scoring.Answer(tuple(calls), answer, looped, timed_out),
        rounds,
        time.monotonic() - started,
    )


def provider() -> tuple[Any, str]:
    """The model the lane names, through the server's own adapter: an
    OpenAI-compatible Ollama by default, or Anthropic's API when
    `VINGA_LOCAL_LLM_PROVIDER=anthropic`, its key read from
    `VINGA_DEV_ANTHROPIC_API_KEY` and never printed. The compatible
    path's key and options are `API_KEY_ENV` and `passthrough()`."""
    if os.environ.get("VINGA_LOCAL_LLM_PROVIDER") == "anthropic":
        from vinga_server.providers.anthropic_llm import AnthropicLlm
        from vinga_server.providers.kit import DEFAULT_MAX_TOKENS

        model = os.environ.get("VINGA_LOCAL_LLM_MODEL", "claude-sonnet-5")
        # Exactly what a deployment's `anthropic` entry sends, with no
        # temperature: the adapter sends none, and claude-sonnet-5
        # refuses one ("`temperature` is deprecated for this model"), so
        # this run is not pinned to temperature 0 as the Ollama runs are.
        llm = AnthropicLlm(
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS,
            api_key=os.environ["VINGA_DEV_ANTHROPIC_API_KEY"],
            timeout_s=QUESTION_CAP_S,
        )
        return llm, model
    model = os.environ.get("VINGA_LOCAL_LLM_MODEL", "gemma4:e4b")
    llm = OpenAiCompatibleLlm(
        base_url=OLLAMA,
        model=model,
        max_tokens=None,
        api_key=os.environ.get(API_KEY_ENV) or None,
        timeout_s=WARM_UP_S,
        passthrough=passthrough(),
    )
    return llm, model


def passthrough() -> dict[str, object]:
    """The options sent beside vinga's request: the default, or the JSON
    object `VINGA_LOCAL_LLM_PASSTHROUGH` holds instead of it, whole. A
    value that is not an object stops the run before any request."""
    raw = os.environ.get(PASSTHROUGH_ENV)
    if raw is None:
        return dict(DEFAULT_PASSTHROUGH)
    options = json.loads(raw)
    if not isinstance(options, dict):
        raise TypeError("the passthrough is not a JSON object")
    return options


async def run(which: str, out: Path, lookup: ToolDef, guide: str | None):
    llm, model = provider()
    questions = scoring.frozen() if which == "frozen" else scoring.rephrased()
    prompt = system()
    tools = offered()
    exchanges: dict[str, list[Turn]] = {}
    out.parent.mkdir(parents=True, exist_ok=True)
    # A run that stopped part-way resumes where it stopped: answered
    # questions are skipped, and a follow-up exchange is rebuilt from
    # the answers already written.
    done: set[str] = set()
    if out.exists():
        by_id = {q.id: q for q in questions}
        for line in out.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            done.add(record["id"])
            exchange = by_id[record["id"]].exchange
            if exchange:
                exchanges[exchange] = [
                    *exchanges.get(exchange, []),
                    Turn("user", record["question"]),
                    Turn("assistant", record["answer"]["text"]),
                ]
    # The shared prefix (the persona, the facts and the tools) read once
    # before the first question, and not measured: a cold runner spends
    # minutes reading it on a Pi, which is the first question's cost
    # and no answer's, and every later question finds it cached. A
    # vendor's API has no cold prefix to read, so it is not warmed.
    if os.environ.get("VINGA_LOCAL_LLM_PROVIDER") != "anthropic":
        began = time.monotonic()
        async for _ in llm.stream(prompt, [Turn("user", "Hello.")], tools, "none"):
            pass
        print(f"warm-up {time.monotonic() - began:.1f}s", flush=True)
    with out.open("a", encoding="utf-8") as sink:
        for question in questions:
            if question.id in done:
                continue
            history = exchanges.get(question.exchange or "", []) if question.exchange else []
            answer, rounds, total = await ask(
                llm, prompt, tools, history, question.text, lookup.name, guide
            )
            if question.exchange:
                exchanges[question.exchange] = [
                    *history,
                    Turn("user", question.text),
                    Turn("assistant", answer.text),
                ]
            category, hallucinated, why = scoring.score(question, answer, lookup.name)
            record = {
                "set": which,
                "model": model,
                "id": question.id,
                "question": question.text,
                "answer": asdict(answer),
                "rounds": rounds,
                "total_s": total,
                "auto": category,
                "auto_hallucinated": hallucinated,
                "auto_why": why,
                "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")
            sink.flush()
            print(f"{question.id:4} {total:6.1f}s {category:14} {answer.text[:100]!r}", flush=True)
    await llm.close()


# What the harness says when a run stops, with the failure's class name
# and nothing else: a provider's error can carry the URL it was given or
# the bytes a server answered, and a traceback renders the whole chain.
STOPPED = "the lookup gate stopped: {failure}"


def main(argv: list[str] | None = None) -> int:
    """Run one question set, and answer an exit status.

    Every failure, building the provider included, is contained here:
    the report is built in the except arm from the class name alone
    (`failure_name`, which gives a fixed phrase for a name it will not
    print) and said after the block, so neither the exception, its
    message, nor the chain behind it outlives the arm or reaches stdout
    or stderr."""
    args = sys.argv[1:] if argv is None else argv
    report: str | None = None
    try:
        which, out = args[0], Path(args[1])
        guide = knowledge.board_guide(BOARD)
        asyncio.run(run(which, out, builtin.search_docs_tool(), guide))
    except Exception as exc:
        report = STOPPED.format(failure=failure_name(exc))
    if report is not None:
        print(report, file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
