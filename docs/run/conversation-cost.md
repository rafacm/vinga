# Pricing a conversation

At the end of this guide you will know what each stage of a turn
reports about what it was given, and you will have entered the model
definitions a telemetry backend needs before it can turn that usage
into a cost, or know why a model deliberately has none.

The usage rides the traces this server exports, which
[Exporting traces](logs-and-traces.md#exporting-traces) sets up; the
keys that switch them on are under
[`server.telemetry`](../reference/server-config.md#servertelemetry) in
the server configuration reference.

## What a conversation cost

Every stage of a turn says what it was given, on its own span, in the
unit that stage is actually billed in:

| Stage | Span | What it reports |
| --- | --- | --- |
| Transcription | `asr` | `gen_ai.usage.input_milliseconds`, how much audio the ear was actually sent |
| Generation | `llm` | `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`, as the endpoint reported them, and `gen_ai.usage.cache_read.input_tokens` where the endpoint reported what its prompt cache served |
| Synthesis | `tts_stream` | `gen_ai.usage.input_characters`, the length of the sentence the voice was handed |

The milliseconds and the characters are both INPUT, read from the
model's side the way the OpenTelemetry GenAI conventions read the token
halves: an ear is given the audio and produces a transcript, a voice is
given the sentence and produces the audio. Those conventions name token
counts and nothing else, so the two units they have no word for state
that unit in the attribute name rather than being reported as tokens
they are not. Every value is a whole number, because a backend drops a
usage value that is not.

The cached count is part of the input count, never beside it: of the
`gen_ai.usage.input_tokens` a round reports, that many were served from
the provider's prompt cache. A backend that knows the key takes it out
of the input and prices it at the model's cached rate, which is
usually a fraction of the full one, so the round's cost is what the
provider actually charged rather than an upper bound on it. An endpoint
that does not say what it cached reports no cached count at all, rather
than a zero that would claim nothing was.

**The transcription number is what was SENT, not how long you spoke.**
The two come apart in both directions on a real endpoint: a clip under
the endpoint's own minimum is never sent at all and reports zero, and a
clip a prompt-echo retry has to send a second time reports twice its
length. How long the user spoke is a different question and stays where
it was, on `vinga.asr.duration_s`. An engine that cannot say what it
submitted, which is every local one, reports no usage rather than a
zero: an unmeasured call and a free call are different facts, and only
the second is worth nothing.

Usage is not a cost. A backend turns one into the other with a model
definition, which is a match pattern, a unit and a price per unit, and
**those are yours to enter.** This server never writes one. It holds no
admin credential for your backend, the OTLP path carries none, and a
deployment that provisioned prices at boot would be mutating a
third-party system on the strength of telemetry credentials, which is a
larger claim on your infrastructure than anything else here makes.

### The generation stage usually needs nothing

A backend ships managed definitions for well-known vendor models, so
the `llm` stage is normally priced the moment its spans arrive. On the
project this section was written against, `gpt-4o-mini` came back with
`costDetails` filled in from input and output token counts with no
definition entered by hand at all.

To check yours, hold one conversation with telemetry on, open the `llm`
observation of any turn, and look at whether it has a cost beside its
token counts. If it has, there is nothing to do for this stage, and a
definition of your own would only shadow one the backend maintains.

If it has not, the model is one the backend does not know: a
self-hosted model, a model behind a compatible endpoint, or a vendor
model under a name your deployment renamed. Then it needs a definition
like the ones below, with one difference: a generation reports tokens
in BOTH directions, so it takes `inputPrice` and `outputPrice` rather
than an input rate alone, `unit` is `TOKENS`, and the two rates are
whatever that model's own published price list says per token. This
page does not name them, because a price nobody has read is not a price.

### The definitions worth entering

These are the stages a backend has no managed definition for, because
the units are vinga's own. Prices as published on <https://developers.openai.com/api/docs/pricing>,
read 2026-09-12. A price is a fact with an as-of date; re-read it before
trusting a cost report made long after this one.

| Model | Match pattern | Unit | Input price | Published as |
| --- | --- | --- | --- | --- |
| `gpt-transcribe` | `(?i)^(gpt-transcribe)$` | `MILLISECONDS` | `0.000000075` | $0.0045 per minute |
| `whisper-1` | `(?i)^(whisper-1)$` | `MILLISECONDS` | `0.0000001` | $0.006 per minute |
| `tts-1` | `(?i)^(tts-1)$` | `CHARACTERS` | `0.000015` | $15.00 per 1M characters |
| `tts-1-hd` | `(?i)^(tts-1-hd)$` | `CHARACTERS` | `0.00003` | $30.00 per 1M characters |

The price column is the published one converted into the unit the span
reports, and nothing else: 0.0045 per minute is 0.000000075 per
millisecond, 15.00 per million characters is 0.000015 per character. An
exact conversion of a list price is still that list price. An estimate
is not, which is why the models below get no definition at all.

Milliseconds rather than seconds for the two speech models, because a
usage value has to be a whole number and whole seconds are too coarse
for what a voice assistant actually hears: rounding a 0.4 second "ja"
up to one second would overcharge it by 150%.

The match pattern is what the backend compares the span's
`gen_ai.request.model` against, and that value is whatever your provider
entry names as its model, so a definition only ever fires for a
deployment that configured that model.

### Entering one

Against a Langfuse backend, a model definition is a `POST` to
`/api/public/models` authenticated with the project's own key pair:

```bash
# Once: a curl config file only you can read. Write one line into it
# in the editor, user = "<public key>:<secret key>", with the project's
# key pair pasted there and nowhere else.
install -m 600 /dev/null ~/.langfuse-curlrc
"${EDITOR:-vi}" ~/.langfuse-curlrc

curl -sS -K ~/.langfuse-curlrc -X POST "$LANGFUSE_HOST/api/public/models" \
  -H 'content-type: application/json' \
  -d '{
        "modelName": "tts-1",
        "matchPattern": "(?i)^(tts-1)$",
        "unit": "CHARACTERS",
        "inputPrice": 0.000015
      }'
```

The key pair goes into the file in an editor and reaches `curl` from
there, so the shell never sees it: it is in no command's arguments,
where the process table would show it, and in no expansion, which the
shell's tracing (`set -x`) would print. `LANGFUSE_HOST` is the
project's address and no secret.

One request per row of the table above. The backend's own settings page
does exactly the same thing through a form, which is usually the easier
way to enter four of them and to see what a project already has; the
request is here because a deployment that is rebuilt from files wants
the four in a file.

`unit` is a closed set (`TOKENS`, `CHARACTERS`, `MILLISECONDS`,
`SECONDS`, `REQUESTS`, `IMAGES`) and the price keys are `inputPrice`,
`outputPrice` and `totalPrice`. Both halves are why vinga reports its
seconds and characters as INPUT: a usage number under any other key has
no price beside it, however carefully it was measured.

### With none of them entered

Usage is present on every span, and every cost the backend cannot price
on its own reads zero. That is correct rather than broken: the server
measured what it was given and the backend was never told what a
millisecond of audio is worth. Enter the definitions before the run
whose cost you want to read, because whether a backend goes back and
prices traces it has already taken in is that backend's own behaviour
and not something this server can promise on its behalf.

### The models that deliberately get none

An estimate entered as a price is worse than an empty column, because it
is a number a report adds up.

- **`gpt-4o-transcribe` and `gpt-4o-mini-transcribe`** are billed per
  audio token ($2.50 and $1.25 per 1M input tokens). The `asr` span
  carries milliseconds, and converting would take a tokens-per-second
  assumption. Their transcriptions show usage and no cost.
- **`gpt-4o-mini-tts`** is billed per audio output token ($12.00 per 1M),
  and the `tts_stream` span carries the characters the voice was given.
  Same reason, same answer.
- **ElevenLabs** bills in credits whose value depends on the plan, so
  there is no list price to enter at all.
- **Piper and faster-whisper** run in this process. There is no rate
  because there is no vendor, which is a true answer rather than a gap:
  what a local voice costs is the machine it runs on. They also report
  no usage: a local engine does not count what it was sent, and this
  server will not count it on the engine's behalf.
