"""What the browser client is made of, and how each part is served.

The page and its modules ship inside the package, under `static/`, and
are served from a fixed allowlist rather than from a directory: a name
that is not in `ALLOWLIST` is not a file this server has, whatever the
filesystem beside it holds, so there is no listing and no path to
traverse (#613, D2).

Modules are addressed by version, `/try/static/<version>/<name>`, named
by the page relative to itself so a path prefix in front of the
deployment is kept, and
served immutable; the page that names them is served `no-store`, so a
page fetched after an upgrade names the new set and can never import a
module a browser cached from the old one, and a request for any other
version answers 404 (D2b). The version is a digest of the allowlisted
files' bytes rather than the server's build revision, which is what the
plan named: a wheel install reports its revision as `unknown` for every
release, and a working tree's `-dirty` revision does not move while its
files are edited, so a revision would put two different module sets
behind one immutable URL in exactly the two places this client is
developed and first installed. A digest moves exactly when a served
byte does.

Nothing here is secret, so nothing here needs a key: the onboarding
path a browser checks in at reaches the page in a response body, never
in a URL the page is loaded from (Q2).
"""

import hashlib
from collections.abc import Mapping
from importlib.resources import files

from vinga_server.config.models import BROWSER_MOUNT_PATH
from vinga_server.device.boundary import WEBSOCKET_PATH

# Where the page is served, and where its modules are served under it.
# From the constant `ota_path`'s validator reserves, so where the client
# is served and what an OTA path may not be are one fact.
PAGE_PATH = f"{BROWSER_MOUNT_PATH}/"
STATIC_PATH = f"{BROWSER_MOUNT_PATH}/static"

# Every file served under `STATIC_PATH`, with its media type. The whole
# set: adding a module to the client means adding its name here.
_MODULE = "text/javascript; charset=utf-8"
ALLOWLIST: Mapping[str, str] = {
    "page.js": _MODULE,
    "identity.js": _MODULE,
    "ota.js": _MODULE,
    "wire.js": _MODULE,
    "tools.js": _MODULE,
    "audio.js": _MODULE,
    "audio-worklet.js": _MODULE,
    "urls.js": _MODULE,
    "page.css": "text/css; charset=utf-8",
}

# The page's own file, the marker in it that names where its modules
# are served this version, and the one that names the device socket's
# path, relative to the deployment's root as the client resolves every
# address it reaches. From the boundary's own constant, so the path a
# board is sent to and the path a browser connects to are one fact.
INDEX = "index.html"
ASSETS_MARKER = "{{assets}}"
SOCKET_MARKER = "{{socket}}"
SOCKET_PATH = WEBSOCKET_PATH.lstrip("/")

# How many hex digits of the digest a version is. Sixty-four bits: the
# question is only ever whether two module sets differ.
VERSION_LENGTH = 16

# Everything the page may load or reach is its own origin's, and nothing
# else is allowed at all: no inline script, no third-party origin, no
# framing, no form posts, no `<base>`.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; "
    "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

# Said on every response under /try/: nothing the page does is to name
# its own address to anybody, and nothing is to be read as another type.
COMMON_HEADERS: Mapping[str, str] = {
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

PAGE_HEADERS: Mapping[str, str] = {
    **COMMON_HEADERS,
    "Cache-Control": "no-store",
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
}

# A year, the conventional ceiling, and immutable: a versioned path's
# bytes never change, so a browser holding them need never ask again.
ASSET_HEADERS: Mapping[str, str] = {
    **COMMON_HEADERS,
    "Cache-Control": "public, max-age=31536000, immutable",
}

_PACKAGE = "vinga_server.browser"
_STATIC = "static"


class Assets:
    """One version of the client: the page and the allowlisted files.

    Built from bytes rather than read per request, so the version a page
    names and the bytes served under it are computed from the same read
    and cannot disagree. `packaged()` is the set that ships; a suite
    builds another to stand for the next release.
    """

    def __init__(self, index: str, served: Mapping[str, bytes]) -> None:
        unknown = set(served) - set(ALLOWLIST)
        missing = set(ALLOWLIST) - set(served)
        if unknown or missing:
            raise ValueError("the served files must be exactly the allowlist")
        self._served = dict(served)
        digest = hashlib.sha256()
        for name in sorted(self._served):
            content = self._served[name]
            digest.update(f"{name}\0{len(content)}\0".encode())
            digest.update(content)
        self.version = digest.hexdigest()[:VERSION_LENGTH]
        # Relative to the page, never from the root: a deployment served
        # under a path prefix (`server.public_url` may carry one) is
        # reached at `<prefix>/try/`, and a root-relative module path
        # would reach past the prefix. Two renderings, one per spelling of
        # the page's own path, because a relative reference resolves
        # against the directory: `static/...` from `/try/`, and
        # `try/static/...` from `/try`, which a browser reads as a file in
        # the directory above.
        relative = STATIC_PATH.removeprefix(PAGE_PATH)
        mount = PAGE_PATH.strip("/").rsplit("/", 1)[-1]
        # The socket's path is the same in both: the client resolves it
        # against the deployment's root, read off its own module's
        # address, never against the page.
        page = index.replace(SOCKET_MARKER, SOCKET_PATH)
        self._pages = {
            True: page.replace(ASSETS_MARKER, f"{relative}/{self.version}").encode(),
            False: page.replace(ASSETS_MARKER, f"{mount}/{relative}/{self.version}").encode(),
        }

    @classmethod
    def packaged(cls) -> "Assets":
        """The client as this package ships it."""
        static = files(_PACKAGE) / _STATIC
        return cls(
            (static / INDEX).read_text(encoding="utf-8"),
            {name: (static / name).read_bytes() for name in ALLOWLIST},
        )

    def page(self, slashed: bool = True) -> bytes:
        """The page, naming this version's modules relative to itself.
        `slashed` is which spelling of the page's path it is answering:
        `/try/` (the default) or `/try`."""
        return self._pages[slashed]

    def file(self, version: str, name: str) -> tuple[bytes, str] | None:
        """One allowlisted file of this version and its media type, or
        None for any other version or any other name."""
        if version != self.version or name not in ALLOWLIST:
            return None
        return self._served[name], ALLOWLIST[name]
