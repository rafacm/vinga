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
