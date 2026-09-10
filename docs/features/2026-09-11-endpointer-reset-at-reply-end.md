# The endpointer stops carrying the reply into the user's turn

**Date:** 2026-09-10

## Problem

A realtime device streams its microphone continuously, through replies
as well as through silences. So for the whole of a reply the only thing
the endpointer is fed is the assistant talking, coming back off the
room, and nothing reset it when the reply ended.

Silero is recurrent. It scores a window against the windows before it,
which is what makes it good at speech and what makes it carry the
assistant's own voice into the pause a user answers in. The measured
consequence, from the capture that diagnosed it (#70, and #456 filed off
it):

- The utterance was there and was clear: peak -36.1 dBFS against a
  -72.7 dBFS floor, 85 to 91% of its energy in the 300-700 Hz band,
  matching the utterances the same session did register and matching
  neither room tone nor playback echo.
- The server fed it to the endpointer: unbroken `vad` samples every
  ~65 ms with `listening=true` and `frames_dropped` zero, and
  `speech_ms` flat at 0 throughout.
- Replaying that same channel-0 audio through the committed
  `pysilero-vad` at the shipped threshold of 0.5, varying only where the
  detector was last reset, moves the peak probability on the missed
  burst from **0.266 (missed)** at the real reset point to **0.856
  (detected)** at a reset just after the reply's last frame. Nothing
  about the audio changes across those rows.

The reset point, and nothing else, decided whether the answer was heard.
`restart()` is what resets the endpointer, and it is called when an
utterance finishes, when the device sends `listen start`, on a device
abort and at agent activation. In that session the last utterance
finished at 72.85 s, the reply ran 73.70 to 83.72, and `listening` never
went false, so no `listen start` arrived and no reset happened. The
endpointer was fed about ten seconds of echo arriving at -20 to -50
dBFS, and the user answered 260 ms after the room went quiet.

The symptom class this predicts is exactly the reported one: the first
answer after a reply is missed and a second, later attempt succeeds. The
same capture has the user saying so out loud, twice.

Two obvious fixes were rejected before this one:

- **Stop feeding the endpointer while replying.** Not viable. The
  barge-in ladder's first gate reads `speech_ms` straight off the
  endpointer, and the endpointer is also what endpoints the interrupting
  utterance. Not feeding it would blind barge-in rather than degrade it.
- **Call `restart()` when playback ends.** Viable and wrong. `restart()`
  also clears the utterance buffer, the drop accounting and the
  endpointing state, so a user who is mid-sentence when the reply ends
  has what they said discarded. That is precisely the continuation loss
  #80 is about, and fixing this issue that way would make that one
  worse.

## Changes

### The endpointer's reset becomes two calls

`pysilero_vad.SileroVoiceActivityDetector.reset()` clears the model's
recurrent state and keeps no accounting of its own. Everything else in
`Endpointer.reset()` (`_pending`, `_speech_heard`, `_silence_ms`,
`_utterance_ms`, `_speech_ms`, `_consumed_bytes`, `_speech_start`) is
vinga's own bookkeeping, bundled with it. The two are now separable at
the interface:

- `reset()` starts a fresh utterance, unchanged in what it does and in
  every place that calls it.
- `forget_audio()` says only that what was heard so far must stop
  colouring what is heard next, and leaves all of that accounting
  exactly where it stands.

`SileroEndpointer.reset()` is now written in terms of `forget_audio()`,
so the model reset has one home and the two can never drift apart.

The protocol is where the distinction is documented, because it is a
statement about what an implementation may carry, not about Silero. An
endpointer that scores each window from that window alone carries
nothing between them, so `EnergyEndpointer.forget_audio()` does nothing
and says why: a fact about what it holds rather than an omission.

### The reply's end asks for the second one

`TurnTaking.forget_reply_audio()` is the floor's side of it, and the
guard it carries is real: a runtime with no endpointer yet has nothing
to tell. It sits beside `restart()` and is deliberately not it.

The call site is `PipelineRuntime._reply`'s `finally`, immediately after
`self._turntaking.clear_pending()`. That is where the fact "this reply's
audio is over" already lives, so nothing new crosses a boundary:

- **After `await self._filler.settle()`**, because a filler clip still
  sounding is more of this reply's audio.
- **Before the awaits below it**, none of which puts a frame on the
  wire: `_record_turn` is synchronous and `finish_speaking` sends `tts
  start` and `tts stop`, which are text.
- **Not in `device/session.py`.** `finish_speaking` is the edge's, and
  the endpointer belongs to the agent behind the runtime; carrying this
  there would mean the edge reaching into the floor for a fact the
  runtime already has.

The reset happens at the server's last frame rather than at the room's.
The device's playback trails the server by about 760 ms (correlating the
mic envelope against the speaker envelope over three separate replies:
r = 0.60, 0.74, 0.60 at that lag, no correlation at lag 0), so the room
is still hearing the reply for three quarters of a second afterwards.
Waiting that out is unnecessary: the #70 measurements show a reset about
80 ms after the server's last frame giving p=0.856 on a burst a second
later, so roughly 700 ms of trailing echo does not re-poison a freshly
cleared detector the way ten seconds of it does.

### The reset is unconditional

The one open question was what a detector-state reset does to a barge-in
that is mid-utterance when the reply ends: Silero's recurrent state
carries "I am currently inside speech", so clearing it mid-sentence
makes the next windows score low, which accumulates `_silence_ms` and
could endpoint the user prematurely.

That was measured rather than argued, by feeding an utterance the server
actually heard twice and resetting the detector in the middle of the
second run:

```
    t(s)   no reset   reset@97.90
   97.86     0.981     0.981
   97.90     0.978     0.978   <-- reset here
   97.93     0.997     0.070
   97.96     0.999     0.638
   97.99     0.999     0.698
   98.02     0.999     0.894
```

One window below threshold, 32 ms, then back over 0.5 and climbing. The
budget it is spent against is `trailing_silence_ms` of 700 ms, which is
about 22 such windows: a margin of roughly 22 to 1. So the reset needs
no branch on whether an utterance is open, and the branch, the state it
would have needed, and the decision all go away.

That measurement is one utterance, one voice, one room. The claim is not
that a mid-speech reset is free, it is that its cost is about one window
against a budget of about twenty-two, which is why the pin below asserts
the margin and never a probability.

## Key parameters

- `Endpointer.forget_audio()`
  (`vinga-server/src/vinga_server/providers/base.py`): stop carrying the
  audio heard so far, keep the accounting. The half of `reset` a reply's
  end asks for.
- `SileroEndpointer.forget_audio()`
  (`vinga-server/src/vinga_server/providers/silero.py`): one line,
  `self._detector.reset()`, and `reset()` now calls it.
- `EnergyEndpointer.forget_audio()`
  (`vinga-server/src/vinga_server/providers/mock.py`): nothing, because
  it scores each chunk on that chunk's own RMS.
- `TurnTaking.forget_reply_audio()`
  (`vinga-server/src/vinga_server/runtime/turntaking.py`): the floor's
  side, with the same no-endpointer guard `restart()` carries.
- `PipelineRuntime._reply`'s `finally`
  (`vinga-server/src/vinga_server/runtime/pipeline.py`): the one call
  site, after the filler settles and before the closing `tts stop`.
- `trailing_silence_ms`, default 700.0, and Silero's fixed 32 ms window:
  the two numbers the margin is a ratio of. Neither changed.

No configuration key changed, no event field changed, and no event
sentence changed.

## Verification

From `vinga-server/`, with the worktree's own Postgres up
(`VINGA_DB_PORT=55435 docker compose -p wt456 up -d postgres --wait`):

- `uv run ruff check .`: clean.
- `uv run mypy`: clean over the events package.
- `uv run pytest tests/unit -q -n auto --dist loadfile`, the shape CI
  runs: 6187 passed, 19 skipped.
- `uv run pytest tests/integration -q`: 282 passed.

Three pins, and how each was proven to bite.

- **The regression, end to end**
  (`tests/unit/test_endpointer_echo.py`). A reply runs while the room
  feeds its echo back, and the moment it ends the user answers. The
  endpointer is a double, because the mechanism and not the model is on
  trial: a real Silero missing this audio needs the capture that
  diagnosed it, and a synthetic tone tells a real model nothing. What
  the double reproduces is the one property that matters, that audio
  already fed decides what the next window is heard as; its accounting
  underneath is the real `EnergyEndpointer`'s. **Mutation-proved** by
  deleting the `forget_reply_audio()` line from the pipeline's `finally`
  (the file copied aside first, restored by copy plus `touch`, never
  `git checkout`): the pin fails with "the answer was not heard",
  `speech_ms` 0.0, and its 36 neighbours in `test_turntaking.py`,
  `test_providers_silero.py` and `test_turn_lifecycle.py` all pass.
- **The #80 boundary**
  (`tests/unit/test_turntaking.py::test_the_replys_audio_is_forgotten_and_the_user_is_not`).
  A reply ending under a user who is mid-sentence leaves every byte of
  what they said waiting to be answered, and asks the endpointer to
  forget rather than to reset. **Mutation-proved** by making
  `forget_reply_audio()` call `restart()`: the pin fails with "the
  sentence the user was in the middle of was discarded" and 13
  neighbours pass.
- **The margin**
  (`tests/unit/test_providers_silero.py::test_a_mid_speech_forget_costs_far_less_than_the_trailing_silence_budget`).
  A detector that needs a run of windows to find speech again after its
  state is cleared. The measured re-warm of one window survives, so does
  ten times it, and what would break it is a re-warm as long as the
  whole 22-window budget. The assertion is the margin, never a
  probability, per the caveat above.

Not verified here: nothing on hardware. The mechanism reproduces
deterministically against the committed code from the `8a709505` capture
(#70), and that capture is not in this repository, so the pins model the
mechanism rather than replaying the audio. A field run on the Waveshare
board is what would confirm the user-visible half.

## Files modified

- `vinga-server/src/vinga_server/providers/base.py`
- `vinga-server/src/vinga_server/providers/silero.py`
- `vinga-server/src/vinga_server/providers/mock.py`
- `vinga-server/src/vinga_server/runtime/turntaking.py`
- `vinga-server/src/vinga_server/runtime/pipeline.py`
- `vinga-server/tests/support/providers.py`
- `vinga-server/tests/unit/test_endpointer_echo.py` (new)
- `vinga-server/tests/unit/test_turntaking.py`
- `vinga-server/tests/unit/test_providers_silero.py`
- `vinga-server/tests/unit/test_session_reply_failures.py`
- `CHANGELOG.md`
