# A reply is only cancelled on evidence of user speech

**Status:** Accepted

## Context

Barge-in as first built cancelled the reply in flight on a single VAD
trip: any utterance that endpointed while a reply was streaming
replaced it, in any phase of the reply. Field logs from the reporting
deployment ([#28](https://github.com/rafacm/samtal/issues/28)) showed
what that costs. Noise and playback bleed cut replies off seconds into
playback; the acoustic aftermath of the user's own utterance cancelled
replies in the post-ASR spin-up window and replaced them with silence;
and a barge-in landing while the reply was still transcribing destroyed
the head of the user's own sentence, a data-loss bug independent of
noise. The surveyed systems converged on the same lesson: LiveKit
Agents gates on a minimum sustained-speech duration and resumes speech
when an interruption produces no transcript, pipecat gates on
transcript content while the bot speaks, and upstream xiaozhi's non-AEC
path only ever aborts after a full transcript exists.

The underlying trade-off is real: cancelling fast on acoustics alone
gives the snappiest interruption, but every false positive kills a
reply the user wanted, and a killed reply cannot be un-killed. A pause
can.

## Decision

A reply is only cancelled on evidence of user speech; acoustics alone
can at most pause it.

Concretely: an endpointer-driven utterance end during a reply must
carry a minimum of speech-classified audio, must fall outside the
refractory window after playback starts, and, when nothing cheaper
decides it, must produce a non-empty transcript before the reply dies.
While that transcript is pending, the outgoing frames pause rather than
stop: audio halts just as fast either way, but a wrong decision now
costs one ASR latency of silence instead of a reply. The one exception
is deliberate action: a manual `listen stop` mid-reply is the user
holding the button and speaking, which is evidence enough, and cancels
unconditionally. A reply still inside ASR is a special case of the same
rule: what it holds is the user's own speech, so a barge-in there
merges the audio instead of destroying it.

## Consequences

- Interrupting the assistant costs slightly more than a VAD trip: a
  real interjection must sustain `server.barge_in_min_speech_ms` of
  speech, and one that needs transcript confirmation waits roughly one
  ASR pass before the old reply dies. That is the accepted price of
  never killing a reply on noise.
- Every gate decision is a structured log event (`barge_in`,
  `barge_in_suppressed`, `barge_in_merged`, with `speech_ms`), because
  the thresholds are field-tunable numbers and the retained logs are
  the observability surface
  (see [the observability ADR](2026-08-04-json-logs-are-the-observability-surface.md)).
- The frame pacer must be pausable and resumable without disturbing
  the cadence, which is why the pacing clock shifts by the pause
  duration on resume.
- Future echo defenses (audio-domain correlation, comparing a
  confirmed transcript against the assistant's own recent sentences)
  slot in as additional evidence checks behind the same rule rather
  than replacing it.

## Amendment: the refractory window is gone (2026-09-11)

The decision above stands whole; one of the concrete gates it named
does not. The refractory window, "must fall outside the refractory
window after playback starts", was itself a drop on acoustics alone,
which is the one thing the rule says a gate may not do, and it was
exempt only because the acoustics it read were believed to be the
device's own playback rather than the user.

The measurement says they cannot be. `server.barge_in_min_speech_ms`
is checked first, so nothing reached the window without at least half
a second of endpointer-classified speech; the primary board's playback
trails the server by roughly 760 ms (mic envelope against speaker
envelope, r = 0.60 to 0.74 at that lag over three replies, nothing at
lag 0); and the window was counted from the first frame this server
delivered, so its default second was at most about 240 ms of sound in
the room. Echo cannot supply 500 ms of speech out of 240 ms of
playback. The field agreed before the arithmetic did: every refractory
suppression on record, four in 48 h of household use and five in a
later commissioning window, was a user finishing their own sentence.

So the rung is removed and the utterance falls through to the
confirmation arm (#80), which is this record's own rule applied to the
one gate that was exempt from it: a wrong pause costs one ASR latency,
a wrong drop costs the user's sentence. `server.barge_in_refractory_ms`
is removed with it, and `barge_in_suppressed` loses its `refractory`
reason. What is left of the ladder is the speech floor, the
merge-mid-ASR special case and the transcript confirmation, all three
of which the decision above already justifies.
