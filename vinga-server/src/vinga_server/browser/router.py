"""Where the browser client is served, and how an unbound one starts.

Three things, mounted together whenever onboarding is enabled, since a
browser needs the onboarding alias to check in at all (#613, D2):

- `GET /try/`, the page, keyless and `no-store`;
- `GET /try/static/<version>/<name>`, its modules, immutable;
- `POST /x/<key>/try-identity`, on the onboarding alias and behind its
  key guard, which mints an identity for a browser that holds none
  (D4). A wrong key meets the alias's stock 404, through the same
  guard every other alias route stands behind.

The mint refuses while a default agent is set (D4a). A default agent
admits every unknown MAC without a code, so a browser minted there
would reach an agent unbound, which is what the issue rules out; until
#612 makes every unbound device pair, a browser on such a deployment
starts from a try link instead. The question asked is the check-in's
own, about the identity just minted: would this MAC resolve to an
agent with nobody having bound it? A minted MAC is new, so it does
exactly when a default agent covers it, and asking the bindings rather
than reading the default agent keeps one rule rather than two that
could disagree. When the database cannot be read, the bindings answer
from the served configuration instead, and an empty answer from there
cannot say no default agent is set, only that none was when it was
loaded; the mint refuses that too, with a 503 a retry may outlive. A
refusal hands nothing over and writes nothing.

The refusal is asked at the mint and nowhere after it, so one window
stays open, deliberately. A browser minted while no default agent is
set, which never pairs, is admitted without a code once an operator
later sets one: its MAC is unbound, and a default agent covers every
unbound MAC. That adds no capability. D4a is a product rule (a cleared
browser pairs), not an access boundary: under a default agent the stock
OTA check-in hands a token to any unknown MAC, so whoever holds the
onboarding path can already reach the default agent with a made-up MAC,
and an identity minted earlier gains nothing over that. Remembering
which MACs were minted, to make them pair anyway, would be the second
admission rule D4a exists to avoid; #612 closes the window by making
every unbound device pair.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from vinga_server.composition import Composition
from vinga_server.config.models import ONBOARDING_MOUNT_PATH
from vinga_server.device.bindings import DeviceBindings
from vinga_server.onboarding.browser import mint
from vinga_server.onboarding.keys import _guarded, onboarding_path
from vinga_server.ota.router import spellings

from .assets import ASSET_HEADERS, PAGE_HEADERS, PAGE_PATH, STATIC_PATH, Assets

# What a browser appends to the onboarding path to ask for an identity.
TRY_IDENTITY_SEGMENT = "try-identity"

# What the mint answers while a default agent is set. Fixed, and the
# page shows it as it stands.
TRY_LINK_NEEDED = (
    "This server connects every new device to its default agent, so a browser "
    "joins it through a try link rather than by pairing. Ask the person who "
    "runs it for one."
)

# What the mint answers when it cannot find out whether a new browser
# would be admitted unbound: the database could not be read, and the
# served configuration answering in its place cannot be trusted about a
# default agent it does not name. Fixed, saying nothing of the failure,
# which the bindings view has already logged; a retry may succeed, which
# is why it is a 503 and not the try-link refusal.
TRY_IDENTITY_UNAVAILABLE = (
    "This server cannot check right now whether a new browser may start here. "
    "Try again in a moment."
)

# An identity is the browser's own from the moment it is handed over:
# nothing between here and the page keeps a copy.
_NO_STORE = {"Cache-Control": "no-store"}


def build_router(key: str | None, assets: Assets | None = None) -> APIRouter:
    """The browser's routes. `key` is the onboarding key the alias is
    guarded by, None when it mounts keyless; `assets` is the client to
    serve, the packaged one unless a suite hands it another."""
    served = assets if assets is not None else Assets.packaged()
    router = APIRouter()

    async def page() -> Response:
        return Response(served.page(), media_type="text/html; charset=utf-8", headers=PAGE_HEADERS)

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

    if key is None:
        for spelling in spellings(f"{onboarding_path(None)}{TRY_IDENTITY_SEGMENT}/"):
            router.post(spelling)(try_identity)
    else:
        for spelling in spellings(f"{ONBOARDING_MOUNT_PATH}/{{key}}/{TRY_IDENTITY_SEGMENT}/"):
            router.post(spelling)(_guarded(key, try_identity))
    return router


async def try_identity(request: Request) -> Response:
    """A fresh identity for a browser that holds none, or the fixed
    refusal while a default agent would admit it unbound, or while this
    server cannot find out whether one would."""
    comp: Composition = request.app.state.composition
    bindings: DeviceBindings = comp.bindings
    identity = mint()
    bound = await bindings.resolve(identity.mac)
    if bound.names:
        return JSONResponse({"error": TRY_LINK_NEEDED}, status_code=409, headers=_NO_STORE)
    if not bound.authoritative:
        # The activation ceremony's `"unreadable"` arm, for the same
        # reason: an empty answer from the snapshot fallback is not the
        # database saying no default agent is set, it is this server not
        # having been able to read it. A default agent set since the
        # snapshot was loaded would admit the identity minted here at
        # its next check-in, with no code. The warning naming the
        # failure is already in the log, from the view itself.
        return JSONResponse({"error": TRY_IDENTITY_UNAVAILABLE}, status_code=503, headers=_NO_STORE)
    return JSONResponse({"mac": identity.mac, "client_id": identity.client_id}, headers=_NO_STORE)
