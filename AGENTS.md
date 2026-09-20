# Agent guidance for vinga

vinga is a self-hostable voice agent: ESP32-S3 devices (mic, speaker,
display) talk to a Python conversation server over WebSocket. It builds on
78/xiaozhi-esp32 (device firmware) and xinnan-tech/xiaozhi-esp32-server
(server), both MIT.

## Repository layout

- `vinga-server/`: the conversation server (Python). OTA/config HTTP endpoint,
  WebSocket audio channel, VAD → ASR → LLM → TTS pipeline with pluggable
  providers (LLM, voice, MCP tools).
- `vinga-esp32/`: thin firmware customization on top of upstream
  xiaozhi-esp32 (ESP-IDF v6.0.x, target `esp32s3`).
- `docs/README.md`: the documentation index, and the authority taxonomy
  that says which class a page belongs to and therefore what it may
  claim. Start here when you need to know where a fact lives.
- `docs/xiaozhi-notes.md`: research notes on the device↔server protocol,
  key by key, and on the upstream projects it came from. Read this first
  for anything protocol-related. Board procedures and per-board behavior
  are not here; they are in `docs/devices/`.
- `docs/architecture/product-promises.md`: the standing commitments to the
  person running vinga, falsifiable from outside. They take precedence over
  everything below.
- `docs/architecture/guidelines.md`: vinga's identity and the revisable
  defaults that keep those promises, each with an example and a
  counterexample. Read both before designing a feature or deciding
  direction.
- `vendor/`: reference clones of the upstream repos. Not committed; recreate
  with the clone commands at the top of `docs/xiaozhi-notes.md`.

## Commands

All vinga-server commands run from the `vinga-server/` directory. Use `uv`
for Python; never `pip install` directly.

```bash
uv sync                          # Install/update dependencies
uv run vinga-server             # Run the server (--config or VINGA_CONFIG)
uv run pytest tests/unit -q      # Unit tests
uv run pytest tests/integration -q  # Integration tests
uv run ruff check .              # Lint

# Both lanes the way CI runs them: distributed over worker
# processes, a file at a time. Local runs are serial by default;
# this is how to reproduce a failure that only shows up in CI.
uv run pytest tests/unit -q -n auto --dist loadfile
uv run pytest tests/integration -q -n auto --dist loadfile
```

CI (`.github/workflows/vinga-server.yml`) runs the same lint, unit, and
integration steps in two parallel jobs: `unit` (the compose file's two
resolutions, lint, the events package's type check, the unit tests) and
`integration` (the integration tests, the generated-document drift
checks, the wheel migration). A third job, `image`, builds and smokes
both image variants on everything but a pull request, and boots the
committed compose file against the image it just built. The workflow
runs on pull requests, and on pushes to `main`, when the change touches
`vinga-server/`, `docs/reference/`, `docker-compose.yml`, `deploy/`, or
the workflow file itself; a
`workflow_dispatch` runs it against any branch whatever the change
touched. Every other change (documentation, the skills, this file) runs
`.github/workflows/docs.yml` instead, whose `paths-ignore` mirrors the
server workflow's paths: it checks internal links and anchors
(`scripts/check_doc_links.py`) and runs the command-spellings census,
which sweeps every tracked file, so a documentation change can stale
it: a spelling a document starts or stops quoting, or a move that gives
one another class. On a pull request it also refuses an edit to
`CHANGELOG.md` and holds every `changelog.d/` fragment to its shape.
Between the two workflows every change runs the census somewhere. A
third workflow, `.github/workflows/changelog-fold.yml`, runs only on a
push to `main` that touches `changelog.d/`: it folds the fragments into
the dated changelog section and pushes the result, which is the one bot
commit this repository makes.

### Restoring a file mid-experiment

Two traps, neither guessable, both of which have already cost a session.

- **Do not restore with `git checkout <file>`.** It restores the committed
  version, which silently discards unrelated uncommitted edits to that file.
  Copy the file aside first and copy it back.
- **After restoring a file, `touch` it.** A cached `.pyc` records the source's
  size and its mtime in whole seconds, and CPython accepts the cache when both
  still match. Restoring carries the backup's mtime rather than the current
  time, which can land back on the second the cache was compiled on, so the
  interpreter keeps running the pre-restore version. The test suite writes no
  bytecode and clears the caches it finds (`tests/conftest.py`), so pytest is
  safe, but anything run outside it is not. Export
  `PYTHONDONTWRITEBYTECODE=1` for those, or clear `__pycache__`.

The same shape bites a revert-run-restore cycle that checks a regression test
really fails without its fix: swapping two statements preserves the byte count,
a scripted cycle finishes inside one second, and the `.pyc` validation looks at
nothing else. If a result ever contradicts the source you are reading, suspect
this before suspecting the code.

### A stale `uv` build cache, wearing a database's error message

Third cache of the same family, and the one that lies about where the fault
is. The tier-closure lane (`tests/integration/test_tier_closure.py`) builds
throwaway installs with `uv sync --frozen --no-dev --no-editable`, and `uv`
can reuse a cached build of this project. When it does, the install is missing
every migration added since that cache entry was made, while the lane migrates
its own database from the source tree. The install then meets a database
stamped at a revision its packaged scripts do not contain.

What that reads as is the trap. Alembic raises `Can't locate revision
identified by ...`, which is neither cause `db.migration_failure` recognizes,
so it falls through to the general sentence: **`cannot open the vinga
database`**, naming host, port, credentials and a database that is open and
reachable throughout. CI never sees it, because its cache is cold.

`uv cache clean vinga-server` and rerun. Confirm the diagnosis rather than
assuming it, by listing the built venv's
`site-packages/vinga_server/conversations/migrations/versions/` against the
source tree; the venv's path is in the failure's own traceback. Nothing in
the repository is wrong when this happens, so a fix committed in response to
it is a fix to the wrong thing.

### Rebasing a milestone branch

Three traps, all of which cost this repository work in one session. They
share a shape with the two above: a command that silently discards
something, run because the tedious alternative invited automating it.

- **Never `git rebase --skip`, and never as a fallback after
  `--continue`.** It discards the commit being applied. A helper written
  to resolve this repository's two recurring rebase conflicts ended each
  iteration with `--continue || --skip || break`, and on one branch it
  discarded nineteen commits of a finished milestone and exited 0. The
  only safe fallback is `|| break`, which stops and surfaces the
  conflict. Resolve an unexpected conflict by reading it, not by
  reaching for the next flag.
- **`git fetch` and reset to `origin/<branch>` before rebasing a branch a
  pull request may have merged into.** A milestone that merged into its
  plan branch on GitHub is not in the worktree that created it, so the
  local branch can be many commits behind while looking healthy. Rebasing
  that and force-pushing deletes the merged milestone from the branch.
- **Check the work is there afterwards, by content and not only by
  count.** `git rev-list --count <base>..HEAD` is a useful alarm: a
  number that should rise and falls means look. It is not a verdict in
  either direction, because a regenerated-artifact commit legitimately
  becomes empty during a rebase and git drops it. What settles it is
  grepping for the milestone's own symbols, and the unit-test count,
  which is what actually caught the nineteen lost commits.

Two files used to conflict on almost every rebase here. One of those
conflict classes is gone and the other has a known resolution.

The dated `CHANGELOG.md` section can no longer conflict, because a
branch never edits that file. It writes one
`changelog.d/<issue>-<slug>.md` with the entry in final form, and
`.github/workflows/changelog-fold.yml` folds the fragments into the
dated section on `main` after the merge; a `docs.yml` step refuses a
pull request that touches `CHANGELOG.md`, naming the fragment as the
remedy. Two branches adding two files have nothing to merge, so there
is no recipe here any more: `changelog.d/README.md` states the
contract, and a rebase that still reports a `CHANGELOG.md` conflict
means a branch edited the file and should not have.

`vinga-server/tests/unit/command-spellings.txt` is the one that
remains. It is generated and must be **regenerated on the rebased
tree** rather than merged, since a textual merge of it is a state no
generator produced. The manifest records no positions, so a change
that only shifts a line leaves it alone: it moves when the distinct
set of classified spellings moves, one line per spelling added,
removed or reclassified, which git merges cleanly. Regenerating on the
rebased tree stays the rule for the times it does conflict, and
`test_the_manifest_is_the_census` is what enforces it, in both
workflows: the manifest is rendered again and diffed, so a spliced
resolution is a red run rather than a committed state no generator
produced.

And the habit both classes taught, which outlives them: after any
rebase, grep the tree for conflict markers before pushing, and count
what should have changed. A resolution that left a marker behind, or
that dropped a hunk, is invisible in a diff nobody reads line by
line.

### Whether a branch has landed, in a repository that rebase-merges

This repository allows rebase merges only, so a merge rewrites every
commit hash. That breaks both of the obvious ways to ask whether a
branch's work is on `main`, and they fail in opposite directions, so
believing either one costs something.

- **`git merge-base --is-ancestor <branch> origin/main` answers no for
  everything.** During one cleanup it called all 29 worktree branches
  unmerged, two dozen of which had pull requests merged weeks earlier.
  Taken at face value it means nothing is ever safe to delete.
- **`git cherry main <branch>` is closer and still not decisive.** It
  compares patch ids, and a patch id is computed from the diff
  including its context lines. Rebasing a stacked branch onto a new
  base shifts that context, so the id moves even when the content is
  identical. Two milestone branches came back with five and six
  commits apparently not on `main`, which reads exactly like work about
  to be destroyed. All eleven were on `main`.

What settles it, in order: ask GitHub, since a merged pull request is
the fact (`gh pr list --repo rafacm/vinga --head <branch> --state all
--json number,state`); then, for whatever `git cherry` still flags,
compare each commit's subject against `main`, because a commit that
landed in rebased form keeps its subject. A branch with no pull request
at all is the genuinely ambiguous case, and the question to ask there
is whether its issue is still open: one such branch held six unique
commits against an open issue and was live work rather than litter.

Two smaller traps in the same territory. **`git branch -d` refuses
every landed branch here**, for the same reason `--is-ancestor` does,
so cleanup needs `-D`, which does not second-guess the caller; that is
what makes the checks above load-bearing rather than ceremonial. And
**removing a worktree keeps its branch**, so worktree cleanup is safe
whatever the merge status, while branch deletion is the step that needs
the care.

One reading that looks alarming and is not: `git stash list` is
repository-wide rather than per worktree, so the same two stashes
appear against every worktree and are two stashes, not two per tree.


### A completeness check piped through `head`

The fourth trap of the family above, and the one that lies by
agreeing with you. A search whose *completeness* is the claim
(`grep -rn <old path>` before declaring a rename finished, `git
ls-files | grep` before saying nothing else references something)
answers the question only if you see all of it. Piped through `head`,
`tail`, `-m 1` or a truncating pager, it returns a prefix that looks
exactly like the whole answer and contains no sign that anything was
cut.

It cost this repository twice in one session, 2026-09-20, both times
on #489. Once a file classification came back wrong because the run
that produced it was summarized with `-rf`, which lists failures and
hides errors, and errors are how a storage test fails when
provisioning is off; the count was out by fifteen files and the wrong
number reached a committed document. Once a stale path survived a
rename sweep because it sat below a `head -20`, and the
implementation doc then claimed in writing that only historical
references remained. An external review caught the second; the first
was caught only because a later measurement contradicted it.

So: **truncate what you scan, never what you act on.** When the answer
is "how many" or "is that all", pipe to `wc -l`, to `sort -u`, or to
a file you then read in full, and let the count be the thing you
quote. Reserve `head` for looking, and never use it in the command
whose output becomes a claim. The same applies to a test run standing
in for an inventory: `-ra` reports errors as well as failures, and
`-rf` silently does not.

## Workflow

- Implementing an issue end to end follows the pipeline encoded in
  the `implement-issue` project skill (`.claude/skills/`): committed
  plan, external plan review, per-milestone subagents in stacked
  worktrees, a PR per milestone with its own review round. External
  reviews of plans and PR diffs use the `external-review` skill.
- Before beginning any new work: verify the current branch is `main`
  (`git branch --show-current`), pull latest changes (`git pull --rebase`),
  and stop to ask for guidance if either step has problems.
- All code work happens on a dedicated branch off `main` with a descriptive
  name (e.g. `feature/ota-endpoint`, `fix/opus-framing`), merged back via
  pull request. Never commit code directly to `main`. Documentation-only
  changes may go straight to `main`.
- The repository allows rebase merges only; squash and merge commits are
  disabled.
- Commit in small, human-digestible units: one logical change per commit
  (e.g. package skeleton, tests, and CI workflow are three commits, not
  one). Every commit has an imperative title of roughly 50 characters and a
  body explaining the what and the why.

## Design conventions

Modules are judged by depth: how much a caller gets for how little it has to
know. The method and its worked examples from merged vinga code are in
[`docs/architecture/design-guide.md`](docs/architecture/design-guide.md).

- **Module**: a file, or a package when its parts change for separate reasons.
  **Interface**: everything a caller must know. **Implementation**: what the
  module knows so its callers do not. **Depth**: the second divided by the
  first, and the number to maximize.
- **Seam**: a crossing stated as a type, not implied by a shared object both
  sides mutate (`device/boundary.py`). **Adapter**: a module translating at a
  seam so one side stops speaking the other's vocabulary; thin is fine, a
  pass-through is not. **Locality**: every fact has one home, and everything
  that needs it reads it from there.
- **The deletion test**: if a module did not exist and its body were inlined
  into its only caller, would the caller get harder to read? If not, it is a
  pass-through and should not exist.
- **The proportion test**: a structure earns itself against the cheapest
  thing that would also solve the problem, not against doing nothing. Before
  adding a boundary, a lane, a layer, a retry or any other mechanism, price
  the one-function change that would buy the same outcome, and measure the
  difference where the claim is a number. Two measured cases, both from
  2026-09-20: #537's lane failure looked like it wanted a bounded-retry seam
  around every connect, and the cap that replaced it bought seconds no green
  run had ever demonstrated the retry would beat; #489 proposed an enforced
  pure/storage boundary across 219 test files, and it measured 7.3s against
  7.4s for one reused connection in one function. Where the deletion test
  asks whether a module should exist at all, this one asks whether a
  justified structure is the cheapest shape of its own justification.
- **The interface is the test surface**: a test reaches the names a caller
  reaches. An underscore reach-in in a new test is a review flag: either the
  module lacks an interface callers need, or the test pins a detail.
- Prefer deepening an existing module over adding a pass-through beside it: a
  layer that forwards its arguments adds a name and hides nothing.
- A new domain concept gets its own module rather than a thousandth line in an
  existing file. Length is evidence of a second responsibility, never by
  itself a reason to cut a file where it felt tiring.
- Two structures that must agree are one structure with a bug pending. Derive
  the second from the first.

Commands are held to a standard of their own, in
[`docs/architecture/cli-guide.md`](docs/architecture/cli-guide.md): noun
first and verb second, leading positionals are identity addressing in the
API's own order with payload positionals behind them, and system-level
verbs stay flat. Each practice carries an example from the merged CLI and
the shape it rejects, and each rejected shape is labelled merged,
historical or constructed. Read it before adding a command, a noun, a
verb or a flag.

## Documentation process

- When a plan is accepted, commit it to `docs/plans/` as one Markdown file
  with a `YYYY-MM-DD-` date prefix (e.g. `2026-08-02-vinga-server-v1.md`).
- Each plan has a companion implementation doc, same filename with an
  `-implementation` suffix (e.g.
  `2026-08-02-vinga-server-v1-implementation.md`), with one section per
  milestone appended in the same change that ticks the milestone checklist.
  It records deviations from the plan, resolutions of the plan's open
  questions, and discoveries; a milestone with no deviations says so
  explicitly.
- Significant changes outside any active plan get a feature doc in
  `docs/features/`, same date-prefix naming, covering: Problem, Changes,
  Key parameters, Verification, and Files modified. Milestone work under a
  plan is documented by the implementation doc and the PR instead. No
  session transcripts are kept in this repository.
- Every plan and feature doc carries one "Local baseline" line: not
  applicable, outside (with the reason), or joins (citing the recorded
  decision and updating `docs/architecture/product-promises.md` in the
  same change). The rule is the enumerated-baseline record in
  `docs/adr/`; the line makes the membership decision explicit where
  it applies and costs one line where it does not.
- Every plan carries one "Cheapest alternative" line, which is the
  proportion test written down: the smallest change that would also solve
  the stated problem, and what this plan's proposal buys over it. Where that
  gain is a number, it is measured before the plan is committed rather than
  estimated, because an estimate is exactly what a proposal's author is
  worst placed to make. "None, this is the smallest change that works" is
  the honest answer most of the time and costs one line; a plan that cannot
  name any cheaper alternative has usually not looked for one. The two cases
  this rule came from are in the design conventions above.
- Active plans keep a milestone checklist that doubles as the milestone
  descriptions (one annotated checkbox item per milestone, no separate
  status list). Tick the milestone (with its PR number) in the same change
  that completes it, and turn its name into a link to its section in the
  implementation doc, so a fresh session can resume from the repository
  alone.
- PR descriptions include a Verification section as a task list. Check a box
  only when that step was actually carried out; leave it unchecked with a
  short note when it cannot be verified yet. Unchecked boxes are
  information, never decoration.
- Keep in sync: the hardware tables in `README.md` and
  `vinga-esp32/README.md` list the same boards and must move together. When
  the vinga-server config schema changes, update `config.example.yaml` in
  the same change.

## Writing conventions

- Never use em-dashes anywhere: docs, commit messages, code comments.
  Rephrase with commas, colons, semicolons, parentheses, or sentence breaks.
- `CHANGELOG.md` follows Keep a Changelog 1.1.0, but with dates
  (`## YYYY-MM-DD`) as section headers instead of version numbers. Group
  entries under `### Added`, `### Changed`, `### Deprecated`, `### Removed`,
  `### Fixed`, `### Security`. Record every notable change, and record it
  as a fragment: a branch writes `changelog.d/<issue>-<slug>.md` carrying
  those `###` headings and the entry text exactly as it should read in
  `CHANGELOG.md`, states no date (the fold derives the day from the
  commit that brought the fragment onto `main`), and never edits
  `CHANGELOG.md` itself. The fold workflow moves the text into the dated
  section after the merge, and a pull-request check refuses the direct
  edit; `changelog.d/README.md` states the contract. A
  documentation-only change pushed straight to `main` may still edit the
  file, since nothing can conflict with it there, and either spelling
  works for one.
- Name open-source orchestrators and tooling where naming them is what
  makes a procedure runnable: Kubernetes, Docker Compose, an ingress
  controller. Do not name specific hosting providers in documentation;
  describe where a deployment runs generically (a container image, your
  own infrastructure).
- README style follows clew.nvim conventions: centered header with logo and
  etymology, early-development warning, 🚧 marks for unimplemented features,
  honest status reporting.

## Licensing rules

- The project is MIT. When copying or deriving from the upstream repos, keep
  their license notices intact (see `THIRD_PARTY_LICENSES.md`).
- Keep TTS engines as optional pluggable providers; the `edge-tts` Python
  package is GPL-3.0 and must not become a hard dependency of the core
  server.
- Model weights (SenseVoice, Silero, ESP-SR wake words) are downloaded at
  deploy time, never committed or redistributed.

## GitHub API (`gh`) tips

- **Always pass `--repo rafacm/vinga`.** `gh` infers the repository from
  the working directory's git remote, and `vendor/` holds clones of the
  upstream projects, so a `gh` command run from `vendor/xiaozhi-esp32`
  targets `78/xiaozhi-esp32` instead. A `cd` into a vendor clone to read
  firmware source is an ordinary thing to do mid-task, and it silently
  redirects every `gh` call after it. This has already happened once: an
  `issue edit` went to the upstream repository and failed only because
  the account has no write access there. A `gh issue comment` would have
  posted to a stranger's tracker instead of failing.
  `export GH_REPO=rafacm/vinga` at the start of a session overrides the
  inference for `issue`, `pr` and `api`, and is worth doing as well, not
  instead: the flag is what makes the intent visible in the command that
  gets reviewed. Do not check that it worked with `gh repo view`, which
  reports the working directory's repository whatever `GH_REPO` says;
  `gh issue list` is the honest test.
- Wrap request bodies containing backticks in a `$(cat <<'EOF' ... EOF)`
  heredoc; bare backticks in `-f body="..."` are interpreted by zsh.
- Reply to a PR review comment by POSTing to
  `repos/OWNER/REPO/pulls/PR/comments` with `-F in_reply_to=COMMENT_ID`;
  there is no `/replies` sub-endpoint (it returns 404).
- PR review comments live at `pulls/PR/comments`; general PR comments at
  `issues/PR/comments` (PRs are issues).

## Hardware context

Primary test device: Waveshare ESP32-S3-Touch-LCD-1.54 (ESP32-S3, 16 MB
flash, 8 MB PSRAM). Flashing uses esptool with merged binaries at offset
`0x0`; the device's backend URL lives in NVS (namespace `wifi`, key
`ota_url`, partition at `0x9000`). How to write that entry, reset the
board, read its boot log and dump its NVS over serial, which is what a
device checkpoint runs on, is in `docs/devices/README.md`; what this
board in particular does is in its own guide beside it. The protocol
those procedures exercise, and the upstream reply-language trap, are in
`docs/xiaozhi-notes.md`.
