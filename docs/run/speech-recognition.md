# Choosing how an agent hears

At the end of this guide you will have picked the speech recognition
engine an agent listens with, with the measurements behind the choice
in hand, and, on OpenAI's transcription, set the vocabulary and the
languages so that what a household says comes back as what was said.

The options of both types, each with its default, are in the domain
configuration reference under
[`asr` options for `type: faster_whisper`](../reference/domain-config.md#asr-options-for-type-faster_whisper)
and
[`asr` options for `type: openai`](../reference/domain-config.md#asr-options-for-type-openai).
This guide is the measurements behind choosing between them and
setting them.
Which engines exist and what each needs installed is
[Choosing providers](providers.md).

## Choosing how it hears

The ASR stage has two types, and the trade between them is not the one
the voices have. Going to the cloud for a voice costs latency; going
to the cloud to listen mostly saves it, because a transcription is one
round trip against someone else's accelerator instead of a CPU decode
on yours. Median of five per utterance, one machine and one network,
so the columns are comparable:

| Utterance | `faster_whisper` small | `gpt-4o-mini-transcribe` | `gpt-4o-transcribe` | `whisper-1` |
| --- | --- | --- | --- | --- |
| "The kitchen light is now off." (1.8 s) | 1688 ms | 536 ms | 627 ms | 1076 ms |
| "Hello, I am your vinga assistant..." (3.6 s) | 1781 ms | 658 ms | 887 ms | 1177 ms |
| "Hej, jag är din vingasassistent." (2.1 s) | 1743 ms | 545 ms | 607 ms | 1101 ms |

Read that against your own hardware before believing it: the local
column is an int8 CPU decode on a laptop, and a machine with a GPU
would change the answer. The cloud column would not move much, since
almost all of it is the round trip.

**The same measurement on a real device narrows the gap a long way.**
Taken from the server's own log on a Waveshare ESP32-S3, `heard` minus
the end of the utterance, so it is the whole stage and not just the
call:

| | on the board | on the desk |
| --- | --- | --- |
| `gpt-4o-mini-transcribe` | 642, 647, 825 ms | 536 to 658 ms |
| `faster_whisper` small | 964 ms (one sample) | 1688 to 1781 ms |

The cloud figures held; the local one did not, which says the desk
number for `faster_whisper` was measured under contention and flatters
the cloud. Treat the first table's local column as a worst case and
this one as the honest comparison, and measure your own either way.

Accuracy is the other half, and it separates them further, *provided
the language is pinned*. The caveat is not a footnote: see "Set
`language`" below, because unpinned on a real device the cloud engine
was the worse of the two. Synthesized speech under white noise,
standing in for a far-field microphone:

| Signal to noise | `faster_whisper` small | `gpt-4o-mini-transcribe` | `gpt-4o-transcribe` |
| --- | --- | --- | --- |
| clean | exact | exact | exact |
| 10 dB | Swedish already wrong | exact | exact |
| 5 dB | Swedish wrong | exact | exact |
| 0 dB | Swedish is a different sentence | exact | exact |

English survived everywhere; Swedish is where the local `small` model
gives up, turning "vingasassistent" into "samhållssystem" at 10 dB
and the whole sentence into unrelated English at 0 dB. A larger local
model closes some of that, at a latency cost the table above already
shows there is no room for.

That table is synthesized speech, which is cleaner than a room. On the
device, with both engines pinned to Swedish, the cloud engine was still
the better of the two but neither was perfect:

| Said to the board | `gpt-4o-mini-transcribe` | `faster_whisper` small |
| --- | --- | --- |
| "Vad heter Sveriges huvudstad?" | exact | "Vad heter Sveriges Hubbetsstad?" |
| "Vad heter din vingasassistent?" | "Vad hette ditt vingasassistent?" | "Men hejter den vingaassistenten." |

**None of the cloud columns above is what you get by default, which is
worth saying plainly.** Every one of those measurements was taken on the
`gpt-4o` pair or on `whisper-1`, before `gpt-transcribe` became this
type's default, and none was re-run against it. So read them as the
shape of a cloud transcription against a local decode rather than as a
number this server promises, and measure your own, which is the advice
this whole section already gives. What is known about the default is
narrower and recorded where it belongs: it reports the language it
heard, which is the section below, and OpenAI publishes it at $0.0045
per minute of audio against $0.006 for `whisper-1`, which is
[the cost table](conversation-cost.md#the-definitions-worth-entering)
in the cost guide.

What the local engine still wins: it is the only one that keeps the
audio on your host, the only one that says how sure it was of the
language it heard, and the only one that can hold a session to that
language. It is also free per utterance, which a busy household
notices. Which language it heard is no longer one of them: the cloud
type reports that too, on a model that answers it and where nothing
named a language. The section below says when that is.

## OpenAI transcription

```bash
vinga-server config provider set asr ears -f - <<'YAML'
type: openai
api_key_env: OPENAI_API_KEY
prompt: vinga
YAML
```

Keys are named, never written, exactly as for the
[TTS types](voices.md#elevenlabs).

The options, each with its default and what it accepts, are in the
domain configuration reference under
[`asr` options for `type: openai`](../reference/domain-config.md#asr-options-for-type-openai).
What the reference does not say is below: why `prompt` holds
vocabulary and nothing imperative, why `language` is worth setting,
which models were measured to accept `languages`, and that only
OpenAI's own host requires `api_key_env`.

**This `prompt` is not the agent's prompt.** Two unrelated options share
the name: the one here is a list of words the transcriber should expect,
and the one under `agents:` is the agent's instruction sent to the LLM.
This one is a hint about vocabulary, not a request for behaviour, which
is exactly what makes the failure below surprising.

**Set `prompt`, and keep it to vocabulary.** An unfamiliar proper noun
is the one thing this type reliably gets wrong, and the prompt is what
fixes it: under noise, "vinga" came back as "sample" without it and as
"Vinga" with it. It fixes vocabulary, not language, so it cannot
compensate for the setting below: on the board, `prompt: vinga` still
produced "samstal" until `language` was pinned, and produced
"vingasassistent" exactly once it was.

**Never put anything the assistant could act on in it.** On short or
low-content audio the model hands the prompt back as the transcript
instead of hearing anything, reliably: 45 out of 45 clips of room tone
under a second came back as the prompt word for word. A prompt of plain
vocabulary makes that harmless noise. A prompt naming your agents makes
it an instruction, and in a field session it was one: a 0.9 s utterance
transcribed as `vinga, Oliver, Greta, Mateo`, and the model read the
agent names as a request and handed over to an agent nobody had
asked for. The server never hands a transcript that is the prompt and
nothing else (trimmed, case-insensitive, and ignoring sentence-final
punctuation the model added) to the LLM as if spoken. Nor does it treat the echo as
proof of silence, because a field test caught that reading swallowing
real speech: nine echoes in two days of testing, every one on a clip
under two seconds, two of them a user saying "yes, please" and being
ignored.
An echoed clip is transcribed once more with the prompt withheld; a
real short answer survives that retry and is heard normally, genuine
silence comes back empty and is discarded, and each trip logs one
`asr_prompt_echo` event saying which it was. The rule stands anyway:
wake words, agent names and anything imperative do not belong here.
Recognising an agent's name when it is genuinely spoken is worth less
than never acting on one that was not.

**Set `language` unless the household speaks English.** This is the
one setting a device checkpoint changed our mind about. On clean audio,
leaving it unset costs nothing: recognition is multilingual either way,
and detection happens inside the model rather than as a separate pass
you pay for. On a real board in a real room it is a different story.
Unpinned, Swedish came back as English-shaped nonsense:

| Said to the board | Unpinned | `language: sv` |
| --- | --- | --- |
| "Vad heter Sveriges huvudstad?" | "Hat hetas verigezogistad." | exact |
| "Vad heter din vingasassistent?" | "Wat hat er dien samstal asynstind?" | "Vad hette ditt vingasassistent?" |

The audio was not the problem; the language choice was. Far-field mic
audio through Opus gives detection much less to go on than a clean
file, and the model appears to fall back on English phonetics. Pinning
fixed it outright, and no `prompt` rescued it while unpinned.

**A household that speaks more than one names them all.** `languages:
[sv, en]` describes a set the model chooses inside, where `language`
describes one it is told, and it is the middle answer between pinning
the wrong language and pinning none. Three cases, and the third is the
one most deployments skip:

- **One language spoken here.** Set `language`, which is what the
  device session above earned. The report goes quiet, and the trade is
  in the next section.
- **Two or three spoken here.** Set `languages`, and leave `language`
  out: the two cannot both be set, and writing both is refused when the
  entry is written rather than discovered on a conversation. One clip
  says it helps, which is the clip this whole feature started from:
  spoken German "Hallo" came back as "Hello." unhinted and as "Hallo."
  with `[de, en]` set. That is one clip and not a table, so read it as
  the reason to try the option rather than as a number. What you
  definitely keep is the report, which now says which of the declared
  languages the model chose per turn.
- **You do not know yet.** Leave both unset for a while on a deployment
  whose transcripts already look right, and read the codes that arrive.
  That is the only one of the three that measures rather than tells.

`languages` is `gpt-transcribe`'s, as far as anyone here has measured:
on 2026-09-13 it accepted the option, and `whisper-1` and
`gpt-4o-mini-transcribe` each answered 400 to it in their own words.
`gpt-4o-transcribe` and compatible endpoints were not tested and decide
it for themselves. Nothing checks this at startup, because applying an
entry contacts no endpoint: one naming a model that refuses the option
applies cleanly and then fails on the first real transcription, so the
model and the option are worth reading together. A list of exactly one is
accepted, and it is a pin: the model hands a single language straight
back whichever way it was named.

Setting it is a hint rather than a hard pin on the two models that were
measured: a `gpt-4o` model given Swedish audio and `language: en`
answers in Swedish anyway, and `gpt-transcribe`, the default, did the
same on 2026-09-13 with German speech sent as Swedish and transcribed
as German. That says nothing about `whisper-1` or about a compatible
endpoint, which decide it for themselves and were not measured. The
local engine would have forced the wrong language and produced
nonsense. So on the default a wrong value is fairly harmless, and it is
leaving it *empty* that costs you.

**The language it heard is reported back, where the model answers one
and you named none.** `gpt-transcribe`, the default, answers a code
whenever it makes out a language, so the `heard` log line carries
`language`, the conversation record keeps it, and an operator can
finally see a household's language being misheard instead of inferring
it from odd replies. Not every turn carries one: a clip the model makes
no language out of comes back with an empty list, which silence and
laughter both did, and that turn's field is simply absent. The `gpt-4o`
models answer no language at all and `whisper-1` answers only in a
format this server does not ask for, so with either of those the field
stays empty as it always did.

Setting `language` above, or a session handing one over from another
engine, suppresses the report: told a single language, the model hands
that code straight back rather than saying what it heard, and echoing
a configured value into a metric would read as a measurement of the
room. A `languages` set of two or more does not suppress it, and that
is the same rule rather than an exception: handed a choice, the model
reports which one it made, which is a detection inside what you
declared. A set of exactly one is a single language however it is
written, and suppresses like the line above. Read what does arrive as a
rate to watch rather than a verdict on one turn, since it says what the
model decided rather than what was said: a spoken German "Hallo" came back as "Hello." and reported as
English, which is the mishearing this reporting exists to make
visible. There is still no confidence, because no model reports one,
and no `language_detect` option: the local engine's
`language_detect: once` exists to skip a detection pass that costs
seconds of CPU, and here detection is free.

**It does not stream, deliberately.** The stage hands over one whole
utterance and the LLM cannot start on half a sentence, so response
deltas would arrive before anything could use them. The TTS stage is
the opposite case and does stream.

**Very short audio is answered empty without a request.** OpenAI
refuses anything under 0.1 s, and the barge-in path is what would send
it: a snippet classified as speech mid-reply gets transcribed to
decide whether the interruption was real. That refusal would be logged
as a failure rather than the non-answer it is. The floor was measured
against OpenAI and applies only there. A compatible endpoint that
accepts shorter clips receives them, because suppressing one it would
have answered would drop a barge-in it could have confirmed.

`base_url` is the same door the `openai_compatible` LLM type and the
`openai` TTS type open, with the same consequences: the host rather
than the spelling decides whether an entry counts as OpenAI, a
`base_url` that is not a URL fails the boot, and the endpoint rather
than the type decides how far the audio travels, so an entry under a
declared `server.data_boundary` carries its own `reach`.

Only OpenAI's own host *requires* a key. A keyless self-hosted server
can leave `api_key_env` out, but a gateway or hosted endpoint that
authenticates still names its variable there and the key is sent, so
"compatible" does not mean "keyless".

**It sends the microphone audio wherever `base_url` points**, which by
default is OpenAI, and that is a stronger claim than the TTS types
make: what leaves is what was said in the room, not what the assistant
answered. See [The data boundary](security.md#the-data-boundary) for how
`server.data_boundary` treats it.
