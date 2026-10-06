# Tuning when a turn ends

At the end of this guide you will know how a device listens while a
reply plays, what it takes for speech to interrupt a reply and when to
turn interrupting off for a board, and how to give one agent a patient
endpointer without slowing every other agent down.

The two interruption keys, `barge_in` and `barge_in_min_speech_ms`, are
in the server configuration reference under
[`server`](../reference/server-config.md#server), with their defaults.
`trailing_silence_ms` is an option of the `silero` VAD type, written
down in its example fragment,
[`vad-silero.yaml`](../../vinga-server/examples/vad-silero.yaml); an
agent's `vad` field, which picks the entry it listens with, is in the
domain configuration reference under
[Agent](../reference/domain-config.md#agent).

## Listening and barge-in

The firmware decides how it listens and the server follows. In `auto`
mode the device shuts its microphone off while a reply plays and sends a
fresh `listen start` afterwards. In `realtime` mode, which it picks when
its echo cancellation is on, it streams continuously and asks only once,
so the session here never stops listening: an utterance that ends while
a reply is playing cancels that reply and is answered instead. Talking
over the assistant stops it, which is what barge-in means.

```yaml
server:
  barge_in: true               # speech during a reply interrupts it
  barge_in_min_speech_ms: 500  # least classified speech that may interrupt
```

Turn it off for a board whose echo cancellation leaks the speaker back
into the microphone, typically a single-mic board, where a reply would
otherwise interrupt itself. Conversations stay multi-turn with it off;
only the interrupting goes. What says a board wants it: replies that
answer nothing at all, arriving just after the previous reply finished
speaking.

An interruption the endpointer hears is gated before it may cancel: a
reply is only cancelled on evidence of user speech. Speech shorter than
`barge_in_min_speech_ms` is a noise blip and never interrupts. Past
that floor, the reply pauses while ASR transcribes the interruption,
and only a non-empty transcript cancels; an empty one resumes the reply
where it stopped, about one ASR pass later. An interruption landing
while the reply is still transcribing merges with what it interrupted
instead, so one reply answers the whole sentence. Nothing is dropped
for arriving early in the playback: a refractory window used to do
that, and it turned out to catch only users finishing their own
sentence, since half a second of classified speech cannot come out of
the fraction of a second of reply the room has heard by then.
Every one of these decisions is a structured log event, which is what
the threshold is tuned from, apart from a confirmation whose
transcription failed: that resumes the reply, and what says so is the
`provider_failed` beside it and a plain log line. A manual
`listen stop` mid-reply is the user holding the button and speaking, so
with `barge_in` on it cancels unconditionally; with it off, that
utterance is dropped like any other that arrives during a reply.

**Where a turn ends is one number, and it belongs to the agent rather
than to the server.** The endpointer ends an utterance after
`trailing_silence_ms` of silence, 700 ms by default, which is the right
bound for question-and-answer speech. Dictation is slower: telling an
agent things to remember pauses between clauses for longer than that,
so the turn ends mid-sentence, the reply answers a fragment, and the
rest of the sentence arrives as an interruption to it. Raising the
bound for the whole server would put the added latency on every turn of
every agent to fix one agent's usage pattern, and there is no need to.
The bound is an option on the VAD provider entry, and an agent binds
the entry it wants:

```yaml
providers:
  vad:
    quick:
      type: silero
    patient:
      type: silero
      trailing_silence_ms: 1200

agents:
  quizmaster:
    vad: quick
  archivist:
    vad: patient
```

Each agent's endpointer is built from the entry that agent binds, and a
handover mid-conversation builds a fresh one from the incoming agent's,
so the two agents above listen differently inside the same session.
What a longer bound cannot do is tell a thinking pause from a finished
sentence: every pause costs its full length before the reply starts,
which is why this is per agent rather than raised everywhere, and why
reading more than silence is its own piece of work
([end-of-turn detection](../glossary.md#end-of-turn-detection)).
