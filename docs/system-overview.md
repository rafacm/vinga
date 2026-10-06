# System overview

A maintained explanation of one conversation turn, from the wake word
to the spoken reply. It follows the two hand-drawn diagrams the
project is described with and explains each concept, and the problem
that concept solves, before using its acronym, so it can be read
start to finish by somebody who has never run vinga. It describes the
system as it is today and changes when the pipeline does.

[`glossary.md`](glossary.md) is the same vocabulary arranged for
looking one thing up; this page is the tour.
[`architecture/README.md`](architecture/README.md) is the index for
the pages that say what a change to any of this is held to.

## On this page

- [The overview](#the-overview): the whole system in one picture.
- [One conversation turn, in detail](#one-conversation-turn-in-detail):
  the eleven steps from a spoken sentence to a spoken answer, in two
  flows, and the one kind of sentence a reply never speaks.
- [What this diagram leaves out](#what-this-diagram-leaves-out):
  interrupting a reply, and which stages leave your machine.
- [Transports](#transports): the one transport a device and the server
  speak, and the two upstream names that are not it.

## The overview

[![vinga architecture overview](architecture/diagrams/excalidraw/vinga-architecture-overview.png)](architecture/diagrams/excalidraw/vinga-architecture-overview.excalidraw)

The picture the root README leads with: a human talks to an ESP32-S3
device, the device talks to your vinga-server over one WebSocket, and
the server talks to whatever providers you configured. Everything that
follows is that loop, zoomed in.

## One conversation turn, in detail

[![vinga conversation flow, detailed](architecture/diagrams/excalidraw/vinga-conversation-flow-detailed.png)](architecture/diagrams/excalidraw/vinga-conversation-flow-detailed.excalidraw)

The diagram reads top to bottom as one turn of conversation: flow 1
(blue) carries your speech up to the language model, flow 2 (green)
carries its reply back down to your ears. Dashed gray lines are the
control and tool messages riding the same connection. Before the first
turn, the device has already fetched its configuration from the server's
over-the-air (OTA) endpoint, opened the WebSocket with the token that
response contained, and agreed on audio codecs in a `hello` exchange;
that setup is the thin note at the top of the diagram, and the
[xiaozhi research notes](xiaozhi-notes.md) document it key by key.

### Flow 1: from your voice to the language model

1. **You speak.** The turn starts with a wake word (spotted on the
   device by Espressif's [ESP-SR](https://github.com/espressif/esp-sr)
   models) or a button press; either opens the session and starts the
   microphone.

2. **The microphone captures audio, minus the assistant's own voice.** A
   speaker and a microphone centimeters apart mean the microphone hears
   whatever the assistant is saying, and a naive assistant would answer
   itself in an endless loop. The fix is
   [acoustic echo cancellation](https://en.wikipedia.org/wiki/Echo_suppression_and_cancellation)
   (AEC): subtracting the known playback signal from what the microphone
   picks up. On the
   [boards vinga targets](https://docs.waveshare.com/ESP32-S3-Touch-LCD-1.54)
   this runs in hardware (an ES7210 microphone ADC paired with an ES8311
   codec), which is what makes barge-in (interrupting the assistant
   mid-reply) possible at all.

3. **The device compresses the audio with Opus.** Raw 16-bit audio at 16
   kHz is 256 kbit/s, wasteful over Wi-Fi from a small embedded chip.
   [Opus](https://opus-codec.org/) is an open codec designed for live
   speech: it compresses each 60 millisecond frame to a few hundred
   bytes with imperceptible loss and almost no delay.

4. **The server receives frames and decodes them.** The device and
   server share one
   [WebSocket](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API),
   a connection that starts as an ordinary HTTP request and then stays
   open for both sides to send at any time; that gives the device a
   single outbound connection (friendly to home routers) carrying binary
   audio and JSON control messages alike. The server decodes each Opus
   frame back to
   [pulse-code modulation](https://en.wikipedia.org/wiki/Pulse-code_modulation)
   (PCM), the plain stream of samples every later stage works on.

5. **The server notices when you stop talking.** There is no
   push-to-talk button in a natural conversation, so the server must
   hear the difference between a pause for breath and the end of your
   sentence. That is voice activity detection (VAD):
   [Silero VAD](https://github.com/snakers4/silero-vad), a small local
   neural network, scores each chunk as speech or silence, and an
   endpointer on top waits for enough trailing silence to call the
   utterance finished. It also trims the recording down to the speech
   plus a short pre-roll, so the long silences of an open microphone
   never reach the next step.

6. **The utterance becomes text.** Automatic speech recognition (ASR)
   turns the trimmed audio into a transcript. vinga's local engine is
   [faster-whisper](https://github.com/SYSTRAN/faster-whisper), a
   reimplementation of OpenAI's
   [Whisper](https://github.com/openai/whisper) model that runs quickly
   on ordinary CPUs, and the same stage runs through the OpenAI
   transcription API instead if you configure it, which on a small CPU
   is both quicker and better at a noisy room in a language that is not
   English. The transcript is also sent back to the device (the dashed
   `stt text` line), so the display can show what was understood.

7. **The language model decides what to say and do.** The transcript,
   the active agent's prompt, what it remembers and what this
   conversation is keeping, and a list of tools go to a large language
   model (LLM), local via [Ollama](https://ollama.com) or remote
   (Anthropic or any OpenAI-compatible endpoint). A model alone can only
   produce text, so tools are how it acts: the
   [Model Context Protocol](https://modelcontextprotocol.io) (MCP) is an
   open standard for offering such tools, and vinga wires it in on both
   sides. External MCP servers add whatever capabilities you attach; the
   device itself offers its own controls (volume, brightness, screen) as
   MCP tools over the same WebSocket. The server loops: the model asks
   for tools, results go back in, until the model settles on a reply,
   which it streams out sentence by sentence.

### Flow 2: from the model's words to your ears

8. **Each sentence is spoken as soon as it exists.** Text-to-speech
   (TTS) synthesis runs per sentence, locally with
   [Piper](https://github.com/OHF-Voice/piper1-gpl) or through OpenAI or
   ElevenLabs for a better voice, so the first sentence is playing while
   the model is still writing the rest. Waiting for the full reply first
   would add seconds of dead air to every answer. The next sentence is
   then synthesized while the current one is still playing: frames are
   paced to realtime, so a sentence takes about as long to send as it
   does to hear, and synthesizing only after the previous one finished
   put every sentence's time to first byte on the speaker as silence
   (measured at 617 ms and 520 ms between the sentences of a
   three-sentence reply, and heard on a board as hiccups in the
   assistant's voice). One kind of sentence is not spoken: a model that
   writes a tool call into its own prose instead of issuing it would
   have the JSON read out loud, so a sentence shaped like a call to a
   tool this reply offered is dropped, with an event saying it happened
   ([below](#when-a-model-writes-a-tool-call-into-its-speech)).

9. **The audio is resampled, re-encoded, and paced.** The voice's sample
   rate is converted to the 24 kHz the server announced in the `hello`
   exchange, encoded back into Opus frames, and sent at playback speed
   rather than as fast as the network allows. Pacing matters because the
   device has a small playback buffer: flooding it would overflow
   memory, and a reply queued seconds ahead could not be cut short
   cleanly when you barge in.

10. **The device plays the reply.** Frames are decoded back to samples
    and fed to the speaker through the same audio codec chip from step
    2, while the display shows each sentence as it starts (the
    `tts sentence_start` messages).

11. **You hear the answer, and the loop closes.** After the final
    `tts stop` message the device starts listening again on its own
    (auto mode), so the next thing you say begins the next turn at step
    1 with no wake word needed. A realtime device never stopped
    listening in the first place, and a conversation nobody comes back
    to is hung up after `server.limits.idle_timeout_s` (two minutes by
    default), because otherwise its microphone would stream to the
    server for the whole hour the session is allowed.

#### When a model writes a tool call into its speech

A reply is spoken sentence by sentence, and every sentence is spoken
except one kind: a sentence shaped like a call to a tool this reply
actually offered. Some models, small local ones especially, write their
calls out as ordinary prose instead of issuing them, and read aloud
that is JSON in the assistant's voice on the one user-facing surface
with no filter on what a model produced.

The check is narrow, and it is anchored to the tools of the reply it is
in rather than to "looks like JSON": someone asking an agent to explain
a JSON snippet is a real conversation and gets an answer. A sentence is
withheld when it contains a complete JSON object that either names one
of the offered tools, in its own `name` or in the `name` under a
`function` key, or whose keys all fall inside the properties one
offered tool declared. The second is the shape the field actually
produces, where the name never made it out and only the arguments did
(`{"volume":"100"}`), so nothing about it can be matched by name; keys
are compared and values never are, since the observed one had the wrong
type for the schema it belonged to.

The sentence goes whole and the reply carries on. It is not spoken, not
shown, not added to the conversation this server keeps, and not stored,
and no event or log line carries a byte of it: what says it happened is
a `sentence_withheld` event, carrying its length in characters and
which tool it was shaped like, under the same naming rule `tool_call`
follows, or `unknown` where its keys fit more than one offered tool.
The one place it does go is the opt-in trace export of what a model was
sent and wrote (`server.telemetry.export_llm_input`), which captures a
model's output before any of this filtering. A reply left with nothing at all to say, every sentence of it
withheld, says the agent's fallback phrase
([When a reply fails](run/slow-and-failed-replies.md#when-a-reply-fails))
with the reason `nothing_sayable`, because the alternative is the
silence that phrase exists to end.

**One bound, stated rather than hidden.** The test is on each sentence
as it arrives, because a sentence has already been handed to the voice
by then. Sentences are cut at newlines, so a pretty-printed call
arrives as a handful of fragments no JSON decoder can read, and those
fragments are spoken. Closing that would mean holding sentences back to
see what follows them, which puts a stall in front of live speech at
every ordinary `{` in every reply. The residue is left visible through
the event instead: an operator seeing `sentence_withheld` repeatedly,
or hearing the fragments, is reading a fact about the model this
deployment configured. The same event is what makes the cost of the
key-matching rule visible, since an agent reading out a JSON example
whose keys mirror an offered tool is withheld too.

## What this diagram leaves out

It draws one turn going well, which is what makes it readable, and two
things that matter are therefore not on it. Both have their own picture
in [`architecture/diagrams/plantuml/`](architecture/diagrams/plantuml/).

**Interrupting a reply.** Speaking while the assistant is speaking
cancels it, but only on evidence that you really did speak: acoustics
alone, mid-reply, are as often the room or the assistant's own voice
leaking past the echo cancellation. Too little speech is a noise blip
and is ignored, an interruption that lands while the reply is still
being transcribed merges with what it interrupted, and anything else
pauses the reply and asks the transcriber before deciding, so a wrong
guess costs one transcription rather than the answer. The
branches are drawn in
[`barge-in-decision`](architecture/diagrams/plantuml/vinga-barge-in-decision.png).

**Which of these stages leaves your machine.** Every provider declares
how far session data given to it travels (`host`, `network` or
`internet`), `server.data_boundary` declares the outermost reach you
allow, and a build that exceeds it is refused at startup, so a server
that starts is one that stays inside the boundary you drew. Some types
cannot answer for themselves, an OpenAI-compatible base URL being
equally a vendor, a model server on your network, or an Ollama on
localhost, and those must say so explicitly.
[`architecture-overview`](architecture/diagrams/plantuml/vinga-architecture-overview.png)
colours every provider by that declaration.

## Transports

**WebSocket only.** The device speaks Opus over one WebSocket, and that is
the only transport vinga-server implements.

Upstream supports a second one, **MQTT plus UDP**: the OTA reply carries an
`mqtt` section instead of a `websocket` one, control messages go over MQTT
and audio over a separate UDP stream. vinga-server never sends an `mqtt`
section, so devices always take the WebSocket path. The OTA reply is
where a transport is chosen, per device, by which of the two sections
it carries.

**WebRTC is not an upstream transport.** The only WebRTC reference upstream
is the WebRTC/NSNet noise-suppression algorithm in the device's audio front
end (and it ships disabled). A WebRTC transport would be new work on both
sides, not adoption of something the firmware already speaks.
