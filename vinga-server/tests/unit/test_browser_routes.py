"""The browser client's home and an unbound browser's start (#613).

`GET /talk/` serves the page keyless and `no-store`, under a
Content-Security-Policy that keeps its scripts and connections on its
own origin; `GET /talk/static/<version>/<name>` serves the allowlisted
modules immutable and nothing else (D2, D2b). `POST
/x/<key>/browser-identity` mints an identity on the onboarding alias, behind
its key guard, on every deployment (D4; #612 removed D4a's refusals,
since no unbound device is admitted any more). All of it is mounted
with the alias and never without it.
"""

import re
import uuid
from importlib.resources import files
from urllib.parse import urljoin

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import TEST_API_SECRET
from tests.support.checkin import SYSTEM_INFO, unbound_config
from tests.support.configs import config_with_agent, load_config_from_data
from tests.support.leaks import chain
from tests.support.registry import booted
from vinga_server.app import create_app
from vinga_server.browser import (
    ALLOWLIST,
    PAGE_PATH,
    STATIC_PATH,
    Assets,
    build_router,
)
from vinga_server.config import ConfigError
from vinga_server.config.models import BROWSER_MOUNT_PATH, ServerConfig
from vinga_server.onboarding import onboarding_key, onboarding_path
from vinga_server.onboarding.browser import CLIENT_ID_NAMESPACE

AUTH_SECRET_ENV = "VINGA_AUTH_SECRET"

# The module as the page names it: relative to the page, which every
# caller here fetched at `/talk/`.
MODULE = re.compile(r'src="(static/([0-9a-f]+)/page\.js)"')

BEARER = {"Authorization": f"Bearer {TEST_API_SECRET}"}


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(AUTH_SECRET_ENV, "a-fixed-secret-for-the-browser-routes")


def short_path(client: TestClient) -> str:
    return onboarding_path(onboarding_key(client.app.state.composition.server))


def module_path(page: str) -> str:
    """The module's path, resolved against the page at `/talk/` the way a
    browser resolves it."""
    match = MODULE.search(page)
    assert match is not None, page
    return urljoin(PAGE_PATH, match.group(1))


def packaged(name: str) -> bytes:
    return (files("vinga_server.browser") / "static" / name).read_bytes()


def client(page: bytes) -> dict[str, bytes]:
    """Every allowlisted file as it ships, with `page.js` replaced: a
    whole client standing for another release."""
    return {name: packaged(name) for name in ALLOWLIST} | {"page.js": page}


# --- the page ------------------------------------------------------------


@pytest.mark.parametrize("path", ["/talk/", "/talk"])
def test_the_page_is_served_keyless_and_never_stored(path: str) -> None:
    with TestClient(create_app(config_with_agent())) as client:
        answer = client.get(path, follow_redirects=False)

    assert answer.status_code == 200
    assert answer.headers["content-type"] == "text/html; charset=utf-8"
    assert answer.headers["cache-control"] == "no-store"
    assert answer.headers["referrer-policy"] == "no-referrer"
    assert answer.headers["x-content-type-options"] == "nosniff"


def test_the_page_keeps_its_scripts_and_connections_on_its_own_origin() -> None:
    with TestClient(create_app(config_with_agent())) as client:
        policy = client.get("/talk/").headers["content-security-policy"]

    directives = dict(
        (part.split(" ", 1) + [""])[:2] for part in (one.strip() for one in policy.split(";"))
    )
    assert directives["default-src"] == "'none'"
    assert directives["script-src"] == "'self'"
    assert directives["connect-src"] == "'self'"
    assert directives["frame-ancestors"] == "'none'"
    assert directives["base-uri"] == "'none'"
    assert "unsafe-inline" not in policy
    assert "unsafe-eval" not in policy


def test_the_page_names_its_module_under_the_current_version_and_it_is_served() -> None:
    with TestClient(create_app(config_with_agent())) as client:
        path = module_path(client.get("/talk/").text)
        answer = client.get(path)

    assert path == f"{STATIC_PATH}/{Assets.packaged().version}/page.js"
    assert answer.status_code == 200
    assert answer.content == packaged("page.js")
    assert answer.headers["content-type"] == "text/javascript; charset=utf-8"
    assert answer.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert answer.headers["referrer-policy"] == "no-referrer"
    assert answer.headers["x-content-type-options"] == "nosniff"


def test_every_allowlisted_file_ships_in_the_package() -> None:
    """The page and every name the allowlist serves are package data, so
    a file missing from the source tree fails here rather than in a
    browser."""
    assert packaged("index.html")
    for name in ALLOWLIST:
        assert packaged(name)


# --- what is not served ---------------------------------------------------


def unserved(client: TestClient) -> tuple[int, bytes]:
    answer = client.get("/never-served-by-anything")
    return answer.status_code, answer.content


@pytest.mark.parametrize(
    "name",
    [
        # Files that are in the package but are not the client.
        "index.html",
        "assets.py",
        "router.py",
        "__init__.py",
        # And every way of climbing out that reaches the handler as one
        # segment, the separator escaped.
        "..",
        "%2e%2e",
        "..%2Fassets.py",
        "..%2F..%2Fapp.py",
        "%2E%2E%2F__init__.py",
        "page.js%00",
        "PAGE.JS",
    ],
)
def test_only_the_allowlist_is_served(name: str) -> None:
    with TestClient(create_app(config_with_agent())) as client:
        version = Assets.packaged().version
        answer = client.get(f"{STATIC_PATH}/{version}/{name}")
        expected = unserved(client)

    assert (answer.status_code, answer.content) == expected


@pytest.mark.parametrize(
    "path",
    [
        "/talk/static/page.js",
        "/talk/static/../browser/assets.py",
        "/talk/static/{version}/../assets.py",
        "/talk/static/{version}/static/page.js",
        "/talk/index.html",
        "/talk/page.js",
    ],
)
def test_no_other_path_under_try_reaches_a_file(path: str) -> None:
    with TestClient(create_app(config_with_agent())) as client:
        answer = client.get(path.format(version=Assets.packaged().version))
        expected = unserved(client)

    assert (answer.status_code, answer.content) == expected


@pytest.mark.parametrize("trailing", ["", "/"])
@pytest.mark.parametrize("version", ["0000000000000000", "not-a-version"])
def test_a_refused_module_is_the_stock_404_in_either_spelling(trailing: str, version: str) -> None:
    """Both spellings of a module path reach the handler, so a refused
    one is never answered by the router's slash redirect instead, whose
    `Location` would repeat the path and the query it was asked with."""
    sentinel = "SENTINEL-try-static-query"
    with TestClient(create_app(config_with_agent())) as client:
        answer = client.get(
            f"{STATIC_PATH}/{version}/page.js{trailing}?{sentinel}=1",
            follow_redirects=False,
        )
        expected = unserved(client)

    assert (answer.status_code, answer.content) == expected
    assert "location" not in answer.headers
    assert sentinel not in answer.text
    assert all(sentinel not in value for value in answer.headers.values())


@pytest.mark.parametrize("trailing", ["", "/"])
def test_a_module_is_served_in_either_spelling(trailing: str) -> None:
    with TestClient(create_app(config_with_agent())) as client:
        path = module_path(client.get("/talk/").text)
        answer = client.get(f"{path}{trailing}", follow_redirects=False)

    assert answer.status_code == 200
    assert answer.content == packaged("page.js")


def test_another_version_is_not_served() -> None:
    with TestClient(create_app(config_with_agent())) as client:
        answer = client.get(f"{STATIC_PATH}/0000000000000000/page.js")
        expected = unserved(client)

    assert (answer.status_code, answer.content) == expected


def test_a_new_version_is_a_new_path_and_the_old_one_is_refused() -> None:
    """The upgrade, in two servers: the page the first serves names one
    module path, the page the second serves names another, and the
    second refuses the first's. A browser holding the old module cached
    can never be told to import it by a new page (D2b)."""
    index = (files("vinga_server.browser") / "static" / "index.html").read_text()
    before = Assets(index, client(b"// the old client\n"))
    after = Assets(index, client(b"// the new client\n"))

    old_app, new_app = FastAPI(), FastAPI()
    old_app.include_router(build_router(None, before))
    new_app.include_router(build_router(None, after))
    with TestClient(old_app) as old, TestClient(new_app) as new:
        old_path = module_path(old.get("/talk/").text)
        new_path = module_path(new.get("/talk/").text)

        assert old.get(old_path).content == b"// the old client\n"
        assert new.get(new_path).content == b"// the new client\n"
        assert new_path != old_path
        assert new.get(old_path).status_code == 404


def test_the_version_is_the_served_bytes_and_nothing_else() -> None:
    index = "<script src='{{assets}}/page.js'></script>"
    one = Assets(index, client(b"a"))

    assert Assets(index, client(b"a")).version == one.version
    assert Assets("<p>another page</p>", client(b"a")).version == one.version
    assert Assets(index, client(b"b")).version != one.version


def test_assets_outside_the_allowlist_cannot_be_served() -> None:
    with pytest.raises(ValueError):
        Assets("", {"page.js": b"", "extra.js": b""})
    with pytest.raises(ValueError):
        Assets("", {})


def test_nothing_is_mounted_with_onboarding_off() -> None:
    config = config_with_agent()
    config.server.onboarding.enabled = False
    with TestClient(create_app(config)) as client:
        version = Assets.packaged().version
        assert client.get("/talk/").status_code == 404
        assert client.get(f"{STATIC_PATH}/{version}/page.js").status_code == 404


@pytest.mark.parametrize("path", ["/talk/", "/talk/xiaozhi-ota-5e1d9c0b/"])
def test_an_ota_path_under_the_page_is_refused(path: str) -> None:
    """The OTA router is registered first, so an OTA path at or under
    /talk/ would answer the page's own requests. Refused, naming the
    prefix and never the configured segment."""
    with pytest.raises(ConfigError) as caught:
        load_config_from_data({"server": {"ota_path": path}})
    message = str(caught.value)

    assert f"{BROWSER_MOUNT_PATH}/ is reserved" in message
    assert "xiaozhi-ota-5e1d9c0b" not in chain(caught.value)


@pytest.mark.parametrize("path", ["/talkative/", "/try/"])
def test_a_path_that_is_not_under_the_page_is_allowed(path: str) -> None:
    """One merely starting with the page's prefix, and the page's old
    prefix, which moved with the page (#612, Q11): the reservation reads
    the one constant the routes do."""
    config = load_config_from_data({"server": {"ota_path": path}})

    assert config.server.ota_path == path


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/try/"),
        ("GET", "/try"),
        ("GET", "/try/static/{version}/page.js"),
        ("POST", "/try/redeem"),
        ("POST", "/try/redeem/"),
        ("POST", "{alias}try-identity"),
        ("POST", "{alias}try-identity/"),
    ],
)
def test_the_page_s_old_paths_answer_the_stock_404(method: str, path: str) -> None:
    """The page moved to `/talk/` and its identity route to
    `browser-identity` with no alias left behind (#612, Q11): each old
    path answers exactly what a path nobody serves answers."""
    with TestClient(create_app(booted(default_agent="assistant"), from_store=True)) as client:
        address = path.format(version=Assets.packaged().version, alias=short_path(client))
        old = client.request(method, address, json={"token": "A" * 43})
        unserved = client.request(method, "/never-served-by-anything", json={"token": "A" * 43})

    assert old.status_code == 404
    assert old.content == unserved.content


def test_the_ota_path_description_names_the_page_reservation() -> None:
    description = ServerConfig.model_fields["ota_path"].description or ""

    assert f"`{BROWSER_MOUNT_PATH}/`" in description


# --- the unbound start ----------------------------------------------------


def test_a_browser_with_no_identity_is_minted_one_and_shown_a_code() -> None:
    """No default agent: the mint answers an identity, and checking in
    with it at the same alias is answered with a code to claim, which is
    D4's pairing, end to end."""
    with TestClient(create_app(unbound_config())) as client:
        base = short_path(client)
        minted = client.post(f"{base}browser-identity")
        assert minted.status_code == 200
        assert minted.headers["cache-control"] == "no-store"
        body = minted.json()
        assert set(body) == {"mac", "client_id"}
        first = int(body["mac"].split(":")[0], 16)
        assert first & 0x02 and not first & 0x01
        assert body["client_id"] == str(uuid.uuid5(CLIENT_ID_NAMESPACE, body["mac"]))

        reply = client.post(
            base,
            json={**SYSTEM_INFO, "board": {"type": "vinga-browser"}},
            headers={"Device-Id": body["mac"], "Client-Id": body["client_id"]},
        )
        assert reply.status_code == 200
        assert reply.json()["activation"]["code"].isdigit()


def test_each_start_is_a_new_identity() -> None:
    with TestClient(create_app(unbound_config())) as client:
        base = short_path(client)
        first = client.post(f"{base}browser-identity").json()
        second = client.post(f"{base}browser-identity").json()

    assert first != second


def _checked_in(client: TestClient, base: str, minted: dict[str, str]) -> dict:
    """The check-in a minted browser makes next, as the page makes it."""
    reply = client.post(
        base,
        json={**SYSTEM_INFO, "board": {"type": "vinga-browser"}},
        headers={"Device-Id": minted["mac"], "Client-Id": minted["client_id"]},
    )
    assert reply.status_code == 200
    return reply.json()


def test_a_minted_browser_pairs_and_is_admitted_only_once_claimed() -> None:
    """The admission path M1 opens is no wider than the one it closes
    (#612, plan review round 2): with a default agent set, which used to
    be the mint's refusal, a freshly minted identity checks in, is
    offered a code and no token, and is still refused a token at its
    next check-in, until an operator claims that code. Then, and only
    then, it is admitted, bound to the default agent the claim named
    none instead of."""
    config = booted(default_agent="assistant")
    with TestClient(create_app(config, from_store=True)) as client:
        base = short_path(client)
        minted = client.post(f"{base}browser-identity")
        assert minted.status_code == 200
        identity = minted.json()

        first = _checked_in(client, base, identity)
        assert first["websocket"]["token"] == ""
        code = first["activation"]["code"]
        assert code.isdigit()

        again = _checked_in(client, base, identity)
        assert again["websocket"]["token"] == ""
        assert again["activation"]["code"] == code

        claimed = client.post(f"/api/devices/pending/{code}", json={}, headers=BEARER)
        assert claimed.status_code == 200, claimed.text

        admitted = _checked_in(client, base, identity)
        bound = client.get(f"/api/devices/{identity['mac']}", headers=BEARER)

    assert admitted["websocket"]["token"] != ""
    assert "activation" not in admitted
    assert bound.json()["entity"]["agents"] == ["assistant"]


# Carried by the failing read, so an answer that repeated anything of the
# failure would carry it too.
READ_FAILURE = "sk-test-browser-mint-read-failure-never-a-real-credential"


def _failing_read(*_: object) -> None:
    raise RuntimeError(f"disk I/O error near {READ_FAILURE}")


def test_a_mint_does_not_depend_on_reading_the_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mint used to ask the bindings whether a fresh MAC would be
    admitted unbound, and refused with a 503 when the database could not
    say (D4a). No unbound MAC is admitted since #612, so there is nothing
    to ask: a mint while the read is failing answers an identity, carries
    nothing of the failure, and leaves the pending table alone."""
    with TestClient(create_app(booted(default_agent="assistant"), from_store=True)) as client:
        with monkeypatch.context() as failing:
            failing.setattr("vinga_server.device.bindings.read_live_binding", _failing_read)
            minted = client.post(f"{short_path(client)}browser-identity")
        pending = client.app.state.composition.pending.listing()

    assert minted.status_code == 200
    assert set(minted.json()) == {"mac", "client_id"}
    assert minted.headers["cache-control"] == "no-store"
    assert READ_FAILURE not in minted.text
    assert pending == ()


@pytest.mark.parametrize("wrong", ["AAAAAAAA", "aaaaaaab", "nonsense-key"])
def test_a_wrong_key_meets_the_alias_stock_404(wrong: str) -> None:
    with TestClient(create_app(unbound_config())) as client:
        missed = client.post(f"/x/{wrong}/browser-identity")
        expected = client.post(f"/x/{wrong}/")

    assert missed.status_code == expected.status_code == 404
    assert missed.content == expected.content
    assert "mac" not in missed.text


def test_with_auth_off_the_mint_is_on_the_keyless_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(AUTH_SECRET_ENV, raising=False)
    config = unbound_config()
    config.server.auth.enabled = False
    with TestClient(create_app(config)) as client:
        assert short_path(client) == "/x/"
        assert client.post("/x/browser-identity").status_code == 200
        assert client.post("/x/browser-identity/").status_code == 200


def test_the_mint_is_a_post() -> None:
    with TestClient(create_app(unbound_config())) as client:
        assert client.get(f"{short_path(client)}browser-identity").status_code == 405
