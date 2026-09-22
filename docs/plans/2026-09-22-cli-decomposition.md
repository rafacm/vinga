# Decompose the CLI along its existing seams

Plan for [#488](https://github.com/rafacm/vinga/issues/488), as re-cut
on 2026-09-22. Its companion is
`docs/plans/2026-09-22-cli-decomposition-implementation.md`, one
section per milestone, appended in the same change that ticks the
milestone.

**Local baseline:** not applicable. Nothing here touches a
conversational capability; the subject is how the configuration CLI
is built and how a refusal tells a client what to do next.

**Cheapest alternative:** three of the four milestones name theirs in
their own text, and two were re-cut to it before this plan was
written. For M1 the cheapest change is leaving the file whole and
adding an index comment, which buys nothing the section headers do
not already give, so the split has to earn its cost, measured below:
43 test files re-pointed, nine patch targets moved, two structural
tests rewritten to the property they guard. What it buys is a module a
command author can read in one sitting, acts and renderers of one
family together, instead of 9,674 lines. For M2 the cheapest shape is
no code, and the measurement says that is the shape. For M3 the
cheapest shape is one function and one test beside the reader that
already exists, and that is the shape. For M4 the cheapest shape is
leaving the five sentences as they are, which #386 already priced as
the skew it measured, so M4 buys exactly the end of that class.

**Attribution:** anthropic/claude-fable-5-1, thinking high; Claude
Code 2.1.278; 2026-09-22.

## Goal

Split `config/cli.py` into a package whose modules each hold one
responsibility, without changing one byte of what any command prints,
so that a change to the simulator no longer reads past the SSE frame
parser and a new command's author learns a registry row and a family
module rather than the file. Beside that, give the five refusals that
still name a client command a closed token instead, so the server
stops speaking a grammar it does not own. The milestone order is M4,
M1, then M2 and M3 stacked on M1, for the reasons the issue records.

Everything below rests on two measurements taken before this plan was
written, both scripted so the reviewer can audit the method rather
than the conclusion. Their scripts are pasted into the review prompt,
their results are quoted where a decision depends on them, and both
are committed under `tests/tools/` by the milestone that re-runs
them (`cli_sections.py` in M1, `cli_fields.py` in M2), so the numbers
here can be reproduced from the tree rather than trusted.

## What is settled and not re-litigated

From the issue, as re-cut on 2026-09-22:

- The grammar is unchanged. Noun-first, entity-derived addressing, the
  shared command registry as the single home of the grammar,
  deterministic output, secure credential input, lightweight client
  dependencies, and the stdout-data/stderr-notices separation are all
  preserved. Help output and the generated `docs/reference/cli.md`
  stay byte-identical through M1.
- M1 splits along the seams the file already has: shared execution
  infrastructure in one place, focused modules for the command
  families. Not a generic command framework, and no class where it
  owns no coherent state. The two tests that pin filenames move to the
  properties they guard.
- M2 is sized by measurement: per-family invocation types only where
  the measurement finds exposure, the recorded measurement and no code
  where it finds none.
- M3 is a mechanical dump beside the reader that exists, one escape
  test on the model, and the CLI guide's `--json` deferral repriced.
  No new model layer, no new dependency, no flag shipped.
- M4 restates the five command-naming refusals as state plus a closed
  token on `Problem`, additive and defaulted, published the way
  `Applies` is; the CLI phrases the remedy from a client-side table
  beside its consumer, and quotes `detail` alone for a token it does
  not know. The stale `SERVER_PROGRAM` comment is corrected. Classes
  (b), (c) and (d) of #386's census stay out of scope.
- M4 has no gate: #487's re-cut moved the token here, where its only
  consumer is.

## The two measurements

### M1: the section graph is acyclic once four definitions move

`sections.py` parses the file, assigns each of its 543 top-level
definitions to the section whose comment header precedes it, and
records every reference from a definition's body to a top-level name
of another section. Every header and every named definition sits at
the line the issue's assessment recorded, and no definition straddles
a boundary.

The matrix of distinct names referenced, rows referencing, columns
referenced:

```
             prelude  reach  read  onboard  render  input  output  acts  simboard  events  grammar
  prelude          .      .     .        1       .      .       .     .         .       .        3
  reach           12      .     .        .       .      .       .     .         .       .        .
  read             .      .     .        .       .      .       .     .         .       .        .
  onboard          1      .     .        .       .      .       .     .         .       .        .
  render          35      .     1        .       .      .       .     .         .       .        .
  input            3      .     .        .       .      .       .     .         .       .        .
  output           2      .     .        .       4      .       .     .         .       .        .
  acts             9      6     1        .      27      8       2     .         .       .        .
  simboard         3      1     .        .       .      .       .     2         .       .        .
  events           2      3     .        .       .      .       .     .         .       .        .
  grammar         14      1     .        .       .      1       .    57         6       6        .
```

The graph over sections has one strongly connected component and
twenty elementary cycles, and every one of them passes through one of
four definitions that sit in the prelude but belong elsewhere by
dependency: `main` and `_parsed` (under no header, calling
`_print_version`, `_version_asked` and `command`), `cli_reference`
(calling `command()`), and `_ota_url` (calling `_server_config`, the
one function of the onboarding-URL section). With those four placed
where their dependencies are, the graph is a DAG in file order:
constants, transport, reading, rendering, input, output, acts, then
simulator and events side by side, then grammar. That is the
extraction order, and it is the file's own.

The test surface, from `test_surface.py` over the 304 tracked test
files: 47 touch the module, 43 reach at least one of 152 distinct
names, and one server module imports it (`main.py`, for `main`).
Fourteen of the 152 are names `cli.py` merely re-exports from other
modules (`ConfigError`, `docgen`, `entities`, `check_transportable`,
`load_file_config`, three Click classes, and the rest). Nine names are
replaced on the module with `monkeypatch.setattr`, and for five of
them the function that looks the name up will live in a different
module than the definition after the split: `_call` and `narrated`
(defined in transport, looked up by `_act`), `PROGRESS_CADENCE_S`
(a constant, looked up by `narrated`), `_act` (looked up by
`_performed` and by the simulator's claim), and three imported names
(`check_transportable`, `load_file_config`, `threading`). A patch
reaches a consumer only if it targets the module whose globals the
consumer reads, so those patches follow the consumer. `build_client`
(19 sites over 8 files) and `COMMANDS` are looked up in the module
that defines them and survive a retarget.

### M2: one command in sixty-five, and no history

`fields.py` imports the module so that every `Command` row, every
`Act` and every grammar function are real objects, maps each callable
to its source through `__code__.co_firstlineno`, and for each command
collects the `Invocation` fields its act callables and handler read,
following calls transitively (depth three at most), against the fields
its grammar passes when it builds the invocation. The four global
options and `kind` are set for every command by `_invocation` itself
and are reported apart.

```
commands: 65
read-not-set empty: 62
read-not-set non-empty: 3
  handler-preset on a replace() copy, not a silent default: 2
  genuinely silent default: 1
distinct fields ever in read-not-set: 2
  code: simulator check-in, simulator run   (preset by the handler)
  file: memory delete                        (silent)
```

The one silent case: `memory delete` reads `file` through `_typed`,
which it shares with `memory set`, and its grammar never offers `-f`,
so the conversation-scope deletion always takes the stdin branch,
which is what its help says it does. Behaviour today is correct; the
shape is exactly the one the issue priced, and it is the only
instance. The history check ran `git log -S` for each field over the
file's 138 commits (188 with `--follow`) and read every subject, plus a
body grep for the vocabulary such a fix would use: no commit in the
CLI's history fixes a command reading a field its grammar never set.

So the question is whether that one instance is the exposure the
issue priced, and it is not. The issue's bug class is a handler that
silently gets a default where it needed a value; here the default is
the documented behaviour, since `memory delete` takes its key from
standard input by design and `_typed`'s file branch is simply
unreachable for it. A read that cannot change behaviour is a dead
branch, not an exposure, and the history confirms the class has never
produced a defect. Per-family types would carry between one and nine
fields each across 26 families to make a static error of that. M2
lands as the measurement recorded and no code: no invocation type is
added, the resolved-globals merge stays the one seam it is, and the
dead branch is recorded in the M2 section as a discovery rather than
changed, because changing it is neither of the two outcomes the issue
settled and buys nothing a reader of the measurement does not already
have.

## The smaller decisions

### The split is a package named `cli`, and nothing is re-exported

`config/cli.py` becomes `config/cli/`, so `from vinga_server.config
import cli` and `cli.main(sys.argv[2:])` in `main.py` are unchanged and
the console script's entry point is unchanged. A package rather than
sibling files because the parts change for separate reasons, which is
the design guide's definition, and because `config/cli_render.py` is
the guide's own counterexample.

Tests import each name from the module that defines it. A blanket
re-export from `__init__.py` would keep 43 files untouched and hide
nothing, and it would leave the five patched names pointing at a
module their consumers do not read, so the edits happen either way.
Measured on the tree: 43 files need an import edit with no re-exports,
39 with the grammar and `main` kept in one module, so re-exporting
buys four files. The fourteen names tests reach through `cli.py` that
it only re-exports are imported from their own modules.

### The modules, each with what its callers stop knowing

Shared infrastructure, in the DAG's order:

- `cli/__init__.py`: `main`, `_parsed`, the usage-problem
  translation, the entry-point constants and the version answer. What
  callers stop knowing: how an argument vector becomes an exit code
  and one sentence, whichever of the two entry points it came in by.
- `cli/invocation.py`: `Invocation`, the one resolved-arguments type,
  alone. Every other module reads it and it reads nothing, which is
  what a seam stated as a type looks like, and it is the lowest module
  of the package for that reason. It is not in `acts.py` because
  `reach.py` annotates with it and `acts.py` imports `reach.py`.
- `cli/reach.py` (the "Reaching the API" section): `Address`,
  `Reached`, `build_client`, `_call`, `_permitted`, `_sent`,
  `_refusal`, `_payload`, `narrated` and `_ProgressLine`, with
  `PROGRESS_CADENCE_S` beside its one reader. Callers stop knowing
  the transport policy, the sanitized-refusal rule, and how a long
  wait is narrated. Named `reach` rather than `transport` because
  `config/transport.py` already exists and is about what JSON can
  carry.
- `cli/answers.py` (the "Reading an answer" section): `_understood`,
  `_declared` and the unreadable-field sentinel. Three definitions,
  and a module because two sections read through it and it depends on
  nothing: it is the seam with `responses.py`, and M3 adds the
  mechanical dump beside it.
- `cli/input.py`: reading YAML, inline values, the two-alternatives
  rule, the destructive-verb confirmation, the interactive reads, and
  `_read_secret`. Callers stop knowing which library parsed what and
  what an interactive failure is called.
- `cli/output.py`: the "Output" section plus the rendering primitives
  every family shares (`_section`, `_acknowledged`, the column
  writers, the notice-on-stderr rule). Callers stop knowing which
  stream a thing goes to and how a table is aligned.
- `cli/acts.py`: `Act`, `_act`, `_performed`, `_path`, and only the
  helpers every family reaches (the fixed unreadable-answer sentences,
  the address helpers). Nothing entity-shaped: the per-kind
  `SET_ENTITY`/`SHOW_ENTITY`/`EXPORT_ENTITY`/`DELETE_ENTITY` tables
  and `_entity_path` are the entity family's, and `SHOW_ENTITY` names
  the entity renderer, so keeping them here would make `acts` import
  `entities` while `entities` imports `Act`. Callers stop knowing how
  one act becomes one request and one rendering.
- `cli/grammar.py`: `Globals`, `Command`, `_Grouped`, `_Verbatim`,
  the declare shapes, `GROUPS`, `COMMANDS`, `command()`, and the
  committed-reference builders `cli_reference` and `cli_recipes`,
  which call `command()` and belong with it. The registry stays the
  single home of the grammar.

The families, each holding its acts, its renderers and its fixed
sentences together, which is the issue's stated shape:

- `cli/entities.py`: provider, mcp-server, prompt-fragment, agent,
  agent-defaults, default-agent, and the secret rows of the two
  holders; the per-kind act tables and `_entity_path`; the entity
  renderers and the masked-configuration shapes (`BODY`, `ENTRIES`,
  the `_sections` reading).
- `cli/deployment.py`: the commands about the deployment as a whole:
  export, import, apply, diff, list, info, with the export document,
  the apply and diff listings, `SPOKEN` and `INSTALLS`.
- `cli/devices.py`: device and device pending, with the binding and
  record renderers.
- `cli/records.py`: conversation, session, memory and metric, with
  the thread, memory and aggregate listings.
- `cli/simulator.py`: the simulated board.
- `cli/events.py`: the live event stream.
- `cli/local.py` (the "commands that reach no API" block): ota-url,
  schema, openapi, reference, check, with `_ota_url` beside
  `_server_config`, the one function of the onboarding-URL section,
  which is its only caller.

The prelude's constants and fixed sentences are not a module. Each
moves to the module of its consumer, and one with consumers in several
modules moves to the lowest of them in the DAG order, the one the
others already import; `sections.py`'s per-name referrer lists say
which that is for every name, and the AST-identity map records where
each landed. `PROGRAM`, `CONSOLE_SCRIPT`, `DISPATCHED` and
`DISTRIBUTION` follow the same rule rather than an exception to it.

Fifteen modules. Each passes the deletion test in the direction the
guide asks it in both ways: inlining any family back into the acts
module puts a family's renderers beside every other family's, which
is the file this plan exists to end; and no module forwards its
arguments to another. The assignment of each of the 65 commands to a
family follows its noun; the six that are not obvious are fixed here:
`info` and `list` are deployment, `check` and `ota-url` are local,
`default-agent` is entities, and the memory rows are records. The
subagent records any assignment it has to change, with the reason.

### The proof that M1 changes nothing

Three proofs, none of them "the tests pass".

- **Every definition's AST is identical before and after.** A script
  built from `sections.py`'s walker dumps every top-level definition
  of `cli.py` at the base commit and of every module of the package
  at the milestone's head, as `ast.dump` with line and column
  attributes stripped, and diffs the two maps name by name. What may
  differ is the set of import statements and nothing else; a
  definition whose dump moved is a definition that was edited, and the
  script names it. The script is committed under `tests/tools/` and
  run once in the milestone's verification; it is not a lasting test,
  because the property it proves is about one change.
- **The generated CLI reference is byte-identical.** The drift check
  the server workflow already runs regenerates `docs/reference/cli.md`
  and diffs it, which pins every help page of the grammar wholesale.
- **The census manifests move only where the plan says.** The
  reach-in manifest records `path  name  count` per test file, so a
  test that keeps reaching `_call` from a new module leaves its line
  alone and a test that stops reaching it removes one line. The
  command-spellings manifest scans every tracked file and is expected
  to move for the spellings the new modules quote in their own
  comments, one line per spelling, regenerated and never merged.

### The two structural tests move to their properties

- `tests/unit/test_config_cli_untransportable.py` asserts the guarded
  call sites of `check_transportable` are exactly the files
  `{"cli.py", "store.py"}`. The property is that a fragment is checked
  before it travels, on both sides of the connection. On the CLI side
  it becomes a statement over the registry rather than over a file:
  for every `Command` row whose act carries a `body`, the body
  callable reaches `check_transportable` in its call graph, resolved
  the way `cli_fields.py` resolves a callable to its source and
  follows its calls, so a new write command whose body skipped the
  check is red whichever module it lands in. The repository side
  keeps its existing assertion, and the behaviour cases beside them
  (a fragment holding a NaN meets the sentence and no request is made,
  nothing of the fragment leaks) are unchanged. No CLI filename is
  asserted.
- `tests/unit/test_cli_import_weight.py` pins the exact set of
  `vinga_server` modules `import vinga_server.config.cli` loads. The
  property is the client-install weight bound: nothing of the server
  half loads with the CLI. The inventory stays exact, because an exact
  inventory is what catches a stray import, and it grows by the
  package's own modules and by nothing else; the test that nothing but
  the entry point imports the CLI is restated for a package, where the
  modules import each other and `main.py` is still the one importer
  from outside.

### M3: the dump beside the reader, and the dispatch on the render step

`answers.py` gains one function, `encoded(shape, answer, format)`,
which validates an answer as its shape the way `_understood` does and
dumps it in JSON mode (`TypeAdapter.dump_python(..., mode="json")`),
so an enum member such as `Applies.RELOAD` leaves as its string and a
date as ISO text, before writing it as JSON (the standard encoder,
sorted keys, no ASCII escaping of non-ASCII) or YAML (`yaml.safe_dump`,
block style, the flags the export already uses). `_understood`'s own
Python-mode dump keeps enum members as members, which PyYAML's safe
dumper has no representer for, so the dump mode is the whole
difference between the two readers. Both encoders escape a control character
natively, verified on the tree while this plan was written: the
standard encoder writes `\u001b`, PyYAML writes `"\e"` inside a
double-quoted scalar. That is the whole of the "second no-leak audit"
the CLI guide prices, and it is proven once, on the model: a test
plants a control character and the fixed-length mask in a response
model that carries an enum (an `Acknowledgement` with its `applies`),
dumps it through both encoders, and asserts the character is escaped,
the mask is the mask, and the enum is its value.

The dispatch sits where the issue put it, on the act's render step.
`answers.py` declares `Output(StrEnum)` with `human`, `json` and
`yaml`, and `_act` takes `output: Output = Output.HUMAN` as its last
parameter: the human arm is `act.render(act.read(answer))`, unchanged,
and the machine arm writes `encoded(act.answers, answer, output)` to
stdout and nothing to stderr. `_performed` passes the default and is
the one production caller, so the seam's default policy gets its own
pin, per the honest-seams lens: a test drives `_act` with a fake
`_call` through both arms and asserts what each stream received. No
flag reaches the grammar, so every command runs under `Output.HUMAN`;
adopting `--json` later is the grammar setting the parameter, one
line, and the guide's deferral entry says so. Notices are not a second
stream the machine arm has to route: what the human renderers say on
stderr (a write's notice, a boundary sentence, a page cursor) is
derived from fields of the model the act read, so it travels in the
data and the machine arm prints nothing else. The deferral is repriced
in `docs/architecture/cli-guide.md`: the second bullet ("a second
format is a second no-leak audit") is replaced by the fact that the
audit is one test on the model, the entry keeps its "what would change
the answer" paragraph, since no consumer has appeared, and the
sentence about notices joins it.

### M4: an extension member, not the RFC's `type`

RFC 9457 makes `type` a URI reference and this API's `Problem`
deliberately leaves it absent, which its docstring explains: an absent
`type` is `about:blank`, and a title of the API's own would imply a
problem type the body does not identify. The issue's "problem-type
token" is therefore an extension member, which is the RFC's own
mechanism for a body that says more, and it is named `reason`, the
word this codebase already uses for a closed token drawn at a
decision site.

- `responses.py` declares `RefusalReason(StrEnum)`, six members, one
  per state the five sites can be in, kebab-case like `Applies`:
  `code-not-pending`, `agents-unknown`, `agent-not-serving`,
  `device-already-bound`, `provider-missing`, `mcp-server-missing`.
  The secret-holder refusal splits in two because the remedy names
  the holder's noun and the holder is one of exactly two kinds; the
  server states which, the client spells the command. `Problem` gains
  `reason: RefusalReason | None = None`, described in its docstring
  as the closed token a client may phrase a remedy from, with the
  reading rule the issue records. `Problem.detail`'s description stops
  claiming it is the sentence the CLI prints: it is the state the
  server refused in, in the server's own words, which a client holding
  the `reason` may extend in its own grammar, as the CLI does. The
  regenerated document carries the new description.
- `loader.ConfigError` gains a keyword-only `reason` argument stored
  beside `problems`, so every raise site keeps reading as it does and
  the five gain one keyword. `api._refusal` passes it through to
  `problem_response`, which takes it as a keyword defaulting to `None`.
  The token is chosen at the raise site, by the code that classified,
  never by message text.
- `reason` is absent from the wire when it is `None`, never `null`.
  `problem_response` dumps the model with the member excluded when it
  is unset, so the 401s, the malformed-request 422, the routing
  refusals, the storage 500s and every refusal outside the five keep
  exactly the member set they have today, and an older client keeps
  reading them. A case in `tests/unit/test_config_api_problems.py`
  asserts an unrelated refusal's body has exactly `title`, `status`,
  `detail` and `errors`, which is what makes the skew below five
  bodies rather than all of them.
- The five sentences lose their command spellings and keep their
  state. `_UNKNOWN_CODE` ends at "read the code currently on the
  device's screen and use that"; `_CLAIM_REFUSED` ends at "the code is
  still claimable. What was sent is not quoted back"; `_UNLOADED_AGENT`
  says an agent written since is served by the apply that installs it,
  and one that never existed is a name nothing answers to; `ALREADY_BOUND`
  ends at "the device reaches its agents at its next check"; the
  secret-holder sentence is `_missing(holder)` alone. After that,
  `store.py` no longer composes with `SERVER_PROGRAM`; `loader.served`
  still does, so the constant stays and only its comment moves: it
  claims a boot refusal, a runtime refusal and an event message compose
  with it, and #386's census found the first two no longer do and the
  third never did. The comment states the one composer that remains.
- The CLI reads `reason` tolerantly and phrases the remedy. `_refusal`
  in `reach.py` (in `cli.py` until M1 lands, since M4 goes first)
  applies the reading rule before validating: a `reason` that is a
  string but not a member is replaced by `None`, so a token from a
  newer server meets the fallback rather than the "body this client
  does not recognize" sentence, and everything else about the three
  agreements stays strict. `REMEDIES: dict[RefusalReason, str]` sits
  beside `_refusal`, its only consumer, spelled with `PROGRAM` the way
  `SPOKEN` is, and the printed sentence is `detail`, a space, and the
  remedy where the token is known, `detail` alone where it is not or
  where there is none.
- The skew, stated rather than hidden. A newer CLI reads an older
  server's body because the member defaults to absent. An older CLI
  against a newer server refuses the five bodies as unrecognized,
  because its `Problem` forbids the member it does not know. That is
  pre-release skew between two halves that ship together, and the
  wheel-grade lane tests the installed CLI against a server of the
  same tree; it is recorded here and in the changelog fragment, and
  nothing is built to bridge it.

## Design footprint

- **M4** deepens `responses.py` (the vocabulary grows a member the
  way `Applies` did), `loader.py` (`ConfigError` carries one more fact
  its raiser knows) and the CLI's refusal reader (it phrases what it
  knows and quotes what it does not). No new module; `REMEDIES` is a
  table beside its one consumer, per #386's own reasoning.
- **M1** turns one module into fifteen, listed above with what each
  hides. No seam is added: the package's modules import each other's
  names, which is what they did as one file, and the one seam that
  exists (the `Invocation` type and the `Act` row) is unchanged.
- **M2** deepens nothing and changes no code.
- **M3** deepens `answers.py` by one function and one token, and adds
  one parameter to the act runner, pinned at its default.

## Documentation footprint

- **M4**: `docs/reference/api-openapi.json` regenerates through
  `vinga-server config openapi` (the `Problem` schema gains the member
  and the `RefusalReason` component); the `Problem` docstring is the
  published description and changes with it. `docs/reference/cli.md`
  regenerates only if a help page changes, which none does. The
  changelog fragment records the five sentences' change and the skew.
  No hand-maintained page describes the five sentences; the feature
  doc `docs/features/2026-08-19-refusal-and-debug-hygiene.md` quotes
  one and is historical, so it is left as written.
- **M1**: `AGENTS.md` names `config/cli.py` nowhere; the design guide
  names it in two worked examples as history, left as written; the
  CLI guide's practices cite functions by name and none of the names
  change. `docs/reference/cli.md` is byte-identical or the milestone
  has failed. The `tests/census` manifests regenerate.
- **M2**: the implementation-doc section is the record, with the
  measurement's totals and the history result quoted.
- **M3**: `docs/architecture/cli-guide.md`, the `--json` deferral
  entry, repriced as described.

The 2026-09-20 comment's bookkeeping ask lands in M1's
implementation-doc section: for the eighteen test files it names,
whether the storage dependency became explicit in a signature, and the
count either way. The prediction, recorded here so the section can
falsify it: no, because M1 moves definitions and touches no fixture.

## Tests

Reusing what exists wherever the assertion already has a home.

- **M4**, server side: `tests/unit/test_config_api_pending.py` and
  `tests/unit/test_simulator_board.py` pin the sentences and gain the
  token; a new case per site asserts the body carries the member and
  the sentence names no command (`PROGRAM` and `SERVER_PROGRAM` absent
  from `detail`, the #386 invariant extended to these five). The
  closed-set pin: `set(REMEDIES) == set(RefusalReason)`, so a member
  added on one side alone is red. Client side, in
  `tests/unit/test_config_cli_rendering.py` beside the existing
  problem-document cases: a body with a known token prints `detail`
  plus the remedy; a body with an unknown token prints `detail`
  alone; a body with no member prints `detail` alone; a body whose
  `reason` is not a string is unrecognized. `tests/integration/test_cli_live.py`
  keeps its live case for the pending listing and gains the claim
  refusal end to end. Falsified first: each client case is run with
  the reading rule removed and watched fail.
- **M1**: the AST-identity script, run and its output quoted in the
  section; the existing suite, whose 47 touching files are re-pointed;
  the two structural tests rewritten as above, each watched failing
  against a planted violation (a second `check_transportable` call
  site in a family module; a server module added to the package's
  imports) before the rewrite is claimed.
- **M2**: no new test and no code; the committed measurement script
  and the section's quoted totals are the record.
- **M3**: `tests/unit/test_config_cli_rendering.py` gains the escape
  test on both encoders, watched failing with the escaping asserted
  the wrong way round, and the two-arm test through `_act` with a
  fake `_call`: the default arm renders and prints its notice on
  stderr, the machine arm writes the encoded model to stdout and
  nothing to stderr, and the default is asserted by calling `_act`
  without the parameter.
- **Reach-ins**: a new test reaches public names or the names the
  existing tests already reach; any new underscore reach-in is
  recorded in the manifest and named in the PR as the design question
  it is.

## Risks

- **A moved definition edited on the way.** The AST-identity script
  is the mitigation, and it is run rather than argued.
- **A patch that no longer reaches its consumer.** The five names are
  listed above with their consumers; the subagent retargets each and
  the test that patched it is watched to still change behaviour (a
  patch that reaches nothing passes silently, which is the surviving-
  mutation shape).
- **The import-weight inventory going stale mid-milestone.** It is
  the last thing regenerated, after every move, and the test that
  nothing outside the package imports the CLI is what would catch a
  family module reaching a server module.
- **Two generated manifests conflicting on the stacked rebases.**
  Regenerated on the rebased tree, never merged, per AGENTS.md.
- **The older-CLI skew reading as a defect in the field.** Stated in
  the changelog fragment and in the M4 section; nothing bridges it,
  and the pre-release stance is the recorded one.
- **Cycles reappearing.** The DAG holds only with the four prelude
  definitions placed as described; the M1 section re-runs
  `sections.py` against the package and quotes "acyclic: yes".

## Milestones

- [ ] **M4: refusal reasons.** `RefusalReason` and `Problem.reason`
  in `responses.py`, `ConfigError.reason` in `loader.py`, the five
  raise sites, the five sentences without their commands, the handler
  passing the token, the tolerant read and `REMEDIES` in the CLI, the
  `SERVER_PROGRAM` comment, the regenerated OpenAPI document, the
  tests above, a changelog fragment. Own PR, from this branch, first.
- [ ] **M1: the package.** `config/cli/` with the fifteen modules,
  every definition moved unchanged, the 47 test files re-pointed, the
  five patches retargeted, the two structural tests rewritten, the
  manifests regenerated, the AST-identity script and `cli_sections.py`
  under `tests/tools/` with their output in the section, the #489
  bookkeeping line. Stacked on M4.
- [ ] **M2: the measurement recorded.** `cli_fields.py` under
  `tests/tools/`, adapted to the package and re-run, and the section
  quoting the totals, the history result and the one dead branch as a
  discovery. No CLI code changes. Stacked on M1; low-stakes review
  tier.
- [ ] **M3: the dump, the dispatch and the repricing.** `Output` and
  `encoded` in `answers.py`, the `output` parameter on `_act` with
  `_performed` passing the default, the escape test and the two-arm
  test, the CLI guide entry. Stacked on M1, beside M2.

## Verification

- `uv run ruff check .`, `uv run pytest tests/unit -q`,
  `uv run pytest tests/integration -q`, `uv run pytest tests/census -q`
  from `vinga-server/`, per milestone.
- The generated-document drift checks: `vinga-server config openapi`
  against `docs/reference/api-openapi.json` (M4), and the CLI
  reference regeneration (M1, byte-identical).
- M1's AST-identity script, output quoted; `sections.py` re-run on
  the package, "acyclic: yes" quoted.
- The wheel-grade lane, which installs the CLI bare and drives it
  against a live server, on M1 and M4.

## Plan review round

Reviewed 2026-09-22 by openai/gpt-5.6-sol, thinking high via codex CLI 0.155.1, read-only sandbox, runtime 14m44s, at commit 30f951f5, plan blob 41694179.

Eight findings, verdict "not ready" pending the three P1 design
decisions. Condensed but faithful; the reviewer's evidence lines
refer to the plan as committed at that blob.

1. **P1: M3 omits the serialization dispatch the issue settled.** The
   plan declines the act-level dispatch, so `encoded()` has no caller
   and fails the deletion test: removing it changes nothing.
   Execution still ends in `act.render(act.read(answer))`. Add format
   selection at the `Act` rendering seam, defaulted to human without
   a CLI flag, route machine formats to `encoded()`, say how notices
   stay on stderr, and test both arms directly through `_act`.

   *Resolution*: accepted. The M3 section now puts the dispatch on
   `_act` as an `output` parameter defaulted to human, with
   `_performed` as the one production caller and a pin on the
   default; the machine arm writes the encoded model to stdout and
   nothing to stderr, and the section says why notices need no second
   route. The milestone drops its low-stakes tier, since it now
   changes the act runner.

2. **P1: M2 takes a third path the issue excludes.** The settled rule
   is per-family types on exposure, measurement and no code on none.
   The measurement finds exactly the targeted shape (`memory delete`
   reading an unset `file`) and the plan proposes a one-off `_typed`
   refactor. Either classify it as exposure and add the prescribed
   type, or justify that it is not exposure and land no code.

   *Resolution*: accepted, on the second branch. The measurement
   section now argues that a read whose default is the documented
   behaviour is a dead branch and not the exposure the issue priced,
   and M2 lands as the measurement and no code; the `_typed` tidy is
   withdrawn and the branch is recorded as a discovery.

3. **P1: `acts.py` keeps entity-family code and creates the cycle M1
   claims to remove.** `SHOW_ENTITY` needs `_print_entity`, which the
   plan puts in `entities.py`, while the entity and secret rows need
   `Act`: `acts -> entities -> acts`. The builders are not shared by
   every family. Keep only shared execution concepts in `acts.py`
   (`Invocation`, `Act`, `_act`, `_performed`, genuinely shared
   helpers) and put every entity-specific builder, table, renderer
   and secret row in `entities.py`.

   *Resolution*: accepted, and it exposed an omission: the plan had
   not said where `Invocation` lives. The entity tables and
   `_entity_path` move to `entities.py`, `acts.py` keeps only what
   every family reaches, `Invocation` gets `cli/invocation.py` as the
   package's lowest module (so `reach.py` can annotate with it without
   importing `acts.py`), and a rule for where each prelude constant
   lands is written down. Fifteen modules.

4. **P2: the rewritten transportability test still pins a filename,
   and the wrong one.** The calls sit inside `_fragment_body` and
   `_document_body`, which the family split puts in `entities.py` and
   `deployment.py`, not `input.py`. Assert the semantic property
   instead: every outbound fragment or document body passes through
   `check_transportable` before `_call`, plus the existing no-request
   and no-leak behaviour, with no exact CLI filename.

   *Resolution*: accepted. The test becomes a statement over the
   registry: every act body reaches `check_transportable` in its call
   graph, resolved the way the field audit resolves callables, and no
   CLI filename is named.

5. **P2: M3's YAML encoder cannot serialize every `_understood`
   value.** `_understood` dumps in Python mode, so `StrEnum` members
   such as `Applies` survive, and PyYAML's safe dumper has no
   representer for them. The control-character test would not meet
   this. Serialize a JSON-mode dump through both encoders and include
   an enum-bearing answer such as an acknowledgement in the test.

   *Resolution*: accepted. `encoded` dumps in JSON mode, the section
   says why that is the difference from `_understood`, and the escape
   test carries an acknowledgement's `applies`.

6. **P2: a defaulted `Problem.reason` alters every refusal body.**
   `problem_response` dumps the model without excluding `None`, so
   `"reason": null` would appear on 401s, malformed requests,
   unmatched routes and every other problem, and an older client
   forbids that member. Omit `reason` from the wire when it is
   `None`, and assert in `test_config_api_problems.py` that an
   unrelated refusal keeps its exact member set.

   *Resolution*: accepted, and it would have been a field defect: the
   skew would have covered every refusal, not five. The member is
   excluded from the dump when unset and a test pins an unrelated
   refusal's exact member set.

7. **P2: the published `Problem.detail` contract becomes false.** Its
   description says `detail` is the same sentence the CLI prints;
   after M4 the CLI prints `detail` plus a remedy for a known reason.
   Revise the description to server-owned state prose that a client
   with the `reason` may extend, and regenerate the document.

   *Resolution*: accepted. The `detail` description is revised in the
   M4 section and travels into the regenerated document.

8. **P2: the proposed cycle proof does not inspect the import graph.**
   `sections.py` excludes import-bound names, and once the file is a
   package the relevant cycle mechanisms are module imports,
   initialization order and `__init__.py`. Add a static
   module-import graph check including `__init__.py`, import each
   module in a fresh interpreter, and keep the definition-reference
   measurement as supporting evidence.
