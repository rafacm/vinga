# Three doors, current-only concepts, and task guides

Plan for [#609](https://github.com/rafacm/vinga/issues/609), the first
child of epic [#615](https://github.com/rafacm/vinga/issues/615), whose
decisions (2026-10-05) this rests on and does not re-open. Its companion
is `docs/plans/2026-10-05-three-doors-and-task-guides-implementation.md`,
one section per milestone, appended in the same change that ticks the
milestone. It supersedes #492's two-door framing.

The work is documentation and one docs-lane check. Nothing the server
does changes; what changes is where a person running vinga, a person
talking to a device, a contributor, a coding agent and (later, #612)
vinga itself find what they need.

**Local baseline:** not applicable; documentation only, no
conversational capability joins or leaves the baseline.

**Cheapest alternative:** the issue prices the cheapest one (a new
current-only "How vinga works" page beside an untouched `concepts.md`)
and rejects it as a second description of the current model that has
to agree with the first. For M3 the cheapest alternative is leaving the
server README whole and adding an index of anchors into it from the Run
door: it moves nothing and breaks no link, and it leaves the one thing
#611 and #364 need missing, a home where a procedure is a page of its
own that an index can list one line per guide and a new feature can add
a page to rather than a section. Leaving the problem alone was priced
in Step 0 (below): every operator and every coding agent reads a
4,176-line page as the only procedure home, and #612 has no
current-only concepts page to package. No number decides between these,
so none was measured.

**Operator surface:** procedures, all existing ones, move to new homes:
one task guide per task under `docs/run/`, indexed one line per guide in
`docs/run/README.md`, which #611's coding-agent guide will point at
rather than repeat. Concepts: `concepts.md` and `glossary.md` become
current-only and gain the coding-agent glossary entry. No configuration
key, readiness check, device-facing behavior or upgrade action changes,
so no `Upgrade:` line; each milestone's changelog fragment says where
the moved procedures went.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.289; 2026-10-05.

## Where this starts from

Verified at `3073d08b`, `main`'s head, in the
[Step 0 comment](https://github.com/rafacm/vinga/issues/609#issuecomment-6003545143)
(verdict: proceed), and re-read for this plan at the same commit.

- `docs/README.md` (285 lines) opens with "Two questions place a page"
  and the seven-class authority taxonomy (L3-102); navigation ("Start
  here", L104) comes after it. L49-52 make `concepts.md` the one
  maintained map allowed to carry direction; L170-177 describe it as
  "deliberately ahead of the code"; L197-200 call the board guides the
  knowledge source of "the planned built-in help agent".
- `docs/concepts.md` (715 lines): 31 issue references to 12 issues
  (#190 x14, #439 x3, #440 x3, #599 x2, #21 x2, and #40, #83, #93,
  #96, #112, #120, #314 once each), the "deliberately ahead of the
  code" framing at L7, a status line under every section, and 12 lines
  carrying the "decided direction" marker.
- `docs/glossary.md` (608 lines): 7 issue references (#190 x2, #48,
  #54, #69, #37, #112); direction in the Handover (L289-290), Help
  agent (L293-302), Meta capability (L375-387) and Session (L509-513)
  entries.
- `vinga-server/README.md`: 4,176 lines, 22 top-level sections; the
  heading tree with line ranges is the M3 table below.
- Anchored links into the server README from outside it: 25 lines to
  14 anchors (`git grep -nE 'vinga-server/README\.md#'`, untruncated),
  16 of them in `docs/deployment.md`; one in `CHANGELOG.md` (L3386),
  which a pull request may not edit; one emitted by
  `src/vinga_server/events_docgen.py` (`LOGGING_SECTION`, L89) into
  `docs/reference/events.md`; one in `docs/architecture/product-promises.md`
  (L171, `#when-the-server-will-not-start`). One more is in
  `vinga-server/examples/README.md` (`../README.md#the-configuration-api`),
  which `scripts/check_doc_links.py` does not scan. None is in
  `docs/plans/` or `docs/features/`; the 120 plan links are to the file,
  which keeps its path.
- Prose (not link) references to README sections by name: comments in
  `deploy/k8s/deployment.yaml` (5), `docker-compose.yml` (6),
  `vinga-server/Dockerfile` (L174), `vinga-server/examples/asr-openai.yaml`
  (L20), the docstring of `tests/unit/test_session_events.py` (L5), and
  two that stay (below, D11).
- Issue references and the "decided direction" marker on the other
  candidate Run and Use pages: zero on `README.md`, `docs/deployment.md`,
  `docs/system-overview.md`, every page under `docs/devices/`,
  `vinga-server/README.md` and `vinga-esp32/README.md`. The generated
  references carry some (`server-config.md` 10 lines, `events.md` 5,
  three others 1 each), which D4 excludes.
- `scripts/check_doc_links.py` scans `README.md`, `AGENTS.md`,
  `vinga-server/README.md`, `vinga-esp32/README.md` and `docs/**`, runs
  only in `docs.yml`, and cannot see a link wrapped across two lines.
  Its tests are `vinga-server/tests/unit/test_check_doc_links.py`.
- The census classifies `docs/run/` and `docs/contributing.md` as
  `respell` (neither is under `_HISTORICAL_PATHS` or the generated
  paths in `tests/census/test_command_spellings.py`), the same class
  the README's spellings have now.

## Decisions, restated

The issue's three milestones and its constraints, as Step 0 confirmed
them:

1. **M1:** `docs/README.md` opens with **Run vinga**, **Use vinga** and
   **Develop vinga**, each a short annotated link list, and says where
   each kind of knowledge lives (#615's table). The authority taxonomy
   moves behind the navigation, intact and closed. Generated references
   are shared between doors rather than duplicated. Task guides join the
   maintained maps; no new class.
2. **M2:** every issue reference leaves `concepts.md` and `glossary.md`;
   a provenance-only reference is dropped; direction an issue or record
   owns is deleted and stays with its owner; direction nobody owns
   moves to one Develop-door page, `docs/architecture/direction.md`.
   `concepts.md` loses its "ahead of the code" framing and per-section
   status lines, and `docs/README.md` its exception for it. The
   glossary gains an entry separating vinga's agent from a coding
   agent. A docs-lane check refuses an issue reference and the
   "decided direction" marker on every Run and Use page.
3. **M3:** one directory of task guides; each guide covers one task,
   opens with what the reader will have at the end, links facts in
   `docs/reference/` and concepts in `concepts.md` rather than
   restating them, and joins the maintained maps in the commit that
   adds it. Architecture and development content moves to existing
   homes and a contributing page in the Develop door. The server README
   ends as a short page about the package that links the guides. Split
   into several PRs if one would be unreviewable; the census is
   regenerated on each.
4. **Constraints:** Run and Use pages stand alone. The hardware-table
   sync rule is untouched. No renames of `docs/reference/`, `docs/adr/`
   or `docs/plans/`; `concepts.md` and `glossary.md` keep their paths.

## Open questions, resolved

**Q1. The task-guide directory's name.** `docs/run/`. It is the Run
door's own name, and #611 already plans its guide at
`docs/run/with-a-coding-agent.md`. The directory gets an index,
`docs/run/README.md`, one line per guide, grouped by what the reader is
doing (deploying, configuring, observing). #611's issue body puts "the
task-guide index, one line per guide" in its coding-agent guide; this
plan's index exists first, and the M3a implementation-doc section
records the recommendation that #611 link it rather than keep a second
list (two lists that must agree are one list with a bug pending). That
is a note for #611's plan, not an edit to #611.

**Q2. How M3 splits.** Four PRs, M3a to M3d, each moving whole README
sections (table below) and each leaving the README coherent: its "On
this page" list and every remaining cross-reference point at wherever
the moved sections now live. Measured sizes of what each moves: M3a 959
README lines, M3b 1,115, M3c 883, M3d 1,138. One PR moving 4,000 lines
is a diff of about 8,000; a reviewer reading a 2,000-line diff already
risks the empty review `external-review` warns about. Four is the
fewest that keeps each move near a thousand lines. Each PR is a valid
release: the README, the guides and every inbound link agree after
each merge.

**Q3. Which pages are Run and Use pages, for the check.** Derived, not
listed: the check reads `docs/README.md`, takes the **Run vinga** and
**Use vinga** sections, and holds every Markdown page they link to the
rule (a directory link brings every `.md` under it). Adding a guide to
the Run door therefore puts it under the check with no second list to
update, and a door page cannot silently escape it. See D3 and D4.

**Q4. Where the direction page sits in the taxonomy.** Research and
field notes. Each entry is a dated record of something decided, where
it was recorded and when, which is the class's definition ("what was
read, measured, or observed, carrying the date and provenance"); it
makes no claim about current behavior, so it cannot drift from
`concepts.md`. An entry leaves the page in the commit that opens an
issue or a record for it, which says so in the entry's place. It is
listed in the Develop door only.

**Q5. The contributing page's home.** `docs/contributing.md`, in the
Develop door, maintained-maps class: the Stack and Development sections
(L1363-1529), which describe how to set up and test a checkout as it is
now. `AGENTS.md` keeps its own Commands section (agent instructions are
the guidelines class and are out of scope here) and gains a link to the
page.

## Smaller decisions

**D1. The Run, Use and Develop sections link; they do not describe at
length.** One line of annotation per entry, as the issue asks. The
current "Start here", "Reference", "Board guides", "Architecture",
"Research notes" and "The record" sections fold into the doors and a
shared **Reference** section; their longer annotations are trimmed to a
line where the target page already says the rest on its first screen.

**D2. The "Where knowledge lives" table lists what exists.** It is #615's
table restated for the tree as it is: Facts (generated references,
`vinga schema`, `vinga reference`, `--help`), Concepts (`concepts.md`,
`glossary.md`), Device behavior (`docs/devices/`), State (`vinga info`
today; the readiness model is #611), Procedures (the Run door's guides),
Direction (its issue or record; `architecture/direction.md` once M2 adds
it). The column for what reaches vinga is omitted until #612 builds
that. `docs/README.md` is an index page and may cite issues; only Run
and Use pages may not.

**D3. The check is a script beside the link checker, run in `docs.yml`.**
`scripts/check_run_use_pages.py`, stdlib only, invoked as
`python3 scripts/check_run_use_pages.py .` in the step after "Internal
links and anchors". It reuses the link checker's `LINK_RE` and fence
handling by importing them rather than copying them, since the two must
agree on what a link is. Its unit tests sit beside the link checker's,
in `vinga-server/tests/unit/test_check_run_use_pages.py`, and run in the
server workflow's unit lane. Every Run and Use page today lies outside
the server workflow's paths, so a change to one runs `docs.yml`; until
M3d moves it to the Develop door, `vinga-server/README.md` is the
exception, and a server-only PR could add an issue reference to it
unchecked for that window. That is stated in the script's docstring, as
the link checker states its limits, rather than closed with a second
workflow step: the README has none today and every PR in this plan that
edits it also edits `docs/`.

**D4. What the check refuses, and on which pages.**

- Pages: every `.md` file linked from the Run and Use sections of
  `docs/README.md`, after stripping anchors, resolving directories to
  their `.md` files, deduplicating, and excluding `docs/reference/`.
  The generated references are the facts class; their issue references
  come from `Field(description=)` text, and changing them is a
  generator change outside this issue. Same-page anchors and non-`.md`
  targets (`deploy/postgres-init.sql`, `config.example.yaml`) are
  skipped.
- Refused, on every line including fenced code: an issue or pull
  request reference `#<digits>` not preceded by a word character, `&`
  or `/` (so `#binding`, `&#8217;` and `page.md#1` pass);
  `<owner>/<repo>#<digits>`; and a `github.com/<owner>/<repo>/issues/`
  or `/pull/` URL; and the phrase "decided direction", case-insensitive.
- Refused: a `docs/README.md` without a `## Run vinga` or `## Use vinga`
  heading, or with either section linking no page. Fail closed, so a
  renamed heading cannot switch the check off.
- Output: one line per finding naming the file, the line and the kind
  (`issue-reference`, `direction-marker`, `door-missing`), and nothing
  of the line itself, on the link checker's reasoning. Exit 1 on any
  finding, 2 on a bad invocation.
- Not refused: 🚧 marks. They state a present absence, which is the
  root README's and the board guides' standing convention, and are
  honest on a current-only page. The two 🚧 sentences in the
  Touch-LCD-1.54 guide that describe vinga's planned firmware build
  (L57, L129) are marked, so they stay; #612, which packages these
  pages, is where reading them aloud is decided.

**D5. What `concepts.md` keeps, deletes and moves.** The inventory, by
section, which the implementer re-verifies against each owner issue's
body at implementation time (an owner that has moved changes the row,
not the rule):

| Passage | Disposition |
| --- | --- |
| Intro L5-37: "deliberately ahead of the code", the "owning issue holds a decided direction" bullet | Rewritten current-only; the outrank list stays without that bullet |
| Every "**Implemented today...**" status line | Deleted |
| Model in one paragraph L83-86: users arrive later | Deleted (owned: #606) |
| Device L121: "(issue #40, implemented)" | Reference dropped |
| Device L215: durable record of observed facts | Deleted (owned: #96) |
| Device L216-220: board catalog with "a machine-readable sibling serves the server" | Rewritten to what exists, the per-board guides; the catalog is #96's (no catalog exists under `src/`) |
| Device L222-226: "The help agent reads all three" | Help-agent sentence deleted (owned: #612); the observation-not-control point kept |
| Binding L267-270: changing a device's default by voice | Moved to `direction.md` (#612 and #615 decision 5 both say configuration by voice waits for #606; neither owns it) |
| Conversation and session L274-279 status, every "(issue #190)", "(issue #599)" | References dropped, facts kept |
| L326-334: recording rule for meta turns | Moved |
| Cost bullet L361-375: per-conversation cost, the tokens-then-price-map shape, "accounting awaits users" | Current facts kept (`record.metrics_tokens_daily`, `vinga metric show tokens`); the rest moved |
| L427-430: carrying context deliberately across a switch | Moved |
| Wake word L486-489: unchecked trigger audio "(issue #112)" | Reference dropped; "has not been checked on the wire" kept, a current fact |
| Wake word L499-500: "The help agent knows..." | Deleted (owned: #612) |
| Memory L527 "(issue #314)" | Reference dropped |
| Memory L592-606: (user, agent) key, shared user profile | Deleted (owned: #606, whose body names both) |
| Meta capabilities L616-647 | Rewritten to the three that exist and the agent-scoped search as current fact; anchor `#meta-capabilities` kept (the glossary links it); cross-agent search and the general "more meta capabilities" framing moved |
| The help agent L649-677 | Section deleted (owned: #612); the glossary link to it removed in the same commit |
| Before users arrive L679-701 | Renamed **Who the user is**, current limitation kept; users, budgets, voiceprint deleted (owned: #606, #608) except budget enforcement, which #606 lists out of scope, moved |
| L703-715: users do not bring a session (2026-09-23) | Moved; #606's body does not cover it |

`concepts.md`'s **Date** line becomes the M2 date. Its "On this page"
list follows the sections.

**D6. What `glossary.md` changes.** References dropped from Conversation
(#190), Echo leakage (#48), Prompt echo (#54, #69), Sentence lookahead
(#37) and Wake word (#112, "unchecked" kept). Handover loses its
direction sentence. The **Help agent** entry is deleted (owned: #612;
#612 adds its own entry when vinga's agent ships). Meta capability
keeps the three tools that exist and loses "the cost question is
planned" and the recording-rule sentence, which states the unowned
direction above as if it were built. Session keeps the "device session"
writing convention and loses "will not gain one when users arrive",
which moves with the 2026-09-23 note. A new **Coding agent** entry says
that in vinga "agent" always means a voice persona, that a coding agent
(Claude Code, Codex and the like) is a program a person runs to work on
a deployment or on the code, and that the two never share the word
unqualified; the **Agent** entry links it.

**D7. `direction.md`'s shape.** A short intro (what the page is, that it
holds no current facts, that an entry leaves when an issue or record
takes it), then one H2 per item: the direction in the words it was
recorded in, where and when it was recorded (`concepts.md`, 2026-08-21,
or 2026-09-23), and which open issue it waits on where one does
(#606, #612). Items, from D5: changing a device's default by voice;
the recording rule for meta turns; carrying context deliberately across
a switch; per-conversation cost and its tokens-then-price-map shape;
cross-agent conversation search; budget enforcement; users do not bring
a session of their own. Seven, against the issue's "and the rest the
plan inventories".

**D8. A guide's shape.** H1 is the task ("Running vinga in a
container"); the first paragraph says what the reader will have at the
end; then the moved sections, with headings demoted one level where
needed. Links into `docs/reference/` replace restated facts in one
place only, the three provider option tables (OpenAI transcription,
ElevenLabs, OpenAI speech): each becomes a link to its reference
section, and a row whose content the reference lacks (a measured
finding such as "only `gpt-transcribe` was measured to accept
`languages`") stays as a sentence. Every other paragraph moves
verbatim, apart from its links and its prose pointers ("see Security
below"), which are rewritten to wherever the target now lives. Rewriting
the moved prose further is out of scope: each paragraph has already
survived review once, and #364 is the pilot for the guide format.

**D9. The server README's end state (M3d).** The title and the opening
(what the package is, its two endpoints, the four-stage vocabulary
table, what it exposes), Goals, a "Running and configuring it" pointer
to `docs/run/README.md`, a "Developing it" pointer to
`docs/contributing.md`, and Status. It moves from the Run door to the
Develop door in the same commit. No compatibility anchors: a former
anchor 404s to the top of a page whose first screen links every guide.

**D10. Inbound links and prose pointers move in the PR that moves their
target.** Every link and every by-name mention in the inventory above
is rewritten in the same PR as the section it names, so no merged state
has a link pointing at a removed anchor. Two exceptions, by mechanism:
`events_docgen.py`'s `LOGGING_SECTION` changes in M3d and
`docs/reference/events.md` is regenerated, never hand-edited; and
`CHANGELOG.md` L3386 is retargeted by a documentation commit straight
to `main` after M3a merges, since a pull request may not edit it.

**D11. Two by-name mentions stay.** The column comment "the event
vocabulary the README's table defines" in
`conversations/schema.py` (L774) and in migration
`1002_conversation_threads.py` (L214). The migration is history; the
schema comment is a schema fact a migration carries, and changing a
column comment to follow a documentation move would buy a migration
for one noun. Both are recorded as known residue in the M3d
implementation-doc section. The `memory/migrations/versions/2002_memory_scopes.py`
docstring is history and stays as well.

**D12. Changelog.** One fragment per milestone,
`changelog.d/609-<slug>.md`, under `### Changed`, saying in an
operator's words where the moved content now lives. No `Upgrade:` line:
nothing is asked of an operator.

## The M3 table

Every top-level section of `vinga-server/README.md` at `3073d08b`, its
lines, its destination, and the PR that moves it. Destination paths are
relative to the repository root.

| README section | Lines | Destination | PR |
| --- | --- | --- | --- |
| Title and opening | 1-42 | stays (D9) | M3d trims |
| On this page | 43-62 | stays, rewritten by each PR | each |
| Goals | 63-81 | stays (D9) | |
| Providers (the table, local vs vendor, licensing) | 82-127 | `docs/run/providers.md` | M3b |
| Choosing how it hears; OpenAI transcription | 128-390 | `docs/run/speech-recognition.md` | M3b |
| Choosing a voice; ElevenLabs; OpenAI | 391-620 | `docs/run/voices.md` | M3b |
| Tools: MCP servers, transports, grants, guidance, device tools, builtins, tool failures, what a tool answers | 621-851, 1013-1030 | `docs/run/tools-and-mcp.md` | M3b |
| Tools: `remember` to "Whether an agent remembers at all", the ledger, `vinga memory` | 852-1012 | `docs/run/memory.md` | M3b |
| What the model is actually sent | 1031-1144 | `docs/run/agents-and-prompts.md` | M3b |
| What the MCP servers are doing | 1145-1196 | `docs/run/tools-and-mcp.md` | M3b |
| Applying a change without a restart | 1197-1362 | `docs/run/configuration.md` | M3c |
| Stack; Development; the local and smoke lanes | 1363-1529 | `docs/contributing.md` | M3d |
| Configuration (two halves, CLI, import, when a change applies, env layering) | 1530-1703 | `docs/run/configuration.md` | M3c |
| Configuration: the database keys and the unreachable-database refusal | 1704-1743 | `docs/run/database.md` | M3c |
| The configuration API | 1745-1981 | `docs/run/configuration-api.md` | M3c |
| Secrets | 1982-2021 | `docs/run/security.md` | M3c |
| Security (hosts reached, device auth, OTA path, exposure, data boundary, telemetry reach) | 2022-2219 | `docs/run/security.md` | M3c |
| Security: upgrading from `server.local_only` | 2220-2226 | `docs/run/upgrading.md` | M3c |
| Security: memory is stored on the host and read out to the model | 2228-2245 | `docs/run/memory.md` | M3c |
| Listening and barge-in; Masking reply latency; When a reply fails; When a model writes a tool call into its speech | 2247-2482 | `docs/run/listening-and-replies.md` | M3d |
| Limits (bounds, drain, probes, the first-token watchdog) | 2483-2592 | `docs/run/limits-and-probes.md` | M3a |
| Logging; Watching a deployment; Exporting traces | 2593-2863 | `docs/run/logs-and-traces.md` | M3d |
| Capturing a session | 2864-2946 | `docs/run/capturing-a-session.md` | M3d |
| What a conversation cost | 2947-3107 | `docs/run/conversation-cost.md` | M3d |
| The conversation store | 3108-3327 | `docs/run/conversation-store.md` | M3d |
| Which build is running | 3328-3371 | `docs/run/upgrading.md` | M3a |
| Running in a container | 3372-3479 | `docs/run/running-in-a-container.md` | M3a |
| The configuration database in a deployment: provisioning, master key, rotation, backups, restore, reading as `vinga_ro`, "an edit is stored" | 3480-3528, 3576-3677 | `docs/run/database.md` | M3a |
| The same: this release's and the previous release's upgrade notes | 3529-3575 | `docs/run/upgrading.md`, or a link to the `CHANGELOG.md` entry that already says it (D13) | M3a |
| The configuration API in a deployment: set the secret before rolling | 3684-3693 | `docs/run/upgrading.md` | M3a |
| The same: `/api/` at the edge; loopback or TLS | 3695-3727 | `docs/run/exposing-a-deployment.md` | M3a |
| When the server will not start | 3729-3832 | `docs/run/recovering-a-deployment.md` | M3a |
| Choosing an image | 3833-3905 | `docs/run/running-in-a-container.md` | M3a |
| Onboarding a device | 3906-4073 | `docs/run/onboarding-a-device.md` | M3a |
| Transports | 4074-4090 | `docs/system-overview.md`, a short section | M3a |
| Ports and topology; Behind a reverse proxy | 4091-4165 | `docs/run/exposing-a-deployment.md` | M3a |
| Status | 4166-4176 | stays (D9) | |

Line ranges are at `3073d08b` and move as earlier PRs remove sections;
each PR re-derives its ranges by heading, never by these numbers.

**D13. Per-release upgrade notes.** L3529-3575 describe what two past
releases asked of an operator (the `memory` schema's rerun, stop before
start for the scopes migration, the memory files left on disk, the
`conversations` to `record` schema rename). Epic decision 8 puts upgrade
detail in the changelog. Each note is looked up in `CHANGELOG.md`: one
the changelog already carries becomes a link to that entry from
`upgrading.md`'s "Past releases" list; one it does not carry moves to
`upgrading.md` verbatim. The standing rule (rerun
`deploy/postgres-init.sql`, then boot) is a procedure and moves whole.

**D14. Where `deployment.md` points.** Its contract table and its 16
anchored links retarget to the guides, and its sentence "The server
README stays the authority for the contract itself" names the guides.
Its own lane-specific sections ("Upgrading", "Choosing a tag") keep the
lane steps and link the guide for the standing facts, the pattern the
page already follows with the README; any paragraph the two would then
both hold is kept in the guide and linked from `deployment.md`.

## Module layout and design footprint

Pages are this plan's modules; the reader is the caller.

- **M1** deepens `docs/README.md`: a reader stops having to read the
  authority taxonomy to find a page for their task. No new page.
- **M2** deepens `concepts.md` and `glossary.md` (a reader, a coding
  agent and later vinga stop having to tell a fact from a plan) and adds
  two modules. `docs/architecture/direction.md`: a contributor stops
  having to know which pages carry unowned direction, because one page
  does. `scripts/check_run_use_pages.py`: a page author stops having to
  know which pages the current-only rule covers, because the door lists
  in `docs/README.md` are the list.
- **M3a to M3d** add `docs/run/` (an index and twenty-one guides) and
  `docs/contributing.md`: an operator or a coding agent stops having to
  search a 4,176-line page for one procedure, and a new feature's how-to
  gets a page an index lists rather than another README section. The
  README becomes the package's own page. No seam, no code module.

## Tests

- **M2's check:** `test_check_run_use_pages.py`, written before the
  script and watched failing, each case building a temporary tree with
  its own `docs/README.md`: a clean tree passes; `#123` on a Run page,
  on a Use page and inside a fenced block each fail with file, line and
  kind; the line's text is absent from the output (a planted
  credential-shaped token on the offending line, asserted absent); the
  `owner/repo#9` and both GitHub URL forms fail; "Decided Direction"
  fails; a page linked only from the Develop door passes with `#1` on
  it; a directory link brings its pages in; a `reference/` link is
  excluded; `#binding`, `&#8217;` and `page.md#1` pass; a missing Run or
  Use heading, and a door section linking no page, each fail closed.
  Straight-line logic, so one run per mutation: remove each refusal
  pattern in turn and name the test that turns red, and drop the
  fail-closed guard and name its test. A mutation that survives is a
  finding about the tests.
- **The real tree:** the script exits 0 on the M2 tree, and exits 1
  with the expected kinds when run against `3073d08b`'s `concepts.md`
  under the M2 `docs/README.md` (the driver reaches the condition: the
  pre-cleanup page has 31 references and 12 marker lines). That run is
  quoted in the M2 PR.
- **Every PR:** `python3 scripts/check_doc_links.py .`,
  `python3 scripts/check_run_use_pages.py .` (from M2 on), and
  `uv run pytest tests/census -q` last, after the final prose edit, from
  `vinga-server/`. M2 and M3d change code (`scripts/`, `tests/unit/`,
  `events_docgen.py`), so they also run `uv run ruff check .` and the
  unit lane; M3d regenerates `events.md` through its generator and runs
  the drift test that guards it. No milestone needs the integration
  lane, and each PR says so rather than claiming it.
- **M3's coverage check, per PR.** A move is proven by showing every
  paragraph left the README for exactly one place, not by reading
  4,000 lines. Each M3 PR runs this from its worktree, writes the
  output under `.logs/`, and quotes the summary and the full list of
  non-verbatim paragraphs in the PR body:

  ```python
  # coverage.py OLD_README NEW_README DEST... : every paragraph of
  # OLD_README must appear, whitespace-normalized, in NEW_README or a
  # DEST. Prints the totals and each paragraph that does not, by its
  # first 100 characters.
  import sys

  def paragraphs(text):
      out, buf, fence = [], [], False
      for line in text.splitlines():
          if line.lstrip().startswith(("```", "~~~")):
              fence = not fence
          if not line.strip() and not fence:
              if buf:
                  out.append(" ".join(" ".join(buf).split()))
                  buf = []
          else:
              buf.append(line)
      if buf:
          out.append(" ".join(" ".join(buf).split()))
      return out

  old = paragraphs(open(sys.argv[1], encoding="utf-8").read())
  pool = "\n".join(
      " ".join(open(p, encoding="utf-8").read().split()) for p in sys.argv[2:]
  )
  missing = [p for p in old if p not in pool]
  print(f"{len(old)} paragraphs, {len(old) - len(missing)} verbatim, {len(missing)} not")
  for p in missing:
      print("-", p[:100])
  ```

  `OLD_README` is `git show <base>:vinga-server/README.md`. Every
  non-verbatim paragraph is one the PR edited on purpose (a rewritten
  link, a replaced option table, a demoted heading, a new intro), and
  the PR body says which, so the reviewer reads those and not the
  verbatim moves.

## Risks

- **Content lost in a move.** The coverage check above, per PR, with the
  non-verbatim list in the PR body.
- **A link or anchor broken by a move.** The link checker runs in
  `docs.yml`, which every M3 PR triggers because each touches `docs/`.
  Two holes it has, closed by hand in each PR with untruncated `git grep`
  output in `.logs/`: a link wrapped across two lines (keep every link
  on one line), and files it does not scan (`vinga-server/examples/README.md`,
  YAML and Dockerfile comments, Python docstrings).
- **Prose pointers that break silently.** "See Security below" is not a
  link, so no checker sees it land on another page. Each PR greps the
  moved text for `below`, `above` and `this page` and rewrites each hit
  that crossed a page boundary.
- **Stacked rebases on the README and `docs/README.md`.** Every PR edits
  both, so the milestones stack strictly (M1, M2, M3a, M3b, M3c, M3d).
  Each removes distinct README ranges, so a rebase conflict is in the
  "On this page" list or the door lists, resolved by hand and checked by
  the link checker. The census manifest is regenerated on the rebased
  tree, never merged.
- **The census goes stale on a move.** A spelling that changes files
  keeps its class (`respell` both sides), so the manifest moves only if
  a spelling's distinct set moves; the census runs last in every PR.
- **The check refuses something legitimate later.** Its findings name a
  file and line; the fix is in the page (a Run page that needs to say
  an issue exists links the Develop door instead). A real false
  positive is a pattern bug, fixed with a test.
- **M3a touches server-workflow paths** (`deploy/k8s/deployment.yaml`,
  `docker-compose.yml`, `vinga-server/Dockerfile` comments), so it runs
  the full server workflow, image job included. That is the honest cost
  of not leaving stale pointers; it is minutes of CI, not a risk to
  `main`.

## Standing lenses

- **No-leak:** the check's output names a file, a line and a kind and
  never a byte of the line, pinned by a sentinel test. Nothing else in
  the plan emits anything.
- **Pin before reshaping:** the coverage check is this plan's pin for a
  behavior-preserving move of prose: the old text is the pin, and the
  non-verbatim list is the whole of what changed.
- **Closed sets:** the check's kinds are `issue-reference`,
  `direction-marker`, `door-missing`, each with its decision site in
  the script and a test.
- **Honest seams:** none added.
- **Inventories by tooling:** every count in this plan came from an
  untruncated `grep -c`, `git grep` or `awk` over the tree at
  `3073d08b`; each PR re-derives its own with the same commands and
  never with `head`.
- **Proportion:** the "Cheapest alternative" line above; the check is
  one stdlib script against the cheapest alternative of a review rule,
  which is what let `concepts.md` slip past the written landing-page
  rule in the first place.
- **Falsify before claiming:** the check's tests are written first and
  watched failing; the real-tree run against the pre-cleanup
  `concepts.md` proves the driver reaches the condition.

## Documentation footprint

- **M1:** `docs/README.md`. `docs/architecture/README.md`'s pointer to
  "what each class of page may claim" still resolves (the taxonomy keeps
  its `#authority` anchor). `AGENTS.md`'s description of `docs/README.md`
  ("the documentation index, and the authority taxonomy") stays true.
- **M2:** `docs/concepts.md`, `docs/glossary.md`,
  `docs/architecture/direction.md` (new), `docs/README.md` (the
  concepts exception and description, the help-agent sentence in the
  board-guides annotation, the direction page in the Develop door and
  the research-notes class), `docs/architecture/README.md` (a line for
  the direction page), `.github/workflows/docs.yml` (the step).
- **M3a:** `docs/run/README.md` and its seven guides, `docs/system-overview.md`
  (Transports), the server README, `docs/README.md` (the Run door and
  the maintained-maps class name `docs/run/`), `docs/deployment.md`,
  `docs/concepts.md` and `docs/xiaozhi-notes.md` (the onboarding link),
  `docs/architecture/product-promises.md` (the recovery link), the root
  `README.md` (two links: Choosing an image, and the deployment
  pointer), `deploy/k8s/deployment.yaml`, `docker-compose.yml`,
  `vinga-server/Dockerfile`, and `AGENTS.md`'s operator-surface
  sentence, which says task guides do not exist yet. Then the
  `CHANGELOG.md` retarget straight to `main` (D10).
- **M3b:** the six guides, the server README, the `docs/run/` index,
  the root `README.md` (the `#providers` link), and
  `vinga-server/examples/asr-openai.yaml`.
- **M3c:** the three guides plus additions to `database.md`,
  `upgrading.md` and `memory.md`, the server README, the index,
  `vinga-server/examples/README.md`, and the root `README.md`
  (`#applying-a-change-without-a-restart`).
- **M3d:** the five guides, `docs/contributing.md`, the server README's
  end state, the index, `docs/README.md` (the README moves to Develop,
  the contributing page joins it and the maintained-maps class),
  `docs/glossary.md` (`#listening-and-barge-in`), `AGENTS.md` (a link
  to the contributing page), `events_docgen.py` and the regenerated
  `docs/reference/events.md`, `tests/unit/test_session_events.py`'s
  docstring, and the D11 residue recorded.

## Milestones

- [ ] **M1: three doors.** `docs/README.md` opens with Run vinga, Use
  vinga and Develop vinga (D1), then a shared Reference section, then
  "Where knowledge lives" (D2), then the authority taxonomy unchanged
  in substance and still closed, then Conventions. The server README is
  in the Run door until M3d. One PR, docs only.
- [ ] **M2: concepts and glossary describe what runs today.** D5, D6,
  D7, the coding-agent entry, `direction.md`, `docs/README.md`'s
  concepts exception removed, and the check (D3, D4) with its tests and
  its `docs.yml` step. Commits: the check's tests, the check, the step;
  then `direction.md`; then `concepts.md` section by section; then the
  glossary; then the index.
- [ ] **M3a: the task-guide directory and the deployment guides.**
  `docs/run/README.md`, `running-in-a-container.md`, `database.md`,
  `upgrading.md` (D13), `exposing-a-deployment.md`,
  `recovering-a-deployment.md`, `onboarding-a-device.md`,
  `limits-and-probes.md`, Transports into `system-overview.md`, every
  inbound link and pointer for those sections (D10, D14), the
  coverage check.
- [ ] **M3b: providers, tools, memory and prompts.** `providers.md`,
  `speech-recognition.md`, `voices.md` (the three option tables per D8),
  `tools-and-mcp.md`, `memory.md`, `agents-and-prompts.md`.
- [ ] **M3c: configuration and security.** `configuration.md`,
  `configuration-api.md`, `security.md`, and the M3c rows' additions to
  `database.md`, `upgrading.md` and `memory.md`.
- [ ] **M3d: conversation behavior, observability, and the README's end
  state.** `listening-and-replies.md`, `logs-and-traces.md`,
  `capturing-a-session.md`, `conversation-cost.md`,
  `conversation-store.md`, `docs/contributing.md`, the README per D9,
  `events_docgen.py` and the regenerated `events.md`.
