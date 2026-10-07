"""A browser-shaped device against the real server, beside a board (#613).

The unit lane drives the app through Starlette's test client, which
hands the offered subprotocols to the app without a wire in between.
This lane serves the app the way a deployment does, through uvicorn and
the configuration `serve()` builds, and connects with a real websocket
client: the browser's credential crosses as a `Sec-WebSocket-Protocol`
header that uvicorn parses and answers, which is the part only a real
server can prove. A board's handshake runs beside it on the same server,
unchanged.

And at DEBUG, with the floor `logs.configure` applies: uvicorn traces
request headers at that level, and a browser's token is in one, so the
token is hunted in both shipped formats afterwards.
"""

import asyncio
import json
import logging

import httpx
import pytest
import uvicorn
import websockets

from tests.integration.conftest import booted, mock_voice
from vinga_server import logs, serving
from vinga_server.config import Config
from vinga_server.device.handshake import BROWSER_SUBPROTOCOL
from vinga_server.onboarding import onboarding_key, onboarding_path
from vinga_server.ws import WEBSOCKET_PATH

MOCK_PROVIDERS = {stage: {"mock": {"type": "mock"}} for stage in ("llm", "asr", "vad")} | {
    "tts": {"mock": mock_voice()}
}
MOCK_AGENT = dict.fromkeys(("llm", "asr", "tts", "vad"), "mock")

BROWSER_MAC = "02:41:9c:7d:3e:58"
BROWSER_CLIENT = "3d9e1f5a-6b2c-5d8e-9f1a-0c4b6d8e2f7a"
BOARD_MAC = "aa:bb:cc:dd:ee:02"

# Both devices bound by name, the browser as a redeemed invite link binds
# it: an unbound device only pairs (#612).
CONFIG = Config(
    providers=MOCK_PROVIDERS,
    agents={"assistant": MOCK_AGENT},
    devices={BROWSER_MAC: ["assistant"], BOARD_MAC: ["assistant"]},
    default_agent="assistant",
)
BOARD_CLIENT = "8c4e2a6f-1d3b-4f5a-9e7c-0b2d4f6a8c1e"

HELLO = {
    "type": "hello",
    "version": 1,
    "features": {"mcp": False},
    "transport": "websocket",
    "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
}


async def _serving(app, config: Config):
    """The app under the configuration a deployment is served with, on
    an ephemeral port."""
    served = serving.uvicorn_config(app, config)
    served.host, served.port = "127.0.0.1", 0
    server = uvicorn.Server(served)
    task = asyncio.create_task(server.serve())
    while not server.started:
        if task.done():
            task.result()
        await asyncio.sleep(0.01)
    return server, task


async def _check_in(client: httpx.AsyncClient, path: str, mac: str, client_id: str) -> str:
    reply = await client.post(
        path,
        headers={"Device-Id": mac, "Client-Id": client_id},
        json={"board": {"type": "vinga-browser"}},
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["access"] == "token"
    return reply.json()["websocket"]["token"]


async def _hello(socket) -> dict:
    await socket.send(json.dumps(HELLO))
    return json.loads(await asyncio.wait_for(socket.recv(), timeout=30))


@pytest.mark.asyncio
async def test_a_browser_and_a_board_each_reach_a_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    server, task = await _serving(booted(CONFIG), CONFIG)
    port = server.servers[0].sockets[0].getsockname()[1]
    alias = onboarding_path(onboarding_key(CONFIG.server))

    levels = {name: logging.getLogger(name).level for name in logs.VENDOR_LOG_FLOORS}
    logs.quiet_vendor_libraries(logging.DEBUG)
    # This test's own clients are devices, not the server, and both
    # narrate what they send.
    caplog.set_level(logging.WARNING, logger="httpx")
    caplog.set_level(logging.WARNING, logger="websockets.client")
    try:
        with caplog.at_level(logging.DEBUG):
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", timeout=30
            ) as client:
                page = await client.get("/talk/")
                browser_token = await _check_in(client, alias, BROWSER_MAC, BROWSER_CLIENT)
                board_token = await _check_in(client, alias, BOARD_MAC, BOARD_CLIENT)

            # The browser: no headers, everything in the offered list.
            async with websockets.connect(
                f"ws://127.0.0.1:{port}{WEBSOCKET_PATH}",
                subprotocols=[
                    BROWSER_SUBPROTOCOL,
                    f"vinga.mac.{BROWSER_MAC.replace(':', '')}",
                    f"vinga.client.{BROWSER_CLIENT}",
                    f"vinga.token.{browser_token}",
                ],
                open_timeout=30,
            ) as browser:
                browser_selected = browser.subprotocol
                browser_hello = await _hello(browser)

            # The board: headers, no subprotocol, as it always was.
            async with websockets.connect(
                f"ws://127.0.0.1:{port}{WEBSOCKET_PATH}",
                additional_headers={
                    "Device-Id": BOARD_MAC,
                    "Client-Id": BOARD_CLIENT,
                    "Protocol-Version": "1",
                    "Authorization": f"Bearer {board_token}",
                },
                open_timeout=30,
            ) as board:
                board_selected = board.subprotocol
                board_hello = await _hello(board)

            # And a browser whose token is not one is refused on the
            # upgrade, as a board's is: closed before the accept, which
            # uvicorn answers 403.
            with pytest.raises(websockets.InvalidStatus) as refused:
                await websockets.connect(
                    f"ws://127.0.0.1:{port}{WEBSOCKET_PATH}",
                    subprotocols=[
                        BROWSER_SUBPROTOCOL,
                        f"vinga.mac.{BROWSER_MAC.replace(':', '')}",
                        f"vinga.client.{BROWSER_CLIENT}",
                        f"vinga.token.{board_token}",
                    ],
                    open_timeout=30,
                )
    finally:
        for name, level in levels.items():
            logging.getLogger(name).setLevel(level)
        server.should_exit = True
        await task

    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in page.headers["content-security-policy"]

    assert browser_selected == BROWSER_SUBPROTOCOL
    assert browser_hello["type"] == "hello"
    assert board_selected is None
    assert board_hello["type"] == "hello"
    assert refused.value.response.status_code == 403

    opened = [
        record.__dict__.get("device")
        for record in caplog.records
        if record.__dict__.get("event") == "session_open"
    ]
    assert sorted(opened) == sorted([BROWSER_MAC, BOARD_MAC])

    rendered = caplog.text + "".join(
        logs.JsonFormatter().format(record) for record in caplog.records
    )
    assert browser_token not in rendered
    assert board_token not in rendered
