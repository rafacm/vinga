# Give the session's conversations one owner: implementation

Companion to [`2026-09-23-session-conversations-owner.md`](2026-09-23-session-conversations-owner.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the session's conversations get one owner

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.280; 2026-09-23.

A device session's conversations have one owner,
`vinga_server/session_conversations.py`'s `SessionConversations`: each
agent's current thread, every thread's history, the store's handle for
each thread's last write, and the active pair as one frozen `Active`.
The edge constructs it when it normalizes the MAC and hands it to the
runtime factory beside the events object; the runtime moves it through
its transitions; the edge, the runtime and the filler runner read the
pair off it at their emit sites. `SessionEvents` holds no pair any more
and takes the device once, as a snapshot.

### The commits

| Commit | What it is |
| --- | --- |
| `Pin which pair every emission names` | `tests/unit/test_pair_attribution.py` and the filler builder in `tests/support/boundary.py`, green against the code before the move |
| `Add the owner of a device session's conversations` | `session_conversations.py` and `tests/unit/test_conversation_owner.py`, nothing using it yet |
| `Move the session's conversations onto one owner` | The move as one commit, its body walking seam, runtime state, readers, events object; the write-once test; the hardening file (below); the reach-in manifest |
| `Record the owner decision and M1` | The ADR, the 2026-08-10 status-line note, the three docstrings of the documentation footprint, this section and the tick |

### What landed

| Piece | Where |
| --- | --- |
| The owner | `session_conversations.py`: `SessionConversations`, `Active`, `mint`, `RESUME_ACKNOWLEDGEMENT_S`; imports nothing of `vinga_server` at runtime (`Acknowledgement` and `Turn` are annotation-only) |
| The seam | `device/boundary.py`: `RuntimeFactory` takes `SessionConversations` third, required; the comment above it gains the owner's paragraph and the ordinals of the two paragraphs after it move by one |
| The edge | `device/session.py`: `_mac`'s setter identifies the events object and constructs the owner; `_mac`, `_agent` and `_conversation` read it; the public `session_conversations` property; the factory call passes it |
| The runtime | `runtime/pipeline.py`: `_conversations`, `_histories`, `_acknowledged`, `_settled` and `RESUME_ACKNOWLEDGEMENT_S` gone; `conversations` public; `_activate_agent` calls `activate`, `_move_to` calls `start_new` or `reactivate`, `_select` mints through `mint`, `_record_turn` calls `acknowledge`, both resume paths await `settled`, `close` purges `current_threads()` |
| The filler runner | `runtime/filler_runner.py`: takes the owner beside the events object and reads the pair at each site through `_agent()` and `_conversation()` |
| The events object | `events/__init__.py`: `agent` and `conversation` deleted; `device` private and written once through `identify`, refused a second time with `ALREADY_IDENTIFIED` |

### The pins, and what they pinned

The inventory the plan asked for, of what the existing suites already
asserted about the pair on emitted events:

- **Connect, handover, handover back, new, resume:** no suite asserted
  the thread side of that sequence exactly. The handover tests pin the
  two agents (`test_session_events.py:351`,
  `test_session_characterization.py:414`), `test_session_conversations.py`
  pins where the session ends up through `talking_thread` and
  `conversation_resumed`'s own `conversation`, and nothing pinned the
  `from_conversation`/`to_conversation` pair or that the handover back
  continues the first thread. One characterization pin added:
  `test_every_transition_leaves_the_pair_its_emissions_name`, every
  pair every emission carried, in order, with minted ids named by first
  appearance.
- **`speaking_started`:** its agent was pinned
  (`test_session_characterization.py:398`), its thread was not, and
  nothing held the read across the pacer's await. One gated pin added.
- **The capture manifest's `agent`:** already pinned
  (`test_capture_session.py:243`, `test_conversations_session.py:155`),
  so nothing added.
- **The filler runner's emits:** agents pinned in
  `test_filler_runner.py`, threads never, and nothing held a read across
  an await. Four gated pins added, one per emit site: the fire's
  `filler_played` and both `filler_skipped` variants (a handover landing
  inside the fire's delay), and `reply_fallback` (a handover landing
  while the display send is held). The last also pins that the phrase
  is looked up on entry, so today's attribution is, precisely: the
  poet's words, recorded as the tutor's.

The pin file is byte-unchanged from its commit to this one
(`git diff ccfd26f8 HEAD -- vinga-server/tests/unit/test_pair_attribution.py`
is empty). What changed under it is its builder in `tests/support/`,
which is why the builder exists.

### The falsification runs

One run each; the gates make every interleaving deterministic, and the
owner's rules are straight-line logic. Every mutation was applied to a
copy-restored file with the tree's bytecode cleared afterwards, and
each failed on the assertion it was aimed at.

| Mutation | Result |
| --- | --- |
| `send_audio` snapshots the pair on entry | the `speaking_started` pin fails, `'poet' != 'tutor'` |
| `_fire` snapshots the pair on entry | all three fire pins fail |
| `speak_fallback` snapshots the pair on entry | the fallback pin fails |
| activation always mints (at the base) | the sequence pin fails at the handover back |
| `activate` always mints | 5 owner tests fail |
| `reactivate` aliases instead of copying | the copy test fails |
| `settled` skips the wait | "settled returned without waiting" |
| `settled` waits on the loop | "the wait blocked the event loop" (the heartbeat stalled) |
| `settled` passes 3.0 instead of the constant | the recorded argument differs |
| `reactivate` rebinds the first agent, not the active one | its test fails |
| `start_new` rebinds the first agent, not the active one | **survived the first pass**, fails after the fix below |
| `current_threads` lists every thread touched | the purge test fails |
| `identify` lets a second call overwrite | "DID NOT RAISE" |
| `identify`'s refusal carries the value | the exact-message assertion fails |
| an activation of an agent the session lacks (the old hardening failure) | "the reply spoke nothing, so this timed a failed reply" |

The one survivor was a finding about the test, as the plan says a
survivor is: the `start_new` test's active agent was the first agent
activated, so "rebind the first agent" and "rebind the active agent"
were the same agent and the driver never reached the condition. The
test now moves the second agent. The owner tests and the pins then ran
15 times in a row, all green.

### Deviations from the plan

- **The factory's inner parameter is `session_conversations`, not
  `conversations`.** `bespoke_runtime_factory` already closes over a
  `conversations`, the turn store, and a parameter of the same name
  would shadow it. The protocol is positional, so only the builder's
  spelling differs; the runtime's attribute is `conversations` as the
  plan names it.
- **The edge constructs the owner in `_mac`'s setter.** The plan says
  the owner is constructed "on the line that normalizes the MAC", and
  that line is `self._mac = normalize_mac(device_id)`, so the setter is
  where it happens. The reason to keep a setter rather than a named
  method is `tests/support/sessions.py`, whose `device_session`
  transcribes `run`'s lines and sets `session._mac` the same way: it
  stays one line, and the reach-in census stays the plan's prediction.
  The setter identifies the events object first, so a second write is
  refused before anything is replaced.
- **The edge has a public `session_conversations` read.** The plan
  asks `test_boundary_contract.py` to assert with `is` that the runtime
  holds the object the edge constructed; the edge's private field would
  have been a new reach-in. The property is the seam's own claim made
  readable, and `talking` and `talking_thread` read it too.
- **`with_device` became a check.** It wrote the MAC; writing it now
  constructs the owner, which happens once in `device_session`. Every
  caller passes the MAC the session was built for, so it asserts that
  and returns the session, and the callers are unchanged.
- **`open_session` in the telemetry support takes `conversations=`
  in place of `keep_identities=True`**, since a live session's pair is
  no longer on its events object, and **`session_events` identifies its
  emitter at construction** instead of `open_session` writing the
  device each time: one suite (`test_telemetry_llm_input.py`) opens the
  same emitter twice, and the second write is now refused.
- **Nine `events_of(...).conversation` reads**, in
  `test_session_tools.py` (4), `test_session_prompt.py` (3) and
  `test_memory_lifecycle.py` (2), became `talking_thread(...)`. The plan's
  inventory grepped `events.` and missed this spelling; the deletion
  turned each into an `AttributeError`, which is how they were found.
- **`test_telemetry_hardening.py` changed**, which the plan did not
  foresee; see the first discovery.
- **The reach-in manifest was regenerated in the move commit**, not the
  documentation commit, so the move commit's census lane is green on
  its own. The delta is the plan's.
- **A second identity test in `test_boundary_contract.py`**,
  `test_the_bespoke_runtime_holds_the_conversations_the_edge_built`,
  holds the same `is` for the real runtime beside the stub's.

Otherwise none: the module, the interface names, the factory position,
the owner's lifetime and the no-default rule are the plan's.

### Discoveries

- **Two integration cases had been timing replies that failed.**
  `test_telemetry_hardening.py`'s two "costs no reply anything" cases
  opened a real session with the telemetry support's fixed identities,
  which wrote agent `household` onto the events object the pipeline read
  who was talking from. Every reply was answered by an agent the
  session did not have and failed before its first sentence: at the
  plan base, one reply's events were `turn_started`, `heard`, and
  `reply finished (failed) after 0 sentence(s)`, with no frame sent.
  The file's 0.5 s bound was calibrated on those sub-millisecond
  failures (#491). With the pair off the events object nothing renames
  a session, the replies speak, and a speaking reply is paced at real
  time: 0.908 to 0.927 s for twelve replies against a healthy exporter
  and twelve against a wedged one, on agentpi, so the wedged collector
  still costs a reply nothing. The cases now open with the session's
  own conversations, assert every timed reply sent audio, and bound
  replies at 2.5 s, below the five-second shutdown wait the bound
  guards. No other caller of that `open_session` passed a live session
  without asking for its own identities.
- **A stray write to a deleted attribute does not fail.** `SessionEvents`
  has no `__slots__`, so `events.agent = x` after the deletion creates
  an attribute nobody reads rather than raising. Reads raise, which is
  what the lanes caught; writes are proved absent by the grep below,
  not by the lanes.
- **The plan's "17 sites" did not reproduce.** At `0fcc5c26`,
  `self._(conversations|histories|acknowledged|settled)` matches 12
  lines of `pipeline.py`, 16 counting docstring mentions. Not
  load-bearing, and the ADR states no number.

### The closing greps

Untruncated, from `vinga-server/`, counting lines.

| Question | At `8adb8eb9` (plan base) | At this commit |
| --- | --- | --- |
| `events\.(agent\|conversation\|device)\b` in `src` and `tests`, outside `src/vinga_server/events/` | 38 | **0** |
| the same three through other spellings, `(events_of\([^)]*\)\|emitter\|session_events)\.(agent\|conversation\|device)\b` | 15 | **0** |
| `RuntimeFactory` implementers | 2 (`bespoke_runtime_factory`'s `build`; the stub factory in `test_boundary_contract.py`) | 2, both taking the owner third |
| calls of a `RuntimeFactory` | 3 (`device/session.py`, `tests/support/sessions.py`, `test_boundary_contract.py`'s `runtime_for`) | 3, all passing the owner third |
| calls of `bespoke_runtime_factory` itself, whose signature did not change | 10 (`app.py` and nine in tests) | 10, unchanged |

### The reach-in census

Expected delta: `tests/unit/test_session_conversations.py  _acknowledged  1`
removed, nothing added. Observed: exactly that one line removed and
nothing added, regenerated with `uv run python -m tests.census.test_reach_ins`.
`_mac 3`, `_events 2` and `_turns` in `tests/support/sessions.py` and
`_turns 1` in `test_boundary_contract.py` are unchanged, as the plan
predicted. The command-spellings manifest did not move.

### #489's bookkeeping

The plan's command, run from `vinga-server/tests/unit` at `8adb8eb9`
and again at this commit, and column (b) judged per file.

| File | (a) before | (a) after | (b) storage reaching the subject through a visible parameter |
| --- | --- | --- | --- |
| `test_session_events.py` | 0 | 0 | no |
| `test_session_conversations.py` | 1 | 1 | yes, one case: `threads=threads.Reads(DatabaseConfig())` at line 791; every other case hands a written-down double |
| `test_conversations_session.py` | 12 | 12 | yes: the store into the factory and the session, lines 709 and 712 |
| `test_session_close_reason.py` | 0 | 0 | no |
| `test_session_recap.py` | 1 | 1 | no: `threads=` and `conversations=` (lines 224-225) are doubles |
| `test_session_memory_policy.py` | 2 | 2 | yes: `memory=lane_memory()`, first at line 119 |
| `test_events_live_wiring.py` | 1 | 1 | yes: `lane_memory()` into the factory, line 65 |

**Neither column moved**, which is the plan's prediction. The only
change to any of the seven files is one line of
`test_session_conversations.py`, the `_acknowledged` reach-in becoming
`session.runtime.conversations.acknowledge(...)`. The owner takes no
storage and these files reach the database through the recorder, the
memory store and the resumption flow, none of which this issue
touched. That is evidence against #489's premise for this seam, and
the instrument disagreement the plan recorded stands: five of the
seven name a storage helper, against the comment's "name no storage at
all".

### Verification

From `vinga-server/`, on agentpi, lanes with `-n auto --dist loadfile`:

| Where | What ran | Result |
| --- | --- | --- |
| the pins commit | the pins, and every suite importing the changed support module | 6 passed; 42 passed |
| the owner commit | unit lane; census lane | 7483 passed, 19 skipped (13m37s); 66 passed |
| the move commit | unit lane | 7485 passed, 19 skipped (13m40s): the two added are the write-once test and the bespoke identity test |
| the move commit | integration lane, before the hardening change | 345 passed, 2 failed: the two hardening cases the first discovery explains |
| the move commit | `test_telemetry_hardening.py` after the change | 4 passed, three runs |
| this commit | unit lane; integration lane | 7485 passed, 19 skipped (13m45s); 347 passed (3m33s) |
| this commit | `uv run pytest tests/census -q`; `uv run ruff check .`; `uv run mypy` | 66 passed; clean; no issues in 5 source files |
| this commit | the drift checks for the events, domain, server and OpenAPI references; `scripts/check_doc_links.py` | no difference in any; 266 files, 0 failures |

Not run here: the CLI reference's drift check, the tier-closure and
wheel lanes beyond what the integration lane holds, and the image
build and smoke conversation. No event, field, configuration key or
command changed, so none of them should move; the pull request records
what CI says.
