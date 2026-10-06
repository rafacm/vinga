"""Every route this server serves, listed from the application's own table.

The inventory is read from the app rather than written beside it, and
compared with a literal that names, for each route, what stands in
front of it. So a route added anywhere (a router included, a probe
registered, a path spelled twice) fails here until somebody writes down
who may reach it, which is the moment an unauthenticated route stops
being an accident (#613's inventories-by-tooling lens).

The guards named are then checked rather than trusted: every route the
table says the onboarding key guards answers a wrong key with the stock
404, the websocket refuses an upgrade with no token, and the API's mount
refuses a request with no bearer token.
"""

from collections import Counter

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.support.configs import config_with_agent
from vinga_server.app import create_app

# Who may reach each route, in words. The words are for the reader; the
# keys are what the test holds the application to.
PUBLIC_PROBE = "public: a supervisor's probe, answering literals only"
TOKEN_ISSUER = "public: the OTA endpoint, behind the configured segment"
ONBOARDING_KEY = "the onboarding key"
PUBLIC_PAGE = "public: the browser client's static page and modules"
TRY_TOKEN = "a try link's token, spent once, presented from the page's own origin"
DEVICE_TOKEN = "a device token, checked before the accept"
API_BEARER = "the configuration API's bearer token"

EXPECTED = {
    ("http", "/healthz/", "GET"): PUBLIC_PROBE,
    ("http", "/healthz", "GET"): PUBLIC_PROBE,
    ("http", "/readyz/", "GET"): PUBLIC_PROBE,
    ("http", "/readyz", "GET"): PUBLIC_PROBE,
    ("http", "/xiaozhi/ota/", "POST"): TOKEN_ISSUER,
    ("http", "/xiaozhi/ota/", "GET"): TOKEN_ISSUER,
    ("http", "/xiaozhi/ota", "POST"): TOKEN_ISSUER,
    ("http", "/xiaozhi/ota", "GET"): TOKEN_ISSUER,
    ("http", "/xiaozhi/ota/activate/", "POST"): TOKEN_ISSUER,
    ("http", "/xiaozhi/ota/activate", "POST"): TOKEN_ISSUER,
    ("http", "/x/{key}/", "POST"): ONBOARDING_KEY,
    ("http", "/x/{key}/", "GET"): ONBOARDING_KEY,
    ("http", "/x/{key}", "POST"): ONBOARDING_KEY,
    ("http", "/x/{key}", "GET"): ONBOARDING_KEY,
    ("http", "/x/{key}/activate/", "POST"): ONBOARDING_KEY,
    ("http", "/x/{key}/activate", "POST"): ONBOARDING_KEY,
    ("http", "/x/{key}/try-identity/", "POST"): ONBOARDING_KEY,
    ("http", "/x/{key}/try-identity", "POST"): ONBOARDING_KEY,
    ("http", "/try/", "GET"): PUBLIC_PAGE,
    ("http", "/try", "GET"): PUBLIC_PAGE,
    ("http", "/try/static/{version}/{name}/", "GET"): PUBLIC_PAGE,
    ("http", "/try/static/{version}/{name}", "GET"): PUBLIC_PAGE,
    ("http", "/try/redeem/", "POST"): TRY_TOKEN,
    ("http", "/try/redeem", "POST"): TRY_TOKEN,
    ("websocket", "/xiaozhi/v1/", "-"): DEVICE_TOKEN,
    ("mount", "/api", "-"): API_BEARER,
    ("asgi", "/api", "-"): API_BEARER,
}


def served(app) -> Counter[tuple[str, str, str]]:
    """Every (kind, path, method) the application routes, flattened
    through every included router by FastAPI's own iterator, with how
    many times each is registered. Counted rather than collected into a
    set, which would fold a path spelled twice into one entry and keep
    the inventory green over it."""
    table: Counter[tuple[str, str, str]] = Counter()
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        kind = type(route).__name__
        path = context.path or getattr(route, "path", "")
        if kind == "APIRoute":
            table.update(("http", path, method) for method in context.methods or ())
        elif kind == "APIWebSocketRoute":
            table[("websocket", path, "-")] += 1
        elif kind == "Mount":
            table[("mount", path, "-")] += 1
        elif kind == "Route":
            table[("asgi", path, "-")] += 1
        else:
            table[(kind, path, "-")] += 1
    return table


@pytest.fixture
def client():
    with TestClient(create_app(config_with_agent())) as entered:
        yield entered


def test_every_route_is_named_with_what_guards_it(client: TestClient) -> None:
    table = served(client.app)

    twice = sorted(route for route, count in table.items() if count > 1)
    unnamed = set(table) - set(EXPECTED)
    gone = set(EXPECTED) - set(table)
    assert not twice, f"routes registered more than once: {twice}"
    assert not unnamed, f"routes nobody has said who may reach: {sorted(unnamed)}"
    assert not gone, f"routes named here that the app no longer serves: {sorted(gone)}"


def test_every_http_route_is_served_in_both_spellings(client: TestClient) -> None:
    """A path served in one spelling only is answered in the other by the
    router's slash redirect, before any handler or guard has run, with a
    `Location` repeating the path and query it was asked with. Served in
    both, every request reaches its handler, so what a handler refuses is
    refused by the handler and nothing else."""
    table = served(client.app)
    http = {(path, method) for (kind, path, method) in table if kind == "http"}

    def other(path: str) -> str:
        return path[:-1] if path.endswith("/") else f"{path}/"

    lonely = sorted((path, method) for path, method in http if (other(path), method) not in http)
    assert not lonely, f"routes served in one spelling only: {lonely}"


# A query value shaped so a substring search for it cannot match by
# accident, standing for whatever a caller put in a URL it typed.
REDIRECT_SENTINEL = "sentinel-6c1f9a3e-never-in-an-answer"


def test_no_http_route_redirects_a_doubled_slash(client: TestClient) -> None:
    """The router's slash redirect answers a path one slash away from a
    registered one with a 307 whose `Location` repeats the path and the
    query it was asked with, before any handler or guard has run. Every
    HTTP route is served in both spellings (the case above), so nothing
    needs the redirect, and a doubled trailing slash is the spelling no
    route has: it must meet an answer of the application's own, never a
    redirect echoing what was typed. Driven from the route table, so a
    route added later is held to it by existing."""
    table = served(client.app)
    http = sorted({(path, method) for (kind, path, method) in table if kind == "http"})
    assert http

    echoed = []
    for path, method in http:
        concrete = path.format(key="WRONGKEY", version="0000", name="page.js")
        asked = f"{concrete.rstrip('/')}//?s={REDIRECT_SENTINEL}"
        answer = client.request(method, asked, follow_redirects=False)
        if (
            300 <= answer.status_code < 400
            or "location" in answer.headers
            or REDIRECT_SENTINEL in answer.text
            or REDIRECT_SENTINEL in str(answer.headers)
        ):
            echoed.append((method, asked, answer.status_code))
    assert not echoed, f"answered with a redirect or an echo: {echoed}"


def test_the_websocket_does_not_take_a_doubled_slash_either(client: TestClient) -> None:
    """The slash redirect is an `http` scope's: a websocket upgrade one
    slash away from the route is refused, not redirected."""
    ((_, path, _),) = [key for key, guard in EXPECTED.items() if guard == DEVICE_TOKEN]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"{path.rstrip('/')}//?s={REDIRECT_SENTINEL}"):
            pass


KEY_GUARDED = sorted(
    (path, method) for (_, path, method), guard in EXPECTED.items() if guard == ONBOARDING_KEY
)


@pytest.mark.parametrize(("path", "method"), KEY_GUARDED)
def test_every_key_guarded_route_meets_a_wrong_key_with_the_stock_404(
    client: TestClient, path: str, method: str
) -> None:
    answer = client.request(method, path.format(key="WRONGKEY"))
    unserved = client.request(method, "/never-served-by-anything")

    assert answer.status_code == 404
    assert answer.content == unserved.content


TOKEN_GUARDED = sorted(
    (path, method) for (_, path, method), guard in EXPECTED.items() if guard == TRY_TOKEN
)


@pytest.mark.parametrize(("path", "method"), TOKEN_GUARDED)
def test_every_try_token_route_refuses_a_request_with_no_token(
    client: TestClient, path: str, method: str
) -> None:
    """From the page's own origin, so the token is the only thing
    missing."""
    answer = client.request(method, path, json={}, headers={"Sec-Fetch-Site": "same-origin"})

    assert answer.status_code == 403
    assert set(answer.json()) == {"error"}


def test_the_websocket_refuses_an_upgrade_with_no_token(client: TestClient) -> None:
    ((_, path, _),) = [key for key, guard in EXPECTED.items() if guard == DEVICE_TOKEN]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(path):
            pass


@pytest.mark.parametrize("path", ["/api", "/api/", "/api/devices"])
def test_the_api_refuses_a_request_with_no_bearer_token(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401
