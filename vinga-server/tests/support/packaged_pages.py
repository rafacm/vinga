"""Which pages the built-in agent's packaged copy carries, and where.

Shared by three suites, which is why it is support rather than part of
any of them: the census that writes and checks the copy
(`tests/census/test_packaged_pages.py`), the command-spellings pin
that holds every copied page to the live grammar, and the unit and
wheel cases that hold what the package reads to the pages under
`docs/`. The reasoning for the copy, and for reading the filesystem
rather than `git ls-files`, is in the census module's docstring.
"""

from __future__ import annotations

from pathlib import Path

# The checkout, found from this file rather than from the working
# directory, for the reason the censuses give.
REPO_ROOT = Path(__file__).resolve().parents[3]

DOCS = REPO_ROOT / "docs"

# Where the copy lives, inside the package the wheel carries.
COPY = REPO_ROOT / "vinga-server" / "src" / "vinga_server" / "knowledge" / "pages"

REGENERATE = "uv run python -m tests.census.test_packaged_pages"

# The two Use pages that are not device guides, by name. Every device
# page joins by existing, so a new guide needs no entry here.
TOP_LEVEL = ("concepts.md", "glossary.md")

DEVICES = "devices"


def sources() -> dict[str, Path]:
    """Every page the copy carries, keyed by its path inside the copy.

    `docs/concepts.md` is `concepts.md`, and `docs/devices/<page>.md`
    is `devices/<page>.md`, so the copy keeps the shape a reader knows.
    """
    found = {name: DOCS / name for name in TOP_LEVEL}
    for page in sorted((DOCS / DEVICES).glob("*.md")):
        found[f"{DEVICES}/{page.name}"] = page
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
