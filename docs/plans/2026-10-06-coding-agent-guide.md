# A guide a coding agent can be pointed at

Plan for M1 of [#611](https://github.com/rafacm/vinga/issues/611), the
third child of epic [#615](https://github.com/rafacm/vinga/issues/615).
M2, the readiness model, is gated on #610's walkthrough by the issue and
is not planned here; #611 stays open after this plan's PR. The companion
is `docs/plans/2026-10-06-coding-agent-guide-implementation.md`. It
builds on #609's Run door and task guides
(`docs/plans/2026-10-05-three-doors-and-task-guides.md`) and on #364's
LLM guide (`docs/plans/2026-10-06-llm-guide.md`), whose conventions and
review lessons it follows.

**Local baseline:** outside, as the issue says: documentation changes no
conversational capability.

**Cheapest alternative:** a section in `AGENTS.md` for agents that run
rather than develop vinga. It costs one heading, and it is the file a
coding agent loads automatically, which is exactly why it is the wrong
home: it would instruct every agent developing the repository as though
it were running a deployment, and it would be read at whatever commit
the agent's checkout is on, not at the commit the person's server runs.
The issue's own shape, one Run page plus a one-line pointer from
`AGENTS.md`, is the smallest that keeps the two audiences apart.

**Operator surface:** a procedure, `docs/run/with-a-coding-agent.md`,
listed first in `docs/run/README.md`, linked from the Run door, from
Getting Started's opening and from a one-line pointer in `AGENTS.md`. No
key, readiness check, upgrade action or device behavior changes.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.289; 2026-10-06.

## Where this starts from

Verified at `9d489f0f` in the
[Step 0 comment](https://github.com/rafacm/vinga/issues/611#issuecomment-6008879079)
(verdict: proceed with M1, re-scoped).

- `/healthz` answers `{"status","version","revision"}`; the revision of
  a published image equals its `sha-` tag's suffix, and a checkout
  reports `git describe --always --dirty` or `unknown`
  (`docs/run/upgrading.md`, "Which build is running"). GitHub resolves a
  12-character revision in a blob URL (checked: `blob/9d489f0f/...`
  answers 200).
- The CLI has every command M1 names: `vinga info`, `vinga reference`,
  `vinga schema`, `vinga simulator run` (check in, then one conversation
  with a packaged sentence), `vinga events tail`, `vinga conversation`
  and `vinga session`, and every noun's `--help`.
- `docs/glossary.md` has the **Coding agent** entry (#609 M2): in vinga
  "agent" always means the voice persona, and a coding agent is written
  "coding agent" wherever the bare word could be misread.
- `docs/run/README.md` is the task-guide index, and `AGENTS.md`'s
  operator-surface rule says a new procedure is "listed one line per
  guide in `docs/run/README.md`".
- Getting Started is the root README's seven steps; #610 will rewrite it
  in three stages. The `/try/` link does not exist; #613 adds it.
- #345 (closed into #615) settled the interview conventions: current
  values shown first, nothing changed that the person did not ask to
  change, and an answer that invalidates existing state names the fix
  rather than running it.

## Decisions, restated

The issue's M1, as Step 0 re-scoped it:

1. **One Run page**, `docs/run/with-a-coding-agent.md`, written to be
   read by a coding agent on a person's behalf, never named `AGENTS.md`.
2. **Which version to read**: ask the server its revision first and read
   the page, and every page it links, at that commit.
3. **The model before the interview**: `concepts.md` and `glossary.md`
   first; "agent" is the voice persona, so the coding agent calls itself
   something else when talking to the person.
4. **The order of the work**: Getting Started as it stands, then the
   task guides.
5. **Three rules**: facts from the installed CLI, never from memory of
   the docs; state from `vinga info`; secrets typed by the person.
6. **The interview**, with #345's conventions.
7. **Closing each loop**: `vinga simulator run` proves a reply comes
   back; `vinga events tail` and the records confirm and diagnose; the
   same for a board's check-in.
8. **The index is linked, not kept** (Step 0's amendment): the guide
   links `docs/run/README.md`, the one list a new feature adds a line to.
9. **It is a Run page**: #609's check, the census and the link check
   hold it.

## Smaller decisions

**D1. Reading at the revision is a URL rule the agent can follow.** The
guide gives the form
`https://github.com/rafacm/vinga/blob/<revision>/docs/run/with-a-coding-agent.md`
and the three cases: a published image's revision is a commit to read
at; a checkout's `-dirty` revision means the person's tree is ahead of
any commit, so the agent reads that tree's own files; `unknown` means a
build with no revision, and the agent says so to the person and reads
`main` with that caveat stated rather than silently.

**D2. The rules carry their failure modes.** Each of the three rules
says what goes wrong without it, in one sentence each: an agent quoting
last month's docs recommends a command the install lacks (hence the
installed CLI and `--help`); an agent inferring state from the files it
wrote misses what an apply refused (hence `vinga info` and
`vinga diff`); an agent that receives a secret has put it in its own
transcript and its provider's logs (hence the person types it). Secrets
use the two forms the LLM guide settled: a line the person writes in an
editor into a 0600 env file, then a restart; or a `secret set` command
the person runs at its own prompt. The agent hands over the command and
never the value, and never writes a secret into a command it runs.

**D3. The interview is short, ordered, and leaves state alone.** The
questions, in order: local or vendor providers (the two Getting Started
paths as they exist today), which model and voice (linking the LLM and
voice guides rather than restating them), whether to keep the agent
Getting Started creates or add the person's own. Before each change the
agent shows what is stored (`vinga show`, `vinga list`), changes only
what was asked, writes whole entities by export, edit and set (the
replace semantics #609 and #364 hit), and, when an answer conflicts
with stored state, names the command that would fix it and lets the
person decide. Configuring by voice, users and roles (#606) are not
mentioned: they do not exist.

**D3a. Diff before writing and before applying.** `vinga apply` installs
everything stored, not only what this session wrote. So the agent runs
`vinga diff` before its first write, and again immediately before
`vinga apply`; if anything is pending that it did not write, it shows
the person the list and asks before applying, rather than installing a
change nobody in this conversation asked for.

**D4. Closing the loop uses what exists.** After a configuration change:
`vinga apply`, then `vinga simulator run` against the deployment's OTA
URL (`vinga info` prints it), whose transcript and reply show the
pipeline works end to end; if it does not, `vinga events tail` while
rerunning it, reading the event names the logs-and-traces guide lists
(`provider_failed`, `llm_retry`, `reply_fallback`, `sentence_withheld`),
and the conversation record when recording is on. After a board is
added: its check-in in `vinga events tail --device <mac>` and the agent
it reaches. Every command and flag is checked against `--help` at the
implementation commit.

**D5. No future on the page.** The `/try/` link, the three-stage Getting
Started and the readiness model are not mentioned; #613, #610 and #611
M2 add their lines when they land, which their own plans' operator
surface lines will name. The D8c sweep from #609 runs over the page.

**D6. Where it is reachable from.** First line of `docs/run/README.md`
(it is how a coding agent should enter the rest of the index); a line in
`docs/README.md`'s Run door; one sentence at the start of Getting
Started for a person who would rather hand the steps to a coding agent;
and one line in `AGENTS.md`'s repository layout, saying that an agent
asked to run or configure a deployment rather than change the code
should read this page instead. That last one is the only change to
`AGENTS.md`.

**D7. Verification is execution.** Every command the page quotes is run
against a vinga-server started from the worktree (its own database), in
the order the page gives, and the record lists each with its outcome.
The secret step is run with a dummy value through the person-typed form,
confirming nothing echoes. The page is then read cold by a fresh
subagent given only its URL-at-revision rule and a running server, asked
to configure a stated deployment, and the record notes where that
subagent misread or got stuck; each such point is fixed or recorded.
This is a smoke test of the page, not #610's walkthrough, and the record
says so.

**D8. What M1 does not carry, and who carries it.** Three of the
issue's M1 items cannot be true on a Run page today, and each has an
owner that adds it when the thing exists:
- **Getting Started's three stages**: #610 rewrites Getting Started and,
  in the same change, the guide's "order of the work" line.
- **The `/try/` handoff**: #613 adds the link to `vinga info` and, in
  the same change, the guide's step that hands it to the person.
- **The index**: not deferred but resolved. `AGENTS.md` (merged with
  #609) makes `docs/run/README.md` the one list a procedure joins, one
  line per guide; a second copy in this guide would be two lists that
  must agree. The guide links it as the index it reads next, and a new
  feature still adds exactly one line, there.

A comment on #610 and on #613 names the line each must add, so the
follow-up is recorded where the work will happen, not only here. #611
stays open for M2 regardless.

**D9. Steps the person runs, and Getting Started's secrets made safe
first.** The guide sends a coding agent through Getting Started, so a
leak in a linked step is a leak in the guide. Two kinds of step are
person-run handoffs, named as such on the page: generating or entering
a secret, and writing the board's NVS, whose CSV carries the Wi-Fi
password (`README.md` L276 onward). For those the agent hands the
person the step and waits; it does not run them and never reads the
files they write. And Getting Started's secret generation, which today
expands secrets in the shell (`README.md` L115 onward, the follow-up
#609 recorded), is rewritten in this PR to the 0600 pipe form
`docs/run/security.md` documents, so the step the person runs is safe
too. The D8a-style grep runs over every page the guide links, not only
over the guide, and the record lists its hits.

## Module layout and design footprint

One page: a person's coding agent stops having to infer how to run vinga
from contributor instructions and scattered guides. No code.

## Tests

No new test: `check_run_use_pages.py` (the page is enrolled through the
`run/` directory link), the link check, and the census, which holds every
command spelling the page quotes to a registered command. D7 is the
behavioral check.

## Risks

- **The page describes a CLI that has moved.** D7 runs every command at
  the implementation commit, and rule 1 tells the agent to trust
  `--help` over the page.
- **A command on the page leaks a credential.** #609's and #364's forms
  only; the D8a grep runs over the page.
- **The cold-read subagent is not a real person's agent.** Stated in the
  record; #610's walkthrough is the real test.

## Standing lenses

No-leak: the agent never receives a secret, and no command on the page
carries one. Pin before reshaping, closed sets, honest seams: not
applicable. Inventories by tooling: the command list is executed, not
recalled. Proportion: the "Cheapest alternative" line. Falsify before
claiming: D7.

## Documentation footprint

`docs/run/with-a-coding-agent.md` (new), `docs/run/README.md`,
`docs/README.md` (Run door), the root `README.md` (one sentence at
Getting Started), `AGENTS.md` (one line), and
`changelog.d/611-coding-agent-guide.md` (`### Added`).

## Milestones

- [ ] **M1: the guide.** Decisions 1 to 9 and D1 to D7. One PR; it
  leaves #611 open for M2.

## Plan review round

Reviewed 2026-10-06 by openai/gpt-6-sol, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 3m16s, at commit ab35cb23, plan blob 458f726e.

---

1. **P1: M1 omits settled issue requirements.** Evidence: plan, D5 and decision 8 (`docs/plans/2026-10-06-coding-agent-guide.md:80`) replaces the guide's one-line-per-guide index with a link and excludes both Getting Started's three stages and the `/try/` handoff. The pasted issue requires all three in M1. The plan should sequence M1 after #610 and #613, or name explicit follow-up work and leave M1 incomplete until those requirements land.

   *Resolution:* Accepted in part. D8 names the owners: #610 adds the three-stage line and #613 the `/try/` handoff, each in the change that builds the thing, and a comment on each issue records it there. The index is resolved rather than deferred: `AGENTS.md`, merged with #609, makes `docs/run/README.md` the one list a procedure joins, so the guide links it instead of keeping a second list that must agree with the first.

2. **P1: Following Getting Started can put credentials in the coding agent's transcript.** Evidence: plan, D2 and D6 (`docs/plans/2026-10-06-coding-agent-guide.md:96`) directs the coding agent through Getting Started while promising it never receives a secret. The linked README (`README.md:115`) generates secrets through shell expansion, and its NVS recipe (`README.md:276`) places a Wi-Fi password in a command the agent might run. The plan should identify those steps as person-run handoffs and provide safe, editor-based instructions before directing a coding agent through them. A grep over the new page alone cannot catch leaks in linked steps.

   *Resolution:* Accepted. D9 marks two kinds of step as person-run handoffs (secrets, and the NVS write carrying the Wi-Fi password) that the agent hands over and never runs or reads; Getting Started's shell-expanding secret generation is rewritten in this PR to the 0600 pipe form; and the credential grep runs over every page the guide links.

3. **P1: `apply` can install changes the person never requested.** Evidence: plan, D3–D4 (`docs/plans/2026-10-06-coding-agent-guide.md:108`) promises to change only what was requested, then runs `vinga apply`; configuration.md (`docs/run/configuration.md:220`) says `apply` installs the stored snapshot and points to `vinga diff` for *everything* pending. The plan should require a diff before writing and immediately before applying. If unrelated changes are pending, the agent must show them and seek the person's decision rather than install them.

   *Resolution:* Accepted. D3a: `vinga diff` before the first write and immediately before `vinga apply`; anything pending that the agent did not write is shown to the person and applied only on their say.

4. **P2: Revision-pinned reading still executes `main` artifacts.** Evidence: plan, D1 (`docs/plans/2026-10-06-coding-agent-guide.md:87`) pins pages to the running revision, but the linked Getting Started (`README.md:94`) downloads Compose and provisioning files from `main` and installs the CLI from `main` (`README.md:152`). The plan should pin those artifacts and any workstation CLI installation to the same revision, or use the CLI shipped in the running image.

5. **P2: The version rule has no safe answer when the guide cannot be found.** Evidence: plan, D1 (`docs/plans/2026-10-06-coding-agent-guide.md:87`) sends an `unknown` build to `main` and assumes a `-dirty` build's tree is available. A running revision from before this guide lands has no page at the prescribed URL. The plan should specify how to handle an absent page or inaccessible dirty tree, and avoid presenting `main` instructions as instructions for an unidentified install.

6. **P2: The simulator step is not available on every documented path.** Evidence: plan, D4 and D7 (`docs/plans/2026-10-06-coding-agent-guide.md:120`) treats `vinga simulator run` and an OTA URL from `vinga info` as unconditional. A workstation CLI needs the `sim` extra (`docs/reference/cli.md:164`), while onboarding can be disabled (`vinga-server/src/vinga_server/config/cli/deployment.py:790`), in which case `info` prints no URL. The plan should give the installed-client prerequisite and a person-controlled path for deployments using the legacy OTA URL. Its smoke test should exercise the workstation CLI, not only the worktree environment.

7. **P2: The proposed event check can miss the event it claims to confirm.** Evidence: plan, D4 (`docs/plans/2026-10-06-coding-agent-guide.md:120`) checks a board's check-in with `vinga events tail`; logs-and-traces.md (`docs/run/logs-and-traces.md:168`) says the stream retains nothing and reconnects at the present. The plan should start the tail before the simulator or board action, or use a retained record where recording is enabled. Verification should assert the expected `ota_check` and `session_open` events, not merely run the command.

**Verdict: not ready.** The P1 scope, secret-handling, and apply behavior need amendments before implementation.
