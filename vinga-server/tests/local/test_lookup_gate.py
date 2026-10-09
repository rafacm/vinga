"""The #612 lookup gate, replayed against a real model (M5).

Opt-in like the rest of this lane (`VINGA_LOCAL_LANE=1`), and slow: it
asks both question sets, 64 questions, of the model the lane names
(`VINGA_LOCAL_LLM_MODEL`, default `gemma4:e4b`, the model the gate
chose), on Ollama. What it sends and how it scores are
`lookup_gate/harness.py` and `lookup_gate/scoring.py`; this case holds
each set's result to the gate's bar, at least 70% correct and at most
10% hallucinated, with every device command a call. "Correct" is the
gate's category, over all 32 questions, as the gate counted it. An
answer the scorer cannot decide is listed for a person to read and is not
counted as correct.

    VINGA_LOCAL_LANE=1 uv run pytest tests/local/test_lookup_gate.py -q
"""

import json
import os
from pathlib import Path

import pytest

from tests.local.lookup_gate import harness, scoring
from vinga_server import knowledge
from vinga_server.tools import builtin

MODEL_ENV = "VINGA_LOCAL_LLM_MODEL"


@pytest.fixture(autouse=True)
def _opted_in() -> None:
    if os.environ.get("VINGA_LOCAL_LANE") != "1":
        pytest.skip("the local lane is opt-in: VINGA_LOCAL_LANE=1")


@pytest.mark.parametrize("which", ["frozen", "rephrased"])
async def test_the_gate_s_bar_holds(
    which: str, tmp_path: Path, conversation_report: list[str]
) -> None:
    os.environ.setdefault(MODEL_ENV, "gemma4:e4b")
    out = tmp_path / f"{which}.jsonl"
    await harness.run(
        which, out, builtin.search_docs_tool(), knowledge.board_guide(harness.BOARD)
    )
    records = [json.loads(line) for line in out.read_text().splitlines()]
    total = len(records)
    # "Correct" as the gate counted it: the category alone, over all 32,
    # so an honest decline and a device command, scored apart, are not
    # in it.
    correct = sum(r["auto"] == scoring.CORRECT for r in records)
    hallucinated = sum(r["auto_hallucinated"] for r in records)
    undecided = [r["id"] for r in records if r["auto"] == scoring.UNDECIDED]
    commands = [r for r in records if r["id"] in {"C1", "C2"}]
    conversation_report.append(
        f"lookup gate, {which}: {correct}/{total} correct, {hallucinated} hallucinated, "
        f"undecided for a person: {', '.join(undecided) or 'none'}"
    )
    assert total == 32
    assert correct / total >= scoring.CORRECT_AT_LEAST
    assert hallucinated / total <= scoring.HALLUCINATED_AT_MOST
    assert all(r["auto"] == scoring.DEVICE_OK for r in commands)
