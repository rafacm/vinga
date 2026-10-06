# Three doors, current-only concepts, and task guides: implementation

Companion to
[`2026-10-05-three-doors-and-task-guides.md`](2026-10-05-three-doors-and-task-guides.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: three doors

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.289; 2026-10-06.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| D1: the three doors and the shared Reference section; the old Start here, Reference, Board guides, Architecture (with Diagrams), Research notes and The record sections folded into them | `docs/README.md` | `Open the docs index with three doors` |
| D2: "Where knowledge lives", #615's table for the tree as it is | `docs/README.md` | the same |
| The taxonomy behind the navigation, intact and closed, `## Authority` and its anchor kept | `docs/README.md` | the same |
| The architecture index's "what each class may claim" link lands on the taxonomy | `docs/architecture/README.md` | `Point the architecture index at the taxonomy` |
| D12: the fragment | `changelog.d/609-three-doors-index.md` | `Add the changelog fragment for the three doors` |
| The census: the table quotes `vinga schema` and `vinga reference` bare, two new `respell` lines | `vinga-server/tests/census/command-spellings.txt`, regenerated | `Regenerate the command-spellings census` |

The page's order is the plan's: Run vinga, Use vinga, Develop vinga,
Reference, Where knowledge lives, Authority, Conventions. The door
headings are exactly `## Run vinga`, `## Use vinga` and
`## Develop vinga`, which is what M2's check finds the doors by.

Door membership: the Run door links Getting Started
(`../README.md#getting-started`), `deployment.md` (and `../deploy/`
inside its annotation), `deploy/postgres-init.sql`, the server README,
`system-overview.md`, `concepts.md`, `glossary.md` and the Reference
section. The Use door links the `devices/` directory, the common page,
each of the three board guides, `devices/flashing.md`, `concepts.md`
and `glossary.md`. The Develop door links `AGENTS.md`,
`architecture/README.md`, the diagrams index, `system-overview.md`,
the firmware README, the four research notes, `adr/`, `plans/` (with
the first plan and its implementation notes), `features/`, the
changelog and the Reference section.

### Deviations from the plan

- **The audience paragraph moved under the Authority heading and now
  names the doors.** It used to sit above the taxonomy and point at
  "the reference section below" and at "the research notes, the
  architecture pages, and the record", two of which are no longer
  sections. It now points at the Run and Use doors, the reference
  section above, and the Develop door's architecture pages, research
  notes and record. Every other line of the taxonomy, from "Seven
  classes" to the index-pages paragraph, is byte-identical to the old
  page (`diff` of the two extracts, empty).
- **The `docs/architecture/README.md` link gained `#authority`.** The
  plan's footprint says the pointer "still resolves"; it did, but a
  bare `../README.md` would now land on the doors rather than the
  taxonomy the sentence names, so the link names the anchor.
- **The concepts annotation keeps its direction wording once.** The
  Run door's `concepts.md` entry is the old Reference-section
  annotation moved verbatim, including "Deliberately ahead of the
  code" and its two decided-direction clauses, for M2 to rewrite with
  the taxonomy's exception paragraph. The Use door's entry is a new
  one-line annotation without them, so the wording M2 rewrites has one
  copy on the page rather than two. The board guides' help-agent
  sentence moved verbatim into the Use door's `devices/` entry; the
  rest of the old Board guides paragraph is trimmed per D1, since
  `devices/README.md` says it on its first screen.
- **The "Where knowledge lives" table keeps the coding-agent column.**
  D2 omits only the column for what reaches vinga. Where #615's table
  names a home that does not exist yet, the row says what serves today
  and names the issue that builds the rest: the browser client's guide
  (#613), the readiness model (#611), one guide per task (#609), the
  coding-agent guide's index (#611), and the Develop-door page for
  unowned direction (#609). "Read before the interview" is not
  carried, since no interview exists; the row says the coding agent
  reads the same pages.

### Discoveries

- **D4's README-as-index enrollment, applied to the doors the plan
  fixes, enrolls pages full of issue references.** D4 enrolls the
  `.md` pages a door-linked `README.md` links, one level deep. Three
  door links are READMEs the plan requires: the root README (Getting
  Started), the server README (Run door until M3d) and
  `devices/README.md` (Use door, also reached through the `devices/`
  directory link). Simulated against this tree with the link checker's
  `LINK_RE` (`.logs/m1-door-simulation.txt` in the implementer's
  worktree), they enroll `CHANGELOG.md` (478 lines with an issue
  reference), `docs/README.md` itself (the "Where knowledge lives"
  table, which D2 allows to cite issues, and the concepts exception),
  `architecture/guidelines.md`, `architecture/product-promises.md`, an
  ADR, and `xiaozhi-notes.md` (5 lines; `devices/README.md` links it,
  so the Use door alone enrolls it). M2's check as D4 specifies it
  would fail on these whatever `concepts.md` and `glossary.md` say.
  M1 cannot avoid it, since the door links are the plan's; M2's plan
  owner has to narrow the rule before the check is written (for
  example, enrolling an index's pages only for an index that is a
  door's own guide index, such as `docs/run/README.md`, or only pages
  under the index's own directory).
- **The `../deploy/` directory link inside the Run door enrolls
  `deploy/telemetry/README.md`.** It is clean today (no issue
  reference, no marker), so it passes; it is under the check from M2
  on.
- **Pages the doors link directly are clean apart from the two M2
  cleans.** The root README, `deployment.md`, `system-overview.md`,
  the server README and every page under `docs/devices/` carry no
  issue reference, no `owner/repo#N`, no GitHub issue or pull URL and
  no "decided direction"; `concepts.md` has 29 lines with an issue
  reference and 12 with the marker, `glossary.md` 6 and 0
  (`.logs/m1-run-use-pages-refs.txt`).

### Inventories

Untruncated, kept under `.logs/` in the implementer's worktree.

- Link targets of `docs/README.md`, read with the link checker's own
  `LINK_RE`: 40 before, 47 after. The after-set contains the
  before-set except `#board-guides`, the same-page anchor to the Board
  guides section, which no longer exists; its content is the Use
  door. Added: `#authority`, `#reference`, `#where-knowledge-lives`,
  `../README.md#getting-started`, `devices/` and the three board
  guides (`.logs/m1-links-compare.txt`).
- Inbound links to any of the old index's section anchors
  (`#authority`, `#start-here`, `#reference`, `#board-guides`,
  `#architecture`, `#diagrams`, `#research-notes`, `#the-record`,
  `#conventions`), by `git grep` over the tree: two hits, the old
  index's own `#board-guides` link and the plan's mention of
  `#authority`. No other page linked a section of the index.

### Verification

On agentpi, from the worktree root:

- `python3 scripts/check_doc_links.py .`: 298 files, 0 failures.
- `python3 scripts/fold_changelog.py check .`: 1 fragment, 0 failures.
- `uv run pytest tests/census -q` from `vinga-server/`: run last,
  after this section; its outcome is in the hand-back rather than
  here.

M1 touches no code, so neither the unit nor the integration lane was
run.

### PR review round

Reviewed 2026-10-05 by openai/gpt-5.6-terra, thinking high via codex
CLI 0.160.0, read-only sandbox, runtime 2m41s, at commit c59e7536
([the round](https://github.com/rafacm/vinga/pull/616#issuecomment-6004743078)).

No findings; verdict "mergeable as is". The reviewer was told to read
the plan only for what M1 implements and the two index pages in full.
No fix round.

## M2: concepts and glossary describe what runs today

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.289; 2026-10-06.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| The check's tests, written first and watched failing (26 of 27 red; the bad-invocation case passes with the script absent too, since a missing script also exits 2 with one stderr line) | `vinga-server/tests/unit/test_check_run_use_pages.py` | `Test the Run and Use page check before writing it` |
| D3, D4 (as amended after M1): the check | `scripts/check_run_use_pages.py` | `Check Run and Use pages for issues and direction` |
| D3: the two workflow steps | `.github/workflows/docs.yml` (after "Internal links and anchors"), `.github/workflows/vinga-server.yml` (`unit` job, after Lint, `working-directory: .`) | `Run the Run and Use page check in both workflows` |
| D7, Q4: the direction page, its line in the Develop door, its place in the dated-execution-records class, and its line in the architecture index | `docs/architecture/direction.md`, `docs/README.md`, `docs/architecture/README.md` | `Add the direction page as a dated record` |
| D5, section by section | `docs/concepts.md` | the six `concepts` commits, from `Make the concepts intro and user section current` to `Remove the help agent from concepts and glossary` |
| D6 | `docs/glossary.md` | `Make the glossary describe what runs today`, `Separate vinga's agent from a coding agent`; the Help agent entry left with the concepts section it linked |
| D8c over every Use page, and D4's two Touch-LCD-1.54 sentences | `docs/devices/waveshare-esp32-s3-touch-lcd-1.54.md`, `docs/devices/README.md` (the commitment stays in `vinga-esp32/README.md`) | `State the board guides' firmware limits as present` |
| The index footprint and the `ahead of the code` sweep | `docs/README.md`, `docs/architecture/README.md` | `Describe concepts as current in both indexes` |
| D12 | `changelog.d/609-current-concepts.md` | `Add the changelog fragment for current-only concepts` |

Every one of the 31 references D5 lists by line went with its
passage's disposition. The check is the proof: on the pre-cleanup page
it reports exactly those 29 lines (L278 and L646 carry two each), and
on the M2 tree it reports nothing (Verification, below).

### Deviations from the plan

- **The direction marker is also matched across a line break.** D4
  says the pages are scanned line by line "which wrapping cannot
  hide", which holds for a `#123` token and not for a two-word
  phrase. The check matches `decided\s+direction` over the page's
  whole text and reports the line where the match starts. On the
  pre-cleanup `concepts.md` that is 14 lines, not the plan's 12: L332
  and L703 each wrapped "decided" and "direction" onto two lines. The
  glossary's Handover entry had one more. A test pins it.
- **`owner/repo#N` does not match a Markdown path's fragment.** A bare
  `owner/repo#N` pattern also matches `docs/page.md#1`, which D4 says
  must pass as `page.md#1` does. The repo part may not end in `.md`;
  a test covers both spellings and a mutation removing the exclusion
  turns it red.
- **A door link that resolves to `docs/README.md` itself enrolls
  nothing.** Read literally, D4's index rule would treat it as an
  index under `docs/` and enroll the whole `docs/` tree. It is a
  same-page link spelled with the filename; a test pins that the
  index, which may cite issues, and an unrelated page under `docs/`
  stay out.
- **Missing targets enroll nothing, and an unreadable page exits 2.**
  A door link to a missing file is the link checker's finding, so the
  set of kinds stays the four D4 closes; a page that cannot be read
  stops the check with a one-line sentence on stderr and exit 2 rather
  than passing it.
- **The Touch-LCD-1.54 firmware-build commitment has an owner.** D4
  sends it to the direction page only if nothing owns it. The firmware
  README's "Planned customizations" (`vinga-esp32/README.md`, a
  Develop-door page) already lists both items, an English wake word and
  an English UI language, so the board guide's two sentences became
  present limitations and the commitment stays where it was. The
  implementer first added it as an eighth direction entry; the
  orchestrator removed that entry before the PR, since a second home for
  the same direction is what the page exists to avoid. The page has
  D7's seven entries.
- **The direction page's taxonomy and index lines landed with the
  page**, not in the closing index commit, because the closed taxonomy
  says its list "changes in the commit that adds it".
- **Dates on the direction page.** D7 names 2026-08-21 and 2026-09-23,
  the dates `concepts.md` stamped. Several passages are older than
  their stamp (the stamp was added on 2026-08-27, `9bcf33ab`), and
  three carried none. Each entry gives the page's own stamp where it
  had one and otherwise the date of the commit that added the
  passage, and says which.
- **The Coding agent entry does not say "voice persona".** D6's
  wording would define vinga's agent with the word the agent-not-
  persona decision (`features/2026-08-12-agent-not-persona.md`)
  retired for exactly that noun. The entry names what an agent is
  instead, and states the convention the way Session states "device
  session": written **coding agent** wherever the bare word could be
  read as vinga's, since `AGENTS.md` and agent definitions use the
  word in their own names.
- **Three small corrections beyond D5's rows.** Session's transcript
  was "across every conversation touched plus the meta turns", the
  unowned recording rule in passing; the schema reference says every
  stored turn belongs to the thread active when it was spoken, so the
  phrase went. "The incoming agent starts clean, which the last bullet
  below states" had been wrong since the tool-exchanges bullet was
  added after the clean-switch one, and now names it. Meta
  capabilities says the handover tool is offered only where a device
  reaches more than one agent (`tools/source.py`), which the old text
  left out.
- **The board index's status column.** D8c turns "planned 🚧" into
  "not working 🚧" on `devices/README.md`, the 🚧 marking the present
  absence the stub guides' warnings describe. The root README and
  the firmware README keep "planned 🚧" in their hardware tables: the
  root README is a Run page this milestone does not write, and the
  sync rule binds those two tables to each other, not to the board
  index. The two wordings now differ, which review may want settled
  one way.
- **The glossary's Date line is unchanged.** D5 moves `concepts.md`'s
  date and D6 names none for the glossary.

### Resolutions

- **Q4.** The direction page is a dated record, listed in that class
  in `docs/README.md` and in the Develop door only. Its intro says
  entries are never removed or reworded and gain a dated line naming
  an issue or record that takes them.
- **D5's owners, re-read at implementation time.** From the issue
  bodies as the orchestrator verified them on 2026-10-05: #606 owns
  users and groups, the (user, agent) memory scope and the user
  profile, and lists budget enforcement and speaker identification
  (#608) out of scope, saying nothing of a user session or of
  configuration by voice; #612 owns vinga as the built-in default
  agent, replacing #21's help agent, and leaves configuration by voice
  to #606; #96 owns the observed device facts and the board catalog.
  Nothing in the tree contradicted them, so every D5 row stood as
  written.

### Discoveries

- **The `ahead of the code` sweep needs to match across line breaks.**
  `git grep -n -i 'ahead of the code'` found 7 lines and missed both
  live copies, `docs/README.md` and the architecture index, which
  wrapped the phrase. Matched across lines over every tracked file it
  found 12 positions before and 10 after, all 10 in dated records.
- **One mutation survived and was equivalent.** Joining a door
  section's lines with newlines instead of spaces changes nothing,
  because `LINK_RE`'s link text (`[^\]]*`) already spans a newline.
  The real line-by-line mutation (applying `LINK_RE` to each line) was
  run separately and killed by the wrapped-text test.
- **Mutations, one run each** (`.logs/m2-mutations.txt`,
  `.logs/m2-mutations-2.txt`), every one killed apart from the
  equivalent above: the bare `#N` pattern (8 tests red), the
  `owner/repo#N` pattern (`test_an_owner_repo_reference_fails`), the
  GitHub URL pattern (`test_a_github_issue_url_fails`,
  `test_a_github_pull_url_fails`), the marker (both marker tests), the
  marker's line-break span
  (`test_the_direction_marker_fails_across_a_line_break`), the
  missing-heading guard (both missing-heading tests and the fenced
  heading test), the empty-door guard
  (`test_a_door_linking_no_page_fails_closed`), the missing-index
  guard (`test_a_missing_index_fails_closed`), the `door-malformed`
  count (`test_a_door_link_with_a_broken_target_is_malformed`), the
  join (`test_a_door_link_with_wrapped_text_enrolls_its_page`), the
  index rule narrowed to the page and widened to the pre-amendment one
  level out (both `test_an_index_link_enrolls_its_directory_and_nothing_beyond`),
  directories outside `docs/`
  (`test_a_directory_link_outside_docs_enrolls_nothing`), the
  reference exclusion (`test_the_generated_references_are_excluded`),
  the self-link guard (`test_the_index_itself_is_never_enrolled`) and
  the `.md` exclusion
  (`test_anchors_entities_and_page_fragments_pass`).
- **The real tree's Run and Use pages are eleven:** the root README,
  `deployment.md`, the server README, `system-overview.md`,
  `concepts.md`, `glossary.md`, and the five pages under
  `docs/devices/`. Before the cleanup the check reported 50 findings,
  all on `concepts.md` (29 issue-reference lines, 14 marker lines) and
  `glossary.md` (6 and 1).

### Inventories

Untruncated, positions only, under `.logs/` in the implementer's
worktree.

- D8c over every Use page (`docs/devices/`, `concepts.md`,
  `glossary.md`) for `will `, `later`, `planned`, `future`, `not yet`
  and `🚧`: 20 positions before (`.logs/m2-d8c-use-pages.txt`), four
  about vinga's own future (the board index's two "planned" statuses
  and the two Touch-LCD-1.54 sentences D4 names), all rewritten; 18
  after (`.logs/m2-d8c-use-pages-after.txt`), none about vinga's
  future. The text M2 writes onto Run pages is `concepts.md` and
  `glossary.md`, which are in that sweep.
- The pre-cleanup driver run (`.logs/m2-driver-run.txt`): the M2 tree
  with `concepts.md` replaced by `3073d08b`'s exits 1 with 43
  findings, all on `concepts.md`: 29 `issue-reference` lines (exactly
  D5's 31 references) and 14 `direction-marker` lines (the 12 a
  per-line grep finds, plus L332 and L703).

### Verification

On agentpi, from the worktree root unless noted:

- `python3 scripts/check_doc_links.py .`: `checked 300 files, 0 failures`, exit 0.
- `python3 scripts/check_run_use_pages.py .`: `checked 11 Run and Use pages, 0 findings`, exit 0.
- `python3 scripts/fold_changelog.py check .`: `checked 2 fragments, 0 failures`, exit 0.
- `uv run ruff check .` from `vinga-server/`: All checks passed.
- `uv run pytest tests/unit -q -n auto --dist loadfile` from
  `vinga-server/`: `8080 passed, 19 skipped in 910.03s (0:15:10)`, exit 0.
- `uv run pytest tests/census -q` from `vinga-server/`: run last,
  after this section; its outcome is in the hand-back rather than
  here.
- The server workflow's new step (`working-directory: .`) runs for the
  first time on this milestone's pull request; that run is its test,
  and it is not verified here.

M2 adds no migration and changes no server code, so the integration
lane was not run.

### PR review round

Reviewed 2026-10-05 by openai/gpt-6-sol, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 3m11s, at commit 7bf6f82b ([the round](https://github.com/rafacm/vinga/pull/617#issuecomment-6005311644)).

1. **P2: a repeated door heading could leave linked pages unchecked.**
   `door_sections` kept one section per door title, so a second
   `## Run vinga` or `## Use vinga` replaced the first and a page
   linked only from the first went unscanned.
   *Resolution:* each occurrence of a door heading is now its own
   section, held to the door rules on its own, and every section's
   pages are enrolled.
   `test_a_repeated_door_heading_keeps_both_sections` puts `#123` on a
   page only the first of two Run vinga sections links; it was watched
   failing against the old script and passes now (`deb68e2d`).
2. **P2: the fragment counted eight direction entries.** The page has
   seven since the firmware commitment was left with its owner.
   *Resolution:* the fragment says seven (`52708bc3`).
3. **P3: the bad-invocation test passed with the script missing.**
   Python's own "can't open file" also exits 2 with one stderr line.
   *Resolution:* the test asserts the checker's own sentence for each
   invocation, the usage line and "the given repo-root is not a
   directory"; it was watched failing with the script moved aside and
   passes with it restored (`d825a8b3`).

After the fixes: the check's tests `28 passed`; `uv run ruff check .`
passes; `python3 scripts/check_run_use_pages.py .` reports
`checked 11 Run and Use pages, 0 findings`; the link check and the
census ran last, and their outcome is in the hand-back.

## M3a: the task-guide directory and the deployment guides

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.289; 2026-10-06.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| The move audit's tests, written first and watched failing (21 of 31 red; the ten exit-2 cases pass with the script absent, since Python exits 2 too) | `vinga-server/tests/unit/test_audit_doc_move.py` | `Test the page-move audit before writing it` |
| The move audit: the prototype with the exit policy, `edited=`, `DROP`, `README` and a required `kinds=` | `scripts/audit_doc_move.py` | `Audit a page move by paragraph, without its text` |
| Q1: `docs/run/` and its index, in the maintained-maps class and the index pages, linked from the Run door; Limits as the first guide | `docs/run/README.md`, `docs/run/limits-and-probes.md`, `docs/README.md` | `Move Limits into the first task guide` |
| Running in a container and Choosing an image; the permanent stub (D10) | `docs/run/running-in-a-container.md`, the server README | `Move the container and its image choice to a guide` |
| Backups | `docs/run/backups.md` | `Move backups and restores to their own guide` |
| D8b: recovery, decision before the destructive command | `docs/run/recovering-a-deployment.md` | `Move recovery to a guide that decides before it drops` |
| The master key into `security.md` | `docs/run/security.md` | `Start the security guide with the master key` |
| "An edit is stored" into `configuration.md` | `docs/run/configuration.md` | `Start the configuration guide with applying an edit` |
| D13: Which build is running, the rerun-then-boot rule, Past releases as changelog links (the API secret note dropped after review, below) | `docs/run/upgrading.md` | `Move upgrading to a guide that links past releases` |
| Providing the database and reading as `vinga_ro` | `docs/run/database.md` | `Move providing the database to its own guide` |
| Ports and topology, Behind a reverse proxy, the API at the edge | `docs/run/exposing-a-deployment.md` | `Move ports, the proxy and the API's edge to a guide` |
| Onboarding a device | `docs/run/onboarding-a-device.md` | `Move onboarding a device to its own guide` |
| Transports, with D8c's two rewrites | `docs/system-overview.md` | `Move Transports into the system overview` |
| D8a outside the README | `docs/deployment.md`, `deploy/postgres-init.sql`, `docs/reference/cli.md` | `Keep the admin connection out of psql's arguments` |
| The index in reading order; the Run door, root README and server README pointers | `docs/run/README.md`, `docs/README.md`, `README.md`, the server README | `Point the indexes and READMEs at the task guides` |
| The operator-surface rule names `docs/run/` | `AGENTS.md` | `Name docs/run/ as the home a plan's procedure lands in` |
| D14's last two sentences | `docs/deployment.md` | `Make deployment.md defer to the guides throughout` |
| The mapping | `docs/plans/2026-10-05-three-doors-and-task-guides-moves/m3a.tsv` | `Record where M3a's move units went` |
| D12 | `changelog.d/609-deployment-guides.md` | `Add the changelog fragment for the deployment guides` |

Each guide commit moved its units out of the README and retargeted
every inbound link and by-name pointer to them in the same commit, so
the link checker passed after each one (D10). The README went from
4,176 lines to 3,231 (957 removed, 12 added: the stub's sentence, the
retargeted pointers and the "On this page" entry).

The audit against the README at this branch's base (`7bf6f82b`, whose
README is byte-identical to `3073d08b`'s), exit 0
(`.logs/m3a-audit.txt` in the implementer's worktree):

```text
19 units, 135 paragraphs moved, 22 declared edited, 5 declared dropped, 1 kept in the page, 0 findings
```

The 22 declared edits, by mapping row and paragraph, and what each
became:

- Row 8 (Limits) 15: the "When a reply fails" link, which was wrapped
  across two lines, on one line and pointed at the README section it
  still lives in; `config.example.yaml` made a link.
- Row 13 (the container) 2 and 3: "this section is the one home"
  becomes this guide and the others in `docs/run/`, links made
  relative; 9: the `examples/` link.
- Row 15 (database) 2: "Eight things" becomes "Three things" and links
  the guides that took the rest; 4: the provisioning file's link;
  5: the provisioning command (D8a).
- Row 16 (upgrading) 7: "Rerun it when a release moves the file, too"
  leaned on the paragraph before it; its opening is now
  self-contained, and its link relative.
- Row 19 (security) 14: the wrapped rebuild link names the recovery
  guide; 15: rotation's "this release cannot retire one" and "the
  interim path until a re-encrypt command exists" stated as present
  fact (D8c).
- Row 22 (configuration) 24: "And the operational one, said again
  because" dropped from the opening.
- Row 24 (exposing) 2: "Four more things" becomes two, the README link
  made explicit, a pointer to where the container guide states the API
  secret added.
- Row 28 (recovery) 3: the whole-database block says what it deletes
  first, its provisioning rerun takes a service file (D8a), and "the
  run command from above" names the container guide; 13: the `cli.md`
  link. The reorder itself (D8b) changes no paragraph and the audit
  does not see order.
- Row 30 (Choosing an image) 13: the licenses link.
- Row 32 (onboarding) 16, 17 and 29: four links made relative.
- Row 34 (Transports) 2 and 3: D8c, below.
- Row 36 (ports) 2: `server.port` links the reference (D8); 10: the
  Limits link names the limits guide.

The 5 declared drops are past releases' notes, all of which the
changelog carries, so D13 links them rather than moving them: the four
D13 names (2026-08-30 for the `memory` schema's rerun, stopping before
starting, and the memory files left on disk; 2026-08-28 for the
`record` rename's rerun), and "Set `VINGA_API_SECRET` before rolling
the image, not after", which the first hand-back moved verbatim and
flagged because "an image from this release" and "the one upgrade step
this change forces" read like a release's note. Review confirmed it is
one: the changelog carries it under 2026-08-11 ("Every deployment must
set `SAMTAL_API_SECRET` before upgrading", the variable's name before
the rename). It is dropped (row 25), `upgrading.md`'s Past releases
list links that section and names the old spelling, and the standing
fact, that a server without the API secret refuses to boot and which
variable to set, is a new paragraph in `running-in-a-container.md`
under The container, where neither that guide nor `security.md`
stated it; being new rather than a changed moved paragraph, the audit
does not list it. `upgrading.md`'s opening and its index line no longer
mention the secret, and the exposure guide points at the container
guide for it. The one kept paragraph is the stub's heading.

Replaced blocks (D8's table rule): none. M3a's units hold no table or
list whose every row is a key, route, event or column a generated
reference states. The `/readyz` status table is in no reference (the
OpenAPI document does not describe the probes), the variant table is
not a contract, and the Limits YAML block is a worked example. Where a
moved sentence leans on a key's default or bound, the guide gains a
link rather than losing the sentence: a paragraph in
`limits-and-probes.md` linking `server` and `server.limits`, one in
`database.md` linking `server.database`, and `server.port` in
`exposing-a-deployment.md`.

### Deviations from the plan

- **The rerun-then-boot paragraph is in `upgrading.md`.** The plan's
  table lists "the rerun-then-boot rule" in the `database.md` row,
  while D13 calls it a procedure that "moves whole" in the paragraph
  about `upgrading.md`, and the milestone's brief places it in
  `upgrading.md`. It is the step an upgrade takes, so it is there;
  `database.md` links it, and `upgrading.md` links back for how the
  file is run. `database.md` keeps "rerun that file after any database
  reset", which is in the server-role paragraph.
- **The configuration API subsection's heading and opening sentence
  went to `exposing-a-deployment.md`.** No row of the table names them.
  They introduce the two edge decisions, so they moved with them, with
  "Four more things" made two and the README link explicit.
- **The index has three groups, not Q1's three.** Deploying, Keeping a
  deployment running, and Configuring. M3a has no observing guide, and
  upgrading, backups and recovery are neither deploying nor
  configuring.
- **The taxonomy's "Three directories hold one class each" became
  "Some".** It was already four before `run/` (reference, adr, plans,
  features), not counting the diagrams tree. `run/README.md` is also
  added to the index pages, the same double listing `devices/` has.
- **The audit requires `kinds=` on every moved unit**, since D8 says
  each row states it; a missing or unknown kind is a malformed mapping
  (exit 2), and `DROP` and `README` units take none. Destinations are
  paths relative to the directory the audit runs in, the repository
  root. `--list` marks a heading paragraph. A finding says "left behind
  in the page" and a kept unit "kept in the page", since the audit is
  not README-specific; the `README` keyword is the plan's.
- **Beyond the plan's inventory**, found by untruncated greps
  (`.logs/m3a-by-name-before.txt`, `.logs/m3a-by-name-after.txt`,
  `.logs/m3a-tests-reading-readme.txt`): `deploy/k8s/ingress.yaml` and
  `deploy/k8s/job-postgres-init.yaml` each named the README's answer or
  upgrade order; deployment.md's Kubernetes routing notes called the
  edge decisions "the README's", its contract section and its closing
  section named the README; the root README's Documentation section
  listed the container and onboarding as the server README's; and
  `tests/unit/test_config_cli_onboarding.py` read the onboarding
  walkthrough by splitting the README on its heading, which would have
  raised `IndexError` once the section moved. It reads the guide now.
- **The API secret paragraph is a fifth dropped release note.** The
  table puts it in `upgrading.md`; it is the 2026-08-11 changelog
  entry's note, so D13 applies, as recorded with the drops above.

### Resolutions

- **Q1.** `docs/run/` with `docs/run/README.md`, one line per guide.
  Recommendation for #611's plan: its coding-agent guide should link
  `docs/run/README.md` for the task-guide index rather than keep a
  second list, since two lists that must agree are one list with a bug
  pending. The operator-surface rule in `AGENTS.md` already names the
  index.
- **`docs/reference/cli.md` L556 is hand-written.** The recipe sits
  above the `generated: cli reference` marker (L641), and the drift
  checks compare only the regions between the markers, so it was
  edited directly.
- **The changelog's anchor.** The stub is
  `## Running in a container` over one sentence linking the guide and
  `docs/run/`; `CHANGELOG.md`'s link still resolves.

### Discoveries

- **The same credential-in-arguments defect exists outside D8a's
  pattern**, which looks for `psql`, `pg_dump`, `pg_restore` or `curl`
  expanding `$NAME`. Eleven positions
  (`.logs/m3a-d8a-outside-pattern.txt`): the Kubernetes provisioning
  Job passes `$(ADMIN_URL)` to psql as an argument inside its pod
  (`deploy/k8s/job-postgres-init.yaml:82`), and `kubectl create secret
  ... --from-literal=NAME="$VALUE"` puts secrets in kubectl's
  arguments in `docs/deployment.md` (L317-319, L397, L399),
  `deploy/k8s/secret.yaml.example` (L16-18) and
  `deploy/k8s/secret-init.example` (L17, L19). Not fixed here: the Job
  is a deployed artifact `test_deploy_manifests.py` holds to the code,
  and `--from-file`/`--from-env-file` changes the documented lane. It
  wants its own issue.
- **"Separating the two later" in Behind a reverse proxy** (now
  `exposing-a-deployment.md`) describes running the image twice behind
  one database, which the one-replica record says is not a supported
  topology. It moved verbatim, since it is an operator's option and
  not a commitment (D8c); the contradiction predates this move and is
  worth a look. (The review round removed it: finding 5.)
- **Two mutation survivors on the first round**, both findings about
  the tests: dropping fence tracking survived because the fixture's
  fence happened to split into the same paragraph count, and
  accepting a non-heading line survived because the test's missing
  destination exited 2 first. The fixture now splits differently
  without fence tracking, and every exit-2 test names the refusal it
  expects with its destinations present. Second round: all 21
  mutations killed (`.logs/m3a-audit-mutations-2.txt`): the
  left-behind check (5 tests), occurrence consumption, the named-twice
  check, the stale-edit check, a kept unit naming two paragraphs or a
  body paragraph, a kept heading's presence, printing text for the
  digest (2), fence tracking (7), kinds required and validated, unknown
  fields, edits outside the unit, the range bound, an empty mapping,
  the not-a-heading refusal, comparing headings with their #s (3),
  whitespace collapsing, exit 0 always (12), `DROP` not claimed, and a
  missing destination read as empty (14).
- **The planted faults, rerun on the real README with the committed
  script** (`.logs/m3a-planted-faults.txt`): five units over `## Tools`
  into three destinations, 68 paragraphs, 0 findings, exit 0; one
  paragraph deleted from a split unit's destination, exactly that
  paragraph reported, exit 1; a credential-shaped sentinel in the
  moved heading, 0 matches in the output of a passing run and of a
  68-finding failing run; two overlapping units, both shared
  paragraphs reported as named twice, exit 1; the section also left in
  the page, 68 left-behind findings, exit 1.

### Inventories

Untruncated, positions only, under `.logs/` in the implementer's
worktree.

- D8a (`.logs/m3a-d8a-before.txt`, `.logs/m3a-d8a-after.txt`): 8
  positions at the base outside the dated records, plus the two-line
  Langfuse form at the README's Langfuse section. M3a's five are fixed:
  `deploy/postgres-init.sql:11`, `docs/deployment.md:192`,
  `docs/reference/cli.md:556`, `vinga-server/README.md:3507` and
  `:3751`. Three remain, all assigned to later milestones:
  `vinga-server/README.md:479` (L483 at the base, M3b), `:1773` (L1777,
  M3c), `vinga-server/examples/tts-elevenlabs.yaml:17` (M3b), and the
  Langfuse form at `vinga-server/README.md:2942` (L3055-3056 at the
  base, M3d). The
  guides under `docs/run/` have none.
- D8c over the text M3a writes onto Run pages
  (`.logs/m3a-d8c-guides.txt`, dispositions in
  `.logs/m3a-d8c-dispositions.txt`): 27 positions under `docs/run/`,
  none about vinga's own future: 13 are a guide's "you will have" end
  state, 4 a present conditional ("will not open", "will not match"),
  4 a title or heading naming a server that "will not start", 3
  "later" in the sense of time, 1 "not yet in effect" describing an
  edit, 1 what this build never reads, and the operator's option
  above. Before the move, three sentences in M3a's
  units were about vinga's future and were rewritten: Transports' "or
  plans for v1" and "Supporting it later is additive", and rotation's
  re-encrypt command. The Transports section on `system-overview.md`
  has no hit after them.
- Prose pointers (`.logs/m3a-prose-pointers.txt`): 15 `above` or
  `below` in the guides, every one pointing within its own page.
- Anchored links into the server README from outside it
  (`.logs/m3a-server-readme-links-before.txt`), by `git grep`: every
  one to an anchor M3a moved now points at a guide, apart from
  `CHANGELOG.md`'s `#running-in-a-container`, which the stub keeps.

### Verification

On agentpi, from the worktree root unless noted:

- `python3 scripts/check_doc_links.py .`: `checked 311 files, 0 failures`, exit 0.
- `python3 scripts/check_run_use_pages.py .`: `checked 22 Run and Use pages, 0 findings`, exit 0 (the ten guides and their index joined the eleven pages M2 counted).
- `python3 scripts/fold_changelog.py check .`: `checked 2 fragments, 0 failures`, exit 0.
- `python3 scripts/audit_doc_move.py` over `m3a.tsv`: exit 0, quoted above.
- `uv run ruff check .` from `vinga-server/`: All checks passed.
- `uv run pytest tests/unit -q -n auto --dist loadfile` from
  `vinga-server/`: `8112 passed, 19 skipped in 888.96s (0:14:48)`,
  exit 0 (M2's 8080 plus the audit's 32).
- The compose file's two resolutions, the `unit` job's first step, run
  by hand on a copy of `docker-compose.yml` and `deploy/` (so its
  `.env` could not reach the unit lane running beside it): the
  profile-less invocation is the database alone, the server profile
  refuses with no secrets and resolves to both services with dummy
  ones. The step's telemetry and production-file arms were not run
  locally; M3a changes no file they read beyond comments.
- `uv run pytest tests/census -q` from `vinga-server/`: run last,
  after this section; its outcome is in the hand-back rather than
  here.
- Not run: the integration lane, since M3a changes no code it
  exercises and adds no migration; the image job and kubeconform,
  which run in CI on the pull request because M3a touches `deploy/`,
  `docker-compose.yml` and the Dockerfile (comments only).

### PR review round

Reviewed 2026-10-06 by openai/gpt-6-sol, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 4m10s, at commit ac40be9f ([the round](https://github.com/rafacm/vinga/pull/618#issuecomment-6006191404)).

1. **P1: an unopenable destination escaped as a traceback.** `read()`
   caught `OSError` and `UnicodeDecodeError`, and `main()` only the
   audit's own error, so a destination path with a NUL byte (a
   `ValueError` from the operating-system call) reached stderr as a
   library traceback, against the no-leak contract.
   *Resolution:* `read()` catches `ValueError`, which includes
   `UnicodeDecodeError`, and reports the text-free "cannot read the
   destination on row N", exit 2.
   `test_a_destination_no_file_can_have_exits_2` was watched failing
   first (exit 1, ending in `ValueError: embedded null byte`), and
   narrowing the handler back turns exactly it red
   (`.logs/m3a-fix1-mutation.txt`); a second test pins the non-UTF-8
   case nothing exercised before (`e8e94cad`).
2. **P1: `dropdb` and `createdb` ran on libpq's defaults.** The
   whole-database reset took psql's connection from the `vinga-admin`
   service but gave the two destructive commands none, so they could
   act on a same-named database wherever the reader typed.
   *Resolution:* both run under `PGSERVICE=vinga-admin` with
   `--maintenance-db=postgres`, the block says why, and `database.md`'s
   `~/.pgpass` line uses `*` for the database so the maintenance
   connection finds the password. `docs/reference/cli.md`'s
   hand-written recipe, which the block came from, had the same pair
   and gets the same fix (`b423f998`).
3. **P2: the domain-only reset showed its SQL before stopping the
   server, with no way to run it.**
   *Resolution:* the SQL block is now a shell block that stops the
   server and then runs the statement with
   `PGSERVICE=vinga psql -c`, as the server role on the deployment's
   own database; `database.md` describes that second service, and the
   paragraph after it says which lines of the whole-database block to
   skip. Declared edited, row 28 paragraph 6 (`f6e4d155`).
4. **P2: the onboarding guide said a wrong key is logged beside the
   right one.** `onboarding/keys.py` deliberately logs neither key:
   `_log_mismatch` emits `onboarding_key_mismatch` with only the
   attempt's length, or `onboarding_key_unshaped` for a segment no
   person typed at a key.
   *Resolution:* the paragraph says so and links both events in the
   generated reference. The falsehood predates M3a: the README carried
   it since at least the 2026-08-19 rename (`ffa2a72d`), and the code
   has quoted neither key since the PR #153 review its docstring names;
   M3a moved it verbatim. Declared edited, row 32 paragraph 26
   (`8b8f5115`).
5. **P2: the exposure guide told an operator to run the image twice.**
   Two processes on one database break activation, apply and the
   session cap, as the container guide's one-replica paragraph says.
   *Resolution:* the paragraph is removed; `m3a.tsv` splits the Ports
   and topology unit so it is a declared `DROP` (row 37), since none of
   it moved anywhere (`499c4b43`). The discovery recorded above is
   closed by it.
6. **P2: two Past releases lines restated their release's steps.**
   *Resolution:* each line is the date, linked, and a few words naming
   the change, with no instruction; the 2026-08-11 line keeps
   `SAMTAL_API_SECRET` as the old name only (`1b635e7f`).

After the fixes, against `git show origin/main:vinga-server/README.md`
(byte-identical to the base used above), the audit exits 0:

```text
20 units, 135 paragraphs moved, 24 declared edited, 6 declared dropped, 1 kept in the page, 0 findings
```

The audit's tests `34 passed`; the link check reports
`checked 311 files, 0 failures` and the Run and Use check
`checked 22 Run and Use pages, 0 findings`; the D8c sweep over
`docs/run/` still has 27 positions (`.logs/m3a-d8c-guides-3.txt`): the
removed paragraph's "later" is gone, and the guide title database.md
now links for the configuration-only reset is one more;
the census ran last, and its outcome is in the hand-back.

Beyond the round: `docs/reference/cli.md`'s hand-written recovery
recipe carried the same defect finding 3 named in the guide, a bare
`drop schema domain cascade;` SQL block with no stop and no named
connection. The orchestrator gave it the guide's shape: the server
stopped at step 1, the drop run as the server role through the `vinga`
service with its password in `~/.pgpass`, in place of step 2.

## M3b: providers, tools, memory and prompts

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.289; 2026-10-06.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| Choosing a voice, ElevenLabs, OpenAI; D8's ElevenLabs table; D8a's voice listing | `docs/run/voices.md` | `Move choosing a voice and the TTS types to a guide` |
| Choosing how it hears, OpenAI transcription; D8's transcription table; the example's by-name pointer | `docs/run/speech-recognition.md`, `vinga-server/examples/asr-openai.yaml` | `Move choosing how an agent hears to a guide` |
| The Providers section's own paragraphs; D8c's licensing note; the root README's `#providers` link and the two "every provider option" annotations | `docs/run/providers.md`, `README.md`, `docs/README.md` | `Move the providers table and licensing to a guide` |
| What the model is actually sent | `docs/run/agents-and-prompts.md` | `Move what the model is sent to its own guide` |
| The Tools section's memory run, `remember` to "Whether an agent remembers at all" | `docs/run/memory.md` | `Move what an agent remembers to its own guide` |
| The rest of Tools and What the MCP servers are doing; D8c's SSE and display sentences; Applying a change without a restart promoted to a section | `docs/run/tools-and-mcp.md`, the server README, `tests/unit/test_config_cli_rendering.py` (a docstring) | `Move tools and the MCP status to their own guide` |
| D8a in the example fragment | `vinga-server/examples/tts-elevenlabs.yaml` | `Keep the ElevenLabs key out of curl's arguments` |
| The index | `docs/run/README.md` | `List the provider, tool, memory and prompt guides` |
| Seven statements corrected against the code (below) | `tools-and-mcp.md`, `memory.md`, `speech-recognition.md` | `Correct what the moved guides claimed about the code` |
| The mapping | `docs/plans/2026-10-05-three-doors-and-task-guides-moves/m3b.tsv` | `Record where M3b's move units went` |
| D12 | `changelog.d/609-provider-guides.md` | `Add the changelog fragment for the provider guides` |

Each guide commit moved its units and retargeted every inbound link
and by-name pointer to them, so the link checker passed after each
one. The guides that link each other were created in an order that
kept every intermediate commit green (voices, speech recognition,
providers; prompts, memory, tools), and the last of each group added
the links back. The README went from 3,231 lines to 2,117 (1,123
removed, 9 added).

The audit against the README at this branch's base (`ac40be9f`, M3a's
tip), exit 0 (`.logs/m3b-audit.txt` in the implementer's worktree):

```text
11 units, 150 paragraphs moved, 24 declared edited, 0 declared dropped, 0 kept in the page, 0 findings
```

The 24 declared edits, by mapping row and paragraph, and what each
became:

- Row 8 (Providers) 5: "see Security below" links the README's
  Security section, where it still is until M3c; 8: "any future
  `edge-tts` provider" becomes the present rule for that GPL package
  (D8c).
- Row 10 (Choosing how it hears) 13: "the cost table near the end of
  this page" links the README's cost definitions.
- Row 11 (OpenAI transcription) 3: "the TTS types above" links
  `voices.md`; 4: the option table becomes a link to its reference
  section and a sentence naming the facts the reference lacks and
  where below they are said (D8); 7: correction (below); 21: "See
  Security below" links the README section.
- Row 14 (ElevenLabs) 6: the voice listing hands curl the key on
  standard input through `printf` (D8a), followed by a new sentence
  saying why; 7: the option table becomes a link to its reference
  section, keeping as a sentence the one fact the reference lacks,
  Swedish among the default model's languages (D8); 10: the Security
  link.
- Row 15 (OpenAI speech) 18: the Security link.
- Row 17 (Tools, first run) 3 and 25: correction (below); 7: D8c's SSE
  rewrite, "vinga implements no SSE transport of its own; an SSE-only
  server is reached through the `mcp-proxy` bridge", keeping the
  rationale in the present tense; 12 and 22: corrections; 15 and 23:
  "the surface below" links the prompt preview in
  `agents-and-prompts.md`; 27: "`server.conversations.resumption`
  (below)" links its reference section.
- Row 18 (memory) 30: the Listening and barge-in link, a same-page
  anchor, names the README section; 33 and 36: corrections.
- Row 19 (Tools, last run) 49: "(15 seconds by default)" is the
  reference's to state, so the sentence links `tool_timeout_s`
  instead (D8); 50: "The condition for revisiting this is the
  display..." becomes "The device path renders speech and nothing
  else, so no result carries structured content to the board" (D8c).
  The decision itself is the 2026-08-13 MCP operability plan's, which
  records it, so nothing moves to `direction.md`.

Replaced blocks (D8's table rule): the OpenAI transcription table
(row 11, 4) and the ElevenLabs table (row 14, 7), each now a link to
its section of `docs/reference/domain-config.md` (`asr` options for
`type: openai`, `tts` options for `type: elevenlabs`). The OpenAI
speech table stays (deviation, below). Each guide also opens with a
new paragraph linking the reference sections for every field it
names, M3a's convention.

### Deviations from the plan

- **The OpenAI speech table is kept.** D8 names it among the three
  tables to replace, but `domain-config.md` declares no options for
  `tts openai`: it is one of the passthrough types whose options the
  reference says are written down in their example fragments. Under
  D8's own test (a table "which the generated page states") it stays,
  and `voices.md`'s opening says where the undeclared types' options
  are written down.
- **Prose was replaced only where a sentence states a key's default,
  bound or accepted values and nothing else.** That is D8's own
  enumeration ("a key's default or bound, what a route answers, a
  column's meaning"), and it found one sentence beyond the two tables:
  the tool timeout's default. Many moved paragraphs about MCP guidance,
  prompt fragments and the memory switch describe behavior the
  reference's field descriptions also describe, often in the same
  words, since those descriptions were written from this README. They
  explain and advise, so they kept their words and gained the opening
  paragraph's links rather than being cut to a link each. A reviewer
  who reads D8 more strictly will find them in `tools-and-mcp.md`
  (Guidance for a server's tools), `agents-and-prompts.md` (the
  `prompt_includes` paragraph) and `memory.md` (Switching it off).
- **Seven verbatim paragraphs were corrected, not moved verbatim.**
  The brief, after M3a's review found two falsehoods its move had
  carried, asked for the moved claims about logging, refusals,
  offers and bounds to be checked against the code. Twenty-six were
  checked; seven were wrong or short, all of them errors that predate
  this move:
  - the reserved MCP entry names (row 17, 3) and the always-offered
    builtins (row 17, 25) both omitted `set_device_location`
    (`tools/names.py` `BUILTIN_TOOL_NAMES`, `tools/source.py`
    `snapshot`), reserved since 2026-09-11;
  - "An unset variable fails the boot" holds only for an entry some
    agent references (row 17, 12): only referenced entries get a
    manager, and resolution happens in its constructor
    (`tools/mcp/manager.py`);
  - "Values shorter than eight characters are left alone" (row 17,
    22) is not true of a value known to be a credential, which is
    redacted at any length (`tools/mcp/prompts.py`,
    `REDACTION_FLOOR`, since #504);
  - a forgotten fact is held "until that conversation ends" (row 18,
    33): it is held for as long as the conversation is kept, which on
    a recording deployment outlives the session, and until the
    session closes where nothing is recorded (`memory/store.py`);
  - "the deletion answers how much of it went" (row 18, 36): only an
    erasure through the API reports the ledger and held facts it took;
    the retention prune reports conversations, sessions and days
    (`conversations/store.py`);
  - the prompt-echo comparison ignores any sentence-final punctuation,
    not only "a full stop" (row 11, 7; `providers/openai_asr.py`,
    `TRAILING`).
- **Applying a change without a restart is promoted from H3 to H2 in
  the README.** It stays for M3c, and the `## Tools` section it sat
  under is gone; its anchor is unchanged, and the audit compares
  headings without their `#`s, so it is not a finding.
- **`memory.md` has three headings the README did not.** The memory
  run had no heading of its own; the guide adds "What an agent keeps",
  "Reading and correcting what it kept" and "Switching it off" above
  paragraphs that moved verbatim.
- **The index lists the six guides under Configuring**, ahead of the
  two M3a put there, in the order a deployment meets them.

### Resolutions

- **Where the `## Tools` heading went.** It moved with the first run
  to `tools-and-mcp.md`, as a section heading under the guide's title.
- **`server.conversations.resumption` (below)** pointed at the
  conversation store, which M3d moves; the guide links the key's
  reference section instead, which no later milestone moves.

### Discoveries

- **The claims checked and found true**, so the next milestone need
  not redo them: the entry-name pattern; the empty grant refused and
  the grant rechecked at call time; the unpublished-grant warning; the
  shipped-guidance capture, listing check and position-only warnings;
  the 4000-character cap; device tool name sanitizing; the
  resumption offer rules; tool failures as error results; the
  placeholder for non-text content; the memory scope bounds, the
  injected block, `recall`'s bounds and the ownership-blind answer;
  the ledger's caps and order; the 700 ms default; `vinga memory set`
  taking no text argument; memory off withholding all seven tools and
  every block; the prompt order and `prompt_assembled`; the three MCP
  states; the 0.1 s floor, retries off and the host-decided OpenAI
  checks. Two caveats not worth an edit: `vinga memory delete` asks
  only when standard input is a terminal (`--force` and piped input
  proceed), and a tool shadowed by a more specific grant draws no
  unpublished-grant warning.
- **The guide-to-README links are M3c's and M3d's to retarget.** Five
  links now point from the new guides into README sections later
  milestones move: Security (four times), the cost definitions, and
  Listening and barge-in.
- **`domain-config.md` describes the passthrough types' options as
  documented "in the example fragments below"**, and `voices.md`'s
  OpenAI table is a second home for the same facts as
  `tts-openai.yaml`. Typing that provider (the reference names #88)
  would let the table become a link too.

### Inventories

Untruncated, positions only, under `.logs/` in the implementer's
worktree.

- D8a (`.logs/m3b-d8a-before.txt`, `.logs/m3b-d8a-after.txt`): 3
  positions at the base plus the Langfuse form; M3b's two are fixed
  (`vinga-server/README.md:479`, now in `voices.md`, and
  `vinga-server/examples/tts-elevenlabs.yaml:17`). Two remain, both
  later milestones': `vinga-server/README.md:657` (L1777 at `3073d08b`,
  M3c) and the Langfuse form at `:1826` (M3d). The guides under
  `docs/run/` have none.
- D8c over the six guides (`.logs/m3b-d8c-guides.txt`, dispositions in
  `.logs/m3b-d8c-dispositions.txt`): 11 positions, none about vinga's
  own future: 6 a guide's end state, 2 "later" in the sense of time,
  2 present conditionals, and one rationale for the fixed prompt order
  ("lets a later feature compose against a known base"), which names
  no commitment. The three rewritten before the move are listed above.
- Prose pointers (`.logs/m3b-prose-pointers.txt`): 23 `above`, `below`
  or `this page` in the guides, every one within its own page.
- Anchored links to M3b's anchors (`.logs/m3b-anchors-before.txt`,
  `.logs/m3b-anchors-after.txt`): 6 lines before (the root README's
  `#providers`, and five inside the server README), none after. By-name
  pointers (`.logs/m3b-by-name-before.txt`,
  `.logs/m3b-by-name-after.txt`): the root README's "every provider
  option", `docs/README.md`'s annotation, the example comment and the
  test docstring; what remains is the guides' own headings and code
  that names the OpenAI API or a test section. Tests reading the README
  (`.logs/m3b-tests-reading-readme.txt`): only `test_event_docs.py`,
  whose section is M3d's.

### Verification

On agentpi, from the worktree root unless noted:

- `python3 scripts/check_doc_links.py .`: `checked 317 files, 0 failures`, exit 0.
- `python3 scripts/check_run_use_pages.py .`: `checked 28 Run and Use pages, 0 findings`, exit 0 (the six guides joined M3a's 22).
- `python3 scripts/fold_changelog.py check .`: `checked 2 fragments, 0 failures`, exit 0.
- `python3 scripts/audit_doc_move.py` over `m3b.tsv`: exit 0, quoted above.
- `uv run ruff check .` from `vinga-server/`: All checks passed (a test docstring changed).
- `uv run pytest tests/unit -q -n auto --dist loadfile` from
  `vinga-server/`: `8113 passed, 19 skipped in 930.39s (0:15:30)`,
  exit 0, run after the test docstring changed; every commit after it
  touches documentation only.
- The voice listing's `curl -K -` form, run against a local listener
  with a dummy key: the request carried the `xi-api-key` header.
- `uv run pytest tests/census -q` from `vinga-server/`: run last,
  after this section; its outcome is in the hand-back rather than
  here.
- Not run: the integration lane, since M3b changes no code it
  exercises and adds no migration.

### PR review round

Reviewed 2026-10-06 by openai/gpt-6-sol, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 2m53s, at commit 34308ea5 ([the round](https://github.com/rafacm/vinga/pull/619#issuecomment-6006702674)).

1. **P1: the ElevenLabs key still reached the shell.** The voice
   listing in `voices.md` and the `tts-elevenlabs.yaml` comment passed
   `"$ELEVENLABS_API_KEY"` to the builtin `printf`: out of the process
   table, but `set -x` prints the expanded argument to stderr, so the
   guide's claim that tracing could not see it was false.
   *Resolution:* both now read the header from a curl config file
   created with mode 0600 (`install -m 600 /dev/null`) and written in
   an editor, passed as `curl -s -K ~/.elevenlabs-curlrc`, so the key
   is in no argument and no expansion; the claim about the builtin is
   gone, and the changelog fragment follows. Run against a local
   listener with a dummy key, the request carried the header and the
   file's mode was 600. This supersedes D8a's `printf` form for this
   command; row 14, paragraph 6 stays a declared edit (`c43b4ba9`).
2. **P2: memory was said to be read on every reply.** The prompt guide
   said a fact one conversation stores reaches a concurrent one on its
   next reply. Since #536 `_system_prompt` keeps the memory read for a
   conversation's activation under `_SnapshotKey`.
   *Resolution:* the paragraph states the snapshot's lifetime (read at
   the first reply of an activation and kept; another conversation's
   write or an operator's correction seen at the next activation) and
   the three things that make the next reply read again (a hard
   deletion by `vinga memory delete`, the API or a permanent `forget`;
   the memory switch moving; a failed read), and how the
   conversation's own writes reach it. The error predates the move.
   Declared edited, row 21 paragraph 9 (`fc2ea838`).
3. **P2: `prompt_assembled` was said to carry the whole preview's
   counts.** It reports only the half assembled at activation; memory's
   sizes ride each reply round.
   *Resolution:* the paragraph names `prompt_assembled.sources` for the
   persona, fragments and guidance and `llm_round`'s
   `system_characters`, `memory_characters`, `memory_sources` and
   `memory_facts` for the rest, linking both events' reference
   sections. The error predates the move. Declared edited, row 21
   paragraph 8 (`d52c0577`).
4. **P2: an agent told nothing was said to get no memory block.**
   `with_scopes` sends a framed `memory` block saying nothing is saved
   yet whenever the agent may remember and every scope is empty.
   *Resolution:* `memory.md` and the prompt guide's order paragraph say
   so. The error predates the move. Declared edited, row 18 paragraph
   29 and row 21 paragraph 4 (`56447e5b`).
5. **P2: the `vinga memory set` example typed the fact into `echo`'s
   arguments**, directly under the sentence warning that arguments land
   in shell history and the process list.
   *Resolution:* the example writes the fact in an editor and hands the
   file over on `-f` or on standard input. Typing at the command's own
   standard input is not offered, because `vinga memory set` refuses a
   terminal with nothing piped into it (`config/cli/input.py`). The
   example predates the move too. Declared edited, row 18 paragraph 40
   (`8cc1d3dd`).

The audit against `git show origin/main:vinga-server/README.md` (byte
identical to `ac40be9f`'s), exit 0
(`.logs/m3b-audit-round1.txt`):

```text
11 units, 150 paragraphs moved, 29 declared edited, 0 declared dropped, 0 kept in the page, 0 findings
```

The changelog fragment names the three corrected statements and the
example alongside the seven from the first hand-back. No code or test
changed in this round, so ruff and the unit lane were not rerun; the
link check, the Run and Use check, the fragment check and the census
were.
