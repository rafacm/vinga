# Decompose the CLI along its existing seams: implementation

Companion to [`2026-09-22-cli-decomposition.md`](2026-09-22-cli-decomposition.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M4: refusal reasons

**Attribution:** anthropic/claude-opus-5, thinking high; Claude Code 2.1.278; 2026-09-22.

The five refusals that named a command of the CLI's grammar now state
what they refused in and carry a closed token for it, and the CLI says
what to type. The server stops speaking a grammar it neither ships nor
versions, which is the coupling #386 measured: an image built before a
rename told an operator to type a command the client beside it no
longer had.

### What landed

| Piece | Where |
| --- | --- |
| The vocabulary | `config/responses.py`: `RefusalReason(StrEnum)`, six kebab-case members, with the comment above it saying why it is an extension member and not the RFC's `type` |
| The member | `config/responses.py`: `Problem.reason: RefusalReason \| None = None`, described as the state and not the remedy; `Problem`'s docstring gains the paragraph about the extension mechanism |
| The revised contract | `config/responses.py`: `Problem.detail`'s description stops claiming to be the sentence the CLI prints and says it is the state the server refused in, which a client holding the token may extend |
| The fact on the exception | `config/loader.py`: `ConfigError.__init__` gains keyword-only `reason`, stored as `self.reason`; the import edge is `responses.py`, which imports pydantic and nothing of this server |
| The token on the wire | `config/api.py`: `problem_response` takes `reason` and excludes the member from the dump when it is None; `_refusal`'s handler reads `exc.reason` |
| The three API sentences | `config/api.py`: `_UNKNOWN_CODE`, `_CLAIM_REFUSED` and `_UNLOADED_AGENT` lose their command halves; their raise sites (1774, 2554, 2595 before the change) pass `agent-not-serving`, `code-not-pending` and `agents-unknown` |
| The two store sentences | `config/store.py`: `ALREADY_BOUND` loses its command half and its raise site passes `device-already-bound`; `_write_secrets`'s refusal becomes `_missing(holder)` alone with `provider-missing` or `mcp-server-missing` from `_MISSING_HOLDER[location.kind]` |
| The constant's comment | `config/models.py`: `SERVER_PROGRAM` now names the one composer left, `loader.served`, instead of claiming three |
| The reading rule | `config/cli.py`: `_nameable` replaces a `reason` that is a string this build cannot name with None before `Problem.model_validate`; everything else stays as strict as it was |
| The remedies | `config/cli.py`: `REMEDIES: dict[RefusalReason, str]` beside `_refusal`, its one consumer, spelled with `PROGRAM` the way `SPOKEN` is; `_refusal` returns `detail`, a space and the remedy where the token is known, `detail` alone where it is not |
| The published document | `docs/reference/api-openapi.json`, through `uv run vinga-server config openapi`: the `RefusalReason` component, `Problem.reason` as `anyOf[$ref, null]`, and the revised `detail` description |
| The changelog fragment | `changelog.d/488-refusal-reasons.md`, `### Changed`, two entries: the five refusals, and the upgrade order |

`docs/reference/cli.md` did not move. Verified with the workflow's own
drift check over the generated region rather than assumed, and it
reports no difference: no help page changed.

The six remedy sentences are the plan's, verbatim, with `PROGRAM`
standing for `vinga`, checked against the plan's text by comparing the
rendered table string by string.

### The tests, by path

One named home per raise path, each asserting the sentence, the exact
token the site attaches, that neither spelling of this grammar's
program word is in `detail`, and keeping the no-secret and no-address
checks already beside it.

| Path | Where |
| --- | --- |
| `code-not-pending`, unknown and expired and already-claimed | `tests/unit/test_config_api_pending.py`: `test_an_unknown_code_points_at_the_screen`, `test_an_expired_code_is_answered_the_same_way`, `test_a_claim_retires_the_code` |
| `agents-unknown` | `tests/unit/test_config_api_pending.py`: `test_a_refused_claim_does_not_quote_the_names_it_refused`, and end to end in `tests/integration/test_cli_live.py` |
| `agent-not-serving` | `tests/unit/test_config_api_runtime.py`: `test_an_agent_this_server_is_not_serving_is_a_404_carrying_the_state` |
| `device-already-bound` | `tests/unit/test_config_api_pending.py`: `test_a_claim_will_not_replace_a_binding_made_underneath_it`, and through the client in `tests/unit/test_simulator_board.py` |
| `provider-missing`, `mcp-server-missing` | `tests/unit/test_config_store.py`: `test_a_holder_that_is_not_there_at_the_write_says_which_kind_it_was`; over HTTP in `tests/unit/test_config_api_writes.py`: `test_a_secret_for_a_holder_that_is_not_there_says_which_kind_it_was` |

| Claim | Where |
| --- | --- |
| A refusal with no token carries exactly `title`, `status`, `detail`, `errors` | `tests/unit/test_config_api_problems.py`: `test_a_refusal_with_no_token_carries_exactly_the_four_members` |
| And a sibling of one of the five, `ALREADY_COVERED`, carries the same four | `tests/unit/test_config_api_pending.py`: `test_a_claim_will_not_bind_a_device_a_default_agent_now_covers` |
| A known token prints `detail` plus the remedy, the whole of stderr, once per member | `tests/unit/test_config_cli_rendering.py`: `test_a_state_this_client_knows_is_answered_with_its_own_remedy` |
| A token this build cannot name prints `detail` alone and is never echoed | `test_a_state_this_client_cannot_name_is_quoted_and_not_guessed_at` |
| No member at all prints `detail` alone | `test_a_refusal_from_a_server_older_than_the_vocabulary_is_unchanged` |
| A `reason` that is not a string is unrecognized, and nothing of it reaches a stream | `test_a_body_whose_state_is_not_a_token_is_not_this_apis_refusal`, three shapes |
| `set(REMEDIES) == set(RefusalReason)` | `test_the_remedies_cover_the_whole_vocabulary` |
| Every command quoted in a remedy names a row of `COMMANDS`, in the short spelling | `test_every_remedy_names_a_command_this_grammar_has` |
| Every secret holder has a token of its own | `tests/unit/test_config_api_writes.py`: `test_every_secret_holder_answers_in_a_token_of_its_own` |
| The whole client path against a real application: the server's sentence and this client's remedy | `tests/unit/test_config_cli_rendering.py`: `test_prompt_says_what_the_server_answered_for_an_unserved_agent` |
| Over a real connection: the pending row reads the table, and a claim naming an agent that is not there is refused whole | `tests/integration/test_cli_live.py`: the `("device", "pending")` row of `REFUSALS`, and `test_a_claim_naming_an_agent_that_is_not_there_is_refused_over_the_wire` |

`tests/support/problems.py` gained a keyword-only `reason=` mode on
`refused()`, which requires exactly the four members plus `reason`
holding that value. `PROBLEM_KEYS` was not broadened: the four-member
default is what pins every other refusal's body, and it is what the
old-client compatibility claim rests on.

### The falsification runs

Each was performed, watched and reverted.

| Mutation | What caught it |
| --- | --- |
| `problem_response` dumping the model plainly, so `reason` goes out as null | `test_a_refusal_with_no_token_carries_exactly_the_four_members`, on a malformed-request 422: `AssertionError ... Extra items in the left set: 'reason'` |
| `_write_secrets` raising without `reason=` | Both store-level holder cases: `assert None is <RefusalReason.PROVIDER_MISSING: 'provider-missing'>`, and both HTTP cases on the four-member body |
| The remedy lookup removed from `_refusal`, returning `problem.detail` | The six known-token cases, each on the whole of stderr being `detail` with nothing after it; the other six client cases stayed green, which is what says the mutation was local |
| The reading rule removed, validating the payload as it arrived | `test_a_state_this_client_cannot_name_is_quoted_and_not_guessed_at` alone: the unknown token turned a readable refusal into "a body this client does not recognize" |
| `provider set` spelled `provider add` in `REMEDIES` | `test_every_remedy_names_a_command_this_grammar_has`: `assert [('vinga', 'provider', 'add')] == []` |

No mutation survived a test.

The `PROGRAM`-absent and `SERVER_PROGRAM`-absent assertions need no
mutation: every one of the five sentences held one of those spellings
before this change, so each assertion is red against the pre-change
tree by construction. `PROGRAM` is `vinga`, which is a substring of
`vinga-server config`, so the first of the two would catch either
spelling on its own; both are asserted because the two constants are
two decisions and a sentence may come to hold either.

### Deviations from the plan

Five, all additive, none changing what the plan specifies.

- **A registry guard over `REMEDIES`, which the plan does not ask for.**
  The plan says the spelling is inside the command-spellings census's
  reach, quoting `SPOKEN`'s comment. It is not: that census reads the
  tree as text and these sentences are composed from `PROGRAM`, so a
  rename would leave a line naming a command nothing answers to with no
  text match to catch it. Measured rather than argued: both manifests
  were regenerated after the table landed and neither moved.
  `test_every_remedy_names_a_command_this_grammar_has` is the same
  guard over the composed table, holding every quoted invocation to a
  row of `COMMANDS` and to the short spelling, and the comment beside
  `REMEDIES` points at it rather than at the census.
- **The two holder cases pin the whole sentence**, against
  `entities.SECRET_HOLDERS[kind].missing`, rather than its `section:`
  prefix. What changed at that site is that the sentence is the kind's
  own ALONE, and the command that used to follow it would have passed a
  prefix check.
- **The `ALREADY_COVERED` sibling asserts the strict four members.** It
  is the refusal next door to `device-already-bound` and is not one of
  the five, so it is where "the skew is five bodies and not all of
  them" is cheapest to state twice.
- **The client cases are driven through `main`** with a mock transport
  of their own rather than through `_refusal`, so they assert the whole
  of what reaches an operator and add no reach-in. The one
  problem-document case that already existed in that file,
  `test_prompt_says_what_the_server_answered_for_an_unserved_agent`,
  was updated in place: it pinned `"config apply"`, which is exactly
  the coupling this milestone removes.
- **The reading rule's function is `_nameable`, not `_reported`.**
  `cli.py` already has a `_reported`, the simulator's check-in
  rendering, and the first draft shadowed it, which the suite caught as
  a `TypeError` out of the refusal reader rather than as a name clash.

### Discoveries

- **The refusal M4 changes in `store.py` had nothing driving it.** The
  sentence that composed with `SERVER_PROGRAM` is `_write_secrets`'s,
  raised when its update affects no row, and every ordinary way of
  addressing a secret at a holder that is not there is answered by
  `_check_slot` before the write. The existing secret-write case near
  line 861 of `test_config_api_writes.py` meets the slot check, not
  this. So the sentence was being changed with no test on it, which is
  why the plan's Tests section now names a fixture for it.
- **No schedule can be raced into that window.** `set_secret` runs the
  check and the write in one transaction, and every transaction on this
  engine takes the chain's advisory lock in its begin listener
  (`db/__init__.py`), so a second connection deleting the holder waits
  on the one in flight and times out: what comes back is
  `DatabaseBusyError`, measured, not the state under test. The fixture
  is therefore a seam on the check, which answers as if the holder were
  present while the holder is never written.
- **An earlier draft widened the token to all three holder-missing
  sites**, `_check_slot`'s two included, on the reasoning that one state
  should have one home. It was narrowed back: the plan scopes the skew
  to five bodies, and tokenizing the slot check would have put the
  member on a refusal an ordinary request reaches. What is left is a
  real design question, recorded rather than resolved: after this
  change the two paths compose the same sentence and only one carries a
  token, so the reachable one gives a client nothing to phrase a remedy
  from. Extending the vocabulary to the slot check is a change to the
  published contract and belongs in its own issue.
- **The live lane's deployment is shared, and a case that mints a code
  needs a board of its own.** The end-to-end claim refusal first used
  the board the onboarding case is about, which that case binds, so by
  the time this one checked in it was answered as a configured device
  and no code was minted: `Unwelcome(...)` where `Activating` was
  expected, caught by the integration lane and not by anything
  smaller. Two of the lane's addresses already carried that reasoning
  in a comment; this is a third, and the reason it needs one is
  different enough to be written out, since what it needs is a board
  that stays unbound rather than one nothing else reads.
- **The published API document carries issue references already**
  (`#19`, `#88`, `#384`), so the reasoning that names `#386` was kept in
  comments above the declarations rather than in the docstrings the
  document renders, which is where this repository puts reasoning
  anyway.

### The reach-in, named

`vinga_server.config.store._check_slot` is replaced in two test files,
`tests/unit/test_config_store.py` and
`tests/unit/test_config_api_writes.py`. It is an underscore name and
therefore a review flag, answered explicitly: the refusal under test is
raised only when the holder's row is gone between two statements of one
transaction, and a race has no caller-facing seam to reach it by. The
design guide's two answers are "the module lacks an interface callers
need" and "the test pins a detail"; neither applies, because no caller
can ever ask for this state and nothing here pins how the check works,
only that it passed. That the slot-check refusal was not what answered
is proven by the body's `reason`, which only the write path attaches.

It arrives as no line in `tests/census/reach-ins.txt`, and that is a
fact about the census rather than about the reach: a site is a `.`
followed by an underscore name, and `monkeypatch.setattr(store,
"_check_slot", ...)` names it as a string. Recorded here so the flag is
raised where the manifest would have raised it.

### The upgrade order

An older CLI against a newer server refuses these five bodies, because
its `Problem` forbids the member it does not know, and the `vinga`
client installs separately from the image it administers. So the order
is stated where an operator meets upgrades: **upgrade every
administering CLI before the server.** Until that is done the five
refusals print the unreadable-body sentence instead of what was
refused, and every other refusal reads exactly as before, because none
of them carries the member. Nothing negotiates a version: the two
halves ship from one tree, the failure mode is a degraded sentence and
never a command that misbehaves, and the project is pre-release with no
third-party install to carry. The changelog fragment says the same
thing under `### Changed`, which is what the fold carries into
`CHANGELOG.md`.

### Verification

From `vinga-server/`: `uv run ruff check .` (clean),
`uv run pytest tests/unit -q` (7418 passed, 19 skipped, 28m37s),
`uv run pytest tests/integration -q` (347 passed, 9m01s) and
`uv run pytest tests/census -q` (66 passed), plus the two
generated-document drift checks run the way the workflow runs them:
the OpenAPI document matches the committed copy and the CLI
reference's generated region has no difference. The wheel-grade lane
is inside the integration lane and ran, since `uv` is on PATH and
nothing skipped. The image build and the smoke conversation were not
run here and are unverified in this section; the pull request records
what CI says about them.

### PR review round, PR #548

Automated external review of this PR's diff (origin/main...cc54b763).
Reviewed 2026-09-22 by openai/gpt-5.6-sol, thinking high via codex CLI
0.155.1, read-only sandbox, runtime 12m54s, at commit cc54b763. Verdict
as received: **mergeable after the listed fixes**. Three findings, one
P1, all adopted.

Two of the three are the same shape and it is one this repository has a
name for: a test that asserts something narrower than the sentence
beside it claims. The third is a real leak, and the milestone's own
tolerance is what opened it.

1. **P1: an explicit `reason: null` bypassed the refusal trust boundary
   and printed `detail`.** `_nameable` normalized only unknown strings
   and left every other value alone, and `RefusalReason | None` accepts
   `null`, so a problem-shaped body carrying `"reason": null` validated
   and its `detail` reached a terminal. `detail` is the field of that
   shape whose words a middlebox chooses. The plan's own requirement is
   that a non-string reason be unrecognized, and the test matrix had
   every non-string but that one.

   *Resolution.* Adopted whole, in `638a029d`. `_nameable` now tells an
   ABSENT member from a PRESENT one: absent stays absent, an unknown
   string is read as that same silence, and anything present that is not
   a string answers `_UNNAMEABLE`, which `_refusal` turns into the fixed
   unreadable-body sentence with none of the body on either stream. The
   `an explicit null` case joined the matrix with the planted credential
   in `detail`, and it was watched failing first, with the credential on
   stderr.

2. **P2: the remedy wording and the token-to-remedy pairing were not
   pinned.** The full-stderr cases built their expectation from
   `cli.REMEDIES`, which is the table under test, so they asserted that
   it equals itself: a remedy reworded, or two remedies swapped between
   their tokens, stayed green, and the implementation record above
   claimed a string-by-string comparison that only ever happened once,
   by hand, at authoring time.

   *Resolution.* Adopted whole, in `83384d05`.
   `REMEDY_SENTENCES` in `tests/unit/test_config_cli_rendering.py` is
   the plan's six sentences written out, `cli.REMEDIES` is held equal to
   it as a whole mapping, and the full-stderr cases read the literals.
   Two mutations were watched failing; a third, moving the two whole
   dictionary lines, was a no-op, because dict equality does not see
   order, and the test was right to stay green.

3. **P2: the secret-holder cases did not prove their stated no-address
   contract.** The HTTP case asserted `path.split("/")[2]`, which for
   `/providers/llm/claude/...` is the stage `llm` and not the identity
   that was refused, so it checked a word the refusal is entitled to
   say. The store-level case asserted nothing about the address at all.

   *Resolution.* Adopted whole, in `2563def7`. Each case addresses its
   holder by a credential-shaped sentinel of its own, distinct per kind
   and held so by the guard beside them, and asserts it absent from the
   body, the headers, the records this server wrote and, at the store,
   the whole exception chain. The two no-leak claims have different
   scopes and the test says why: a credential travels in a body and is
   held to `renderings`, every captured record read three ways, while a
   holder's name travels in the request line, so the caller's own HTTP
   client logs it by construction and what can be claimed is that
   nothing this server wrote repeats it. Both readings were watched
   failing on leaks the sentence pin cannot see.

Beside the three, the command-spellings manifest was stale on the
rebased tree and is regenerated in `850b8d6a`: three pairs, the plan's
own quoted remedies as `historical`, and `vinga device show` and
`vinga provider set` as `respell`, which is a gain rather than a cost.
Written out rather than composed from `PROGRAM`, the remedy sentences
are inside that census's reach for the first time, which is the guard
the M4 section above had to write a test for because the census could
not see them.

## M1: the package

**Attribution:** anthropic/claude-opus-5, thinking high; Claude Code 2.1.278; 2026-09-22.

`config/cli.py` is `config/cli/`: fifteen modules along the seams the
file already had, every definition moved unchanged, the suite re-pointed
at the module that defines each name, and two structural tests restated
as the properties they guard. What a command prints did not move, which
the generated reference proves byte for byte rather than by argument.

### The module map as it landed

The order below is the order the modules may import one another in, and
`tests/unit/test_cli_import_graph.py` is what holds them to it. Counts
are `tests/tools/cli_sections.py`'s, run on the head of this branch.

| Module | Definitions | Lines | What it owns |
| --- | ---: | ---: | --- |
| `invocation.py` | 1 | 187 | `Invocation`, the resolved-arguments type, alone. It reads nothing else here and everything else here reads it |
| `answers.py` | 3 | 157 | Reading an answer as the shape the API declared, and the tolerances this client keeps against a server of another age |
| `reach.py` | 43 | 1144 | The transport policy, the sanitized refusal and its remedies, and the line a long wait draws |
| `input.py` | 47 | 636 | Everything a command reads that did not ride argv: YAML, inline pairs, the confirmation, the credential, the memory noun's content |
| `output.py` | 24 | 479 | Which stream a thing goes to, how a value is bounded, how a table is aligned, and the boundary a write is waiting at |
| `acts.py` | 7 | 195 | `Act`, `_act`, `_performed`, `_path`, `_printed` and the two fixed unreadable-answer sentences |
| `entities.py` | 51 | 645 | The five commanded kinds and the default agent: their acts, their renderers, their secret rows, and the masked document's shapes |
| `devices.py` | 23 | 232 | The device noun: the record, the binding by MAC and by code, and the boards waiting |
| `deployment.py` | 59 | 1143 | The whole-deployment verbs: export, import, apply, diff, list, show, info, with the documents each of them prints |
| `records.py` | 98 | 1161 | The conversation store: sessions, conversations, memory and the aggregates over them |
| `local.py` | 13 | 272 | The five commands that reach no API, and the gate that says which half of the distribution is missing |
| `simulator.py` | 23 | 397 | The simulated board, and the seam that keeps the two credentials apart |
| `events.py` | 28 | 435 | The live event stream: the frame vocabulary, the envelope check and the one-line rendering |
| `grammar.py` | 114 | 2689 | The registry, the argument declarations, the tree `command()` builds, and the committed reference rendered off it |
| `__init__.py` | 12 | 368 | The door: an argument vector to an exit code and one sentence, whichever entry point it came in by. It re-exports nothing |
| **total** | **546** | | |

The 65 commands went to the family their noun names, and the eight the
plan fixed by hand went where it said: `info`, `list` and `show` to
deployment, `check` and `ota-url` to local, `cli-reference` to grammar,
`default-agent` to entities, the memory rows to records. No assignment
had to be changed.

### The proof that nothing was edited on the way

`tests/tools/cli_ast_identity.py`, run from `vinga-server/` against this
branch's parent:

```
$ uv run python -m tests.tools.cli_ast_identity 4d6aea57
base: 4d6aea57
definitions before: 547
definitions after:  547

definitions whose dump moved: 1
  CHANGED __all__ (now in __init__.py)
definitions no longer defined: 0
definitions not there before: 0

identical: 546
```

The one that moved is `__all__`, and it is the deviation recorded below.

The base is `main` rather than the commit this branch was cut from,
because M4 merged as PR #548 while this milestone was being built and
took five fixes with it. Three of those are in the file this package
replaced, so the package has to match `main`'s `cli.py` rather than the
one it was split from: `_UNNAMEABLE`, `_nameable`'s third arm and
`_refusal`'s two lines were ported into `cli/reach.py` beside
`REMEDIES`, which is where every one of their neighbours went. The
count moved from 546 to 547 for the sentinel, and 546 of the 547 are
identical.

`tests/tools/cli_sections.py`, the section measurement adapted to the
package, is supporting evidence about the definitions rather than the
cycle proof. Its verdict:

```
== Acyclic: YES ==
== The stated order is a topological order: no edge points forward ==
```

And the generated reference did not move. The workflow's own drift
check, run here, reports no difference on the region between the
markers, and the inner recipes check reports no difference either.

### The cycle proof, and each module in a fresh interpreter

`tests/unit/test_cli_import_graph.py` builds the package's
module-import graph from every `import` and `from ... import` statement
of every module, `__init__.py` included, in both the relative and the
absolute spelling and at any depth of a body, and asserts that no
module can reach itself. It is a lasting test because a package's
cycles are about modules rather than definitions: an import runs when
the module is first loaded, the load order decides which names exist
when, and `__init__.py` runs first.

Beside it, each module imported in an interpreter of its own, from
`vinga-server/`:

```
vinga_server.config.cli                  ok
vinga_server.config.cli.invocation       ok
vinga_server.config.cli.answers          ok
vinga_server.config.cli.reach            ok
vinga_server.config.cli.input            ok
vinga_server.config.cli.output           ok
vinga_server.config.cli.acts             ok
vinga_server.config.cli.entities         ok
vinga_server.config.cli.devices          ok
vinga_server.config.cli.deployment       ok
vinga_server.config.cli.records          ok
vinga_server.config.cli.local            ok
vinga_server.config.cli.simulator        ok
vinga_server.config.cli.events           ok
vinga_server.config.cli.grammar          ok
```

### The tests, re-pointed

43 files changed under `tests/`: 41 re-pointed at the modules that
define the names they reach, one new (the cycle proof above) and one
whose only CLI reference was a path in a fixture list. Eight files that
name the module are unchanged, because every name they reach stayed in
`__init__.py` or was never a name at all.

The fourteen names `cli.py` only re-exported come from their own
modules: `ConfigError` and the two missing-half sentences from
`config/loader.py`, the Click classes from the copy Typer ships,
`check_transportable` from `config/transport.py`, `docgen` and
`entities` from `config/`. Three are read off a module of the package
instead, because what the test asserts is about the CLI's own reading
rather than about the name: `UNPARSEABLE` off `cli/input.py`, whose
fragment boundary is what `test_both_yaml_readers_catch_one_family`
says shares one tuple with the boot path, and `getpass` and
`load_file_config` off the modules whose functions call them.

### The patch retargets, and the proof each still reaches

A `monkeypatch.setattr` reaches a consumer only when it targets the
module whose globals that consumer reads. Three of the nine patched
names are looked up somewhere other than where they are defined:

| Name | Defined in | Looked up by | Patched on |
| --- | --- | --- | --- |
| `_call` | `reach` | `acts._act` | `acts` |
| `narrated` | `reach` | `acts._act` | `acts` |
| `_act` | `acts` | `acts._performed`, `simulator._claimed` | `simulator`, which is the consumer the one test that patches it drives |
| `build_client` | `reach` | `reach._sent`, `reach._reading` | `reach` |
| `PROGRESS_CADENCE_S` | `reach` | `reach.narrated` | `reach` |
| `threading` | stdlib, imported by `reach` | `reach._ProgressLine`, `reach.narrated` | `reach` |
| `load_file_config` | `loader`, imported by `reach` and `local` | `reach._reached` on this path | `reach` |
| `check_transportable` | `transport`, imported by `entities` and `deployment` | `entities._fragment_body`, `deployment._document_body` | both |
| `COMMANDS` | `grammar` | `grammar.command` | `grammar` |

Every one of the eight a unit test makes was proven to reach rather
than argued: the replacement was made to raise (or, for the cadence, to
be the one value its reader refuses), the test was run and watched fail,
and it was restored.

| Patch | What failed with the replacement made to raise |
| --- | --- |
| `acts._call` | `test_config_cli_summary.py::test_a_document_a_rendering_cannot_walk_is_quoted_nowhere[list-providers-is-a-list]` |
| `acts.narrated` | `test_config_cli_progress.py::test_the_bytes_off_a_terminal_are_the_same_with_the_line_and_without[import]` |
| `simulator._act` | `test_simulator_board.py::test_a_claim_performs_the_act_the_grammar_already_has` |
| `reach.build_client` | `test_config_cli_transport.py::test_a_body_that_is_not_this_api_s_own_is_not_relayed` |
| `reach.PROGRESS_CADENCE_S` | `test_config_cli_progress.py::test_a_wedged_redraw_does_not_stop_an_answered_import_reporting` |
| `reach.threading` | `test_config_cli_progress.py::test_a_writer_that_will_not_start_changes_nothing_about_the_command` |
| `reach.load_file_config` | `test_config_cli_info.py::test_both_acts_are_answered_by_the_address_the_banner_named` |
| `entities.check_transportable`, `deployment.check_transportable` | the three `spy` cases of `test_config_cli_untransportable.py`, under the two guard mutations below |

`COMMANDS` is the ninth and is patched only in the live lane, so the
lane's own run is what says it reaches.

No surviving mutation was found. The three that would have survived are
the three retargeted above, and they are the reason the proof is a step
of the milestone rather than a claim in it.

### The two structural tests, and their falsifications

**`test_config_cli_untransportable.py`** asserted that the guarded call
sites are exactly `{"cli.py", "store.py"}`. The CLI half is now a
statement over the registry: every `Command` row's acts are read for the
bodies they carry (eleven), each is resolved to its source through its
code object's first line and followed through its calls, and the set
that can reach the one place this CLI calls a YAML parser is pinned to
the two that take one. Every member of that set is asserted to reach the
guard. The repository side keeps its own filename. No module of the
package is named anywhere in the file.

Reachability is not order, so the ordering is proven at run time over
the same discovered set: each member is driven through `_act` with the
request seam replaced by a recorder, and the recorder stays empty. A
discovered member with no invocation builder is an error rather than a
skip.

| Mutation | What caught it |
| --- | --- |
| `check_transportable` taken out of `_fragment_body` | eight cases, `test_every_body_that_parses_yaml_reaches_the_guard[_fragment_body]` and `test_the_guard_runs_before_the_request_is_made[_fragment_body]` among them |
| `check_transportable` moved after the body's `return`, so it is reachable and never runs | seven cases. `test_every_body_that_parses_yaml_reaches_the_guard` stayed GREEN, which is exactly the finding the plan's fourth review round made, and `test_the_guard_runs_before_the_request_is_made[_fragment_body]` is what went red |

**`test_cli_import_weight.py`** keeps its exact inventory, which grows
by the package's own fourteen modules and by nothing else, listed one
by one rather than allowed as a prefix. The one-importer claim is
restated for a package: what it counts is edges from outside, and a
second test holds the package's own modules to the relative spelling,
which is what keeps the inside and the outside two different questions.

| Mutation | What caught it |
| --- | --- |
| `from vinga_server.config.store import ConfigStore` planted in `devices.py` | `test_the_cli_reaches_exactly_this_much_of_the_server`, on five extra modules including `vinga_server.db` and `vinga_server.config.store` |
| `from .grammar import DESCRIPTION` planted in `invocation.py` | `test_the_package_imports_itself_in_one_direction_only`, reporting `grammar -> acts -> invocation -> grammar` |

### The manifests

Three lines moved, all regenerated with the generators and none edited.

| Manifest | Line | Why |
| --- | --- | --- |
| `reach-ins.txt` | `+ tests/unit/test_config_cli_untransportable.py  _act  1` | A real new reach-in, named below |
| `reach-ins.txt` | `tests/unit/test_config_cli_grammar.py  _click` 1 → 2 | Not a reach at all: a site is a `.` followed by an underscore name, and `typer._click.exceptions` is the import that file now spells for itself instead of reaching through the CLI for |
| `command-spellings.txt` | nothing, after the rebase | The line this milestone added, the plan's own quoted remedy, arrived on `main` first: PR #548's own review round regenerated the same manifest for the same reason. The generators were re-run on the rebased tree and agree with it |

### The reach-in, named

`acts._act` is reached by `test_the_guard_runs_before_the_request_is_made`
in `tests/unit/test_config_cli_untransportable.py`. It is an underscore
name and therefore a review flag, answered explicitly: what the case
proves is that the guard runs BEFORE the request, and the dispatcher is
the one place where a body meets a request, so it is where the order
exists to be watched. The design guide's two answers are "the module
lacks an interface callers need" and "the test pins a detail"; the
first is the live question, since `Command.perform` is the public way in
and it resolves an address and a token before it dispatches, which this
case has no server for. Nothing here pins how `_act` works, only that
its body ran and its request did not.

### Deviations from the plan

Six, five of them decisions the plan left to the milestone and one a
genuine change.

- **`__all__` is the one definition that changed.** It named five
  names the package does not define, and the package re-exports
  nothing, so it is `["main"]`. Its own commit, and the AST-identity
  report names it.
- **`_from_an_installed_half` lives in `local.py`, and `simulator.py`
  imports it from there.** The plan puts the gate nowhere. Three of the
  four gated commands are local's and the fourth is `simulator run`, and
  the alternatives were worse: `acts.py` is "only the helpers every
  family reaches" and this is reached by two of six, and a module of its
  own for one function is a name that hides nothing.
- **`_paged` and `MORE_PAGES` are `output.py`'s**, though every one of
  their five consumers is in `records.py`. They are a renderer
  combinator over any listing and the third of the stderr-notice
  writers that module owns; `records.py` would otherwise hold a paging
  primitive that is about no record in particular.
- **`_device_summary` is `devices.py`'s**, though its one consumer is
  `deployment._summary`. It renders a device body, which is the devices
  module's subject, and the edge it costs is one import.
- **`_halves`, `_sections`, `_nesting` and `_counted` are
  `entities.py`'s**, though every caller is in `deployment.py`. The plan
  assigns "the `_sections` reading" to entities and it is right: what
  those four know is what the registry says a section of the document
  is, which is entity knowledge, and keeping them together is what
  stops a count and a tree walking one document two ways.
- **`_version_asked` and `_root_options` are `__init__.py`'s**, which
  is the plan's "the version answer" read as the answer given in front
  of the parse. `_print_version` could not join them: `grammar`'s
  `--version` callback calls it, so it lives there and `main` imports
  it.

Two smaller ones, both additive. The stale paths were corrected: sixteen
comments and two workflow commands named `config/cli.py`, and two of
those were commands that would have failed rather than read oddly. And
`__init__.py` carries the usage-problem section comment that
`MISSING_ARGUMENT` used to carry, since that constant went to
`input.py` with its raise site.

### Discoveries

- **A patch aimed at the defining module is silent, not red.** The
  re-pointing aimed every `monkeypatch.setattr` at the module that
  defines the name, which is the obvious reading and is wrong for three
  of them: `acts.py` imports `_call` by name, so `reach._call` is a
  different binding and patching it changes nothing about what `_act`
  calls. It was caught by 112 failures across three files rather than by
  anything subtle, which is luck: a patch whose test asserts only the
  happy path would have gone green.
- **Two reaches no import rewrite can see.** `getattr(cli, name)` in
  two files, which is how a parametrized row names the sentence it
  expects, and `cli.PROBLEM_MEDIA_TYPE`, a re-export of
  `config/responses.py`. Both were found by running the suite and
  neither by any static sweep of `cli.<name>`, because one is a string
  and the other was not in the re-export list the plan measured.
- **The command-spellings manifest was stale, and two milestones
  found it independently.** The plan's own remedy sentence quotes
  `vinga device pending list`, and the manifest did not have that line.
  M1 regenerated it, PR #548's review round regenerated it on `main`
  first, and the rebase dropped M1's hunk as the duplicate it had
  become. Neither milestone caused the staleness: a plan committed to
  `main` outside either branch did.
- **The census counts an import path as a reach-in.** A site is a `.`
  followed by an underscore name, so `typer._click.exceptions` reads as
  a reach into `_click`. It moved one line because a file that used to
  get the Click classes through the CLI now imports them itself.

### The #489 bookkeeping

The issue's 2026-09-20 comment asks, for the eighteen test files it
names, whether the storage dependency became explicit in a signature.
The answer is **no, for every one of them**, which is the prediction the
plan recorded.

Measured rather than asserted: of the nineteen `test_config_cli_*.py`
files in the tree plus `test_config_api.py`,
`test_config_api_events.py`, `test_config_examples.py` and
`test_config_snapshot_mode.py`, twenty-three files in all, **zero**
gained a storage dependency in any signature and **twenty-three** did
not. Three of them have a signature line in their diff at all, and none
of the three is a storage dependency: a return annotation that stopped
saying `cli.ConfigError`, a call that stopped saying `cli.command()`,
and the transportability file's new helpers, which take `tmp_path` and
`monkeypatch`. M1 moved definitions and touched no fixture, which is
exactly why.

### Verification

Run on the rebased tree, from `vinga-server/`: `uv run ruff check .`
(clean), `uv run pytest tests/unit -q` (7429 passed, 19 skipped,
28m55s), `uv run pytest tests/integration -q` (347 passed, 9m04s) and
`uv run pytest tests/census -q` (66 passed), plus the CLI reference
drift check the server workflow runs, over the generated region and
over the recipes inside it, both reporting no difference. The
AST-identity script and the section measurement above were run at this
branch's head, and each package module was imported in an interpreter
of its own.

The unit lane grew by nine cases and by nothing else, which the rebase
is what proves: 7,446 collected on the old base and 7,448 on `main`,
and the two are `main`'s own, the remedies-as-literals pin and the
`null` shape its review round added. The nine are the two of the cycle
proof, the one holding the package to the relative spelling, and the
six the transportability property and its ordering cases add. The
wheel-grade
lane is inside the integration lane and ran, since `uv` is on PATH and
nothing skipped. The image build and the smoke conversation were not
run here and are unverified in this section; the pull request records
what CI says about them.

### PR review round, PR #549

Automated external review of this PR's diff (origin/main...55d65b64).
Reviewed 2026-09-22 by openai/gpt-5.6-sol, thinking high via codex CLI
0.155.1, read-only sandbox, runtime 17m59s, at commit 55d65b64. Verdict
as received: **not mergeable until the P1 and P2 findings are fixed**.
Five findings, all adopted.

Four of the five are the same shape, and it is the one this milestone
was supposed to be about: a check that reports a problem and passes
anyway. Two tools print a duplicate and exit 0, a cycle proof drops the
shortest cycle there is, and two locality tests assert a string against
itself. Each of them would have gone on being read as evidence.

1. **P1: the documented AST-checker path emits a raw traceback.** It
   defaulted to `HEAD^`, which on a milestone of more than one commit
   is already the package, so the documented no-argument run asked git
   for a file that is not there and the `CalledProcessError` left as a
   traceback. A supplied revision that names nothing did the same and
   put the rejected revision in it.

   *Resolution*: accepted, in `4e1b38f4`. The default is the merge base
   of this checkout and the branch it merges into, resolved rather than
   guessed at; a checkout with neither `origin/main` nor `main` is
   refused, because a base this tool invented would report the
   difference as a definition somebody edited. Every git call goes
   through one function that answers `None` rather than raising, so
   there is nothing to chain, and the three refusals are fixed
   sentences naming no revision, no path and no word of git's own.
   Falsified four ways, each watched before and after: no argument, a
   bogus revision spelled as a credential, outside a checkout, and
   inside one with no upstream branch.

2. **P2: the import-cycle proof silently removed self-cycles**, and did
   not read `from .. import cli` or `from vinga_server.config import
   cli` as edges to `__init__`, so a self-import or a cycle through the
   package door stayed green.

   *Resolution*: accepted, in `dba5a479`. Self-edges are kept, both
   door spellings are edges to `__init__`, and `from ..cli import reach`
   is read as the sibling it is. Four regression cases, one per
   spelling, planted in a package of the test's own with a no-cycle
   control beside them. Falsified twice: against the old walk the three
   it missed go red and `import vinga_server.config.cli` stays green,
   which is why that one is kept as a case; and planted one at a time
   in the real package, each of the three turns
   `test_the_package_imports_itself_in_one_direction_only` red.

3. **P2: two locality tests were reduced to tautologies.**
   `NEEDS_THE_SERVER_HALF is NEEDS_THE_SERVER_HALF` and the same for
   `NEEDS_THE_SIM_EXTRA` are true of every name there has ever been,
   while what their docstrings claim is that there is one string and
   not two. `loader.py` still said `cli` re-exports the constant.

   *Resolution*: accepted, in `b083def2`. Each consumer's binding is
   held to the loader's: `local`, `doctor` and `main` for the server
   half, `simulator` for the extra. The comment names its three readers
   and says that each imports this module rather than hopping through
   another, since the package re-exports nothing; the parser sentence's
   comment named the CLI as a file and now names the module. Falsified
   by rebinding each consumer to a copy of the sentence, equal and not
   the same, which turns both tests red.

4. **P3: both definition measurements could report success after
   finding duplicates.** Both printed a duplicate and exited on
   something else.

   *Resolution*: accepted, in `c8a33318`. Both collect duplicates, keep
   the first definition, report them under a heading of their own and
   fail on them. It was not only a status: `cli_ast_identity` let the
   second definition replace the first and compared the survivor, and
   `cli_sections` dropped it and went on to build the matrix and the
   reference graph its verdict is read off. Falsified with `UNNAMEABLE`
   planted in `answers.py` beside `output.py`'s: before, `cli_sections`
   exited 0 and `cli_ast_identity` reported the totals matching; after,
   both exit 1 and name the pair.

5. **P3: a live module docstring still described the removed
   architecture.** `docgen.py` said the configuration commands pay for
   SQLAlchemy and cryptography because `cli.py` imports three helpers
   from `store.py`.

   *Resolution*: accepted, in `e82db44c`. The paragraph says where the
   three helpers actually are, `transport.py` and the entity registry,
   and names the test that pins it. Checked against `CLI_REACH` rather
   than asserted: `config.store` absent, `config.transport` and
   `config.entities` present.

A trap worth keeping, from the third finding's falsification: `str(x)`,
`x + ""`, `"".join([x])` and `x[:]` all answer the same object for a
`str` in CPython, so the first attempt at rebinding a consumer to a
copy did not bite and read exactly like a fix that had not worked.
