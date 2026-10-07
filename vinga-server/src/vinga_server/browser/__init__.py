"""The browser client this server serves, and the routes it needs.

A browser is a device here, speaking stock xiaozhi over the same
websocket edge a board does (#613); nothing behind the edge knows it is
a browser. What is the browser's own is in this package: the static
client under `static/` and what serves it (`assets`), and the routes the
application mounts as one router (`router`): the keyless page, its
versioned modules, the redemption of a try link, and the identity an
unbound browser starts from.
"""

from .assets import ALLOWLIST, PAGE_PATH, STATIC_PATH, Assets
from .router import (
    REDEEM_PATH,
    REDEEM_REFUSED,
    TRY_IDENTITY_SEGMENT,
    build_router,
    same_origin,
    try_identity,
)

__all__ = [
    "ALLOWLIST",
    "PAGE_PATH",
    "REDEEM_PATH",
    "REDEEM_REFUSED",
    "STATIC_PATH",
    "TRY_IDENTITY_SEGMENT",
    "Assets",
    "build_router",
    "same_origin",
    "try_identity",
]
