"""The Use pages vinga answers from, held byte for byte to the pages a
reader reads.

The built-in agent (#612) answers from the Use door: `docs/concepts.md`,
`docs/glossary.md` and every page under `docs/devices/`. A server reads
them at run time, so they have to be inside what it was installed from,
and the image's build context is `vinga-server/`, which cannot see the
root `docs/` at all. So the pages are committed a second time, inside
the package, at `src/vinga_server/knowledge/pages/`, and this module is
what keeps the two from being two documents.

It does both halves, the way the manifests beside it do. Run as a
module it writes the copy:

    uv run python -m tests.census.test_packaged_pages

from `vinga-server/`, never a hand edit. Collected as a test it checks
the copy: the same file set and the same bytes, so a Use page edited
without regenerating, a guide added without its copy, a guide deleted
whose copy stayed, and a stray file in the package's directory all fail
by name.

Why a committed copy rather than a build step, priced in the plan's Q7:
a force-include of `../docs` reaches outside the build root, so the
image and a wheel built from an sdist lose it; a copying build step has
to be remembered by every builder, the documented `docker build` lines
and the git install among them; and an extra build context fixes the
image and still not the wheel. The copy needs no build change at all,
at the cost of one regenerate command when a Use page changes.

Why here: this lane runs in both workflows, and an edit to a Use page
runs only the documentation one. A check in the unit lane would never
see the edit that stales it.

Both sides are read from the filesystem rather than from `git ls-files`,
which is where this module departs from its two neighbours on purpose.
What a wheel and an image carry is what is on disk under the package,
tracked or not, so the copy is compared as the build would see it; and
the regenerator writes from what is on disk, so its check has to read
the same thing.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The checkout, found from this file rather than from the working
# directory, for the reason the other two censuses give.
REPO_ROOT = Path(__file__).resolve().parents[3]

DOCS = REPO_ROOT / "docs"

# Where the copy lives, inside the package the wheel carries.
COPY = REPO_ROOT / "vinga-server" / "src" / "vinga_server" / "knowledge" / "pages"

REGENERATE = "uv run python -m tests.census.test_packaged_pages"

# The two Use pages that are not device guides, by name. Every device
# page joins by existing, so a new guide needs no entry here.
_TOP_LEVEL = ("concepts.md", "glossary.md")

_DEVICES = "devices"


def sources() -> dict[str, Path]:
    """Every page the copy carries, keyed by its path inside the copy.

    `docs/concepts.md` is `concepts.md`, and `docs/devices/<page>.md`
    is `devices/<page>.md`, so the copy keeps the shape a reader knows.
    """
    found = {name: DOCS / name for name in _TOP_LEVEL}
    for page in sorted((DOCS / _DEVICES).glob("*.md")):
        found[f"{_DEVICES}/{page.name}"] = page
    return found


def copied() -> dict[str, bytes]:
    """Every file under the copy, whatever it is, keyed the same way.

    Every file and not only the Markdown ones, because whatever is in
    the directory ships in the wheel.
    """
    if not COPY.is_dir():
        return {}
    return {
        path.relative_to(COPY).as_posix(): path.read_bytes()
        for path in sorted(COPY.rglob("*"))
        if path.is_file()
    }


def regenerate() -> list[str]:
    """Write the copy from the pages, and remove what no page backs.

    Returns the copy's paths, for the command to report.
    """
    wanted = sources()
    for stale in set(copied()) - set(wanted):
        (COPY / stale).unlink()
    for name, source in wanted.items():
        target = COPY / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    return sorted(wanted)


def test_the_packaged_pages_are_the_tree() -> None:
    """The copy is the pages: the same names and the same bytes.

    The names first, because a missing or extra file is the more
    useful report, and a byte comparison over two different sets would
    only say that something differs.
    """
    wanted = {name: source.read_bytes() for name, source in sources().items()}
    have = copied()

    assert sorted(have) == sorted(wanted), (
        f"the packaged pages are not the Use pages; regenerate with `{REGENERATE}` "
        "from vinga-server/"
    )
    differing = sorted(name for name in wanted if have[name] != wanted[name])
    assert differing == [], (
        f"these packaged pages differ from their source: {differing}; regenerate with "
        f"`{REGENERATE}` from vinga-server/"
    )


def test_the_copy_carries_the_whole_use_door() -> None:
    """The source set, asserted rather than trusted.

    A glob that silently matched nothing would make the check above
    compare two empty sets and pass. So the two named pages and at least
    one device page are required to exist, and the device pages are
    required to include the common page, which is the one a board with
    no guide is answered from.
    """
    found = sources()

    assert all(found[name].is_file() for name in _TOP_LEVEL)
    assert f"{_DEVICES}/README.md" in found
    assert len([name for name in found if name.startswith(f"{_DEVICES}/")]) > 1


if __name__ == "__main__":  # pragma: no cover - the regeneration entry point
    written = regenerate()
    sys.stdout.write(f"wrote {len(written)} pages to {COPY}\n")
