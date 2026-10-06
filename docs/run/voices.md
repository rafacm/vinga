# Giving an agent a voice

At the end of this guide you will have chosen the engine an agent
speaks with, weighing how long each keeps a device silent before a
reply starts, and configured an ElevenLabs or an OpenAI voice.

The `elevenlabs` type's options are in the domain configuration
reference under
[`tts` options for `type: elevenlabs`](../reference/domain-config.md#tts-options-for-type-elevenlabs).
The `openai` and `piper` types pass their options through rather than
declaring them, so the reference lists none of theirs: the `openai`
table below and the example fragments
[`tts-openai.yaml`](../../vinga-server/examples/tts-openai.yaml) and
[`tts-piper.yaml`](../../vinga-server/examples/tts-piper.yaml) are
where they are written down.

## Choosing a voice

The three TTS types differ in the one thing a conversation actually
feels: how long the device stays silent before it starts speaking.
Measured on one machine in a single run, median of five rounds per
sentence, so the columns are comparable with each other:

| | Piper | ElevenLabs | OpenAI |
| --- | ----- | ---------- | ------ |
| "The kitchen light is now off." | 40 ms | 194 ms | 888 ms |
| "Hello, I am your vinga assistant..." | 79 ms | 188 ms | 764 ms |
| "Hej, jag är din vingasassistent." | 54 ms | 194 ms | 818 ms |
| Runs | on your host | ElevenLabs | OpenAI |
| Needs | `--extra piper` | a key | a key |

Read down the columns, not across the rows. Piper is the only one
whose figure grows with sentence length, because it synthesizes a
whole sentence before yielding anything; both cloud types stream, so
their figure is flat and a longer sentence starts no later than a
short one. Past a long enough sentence Piper is the slower of the two
to start speaking, even though it is local.

**The number above is only the start of the reply, and it used to not
be the whole cost.** A reply is spoken sentence by sentence, and each
sentence used to be synthesized only once the previous one had
finished playing, so the same wait fell at every sentence boundary
too. On a three-sentence reply:

| | Gap at each sentence boundary | Total dead air mid-reply |
| --- | --- | --- |
| Piper | 40 to 80 ms | negligible |
| ElevenLabs | 129 to 139 ms | 268 ms |
| OpenAI | 478 to 884 ms | 1362 ms |

Around 130 ms passed unnoticed. Around 600 ms did not: it was audible
as the voice stuttering every few seconds through a long reply, and
worse than a plain pause, because the frame pacer's schedule is
absolute from the reply's first frame, so the frames after a stall
burst out to catch up. The device got a dropout followed by a flood.

The server now synthesizes the next sentence while the current one is
still playing, so that latency is spent against playback that is
already happening. The same replies, measured again: every
boundary is one frame, 60 ms, which is the cadence rather than a gap.
The table above is what it cost before, kept because it is what the
start-of-reply figure has to be weighed against if a provider ever
becomes slower than a sentence is long.

This leaves the start of the reply as the only latency a listener
meets, which is a one-time delay a person tolerates rather than a
defect they notice every few seconds. It is why the recommendation
below no longer bounds a cloud provider on latency alone.

So: **Piper** if it must stay on your host or cost nothing per
character, **ElevenLabs** for the best voice per millisecond, and
**OpenAI** when the deployment is already on OpenAI and one key is
worth more to you than 700 ms at the start of a reply. Reply length no
longer picks between them, which it did while every sentence boundary
cost what the first one did. Each type's own section below has its
options and the details behind its number.

These are one machine on one day from one network, not a benchmark.
Your ratios should hold; your absolute numbers will not. (The
ElevenLabs section quotes ~130 ms from its own earlier measurement,
with a different voice on a different day, which is the size of the
run-to-run variation to expect.)

## ElevenLabs

The reason to reach for the `elevenlabs` TTS type is that it sounds
markedly better than Piper. It needs two things: a key, and a voice
id.

```bash
vinga-server config provider set tts eleven -f - <<'YAML'
type: elevenlabs
voice_id: PUT_YOUR_VOICE_ID_HERE
api_key_env: ELEVENLABS_API_KEY
YAML
```

The key is named, never written. `api_key_env` gives the name of an
environment variable and the server reads it at startup, failing the
boot if it is unset rather than failing every conversation later. A
`.env` file next to the config works, since the server loads one.

The voice id is the id, not the display name, and it is
account-specific even for the stock voices, so an id copied from
someone else's configuration will usually 404. Pick one in the
ElevenLabs app, or list your own:

```bash
printf 'header = "xi-api-key: %s"\n' "$ELEVENLABS_API_KEY" \
  | curl -s -K - https://api.elevenlabs.io/v1/voices \
  | jq -r '.voices[] | "\(.voice_id)  \(.name)"'
```

The key reaches `curl` on standard input, as a config file written by
the shell's builtin `printf`, rather than in its arguments, where the
process table and the shell's tracing would show it.

Every option, with its default and what it accepts, is in the domain
configuration reference under
[`tts` options for `type: elevenlabs`](../reference/domain-config.md#tts-options-for-type-elevenlabs).
One thing it leaves out: the default model, `eleven_flash_v2_5`, speaks
Swedish among its 32 languages.

Reference for all of it: the [streaming
endpoint](https://elevenlabs.io/docs/api-reference/text-to-speech/stream),
the [model list](https://elevenlabs.io/docs/overview/models), the
[voice listing
endpoint](https://elevenlabs.io/docs/api-reference/voices/search), and
what the [voice
settings](https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices)
do to a voice.

**What it costs in latency.** First audio at about 130 to 190 ms
whatever the sentence, which is the fastest of the two cloud types by
a wide margin; see Choosing a voice above for the comparison and what
the numbers mean. An idle conversation pays nothing extra to resume.

**It sends your replies to ElevenLabs**, which is what the reply text
is: the API is billed by character. The type is marked `reach:
internet` accordingly, so a `server.data_boundary` of `host` or
`network` refuses to boot it (see
[Security](../../vinga-server/README.md#security)). Nothing else in the pipeline moves: VAD, ASR and the
LLM stay wherever you configured them.

## OpenAI

The `openai` TTS type is the one to reach for if the deployment is
already on OpenAI: the same key serves the LLM stage, and the voices
are the stock ones, so there is nothing to pick out of a library.

```bash
vinga-server config provider set tts openai_voice -f - <<'YAML'
type: openai
voice: alloy
api_key_env: OPENAI_API_KEY
YAML
```

Keys are named, never written, exactly as for ElevenLabs above.

Voices are shared across every account (`alloy`, `ash`, `ballad`,
`coral`, `echo`, `sage`, `shimmer`, `verse`, `marin`, `cedar`), so a
voice copied from someone else's configuration works. Hear them in the
[voice gallery](https://www.openai.fm/).

| Option | Default | What it does |
| ------ | ------- | ------------ |
| `voice` | required | Which voice speaks |
| `api_key_env` | required for OpenAI itself | Name of the variable holding the key |
| `model` | `gpt-4o-mini-tts` | The current speech model, steered in prose, and the fastest of the three to start speaking. `tts-1` and `tts-1-hd` are the older pair |
| `base_url` | `https://api.openai.com/v1` | Point it at any server implementing `/v1/audio/speech` |
| `instructions` | unset | How to speak, in prose ("Speak slowly and warmly"). Read by the `gpt-4o` models only |
| `speed` | unset | A multiplier from 0.25 to 4.0. Read by `tts-1` and `tts-1-hd` only |
| `timeout_s` | `30` | Seconds before a synthesis request is abandoned, and a real bound: retries are off |

`base_url` is the same door the `openai_compatible` LLM type opens.
Several self-hosted speech servers implement this endpoint, so a fully
local pipeline stays available through the same dialect, and a keyless
one of those can leave `api_key_env` out; an endpoint that
authenticates still names its variable there, since only OpenAI's own
host makes a key mandatory. It is also what decides whether this type sends
anything off your host, which is why it cannot declare its own reach:
under a declared `server.data_boundary` the entry carries its own
`reach` to say where the endpoint is, exactly as `openai_compatible`
does.

Whether an entry counts as OpenAI is decided by the host, so every
spelling of it (a trailing slash, an explicit port, a different case)
keeps the same startup checks. A `base_url` that is not a URL at all
fails the boot rather than the first synthesis.

Retries are off. The SDK would otherwise attempt a failed request
three times, which inside the serial sentence loop means the device
sits silent for three timeouts plus backoff. A sentence that fails
should fail now and let the conversation move on.

The last two are the one place this type refuses a configuration the
API would accept. Each OpenAI model reads one of them and silently
ignores the other, so naming the wrong one for the model fails the
boot rather than becoming a knob that never takes effect.

That check applies only when `base_url` names OpenAI's host, because
it is a fact about OpenAI's models rather than about the dialect. A compatible
server may name a model `gpt-4o-anything` and read `speed`, or read
`instructions` on a model named nothing like OpenAI's, and its `speed`
need not stop at 4.0. Both knobs are passed through to such an
endpoint unexamined, so it answers for itself.

There is no audio format option, unlike ElevenLabs: the API's `pcm`
format is fixed at 24 kHz, which is the rate devices are spoken at, so
nothing is resampled and there is nothing to choose. Reference for the
rest: the [speech
endpoint](https://platform.openai.com/docs/api-reference/audio/createSpeech)
and the [text-to-speech
guide](https://platform.openai.com/docs/guides/text-to-speech).

**What it costs in latency, and it is the one real drawback.** First
audio arrives at about 820 to 900 ms, roughly +700 ms on ElevenLabs
and +800 ms on Piper: a pause a person notices at the start of every
reply. See Choosing a voice above for the comparison in full.

That cost is now paid once per reply rather than once per sentence.
The server synthesizes the next sentence while the current one is
still playing, so the boundaries inside a reply cost a single frame,
and the stutter that used to make this type unsuitable for an agent
that tells stories is gone. Reply length no longer picks between the
types; the wait before the first word is what does.

Which model you pick matters more here than the option table suggests,
and the default is the fastest of the three by some margin. Worth
stating plainly, because it contradicts how the older pair is usually
described:

| Model | Short sentence | Longer sentence |
| ----- | -------------- | --------------- |
| `gpt-4o-mini-tts` | 908 ms | 820 ms |
| `tts-1` | 1549 ms | 1413 ms |
| `tts-1-hd` | 1974 ms | 1861 ms |

Reach for this type because the deployment is already on OpenAI and
one key is worth something. If what you want is the best voice per
millisecond, ElevenLabs is the better buy.

**It sends your replies wherever `base_url` points**, which by default
is OpenAI. See [Security](../../vinga-server/README.md#security) for how
`server.data_boundary` treats it.
