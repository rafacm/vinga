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

    uv run python -m tests.tools.cli_ast_identity [<base-commit>]

The base is where the split started from. Given a revision, it is that
revision; given none, it is the merge base of this checkout and the
branch the milestone will merge into, which is the same commit on a
branch that has not been rebased onto something else since. What it may
not default to is `HEAD^`, which is what it used to: on a milestone of
more than one commit that parent is already the package, so the
documented no-argument run asked git for a file no longer there.

Nothing about a revision reaches the terminal. Every git call is a call
this tool may be handed a bad argument for, and a revision is typed,
which makes it the last thing a failure may repeat: the sentences below
name the rule rather than what was given, and each is built inside its
handler and raised after it, so nothing walking the chain finds the
value either. That is `config/cli`'s own refusal standard, and it
applies to a tool that prints for the same reason it applies to a
command that does.

The exit status is 0 when every definition is identical and 1
otherwise.
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

# Where a branch of this repository merges, in the order a checkout is
# likely to have them. The remote's copy first, because it is the one
# that cannot have drifted locally, and the local branch after it, for
# a clone that fetched no remote.
UPSTREAM = ("origin/main", "main")

# What this tool says instead of a traceback, and what each of them
# leaves out. None names a revision, a path or a word of git's own: a
# revision is typed, and every other refusal in this repository holds
# the same line about what was typed.
NO_BASE = (
    "no base commit to compare against: nothing was given and this checkout has no "
    "branch to take a merge base from. Name the commit the split started from as the "
    "one argument. Neither what was looked for nor what git said about it is repeated "
    "here."
)

NO_SUCH_REVISION = (
    "the base names nothing this repository has, or nothing that holds the file the "
    "split started from. It is not quoted back: a revision is typed, and a refusal "
    "here names the rule rather than what was given."
)

NOT_A_REPOSITORY = (
    "this is not a git checkout, so there is no earlier state to compare against. "
    "Run it from inside the repository. What git said about it is not repeated here."
)


class Refused(Exception):
    """One of the three sentences above, on its way to `main`.

    A class of this module's own rather than a `SystemExit` carrying the
    text, so the boundary below decides how a sentence is printed and
    everything under it decides only which one.
    """


def answered(command: list[str], cwd: Path | None = None) -> str | None:
    """One git call's output, or None when it would not give any.

    The one place this tool runs anything, so it is the one place a
    failure can carry a value. `check=False` rather than an arm around
    `CalledProcessError`, because that exception holds the whole command
    line, which holds the revision; there is nothing to catch, nothing
    to chain, and nothing for a walker to find.
    """
    finished = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    return finished.stdout if finished.returncode == 0 else None


def repository_root() -> Path:
    """The repository this module is being run from."""
    printed = answered(["git", "rev-parse", "--show-toplevel"])
    if printed is None:
        raise Refused(NOT_A_REPOSITORY)
    return Path(printed.strip())


def merge_base(root: Path) -> str:
    """Where this branch left the branch it merges into.

    Asked of the first upstream name this checkout has, and refused
    where it has none rather than guessed at: a base this tool invented
    would compare the package against whatever that guess happened to
    hold, and report a difference as a definition somebody edited.
    """
    for upstream in UPSTREAM:
        printed = answered(["git", "merge-base", "HEAD", upstream], cwd=root)
        if printed is not None and printed.strip():
            return printed.strip()
    raise Refused(NO_BASE)


def committed(root: Path, commit: str, path: str) -> str:
    """One file's text as of one commit."""
    printed = answered(["git", "show", f"{commit}:{path}"], cwd=root)
    if printed is None:
        raise Refused(NO_SUCH_REVISION)
    return printed


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
    root = repository_root()
    base = argv[0] if argv else merge_base(root)
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
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Refused as refused:
        # Printed here and raised nowhere: the sentence is the whole
        # answer, and an exception leaving this line would put the
        # traceback back that the sentences exist to replace.
        print(refused, file=sys.stderr)
        raise SystemExit(1) from None
