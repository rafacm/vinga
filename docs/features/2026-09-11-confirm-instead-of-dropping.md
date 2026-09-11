# The refractory gate confirms instead of dropping

**Date:** 2026-09-11

## Problem

The barge-in gate ladder is built on one rule, recorded in
[its ADR](../adr/2026-08-05-replies-cancel-only-on-evidence-of-speech.md):
a reply is only cancelled on evidence of user speech, and acoustics
alone can at most pause it. One rung contradicted the rule it was part
of. An utterance the endpointer ended within
`server.barge_in_refractory_ms` (1000 ms by default) of the reply's
first delivered frame was dropped unheard, on the theory that what the
microphone hears that early is the playback onset leaking through the
device's echo cancellation.

Field round 2 (#80) found it dropping something else entirely: four
refractory suppressions in 48 h of household use, each discarding 0.6
to 1.6 s of classified speech, every one of them a user finishing a
sentence the endpointer had cut in half. A later commissioning window
reproduced it without looking for it, five suppressions in 4 h 33 m
carrying 608 to 2208 ms of speech. The gate's true-positive rate in the
field was zero.

The arithmetic says it could not have been anything else:

- `barge_in_min_speech_ms` (500 by default) is checked first, so
  nothing reached this rung without half a second of endpointer
  classified speech behind it.
- The primary board's playback trails the server by roughly 760 ms,
  measured on that board's own capture by correlating the microphone
  envelope against the speaker envelope across three replies
  (r = 0.60 to 0.74 at that lag, nothing at lag 0). One board in one
  session, so evidence rather than a constant, and the only measurement
  there is.
- The window was measured from the first frame this server delivered,
  server-side. So a second of it is at most about 240 ms of sound in
  the room.

Echo cannot supply 500 ms of speech out of 240 ms of playback.

The issue's second half is the other end of the same failure: the
endpointer ends a turn after `trailing_silence_ms` (700 ms), dictation
pauses longer than that between clauses, and the reply to the fragment
is what the continuation then has to fight. Field round 2 counted 18
transcripts in 48 h ending in an ellipsis.

## Changes

**The gate falls through to confirmation.** `_gate_barge_in` no longer
has a refractory rung. What is left is the speech floor, the merge when
the reply is still inside its own ASR, and the transcript confirmation:
the outgoing frames pause, ASR transcribes the interruption, and only a
non-empty transcript cancels the reply. An empty one resumes the paced
stream where it stopped, which is the ladder's existing contract and
has its own pin. The reasoning above lives in the method's docstring,
because it is a "why there is no gate here" that would otherwise be
re-added.

The onset-based exemption the issue also proposed (skip the gate when
the utterance's speech onset predates the reply's first frame) was
considered and rejected as unnecessary rather than wrong: it needs a
fact the session does not keep, namely when the endpointer was last
reset on the session clock, and the numbers say that work does not need
doing.

**`BargeInInRefractory` and `Suppression.REFRACTORY` leave the
catalog**, because the event-baseline suite holds every declared
variant to being produced by some driver's run and no path produces
this one any more. The suppression group is down to `min_speech` and
`no_transcript`, `docs/reference/events.md` is regenerated from the
declarations, and the baseline's driver for the removed path goes with
the two emit-site indices behind it renumbering.

**`server.barge_in_refractory_ms` is removed.** It had exactly one
reader and lost it. A knob with no reader is worse than an absent one:
it invites tuning a behaviour that no longer exists, and it makes the
schema disagree with the code. Per the pre-release stance (#225, #235)
there are no third-party installs to keep working, so it is removed
rather than deprecated, and a configuration still setting it is refused
at boot by `extra="forbid"` with the ordinary unknown-key error. That
error does NOT name the key: `safe_location` strips a segment the
caller invented before either rendering, because a key is as good a
place to paste a credential as a value, and the sentence is printed by
the CLI, answered by the API and written to the boot log. What the
operator is told is the section, `server`, and the rule; finding the
stale line is a search of their own file.

**The capture and session-record manifest drops `refractory_ms`**
rather than writing it null. The manifest states what a session was
held against; a null would claim this session had the gate and left it
unbounded, while no key says the session ran on a server that has no
such gate. `server.revision` sits beside it in the same manifest and is
what tells the two eras apart. A recording made before this change and
one made after therefore describe their gates differently, which is
what a manifest is for. Nothing here reaches the device: the manifest's
only consumers are the capture writer and the conversation store, and
the store's session row does not read the barge-in block at all.

**Per-agent endpointing is documented rather than built.**
`trailing_silence_ms` keeps its 700 ms default: raising it globally
would put the added latency on every turn of every agent to fix one
agent's usage pattern. The per-agent route already works, verified in
`_activate_agent`, which builds a fresh endpointer from the bound
agent's VAD provider on every activation and therefore on every
handover. What was missing was discoverability, so the route is written
where the question is asked: `examples/vad-silero.yaml` carries the
longer-bound case, the server README's listening section carries the
two-entry configuration, its memory section points there from where the
problem shows up, and the glossary's trailing-silence and
premature-endpoint entries say the bound is per agent.

Adaptive or prosodic endpointing stays out of scope, as the issue says;
it is #81's.

**The explanations follow the code.** The glossary's barge-in and
gate-ladder entries lose the rung; its refractory-period entry keeps
its anchor and its definition of the technique and says plainly that
vinga no longer has one and what removed it. The barge-in ADR gains a
dated amendment rather than an edit, since its decision stands whole
and this is the one gate that contradicted it. The barge-in decision
diagram loses the branch and is re-rendered from its source. The two
research notes that enumerate the current gate stack are corrected,
because neither statement was a dated measurement.

## Key parameters

| Name | Before | After |
| --- | --- | --- |
| `server.barge_in_min_speech_ms` | 500 | 500, unchanged, and now the only gate in front of the confirmation |
| `server.barge_in_refractory_ms` | 1000 | removed; a config setting it is refused at boot |
| `trailing_silence_ms` (VAD entry) | 700 | 700, unchanged, and documented as per-agent |
| `barge_in_suppressed` reasons | `min_speech`, `refractory`, `no_transcript` | `min_speech`, `no_transcript` |
| manifest `barge_in.refractory_ms` | the configured value | absent |

## Verification

- `uv run ruff check .`, `uv run mypy`.
- `uv run pytest tests/unit -q -n auto --dist loadfile` and
  `uv run pytest tests/integration -q`.
- The two new pins are mutation-proved: reinstating the drop inside a
  1000 ms window fails
  `test_speech_at_the_playback_onset_is_confirmed_and_not_dropped`
  (unit, deterministic, the interruption is fed immediately after the
  first frame) and
  `test_speech_at_the_playback_onset_is_confirmed_and_answered`
  (over the websocket, the way the firmware drives it).
- The empty-transcript contract keeps its own pins, at the default
  configuration rather than with the window disabled:
  `test_a_confirmation_that_heard_nothing_resumes_the_reply_it_paused`
  and `test_an_unconfirmed_barge_in_pauses_and_resumes_the_reply`, the
  second of which also holds the pacing clock's shift.
- The generated-document drift checks for `events.md`,
  `server-config.md`, `domain-config.md` and `cli.md`, and
  `scripts/check_doc_links.py`.
- Not verified: nothing was run against a board. The 760 ms playback
  lag and the field suppression counts are prior measurements quoted
  from the issue, not re-measured here.

## Files modified

- `vinga-server/src/vinga_server/runtime/turntaking.py`: the rung goes;
  the docstring carries why there is none.
- `vinga-server/src/vinga_server/events/catalog.py`,
  `vinga-server/src/vinga_server/events/values.py`: the variant and the
  reason token.
- `vinga-server/src/vinga_server/config/models.py`: the setting.
- `vinga-server/src/vinga_server/device/session.py`,
  `vinga-server/src/vinga_server/device/pacing.py`,
  `vinga-server/src/vinga_server/device/boundary.py`: the manifest key,
  and the docstrings that named the gate as a reader of
  `speaking_started_at`.
- `vinga-server/config.example.yaml`,
  `vinga-server/config.deploy.example.yaml`,
  `vinga-server/examples/vad-silero.yaml`,
  `vinga-server/README.md`.
- `docs/reference/events.md`, `docs/reference/server-config.md`
  (generated).
- `docs/glossary.md`, `docs/architecture/guidelines.md`,
  `docs/adr/2026-08-05-replies-cancel-only-on-evidence-of-speech.md`,
  `docs/architecture/diagrams/plantuml/barge-in-decision.puml` with its
  two renders and that directory's README,
  `docs/xiaozhi-notes.md`,
  `docs/conversational-quality-regression-suite.md`.
- Tests: `tests/unit/test_turntaking.py`,
  `tests/unit/test_session_barge_in.py`,
  `tests/unit/test_event_baseline.py`, `tests/tools/event_baseline.py`,
  `tests/support/telemetry.py`, `tests/unit/test_telemetry_spans.py`,
  and the five suites that configured the window away.
