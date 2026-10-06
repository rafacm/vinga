"""The browser page under a path prefix (#613, PR #625's review).

`server.public_url` may carry a path prefix (`https://example/vinga`):
a proxy serves the deployment under it and strips it before the server
sees the request. A page that names a URL from the root (`/try/...`)
then reaches past the prefix to whatever else the proxy serves at the
root, or to nothing. So every URL the page uses is relative to the page
it was served at: its module, its redemption, and the onboarding path a
redemption hands back, which comes relative to the deployment's root
and is resolved by the page against the page's own base minus `try/`.

Driven through a shim that strips the prefix the way such a proxy does,
so what is resolved against `http://testserver/vinga/try/` is what the
application then answers.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from urllib.parse import urljoin, urlsplit

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_API_SECRET
from tests.support.checkin import SYSTEM_INFO
from tests.support.registry import booted
from vinga_server.app import create_app
from vinga_server.browser import REDEEM_PATH
from vinga_server.device.handshake import BROWSER_SUBPROTOCOL

PREFIX = "/vinga"
BEARER = {"Authorization": f"Bearer {TEST_API_SECRET}"}
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}

REFERENCE = re.compile(r'(?:src|href)="([^"]*)"')
MODULE = re.compile(r'src="([^"]*page\.js)"')
SOCKET = re.compile(r'<meta name="vinga-socket" content="([^"]*)">')

# How `urls.js` finds the deployment's root: a URL relative to its own
# address, `<root>try/static/<version>/urls.js`, read out of the module
# itself so what is resolved here is what the browser resolves.
URLS_ROOT = re.compile(r'const ROOT = new URL\("([^"]*)", import\.meta\.url\);')

HELLO = {
    "type": "hello",
    "version": 1,
    "features": {"mcp": False},
    "transport": "websocket",
    "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60},
}


class Stripped:
    """A proxy serving the application under a prefix: it answers only
    paths under the prefix, and hands the application the rest."""

    def __init__(self, app, prefix: str) -> None:
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope, receive, send) -> None:
        # The lifespan passes through untouched, so the application is
        # entered once, by this client.
        if scope["type"] in ("http", "websocket"):
            path = scope["path"]
            if not path.startswith(f"{self.prefix}/"):
                await send({"type": "http.response.start", "status": 404, "headers": []})
                await send({"type": "http.response.body", "body": b"not under the prefix"})
                return
            scope = {**scope, "path": path[len(self.prefix) :], "raw_path": None}
        await self.app(scope, receive, send)


@contextmanager
def behind_a_prefix() -> Iterator[TestClient]:
    app = create_app(booted(default_agent="assistant"), from_store=True)
    with TestClient(Stripped(app, PREFIX), base_url="http://testserver") as proxied:
        yield proxied


@pytest.mark.parametrize("spelling", ["/try/", "/try"])
def test_every_reference_the_page_makes_stays_under_the_prefix(spelling: str) -> None:
    with behind_a_prefix() as proxied:
        page_url = f"http://testserver{PREFIX}{spelling}"
        page = proxied.get(page_url)
        assert page.status_code == 200
        references = REFERENCE.findall(page.text)
        assert references, page.text

        for reference in references:
            assert not reference.startswith("/"), reference
            assert not urlsplit(reference).scheme, reference
            resolved = urljoin(page_url, reference)
            assert urlsplit(resolved).path.startswith(f"{PREFIX}/try/static/"), resolved
            assert proxied.get(resolved).status_code == 200, resolved


def test_no_client_module_names_a_url_from_the_root() -> None:
    """The modules can only be read, not run, here: what they must not
    do is name a path from the root. What they do instead is resolve
    through `urls.js`, against the deployment's root read off its own
    address (`tests/unit/test_browser_client_files.py` holds the other
    modules to that)."""
    static = files("vinga_server.browser") / "static"
    for module in static.iterdir():
        # `urls.js` takes paths apart (it finds the onboarding mount in
        # whatever was pasted), so it holds slashes that are not
        # addresses; what is asked of it is where its root comes from.
        if module.name.endswith(".js") and module.name != "urls.js":
            script = module.read_text()
            assert not re.search(r"""["'`]/(?!/)""", script), (
                f"a root-relative URL in {module.name}"
            )
    assert URLS_ROOT.search((static / "urls.js").read_text())


def client_root(proxied: TestClient, page_url: str) -> str:
    """The deployment's root as the client computes it: `urls.js`'s
    `ROOT`, resolved against the address the page loads it from."""
    page = proxied.get(page_url).text
    module = urljoin(page_url, MODULE.search(page).group(1))
    urls = urljoin(module, "urls.js")
    assert proxied.get(urls).status_code == 200, urls
    relative = URLS_ROOT.search(proxied.get(urls).text)
    assert relative is not None, "urls.js no longer says where its root is"
    return urljoin(urls, relative.group(1))


@pytest.mark.parametrize("spelling", ["/try/", "/try"])
def test_the_client_s_root_is_the_deployment_s_under_the_prefix(spelling: str) -> None:
    with behind_a_prefix() as proxied:
        root = client_root(proxied, f"http://testserver{PREFIX}{spelling}")

        assert urlsplit(root).path == f"{PREFIX}/"
        assert urlsplit(urljoin(root, "try/redeem")).path == f"{PREFIX}{REDEEM_PATH}"


def test_the_browser_s_whole_way_in_stays_under_the_prefix() -> None:
    """Redeem, check in and connect, each at the address the client
    resolves: the redemption beside the page, the check-in under the
    onboarding path the redemption handed over, and the socket at the
    path the page names, all against the root the client reads off its
    own module, with the identity and the token offered as a browser
    offers them."""
    with behind_a_prefix() as proxied:
        page_url = f"http://testserver{PREFIX}/try/"
        page = proxied.get(page_url).text
        root = client_root(proxied, page_url)
        token = proxied.post(f"{PREFIX}/api/runtime/try-links", headers=BEARER).json()["page"]
        body = proxied.post(
            urljoin(root, "try/redeem"),
            json={"token": token.removeprefix("/try/#")},
            headers=SAME_ORIGIN,
        ).json()
        reply = proxied.post(
            urljoin(root, body["onboarding_path"]),
            json={"board": {"type": "vinga-browser"}},
            headers={"Device-Id": body["mac"], "Client-Id": body["client_id"]},
        ).json()
        socket = urljoin(root, SOCKET.search(page).group(1))

        assert urlsplit(socket).path.startswith(f"{PREFIX}/")
        with proxied.websocket_connect(
            urlsplit(socket).path,
            subprotocols=[
                BROWSER_SUBPROTOCOL,
                f"vinga.mac.{body['mac'].replace(':', '')}",
                f"vinga.client.{body['client_id']}",
                f"vinga.token.{reply['websocket']['token']}",
            ],
        ) as connected:
            connected.send_json(HELLO)
            assert connected.receive_json()["type"] == "hello"


def test_the_onboarding_path_a_redemption_hands_over_resolves_under_the_prefix() -> None:
    with behind_a_prefix() as proxied:
        token = proxied.post(f"{PREFIX}/api/runtime/try-links", headers=BEARER).json()["page"]
        token = token.removeprefix("/try/#")
        page_url = f"http://testserver{PREFIX}/try/"
        redeem_url = urljoin(page_url, "redeem")
        assert urlsplit(redeem_url).path == f"{PREFIX}{REDEEM_PATH}"

        body = proxied.post(redeem_url, json={"token": token}, headers=SAME_ORIGIN).json()
        relative = body["onboarding_path"]
        assert not relative.startswith("/"), relative
        root = urljoin(page_url, "../")
        check_in = urljoin(root, relative)
        assert urlsplit(check_in).path.startswith(f"{PREFIX}/x/"), check_in

        reply = proxied.post(
            check_in,
            json={**SYSTEM_INFO, "board": {"type": "vinga-browser"}},
            headers={"Device-Id": body["mac"], "Client-Id": body["client_id"]},
        )
        assert reply.status_code == 200
        assert reply.json()["websocket"]["token"]
