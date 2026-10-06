# Choosing providers

At the end of this guide you will know which engine can serve each
stage of the pipeline, which of them run on your host and which reach
a vendor, and what an install has to carry for each.

The fields every provider entry shares are in the domain configuration
reference under [Provider](../reference/domain-config.md#provider),
followed by the option tables of the types that declare them and an
example fragment for every type. Choosing the engine that hears is
[Choosing how an agent hears](speech-recognition.md), and the one that
speaks [Giving an agent a voice](voices.md).

## Providers

Each pipeline stage is a named provider entry in the configuration, and
each agent picks one provider per stage. The v1 set:

| Stage | Type                | Runs               | Install                          |
| ----- | ------------------- | ------------------ | -------------------------------- |
| vad   | `silero`            | locally            | core (pysilero-vad)              |
| asr   | `faster_whisper`    | locally            | `uv sync --extra faster-whisper` |
| asr   | `openai`            | OpenAI or anywhere | core                             |
| llm   | `anthropic`         | Anthropic          | core                             |
| llm   | `openai_compatible` | anywhere           | core                             |
| tts   | `piper`             | locally            | `uv sync --extra piper`          |
| tts   | `elevenlabs`        | ElevenLabs         | core                             |
| tts   | `openai`            | OpenAI or anywhere | core                             |
| any   | `mock`              | in tests           | core (deterministic, keyless)    |

"Anywhere" is a `base_url`: those three types speak a dialect rather
than name a vendor, so each reaches a self-hosted server implementing
the same endpoint. That is what keeps a fully local pipeline available
through them, and it is why they cannot declare their own reach.

Model weights are never shipped: faster-whisper models and Piper voices
download at server startup into a local cache (`download_dir` on the
provider entry). A fully local, keyless pipeline is Silero +
faster-whisper + Ollama (through `openai_compatible`) + Piper, and
`server.data_boundary: host` makes the server refuse to boot anything
else (see [The data boundary](security.md#the-data-boundary)).

The Install column is a checkout's, since a deployment installs nothing:
both image variants carry `core`, and the default variant carries the
two extras as well. "Core" here means the server half, which a checkout
gets from a plain `uv sync` and the image build gets from the `serve`
extra it names in its Dockerfile. The configuration CLI is the other
half and carries none of this.

Cloud providers need no extra. They speak their APIs over HTTP, or
through an SDK the server install already carries for another stage, so
they are in every server and cost nothing to carry; what makes a
provider optional is weight or licensing, and a network client has
neither.

Licensing note: `piper-tts` (piper1-gpl) is GPL-3.0, which is why it is an
optional extra and never a core dependency of the MIT server. The
`edge-tts` package is GPL-3.0 as well, and the same rule holds for it.
