"""The #612 lookup gate's model run: vinga's prompt, vinga's tools and
the real lookup, against a real model, one question set at a time.

    VINGA_LOCAL_LLM_MODEL=gemma4:e4b uv run python -m tests.local.lookup_gate.harness \
        frozen .logs/gate-frozen.jsonl

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
first byte of each round and, for the round after a lookup, how long
the model took to start answering, which is what the first-token
allowance is about.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from tests.local.lookup_gate import scoring
from vinga_server import knowledge
from vinga_server.providers import StreamStarted, TextDelta, ToolCall, ToolResult, Turn
from vinga_server.providers.base import ToolDef
from vinga_server.providers.openai_llm import OpenAiCompatibleLlm
from vinga_server.runtime.pipeline import MAX_TOOL_ROUNDS
from vinga_server.tools import builtin
from vinga_server.tools.source import BuiltinTools

BOARD = "esp32-s3-touch-lcd-1.54"

OLLAMA = os.environ.get("VINGA_LOCAL_OLLAMA", "http://127.0.0.1:11434/v1")

# Per question, all rounds together: the gate's later cap.
QUESTION_CAP_S = 360.0

# The warm-up's own bound: the cold read of the shared prefix.
WARM_UP_S = 1_800.0

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


def offered(lookup: ToolDef) -> list[ToolDef]:
    """vinga's tools on a device bound to it alone, the lookup among
    them, and the board's volume tool."""
    source = BuiltinTools(
        agents=["vinga"],
        memory=None,  # type: ignore[arg-type]
        timeout_s=10.0,
        context=None,  # type: ignore[arg-type]
        remembers=lambda: True,
        is_builtin=lambda: True,
    )
    return [*source.snapshot("vinga"), lookup, VOLUME]


def system() -> str:
    """vinga's persona (the lookup's sentence included) and the board's
    facts, as the device block ends with them."""
    return f"{knowledge.persona()}\n\n{knowledge.board_facts(BOARD)}"


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
            rounds.append(
                {
                    "first_byte_s": first_byte,
                    "first_text_s": first_text,
                    "elapsed_s": time.monotonic() - began,
                    "after_lookup": after_lookup,
                    "calls": [call.name for call in made],
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
                    content = knowledge.search(str(call.arguments.get("query", "")), guide)
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


async def run(which: str, out: Path, lookup: ToolDef, guide: str | None):
    model = os.environ.get("VINGA_LOCAL_LLM_MODEL", "gemma4:e4b")
    llm = OpenAiCompatibleLlm(
        base_url=OLLAMA,
        model=model,
        max_tokens=None,
        api_key=None,
        timeout_s=WARM_UP_S,
        passthrough={"temperature": 0, "seed": 42, "reasoning_effort": "none"},
    )
    questions = scoring.frozen() if which == "frozen" else scoring.rephrased()
    prompt = system()
    tools = offered(lookup)
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
    # and no answer's, and every later question finds it cached.
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


def main() -> None:
    which, out = sys.argv[1], Path(sys.argv[2])
    guide = knowledge.board_guide(BOARD)
    asyncio.run(run(which, out, builtin.search_docs_tool(), guide))


if __name__ == "__main__":
    main()
