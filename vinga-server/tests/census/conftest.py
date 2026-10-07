"""The census lane, which stores nothing and says so by saying nothing.

`tests/unit` and `tests/integration` declare their storage at import,
by calling `provision_stores`, and that declaration is what makes their
fixtures work and their refusal honest. This lane makes no such call,
which is the whole reason it is a lane of its own.

Three checks live here, each held to a committed artifact, and they
share exactly one property: none opens a store or reads a row. Their
reaches are otherwise different, which is worth knowing before reading
a failure.

- **Command spellings** (`test_command_spellings.py`,
  `command-spellings.txt`) reads every tracked file in the repository
  and compares the command spellings it finds against the manifest, so
  a documentation edit can stale it.
- **Reach-ins** (`test_reach_ins.py`, `reach-ins.txt`) reads the tracked
  Python under `tests/` and counts the places a test reaches past an
  interface, so a change under `tests/` can stale it and a
  documentation edit cannot.
- **Packaged pages** (`test_packaged_pages.py`, the copy under
  `src/vinga_server/knowledge/pages/`) holds the built-in agent's
  packaged copy of the Use pages to `docs/concepts.md`,
  `docs/glossary.md` and `docs/devices/`, byte for byte, so an edit to
  any of those pages stales it until the copy is regenerated.

The lane exists because of the first of them. It read no row and never
did, but while it lived under `tests/unit` it inherited that lane's
declaration anyway, and the visible cost was in CI: the documentation
workflow carried a Postgres service container for a job whose only test
never connected to it, and said so in a comment that called the
refusal the lane's honesty mechanism and declined an exemption from it.

The honest repair was not an exemption. It was for the census to stop
being in a lane that provisions (#489). The second census was placed
here rather than beside the first's old home for the same reason, and
it needed no workflow edit, because both workflows already collect this
directory whole; so did the third (#612), which is here for the reason
the first is: a Use page edit runs only the documentation workflow.

This file exists to be empty on purpose. Without it a reader would have
to know that the absence of a conftest is a decision rather than an
oversight.
"""
