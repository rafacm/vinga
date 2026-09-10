"""The wire latency script over a capture this lane produced itself.

Every other test of `scripts/wire_latency.py` builds its WAV and its
decision track by hand, which proves the arithmetic and proves nothing
about the format. This one records a real session: a server with
capture enabled, one simulator conversation through the ordinary
pipeline, then the script over the triplet that session left behind. It
is the first test in the repository that produces a capture at all.

What it asserts is the end of the chain rather than a number. The
timings of a driven conversation are wall-clock and belong to nobody,
so the assertions are that a turn measured, that the measurement is
reported as a wire response latency, and that the run states its
precision and what it excludes. The numbers themselves are the unit
lane's, on captures built sample by sample.
"""

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from vinga_server.config import Config
from vinga_server.config.models import CaptureConfig, ServerConfig

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "wire_latency.py"

MOCK_PROVIDERS = {stage: {"mock": {"type": "mock"}} for stage in ("llm", "asr", "tts", "vad")}
MOCK_AGENT = dict.fromkeys(("llm", "asr", "tts", "vad"), "mock")

DEVICE_MAC = "aa:bb:cc:dd:ee:44"

# A measured turn, in the script's own words and at its own precision.
MEASURED = re.compile(
    r"turn 1: speech ended at \d+\.\d s, reply audio began at \d+\.\d s, "
    r"wire response latency \d+\.\d s"
)


@pytest.fixture
def captures(tmp_path: Path) -> Path:
    return tmp_path / "captures"


async def finished_capture(directory: Path, timeout_s: float = 20.0) -> None:
    """Wait for one capture to be written and closed.

    The three files exist from the moment the session opens, and the
    manifest's `complete` is what says the writer finished with them, so
    that is what is waited for. Bounded, because a capture that never
    closes is a failure to report rather than a run to hang (#283).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        for manifest in sorted(directory.glob("*.json")):
            written = json.loads(manifest.read_text(encoding="utf-8"))
            if written.get("capture", {}).get("complete") is True:
                return
        await asyncio.sleep(0.05)
    raise AssertionError("no capture was finished within the bound")


async def test_the_script_measures_a_turn_of_a_session_it_recorded(
    serve, simulate, captures: Path
) -> None:
    config = Config(
        providers=MOCK_PROVIDERS,
        agents={"assistant": MOCK_AGENT},
        default_agent="assistant",
        server=ServerConfig(capture=CaptureConfig(enabled=True, dir=captures)),
    )
    async with serve(config) as port:
        await simulate(port, DEVICE_MAC)
        await finished_capture(captures)

    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(captures)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    assert "capture 1: 1 turn(s), 1 measured" in done.stdout
    assert MEASURED.search(done.stdout) is not None
    assert "800 ms or 2.5 s, never a count of milliseconds" in done.stdout
    assert "excludes downlink transport and device playback" in done.stdout
    # The recording is of a room, and its identity stays in the
    # directory it was read from.
    assert DEVICE_MAC not in done.stdout
    assert "Traceback" not in done.stderr
