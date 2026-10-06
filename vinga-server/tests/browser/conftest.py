"""The browser lane: the real page, in headless Chromium, against a real
server (#613, Q5, Q5a, Q5b).

Opt in with VINGA_BROWSER_LANE, which `run.sh` sets. Without it nothing
here is collected, so a bare `pytest` in a checkout, which has no
Playwright, stays what it was; and this file imports nothing at module
level but the standard library and pytest, for the same reason.

The server under test is one of two things. Started here from
VINGA_BROWSER_SERVER, the `vinga-server` of the environment `run.sh`
installed the built wheel into, on a free loopback port, with its log
written where the lane reads it. Or already running at
VINGA_BROWSER_URL, which is how CI runs the lane against the image it
built, with VINGA_BROWSER_SERVER_LOG naming the file that server's log
is streamed into.

The page is opened at `localhost`, a secure context, so the microphone,
AudioWorklet and WebCodecs are all available to it without TLS.
"""

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

LANE_ENV = "VINGA_BROWSER_LANE"
API_SECRET_ENV = "VINGA_API_SECRET"

if not os.environ.get(LANE_ENV):
    collect_ignore_glob = ["test_*.py"]


@pytest.fixture(scope="session")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    from lane import IDLE_TIMEOUT_S, Server, free_port, wait_ready

    token = os.environ.get(API_SECRET_ENV, "")
    if not token:
        pytest.fail(f"{API_SECRET_ENV} must name the server's API token", pytrace=False)
    running = os.environ.get("VINGA_BROWSER_URL")
    if running:
        named = os.environ.get("VINGA_BROWSER_SERVER_LOG")
        log = Path(named) if named else None
        wait_ready(running, None, log)
        served = Server(running, token, log)
        served.follow_events()
        yield served
        return

    executable = os.environ.get("VINGA_BROWSER_SERVER")
    if not executable:
        pytest.fail(
            "the browser lane needs VINGA_BROWSER_SERVER (an installed vinga-server) "
            "or VINGA_BROWSER_URL (a running one); tests/browser/run.sh sets the first",
            pytrace=False,
        )
    home = tmp_path_factory.mktemp("server")
    log = home / "server.log"
    port = free_port()
    environment = {
        **os.environ,
        "VINGA_SERVER__HOST": "127.0.0.1",
        "VINGA_SERVER__PORT": str(port),
        "VINGA_SERVER__LOG_FORMAT": "json",
        "VINGA_SERVER__LOG_LEVEL": "DEBUG",
        "VINGA_SERVER__LIMITS__IDLE_TIMEOUT_S": str(IDLE_TIMEOUT_S),
    }
    with log.open("wb") as written:
        process = subprocess.Popen(
            [executable], cwd=home, env=environment, stdout=written, stderr=subprocess.STDOUT
        )
    base = f"http://127.0.0.1:{port}"
    try:
        wait_ready(base, process, log)
        served = Server(base, token, log)
        served.follow_events()
        yield served
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
        kept = os.environ.get("VINGA_BROWSER_KEEP_LOG")
        if kept:
            # Where a run that failed is read afterwards: CI uploads it,
            # and a local run names a file outside the container.
            shutil.copyfile(log, kept)


@pytest.fixture(scope="session")
def browser(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    """One Chromium for the whole run, its microphone the lane's loop."""
    from lane import compose_microphone
    from playwright.sync_api import sync_playwright

    microphone = compose_microphone(tmp_path_factory.mktemp("microphone"))
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch(
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={microphone}",
            ]
        )
        yield launched
        launched.close()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Any:
    """On a failed case, what the page and the server were saying."""
    report = yield
    if report.when != "call" or not os.environ.get(LANE_ENV):
        return report
    from lane import DIAGNOSTICS

    if report.failed:
        for describe in DIAGNOSTICS:
            try:
                report.sections.append(("browser lane", describe()))
            except Exception as failure:  # a page that has gone says why
                report.sections.append(("browser lane", f"(no diagnostics: {failure})"))
    DIAGNOSTICS.clear()
    return report
