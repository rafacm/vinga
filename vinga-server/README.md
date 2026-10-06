# vinga-server

The Vinga conversation server (Python): a wire-compatible backend for
[78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) devices, written
against the firmware's
[protocol docs](https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket.md);
the device-token scheme follows
[xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server).

It implements the two endpoints a device needs:

- **HTTP OTA/config endpoint** (`/xiaozhi/ota/`): the device POSTs its
  identity and receives the WebSocket URL (and optionally firmware updates).
- **WebSocket endpoint** (`/xiaozhi/v1/`): the conversation channel,
  carrying Opus audio frames up, JSON control messages both ways, and Opus
  audio back.

Behind the WebSocket sits the conversation pipeline: VAD segments speech,
ASR transcribes it, the LLM streams a reply, and TTS speaks it back
sentence by sentence, every stage a pluggable provider chosen per agent.
Agents reach tools over MCP, both their own servers and the device's own
controls.

Those four acronyms are the vocabulary of the whole configuration, so in
full:

| Stage | | What it does |
| ----- | - | ------------ |
| `vad` | voice activity detection | Decides where speech starts and when the user has stopped, so the rest of the pipeline runs on an utterance rather than on a stream |
| `asr` | automatic speech recognition | Turns that utterance into text. Also called speech to text |
| `llm` | large language model | Writes the reply, and asks for tools |
| `tts` | text to speech | Turns each sentence of the reply back into audio |

They run strictly in that order, each waiting on the one before it, which
is why the latency of any one of them is latency the user hears.

Those two paths, the two probes `/healthz` and `/readyz`, and the
configuration API under `/api` are
everything the server exposes: the interactive API docs are turned off,
the WebSocket requires a device token the OTA endpoint issued, and every
request to `/api` carries a bearer token.

## Goals

- Python, and one Postgres database holding everything this server
  stores: the domain half of the configuration in a `domain` schema,
  and the conversation record, when it is turned on, in a
  `record` schema beside it. Both are migrated at every boot,
  so a blank database is a valid state to start on and there is no
  init command to forget
- Configurable providers:
  - **LLM**: Anthropic, any OpenAI-compatible endpoint (Ollama, LM Studio,
    gateways)
  - **ASR**: local (faster-whisper) or cloud (OpenAI, and anything
    speaking the same dialect)
  - **TTS**: pluggable engines as optional extras (Piper)
  - **MCP**: attach any MCP servers as tools for the assistant, alongside
    the device's own
- Distributed as a multi-arch container image, deployable on your own
  infrastructure

## Running and configuring it

Everything a person running this server does is a task guide in
[`docs/run/`](../docs/run/README.md), one task per page, listed one
line each in that directory's index: running the container and
providing its database, exposing and securing it, configuring it and
using its configuration API, choosing an agent's providers, tools,
memory and prompt, tuning when a turn ends and what a slow or failed
reply says, and reading its logs, traces, cost and conversation
record.

## Developing it

[Contributing to vinga](../docs/contributing.md) is how to run this
server from source, what it is built on, and the four lanes a change is
exercised in before it ships.

## Running in a container

This has moved to
[Running vinga in a container](../docs/run/running-in-a-container.md),
and every other deployment task has a guide of its own in
[`docs/run/`](../docs/run/README.md).

## Status

vinga-server serves conversations end to end: OTA and WebSocket
endpoints, the VAD/ASR/LLM/TTS pipeline on pluggable providers, agents
bound to devices, MCP tools on both sides, device authentication,
onboarding by a short URL and an activation code, limits,
structured logging, and a published multi-arch container image. The v1
plan and its per-milestone implementation notes live in
[`docs/plans/`](../docs/plans/); getting a device on your desk onto it
is in [`../docs/devices/`](../docs/devices/README.md), and the wire it
speaks is in [`../docs/xiaozhi-notes.md`](../docs/xiaozhi-notes.md).
