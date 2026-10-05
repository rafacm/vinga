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
| D8c over every Use page, and D4's two Touch-LCD-1.54 sentences | `docs/devices/waveshare-esp32-s3-touch-lcd-1.54.md`, `docs/devices/README.md`, an eighth direction entry | `State the board guides' firmware limits as present` |
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
- **The direction page has eight entries, not seven.** D7 lists seven
  from D5; D4 sends the Touch-LCD-1.54 firmware-build commitment there
  too when it has no owner, and no issue or record was named where it
  was recorded. It is the eighth, quoting both sentences and noting
  that the firmware README's "Planned customizations" lists the same
  two. Whether that README counts as the commitment's owner, which
  would make the entry redundant, is a question for review.
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
