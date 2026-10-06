# vinga documentation

Three doors, by what you came to do. **Run vinga** is for whoever
deploys and operates a server, **Use vinga** for whoever talks to a
device, and **Develop vinga** for whoever changes the code, a person
or a coding agent working for one. The generated
[Reference](#reference) is shared between them rather than repeated
in each. [Where knowledge lives](#where-knowledge-lives) says which
page holds each kind of knowledge, and [Authority](#authority) says
what each class of page may claim.

## Run vinga

- [**Getting Started**](../README.md#getting-started): the path from
  nothing to a board answering a server on your own computer.
- [**run/**](run/): one task guide per page, from running the container
  to onboarding a device, listed one line each in
  [the guides' index](run/README.md).
- [**deployment.md**](deployment.md): from a published image to a
  deployment that stays up, in a Docker Compose lane and a Kubernetes
  lane, with the artifacts under [`../deploy/`](../deploy/) that
  implement it.
- [**deploy/postgres-init.sql**](../deploy/postgres-init.sql): the one
  thing a deployment runs against its own Postgres before the server
  does; its header says what the executor needs and why rerunning it
  is safe.
- [**vinga-server**](../vinga-server/README.md): the server in full:
  the two halves of the configuration and the security defaults;
  running it, onboarding a device and choosing its providers are task
  guides under `run/`.
- [**system-overview.md**](system-overview.md): one conversation turn
  from the wake word to the spoken reply, each concept explained
  before its acronym is used.
- [**concepts.md**](concepts.md): the domain model from the user's
  point of view, as it runs today: device, agent, binding,
  conversation, session, and the semantics that connect them (wake
  word, switching, memory, meta capabilities).
- [**glossary.md**](glossary.md): the concepts, techniques, and
  technologies the project is built on, one short definition each.
- [**Reference**](#reference): every command, configuration key, API
  route, event and stored table, generated from the code.

## Use vinga

- [**devices/**](devices/): one guide per board vinga targets,
  describing the hardware in front of you.
- [**The common page**](devices/README.md): what every board running
  the upstream firmware shares: listening modes, networks, getting a
  board onto your server, and what the device answers by voice.
- [**Waveshare ESP32-S3-Touch-LCD-1.54**](devices/waveshare-esp32-s3-touch-lcd-1.54.md):
  the board vinga is developed on, and the one guide written in full.
- [**Waveshare ESP32-S3-ePaper-1.54**](devices/waveshare-esp32-s3-epaper-1.54.md):
  a stub 🚧, read from the upstream board support code.
- [**Waveshare ESP32-S3-Touch-AMOLED-2.16**](devices/waveshare-esp32-s3-touch-amoled-2.16.md):
  a stub 🚧, brought up far enough to learn what its guide records.
- [**devices/flashing.md**](devices/flashing.md): writing the firmware
  over USB, the one procedure that is the same on every board.
- [**concepts.md**](concepts.md): what a device, an agent, a binding
  and a conversation are.
- [**glossary.md**](glossary.md): one short definition per word vinga
  uses, with pointers for going deeper.

## Develop vinga

- [**AGENTS.md**](../AGENTS.md): the commands, the workflow, and the
  design, writing and documentation conventions every change follows,
  whoever or whatever makes it.
- [**architecture/**](architecture/README.md): the index for where the
  boundaries are and what a change is held to, organized by the
  question you arrived with; the promises, the guidelines, the design
  and CLI guides and the observability map are behind it.
- [**architecture/diagrams/**](architecture/diagrams/README.md): every
  diagram, indexed by the question it answers, a directory per
  authoring tool.
- [**system-overview.md**](system-overview.md): one conversation turn
  end to end, the walk the diagrams illustrate.
- [**vinga-esp32**](../vinga-esp32/README.md): the thin firmware
  customization and the boards it targets.
- [**xiaozhi-notes.md**](xiaozhi-notes.md): the device↔server protocol,
  key by key, and the upstream projects it came from. Read this first
  for anything protocol-related.
- [**related-projects.md**](related-projects.md): neighbouring voice
  assistant and agent projects, and the projects vinga is built from,
  with the license terms left in
  [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md).
- [**conversational-quality-regression-suite.md**](conversational-quality-regression-suite.md):
  why field tests exist and how a test round is set up and analyzed.
- [**architecture/cli-guide-audit.md**](architecture/cli-guide-audit.md):
  the 2026-08-24 walk of four published CLI guides the CLI guide's
  practices were dispositioned from.
- [**architecture/direction.md**](architecture/direction.md): decided
  direction no issue or record owned when it was written down, one
  dated entry each, with the open issue it waits on.
- [**adr/**](adr/README.md): one immutable record per decision that
  was hard to reverse, surprising without context, and the result of a
  real trade-off.
- [**plans/**](plans/): one dated file per accepted plan, each with an
  `-implementation` companion whose sections the plan's milestone
  checklist links; the first is
  [vinga-server v1](plans/2026-08-02-samtal-server-v1.md) ·
  [implementation notes](plans/2026-08-02-samtal-server-v1-implementation.md).
- [**features/**](features/): one dated doc per significant change made
  outside any plan.
- [**CHANGELOG.md**](../CHANGELOG.md): every notable change, by date.
- [**Reference**](#reference): the same generated pages the Run door
  reads.

## Reference

Generated from the code and diffed by CI, so none of it can come to
describe a server this repository does not build:
[`reference/`](reference/), shared by every door.

- [**reference/cli.md**](reference/cli.md): the configuration CLI,
  from installing it to rebuilding a deployment whose server will not
  boot, and every command's own help page.
- [**reference/domain-config.md**](reference/domain-config.md): every
  field of the domain half of the configuration.
- [**reference/server-config.md**](reference/server-config.md): every
  key of the server half, the `server:` section of the YAML file, with
  its type, default, bounds and the combinations refused at boot.
- [**reference/api-openapi.json**](reference/api-openapi.json): the
  configuration API's contract, which an install carrying the client
  alone reads instead of asking a server.
- [**reference/events.md**](reference/events.md): the structured
  events, which are this server's observability surface.
- [**reference/conversations-schema.md**](reference/conversations-schema.md):
  the conversation store's tables.
- [**reference/metrics-views.md**](reference/metrics-views.md): the
  named aggregate views over that store, one section per view.

## Where knowledge lives

Each kind of knowledge has one home, and the other pages link it
rather than restate it. A home that does not exist yet names the issue
that builds it.

| Kind | Home | Reaches a person through | Reaches a coding agent through |
| --- | --- | --- | --- |
| **Facts**: what a key means, its default, bounds and refusals | the models' `Field(description=)` and the entity descriptor registry | the generated [Reference](#reference) | `vinga schema`, `vinga reference`, `--help` |
| **Concepts**: what the nouns are and how they relate | [`concepts.md`](concepts.md) and [`glossary.md`](glossary.md) | the Run and Use doors | the same pages |
| **Device behavior** | [`devices/`](devices/), one guide per board; the browser client's guide is #613 | the Use door | the same guides |
| **State**: what this deployment has, what is missing, the next command | `vinga info` reports which deployment this is and how much of each kind is configured; a readiness model that names what is missing is #611 | `vinga info` | `vinga info` |
| **Procedures**: how to do one task | one task guide per task under [`run/`](run/README.md); the tasks not yet moved there are in the server README, and moving them is #609 | the Run door | the same guides through their index, [`run/README.md`](run/README.md), which the coding-agent guide (#611) links rather than repeats |
| **Direction**: decided, not built | its owning issue or record; direction nobody owns is recorded, dated, on [`architecture/direction.md`](architecture/direction.md) | the Develop door | not read |

## Authority

Two questions place a page. **What may it claim?** is authority, and
the seven classes below answer it. **Who is it for?** is audience,
and it decides only where a page is listed and how it is written:
**user-facing documentation** describes vinga to somebody running it
or talking to a device (the Run and Use doors, and the reference
section above), **working notes** are how this project thinks and what
it decided (the Develop door's architecture pages, research notes and
record).
Audience never settles authority. A working note does not outrank a
user-facing page by being a working note, and a page is not
authoritative for being written for the person running vinga.

Seven classes, covering every page under `docs/`, the three READMEs,
[`../AGENTS.md`](../AGENTS.md) and the changelog. The set is closed:
a new page joins one of these classes, or this list changes in the
commit that adds it. Some directories hold one class each and are
classified as directories; every other page is classified here rather
than by claiming a rank for itself.

**Product promises** are commitments to the person running vinga,
falsifiable from outside. Breaking one does not refactor vinga, it
changes what vinga is, and they outrank every other class here. Today
they are the three in
[`architecture/product-promises.md`](architecture/product-promises.md).

**Guidelines** are how the code keeps those promises. Any of them can
be revised given new evidence, provided the promises still hold:
[`architecture/guidelines.md`](architecture/guidelines.md),
[`architecture/design-guide.md`](architecture/design-guide.md),
[`architecture/cli-guide.md`](architecture/cli-guide.md), and
[`../AGENTS.md`](../AGENTS.md).

**Maintained maps and explanations** describe the system as it is now
and are corrected when it moves:
[`system-overview.md`](system-overview.md),
[`deployment.md`](deployment.md),
the whole [`run/`](run/README.md) directory (its index and one task
guide per page),
[`concepts.md`](concepts.md), [`glossary.md`](glossary.md),
[`architecture/observability-surfaces.md`](architecture/observability-surfaces.md),
the whole [`architecture/diagrams/`](architecture/diagrams/README.md)
tree (its index, each tool directory's own authoring guide, and the
diagram sources and renders they describe),
[`devices/`](devices/README.md), and the three READMEs: the
[project](../README.md), the [server](../vinga-server/README.md), and
the [firmware](../vinga-esp32/README.md). Such a page may summarize an
authoritative source and link it; it may not quietly become a second
one.

**Generated references** are rendered from the code and diffed by CI,
so they cannot come to describe a server this repository does not
build: [`reference/`](reference/), whole directory.
[`reference/cli.md`](reference/cli.md) is hand-written prose around
two generated halves and is held to the same rule, since what it says
the grammar is comes from the command tree. Correcting a generated
page means changing its generator.

**Decisions** are one immutable, date-prefixed record per decision
that was hard to reverse, surprising without context, and the result
of a real trade-off: [`adr/`](adr/README.md), whole directory. A
record is superseded by a later one, never edited into agreement with
the code.

**Dated execution records** report what was true when they were
written and are not rewritten when the code moves on:
[`plans/`](plans/) with their `-implementation` companions and
[`features/`](features/), both whole directories, plus
[`../CHANGELOG.md`](../CHANGELOG.md), which is the same thing in one
file, and
[`architecture/direction.md`](architecture/direction.md), which records
unowned decided direction with the date it was written down and
appends, never rewrites, when an issue or a record takes an entry.
They are evidence about a change, never current guidance.

**Research and field notes** are what was read, measured, or observed,
carrying the date and provenance that make them worth trusting:
[`xiaozhi-notes.md`](xiaozhi-notes.md),
[`related-projects.md`](related-projects.md),
[`conversational-quality-regression-suite.md`](conversational-quality-regression-suite.md),
and
[`architecture/cli-guide-audit.md`](architecture/cli-guide-audit.md),
the 2026-08-24 walk of four published CLI guides that the CLI guide's
practices were dispositioned from. A note is evidence: where one and
the guideline it fed disagree about the code today, the guideline is
the one that was corrected.
[`xiaozhi-notes.md`](xiaozhi-notes.md) is the mixed one and says so on
its own first screen: its protocol sections are maintained, and carry a
statement of which upstream commits and which observed firmware
versions they were last read against, while its reading of the upstream
server and its field observations keep their dates and are not chased.

Index pages carry no authority of their own, because they route
rather than claim: this page,
[`architecture/README.md`](architecture/README.md),
[`architecture/diagrams/README.md`](architecture/diagrams/README.md),
[`devices/README.md`](devices/README.md),
[`run/README.md`](run/README.md) and
[`adr/README.md`](adr/README.md) say where a thing is, and the page
they send you to is the one that says it.
[`architecture/principles.md`](architecture/principles.md) is one of
these too, and only that: the promises and the guidelines it used to
hold are now the two pages above, and the path stays because dated
records link it.

## Conventions

Documentation process, writing conventions, and the workflow these documents
follow are defined in [`../AGENTS.md`](../AGENTS.md).
