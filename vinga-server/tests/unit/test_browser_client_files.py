"""The browser client's files, read as an inventory (#613, D2, D3).

What the browser lane cannot see cheaply is held here, by reading the
files themselves: that the allowlist the server serves from is exactly
the client that ships, that every module the client loads is one the
server will serve, that no module but `urls.js` writes an address of
its own (so a deployment published under a path prefix reaches every
route through the one place that knows the prefix), and that the device
socket the page connects to is the path the boundary names.
"""

import re
from importlib.resources import files

from vinga_server.browser import ALLOWLIST, Assets
from vinga_server.browser.assets import INDEX
from vinga_server.device.boundary import WEBSOCKET_PATH

STATIC = files("vinga_server.browser") / "static"

# A module's static imports, and the module URL the worklet is loaded
# from, both relative to the importing module.
IMPORTED = re.compile(r'from\s+"\./([^"]+)"')
URL_OF = re.compile(r'new URL\(\s*"\./([^"]+)",\s*import\.meta\.url\s*\)')

# What the page itself loads, under the version marker.
REFERENCED = re.compile(r"\{\{assets\}\}/([^\"']+)")

# A string literal that is an address from the origin's root: a quote,
# then one slash, then anything but another slash.
ROOT_RELATIVE = re.compile(r"""["'`]/(?!/)""")

# The one module that resolves addresses.
URLS = "urls.js"


def client_files() -> set[str]:
    return {entry.name for entry in STATIC.iterdir() if entry.is_file()}


def text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def modules() -> list[str]:
    return sorted(name for name in ALLOWLIST if name.endswith(".js"))


def test_the_allowlist_is_exactly_the_client_that_ships() -> None:
    """A file added to the client and not to the allowlist would ship
    and never be served; one in the allowlist and not in the package
    would be a 404 in a browser. Both fail here."""
    assert client_files() - {INDEX} == set(ALLOWLIST)


def test_every_module_the_client_loads_is_one_the_server_serves() -> None:
    loaded = set(REFERENCED.findall(text(INDEX)))
    for name in modules():
        source = text(name)
        loaded |= set(IMPORTED.findall(source)) | set(URL_OF.findall(source))

    assert loaded, "the client loads nothing, which means these patterns found nothing"
    assert loaded <= set(ALLOWLIST), loaded - set(ALLOWLIST)
    # And nothing is served that nothing loads.
    assert set(ALLOWLIST) <= loaded, set(ALLOWLIST) - loaded


def test_no_module_but_urls_writes_an_address() -> None:
    """Every request resolves against where the page was served, through
    `urls.js`, so a deployment under a path prefix needs no other module
    to know it. A root-relative literal anywhere else would reach the
    origin's root instead."""
    offenders = {name: ROOT_RELATIVE.findall(text(name)) for name in modules() if name != URLS}

    assert {name: found for name, found in offenders.items() if found} == {}
    for name in modules():
        if name in (URLS, "audio.js"):
            continue
        assert "new URL(" not in text(name), name
    # audio.js loads the worklet beside itself, relative to its own
    # address, which is the one URL a module may build.
    assert URL_OF.findall(text("audio.js")) == ["audio-worklet.js"]


def test_the_page_connects_to_the_socket_the_boundary_names() -> None:
    """The socket's path is the boundary's constant, rendered into the
    page relative to the deployment's root rather than written into the
    client a second time."""
    page = Assets.packaged().page().decode()

    assert f'<meta name="vinga-socket" content="{WEBSOCKET_PATH.lstrip("/")}">' in page
    assert "{{" not in page
