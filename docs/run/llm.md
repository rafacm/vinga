# Choosing the model an agent thinks with

At the end of this guide an agent of yours will be answering through
the model you chose: a local one served by Ollama or another runner on
your own machine, or a vendor's, Anthropic's or OpenAI's or another
OpenAI-compatible service's, with its key kept out of every command
line. You will also know how to tell whether a model can do what a
voice agent asks of it, before you blame the agent.

Every field this guide writes is in the domain configuration
reference: the fields every provider shares under
[Provider](../reference/domain-config.md#provider), the
`openai_compatible` type's own under
[`llm` options for `type: openai_compatible`](../reference/domain-config.md#llm-options-for-type-openai_compatible),
and the stage fields an agent picks its model with under
[Agent](../reference/domain-config.md#agent) and
[Agent defaults](../reference/domain-config.md#agent-defaults). The two
server keys it leans on, `llm_first_token_timeout_s` and
`data_boundary`, are rows of the
[`server` section](../reference/server-config.md#server). Which engines
exist for every stage is [Choosing providers](providers.md).

The commands are the `vinga` client's, installed or through the shell
function into the container that Getting Started defines. Every file
goes in on standard input (`-f - < file`) and comes out on standard
output, so the same lines work both ways.

## What the model has to do

The LLM stage has two types. `anthropic` speaks Anthropic's API and
nothing else. `openai_compatible` speaks the OpenAI chat completions
dialect to whatever its `base_url` names: Ollama, llama.cpp, LM
Studio, vLLM, OpenAI itself, or a service that imitates it. Which
model sits behind either is your choice, and three things decide
whether it works here.

**It makes real tool calls.** Every agent is offered tools: the
server's own (starting a new conversation, resuming one, recording
where the board is) whatever its configuration says, the board's
controls (volume, brightness, the screen) when the board publishes
them, the memory tools unless its memory is off, and its MCP servers'.
A model that cannot call them looks like an agent whose tools never
fire. Some models write a call out as text instead of making it; the
server withholds a sentence shaped like a call to an offered tool
rather than speak it
([When a model writes a tool call into its speech](../system-overview.md#when-a-model-writes-a-tool-call-into-its-speech)),
which keeps the JSON off the speaker and still leaves the tool
uncalled. A call whose argument has the wrong type, a number written
in quotes, is converted only where the conversion is exact, with a
`tool_arguments_coerced` event; any other value reaches the tool as
the model wrote it. On Ollama, `ollama show <model>` lists `tools`
under Capabilities. On every runner, the test that settles it is a
question only a tool can answer, with `vinga events tail --follow`
open beside it: a `tool_call` event is the call happening.

**Its first token arrives well inside the watchdog.** A round whose
stream shows no sign of life within
[`llm_first_token_timeout_s`](../reference/server-config.md#server),
ten seconds by default, is cancelled and retried once, and a second
stall gives the turn up and says the agent's fallback phrase
([Setting limits and probes](limits-and-probes.md#limits) and
[When a reply fails](slow-and-failed-replies.md#when-a-reply-fails)).
Raising it helps only up to 30 seconds: the request itself gives up
after 30 seconds without a byte, a fixed bound rather than
configuration, and fails as a `provider_failed` with
`ProviderCallTimeout`. Every finished round logs an `llm_round` event
whose `duration_ms` is the whole round and whose `first_token_ms` is
how long the first spoken token took; a round that only asked for a
tool carries no `first_token_ms`, and its `duration_ms` is the wait.

**It fits the machine.** A local model holds its weights in memory
while it is loaded, beside the speech engines if those are local too,
and on a CPU it is slow in proportion to its size. `ollama ps` shows
what is loaded, how much memory it takes, and whether it runs on the
CPU or a GPU.

## The local model

The local preset
([`presets/local-stack.yaml`](../../vinga-server/examples/presets/local-stack.yaml)),
the `openai_compatible` example and Getting Started's step 0 name
`gemma4:e4b`, Gemma 4 e4b. It was chosen by measurement on a Raspberry
Pi 5 (16 GB, CPU only, Ollama 0.35.1), on 2026-10-06 and 2026-10-07:
asked 32 questions about vinga and the board it speaks through, it was
the most accurate model measured, at a median 9 s per question against
117 s for `llama3.1:8b` and 27 s for `qwen3:8b` with its thinking off.

Gemma 4 e4b thinks before it answers unless told not to, and over
Ollama's OpenAI endpoint its thinking arrives before any of the
answer: on the same Pi, on 2026-10-09, a question that needed one tool
took 39 to 137 s with the thinking on. `reasoning_effort: none` on the
entry turns it off, and the preset, Getting Started and the recipe
below all carry it.

**On small hardware the first turn does not fit.** Every request
carries the agent's instructions and the tools it is offered, and the
runner reads all of it before the first byte of the answer. On the
same Pi, on 2026-10-09, Gemma 4 e4b took 107.6 s to the first byte of
a conversation's first request, 1,990 tokens it had not seen, and
179.8 s for a probe of 2,363 tokens. With the defaults the server
waits `llm_first_token_timeout_s`, 10 s, for the first sign of life,
cancels the request and sends it once more, and when the second also
stalls gives the turn up with a `FirstTokenTimeout` and speaks the
agent's fallback phrase, about 20 s after the reply began. Raising the
watchdog helps only up to 30 s, since each request also ends after 30
s without a byte, a fixed transport bound, as a `ProviderCallTimeout`
(see [What the model has to do](#what-the-model-has-to-do)); with the
watchdog at 30 s, both requests stalled and the turn was given up
after about a minute. Trying again did not help in the measurements:
seven cold conversations in a row, over about a quarter of an hour,
five at 10 s and two at 30 s and each with its retry, got no answer: a
request the server cancelled left the next one no closer. Once the
runner held the prompt, the same request came back in 2.4 to 3.4 s,
but nothing in vinga gets it there today. Pinning the model, below, is
still needed and is not enough, since it keeps the weights loaded and
it is the prompt that is slow to read. On hardware that size, what
answers the first turn today is a model the machine reads faster (the
1.5B model below spent 2.7 s on a tool round once warm), a machine
with a GPU, or a vendor's model.

Before Gemma 4 e4b, the preset named `qwen3:8b` and Getting Started
`llama3.1:8b`. Either remains an option on a machine that runs an 8B
model fast enough, and these are their measurements, with their dates.

- **Tool calls.** Both list `tools` among their capabilities, and both
  made the call in the tool-carrying turns below. On the 2026-09-03
  Getting Started walkthrough, on a Mac, eight identical requests to
  raise a board's volume, with the board's real tool schema, gave
  `llama3.1:8b` 8 proper tool calls of 8, 7 of them with the volume as
  an integer. Once on the Pi below, `llama3.1:8b` first wrote the call
  out as text (withheld) and then made it.
- **First token.** `qwen3:8b` is a reasoning model: by default it
  streams its thinking before its answer. On the walkthrough's Mac the
  first word of the answer trailed by 1.5 to 2.5 s. The thinking keeps
  the stream alive, so the watchdog never fires; the device simply
  waits. Ollama turns the thinking off per request, and an
  `openai_compatible` entry sends a key it does not declare as part of
  the request, so `reasoning_effort: none` on the entry is the switch
  (the recipe below carries it). `llama3.1:8b` has no thinking to turn
  off.
- **The machine.** On a Raspberry Pi 5 (16 GB, CPU only), on
  2026-10-06, an 8B model was not a conversation. `ollama ps` showed
  `llama3.1:8b` at 5.6 GB and `qwen3:8b` at 5.9 GB, both on the CPU.
  One turn that needed one tool, with the model pinned: `qwen3:8b`
  without thinking spent about 9.5 s on the round that asked for the
  tool and 6 s more to the first spoken word of the answer; with its
  thinking on, about 80 s and 47 s, over two minutes for the turn;
  `llama3.1:8b` spent 15 to 42 s on the tool round, so most of its
  turns stalled at the watchdog. The first turns after switching
  models, before the runner had the prompt cached, took over 30 s to
  the first byte and failed whatever the watchdog said. A 1.5B model
  under llama.cpp on the same Pi, once warm, spent 2.7 s on the tool
  round and 0.6 s to the first spoken word.

Whichever you run, **load it before the first conversation and keep it
loaded.** Ollama unloads a model five minutes after its last request,
and loading one is slower than the watchdog (a cold request took
about 20 s to its first byte for either 8B model on that Pi), so the turn that meets a cold model is given up and
answered with the fallback phrase. Getting Started's step 0 shows the
one request that loads a model and pins it
([Getting Started](../../README.md#getting-started)); name your model
in it.

## The built-in agent's lookup

vinga, the built-in agent, is offered one tool no other agent has,
`search_docs`, a search over the concepts page, the glossary and the
device guides packaged with the build, for the questions its prompt
does not answer. Whether a model calls it is the model's own choice,
and it is where models differ most. Both measurements below asked the
same 32 questions, each in two wordings (the questions are in
`vinga-server/tests/local/lookup_gate/`), on 2026-10-09, through a
model harness that sends vinga's real prompt and tools, with the
ESP32-S3-Touch-LCD-1.54 board's facts in the prompt as a session on
that board would have them, and reads the model's text back: no board,
no speech recognition or synthesis and no device output were involved,
and every answer was read by hand. A correct answer holds every key fact the pages give for it;
of the 32, 15 need the lookup, 12 are answered by the prompt, 3 cannot
be answered and should be declined, and 2 are volume commands.

| Model | Correct | Invented a claim | Searched when needed (of 15) | Declined (of 3) | Volume commands (of 2) | Median s per question |
| --- | --- | --- | --- | --- | --- | --- |
| `claude-sonnet-5` | 78%, 81% reworded | 0 | 13, 13 reworded | 3 | 2 | 2.9, 3.1 reworded |
| `gemma4:e4b`, Pi 5 | 50%, 41% reworded | 0, 1 reworded | 5, 2 reworded | 3 | 1 | 6.3, 7.4 reworded |

On Gemma 4 e4b the misses are mostly questions it answered "I do not
have information" to without searching; the prompt's twelve questions
it answers well, in a median 1.8 s to its first text (the harness
times text, not speech). When it does search, the round after the
search is slow on a Pi: the runner reads the passages found before it
says anything, and in the harness, which waits for as long as the
model takes, the first byte of that round came after 34 to 53 s. A
running server does not wait that long. With the defaults it waits
`llm_first_token_timeout_s`, 10 s, for the first sign of that round,
cancels the request and sends it once more, and when the second also
stalls gives the turn up with a `FirstTokenTimeout` and speaks the
agent's fallback phrase, as in the cold first turn above. Raising the
watchdog stops helping at 30 s, where the request itself ends after 30
s without a byte as a `ProviderCallTimeout`
([What the model has to do](#what-the-model-has-to-do)), and every one
of the measured rounds was past that. So on that hardware a turn that
searches is expected to be given up today; that is inferred from the
harness's first-byte times and was not observed in a running server.
What vinga does say during that wait is its filler: a
`builtin_agent.filler` section ([Overriding vinga](configuration.md#overriding-vinga-the-built-in-agent))
plays one of its phrases the moment vinga searches. `claude-sonnet-5`
reached the first byte after a search in under 3 s, and spent about
8,400 input tokens and 130 to 150 output tokens per question, uncached.

## Pointing an agent at an entry

A model is a provider entry, and an agent answers through the entry
its `llm` field names, or the one `agent_defaults` names when it names
none. So there are two ways to switch.

**Replace the entry your agents already use.** Writing an entry under
the name they already reference (Getting Started's is `local`) and
applying it is the whole change: every agent that inherits it answers
through the new model from the next conversation on, and nothing else
moves.

**Or write a new entry and point an agent at it.** `vinga agent set`
and `vinga agent-defaults set` replace the whole entity, its other
stages, prompt, tools and sections included, so the change is made to
the entity as it stands rather than written from scratch:

```bash
# Every agent that names no model of its own:
vinga agent-defaults export > agent-defaults.yaml
"${EDITOR:-vi}" agent-defaults.yaml    # set llm: to the new entry's name
vinga agent-defaults set -f - < agent-defaults.yaml
vinga apply

# Or one agent:
vinga agent export assistant > assistant.yaml
"${EDITOR:-vi}" assistant.yaml         # add or change its llm: line
vinga agent set assistant -f - < assistant.yaml
vinga apply
```

A mistake is caught at one of two moments, and what it leaves behind
differs.

**At the write.** `vinga provider set` checks the fragment against
what its type takes before anything is stored: an `openai_compatible`
entry without `base_url` or `model` is refused there, and so is an
agent naming an entry that does not exist. A refused write stores
nothing; correct it and write again.

**At the apply.** Nothing written is serving until `vinga apply`, and
what can only be judged by building the entry inside the running
server is judged there: a key variable the server's environment does
not hold, a `reach` on a type that knows its own, a reach outside the
data boundary. The apply refuses with nothing running changed, but the
write it refused is still stored, and **the next start boots from what
is stored**: put the write back, or fix it and apply, before the server
restarts, or it will refuse to start with the same sentence.

What neither moment does is call the model, so an endpoint that is
wrong or unreachable passes both and fails the first turn instead.
When an apply takes effect and what it rebuilds is
[Applying a change without a restart](configuration.md#applying-a-change-without-a-restart).

## Local runners

### Reaching a runner on the host

A server in a container that dials `localhost` reaches the container,
not your machine. The compose file names the host
`host.docker.internal` for that reason, and the server warns with a
`provider_reaches_loopback` event at the apply when an entry built
inside a container names `localhost`, which is the only sign there is
until the first turn fails.

**On Linux the name is not enough.** It resolves to an address of the
host, and a runner listening only on the host's loopback, which is
Ollama's default and llama.cpp's, is not listening there. The runner
has to listen on an address the container can reach:

- Ollama: the `OLLAMA_HOST` variable, set where Ollama starts (its
  [FAQ](https://github.com/ollama/ollama/blob/main/docs/faq.md) shows
  the systemd form);
- `llama-server`: `--host`;
- LM Studio's `lms server start`: `--bind`.

`0.0.0.0`, every interface, always works, and it also opens the
runner, which asks for no key, to everyone on your network; listening
on the one address the container reaches does not. Which address that
is depends on the container engine: on the rootless Podman this guide
was run on, `host.docker.internal` led to the host's LAN address, and
a listener on loopback or on the `docker0` bridge refused the
connection. So check from inside the container rather than from the
host, where loopback always answers:

```bash
docker compose exec vinga python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/v1/models').read().decode())"
```

It prints the runner's model list, which is also the vocabulary the
entry's `model` is written in; `Connection refused` means the runner
is not listening where the container looks. On macOS, Docker Desktop
resolves the name itself and reaches a runner on the host's loopback,
which is how Getting Started was walked.

A server started from a checkout on the host, rather than in the
container, is on the host already, and `localhost` is right for it.

### Ollama

```bash
ollama pull gemma4:e4b
ollama show gemma4:e4b    # Capabilities lists tools
```

Load and pin it with Getting Started's step 0 request, naming
`gemma4:e4b`, then write the entry and apply it:

```bash
vinga provider set llm local -f - <<'YAML'
type: openai_compatible
# The host, from inside the container.
base_url: http://host.docker.internal:11434/v1
# In Ollama's vocabulary: the NAME column of `ollama list`.
model: gemma4:e4b
# Sent to Ollama with every request: answer without streaming the
# model's thinking first.
reasoning_effort: none
# Your assertion about where the endpoint is, which base_url decides:
# this machine.
reach: host
YAML
vinga apply
```

That replaces `local`, so every agent inheriting it now answers
through `gemma4:e4b`. For `qwen3:8b`, write that name and keep
`reasoning_effort`; for `llama3.1:8b`, write that name and leave
`reasoning_effort` out.

### Other local runners

What changes from one runner to the next is the address and the
vocabulary the model is named in. Each runner's default port, as its
own documentation gave it on 2026-10-06:

| Runner | `base_url` from the container | `model` is | Tool calls need |
| --- | --- | --- | --- |
| [Ollama](https://docs.ollama.com/api/openai-compatibility) | `http://host.docker.internal:11434/v1` | a NAME from `ollama list` | a model whose `ollama show` lists `tools` |
| [llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) `llama-server` | `http://host.docker.internal:8080/v1` | the `--alias` it was started with, else the model file's path | `--jinja`, on by default in current builds |
| [LM Studio](https://lmstudio.ai/docs/developer/openai-compat) | `http://host.docker.internal:1234/v1` | the model identifier LM Studio shows | a model with tool use, which its documentation covers |
| [vLLM](https://docs.vllm.ai/en/latest/features/tool_calling.html) | `http://host.docker.internal:8000/v1` | the Hugging Face id `vllm serve` was given | `--enable-auto-tool-choice` and a `--tool-call-parser` |

Whatever the runner, `<base_url>/models` lists the ids it answers to,
which is what the check above prints. A port you changed is the port
to write, and `llama-server` announces in its own log that its default
will move, so start it with `--port` rather than rely on the default.

A `llama-server` on the host, started so the container can reach it
and tool calls work, and its entry:

```bash
llama-server -m ./qwen2.5-1.5b-instruct-q4_k_m.gguf \
    --alias qwen2.5-1.5b-instruct --jinja --host 0.0.0.0 --port 8080
```

```bash
vinga provider set llm llamacpp -f - <<'YAML'
type: openai_compatible
base_url: http://host.docker.internal:8080/v1
model: qwen2.5-1.5b-instruct
reach: host
YAML
```

Then point `agent_defaults` or an agent at `llamacpp` as above, and
apply. A runner in a container of its own on the same compose network
is reached by its service name instead
(`http://llamacpp:8080/v1`), with nothing published on the host at
all.

LM Studio and vLLM were not run for this guide: their rows are their
documentation's, and their recipe is this entry with their address and
their model id.

## Vendors

### The data boundary comes first

A deployment can declare how far session data may travel, and a
declared boundary refuses a vendor. `server.data_boundary` is server
configuration, in the server's config file or as
`VINGA_SERVER__DATA_BOUNDARY` in its environment (Getting Started's
`.env` sets neither, so it declares none), and the server reads it
once, at start. Under `host` or `network`, an `anthropic` entry an
agent uses is refused, and so is an `openai_compatible` one whose
`reach` is `internet`, naming the entry and the boundary: at the apply,
and at every start while it is stored.

So before a vendor recipe, look at what the deployment declares. If it
declares `host` or `network`, letting a conversation reach a vendor
means changing that declaration, to `internet` or removed. That is a
decision about where what the household says goes, and the boundary
exists so that it is made once and on purpose rather than by an entry;
[The data boundary](security.md#the-data-boundary) is what it
promises. Change the file or the environment and restart the server
(`docker compose --profile server up -d` recreates the container with
it), then write the entry and apply it. Under any declared boundary,
`internet` included, every `openai_compatible` entry still has to state
its own `reach`.

### The key

A vendor needs its key, and the key is never a field of the entry and
never an argument: the entry names where the server finds it. The
server refuses a write that carries a credential-shaped value under a
key named like one, `api_key=...` among the inline `key=value`
arguments included, but that refusal stores nothing and protects
nothing: by the time it answers, the key is already in your shell's
history and was visible in the process list while the command ran.
Treat a key typed into an argument as exposed and replace it at the
vendor. An entry naming a variable the server's environment does not
hold refuses the apply. There are two places for it, and the order
is the same for both: the key reaches the server, or the store, before
the apply that puts the entry in service.

**In the server's environment**, named by the entry's `api_key_env`.
The deployment's env file is where it goes, written so the key is
never part of a command: the file private before anything is in it,
the line typed in an editor, and a restart, since the environment is
read at start.

```bash
# Getting Started's .env is already readable only by you. A new env
# file is made so before anything is in it:
#   install -m 600 /dev/null vinga.env
"${EDITOR:-vi}" .env    # add ANTHROPIC_API_KEY=<the key>, pasted here only
docker compose --profile server up -d    # recreates the server with it
```

**Encrypted in the database**, with `vinga provider secret set`, which
reads the key at its own prompt without echoing it, and takes
precedence over `api_key_env` on the same entry (the variable it names
is then not read at all). It needs `VINGA_MASTER_KEY` in the server's
environment first, generated and kept apart from the database as
[The master key](security.md#the-master-key) describes. A secret is
stored on an entry, so the entry comes first: the command refuses a
secret for an entry that is not written. Write the entry from its
recipe below, store the key on it, and only then point an agent at it
and apply, which is when the stored key reaches a conversation:

```bash
# After `vinga provider set llm claude ...` from the recipe below:
vinga provider secret set llm claude api_key    # an installed client
docker compose exec vinga vinga provider secret set llm claude api_key    # the container's
# Then point agent_defaults or an agent at claude, and:
vinga apply
```

The shell function from Getting Started runs the client without a
terminal (`-T`), so it has no prompt to give and cannot hide what you
type; call the container's client the way the second line does
instead. Both places are described under
[Secrets](security.md#secrets).

### Anthropic

```bash
vinga provider set llm claude -f - <<'YAML'
type: anthropic
model: claude-sonnet-5
# The variable holding the key, never the key.
api_key_env: ANTHROPIC_API_KEY
YAML
```

Then store the key, if it goes in the database rather than the
environment, point `agent_defaults` or an agent at `claude`, and
apply. The type knows it reaches Anthropic, so it takes no `reach`, and an entry
declaring one is refused at the apply. Without a `max_tokens` it caps
a reply at 1024 tokens, which a spoken reply does not come near.

### OpenAI

OpenAI is the `openai_compatible` type pointed at OpenAI. `base_url` is
required on the type, so the recipe writes it:

```bash
vinga provider set llm openai -f - <<'YAML'
type: openai_compatible
base_url: https://api.openai.com/v1
model: gpt-5.4-mini
api_key_env: OPENAI_API_KEY
# The current models refuse max_tokens and take this instead; the type
# sends it as written.
max_completion_tokens: 1024
reach: internet
YAML
```

Then store the key, if it goes in the database, point
`agent_defaults` or an agent at `openai`, and apply. Leave
`max_tokens` out: a model of the current family answers it with an
HTTP 400. An entry with no key at all is not refused, since a local
runner needs none, so a missing key against OpenAI shows only as a
failed first turn.

### OpenAI-compatible services

The same entry with the service's address, its key's variable and a
model id from its own catalogue. The addresses, from each service's
documentation on 2026-10-06:

| Service | `base_url` |
| --- | --- |
| [Groq](https://console.groq.com/docs/openai) | `https://api.groq.com/openai/v1` |
| [OpenRouter](https://openrouter.ai/docs/quickstart) | `https://openrouter.ai/api/v1` |
| [Together](https://docs.together.ai/docs/openai-api-compatibility) | `https://api.together.ai/v1` |

None of the three was run for this guide. Whether a given model of
theirs makes tool calls is theirs to say, and the test under
[What the model has to do](#what-the-model-has-to-do) is how to find
out.

## When it does not answer

Each of these is a turn that ends in the fallback phrase or a refused
command, and `vinga events tail --follow` or the refusal names which
one it was.

- **`localhost` from inside the container.** A
  `provider_reaches_loopback` warning at the apply, then a
  `provider_failed` on the first turn. Use `host.docker.internal`
  ([Reaching a runner on the host](#reaching-a-runner-on-the-host)).
- **A runner listening only on the host's loopback.** The apply
  succeeds and every turn is a `provider_failed`; the check from inside
  the container answers `Connection refused`.
- **A cold or slow model.** An `llm_retry`, then a `provider_failed`
  with `FirstTokenTimeout`, or with `ProviderCallTimeout` past 30
  seconds: pin the model loaded, or choose one the machine runs fast
  enough ([The local model](#the-local-model)).
- **A key or a request the vendor refuses.** An unset variable refuses
  the apply, naming the entry. A key the vendor rejects, or a field its
  model will not take, is a `provider_failed` with `ProviderCallError`,
  the same as an endpoint that is not there: the event names the entry,
  the host and the model, and neither the HTTP status nor the vendor's
  words, which are kept out of the log. Send the request by hand to see
  the answer.
- **An entry outside the data boundary.** The apply is refused, naming
  the entry and the boundary, and the running configuration is
  unchanged; put the write back before the next restart
  ([The data boundary comes first](#the-data-boundary-comes-first)).
- **A model that does not call tools.** No `tool_call` where one was
  needed, a `sentence_withheld` where it wrote the call out as text, or
  an answer the tool would have corrected. Choose a model that passes
  the tool check.

## What was run for this guide

On 2026-10-06, on the Raspberry Pi 5 above, with rootless Podman as the
container engine. Every recipe that was run was written with this
page's commands, applied, and then asked, through the device simulator,
a question only a tool could answer, with the speech stages replaced by
test doubles so the turn exercised the LLM entry alone:

| Recipe | Where the server ran | Tool call made |
| --- | --- | --- |
| Ollama, `qwen3:8b` and `llama3.1:8b` | from a checkout on the host, `base_url` on `localhost`, since the runner there listens only on loopback and was left that way | yes, both |
| llama.cpp, `qwen2.5-1.5b-instruct` | the published image under Getting Started's compose file, the runner in a container on the same network | yes |
| Anthropic, `claude-sonnet-5`, the key in the env file | the same | yes |
| OpenAI, `gpt-5.4-mini`, the key stored encrypted | the same | yes |

The container-side check under
[Reaching a runner on the host](#reaching-a-runner-on-the-host) was run
against a runner on loopback, where it answered `Connection refused`.
LM Studio, vLLM, Groq, OpenRouter and Together were not run.
