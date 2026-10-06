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
