"""Where the browser client is served, how an invite link is redeemed, and
how an unbound browser starts.

Four things, mounted together whenever onboarding is enabled, since a
browser needs the onboarding alias to check in at all (#613, D2):

- `GET /try/`, the page, keyless and `no-store`;
- `GET /try/static/<version>/<name>`, its modules, immutable;
- `POST /try/redeem`, which spends an invite link's token and binds the
  browser presenting it (D5), keyless because the token is the
  credential, and refused from any origin but the page's own;
- `POST /x/<key>/try-identity`, on the onboarding alias and behind its
  key guard, which mints an identity for a browser that holds none
  (D4). A wrong key meets the alias's stock 404, through the same
  guard every other alias route stands behind.

The page is inert. An invite link carries its token in the URL's fragment,
which no browser sends to any server, so `GET /try/` is the same page
for a person, a link preview, a prefetch and a scanner, and spends
nothing for any of them; only the page's own script, reading the
fragment, can redeem it. The redemption answers the identity and the
onboarding path in its body, which the page keeps and checks in at,
while its own address stays `/try/`.

The mint always mints. It used to refuse while a default agent was set
(D4a), because a default agent admitted every unknown MAC without a
code, and to refuse again when it could not find out whether one was
set. Since #612 an unbound device only pairs, on every deployment, so a
minted identity is admitted only once an operator claims the code its
check-in shows, and there is nothing left for the mint to ask. A mint
hands over an identity and writes nothing.
"""

import json

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from vinga_server.composition import Composition
from vinga_server.config.api import store_dependency
from vinga_server.config.models import BROWSER_MOUNT_PATH, ONBOARDING_MOUNT_PATH
from vinga_server.onboarding.browser import mint
from vinga_server.onboarding.invites import redeem
from vinga_server.onboarding.keys import _guarded, onboarding_path
from vinga_server.ota.router import spellings

from .assets import (
    ASSET_HEADERS,
    COMMON_HEADERS,
    PAGE_HEADERS,
    PAGE_PATH,
    STATIC_PATH,
    Assets,
)

# What a browser appends to the onboarding path to ask for an identity.
TRY_IDENTITY_SEGMENT = "try-identity"

# Where the page redeems an invite link's token.
REDEEM_PATH = f"{BROWSER_MOUNT_PATH}/redeem"

# What every way of not redeeming answers, byte for byte: a token never
# issued, expired, already spent, presented from another origin, or a
# body that is not one. One sentence, so a guesser learns nothing from
# which it got, and the page shows it as it stands.
REDEEM_REFUSED = (
    "This invite link cannot be used: it has been opened already, it has expired, or "
    "the server has restarted since it was made. Ask the person who runs this server "
    "for a new one."
)

# How much of a redemption's body is read before it is refused. A token
# is forty-three characters, and its JSON object a few more; anything
# near this is not one.
REDEEM_BODY_LIMIT = 1024

# An identity is the browser's own from the moment it is handed over:
# nothing between here and the page keeps a copy.
_NO_STORE = {"Cache-Control": "no-store"}

# And what a redemption's answer carries, either way: not stored, not
# named to anybody in a `Referer`, not read as another type.
_REDEEM_HEADERS = {**COMMON_HEADERS, **_NO_STORE}


def build_router(key: str | None, assets: Assets | None = None) -> APIRouter:
    """The browser's routes. `key` is the onboarding key the alias is
    guarded by, None when it mounts keyless; `assets` is the client to
    serve, the packaged one unless a suite hands it another."""
    served = assets if assets is not None else Assets.packaged()
    router = APIRouter()

    async def page(request: Request) -> Response:
        return Response(
            served.page(slashed=request.url.path.endswith("/")),
            media_type="text/html; charset=utf-8",
            headers=PAGE_HEADERS,
        )

    async def static(version: str, name: str) -> Response:
        found = served.file(version, name)
        if found is None:
            # Raised rather than composed, so the answer is the stock 404
            # an unserved path gets, byte for byte.
            raise HTTPException(status_code=404)
        content, media_type = found
        return Response(content, media_type=media_type, headers=ASSET_HEADERS)

    for spelling in spellings(PAGE_PATH):
        router.get(spelling)(page)
    # Both spellings, so every request for a module reaches `static` and
    # a refused one meets its 404. With one, the router's slash redirect
    # would answer the other first, with a `Location` repeating whatever
    # version and query it was asked with.
    for spelling in spellings(f"{STATIC_PATH}/{{version}}/{{name}}/"):
        router.get(spelling)(static)

    async def redeem_link(request: Request) -> Response:
        """Spend an invite link's token and bind the browser presenting it,
        or the one refusal.

        The origin is asked first and the body second, and both before
        the token is claimed, so a request from another origin or with a
        body that is not one spends nothing."""
        if not same_origin(request):
            return _refused()
        token = await _token_of(request)
        comp: Composition = request.app.state.composition
        # The server's own configuration store, over the engine its
        # lifespan opened: the store the bindings this browser is about
        # to check in against are read from.
        store = next(store_dependency(comp.api))
        identity = await redeem(comp.invites, token, store)
        if identity is None:
            return _refused()
        return JSONResponse(
            {
                "mac": identity.mac,
                "client_id": identity.client_id,
                # Relative to the deployment's root rather than from the
                # server's: behind a proxy that serves this deployment
                # under a path prefix, the page resolves it against its
                # own address minus `try/`, which keeps the prefix.
                "onboarding_path": onboarding_path(key).removeprefix("/"),
            },
            headers=_REDEEM_HEADERS,
        )

    for spelling in spellings(f"{REDEEM_PATH}/"):
        router.post(spelling)(redeem_link)

    if key is None:
        for spelling in spellings(f"{onboarding_path(None)}{TRY_IDENTITY_SEGMENT}/"):
            router.post(spelling)(try_identity)
    else:
        for spelling in spellings(f"{ONBOARDING_MOUNT_PATH}/{{key}}/{TRY_IDENTITY_SEGMENT}/"):
            router.post(spelling)(_guarded(key, try_identity))
    return router


async def try_identity(request: Request) -> Response:
    """A fresh identity for a browser that holds none. Unconditional: what
    admits it is a claim of the code its check-in is then shown, never
    the mint (#612)."""
    identity = mint()
    return JSONResponse({"mac": identity.mac, "client_id": identity.client_id}, headers=_NO_STORE)


def same_origin(request: Request) -> bool:
    """Whether this request comes from a page of this server's own
    origin, which for a redemption is the page at `/try/`.

    The browser says so itself, and nothing else is believed:
    `Sec-Fetch-Site` is set by the browser, never by a page, and a proxy
    in front of this server does not rewrite it, so a redemption is
    admitted exactly when it says `same-origin`. Every engine that can
    run the client (WebCodecs Opus: Chromium 94+, Firefox 130+, Safari
    26) sends it, so a request without it is not this page. `Origin` is
    not a fallback: comparing it with the `Host` a request reached sees
    the authority and not the scheme, since a TLS-terminating proxy
    hands this server `http` for a page loaded over `https`, so a page
    on `http://host` posting to `https://host` would pass it.
    """
    return request.headers.get("sec-fetch-site") == "same-origin"


async def _token_of(request: Request) -> object:
    """What a redemption's body says the token is, or None when it is
    not a JSON object of exactly that one member, or is longer than any
    such object could be. Never raised from: what a parser says about a
    body quotes the body, and this one may hold a credential."""
    received = bytearray()
    async for chunk in request.stream():
        received += chunk
        if len(received) > REDEEM_BODY_LIMIT:
            return None
    try:
        body = json.loads(received)
    except ValueError:
        return None
    if not isinstance(body, dict) or set(body) != {"token"}:
        return None
    return body["token"]


def _refused() -> Response:
    return JSONResponse({"error": REDEEM_REFUSED}, status_code=403, headers=_REDEEM_HEADERS)
