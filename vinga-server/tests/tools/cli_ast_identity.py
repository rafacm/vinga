"""Prove that splitting `config/cli.py` edited none of its definitions.

Read-only. Dumps every top-level definition of the file as it stood at
a base commit, and every top-level definition of the `config/cli`
package at the working tree's head, as ``ast.dump`` with the line and
column attributes stripped, and diffs the two maps name by name.

What may differ is the set of import statements and nothing else: a
split copies the import lines each module needs, and the names bound by
them are not definitions. A definition whose dump moved is a definition
that was edited on the way, which is what this exists to name, and the
report says so per name rather than reporting that something changed.

It is not a lasting test. The property it proves is about one change,
so it is run in that milestone's verification and its output is quoted
in the implementation doc.

Usage, from `vinga-server/`::

    uv run python -m tests.tools.cli_ast_identity <base-commit>

The base commit defaults to the milestone branch's parent. The exit
status is 0 when every definition is identical and 1 otherwise.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

# Where the file was, and where the package that replaced it is. Both
# relative to the repository root, which is where `git show` addresses
# from and what the walk below resolves against.
BEFORE = "vinga-server/src/vinga_server/config/cli.py"

AFTER = "vinga-server/src/vinga_server/config/cli"

# The default base: the parent of whatever this checkout has at HEAD,
# which for a milestone branch built on top of a merged one is the
# commit the split started from.
DEFAULT_BASE = "HEAD^"


def repository_root() -> Path:
    """The repository this module is being run from."""
    answered = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(answered.stdout.strip())


def committed(root: Path, commit: str, path: str) -> str:
    """One file's text as of one commit."""
    answered = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return answered.stdout


def bound_targets(target: ast.AST) -> list[str]:
    """The names one assignment target binds."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in bound_targets(element)]
    if isinstance(target, ast.Starred):
        return bound_targets(target.value)
    return []


def definitions(source: str) -> dict[str, ast.AST]:
    """Every top-level definition of one module, by the name it binds.

    Descends into top-level `if`/`try`/`with` blocks, which is where a
    guarded definition would live, so that no definition is missed. The
    walk is `tests/tools/cli_sections.py`'s, which is where the section
    measurement this split was drawn from reads the same set.
    """
    found: dict[str, ast.AST] = {}

    def walk(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.setdefault(node.name, node)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    for name in bound_targets(target):
                        found.setdefault(name, node)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                for name in bound_targets(node.target):
                    found.setdefault(name, node)
            elif isinstance(node, ast.If):
                walk(node.body)
                walk(node.orelse)
            elif isinstance(node, ast.Try):
                walk(node.body)
                for handler in node.handlers:
                    walk(handler.body)
                walk(node.orelse)
                walk(node.finalbody)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                walk(node.body)

    walk(ast.parse(source).body)
    return found


def dumped(node: ast.AST) -> str:
    """One definition as text, with its position taken out.

    `ast.dump` includes neither line nor column by default, which is
    exactly the property wanted: a definition that moved from line 4,000
    to line 12 of another file dumps the same, and one whose body,
    decorators, defaults or annotations changed does not.
    """
    return ast.dump(node)


def before(root: Path, base: str) -> dict[str, str]:
    return {name: dumped(node) for name, node in definitions(committed(root, base, BEFORE)).items()}


def after(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Every definition of the package at the working tree, and its home."""
    dumps: dict[str, str] = {}
    home: dict[str, str] = {}
    for path in sorted((root / AFTER).glob("*.py")):
        for name, node in definitions(path.read_text()).items():
            if name in dumps:
                print(f"DUPLICATE {name}: {home[name]} and {path.name}")
            dumps[name] = dumped(node)
            home[name] = path.name
    return dumps, home


def main(argv: list[str]) -> int:
    base = argv[0] if argv else DEFAULT_BASE
    root = repository_root()
    was = before(root, base)
    now, home = after(root)

    print(f"base: {base}")
    print(f"definitions before: {len(was)}")
    print(f"definitions after:  {len(now)}")
    print()

    moved = sorted(name for name in was.keys() & now.keys() if was[name] != now[name])
    gone = sorted(was.keys() - now.keys())
    added = sorted(now.keys() - was.keys())

    print(f"definitions whose dump moved: {len(moved)}")
    for name in moved:
        print(f"  CHANGED {name} (now in {home[name]})")
    print(f"definitions no longer defined: {len(gone)}")
    for name in gone:
        print(f"  REMOVED {name}")
    print(f"definitions not there before: {len(added)}")
    for name in added:
        print(f"  ADDED {name} (in {home[name]})")
    print()
    identical = len(was.keys() & now.keys()) - len(moved)
    print(f"identical: {identical}")
    return 0 if not (moved or gone or added) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
