# A guide a coding agent can be pointed at: implementation

Companion to
[`2026-10-06-coding-agent-guide.md`](2026-10-06-coding-agent-guide.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the guide

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.289; 2026-10-06.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| D9's first part: Getting Started's secrets generated into the file | `README.md`, step 1's `.env` block | `Generate Getting Started's secrets into the file` |
| Decisions 1 to 8, D1 to D5, D9's handoffs | `docs/run/with-a-coding-agent.md` (new) | `Add the guide a coding agent is pointed at` |
| D6: the four doors | `docs/run/README.md` (first section), `docs/README.md` (Run door), `README.md` (Getting Started's opening), `AGENTS.md` (repository layout, its only change) | `Link the coding-agent guide from its four doors` |
| D7's findings folded back | `docs/run/with-a-coding-agent.md` | `Fold the guide's execution back into it` |
| The cold read's findings folded back, and a rewrap | `docs/run/with-a-coding-agent.md` | `Fold the cold read back into the guide`, `Rewrap the guide's edited paragraphs` |
| The fragment, `### Added` | `changelog.d/611-coding-agent-guide.md` | this section's commit |
| This record and the tick | this file, the plan | this section's commit |

The page is ordered as the work is: read at the revision (decision 2,
D1, D1a, D1b), learn the model (decision 3), the three rules with
their failure modes (decision 5, D2), the person-run steps (D9), the
order of the work (decision 4, decision 8's linked index), the
interview (decision 6, D3, D3a), and closing the loop (decision 7, D4,
D4a, D4b). Nothing on it is future (D5): the D8c sweep below has three
hits, all about the reader.

### Deviations from the plan

- **With onboarding off, the person runs the simulator; the coding
  agent does not ask for the URL.** D4a says to ask the person for the
  OTA URL their boards use. `vinga info` answers, in that case, that
  the path `server.ota_path` names "is not printed here, since it is
  this deployment's secret" (`config/cli/deployment.py` L135, run in
  `.logs/d7-run.txt`). Asking for it would put what the server calls a
  secret in the coding agent's transcript, against D2's third rule, so
  the page makes it a person-run step: the coding agent hands over the
  simulator line with the URL left to fill in and watches the events.
- **D4a's "the image's CLI, which carries the extra" is true in
  effect, not by the extra.** The Dockerfile says the `sim` extra is
  deliberately not in the image (`vinga-server/Dockerfile` L34). The
  image runs `vinga simulator run` all the same, because `websockets`
  arrives with the `serve` extra, through `uvicorn[standard]`
  (`uv.lock` L1851 names it under `serve`, L1796 lists `websockets`
  among uvicorn's `standard` dependencies). The published
  `ghcr.io/rafacm/vinga-server:slim` at `9d489f0f638e` held a whole
  turn this way (`.logs/d7-run.txt`, "7 (image)"). The page says the
  image's client runs it as it is, which is what was observed; whether
  the Dockerfile comment or the dependency is the one to change is for
  their owner.
- **The workstation install line carries the `sim` extra.** Section 1
  installs `vinga-server[sim] @ git+...@<revision>` rather than the
  bare client, so the one client the page asks for can do everything
  section 7 asks of it. A client without the extra was run too, and
  names the extra and stops.
- **Two additions D7 found that the plan did not name.** A server run
  from a checkout takes its client from the same checkout, run in the
  deployment's directory without syncing it (`uv run --no-sync
  --project <checkout>/vinga-server vinga info`), which D1 implies and
  section 1 now says; and
  `vinga check` is named for a refused `vinga diff` as well as a
  refused apply, since the diff refuses an uncomposable store with the
  same unlocated sentence.

### Resolutions

- **D8's follow-ups** are comments on #610 and #613 naming the line
  each must add; they are GitHub writes, left to the orchestrator.
- **D1's form for a checkout.** A checkout's revision is not always
  `-g<hash>`: with no tag reachable, `git describe --always` prints a
  bare abbreviated hash, which can be shorter than twelve characters.
  The page reads "twelve hexadecimal characters and nothing else" as
  the published image, and anything else as a checkout.

### Discoveries

- **The old `.env` block did not leak under shell tracing.** D9 calls
  Getting Started's command substitution inside an unquoted heredoc a
  shell expansion of the secrets, carrying #609's follow-up. Measured
  before the rewrite, under `bash -x` and `zsh -x`, neither secret
  appeared in the trace: the substitution's output goes into the
  heredoc, not into a traced line (`.logs/d9-env-block-xtrace.txt`).
  The rewrite is made as the plan says, and what it buys is one form
  across Getting Started and the security guide, with no value ever
  passing through the shell, rather than a measured leak closed. After
  the rewrite both shells trace no value either, and the file is mode
  600 in both.
- **A failed turn exits 0.** With an `openai_compatible` entry pointed
  at a port nothing listens on, the simulator printed the agent's
  fallback phrase after `said:` and exited 0; the stream had
  `provider_failed` and `reply_fallback` and no `replied`
  (`.logs/d7-events-failure.txt`). The page judges a turn by the
  stream for that reason.
- **Stopping a background stream.** `kill -INT` does not stop
  `vinga events tail --follow` started with `&` from a non-interactive
  shell, which starts background jobs with SIGINT ignored, and a
  `pkill -f "events tail"` killed the shell that ran it, twice, in this
  run. The page says to send TERM to the process id.
- **The security guide writes the master key into `vinga.env`**, where
  Getting Started's file is `.env`; the page says which file to use.
  The same guide generated the key with the host's `python` and
  `cryptography`, which a host following Getting Started need not
  have; the review round's second finding replaced that form.

### Execution record (D7)

On agentpi (Raspberry Pi 5, rootless Podman 5.4.2 behind the Docker
CLI), 2026-10-06. The server ran from this worktree's environment
(`uv sync` in `vinga-server/`) on `127.0.0.1:8611`, against its own
database `vinga_611`, created as the compose superuser on the running
`vinga-postgres-1` and dropped at the end, from a deployment directory
whose `.env` was written by Getting Started's rewritten block (with
`LAN_IP=127.0.0.1` and the port moved). The development database was
not touched. Every command is in `.logs/d7-run.txt` with its output and
exit code, in the page's order; the event streams are
`.logs/d7-events-*.txt`.

| Page section | Run | Outcome |
| --- | --- | --- |
| 1, the revision | `curl -s .../healthz`, `vinga info` | the checkout form, `spike/openapi-ts-client-2452-g1e235400`; `.../commit/1e235400` answers 404, the branch being unpushed, which is the page's "confirm before reading there" case |
| 1, published-image URLs | at `main`'s `9d489f0f638e` (`.logs/revision-urls.txt`) | `raw` and `blob` for `README.md` 200; this page 404 there, the page's "older than this page" case; `commit/9d489f0f638e` 200 |
| 1, the workstation client | `uv tool install "vinga-server[sim] @ git+file://...@1e2354002553#subdirectory=vinga-server"` into a throwaway tool directory, removed afterwards | installed, `--version` answers; `git+file` stands in for `github.com`, the branch being unpushed. The GitHub form with a twelve-character revision resolved separately (`uvx`, `.logs/uv-short-sha-probe.txt`) |
| 1, the checkout's client | `uv run --project <worktree>/vinga-server vinga info`, from the deployment directory, and with `--no-sync` after the cold read | answers, both |
| 1, the image's client | `docker compose exec -T vinga vinga info` | not run in the first pass, for want of a Compose deployment; run in the review round against one (below), and answered |
| 3 | `vinga --help`, `agent --help`, `agent set --help`, `schema agent`, `reference`, `list`, `show`, `diff`; `schema` and `reference` from the workstation client too | all exit 0 |
| 4, the master key | the security guide's block as it then stood (host `python`), with `.env` for `vinga.env`, then a restart | file mode 600; no secret value anywhere under `.logs/` (checked by value). The block was replaced in the review round, and its replacement run there |
| 4, a key at the prompt | `vinga provider secret set llm claude api_key` in a pty, a dummy value typed (`claude` written first) | prompt `Secret (not echoed):`, the dummy absent from the terminal transcript, `vinga show` prints `********` |
| 4, the env-file form and the NVS write | | not run: an editor session and a board, the two that remain unrun; the env-file form was run for the LLM guide |
| 5 | Getting Started as a whole | not run: that is #610's walkthrough; the `.env` block was run |
| 6 | `info`, `list`, `diff` (one pending entry from section 4), `import -f -` of a mock document, `agent export`, an edit, `agent set`, `diff`, `apply` | the first apply and the diff before it refused without saying where; `vinga check` named `default_agent`; set, diffed, applied |
| 7, worktree client | `events tail --follow` started first, then `simulator run` | `ota_check prompt_assembled session_open turn_started heard llm_round speaking_started reply_finished replied speaking_finished session_closed` |
| 7, workstation client | the same, both from the tool install | the same eleven events |
| 7, the image's client | `docker run --network host ... ghcr.io/rafacm/vinga-server:slim simulator run` | the same eleven events |
| 7, no `sim` extra | `uvx` from GitHub at `9d489f0f638e`, `simulator run` | names the extra, exit 1 |
| 7, a failing turn | an `openai_compatible` entry on a closed port | `provider_failed`, `reply_fallback`, no `replied`; simulator exit 0; reverted afterwards |
| 7, the records | recording on, `session list`, `session show`, `conversation list`, `conversation show` | each answered; the review round cut the page to `session show` and, with consent, `conversation show`, both of which ran here |
| 7, a board | `events tail --follow --device aa:bb:cc:dd:ee:ff`, the simulator with that `--mac`; `device pending list` | only that MAC's events, `ota_check` with `agents=["assistant"]`, then the turn; nothing pending |
| 7, onboarding off | restart with `VINGA_SERVER__ONBOARDING__ENABLED=false`, `vinga info` | the sentence naming `server.ota_path` as the deployment's secret |

### The cold read

A smoke test of the page, not #610's walkthrough: one fresh subagent
(general-purpose, the same model) was given the page's revision rule,
the server's address, the deployment directory (whose `.env` carried
the address and the token, so neither was in its prompt) and the
checkout's path, and the goal "configure this deployment with one
agent called kitchen that uses the mock providers, and prove a reply
comes back". The person was unavailable to it, so it was told to write
down what it would have asked or handed over. It ran against a fresh
database, `vinga_611_cold`, with the server at `36220dc0`.

It met the goal: `kitchen` on `mock` for all four stages, made the
`default_agent`, applied, and a simulator turn whose stream read
`ota_check`, `prompt_assembled`, `session_open`, `turn_started`,
`heard`, `llm_round`, `speaking_started`, `reply_finished`, `replied`,
`speaking_finished`, `session_closed`, with no failure event. It
diffed before writing and before applying, named itself a coding
agent, stopped its stream by process id, and reports that no secret
reached its view: it listed `.env` and never opened it. Where it
misread, stalled or guessed, and what became of each:

| Where | Disposition |
| --- | --- |
| It read the page before asking the revision, since how to ask is on the page | fixed: the opening says to do section 1 first and reread at the server's revision if they differ |
| Nothing says to confirm the `-g` hash is the checkout's `HEAD` | fixed: section 1 says to confirm it, and to say so and ask when it differs |
| "Every page it links" read as all nineteen at once | fixed: each linked page is read at the revision when its step is reached |
| `uv run --project` may sync the checkout's environment | fixed: `--no-sync`, run in `.logs/d7-run.txt` |
| No guide in the index names adding an agent | fixed: when no guide names the task, Configuring a deployment and `--help` |
| The third question assumed `assistant` exists, and it chose `default_agent` itself | fixed: the question reads "the agents that are stored", and the binding-or-default choice is said to be the person's |
| Whether the onboarding URL is sensitive, beside the `ota_path` one | fixed: it is printed to whoever holds the API's token and is the coding agent's to use |
| A stream started through `uv run` has uv's process id | fixed: said, and TERM to it ends the client too, as it observed |
| `mock` is in neither the domain reference, the schema, the examples nor `--help`; only the providers table names it, "in tests" | recorded, not fixed: the type is a test double and the goal was this smoke test's; documenting it is not this page's to do |
| Configuring a deployment fetches a preset from `main` and mixes `vinga-server config` and `vinga` spellings | recorded, not fixed: that page's own; this page's rule fetches every file at the server's revision |
| Its first question did not fit `mock`, which is neither local nor a vendor's | recorded, not fixed, for the same reason as the type |

### Inventories

Untruncated, `path:line` pairs only (D8d), under `.logs/`.

- **D9's credential sweep** over the guide and every page it links,
  twenty files (`.logs/d9-swept-files.txt`), for secret-named
  expansions, secrets made by command substitution, credentials on a
  `curl` command line, literals in `--from-literal` or `-e NAME=`, the
  NVS password row, `export` of a secret-named variable, and a database
  URL with a password (`.logs/d9-sweep.txt`, rerun on the final page as
  `.logs/d9-sweep-final.txt`, the same four hits). The first pattern was
  checked against `docs/run/`, where it does match
  (`tools-and-mcp.md`, not a linked page). Four hits:
  - `README.md:291` and `docs/devices/README.md:139`, the NVS CSV's
    password row: person-run handoffs on the guide (section 4), never
    run or read by the coding agent.
  - `docs/contributing.md:177`, the smoke lane's throwaway values: no
    deployment's credential, on a page the guide links only to say it
    is not this task's.
  - `docs/reference/cli.md:359`, `export VINGA_API_SECRET=...` under
    "Reaching a server": left. It is the person's form for a client
    with no `.env`, which puts the token in their shell's history; the
    guide's clients read the token from the deployment's `.env`, and
    its third rule keeps the coding agent from typing it. A safer form
    there is the CLI reference's own change to make.
- **D8c over the new text**: three hits on the final guide
  (`.logs/d8c-sweep-final.txt`), lines 9, 129 and 246 ("you ... will
  have read", "the agent will do it" as an example of the word
  misread, "not yet serving"), all about the reader or the present,
  kept; none in the lines added elsewhere (`.logs/d8c-sweep.txt`).

### Verification

On agentpi, from the worktree root unless noted:

- `python3 scripts/check_doc_links.py .`: `checked 331 files, 0 failures`, exit 0 (`.logs/verify-links.txt`).
- `python3 scripts/check_run_use_pages.py .`: `checked 36 Run and Use pages, 0 findings`, exit 0, 35 before plus this page (`.logs/verify-runuse.txt`).
- `python3 scripts/fold_changelog.py check .`: `checked 2 fragments, 0 failures`, exit 0 (`.logs/verify-fold.txt`).
- `uv run pytest tests/census -q` from `vinga-server/`: run last, after
  this section; its outcome is in the hand-back rather than here.
- Not run: `uv run ruff check .` and the unit lane, since M1 changes no
  code and no test.

### PR review round

Reviewed 2026-10-06 by openai/gpt-6-sol, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 4m16s, at commit 7900052f ([the round](https://github.com/rafacm/vinga/pull/623#issuecomment-6009350931)).

1. **P1: other people's words to verify a simulator turn.** Section 7
   sent the coding agent to `vinga conversation list` and `show` when
   recording is on; the listing prints titles, which are utterances,
   and `show` prints what was said (`config/cli/records.py`,
   `_conversation_listing` and `_conversation_block`), the household's
   included. *Resolution:* the stream is the check. When it is not
   enough, the coding agent reads only the session the simulator
   opened, by the `session` its `session_open` carried, which
   `vinga session show` prints as metadata and no words
   (`_session_block`); the simulator's own conversation, by the
   `conversation` the same event carried, only with the person's
   consent (`5479a80c`).
2. **P1: the master key needed a package Getting Started never
   installs.** Measured with the package missing, the old form printed
   a traceback and left a bare `VINGA_MASTER_KEY=` with no newline at
   the end of the env file. *Resolution:* `security.md`'s block, the one
   form, linked from the guide, now runs the server image's own
   Python, which carries `cryptography`, into a `mktemp` file, and
   appends to the env file (made 0600 first) only on success, printing
   one sentence otherwise. Measured under `bash -x` and `zsh -x`
   (`.logs/fix2-master-key.txt`): fresh, 600 with one 44-character key;
   over a 0644 file, 600; a missing image and a missing package each
   leave the file's digest unchanged with no traceback; no key in any
   trace (`b4a1d49f`). `deploy/k8s/secret.yaml.example` L51 still names
   the host form in a comment for Kubernetes operators; it is outside
   the guide's path and left to its owner.
3. **P1: a restart before the first diff.** *Resolution:* measured on
   a Compose deployment (`.logs/fix6-compose-run.txt`): a prompt change
   someone else wrote and never applied was listed by `vinga diff`,
   and after the master key's restart, with no apply, the diff was
   empty and the change was serving. Section 4 now says a restart is
   an apply: `vinga diff` before any step that ends in one, and
   anything this conversation did not write goes to the person before
   the restart (`7bd6cbde`).
4. **P2: the checkout forms.** Measured in a scratch repository
   (`.logs/fix4-describe-forms.txt`): `git describe --always --dirty`
   prints `<tag>-<n>-g<hash>`, a bare tag at an annotated tag, or a bare
   hash with no tag reachable, each with `-dirty` after an uncommitted
   change. *Resolution:* every form is validated the same way, by
   running the same command in the checkout and requiring the server's
   revision exactly; a reachable checkout's files come from its
   working tree; an unreachable one stops at `-dirty`, and otherwise
   its hash or tag is resolved to a full commit hash through the
   remote's API before anything is read or fetched there (checked: an
   8- and a 12-character hash and a tag containing a slash return the
   full `sha`; an unpushed commit answers 422) (`15f873f2`).
5. **P2: a rerun kept an old `.env`'s mode.** Measured before the fix:
   a rerun over a 0644 `.env` left it 0644 with both secrets in it.
   *Resolution:* the block builds the file in a new `mktemp` file beside
   it, 0600 from creation, chains the secrets and the heredoc with
   `&&`, and moves it over `.env` only when all of it succeeded.
   Measured under both shells (`.logs/fix5-env-mode.txt`): fresh, 600;
   over 0644, 600 with fresh secrets; with `openssl` failing, `.env`
   unchanged, a 0600 temporary file left holding no complete secret;
   no value in any trace (`c6ef7321`).
6. **P2: the Compose commands were not run.** *Resolution:* run against
   a throwaway project, below (`83b11a21`). Running them found a trap
   the page now names: a signal to a local `docker compose exec -T`
   running `vinga events tail --follow` stops the client and leaves the
   stream following the server inside the container; the page bounds
   it with the image's `timeout`, or runs it without `-T` in a
   terminal.

The Compose run, every command with its output in
`.logs/fix6-compose-run.txt`. A scratch directory held the compose file
and the provisioning SQL fetched as Getting Started fetches them
(identical to this branch's), a `.env` written by the rewritten block,
`COMPOSE_PROJECT_NAME=vinga611`, Postgres moved to 5433 with
`VINGA_DB_PORT` (the compose file's own parameter; the server's port
is fixed at 8003, which was free), the server published on loopback
through an override file rather than on every interface, and
`VINGA_IMAGE=ghcr.io/rafacm/vinga-server:slim` (revision
`9d489f0f638e`). The development project `vinga` and its database
were not touched; the project, its network and both volumes were
removed afterwards.

| Page section | Run | Outcome |
| --- | --- | --- |
| 1 | `curl -s .../healthz`; `docker compose exec -T vinga vinga info` | the published form, `9d489f0f638e`; answered |
| 4 | the master-key block (the image's Python), the baseline `vinga diff`, `docker compose --profile server up -d --wait` | key added, `.env` 600; the diff listed the pending change; the server was recreated and served it with no apply |
| 4 | `docker compose exec vinga vinga provider secret set llm claude api_key` in a pty, a dummy typed; then the same with `-T` | without `-T`: the prompt, nothing echoed; with `-T`: no prompt, the dummy echoed, as the page warns |
| 6 | `docker compose exec -T vinga vinga check` | composes |
| 7 | `docker compose exec -T vinga vinga events tail --follow` first, then `docker compose exec -T vinga vinga simulator run <url>` | the eleven events, ending `session_closed` |
| 7 | stopping that stream | TERM to the local client left it running in the container; `timeout 5` inside it exited 124 and left nothing; Ctrl-C without `-T` left nothing |

After the fixes: the link check, the Run and Use check and the census,
the census last; their lines are in the hand-back.
