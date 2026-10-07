# vinga, the built-in default agent

Plan for [#612](https://github.com/rafacm/vinga/issues/612), a child of
epic [#615](https://github.com/rafacm/vinga/issues/615), replacing
[#21](https://github.com/rafacm/vinga/issues/21). Its companion is
`docs/plans/2026-10-06-vinga-built-in-agent-implementation.md`, one
section per milestone, appended in the same change that ticks it. It
builds on the browser client (`docs/plans/2026-10-06-browser-client.md`,
#613: try links, enrolment, the D4a refusal), the device record (#449),
the per-conversation prompt snapshot (#536), first-class conversations
and resumption (#190), and the three doors and current-only Use pages
(#609).

**Local baseline:** joins. The default agent of a fully local deployment
answers on the local stack: its prompt carries the board's facts and a
summary of the concepts, and the rest is reached with a built-in lookup
tool, measured on both local 8B models before the design was committed
(Gate). Membership is decided under
[the enumerated-baseline record](../adr/2026-09-12-the-local-baseline-is-enumerated.md),
which this line cites, and `docs/architecture/product-promises.md`
gains the list item in the same change that ships the lookup tool (M5).

**Cheapest alternative:** #21 as filed, a help agent bound beside the
operator's own. It is smaller, and it leaves a fresh deployment with no
agent of its own, the first conversation on a placeholder prompt, and
unbound devices reaching whatever the default is. Inside this plan every
part takes its cheapest working shape, priced in Q5 to Q7: a built-in
agent synthesized into the served configuration rather than a stored
row or a new config key; vinga's threads filtered by the existing
`conversations.device` column rather than a new owner; its memory pinned
to the existing device scope rather than a new scope; the board model
read from `DeviceFacts` in RAM rather than persisted; the Use pages
packaged as a committed, drift-checked copy inside the package rather
than a build step, an extra build context or a force-include across the
build root.

**Operator surface:** one new configuration key, `builtin_agent` (amended after plan review findings 3 and 4). A new command, `vinga device invite [--agent NAME]`, prints a single-use invite link and is the only thing that issues one; `vinga info` stops issuing links; the browser page moves from `/try/` to `/talk/`; `POST /api/runtime/try-links` becomes `POST /api/runtime/invites` (M1b, with an `Upgrade:` line). `builtin_agent` holds the
built-in agent's overrides (providers, voice, filler, fallback, memory,
and `prompt_includes`, which is how its language is set; it has no
`prompt` and no `mcp` field), read and written like `agent_defaults`,
with a `vinga builtin-agent` noun beside `vinga agent-defaults`; any
stored `agents.vinga` is an operator's agent; and the `agents` and
`default_agent` descriptions change, with `config.example.yaml`
following and the generated `docs/reference/domain-config.md` with
them. `default_agent` changes meaning: the agent a newly bound device
starts with, `vinga` when unset. `vinga device pending claim <code>`
takes its agent as optional; `vinga default-agent clear` returns to
vinga; `vinga info` names the default and says when the built-in is not
served; the claim body and the try-link refusal change in
`docs/reference/api-openapi.json`; one new event,
`builtin_agent_not_served`, in `docs/reference/events.md`. Concepts
(M3 onward, as each part ships): `docs/concepts.md` Agent, Binding,
Memory and Meta capabilities, and `docs/glossary.md` (vinga, default
agent). Guides: `docs/run/onboarding-a-device.md`,
`docs/run/security.md`, `docs/run/configuration.md` (overriding vinga),
`docs/run/configuration-api.md`, `docs/run/llm.md` (the gate's numbers
and the local model), `docs/run/with-a-coding-agent.md`, and the
README's Getting Started. Readiness: until #611's model exists, the
built-in's state is reported by the event and by `vinga info`, which is
where #611's check will read it. Device guides:
`docs/devices/README.md` (an unbound device always shows its code;
vinga on every bound device), `docs/devices/browser.md` (the D4a
paragraph goes; a cleared browser pairs). Three `Upgrade:` lines: M1
(boards that reached the default agent unbound will show pairing codes;
claim them with `vinga device pending claim <code>`), M3 (an agent
already named `vinga` keeps serving and holds the built-in back until
`vinga agent rename vinga <new>`), M6 (every bound device also reaches
vinga, and every agent on such a device is offered `switch_agent`).

**Attribution:** anthropic/claude-opus-5-5, thinking high (drafted with a Plan subagent of the same model and level); Claude Code 2.1.291; 2026-10-06.

## Goal

Every deployment starts with an agent worth talking to: vinga, composed
at runtime from the build it ships in, answering what the device in
front of you does, what vinga is and which command gets more of it, and
handing over to the other agents the device reaches. It is the default
agent unless the operator names another, it is reachable from every
bound device, its conversations and memory are the device's own, and it
works on the local stack. An unbound device gets pairing and nothing
else. The presets stop creating a placeholder `assistant`.

## Where this starts from

Verified at `c5b592e2` in the
[Step 0 comment](https://github.com/rafacm/vinga/issues/612), which this
plan answers point by point:

- Resolution has two homes: `DeviceBindings._bound`
  (`device/bindings.py`) and `Config.agents_for_device`
  (`config/models.py`), both "the bound list else `default_agent` else
  nothing". `Config.agents_for_device` has no caller outside the tests
  (`grep -rn agents_for_device src/` shows only its definition and two
  docstrings).
- `check_completeness` holds one rule: agents defined, no default
  agent, no device bound, refuse at boot.
- The store's claim refuses with `ALREADY_COVERED` while a default
  agent is set; enrolment refuses with `NOTHING_TO_ENROLL_ONTO`
  without one; try-link issuance refuses with `NO_DEFAULT_AGENT`
  (`onboarding/try_links.py`, `Issuer.issue`); the browser mint refuses
  with `TRY_LINK_NEEDED` while a default agent would admit it, and with
  `TRY_IDENTITY_UNAVAILABLE` when it cannot tell (`browser/router.py`,
  `try_identity`, D4a).
- `DeviceFacts` (`capture.py`) keeps `{firmware, board}` per MAC in a
  bounded LRU of 256, recorded by `ota.reply.check_version` for every
  check-in, bound or not; the session reads it for the capture
  manifest. `reported_board` strips `board.type` and answers `unknown`
  when absent.
- `threads.candidates` scans one agent's threads; the `conversations`
  table carries the session's `device` (a MAC). Memory scopes are
  `conversation`, `agent`, `device`; the model picks agent or device
  per `remember` call (`_fact_scope`), and `read_for_prompt` and
  `MemoryStore.recall` read both fact scopes.
- `BuiltinTools.snapshot` offers `switch_agent` when the device reaches
  more than one agent, and the memory family when `remembers()`.
- Every served-agent consumer reads `config.agents`: eight sites at
  `c5b592e2` by `grep -rn "config\.agents" src/` (`app.py` twice,
  `ota/reply.py`, `ota/poll.py`, `device/session.py`,
  `tools/mcp/slice.py`, `providers/world.py`, `config/diff.py`).
  `providers/world._stage_engine` raises when an agent's stage resolves
  through neither its entry nor `agent_defaults`.
- The image is built with `context: vinga-server`; the wheel
  force-includes `examples` only; the Use door is `docs/concepts.md`,
  `docs/glossary.md` and `docs/devices/*.md`, 118,470 bytes.
- Tool calls are recorded with a source from the closed set
  `TOOL_SOURCES = ("builtin", "device", "mcp", "unknown")`, a schema
  check constraint; a name in `names.BUILTIN_TOOL_NAMES` is `builtin`.
- No offline rename exists: `vinga agent rename` is an API act
  (`store.rename_agent`, which moves bindings, the default agent,
  agent-scope facts and threads in one transaction).
- Tests: `git grep -l default_agent -- vinga-server/tests | wc -l` is
  90 files; the three smoke seeds and the browser lane's `seed` set a
  default agent.

## Decisions, restated

From the issue, as Step 0 confirmed or amended them. Amendments are
marked and say which premise moved.

1. **A built-in agent named vinga**, composed at runtime from the build
   it ships in, never a stored record written once.
2. **The default agent of every deployment**; the operator can make
   another agent the default.
3. **Reachable from every device**, as the way back to the door.
   (Every *bound* device, since decision 9 leaves an unbound one
   nothing to reach.)
4. **Three kinds of answer plus the door**: this device (its guide,
   chosen by board model, or the browser's; an honest vague answer for
   a device with no guide), this system (from `concepts.md` and
   `glossary.md`, with the commands named rather than run), and the
   device's own MCP controls phrased as things to say; and handing
   over with the handover tool that exists.
5. **Its knowledge is the Use door packaged with the build.**
   *Amended (Step 0, premise 12):* packaged as a committed copy inside
   the package, derived from `docs/` and held byte-identical to it by a
   check in the census lane, rather than copied at image build time;
   the image's build context cannot see `docs/` (Q7). What vinga says
   still matches the server it runs in, because the copy is part of
   that build's source.
6. **It is held to current facts.** *Amended (Step 0, premise 7):*
   #609's check guards wording (no issue references, no decided
   direction on Run and Use pages), not facts. What keeps vinga honest
   is four things, none of them that check alone: its knowledge is the
   pages a reader reads, byte for byte (decision 5); every command
   those pages spell is already held to the registered grammar by the
   command-spellings census
   (`test_every_live_spelling_names_a_command_the_tree_has`, which
   sweeps every tracked file and classifies these pages `respell`), to
   which this plan adds one pin that they stay in that class (D10);
   #609's check holds their wording to current behavior; and behavior
   facts are held by the documentation footprint every plan names,
   with no mechanical guard, which this plan states rather than
   claims otherwise.
7. **It works on the local stack**: the prompt carries the board's
   facts and a concept summary, and the rest is a lookup tool, its
   shape decided by the gate.
8. **Its conversations and memory are scoped to the device.**
9. **The board model reaches the session**: from the OTA check-in, kept
   per MAC; the browser reports `vinga-browser`; a device whose check-in
   predates the process gets the vague answer until it checks in again.
10. **An unbound device gets pairing only, everywhere**: the activation
    section and no agent, no provider call; the devices map is always
    the allowlist; `default_agent` becomes the agent a newly bound
    device starts with; no localhost exception; recorded as an ADR,
    with an `Upgrade:` line naming `vinga device pending claim`.
11. **The presets stop creating `assistant`**: they configure providers,
    and vinga is the agent.
12. **Out of scope**: configuration by voice (#606). vinga names
    commands; it runs none.
13. **Browsers join by invite.** *Added 2026-10-06 by Rafael, outside
    the issue's text:* a browser is a permanent device, not a trial, and
    a household's own browsers (a parent's, a child's bound to a kids'
    agent) are meant to talk to a publicly deployed vinga. So the
    "try link" becomes an **invite link**, issued only by a command of
    its own, `vinga device invite`, which may name the agent the browser
    is bound to; `vinga info` reports and never issues; and the page
    moves from `/try/` to `/talk/`. Recorded on #612 in the same change
    that commits this plan. What the command makes exclusive is issuing
    a link that binds a browser *without* a code. A browser may still
    pair by code exactly as a board does (decision 10): the page mints
    an identity, shows the code, and nothing reaches an agent until the
    operator runs `vinga device pending claim`. That is the operator's
    consent, given per device, so M1 enabling it before M1b exists opens
    no admission path the operator does not act on.

## Open questions, resolved

**Q1. How a built-in agent exists in the configuration model.**
Synthesized into the served whole, `Config`, and never into the stored
half, `DomainConfig`.

- The name is one constant, `BUILTIN_AGENT = "vinga"`, in
  `config/models.py`.
- An after-validator on `Config`, ordered before `_check_domain`, puts
  an `AgentConfig` under `agents["vinga"]` built from the stored
  `builtin_agent` entry when there is one (else an empty layer), with
  `prompt=""` and `mcp=[]` pinned. It does so exactly when one pure
  function over a `DomainSnapshot`, `builtin_status(snapshot)`, answers
  `served`. Its closed set has two other answers, each with one
  decision site in that function: `displaced` (Q2: a stored
  `agents.vinga` exists) and `unprovided`
  (some provider stage resolves through neither the override nor
  `agent_defaults`). A private attribute set by the validator backs
  `Config.is_builtin(agent)`, true only for the synthesized entry.
- Why `Config`: all eight served-agent sites read `config.agents`, so
  vinga is built by `build_world`, servable to the OTA paths and the
  session, previewable at `GET /runtime/agents/vinga/prompt`, and
  compared by `config/diff.py`, with no call site changed. Why not
  `DomainConfig`: export, apply and every store write must go on
  meaning the stored rows; an export must never carry the built-in.
- `check_references` resolves names against
  `set(snapshot.agents) | {BUILTIN_AGENT}`, so `default_agent: vinga` and
  a binding to vinga are valid writes whether or not `builtin_agent`
  is stored or vinga is served, and `defined("agents", ...)` lists vinga.
  A binding to an agent not yet served is a state the store already
  allows between a write and an apply.
- `unprovided` does not refuse the boot. A fresh deployment boots empty
  and is configured over the API (Getting Started steps 2 and 3), and a
  deployment naming providers per agent with no `agent_defaults` would
  stop booting on upgrade. vinga is then simply not served, which the
  event and `vinga info` say (D6), and a device bound to it waits as a
  device bound to any unserved agent waits (`unloaded`).
- **Where the overrides live: `builtin_agent`, a key of its own.** It
  mirrors `agent_defaults` end to end: a one-row table created by one
  domain migration (`3005`), `store.read_builtin_agent` and
  `set_builtin_agent`, the key in the configuration document so export,
  import, apply and diff carry it, and a `vinga builtin-agent` noun
  with `agent-defaults`' verbs. Its model, `BuiltinAgentConfig`, is
  `AgentConfig` without `prompt` and `mcp`, so the persona and the
  grants are not refused on it: they cannot be written at all.
  "Mirrors `agent_defaults`" is an inventory, taken by
  `git grep -c "agent_defaults\|agent-defaults\|AgentDefaults" -- '*.py'`
  under `vinga-server/src` (15 files at `7e7caa5d`), and the new key is
  registered at each of those homes, which M3's implementation doc lists
  site by site:
  - `db/schema.py` and domain migration `3005` (the one-row table);
  - `config/models.py`: `DOMAIN_KEYS`, `DomainConfig`, `DomainSnapshot`,
    and `check_references`, which validates `builtin_agent`'s provider
    and fragment references at write time under `builtin_agent.*`
    whether or not vinga is currently synthesized (an `unprovided` vinga
    still refuses a misspelled provider in its override);
  - `config/store.py` (read, set, staged in import and apply);
  - `config/entities.py` and `config/cli/entities.py` (the descriptor and
    the `vinga builtin-agent` noun);
  - `config/views.py`, `config/responses.py` and `config/api.py` (the
    read, the write route and their OpenAPI shapes);
  - `config/diff.py` (`APPLIES`, and a response field of its own, so a
    pending override is visible in `vinga diff` before `vinga apply`)
    and `config/reload.py` (its status after an apply);
  - `config/cli/deployment.py` (`list`, `show` and `export`) and
    `config/docgen.py` (the generated reference).

  `providers/world.py` needs nothing: it reads the synthesized
  `config.agents`. M3 tests an invalid reference refused under
  `builtin_agent.*`, an export and import round trip carrying the key,
  and an override change visible as pending in `vinga diff` and then
  applied.
  Overloading `agents.vinga` as both an operator's agent and the
  built-in's overrides was the first draft; it needed a field heuristic
  to tell a legacy row from an override, and a blank legacy row would
  have silently become the built-in (plan review finding 3).
- **Providers, voice, language.** vinga inherits `agent_defaults` like
  any agent. `builtin_agent` overrides `llm`, `asr`, `tts` (the
  voice), `vad`, `filler`, `fallback`, `memory` and `prompt_includes`;
  the language is a shared fragment ("Always reply in Swedish.")
  included there, the mechanism `AgentConfig.prompt`'s description
  already points an operator at, and `prompt_includes: []` opts vinga
  out of fragments its siblings share.
- **No persona and no grants for the built-in.** The persona is the
  build's (Q10), and `BuiltinAgentConfig` has no `prompt` to carry
  another. vinga is appended to every bound device (Q3), so a grant on
  it would be a grant to every device; it has no `mcp` field, and
  `agent_defaults.mcp` is not inherited either (the pin), because an
  upgrade would otherwise hand the default grants to devices bound only
  to an agent that opted out with `mcp: []`.
- **A new `agents.vinga` is refused; an existing one is not.** Creating
  an agent named `vinga`, or renaming one to it, would displace the
  built-in by a write, so the store refuses it with a reason of its own,
  decided against the stored state before the write: a write that
  leaves an already stored `agents.vinga` as it was, or edits it, is
  the operator's agent being kept, and passes. That is what keeps an
  unchanged export of a displaced deployment applying back (plan review
  finding 4): apply's per-entry preparation sees an existing row, never
  a creation.

**Q2. The name collision.** A stored `agents.vinga`, whatever it holds,
a blank one included, is an operator's agent from before this change
(Q1 refuses creating one after it), and it **displaces** the built-in: it is served exactly as
before, under its name, with its memory and threads; the built-in is
not served (`displaced`) and is not appended to any device (Q3).
`builtin_agent_not_served` fires at boot and at every apply and
`vinga info` says so, both naming the remedy as a state the client
spells: `vinga agent rename vinga <new>`, then `vinga apply`. The
rename moves the bindings, the default agent, the agent-scope facts and
the threads in one transaction, so nothing of that agent's past is
lost, and the built-in appears at that apply.

Rejected, with reasons:

- **Refuse at boot**: the remedy is an API act and no offline rename
  exists, so a server that will not boot cannot be given it.
- **Treat the stored entry as the override**: the operator's persona
  would vanish without a word, and its MCP grants would ride the
  built-in onto every device.
- **Tell a legacy row from an override by its fields** (a non-empty
  `prompt` or `mcp` meaning legacy): a blank legacy row, which
  `AgentConfig` allows, would silently take the built-in's persona and
  lose its inherited grants (plan review finding 3). The overrides
  have their own key instead (Q1).
- **Rename by migration**: a data migration across the domain,
  conversations and memory chains, three Alembic chains with three
  advisory keys, to do what one existing verb does on request.

Two edges the `Upgrade:` line states: while displaced with no stored
`default_agent`, the effective default `vinga` names the operator's
agent, so a claim binds to it; and deleting that agent instead of
renaming it leaves its agent-scope facts unread (the built-in reads no
agent scope, Q5) and its threads findable by the built-in only on the
device they were held on.

**Q3. Reachable from every device.** A device's agents in one world are
the bound names that world serves, in binding order, followed by vinga
when the device has any binding at all, the world serves the built-in,
and the binding does not already name it. An unbound device reaches
nothing. A conversation starts on the first entry, so an operator's
agent keeps opening conversations on the devices bound to it, and a
device claimed onto the default vinga opens on vinga. `switch_agent` is
offered by the rule that exists (`BuiltinTools.snapshot`, more than one
agent), so it now appears on every bound device of a world serving
vinga, offering the device's list; that is the way back to the door,
and no new tool.

The rule has one home and both callers derive from it:

- `Config.bound_to(mac) -> tuple[str, ...]`: the snapshot's binding (a
  record's agents, or nothing), M1.
- `Config.reachable_from(bound) -> tuple[str, ...]`: the rule above,
  M6.
- `DeviceBindings._bound` returns names only, from the stored row or
  `config.bound_to`; `BoundNames.against(config)` answers
  `DeviceAgents(config.reachable_from(names), unloaded, authoritative)`;
  `Config.agents_for_device(mac)` is
  `list(self.reachable_from(self.bound_to(mac)))`.

The append is a fact about a world (does it serve the built-in), so it
belongs where a world is classified, `against`, which the bindings
docstring already makes the caller's single classification against one
generation. `against` therefore takes the `Config` rather than its agent
names, and its three callers (`ota/reply.py`, `ota/poll.py`,
`device/session.py`) pass `generation.config`. The displaced case falls
out of it: a world whose `vinga` is an operator's agent is not serving
the built-in, so that agent is never appended to a device that did not
bind it. Writing vinga into every stored binding was priced and
rejected: a second structure that must agree with the rule, a
migration of every binding, and an operator able to unbind it.

**Q4. Pairing only.** Every site Step 0 named, and what each becomes:

- `DeviceBindings._bound`: the bound list and nothing else. The live
  read stops reading the default row: `read_live_binding`,
  `_live_binding` and `read_live_attachment` drop it and
  `LiveBinding.default_agent` goes; the byte pin in
  `tests/unit/test_live_binding_pin.py` moves in its own commit, a
  deliberate behavior change rather than a reshape.
- `Config.agents_for_device`: no fallback; derived as in Q3.
- `check_completeness`: its rule goes, because a default agent no
  longer reaches any device; a deployment with agents and no devices is
  one awaiting its first claim. The function goes with it if it holds
  no other rule, checked by grep.
- `store.claim_device` / `_device_write(unconfigured=True)`:
  `ALREADY_COVERED` goes. The agents become optional: none named means
  the default agent, read inside the same transaction, the way
  enrolment reads it; until M3, with no default set, the existing
  `NOTHING_TO_ENROLL_ONTO` sentence answers.
- `config/api.py` `add_device` (`POST /devices/pending/{code}`): a body
  model of its own with `agents` optional, so `PUT /devices/{mac}`
  keeps requiring them.
- The CLI: `_bound_by_code` makes `AGENT` optional, a payload group of
  zero or more, which the CLI guide's homogeneity rule allows; its help,
  `default-agent set` and `clear` help, `OTA_URL_GUIDANCE`
  (`cli/local.py`) and `MAY_NOT_SPEAK` (`cli/simulator.py`) are
  reworded.
- `ota.reply.token_for` and `onboarding/unbound.activation_for`: logic
  unchanged (no agents, no token; nothing bound, a code), docstrings
  corrected.
- `browser/router.try_identity`: both refusals go and it always mints;
  the module docstring's D4a paragraphs go, and so do the branches in
  `browser/static/page.js` and `identity.js` that show them.
- `config/entities.py`: `DEFAULT_AGENT_UNSERVED_NOTICE` says what a
  default agent is now (the agent a newly claimed device starts with)
  and applies at reload only, since no device's check-in changes;
  `RENAME_UNSERVED_NOTICE` loses "or by the default agent"; the
  `default_agent` setting's notes, `DOMAIN_DESCRIPTIONS["default_agent"]`
  and the store's `_NOT_AN_AGENT_NAME` follow.
- The smoke seeds (`tests/smoke/seed*.sh`) bind the smoke MAC rather
  than set a default; `tests/smoke/serve.sh`'s comment loses the rule.
- Try links: unchanged in M1, since a default may still be unset.
  From M3 the default always exists: issuance's `NO_DEFAULT_AGENT`
  becomes `DEFAULT_AGENT_NOT_SERVED` (D5), and the claim's no-default
  arm and `NOTHING_TO_ENROLL_ONTO` go.
- `vinga device bind <mac>` keeps requiring an agent: it is also the
  rebind verb, where an omitted agent could mean the default or a
  mistake.
- No localhost exception, for the issue's reason. With
  `server.onboarding.enabled: false` an unbound device gets neither a
  code nor a token, and is bound by MAC.

**Q5. Device-scoped conversations and memory, priced.** One predicate
decides both, `Config.is_builtin(agent)`; the pipeline reads it for the
prompt's memory read, and `BuiltinTools` gets it as one more callable
beside `remembers`, answering for the current reply's world.

- **Threads, by the existing column.** `threads.candidates(connection,
  agent, description, device=None)` adds
  `conversations.c.device == device` when given; `ThreadReads` and
  `ThreadSearch` carry it; `Resumption.described` passes the session's
  MAC for the built-in. `Backlog` answers its device, and
  `Resumption._backlog` refuses a mismatch as it refuses another
  agent's thread, defense behind the offer gate. Whether the filter
  needs an index is measured, not argued: for the built-in the agent's
  threads are the whole deployment's, so M3 times the device-filtered
  search on a seeded store of 50 devices with 200 vinga threads each
  and adds a composite `(agent, device, last_active_at)` index by a
  conversations migration if the search exceeds 50 ms on agentpi,
  recording the number either way. Rejected: an owner string
  such as `vinga@<mac>` in the agent column, which breaks rename,
  listing and every query keyed on the agent's name.
- **Memory, pinned to device scope.** For the built-in, `remember`
  writes device scope and its schema loses the `scope` property (a
  shorter tool for an 8B model); `update_memory`, `forget` and
  `restore_memory` search device scope only (`_reachable`); `recall`
  reads device scope only; `MemoryStore.read_for_prompt` and
  `MemoryStore.recall` take the agent scope as optional, said with
  None as both already say an unidentified device and a missing
  conversation. Rejected: a new `vinga per device` scope (a migration
  of the memory chain's check constraint and a new member of the
  events' closed set) and the owner-string encoding above.
- **What device scope shares**: the device block every agent on that
  device reads, which the `remember` tool's own description promises
  ("every assistant on this device then knows"). What vinga is told on
  a device, the operator's agents bound to the same device read, and
  the other way round. Acceptable: the issue's boundary is the device;
  agents on one device serve one place for one operator, which is what
  device scope is for; and the leak the issue closes, one device
  recalling or resuming what was said on another, stays closed.
- After a board swap (#449, M4) device facts move with the record and
  vinga's threads stay under the old MAC; accepted and stated.

**Q6. The board model.** Read from `DeviceFacts`, in RAM, captured once
when the session opens. Persisting it was priced: a table of observed
facts written from an unauthenticated endpoint (a migration, a write
per check-in, and a bound to keep strangers' MACs out) against a vague
answer for a board that was running when the server restarted, until
its next boot (stock firmware checks in at boot; the browser checks in
at every start). RAM wins; reopen if field use shows the vague answer
is common.

The mapping is derived from the packaged guide filenames, not
tabulated, and it searches only the **board guides**: the packaged
`devices/*.md` pages other than the two that are not about one device,
`README.md` (the common page) and `flashing.md` (the flashing
procedure). That set is one constant beside the matcher, its exclusions
named, so a new device guide joins it by existing and a new non-guide
page is a decision rather than an accident. A reported type,
casefolded and stripped, names the board guide whose stem equals it or
equals `waveshare-` plus it, so
`esp32-s3-touch-lcd-1.54` and `waveshare-esp32-s3-touch-lcd-1.54` both
reach the LCD guide; `vinga-browser` reaches `browser.md`. An absent
type, `unknown`, or a type with no guide gets the fixed vague text
(D3). The reported string never enters the prompt: only a guide's text
or the fixed text does, since `board.type` is a string an
unauthenticated request chose. M4 reads the string a real
ESP32-S3-Touch-LCD-1.54 reports off `vinga events` (`ota_check`'s
`board`) and records it in the implementation doc.

**Q7. Packaging the Use pages.** A committed copy at
`vinga-server/src/vinga_server/knowledge/pages/` (`concepts.md`,
`glossary.md`, `devices/*.md`), byte-identical to the sources, written
by `uv run python -m tests.census.test_packaged_pages` and checked by
that module's `test_the_packaged_pages_are_the_tree` (same file set,
same bytes). The proportion test:

- **A hatch force-include of `../docs`** reaches outside the build
  root: the image's context (`vinga-server`) cannot see it, and a wheel
  built from an sdist loses it.
- **A build step that copies** must be remembered by every builder:
  the CI step, the two documented `docker build` commands
  (`docs/contributing.md`, `docs/run/upgrading.md`), the
  `uv tool install git+...#subdirectory=vinga-server` Getting Started
  uses.
- **An additional build context** fixes Docker only and still needs
  one of the above for the wheel.
- **The committed copy** needs no build change at all, so the wheel
  the browser lane installs, the image and the git install all carry
  it; it costs 118 KB in the tree and a regenerate command when a Use
  page changes, the discipline the two census manifests already have.

The check lives in the census lane because that lane runs in both
workflows, and a Use-page edit runs only `docs.yml`. A wheel-level
assertion joins `tests/integration/test_cli_wheel.py`: the installed
wheel's `knowledge` package lists the same pages.

**Q8. The lookup tool: module, interface, shape.** The module is a new
package, `vinga_server/knowledge/`, importing nothing beyond the
standard library (so `config/models.py` may reach it without breaking
#143's weight pin):

- `pages/`, the copy (Q7); `persona.md`, the hand-written persona
  (D1).
- `persona() -> str`: the persona followed by the concept summary
  (D2).
- `board_facts(board: str | None) -> str`: a guide's facts or the
  vague text (Q6, D3).
- The lookup itself, per the gate: **`search(query) -> Answer`**, the top
  three sections (shape A); the `topics()` and `read(topic)` shape
  measured worse on every model and is dropped. An
  `Answer` is text bounded to a fixed character budget (D4).

What its callers stop knowing: where the pages live and that they are
copies, how a page splits into sections (by `##` heading, titled
`<page title>: <heading>`), how a board-type spelling maps to a guide,
how results are scored (token overlap over title and body, the
normalization `threads.candidates` uses, written here rather than
imported from the conversations package), and how a result is bounded.
It loads once per process, behind a cached reader rather than a
composition field: it is immutable package data, and a field would be a
seam with nothing to inject.

The tool is a builtin: its name(s) join `names.BUILTIN_TOOL_NAMES`, so
a call is recorded with source `builtin` and `TOOL_SOURCES` (a schema
check constraint) does not move. Its definition and executor sit in
`tools/builtin.py` with the others, delegating to `knowledge`, and
`BuiltinTools` offers and dispatches it only where
`Config.is_builtin(agent)`; a call from any other agent is answered
`no_such_tool`, as a withheld memory tool is. A separate `ToolSource`
was considered and rejected: two sources would both own the builtin
namespace that `BuiltinTools.owns` claims whole.

**Q9. Presets.** No agents and no default agent: providers and
`agent_defaults` only, so vinga is the agent; the comments say to claim
a board's code. `config.example.yaml`'s domain comments, the
Getting Started document and `examples/README.md` follow, and
`config.deploy.example.sh`, a real deployment's profile rather than a
preset, keeps its agent. The model ambiguity (`qwen3:8b` in the
preset, `llama3.1:8b` in Getting Started) is decided by the gate: the
preset and Getting Started name the model that measured better, and
`docs/run/llm.md` carries the numbers.

**Q10. The prompt.** Composed by the assembler that composes every
prompt:

- `Config.prompt_for_agent`, "the only source" of a persona, answers
  `knowledge.persona()` for the built-in and the stored prompt for
  every other agent. The pipeline's `_activate_agent` and the preview
  route both get vinga's persona from there, with no branch of their
  own.
- Board facts are a fact about the device a session speaks through, so
  they join the device block (`runtime/prompt.with_scopes`,
  `_device_block`) after `device_introduction` and before the notes,
  under the block's one `device` provenance. That keeps the prompt
  module's rule that there is one device section, and puts the
  per-board text last, so the static persona, summary and fragments
  are a prefix shared by every vinga session that a runner's prompt
  cache can hold. `with_scopes` gains an optional `board` text, empty
  for every agent but the built-in, so an operator agent's prompt is
  byte-identical to today's.
- The operator's providers, voice and language apply through
  `builtin_agent` (Q1): providers by stage, voice by `tts`, language by
  an included fragment, injected after the persona as every fragment
  is.

**Q11. The invite link (decision 13).** One milestone, M1b, after M1
and before the built-in exists, because it reshapes the issuance and
redemption M3 then extends.

- **The command.** `vinga device invite [--agent NAME]`: noun first
  under the existing `device` noun, beside `device bind` and
  `device pending claim`, per `docs/architecture/cli-guide.md`; no
  positional, since nothing is addressed. It prints one link on stdout
  and nothing else there, so `$(vinga device invite)` is the one way a
  script holds a link without printing it. `--agent` is repeatable, as
  `device bind`'s agents are, and binds the browser to exactly those
  agents; omitted, the browser is bound to the default agent.
- **`vinga info`** loses the link line, its two `Act` fields
  (`completes`, `declined`) where nothing else uses them, and the
  try-link refusal printed in its place; it reports and issues nothing.
  The coding-agent guide's `grep -v '/try/#'` filter goes with it, and
  its browser step becomes "the person runs `vinga device invite`".
- **The API.** `POST /api/runtime/try-links` becomes
  `POST /api/runtime/invites` with an optional `agents` list in the
  body; issuance refuses, nothing issued, when a named agent does not
  exist, with the store's existing unknown-agent reason, and when one
  is not served by the current world (the same check D5 makes for the
  default). The agents travel with the token in the in-memory store, so
  redemption binds to what issuance checked, re-read inside redemption's
  one transaction.
- **Names.** `onboarding/try_links.py` becomes `onboarding/invites.py`,
  `TryLinks` becomes `Invites`, the refusal reasons and sentences say
  "invite"; one vocabulary, not a renamed command over a try-link
  module. `BROWSER_MOUNT_PATH` (`config/models.py`) becomes `/talk`,
  which moves the page, its static routes and the `server.ota_path`
  reservation together, since all three read that one constant.
- **No compatibility shims.** vinga is unreleased (the pre-release
  stance): the old path and route answer the stock 404, a browser
  already enrolled keeps its identity (it stores the onboarding path,
  not the page path) and opens `/talk/` from then on, and the fragment
  `Upgrade:` line says so.
- **What stays.** Single use, ten minutes, the fragment-carried token,
  the same-origin redeem, the restart ending outstanding links, the
  32-link bound, `Browser <mac>`: the security shape #613's reviews
  settled does not move.

## Gate: the lookup tool's shape

Measured on 2026-10-06 and 2026-10-07 on this machine (a Raspberry Pi 5,
16 GB, CPU only, Ollama 0.35.1), before M5 is designed. The harness, the
frozen question set, every raw run, the hand-check and the full write-up
are kept outside the repository with the session's working files
(`epic-615.local/612-gate/`, `RESULTS.md`); what the plan needs from
them is here.

- **Question set:** 32 questions, frozen before any model call
  (sha256 `1442b569af5c90810eec945ab3d459a3337ec811030422fd110011d9d415e181`).
  16 about the device (9 for the LCD-1.54 board, 4 for the browser, a
  three-turn follow-up), 11 about the system, 2 device commands, 3 the
  pages cannot answer. 15 need a lookup, 12 are answerable from the
  prompt, 2 are device-tool calls, 3 should be declined. Each carries
  the key facts a correct answer must contain, quoted from the pages
  with their line.
- **Prompt:** the design's: who vinga is, the LCD-1.54 board's facts
  (D3), the concept summary (D2), the rule to look up rather than
  guess, and one device tool (`self_audio_speaker_set_volume`).
- **Scoring:** automatic, then every one of the 419 answers read in full
  (177 automatic verdicts overridden, each with a note). Hallucination
  is a per-answer flag: a confident claim the pages do not support.
- **Stability:** `llama3.1:8b`, shape A, run twice: 0 of 32 answers
  changed category (byte-identical at temperature 0 and a fixed seed;
  determinism, not robustness to rephrasing).

| Model, shape | Correct | Hallucinated | Declined (of 3) | Looked up when needed (of 15) | Device command (of 2) | Median s per question | p90 s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Gemma 4 e4b, A `search` | 53% | 9% | 3 | 11 | 1 | 9 | 69 |
| Gemma 4 e4b, B `topics`+`read` | 44% | 12% | 3 | 1 | 2 | 7 | 23 |
| Gemma 4 e2b, A | 50% | 19% | 3 | 10 | 2 | 6 | 36 |
| Gemma 4 e2b, B | 41% | 12% | 3 | 1 | 2 | 4 | 7 |
| `llama3.1:8b`, A | 47% | 16% | 3 | 14 | 1 | 117 | 185 |
| `llama3.1:8b`, B | 38% | 31% | 2 | 15 (11 guessed topics that do not exist) | 1 | 75 | 99 |
| `qwen3:8b`, thinking off, A | 34% | 34% | 2 | 0 | 1 | 27 | 38 |
| `qwen3:8b`, thinking off, B | 34% | 28% | 3 | 0 | 1 | 26 | 39 |
| `qwen3:4b-instruct`, A | 41% | 31% | 3 | 0 | 2 | 15 | 23 |
| `qwen3:4b-instruct`, B | 41% | 34% | 3 | 0 | 1 | 14 | 20 |

Not complete, reported and left out of the comparison: Gemma 4 12B
(6 of 32, about 100 s per answer without a lookup); `qwen3:4b` (7 of
32, its thinking cannot be turned off and streams into the reply);
`qwen3:8b` with thinking on, as the preset runs it (a six-question
subset: three passed the 360 s cap, the first round alone 94 to 238 s).

**What it shows.**

- **Shape A beats B on every model.** In 192 shape-B runs no model
  called `topics()` once: they guessed a title, met "no such topic",
  and answered anyway.
- **The prompt-carried board facts work.** On the 12 questions the
  prompt answers, the small models got 11 or 12 right, in 2 to 15 s.
  Device questions need no lookup.
- **The preset's model fails the design.** `qwen3:8b` never looks up
  with thinking off, and a lookup turn passes six minutes with it on.
  `llama3.1:8b` looks up but takes a median 117 s per question. What
  separates the models is tool behavior, not size.
- **Retrieval is the next limit.** Measured with no model, term-overlap
  search put the right section in its top three for 22 of the 39
  queries the models actually sent (23 of 39 scoped to the current
  board's pages).
- **Latency after a lookup exceeds the watchdog on this hardware.** The
  reply's first token after a lookup came at a median 23 s (e2b) or
  44 s (e4b), against the 10 s first-token watchdog and the 30 s read
  timeout.

**Verdict: fails as written; passes only with the mitigations below,
which M5 must demonstrate before it ships.**

- **Shape: A**, `search(query)` returning the top three sections. B is
  dropped. This fills Q8's interface line.
- **Default local model: Gemma 4 e4b** (`gemma4:e4b`), replacing
  `qwen3:8b` in the local preset and `llama3.1:8b` in Getting Started
  (Q9, M7). It is the most accurate configuration measured and ten times
  faster than either 8B model on this Pi. That is worth having whatever
  M5 concludes, since the same preset runs every local agent.
- **M5's own gate:** before the lookup tool ships, retrieval is improved
  and measured with no model (target: the right section in the top three
  for at least 32 of the 39 recorded queries), then Gemma 4 e4b, shape
  A, is re-run on the frozen set and must reach **at least 70% correct
  and at most 10% hallucinated**, with a second run on rephrased
  questions. The latency after a lookup gets a holding phrase (vinga's
  filler) and its own first-token allowance on the lookup round, and
  the watchdog's interaction with it is tested.
- **If M5's gate is not met,** vinga ships on the local stack without
  the lookup tool. It answers from its prompt (the board's facts and the
  concept summary, which the gate shows works) and says that deeper
  questions need a larger model. The local-baseline item then covers
  device questions and the summary, and says so. On a vendor model the
  lookup is offered as designed.

This is a decision about the local baseline, so it is recorded for
Rafael on #612 with these numbers, and the baseline item in
`product-promises.md` is written only in M5, from the gate M5 meets.
**M5 and M7 do not start until Rafael confirms it** (plan review round
2, finding 3): the issue named the local preset's 8B model and a lookup
for everything beyond the prompt, and the fallback changes what the
local stack promises. Rafael asked on 2026-10-06 for a more modern
model than the two 8B ones to be measured, which is how Gemma 4 entered
the gate; the fallback is new and is his to accept. M1 to M4 and M6 do
not depend on it.

## Smaller decisions

**D1. The persona.** `knowledge/persona.md`, hand-written, short: vinga
is the built-in agent and the way to the rest; it answers about this
device, about vinga, and names commands rather than running them; it
hands over to the device's other agents with the handover tool; it
replies speakably (one or two sentences, no lists, no markdown) in the
language the person spoke; it says plainly when the pages do not cover
something rather than guessing; it says configuring vinga by voice is
not something it can do and names the command instead. It states no
behavior fact the pages own; a command it names is held by the census
like any tracked file's. M3's persona does not mention the lookup tool,
which M5 adds with the sentence about it.

**D2. The concept summary is the page's own.** The section "The model
in one paragraph" of the packaged `concepts.md` (1,529 characters at
`c5b592e2`), extracted at runtime, so there is no second copy. A test
asserts the heading exists, so renaming it fails a test rather than
silently emptying vinga's summary.

**D3. Board facts and the vague text.** A guide's facts are its lead
(the text before its first `##`) and its `## Controls` section,
verbatim: 1,807 to 3,161 characters across the four board guides at
`c5b592e2`. A test holds every board guide (Q6's set) to having both and
to a budget of 3,500 characters, and the matcher is tested against that
set and against its two exclusions: `readme`, `devices/readme`,
`flashing` and `waveshare-flashing` reported as a board type each get
the vague text, never the page, so a guide that grows past it fails a test
and grows an "At a glance" section rather than silently inflating every
vinga prompt. The vague text says the server has not been told which
board this is, that the answer should come from the common page
(`docs/devices/README.md`, a lookup away), and that restarting the
device lets the server learn it.

**D4. Lookup results are bounded.** A fixed character budget per
answer, a constant measured in the gate (the column "Prompt
characters" includes a typical answer), cut at a section boundary with
a line saying more exists. Nothing scoring is an answer, not a
refusal: it says the pages do not cover it, which the persona tells the
model to repeat honestly.

**D5. Try-link issuance refuses only when the default is not served.**
From M3 the effective default always exists, so `NO_DEFAULT_AGENT` is
replaced by `DEFAULT_AGENT_NOT_SERVED`, its decision site issuance,
comparing the effective default with the current world's agents:
Getting Started's step 2 runs `vinga info` before any provider exists,
and a printed link that binds a browser to an agent nobody serves would
be a link that cannot work. The `RefusalReason` member is renamed, not
added beside the old one. An older CLI meeting the new token quotes the
server's sentence, the client's existing rule for an unknown token,
which M3 verifies.

**D6. Saying the built-in is not served.** One event,
`builtin_agent_not_served` (warning), with `reason` from the closed set
`displaced | unprovided` and, for `unprovided`, `stages` from the
closed set of provider stages; it quotes no operator text. It fires
once per installed world where `Generations` takes its first
generation and where `_install` installs a later one. `vinga info`
reads the status live: `GET /api/runtime/info` composes everything
else once at startup, as a fact of the process (`config/api.py`,
`read_runtime_info`), so the built-in's status is the one field that
route computes per request, from the installed generation
(`comp.generations.current().config`, through `builtin_status`), and
the response model says which of its fields are live. That keeps one
route for `info` rather than a second read the client must combine, and
the client restates no rule; `info` prints the default as
`vinga (built in)` when unset, and the status when it is not `served`.
M3 tests it across applies on one running server: `served`, then a
stored `agents.vinga` and an apply make `info` answer `displaced`,
then a rename and an apply `served` again, and clearing the providers
`unprovided`.

**D7. `default-agent clear` means vinga.** The row is deleted as today;
an unset default and `default-agent set vinga` mean the same thing, and
both are allowed.

**D8. A claim names the agent it bound.** The acknowledgement is built
from the row, as every device write's is, so `vinga device pending
claim 418293` answers which agent the board now starts on.

**D9. Changelog fragments per milestone.** `changelog.d/612-<slug>.md`,
one per milestone that changes what an operator or a person at a device
meets; M2 writes none, since no deployment behaves differently.

**D10. The census pin.** One test in
`tests/census/test_command_spellings.py` asserts every packaged page
and its source classify `respell`, so a future edit to
`_HISTORICAL_PATHS` cannot exempt vinga's knowledge from the live
grammar unnoticed. The copies need no classification of their own: they
carry the same invocations in the same class, so the distinct-pair
manifest does not move.

## Module layout and design footprint

- `knowledge/` (new package): the packaged Use door, its sections, the
  board-guide mapping, the concept summary, the persona, and the
  lookup. Callers stop knowing where the pages are, how they split, how
  a board spelling maps to a guide, and how a result is scored and
  bounded.
- `config/models.py` (deepened): the built-in's name, its synthesis and
  status, `is_builtin`, `bound_to`, `reachable_from`, the reference rule
  that the name always resolves, and `prompt_for_agent` answering the
  persona. The one home of "which agents may this device reach".
- `device/bindings.py` (deepened): names only, and `against(config)`
  classifying against one world, append included.
- `config/store.py` (deepened): the claim without `ALREADY_COVERED` and
  with an optional agent; `builtin_agent` mirroring `agent_defaults`;
  the refusal to create or rename to `agents.vinga`; the effective default in claim and enrolment.
- `tools/builtin.py`, `tools/source.py` (deepened): the device-only
  memory family and the lookup tool, offered by one predicate.
- `memory/store.py`, `conversations/threads.py`,
  `runtime/resumption.py` (deepened): an optional agent scope, an
  optional device filter.
- `runtime/prompt.py` (deepened): board facts inside the device block.
- `runtime/pipeline.py`, `device/session.py`: the board read once at
  open and handed to the snapshot read; the predicate handed to the
  tools.
- `browser/router.py` (shallowed): the mint loses its two refusals.

No new seam: vinga is an agent like any other behind
`device/boundary.py`, and nothing at the device edge knows it is built
in.

## Tests

Reused throughout: `tests/support/configs.py` (`config_with_agent`,
`base_config`), `RecordingLlm` and `llm.systems` for what a prompt
sent (`tests/support/providers.py`, `tests/unit/test_session_prompt.py`),
the session builders in `tests/support/sessions.py`, the store fixtures
of `tests/unit/test_config_store.py`, `tests/unit/test_device_bindings.py`,
`tests/unit/test_onboarding_activation.py`, `tests/unit/test_ota.py`,
the try-link suites, the census lane, the browser lane, and the local
lane (`tests/local/`) for real models.

- **The helpers move first (M1).** `config_with_agent` and
  `base_config` bind `DEVICE_MAC` explicitly beside their default
  agent, so the suites that leaned on the fallback keep their meaning
  without each being edited. The set that still fails after the rule
  changes is the inventory, from a full run with `-ra` (never `-rf`),
  recorded in the implementation doc, and each is either rebound or
  rewritten to assert pairing. `BOUND_MAC`'s comment loses the rule.
- **Both homes, one test.** The pairing rule and, in M6, the append are
  asserted through `DeviceBindings` with a database and through
  `DeviceBindings.snapshot_only`, parametrized, so a mutation in either
  arm fails.
- **Sentinels.** A board type shaped like an instruction and a
  credential is planted at a check-in and asserted absent from
  `llm.systems`, the session's state, every log line and event field
  M4 adds, and both log formats outside the two surfaces that already
  carry it by design: `ota_check`'s bounded `board` field and the
  DEBUG `ota_check_body` event, both untrusted device descriptors this
  plan does not change (the second is an open follow-up of its own).
  The test asserts those two still carry exactly what they carried,
  so the exception is pinned rather than assumed (M4). A lookup query
  carrying a credential-shaped string is asserted absent from both log
  formats and every event field. It may appear only in the two content
  surfaces: the conversation record, and the tool-argument field of the
  LLM-input telemetry span, which exists only when LLM input export is
  switched on (`runtime/pipeline.py` stages tool arguments for it, and
  the event catalog documents that field as content). The test runs
  with export off, where the span carries no arguments, and with it on,
  where the query is in that field and still in no log line or other
  event field (M5). `builtin_agent_not_served` is
  asserted to carry only its closed-set tokens (M3).
- **Pins.** The live-binding statement pin moves in its own commit
  (M1). An operator agent's assembled prompt is pinned byte-identical
  across M3 and M4 (`tests/unit/test_session_prompt.py`), since the
  device block gains text only for the built-in.
- **Mutation targets**, each named with the test that catches it and
  run once (straight-line logic):
  - M1: restoring the `else default` arm in `_bound`, or in the
    snapshot read; restoring `ALREADY_COVERED`; restoring D4a's
    refusal.
  - M2: one byte of a copy changed; a guide added to `docs/devices/`
    without its copy; `docs/devices/` added to `_HISTORICAL_PATHS`.
  - M3: dropping the `mcp` pin (a test grants `agent_defaults.mcp` and
    asserts vinga's snapshot offers none of its tools); answering
    `served` for a legacy row; passing both fact scopes for vinga (a
    fact told on device A must not reach device B's prompt or
    `recall`); dropping the thread filter (a thread on A must not be
    offered on B); dropping the backlog's device check (driven through
    `Resumption` with an offer forged by a second device's search, not
    by a reach-in).
  - M4: mapping only one LCD spelling; interpolating the reported type.
  - M5: offering the tool to every agent.
  - M6: appending by name regardless of whether the world serves the
    built-in, caught by the displaced case (a device bound to `kids`
    must not reach an operator's agent named `vinga`).
- **The browser lane.** M1: the pairing case stops deleting the default
  agent, since a cleared browser now pairs with one set; it claims with
  an empty body and asserts the record is bound to the lane's default
  agent. M3: the seed's mock `agent_defaults` make vinga served; the
  lane keeps its own agent as the default, so the existing cases are
  unchanged, and one case clears the default, redeems a try link and
  asserts the browser is bound to `vinga` and is answered. M6: sessions
  reach `[assistant, vinga]`; the tool case is unaffected, since its
  scripted call names a device tool.
- **The gate, reproducible from the repository (M5).** M5 commits the
  gate's inputs as fixtures under `vinga-server/tests/local/lookup_gate/`:
  the frozen 32-question set with its expected facts and their page
  lines, the rephrased set M5's second run uses, the 39 queries the
  models actually sent, and the scorer as a module whose categories
  (correct, partial, hallucinated, tool-use error, honest decline) are
  the gate's. Two tests read them: a unit test with no model asserts
  retrieval puts the right section in the top three for at least 32 of
  the 39 queries; and an opt-in local-lane case runs a real model over
  both sets through the real tool and asserts the pass bar (at least
  70% correct, at most 10% hallucinated, every device command a call).
  Raw model output stays uncommitted; the hand-check step is replaced
  by the scorer's rules, with any case it cannot decide reported for a
  person rather than counted.
- **Presets (M7).** An integration case imports each preset into a
  blank database, boots, and asserts the served agents are exactly
  `vinga`, no default row is stored, and a claimed device starts on
  `vinga`.

## Risks

- **Boards that reached the default agent unbound start showing
  codes** (M1). Mitigation: the `Upgrade:` line names
  `vinga device pending list` and `vinga device pending claim <code>`,
  and claiming with no agent binds the board to the default it was
  already reaching, so the change costs one short command per board; a
  board bound by MAC keeps working unchanged.
- **An operator agent named `vinga`** (M3). Displaced, not broken
  (Q2): it serves as before, and the event and `vinga info` name the
  one-command remedy, which keeps its memory and threads.
- **Providers only per agent** (M3). vinga is `unprovided`, not a boot
  failure; the event names the missing stages.
- **An 8B model on a Pi is not a conversation**, as `docs/run/llm.md`
  measured: about 9.5 s per tool round for `qwen3:8b` without
  thinking, 15 to 42 s for `llama3.1:8b`. The lookup adds a round.
  Mitigation: board facts are in the prompt, so device questions need
  no round; the static part of the prompt is a shared prefix the
  runner can cache; the gate records time to first spoken word and
  `docs/run/llm.md` carries it; the baseline promises function, not
  latency (rule 2 of the baseline record). The Pi is where reliability
  is measured, not the latency target.
- **The tool list is long for an 8B model**: up to thirteen tools for
  vinga. Mitigation: the gate measures with the real list; the
  device-only `remember` drops a parameter.
- **Every bound device gains `switch_agent`** (M6), including those
  whose agent runs on a small local model. Mitigation: M6 reruns
  `tests/local/test_tool_calling_for_real.py` with the extra tool and
  records the result; the `Upgrade:` line says so.
- **The copy drifts from the pages.** The census lane fails in both
  workflows, naming the regenerate command, which AGENTS.md lists
  beside the two manifests'.
- **The pages state a wrong fact.** No mechanical guard (decision 6);
  the footprint discipline and the board guides' hardware checks are
  what hold them, and a board with no guide gets the vague answer
  rather than a borrowed one.
- **Check-in floods evict board facts.** `DeviceFacts` is a bounded LRU
  any unauthenticated request can push; the worst case is a vague
  answer, never a wrong one.
- **A new builtin name collides with an MCP entry name** (M5). Builtin
  names are reserved entry names, so a deployment with an entry of that
  name would be refused at read. M5 picks a name and checks the
  reservation against the gate's choice; if the name is a plausible
  entry name, the fragment says so in an `Upgrade:` line.
- **Test churn in M1** (90 files mention `default_agent`). The helpers
  absorb most of it; the remainder is inventoried by tooling.

## Standing lenses

- **No-leak**: the reported board type never enters a prompt, a
  sentence or an event beyond the bounded `ota_check` field it already
  rides; a lookup query is conversation content: it reaches the
  conversation record and, only with LLM input export on, the
  telemetry span's tool-argument field, and no log line or other event
  field; `builtin_agent_not_served` carries closed-set tokens
  only; the displacement and override refusals quote no stored text
  (the name they concern is the constant `vinga`). Sentinels as under
  Tests.
- **Pin before reshaping**: the live-binding pin moves deliberately in
  M1, in its own commit; the operator agent's prompt is pinned
  byte-identical across M3 and M4; the claim route's existing tests
  pass unchanged for a body that names agents.
- **Closed sets mapped to decision sites**: `builtin_status`'s three
  answers, each decided in that one function; the event's `reason` is
  its two non-served answers; `DEFAULT_AGENT_NOT_SERVED` decided at
  issuance; `RefusalReason.NO_DEFAULT_AGENT` and `ALREADY_COVERED`
  removed with their decision sites, so no token outlives the site that
  chose it. No new `TOOL_SOURCES` member.
- **Honest seams**: the board text is optional and compared
  `is not None`; the knowledge reader is a cached function, not an
  injected dependency; `BuiltinTools`' new callable answers for the
  reply's world, as `remembers` does.
- **Inventories by tooling**: the eight `config.agents` sites, the 90
  test files, the hand-maintained pages naming the default agent
  (`git grep -n -i "default.agent"` over `docs/`, `README.md`,
  `vinga-server/examples` and `vinga-server/config.example.yaml`,
  excluding `docs/plans`, `docs/adr`, `docs/features` and
  `docs/reference`), and the failing set after M1's rule change, each
  quoted untruncated in the implementation doc and refreshed after any
  rebase.
- **Proportion**: the "Cheapest alternative" line, Q5 to Q7's pricing,
  and the gate's measurement.
- **Falsify before claiming**: every mutation under Tests is run and
  reported, and a surviving one is a finding about its test; the
  displaced case in M6 is the one guarding an access boundary.

## Documentation footprint

Every milestone that edits a Use page regenerates the packaged copy in
the same change (M2 onward), and generated references change only
through their generators.

- **M1**: a new ADR, `docs/adr/<date>-an-unbound-device-only-pairs.md`
  (Status, Context, Decision, Consequences, deciding #612), and its
  index entry; `docs/concepts.md` Binding (the allowlist sentence, the
  new meaning of the default agent) and Device (the location tool's
  "a device a default agent merely covers" sentence goes);
  `docs/glossary.md` (default agent); `docs/run/security.md` ("Who gets
  a token is the allowlist"); `docs/run/onboarding-a-device.md` (steps
  4 and 5, "which devices are offered a code"); `docs/run/configuration.md`
  (the boot rule and "default_agent for unknown devices");
  `docs/run/configuration-api.md` (the claim body);
  `docs/run/with-a-coding-agent.md`; `docs/devices/browser.md` (the D4a
  paragraph); README Getting Started step 5 (pair with a claim); the
  presets' and `config.example.yaml`'s comments about pointing unbound
  boards at an agent; `examples/README.md`; the references
  (`cli.md`, `api-openapi.json`, `domain-config.md`).
- **M2**: AGENTS.md and the `implement-issue` skill's census
  paragraphs (a third committed artifact and its regenerate command);
  no user-facing page.
- **M3**: `docs/concepts.md` Agent (the built-in agent, what it
  answers, how an operator overrides it), Memory and Meta capabilities
  (vinga's memory and thread search are its device's);
  `docs/glossary.md` (vinga; default agent is vinga when unset);
  `docs/run/configuration.md` (overriding vinga: providers, voice,
  language; what the entry refuses; displacement and rename);
  `docs/run/onboarding-a-device.md` (a claim binds to vinga by default;
  the try link's new refusal); `docs/run/security.md` (vinga carries no
  MCP tools by construction); `docs/reference/events.md` through its
  generator.
- **M4**: `docs/devices/README.md` (vinga knows the board from its
  check-in, and a restart teaches it); `docs/devices/browser.md` (vinga
  knows it is a browser); `docs/concepts.md` Device, observed facts.
- **M5**: `docs/concepts.md` Agent (vinga looks things up in the Use
  pages); `docs/architecture/product-promises.md` (the baseline item,
  citing the baseline record); `docs/run/llm.md` (the gate's
  measurements, dated).
- **M6**: `docs/concepts.md` Binding and Meta capabilities (vinga on
  every bound device; the handover offered there);
  `docs/devices/README.md` ("Talking to the device itself": asking for
  vinga).
- **M7**: the presets, `config.example.yaml`, `examples/README.md`,
  README Getting Started (step 3 configures providers only, step 5
  pairs and meets vinga) and its feature list, `docs/run/llm.md` and
  `docs/run/with-a-coding-agent.md` (the local model the gate chose).

## Milestones

- [x] **[M1: an unbound device only pairs](2026-10-06-vinga-built-in-agent-implementation.md#m1-an-unbound-device-only-pairs)** (PR TBD). The resolution
  rule loses its default fallback in both homes, derived through
  `Config.bound_to`; the live read stops reading the default row (pin
  moved); the boot rule goes; the claim loses `ALREADY_COVERED` and
  takes its agent as optional (API body, CLI); the browser mint loses
  D4a; notices and descriptions reworded; smoke seeds and the browser
  lane's pairing case bind explicitly; the test helpers bind
  `DEVICE_MAC`; the ADR; the fragment with its `Upgrade:` line. A
  behavior change alone in review. Design footprint: deepens
  `device/bindings.py`, `config/store.py`, `config/models.py`; shallows
  `browser/router.py`; no new module.
- [ ] **M1b: browsers join by invite** (PR TBD). Q11: `vinga device
  invite [--agent NAME]`, `vinga info` reporting only, the API route
  and body, the agents carried with the token and bound at redemption,
  `try_links` renamed `invites` throughout, the page at `/talk/`; the
  browser lane, the route inventory and the census follow; the
  coding-agent guide's browser step, `docs/devices/browser.md`,
  `docs/run/onboarding-a-device.md`, `docs/run/exposing-a-deployment.md`
  and `docs/run/security.md` follow; the fragment with its `Upgrade:`
  line. Design footprint: `onboarding/invites.py` keeps
  `try_links.py`'s depth under its new name and gains the bound agents;
  the CLI gains one verb under an existing noun.
- [x] **[M2: the Use door, packaged](2026-10-06-vinga-built-in-agent-implementation.md#m2-the-use-door-packaged)** ([PR #631](https://github.com/rafacm/vinga/pull/631)). `knowledge/` with the
  committed copy, sections, the board-guide mapping (D3 budget test),
  the concept summary (D2 test), the cached reader; the census module
  that regenerates and checks the copy; the D10 pin; the wheel-level
  assertion. No behavior change and no runtime caller yet. Design
  footprint: one new package, whose callers (M3 to M5) stop knowing
  where the pages are and how they are cut.
- [ ] **M3: vinga, the built-in default agent** (PR TBD). The name, the
  synthesis and `builtin_status`, `is_builtin`, the reference rule, the
  `builtin_agent` key (table, migration `3005`, store, document key,
  `vinga builtin-agent` noun), the refusal to create `agents.vinga`,
  displacement, the
  effective default in claim and enrolment, D5's refusal, the persona
  through `prompt_for_agent`, device-scoped memory and threads (Q5),
  D6's event and `vinga info` line, the browser lane's vinga case, the
  fragment with its `Upgrade:` line. Device scoping lands here rather
  than with reachability: vinga served with agent-scoped memory for
  even one release would let one device recall what was said on
  another, against decision 8. Design footprint: deepens
  `config/models.py`, `config/store.py`, `tools/builtin.py`,
  `tools/source.py`, `memory/store.py`, `conversations/threads.py`,
  `runtime/resumption.py`.
- [ ] **M4: the board reaches vinga's prompt** (PR TBD). The session
  reads its board once at open; the pipeline hands
  `knowledge.board_facts` to `with_scopes` for the built-in; the device
  block carries it; the vague text; the board string read off a real
  board and recorded. Design footprint: deepens `runtime/prompt.py`,
  `runtime/pipeline.py`, `device/session.py`.
- [ ] **M5: the lookup tool, as the gate chose** (PR TBD). The winning
  shape in `knowledge/`, its builtin name(s) and definition, offered to
  the built-in alone; the persona's sentence about it; the local-lane
  replay; the baseline item in the promises page; the gate's numbers
  in `docs/run/llm.md`. Design footprint: deepens `knowledge/` and
  `tools/builtin.py`.
- [ ] **M6: vinga reachable from every bound device** (PR TBD).
  `Config.reachable_from`, `BoundNames.against(config)` and its three
  callers, the displaced falsification, the local tool-calling rerun,
  the fragment with its `Upgrade:` line. A behavior change for every
  bound device, alone in review. Design footprint: deepens
  `config/models.py` and `device/bindings.py`.
- [ ] **M7: presets and first contact** (PR TBD). The presets carry no
  agent and no default; `config.example.yaml`, `examples/README.md`
  and Getting Started follow; the local model the gate chose; the
  preset boot case. Existing deployments are untouched: importing a
  preset is additive, so an `assistant` already stored stays.


## Plan review round

Reviewed 2026-10-06 by openai/gpt-6-sol, thinking high via codex CLI 0.160.1, read-only sandbox, runtime 5m48s, at commit a5e57a25, plan blob 62b7b8bf.


1. **P1: The required lookup gate is still open.** Evidence: the plan’s gate (`docs/plans/2026-10-06-vinga-built-in-agent.md:564`) says the plan was committed while measurement was running; its results, winner, harness and Q8 interface are placeholders. Issue #612 requires measurement **before the design is committed**. The plan should record the fixed questions, harness, results and chosen tool interface, then review that completed design before M5 begins.

   *Resolution:* accepted. The gate ran to completion on the models that
   matter (Gate): 32 frozen questions, ten complete configurations, every
   answer hand-checked. It chose shape A and Gemma 4 e4b, and it found
   that the design fails as written on the preset's model. So the plan
   now carries the measured verdict and M5's own pass bar (at least 70%
   correct, at most 10% hallucinated on the frozen set and on a
   rephrased run), with the fallback if that bar is not met. That
   decision is recorded on #612 for Rafael.

2. **P1: The board-guide rule selects pages that cannot pass its own test.** Evidence: Q6 (`docs/plans/2026-10-06-vinga-built-in-agent.md:415`) maps a reported type to any packaged device-page filename, while D3 (`docs/plans/2026-10-06-vinga-built-in-agent.md:626`) requires every mapped guide to have `## Controls`. Both flashing.md (`docs/devices/flashing.md:1`) and README.md (`docs/devices/README.md:1`) are in the proposed copy and lack that section. The plan should define which pages are board guides and test the matcher against that set, including these two negative cases.

   *Resolution:* accepted. The matcher searches only the board guides,
   one named set beside it that excludes `README.md` and `flashing.md`
   (Q6), and D3's tests hold that set to the facts rule and drive the
   matcher with both exclusions spelled as board types, which must get
   the vague text.

3. **P2: An existing blank `vinga` agent silently changes identity on upgrade.** Evidence: Q2 (`docs/plans/2026-10-06-vinga-built-in-agent.md:250`) treats a stored `agents.vinga` row as legacy only when `prompt` or `mcp` is non-empty. AgentConfig (`vinga-server/src/vinga_server/config/models.py:3530`) permits both to be empty; such a row can still have provider settings or prompt fragments. The plan would replace that agent’s blank persona with the built-in persona and could remove inherited MCP grants without warning. It should specify how a pre-upgrade row is distinguished from a new override, and test the blank-row upgrade.

   *Resolution:* accepted, by removing the heuristic rather than
   refining it. The built-in's overrides move to a key of their own,
   `builtin_agent`, mirroring `agent_defaults` (table, migration
   `3005`, store, document key, `vinga builtin-agent` noun), whose model
   has no `prompt` and no `mcp` (Q1). Any stored `agents.vinga`, blank
   or not, is then an operator's agent and displaces the built-in (Q2).
   M3 adds the test the finding asks for: a blank `agents.vinga` stored
   before the upgrade stays served under its own empty persona with its
   inherited grants, and vinga is `displaced`.

4. **P2: The collision remedy breaks export-and-apply round trips.** Evidence: Q1 (`docs/plans/2026-10-06-vinga-built-in-agent.md:233`) places the `agents.vinga` refusal in per-entry write staging. apply (`vinga-server/src/vinga_server/config/store.py:901`) prepares every document entry, and _parsed (`vinga-server/src/vinga_server/config/store.py:1954`) runs that write check before deciding an entry is unchanged. An export containing a displaced legacy `vinga` row would therefore fail when applied back unchanged. The plan should preserve that round trip for legacy rows, with a test, while refusing new incompatible writes.

   *Resolution:* accepted. With the overrides in `builtin_agent`, the
   refusal on `agents.vinga` is no longer about its fields: only a write
   that would *create* that agent (or rename one to it) is refused,
   decided against the stored state before the write, so an existing row
   kept or edited passes (Q1). M3 tests the round trip: a displaced
   deployment's export applies back unchanged with nothing written, and
   a document adding a new `agents.vinga` to a deployment without one is
   refused whole.

5. **P2: `vinga info` needs a live status source that the plan does not name.** Evidence: D6 (`docs/plans/2026-10-06-vinga-built-in-agent.md:655`) promises status after every apply. The existing runtime info response (`vinga-server/src/vinga_server/config/api.py:1721`) is composed once at startup from process and file settings. The plan should specify a read against the installed generation for built-in status and test that `vinga info` changes after an apply makes vinga served, displaced or unprovided.

   *Resolution:* accepted. D6 names the source: the built-in's status
   is the one field of `GET /api/runtime/info` computed per request,
   from the installed generation through `builtin_status`, with the
   rest of the response still composed at startup; M3 tests `info`
   across applies through `served`, `displaced`, `served` and
   `unprovided`.

6. **P2: The lookup-query no-leak assertion omits an authorized content channel.** Evidence: the test plan (`docs/plans/2026-10-06-vinga-built-in-agent.md:737`) says a query may appear only in the conversation record. The pipeline (`vinga-server/src/vinga_server/runtime/pipeline.py:793`) also stages tool arguments for a telemetry span when LLM input export is enabled; the event catalog (`vinga-server/src/vinga_server/events/catalog.py:4178`) documents that content field. The plan should classify that opt-in span as an authorized content surface and test both export-off and export-on behavior, while keeping the query out of ordinary logs and event fields.

   *Resolution:* accepted. The opt-in LLM-input span's tool-argument
   field is named as the second content surface beside the conversation
   record, and M5's sentinel test runs with export off and on (Tests,
   Standing lenses).

**Verdict: not ready.** The lookup decision is unmeasured, and the stated board-guide test cannot pass as written.

## Plan review round 2

Reviewed 2026-10-07 by openai/gpt-5.6-terra, thinking high via codex CLI 0.160.1, read-only sandbox, runtime 7m18s, at commit 7e7caa5d, plan blob edb9f179.

1. **P1: The plan overrides the issue’s build-time packaging decision.**

   Evidence: plan, Decisions 5 (`docs/plans/2026-10-06-vinga-built-in-agent.md:153`) explicitly replaces copying pages into the image at build time with a committed in-package copy. The issue settles build-time copying, and the review brief says its numbered decisions are not open for revision.

   Plan should say: retain build-time derivation from the authoritative docs, including a wheel and image build path that carries the pages, or first obtain an issue-level decision changing this requirement.

   *Resolution:* rejected, with the reason recorded on #612 for Rafael. The
   issue's settled point is the property it names, "what vinga says
   always matches the server it runs in"; copying at image build time
   was its proposed mechanism. Step 0 found the premise under that
   mechanism moved (premise 12: the image's build context is
   `vinga-server/` and cannot see `docs/`, and the wheel the browser
   lane installs has no image build at all), which is the case the
   pipeline lets a plan amend, and Decision 5 marks the amendment and
   its reason. The committed copy keeps the property in every artifact
   (wheel, image, git install), and the census lane fails in both
   workflows the moment it drifts from `docs/`.

2. **P1: M1 temporarily creates an enrollment path that violates invite-only browsers.**

   Evidence: Q4 (`docs/plans/2026-10-06-vinga-built-in-agent.md:373`) removes both `try_identity` refusals and makes it always mint, while decision 13 (`docs/plans/2026-10-06-vinga-built-in-agent.md:190`) says only `vinga device invite` may issue browser admission. M1b, which replaces try links with invites, comes later. Today those refusals are the branches in browser/router.py (`vinga-server/src/vinga_server/browser/router.py:201`).

   Plan should say: land the invite-only issuance and redemption path atomically with the pairing-rule change, or preserve a refusal until M1b is installed. A deployable M1 must not let a page mint a browser identity that can pair outside the invite command.

   *Resolution:* rejected, with decision 13 clarified. Only *issuing a link
   that binds without a code* is made exclusive to `vinga device
   invite`; pairing by code stays open to a browser as to a board
   (decision 10), and a code admits nothing until the operator claims
   it. So M1's always-minting `try_identity` lets a browser *ask* to
   join, never join, and M1 is deployable as cut. M1 adds the test: a
   freshly minted browser identity checks in, is offered a code, and is
   refused a token until the code is claimed.

3. **P1: The local-stack fallback contradicts the settled local-agent decision.**

   Evidence: the issue requires the local preset’s 8B model and a lookup tool for knowledge beyond the prompt. The plan instead selects `gemma4:e4b` and says that, if its new gate fails, local vinga ships without lookup (Gate (`docs/plans/2026-10-06-vinga-built-in-agent.md:667`), fallback (`docs/plans/2026-10-06-vinga-built-in-agent.md:680`)). Its own restatement still says “the rest is a lookup tool” (decision 7 (`docs/plans/2026-10-06-vinga-built-in-agent.md:174`)).

   Plan should say: keep the local preset on an 8B model and make M5 a ship gate for lookup reliability, or return to the issue for a decision changing the model-size and lookup requirements. It must not redefine the local baseline after the fact.

   *Resolution:* accepted as an escalation rather than resolved in the plan.
   The plan keeps the measured recommendation (Gemma 4 e4b, shape A,
   M5's pass bar, the prompt-only fallback) and now says M5 and M7 do
   not start until Rafael confirms it on #612, where the gate's numbers
   are posted (Gate). Decision 7's restatement stands as the target the
   M5 bar is measured against.

4. **P2: The board-type sentinel test cannot pass against the existing event contract.**

   Evidence: the test plan requires a credential-shaped board type to be absent from every event (Tests (`docs/plans/2026-10-06-vinga-built-in-agent.md:836`)). Existing OTA handling deliberately emits the bounded reported board in every `ota_check` event (ota/reply.py (`vinga-server/src/vinga_server/ota/reply.py:417`), ota/reply.py (`vinga-server/src/vinga_server/ota/reply.py:442`)), and also retains the submitted body in the DEBUG event (ota/reply.py (`vinga-server/src/vinga_server/ota/reply.py:517`)). The plan itself acknowledges `ota_check.board` as the source for a real-board measurement.

   Plan should say: either change the existing OTA event policy to redact credential-shaped untrusted descriptors, with its own compatibility and documentation review, or narrow the M4 test to new prompt, session, log, and event surfaces while explicitly listing the pre-existing OTA content surfaces as authorized exceptions. The current wording makes the no-leak test false.

   *Resolution:* accepted. The sentinel test is narrowed to the surfaces M4
   creates or feeds (the prompt, the session, the log lines and event
   fields M4 adds), and names `ota_check.board` and the DEBUG
   `ota_check_body` event as the pre-existing descriptor surfaces it
   leaves alone, pinned to carry exactly what they carry today. Changing
   the OTA event policy is out of this plan's scope; the DEBUG body is
   already an open follow-up.

5. **P2: `builtin_agent` is not fully specified as a domain section, so invalid overrides can evade write-time validation and pending-state reporting.**

   Evidence: the plan adds a stored singleton but only names `models.py` and `store.py` in its M3 footprint (M3 (`docs/plans/2026-10-06-vinga-built-in-agent.md:1060`)). A domain section is coupled through `DOMAIN_KEYS` and `DomainSnapshot` (models.py (`vinga-server/src/vinga_server/config/models.py:4234`), models.py (`vinga-server/src/vinga_server/config/models.py:4338`)); `check_references` currently validates only defaults and stored agents (models.py (`vinga-server/src/vinga_server/config/models.py:4424`)); and `config/diff.py` requires every domain key in `APPLIES` (diff.py (`vinga-server/src/vinga_server/config/diff.py:77`)) but has no response field for this singleton.

   Plan should say: enumerate registration in models, store loading, entity descriptors, views, document import/apply, API and CLI routes, diff response/OpenAPI, and reload status. It must also state that `builtin_agent`’s provider and fragment references are validated at write time under `builtin_agent.*`, even while the synthesized entry is absent because its stages are unprovided. Add tests for invalid references, export/import round trips, and a visible pending then applied override change.

   *Resolution:* accepted. Q1 now carries the registration inventory, taken
   by tooling (the 15 files that register `agent_defaults` at
   `7e7caa5d`), with each home named, write-time validation of
   `builtin_agent.*` references whether or not vinga is synthesized,
   a `vinga diff` field so a pending override is visible, and the three
   tests the finding asks for.

6. **P2: The M5 gate is not reproducible from the repository and its local-lane test does not enforce the claimed threshold.**

   Evidence: the question set, harness, annotations, and raw runs are kept outside the repository (Gate (`docs/plans/2026-10-06-vinga-built-in-agent.md:597`)), yet M5 claims repeatability only through a local-lane replay (Tests (`docs/plans/2026-10-06-vinga-built-in-agent.md:882`)). The stated 70% correctness, 10% hallucination, retrieval, rephrasing, and watchdog criteria have no committed fixture or executable scorer.

   Plan should say: commit the frozen prompts, expected facts, rephrased set, scoring rules, and threshold assertions as local-lane fixtures. Raw model output can remain uncommitted, but a future maintainer must be able to rerun and evaluate the gate without recovering session files.

   *Resolution:* accepted. M5 commits the frozen and rephrased question sets,
   their expected facts, the recorded queries and the scorer as
   fixtures, with a model-free unit test holding retrieval to its bar
   and an opt-in local-lane case asserting the pass bar, so a later
   maintainer reruns the gate from the repository (Tests).

7. **P3: The “no index” rationale becomes false once vinga is shared by all devices.**

   Evidence: the plan says filtering `conversations.device` needs no index because the scan already narrows by agent (Q5 (`docs/plans/2026-10-06-vinga-built-in-agent.md:400`)). The current search intentionally scans all threads for an agent (threads.py (`vinga-server/src/vinga_server/conversations/threads.py:712`)). For built-in `vinga`, that agent is precisely the deployment-wide population, so every device-scoped resume search can scan every device’s vinga thread.

   Plan should say: measure the filtered query at a stated deployment size and either add a composite `(agent, device, last_active_at)` index migration or document a justified bound and regression benchmark. The present argument relies on the old agent-per-device cardinality.

   *Resolution:* accepted. The no-index argument assumed one agent per device's
   population; for vinga it is the deployment. M3 measures the filtered
   search on a seeded store (50 devices, 200 vinga threads each) and adds
   the composite index by migration if it passes 50 ms, recording the
   measurement either way (Q5).

Verdict: **not ready.**
