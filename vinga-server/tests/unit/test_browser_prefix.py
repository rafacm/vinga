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

PREFIX = "/vinga"
BEARER = {"Authorization": f"Bearer {TEST_API_SECRET}"}
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}

REFERENCE = re.compile(r'(?:src|href)="([^"]*)"')


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


def test_the_page_script_names_no_url_from_the_root() -> None:
    """The module can only be read, not run, here: what it must not do
    is name a path from the root, and what it does instead is resolve
    against its own address."""
    script = (files("vinga_server.browser") / "static" / "page.js").read_text()

    assert not re.search(r"""["'`]/(?!/)""", script), "a root-relative URL in page.js"
    assert "import.meta.url" in script


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
