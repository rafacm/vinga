"""The browser client this server serves, and the routes it needs.

A browser is a device here, speaking stock xiaozhi over the same
websocket edge a board does (#613); nothing behind the edge knows it is
a browser. What is the browser's own is in this package: the static
client under `static/` and what serves it (`assets`), and the routes the
application mounts as one router (`router`): the keyless page, its
versioned modules, and the identity an unbound browser starts from.
"""

from .assets import ALLOWLIST, PAGE_PATH, STATIC_PATH, Assets
from .router import (
    TRY_IDENTITY_SEGMENT,
    TRY_IDENTITY_UNAVAILABLE,
    TRY_LINK_NEEDED,
    build_router,
    try_identity,
)

__all__ = [
    "ALLOWLIST",
    "PAGE_PATH",
    "STATIC_PATH",
    "TRY_IDENTITY_SEGMENT",
    "TRY_IDENTITY_UNAVAILABLE",
    "TRY_LINK_NEEDED",
    "Assets",
    "build_router",
    "try_identity",
]
