# The CLI's write advice is held to the registry it names

**Date:** 2026-10-02

**Local baseline:** not applicable. A test and two code comments
change; nothing any deployment runs or prints moves.

## Problem

`SPOKEN` in `vinga-server/src/vinga_server/config/cli/output.py` is
the table of lines the CLI prints, in place of the server's sentence,
when a write is stored and not serving yet. Its lines name commands to
run, `vinga apply` through the `INSTALLS` constant and `vinga diff`
directly, and both are composed at import time from `PROGRAM`. The
comment above `INSTALLS` said that because this side names the
command, "the spelling is then inside the command-spellings census's
reach: a rename that missed it fails a test in this checkout rather
than reaching an operator through an old image" (#553).

It is not. The census
(`vinga-server/tests/census/test_command_spellings.py`) reads tracked
files as text, and `f"{PROGRAM} diff"` is not a spelling in any file.
#488 M4 measured this for its own composed table, `REMEDIES` in
`config/cli/reach.py`, by regenerating both manifests after the table
landed and finding neither had moved, and gave that table a registry
guard instead. `SPOKEN` kept the claim and had no guard.

What actually held each command at this branch's base, `4f768b16`:

- **`vinga apply`, indirectly.** The comment above `INSTALLS` ends by
  spelling it out, and the census reads that. Two rendering cases in
  `tests/unit/test_config_cli_rendering.py` (`_bind` and `_import`,
  under `NOTICED`) quote the reload line and the import count line
  written out and assert the client printed them, and those literals
  are `respell` sites the census holds to the registry. A renamer who
  respelled them would have found the table still printing the old
  verb.
- **`vinga diff`, not at all.** The census sites quoting it, listed by
  `census()` filtered to that invocation, are four lines of the CLI
  guide and a console transcript in `vinga-server/README.md` (all
  `respell`, all prose nothing ties to the table), the generated CLI
  reference, and history. The one test literal of the whole sentence is
  the respelling differential's, in a file the census classifies as
  historical and does not hold to the registry; it compares the
  sentence to the client's output, and in the missed-rename case both
  still say `diff`.

## Changes

### One guard over both composed tables

`test_every_remedy_names_a_command_this_grammar_has` becomes
`test_every_command_a_table_advises_is_one_this_grammar_has`,
parametrized over `ADVICE`, a two-entry mapping in the test file that
reads `reach.REMEDIES` and `output.SPOKEN` off the tables rather than
restating them. Each case quotes every backtick span in its table's
lines, asserts there is at least one, holds each to a row of
`grammar.COMMANDS` through `tests.support.config_cli.registered`, and
asserts the short program word. A parametrized case rather than a
second copy of the test, so the two tables are held by one structure.

`SPOKEN` quotes three invocations, two distinct, counted at runtime
rather than by reading the source:

```bash
uv run python -c "import re; from vinga_server.config.cli import output; \
  print([s for l in output.SPOKEN.values() for s in re.findall(r'\`([^\`]+)\`', l)])"
# ['vinga apply', 'vinga diff', 'vinga apply']
```

`NOT_SERVING_YET` and the diff's head line in `config/cli/deployment.py`
read `INSTALLS` as well, and are not in `ADVICE`: they read the same
constant `SPOKEN` quotes, so the guard over the table is a guard over
them.

### The comments say what holds the spelling

The comment above `INSTALLS` no longer claims the census. It says a
rename that missed the command fails a test, names the test, says the
census cannot see a composed sentence, and says why guarding `SPOKEN`
guards every other reader of the constant. Its closing line, which
spells `vinga apply` out, stays: it is prose the census does read.
`REMEDIES`'s comment, which already had the corrected reasoning, now
names the renamed test and says it covers both tables.

The plan where the original claim was made,
`docs/plans/2026-09-05-server-state-vocabulary.md`, keeps its text; its
implementation doc gains a dated correction at its end.

### Composed, or written as literals the census can read

The issue asked this once for both tables: should a sentence naming a
command be composed from `PROGRAM` at all, or written as a literal the
census reads, with `PROGRAM` kept for the generated documents? Both
tables stay composed, and the guard is what holds them. The reasons:

- **The literals already exist, where a literal earns its place.**
  Each table's wording is pinned against text written out in a test, so
  that a test does not assert the code equals itself:
  `REMEDY_SENTENCES` for `REMEDIES`, and for `SPOKEN` the rendering
  cases and the respelling differential. Writing the tables themselves
  as literals would make each sentence two literal copies, the
  source's and the test's, held equal by a test.
- **The census's guard is looser than this one.** It strips any of
  its four program words before looking the rest up (`_typed`), and it
  accepts a group as well as a command (`names_something`), so a
  literal table could advise `vinga-server config apply`, the
  checkout's long spelling, or `vinga provider`, a noun with nothing
  to run, and pass. The registry guard asks for a row of `COMMANDS`
  and the short word, and composition makes that word the client's own
  constant rather than a string that must agree with it.
- **Two tables are not where the idiom lives.** Sixty-two lines under
  `vinga-server/src` compose a program word into a string
  (`grep -rnE '\{(PROGRAM|INSTALLS)\}' --include='*.py' src | wc -l`,
  from `vinga-server/`), across eleven files, of which only
  `config/docgen.py` (nine) and `config/server_reference.py` (one) write
  generated documents. Literals in the two advice tables would leave
  fifty-odd composed sites beside them under the opposite rule, and
  moving all of them is a different change from this one.
- **Proportion.** The guard is one parametrize entry and a renamed
  test. The literal route is the same deletion of a claim plus eight
  sentences rewritten across two tables and a census run to confirm the
  manifest, for a guard the unit lane already gives.

## Key parameters

- `ADVICE` in `tests/unit/test_config_cli_rendering.py`: the tables the
  guard reads, by name (`remedies`, `spoken`). A third composed table
  of advice joins by one entry.
- `test_every_command_a_table_advises_is_one_this_grammar_has`: the
  guard, one case per table.

No runtime string, configuration key, event, API response or generated
reference changed.

## Verification

- The guard was watched failing before any claim was made about it,
  each mutation restored by copy and touched afterwards:
  - The grammar's `diff` row renamed to `compare`
    (`config/cli/grammar.py`): the `spoken` case fails on
    `[('vinga', 'diff')]`, and the `remedies` case, which is the old
    test unchanged, stays green.
  - The grammar's `apply` row renamed to `install`: both cases fail,
    each on `('vinga', 'apply')`.
  - `SPOKEN`'s `{PROGRAM} diff` misspelled `{PROGRAM} dif`: the `spoken`
    case fails on `[('vinga', 'dif')]`.
- The `diff` rename was also run against the census module and the
  suites that read `SPOKEN` or the constants beside it (`test_config_cli.py`,
  `test_config_cli_rename.py`, `test_config_cli_respelling.py`,
  `test_config_cli_rendering.py`, `test_config_cli_progress.py`), with
  `-ra`: 11 failed, 377 passed. Apart from the new guard, every failure
  is a case invoking `diff` itself or `test_the_manifest_is_the_census`
  reporting the manifest's drift, and a renamer clears both without
  touching `SPOKEN`. That is the measurement behind the correction:
  before this change, nothing named the table's stale command.
- Clean, on the final tree: those five unit files,
  `uv run pytest ... -q -ra -n 2 --dist loadfile`, 336 passed in
  77.62s; `uv run ruff check .`; then, after the last prose edit, the
  census lane at `-n 2 --dist loadfile`, 66 passed, with neither
  manifest moved.
  The full unit and integration lanes were not run, since no runtime
  string changed, and are left to CI.

## PR review round

Reviewed 2026-10-02 by openai/gpt-5.6-terra, thinking high via codex
CLI 0.156.1, read-only sandbox, runtime 3m36s, at commit 4a0e4e5f. One
finding.

1. **P2: the guard accepted an invalid invocation with a valid verb
   later in it.** The guard handed the whole quoted span to
   `tests.support.config_cli.registered`, which looks for a registry
   row at any word position, so a span with an unknown word between the
   program word and `diff` passed on the strength of the `diff`. The
   hole was the old `REMEDIES` guard's too.

   *Resolution*: adopted, in the guard rather than in `registered`.
   The any-position search is load-bearing for that helper's other
   callers: it is how a live or wheel test's argv, which can carry
   global options such as `--api-url` in front of the command, is
   mapped to its row (`test_cli_live.py` drives `export` that way), and
   the census's own guard calls it too. The test now asks
   `_advises_a_row`: the first word is `PROGRAM`, and the row
   `registered` finds in the rest begins at the rest's first word, so
   a positional tail such as `<mac>` after `device show` is still
   checked by `registered` and still allowed. Watched both ways with a
   temporary forged `ADVICE` entry quoting such a span: against the
   committed guard all three cases passed, the hole; against the fix
   the forged case failed naming the span and the two real tables
   passed. The forged entry was removed by copying the file back.

### Re-review

Reviewed 2026-10-02 by openai/gpt-5.6-terra, thinking high via codex
CLI 0.156.1, read-only sandbox, runtime 1m59s, at commit a15b1468. One
finding.

1. **P2: the later-verb fix had no permanent regression test.** The
   guard's cases read only the real tables, whose entries are all
   valid, so reverting `_advises_a_row` to a bare `registered` call
   would still pass both; the forged entry that showed the fix working
   was removed after the run.

   *Resolution*: adopted.
   `test_a_row_is_advised_only_from_the_word_after_the_program` holds
   `_advises_a_row` to four cases in `ADVISED_OR_NOT`: a row with its
   positional tail is accepted, and a word between the program word
   and a real verb, a real row under another program word, and a span
   with no row at all are refused. The words are written as separate
   strings composed with `PROGRAM`, so none is a spelling the
   command-spellings census reads; both manifests stayed unmoved.
   Watched failing: with the check reverted to a bare `registered`
   call, the middle-word and wrong-program cases failed (2 failed, 4
   passed); with only the position check dropped, the middle-word case
   failed (1 failed, 5 passed). Each mutation was restored by copy and
   touched.

## Files modified

- `vinga-server/tests/unit/test_config_cli_rendering.py`
- `vinga-server/src/vinga_server/config/cli/output.py`
- `vinga-server/src/vinga_server/config/cli/reach.py`
- `docs/plans/2026-09-05-server-state-vocabulary-implementation.md`
- `docs/features/2026-10-02-spoken-registry-guard.md`
- `changelog.d/553-spoken-registry-guard.md`
