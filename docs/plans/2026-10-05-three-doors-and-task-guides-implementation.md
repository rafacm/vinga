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
  worth a look.
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
