# A regression suite for conversational quality

**Date:** 2026-08-08

Unit and integration tests prove the server does what its code says.
They cannot prove a conversation feels right: that replies come when a
person expects them, that interrupting works, that a quiet "yes,
please" is heard. Those properties only exist on a real device, in a
real room, with a real person talking, so they are verified by field
tests: structured on-device sessions, recorded and analyzed after the
fact.

This page turns what the first field-test rounds learned into a
starting point for anyone setting up and analyzing such a round, and
it names the central idea: treated with a little discipline, field
tests stop being one-off debugging expeditions and become a
**regression suite for conversational quality**. The same tests, run
on a changed system against a recorded baseline, say whether the
change helped, hurt, or did nothing, in the only terms that matter to
a user.

The concrete protocols live in the tracker (round 1: issue #48, now
closed; round 2: issue #73). This page is what stays true between
rounds.

## The shape of a turn

Every test in the suite probes some step of the same loop. The
step-by-step teaching tour with diagrams is in
[system-overview.md](system-overview.md); this is the compact version,
with the structured event each step emits, since those events are what
the analysis reads. The events named below are the ones a turn walks
through; what each one carries, and the whole set of them, is in
[the event schema reference](reference/events.md), generated from the
declarations.

1. **Session open.** The device connects over WebSocket and is bound
   to its agents; `session_open` records the agent, the device, and
   the build revision, so every recording is attributable.
2. **Listening.** The device streams its microphone continuously as
   Opus frames (realtime mode); the server decodes them to PCM.
3. **Endpointing.** The VAD scores each frame for speech; the
   endpointer accumulates the evidence and declares the utterance
   over after enough trailing silence. Continuous `vad` records carry
   what it believed, frame by frame.
4. **Transcription.** The utterance audio goes to the ASR; `heard`
   carries the utterance duration and the language the engine heard,
   and the transcript itself is on the conversation store's turn (the
   events carry no conversation text).
5. **Generation.** The LLM produces the reply, possibly over several
   rounds when tools are called; each round emits `llm_round` with
   its duration and time to first token. A `switch_agent` call emits
   `handover`.
6. **Synthesis and playback.** The reply is synthesized sentence by
   sentence (with lookahead) and paced to the device as Opus frames;
   `speaking_started` marks the first audible frame, `replied` the
   completed reply.
7. **Barge-in.** Speech that endpoints while the assistant is
   replying goes through a gate ladder; `barge_in` marks a confirmed
   interruption, `barge_in_suppressed` a rejected one, with the
   reason.
8. **Session close.** A button press, the idle timeout
   (`session_idle`), or a session limit; a clean close finalizes the
   capture.

Any conversational failure a field test can surface is a failure of
one of these steps, and the first analysis question is always which
one. The three failure classes found in round 1 map cleanly: a reply
that never starts (step 5 stalled with nothing bounding it), speech
never detected (step 3 saw nothing), speech detected but discarded
(step 4 returned nothing).

## What a field test needs before anyone leaves the desk

A session that cannot be attributed or reproduced is an anecdote.
The preflight below is what makes it evidence.

- **A pinned stack.** Providers (LLM, ASR, TTS, VAD), voices, and
  firmware version, recorded before the run. Calibration findings do
  not transfer across stacks (see the layers below), so the stack a
  number was measured on is part of the number.
- **A confirmed build.** `/healthz` reports the revision; it must
  match the image the run believes it is testing.
- **Capture on.** Per-session recording (see below). Capture is a
  deliberate, temporary state: it records room audio, so it is turned
  on for the round and off when the round ends.
- **Self-labelling sessions.** The first thing said in every session
  is the test number ("Starting test three"). Round 1 skipped this in
  8 of 11 sessions and attributing them needed forensics.
- **A marker phrase.** One fixed phrase ("banana, banana, banana"),
  said aloud the moment something misbehaves. Three repetitions
  survive a wrong ASR language pin and are findable in the waveform
  by eye. Round 1 never used it and paid for that in scrubbing time.
- **One session per test**, opened and closed with the conversation
  button, never mid-reply (a device abort bypasses the barge-in
  ladder and contaminates the test).
- **A control.** A quiet ordinary session on the same build and day
  as the interesting ones. Without it, "the room was noisy" and "the
  build regressed" cannot be told apart.

## What a session yields

Each captured session produces three files, together sufficient to
re-derive everything the analysis needs, and a directory of per-turn
clips cut for the analyses that need a turn's audio on its own:

- **`<session>.wav`**: stereo, 16 kHz. Channel 0 is the microphone
  as received, channel 1 what was paced to the speaker. Having the
  reply as its own channel is what turns echo measurement into a
  cross-correlation instead of a guess.
- **`<session>.jsonl`**: the event track, every structured event with
  a session-relative timestamp, including the continuous `vad`
  records that never reach the server log.
- **`<session>.json`**: the manifest: device, firmware, resolved
  provider entries verbatim, completeness flag. The manifest is what
  makes a recording comparable months later, because it answers
  "what exactly produced this" without asking anyone. At close it
  also lists the session's turns.
- **`<session>.turns/`**: mono 16 kHz clips per turn, named by the
  utterance id its `turn_started` event carries: a heard clip, and,
  when reply audio was paced, a reply clip.
  `<utterance>.heard.wav` is the exact audio the turn's ASR was
  handed, which is what a word error rate has to be measured on: not
  a slice of channel 0, which holds the frames the guards dropped and
  no record of where the endpointer's pre-roll or a merged
  utterance's two halves began. `<utterance>.reply.wav` is channel 1
  over the stretch the turn's reply was paced out, barge-in truncation
  included; the manifest records that stretch as `reply_from_ms` and
  `reply_to_ms`, so the clip can be checked against the WAV.

Analysis starts from the event track (reconstruct the turn timeline,
find the moment something went wrong), drops to the WAV only where
events run out (was there really speech the VAD missed?), and uses
the server log for anything session-spanning.

## The three layers, by how they age

Findings from a field round age at three very different rates, and
knowing which layer a finding lives in is what tells you what a
provider or hardware change invalidates.

### The instrument (stack-independent)

The machinery for asking questions, valuable regardless of every
provider and device choice:

- The capture format, the event vocabulary, and the manifest.
- The protocol discipline above (announcements, marker, control
  session).
- The analysis methods, with their validation. The echo measurement
  is the model: cross-correlation over windows where the assistant
  plays and the user is silent, proven against a synthetic injected
  echo before its null result was believed. Both live in
  [`scripts/`](../scripts/): `echo_leakage.py` is the measurement,
  `echo_leakage_control.py` the positive control that must pass
  before any null result is trusted.
- The failure taxonomy: pipeline wedged on a provider, speech never
  detected, speech detected but transcribed to nothing. Any stack
  can fail in these ways; tests that probe them are permanent.
- The architectural invariants the fixes encode: waits on providers
  are bounded, and a failed round degrades to a turn that ends, never
  a wedged session. What that turn sounds like has moved: it used to
  be silence, and a deployment that leaves the `fallback` section on
  now hears a short fixed phrase saying the reply failed. The
  invariant is that the turn ends and the session goes back to
  listening; whether it says so is configuration.

A stack change does not touch this layer; it is what measures the
change.

### The interaction layer (survives provider swaps)

Findings about how people talk and how this class of device hears,
independent of which cloud is on the other end:

- Short acknowledgements ("yes, please") are the turns most at risk,
  simultaneously the hardest clips for an ASR and the ones a user
  expects an instant reaction to.
- Mid-sentence thinking pauses fight the endpointer; the trailing
  silence bound decides whose sentence wins.
- Follow-up timing interacts with reply completion and the barge-in
  gates.
- Echo behaviour is a property of the device, not the voice: on
  hardware with acoustic echo cancellation the assistant's own voice
  comes back below the ambient floor, whoever is speaking.

This layer survives swapping any provider. It does not survive a
change of device (different or absent echo cancellation) or a
redesign of the input pipeline, which is why such changes re-run more
of the suite.

### The calibration (the current stack, and what to optimize on it)

Every tuned constant and every measured provider behaviour. Valid
precisely as long as the stack that produced it:

- Timeouts chosen against a provider's latency distribution (the
  first-token watchdog default).
- Workarounds for a provider's failure modes (the transcription
  prompt echoed back as the transcript, and the retry that recovers
  real speech from it).
- Language pinning behaviour, measured per ASR model.
- Endpointer and barge-in thresholds, tied to the VAD, the
  microphone, and the rooms measured.

Once a deployment settles on a stack, this is the layer with room to
optimize: the distributions the captures produce (first-token times,
utterance speech_ms on fired versus suppressed barge-ins, ASR retry
outcomes) are exactly the data those constants should be tuned
against, per stack, not in general.

## Which loop answers which ASR question

Since a capture keeps each turn's heard clip, the exact audio its ASR
was handed, two loops answer questions about the ASR. The **field
round** is the one this page is about. The **dataset loop** takes
heard clips harvested from field rounds, pairs each with a
hand-corrected expected text, and scores ASR candidates against them
offline, in minutes. The failure this section exists to prevent is
not that anyone picks one loop over the other. It is that the cheap
loop quietly absorbs questions belonging to the expensive one,
because a scoring run costs minutes and a field round costs a person,
a room and a day.

### Supplier and consumer, not rivals

The field round is the only source of dataset items: a clip exists
because a session ran in a real room, on a real device, with a real
person talking, and nothing else produces one. The dataset is what
keeps later field rounds short: questions about model quality are
settled offline before anyone goes into the room, so the room is
spent on what only the room can test.

### The decision rule, by example

The dataset answers questions about what a model does with the audio
it was handed, because the heard clip is exactly that audio:

- Which ASR model transcribes this better.
- Does a prompt hint change the result.
- Does pinning the household's languages beat auto-detect.

The field round alone answers these, because every one of them
happens where no turn exists (before a clip's first sample, between
two clips, or across the exchange as a person lived it), and
therefore where no dataset item can:

- Did the VAD miss speech.
- Was an onset clipped.
- Did barge-in fire when it should have, and only then.
- Is the assistant's own voice bleeding back into the microphone.
- Did the endpointer chop a dictation pause into two turns.
- Does it feel right.

### How an item is born

An item is harvested from a field session: one turn's heard clip, the
transcript the production ASR made of it, and the model that made it.
It is attributed to that session's manifest, whose resolved provider
entries are the stack verbatim, and to the round it came from, so a
word error rate is never quoted without the room it was measured in.
In the layers above, the clips are instrument (they are what measures
the next ASR change) and every number derived from them is
calibration, valid for the stack and the room that produced it.

On the host the parts meet by utterance id: the clip is
`<session>.turns/<utterance>.heard.wav`, the conversation store's turn
row carries the same id in its `utterance` column with the transcript
beside it, and the manifest names the model. In the telemetry backend
they can meet on the turn's own trace with no joining at all, but only
with two exports on, and neither implies the other.
`server.telemetry.export_audio` sends each turn's clips to its trace
and the manifest to the session's trace, audio and metadata only. The
transcript reaches the turn only with `server.conversations` on and
storing text and `server.telemetry.export_transcripts` on. What each
export carries, and on what terms, is in
[Exported capture media](architecture/observability-surfaces.md#exported-capture-media)
and
[Exported transcripts](architecture/observability-surfaces.md#exported-transcripts).

An item's audio is what one device, microphone, VAD and endpointer
produced. It survives an ASR change, which is what it is for. After a
device change or an input-pipeline redesign it still compares models
on the audio the old input produced, which is no longer what the ASR
is handed, so the new input's ASR questions wait for a harvest of its
own.

A turn whose transcript came back empty keeps its heard clip too,
because the capture writes it when the turn starts, before the ASR
runs. So a lost clip can be harvested and corrected like any other,
and the dataset can say how a candidate does on it. It cannot say how
many clips the pipeline loses; that is the loss rate, and it is the
field round's (see the table below).

### Who corrects the expected text

The production transcript is the thing being measured, so it cannot
also be the answer. A person listens to each heard clip and writes
down what it holds, best done by whoever ran the round, who knows what
was said and in which language. The text is what is audible in the
clip, not what the speaker meant: a word cut off before the clip's
first sample is a clipped onset, a field finding, and scoring a model
against it would charge the model for the pipeline.

This is the dataset loop's real human cost, and it is paid once per
item, when the item is harvested, not once per comparison: every later
comparison, whichever model or option it tries, scores against the
same corrected text.

### Where the durable copy lives

Nowhere, until an operator copies it out. Both copies of an item are
under a retention the dataset does not control. The capture directory
prunes its oldest sessions whole, clips included, to stay inside
`server.capture.max_total_mb`. The telemetry backend keeps media for
as long as its own retention policy says, which is configured there
and which vinga neither sets nor sees. A curated item (the heard clip,
its corrected text, and its session's manifest) has to be copied to
storage the operator keeps before either retention removes it.

### What the dataset loop may never claim

The list is closed: these are the between-turn failure classes and the
one number counted over them, and a failure class found later that
happens where no turn exists joins it in the change that finds it.

- **That the VAD caught all the speech.** Speech it missed never
  became an utterance, so it has no clip.
- **That onsets are intact.** What was cut off before a clip's first
  sample is in channel 0 of the session WAV and in no item.
- **That barge-in fires when it should, and only then.** A candidate
  the gate rejected never starts a turn and has no clip, and whether
  one should have fired depends on the reply it spoke over, which a
  heard clip does not hold.
- **That the assistant's voice does not bleed into the microphone.**
  Echo is measured where the assistant plays and the user is silent,
  which are exactly the stretches no utterance covers.
- **That the endpointer leaves a dictation pause alone.** A chopped
  pause yields two turns whose clips each look complete, and the
  silence it was chopped at lies between them, in neither.
- **That it feels right.** Feel is timing, voice and interruption as a
  person in the room lived them, and a clip holds none of it.
- **That the pipeline loses fewer short clips.** The loss rate is
  counted over every utterance spoken in the room, including those
  that never became a turn, and the dataset holds only turns.

## What a change invalidates

| Change | Re-measure | Still valid |
| --- | --- | --- |
| LLM provider or model | First-token distribution, watchdog default | Everything else |
| ASR provider or model, answered by the dataset loop | Which model transcribes the harvested items better (word error rate), prompt behaviour, language pinning against auto-detect | Interaction layer, instrument, the dataset's items and their corrected text |
| ASR provider or model, answered by the field round | Short-clip loss rate, which is not word error rate on short clips: loss rate counts clips that produced no usable transcript at all, including speech the VAD never segmented and transcripts the echo retry discarded. The first never has a dataset item and the second has no transcript to score, so word error rate measured on the survivors improves exactly as the pipeline loses more clips | Interaction layer, instrument |
| TTS provider or voice | Reply pacing feel; echo only if the device lacks AEC | Interaction layer, instrument |
| Device or firmware | Echo leakage, VAD and barge-in thresholds, listening-mode behaviour | Instrument, most of the interaction layer |
| Input-pipeline redesign | Endpointing findings, barge-in ladder behaviour | Instrument |

The working procedure for any such change: re-run the relevant
subset (the quiet baseline, the acknowledgement test, one noisy
session; the echo measurement when the device changed) and compare
against the recorded baseline. For an ASR change, the dataset
loop's row runs first, offline, and the field round that follows
carries only its own row. The manifests make every past recording
attributable to its exact stack, so the comparison is always
available.
