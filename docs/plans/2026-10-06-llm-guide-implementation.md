# A guide to choosing and configuring the LLM: implementation

Companion to [`2026-10-06-llm-guide.md`](2026-10-06-llm-guide.md), one
section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the LLM guide

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.289; 2026-10-06.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| Decisions 1 to 4, D1 to D6a, D7's per-recipe statement | `docs/run/llm.md` (new) | `Add the LLM task guide` |
| Decision 5's reachability: the index, `providers.md`, Getting Started's step 0 and the model bullet | `docs/run/README.md`, `docs/run/providers.md`, `README.md` | `List the LLM guide and link it from its neighbours` |
| The fragment, `### Added`, no `Upgrade:` line | `changelog.d/364-llm-guide.md` | `Add the changelog fragment for the LLM guide` |
| This record and the tick | this file, the plan | `Record M1 of the LLM guide` |

The guide opens with what you will have at the end and links the
reference rows for every field and key it names (decision 4); field
semantics are summarized and linked, never tabled again. Its sections:
what the model has to do (D2), the local model (D1, D3), pointing an
agent at an entry (decision 1), local runners with the reachability
prerequisite, the Ollama recipe, the runner table and the llama.cpp
recipe (D4, D4a), vendors with the boundary first, the key, Anthropic,
OpenAI and the compatible services (D5, D5a, D5b, D6, D6a), the traps
collected (decision 3), and what was run (D7).

### Deviations from the plan

- **The boundary is checked in the file or the environment, not with
  `vinga info`.** D5b names `vinga info` as one place to read
  `server.data_boundary`; it does not report it (no line under
  `config/cli/` or in `config/api.py` names the key, by an untruncated
  grep, `.logs/data-boundary-cli.txt`). The guide says where the
  key lives (the config file, or `VINGA_SERVER__DATA_BOUNDARY`) and
  that Getting Started's `.env` sets neither.
- **The fragment is `### Added`**, since the change is a new page
  rather than a move; the standing rules' `### Changed` was #609's.
- **The Ollama recipe carries `reasoning_effort: none`.** D1 keeps
  `qwen3:8b` as the lead, and it stays the lead; the passthrough key is
  added because the Pi measured the thinking as the whole reply (below),
  and the guide says to leave it out for `llama3.1:8b`. The preset and
  the example are unchanged, as D1 requires.
- **The Ollama recipe ran against a server from the checkout, not the
  container.** D4a's container path needs the runner listening on an
  address the container reaches. On agentpi the Ollama container is
  published on `127.0.0.1` only, and widening it (a forwarder on the LAN
  address) was refused by the session's permission classifier as
  exposing a local service, so it was stopped at once and not retried.
  The server for that recipe ran from the worktree with `base_url` on
  `localhost`, which the guide states as the checkout case; the
  container path was exercised by the in-container check (below) and
  by the llama.cpp, Anthropic and OpenAI recipes, which ran in the
  published image under Getting Started's compose file.
- **The llama.cpp runner was a container on the compose network**
  (`ghcr.io/ggml-org/llama.cpp:server`, arm64, created 2026-10-05,
  `-hf Qwen/Qwen2.5-1.5B-Instruct-GGUF:Q4_K_M --alias
  qwen2.5-1.5b-instruct --jinja --host 0.0.0.0 --port 8080`, nothing
  published on the host), so its `base_url` was
  `http://llamacpp:8080/v1`. The guide's host recipe differs only in
  the address, and the guide names the service-name form.
- **The local lane does not pass on this machine**, at the default
  watchdog or raised (below). D7 anticipated raising
  `llm_first_token_timeout_s`; the lane builds its `Config` in code, so
  the raise was a throwaway two-line patch to `tests/local/conftest.py`
  for the one run, restored and touched afterwards, never committed.

### Resolutions

- **D1's open question** (one default for the preset, the example and
  Getting Started) stays Rafael's, as the plan says. What this
  milestone adds to it: on a CPU-only Pi 5 neither 8B model is a
  conversation, and `qwen3:8b` needs `reasoning_effort: none` on any
  machine where its thinking is slower than the walkthrough's Mac.
- **D7b.** Every recipe that ran made its tool call; none is marked
  unverified for tools.

### Discoveries

- **The watchdog cannot usefully be raised past 30 s.** The provider's
  client is built with `timeout=DEFAULT_TIMEOUT_S` (`providers/kit.py`
  L48, `providers/openai_llm.py` L171) and no retries (`kit.py` L61),
  so a request with no byte for 30 s fails as `ProviderCallTimeout`
  before a longer watchdog could fire. Measured: with the watchdog at
  60 s, two `qwen3:8b` turns and one `llama3.1:8b` turn failed at
  30.0 s (`.logs/turn-ollama-qwen3-w60-1.txt`, `-2.txt`,
  `turn-ollama-llama31-w60-2.txt`). `limits-and-probes.md` recommends
  raising the watchdog for a local model; the guide states the bound.
- **`qwen3:8b`'s thinking is the whole reply on a slow machine.** Its
  reasoning chunks keep the stream alive, so the watchdog never fires
  (`provider_watch.py` L255 waits on the first event, and
  `openai_llm.py` L269 yields `StreamStarted` on the first chunk of any
  kind). On the Pi, thinking on: tool round 78 to 84 s, first spoken
  token 47 s into the answer round, over two minutes a turn; with
  `reasoning_effort: none` sent as a passthrough key
  (`openai_llm.py` L247): 9.5 s and 6 s
  (`.logs/turn-ollama-qwen3-thinking-*.txt`,
  `turn-ollama-qwen3-w10-4..6.txt`). A direct stream against Ollama
  showed the same: first content at 46.8 s with thinking, 0.5 s
  without (`.logs/qwen3-stream-probe.txt`).
- **A refused apply leaves the write stored, and the next start
  refuses.** Under `data_boundary: host`, pointing the agent at an
  `anthropic` entry was refused at the apply ("type "anthropic" reaches
  the internet, but this server's data boundary is host"), and the
  restart that followed refused to boot with the same sentence,
  because the agent write was stored (`.logs/run-boundary-3.txt`,
  `-4.txt`, `-5.txt`). The guide says to put the write back.
- **`provider_failed` cannot tell a rejected key from a missing
  endpoint.** `call_failure` composes a message with the HTTP status
  (`providers/kit.py` L93), but the event reports the class name only
  (`events/assembly.py` L770, by design, `provider_watch.py` around
  L483) and the log line is built from the same, so a 401, a 400 and a
  refused connection all read `ProviderCallError`
  (`.logs/provider-failed-log.txt`). The status is an integer and
  metadata; a `status` field would be a small follow-up for its owner.
- **On rootless Podman, `host.docker.internal` is the host's LAN
  address.** agentpi's "Docker" is Podman 5.4.2 behind the Docker CLI.
  The name resolved to `169.254.1.2` inside the container, and a
  throwaway listener answered there only when bound to the LAN address
  or `0.0.0.0`, not on loopback or on `docker0`
  (`.logs/podman-host-gateway-probe.txt`, `.logs/d4a-before.txt`).
- **`llama-server` says its default port will change** to 9931 in a
  future release (`.logs/llamacpp-port-notice.txt`), which is why the
  guide tells the reader to pass `--port`.
- **Ordering of apply refusals.** An unset key variable is reported
  before a boundary or `reach` refusal of the same entry
  (`.logs/run-boundary-2.txt`), so a reader meets them one at a time.

### Claims checked against the code

Every statement the guide makes about what the server refuses,
retries, converts or logs, with its evidence (lines in
`.logs/claims-lines.txt`; runs in `.logs/`):

| Claim | Code | Observed |
| --- | --- | --- |
| A round with no first sign of life in `llm_first_token_timeout_s` is retried once, then given up as `FirstTokenTimeout` | `runtime/provider_watch.py` L255, L274, L292; `config/models.py` L1493 | `turn-llamacpp-1.txt`, `turn-ollama-llama31-w10-1.txt` |
| Any chunk stops the clock; a tool-only round has no `first_token_ms` | `providers/openai_llm.py` L269; events reference | every `llm_round` with `round=1` |
| The request gives up after 30 s without a byte, not configurable | `providers/kit.py` L48, L61; `openai_llm.py` L171 | `turn-ollama-*-w60-*.txt` |
| A quoted argument is converted only where exact, with `tool_arguments_coerced` | `tools/arguments.py` L71; `runtime/tool_execution.py` L70, L131 | not triggered in these runs |
| A sentence shaped like an offered call is withheld | `docs/system-overview.md`, Flow 2 | `turn-ollama-llama31-w60-1.txt` (`sentence_withheld`) |
| A `key=value` named like a credential is refused before it is sent | `config/models.py` L63, L2424 | `probes-write.txt` |
| `base_url` is required on `openai_compatible` | options model | `probes-write.txt` |
| An unset `api_key_env` variable refuses the apply, naming the entry | `providers/kit.py` L173 | `probes-reach.txt`, `run-boundary-2.txt` |
| A stored secret wins and the reference is not read | `providers/kit.py` L166 | `run-openai-2.txt` (`OPENAI_API_KEY` unset, apply served) |
| Storing a secret needs `VINGA_MASTER_KEY` | `config/secrets.py` L236 | read, not exercised |
| `secret set` prompts without echo at a terminal, reads stdin plainly otherwise | `config/cli/input.py` L553, L558 | `pty-prompt.txt` (prompt shown, dummy value not echoed) |
| `reach` on `anthropic` is refused at the apply | `boundary.py` L123 | `run-anthropic-reach.txt` |
| `anthropic` and `internet` reach refused under `host`; every `openai_compatible` entry must state `reach` under any boundary | `boundary.py` L135, L141, L151 | `run-boundary-5.txt` |
| `anthropic` caps a reply at 1024 tokens unset | `providers/kit.py` L51; `anthropic_llm.py` L285 | read |
| An `openai_compatible` entry with no key is not refused, and fails its first turn | `openai_llm.py` L170 | `run-openai-probes.txt` |
| `max_tokens` is answered 400 by the current OpenAI family | `openai_llm.py` L227 comment | `openai-max-tokens-direct.txt` (400, `unsupported_parameter`) |
| Unknown keys travel in the request | `openai_llm.py` L185, L247 | `reasoning_effort` took effect |
| `localhost` in a container: a `provider_reaches_loopback` warning at the apply, never a refusal | `providers/world.py` L332, L370 | `probes-loopback.txt` |
| An unreachable endpoint passes the apply and fails the turn with the fallback phrase | `openai_llm.py` (no request at build) | `turn-loopback.txt` |
| `provider_failed` carries the class name, not the status or the vendor's words | `events/assembly.py` L770 | `provider-failed-log.txt` |
| A boundary change needs a restart, and compose recreates on an env-file change | server-config reference | `run-boundary-1.txt` (`Recreate`) |

### Execution record

On agentpi (Raspberry Pi 5, 16 GB, CPU only, rootless Podman 5.4.2
behind the Docker CLI), 2026-10-06. The harness (`.logs/turn.sh`,
`.logs/xz_turn.py`, not committed) ran one turn per call: the shipped
`vinga simulator run` for the container deployment, and an
`xiaozhi_sdk` client with a longer ceiling for the slow Ollama runs,
with `vinga events tail --follow` capturing event names and metadata.
The agent had `mock` ASR, TTS and VAD, so the turn exercised the LLM
entry alone; the question was the mock transcript "Ask the tool for
the secret word, then tell me what it is."; the agent was granted the
integration lane's stdio MCP server
(`tests/support/mcp_stdio_server.py`) narrowed to `secret_word`, and
its memory was off to keep the prompt small. Only the tool knows the
answer, so a reply naming it is a reply that called it.

The container deployment was Getting Started's compose file and the
published `ghcr.io/rafacm/vinga-server:slim` (revision `3a6d2346`,
code-identical to this branch's base), in its own project with its own
Postgres on `127.0.0.1:5433` and the server on `127.0.0.1:8003`; the
Ollama run's server came from the worktree on `127.0.0.1:8004`, with
its own database `vinga_ollama` on that Postgres. The development
database was not touched.

| Recipe | Write and apply | Turns | `tool_call` | Timings |
| --- | --- | --- | --- | --- |
| llama.cpp, `qwen2.5-1.5b-instruct` | wrote, `agent_defaults` exported, edited, set, applied (`run-llamacpp-write.txt`) | 3 | turns 2 and 3; turn 1 `FirstTokenTimeout` | warm: tool round 2.7 s, `first_token_ms` 624 |
| Anthropic, `claude-sonnet-5`, key in the env file | wrote, agent exported, edited, set, applied (`run-anthropic-write.txt`) | 2 | both | tool round 1.3 to 1.5 s, `first_token_ms` 639 to 1010 |
| OpenAI, `gpt-5.4-mini`, key stored encrypted | wrote, secret stored, agent pointed, applied (`run-openai-1.txt`, `-2.txt`) | 2 | both | tool round 1.2 to 2.9 s, `first_token_ms` 513 to 1153 |
| Ollama, `qwen3:8b`, `reasoning_effort: none` | wrote, applied (`run-ollama-write.txt`) | 6 at 10 s, 3 at 60 s | 5 of 9 | tool round 9.2 to 9.6 s, `first_token_ms` 5982 to 6299; 2 `FirstTokenTimeout`, 2 `ProviderCallTimeout` |
| Ollama, `qwen3:8b`, thinking on | wrote, applied | 2 | both | tool round 78 to 84 s, `first_token_ms` 47361 to 47888 |
| Ollama, `llama3.1:8b` | wrote, applied (`run-ollama-llama31-write.txt`) | 4 at 10 s, 3 at 60 s | 3 of 7 | tool round 15 to 42 s, `first_token_ms` 4538 to 4612; 3 `FirstTokenTimeout`, 1 `ProviderCallTimeout`, 1 `sentence_withheld` |

Every completed turn whose reply the harness checked named the tool's
answer; three early `qwen3:8b` turns ran before it reported that, and
their `tool_call` is the evidence. Cold loads, from
a direct stream (`.logs/qwen3-stream-probe.txt`,
`llama31-stream-probe.txt`): 20.3 s and 20.9 s to the first byte.
`ollama ps`: `llama3.1:8b` 5.6 GB, `qwen3:8b` 5.9 GB, 100% CPU.

The local lane, `VINGA_LOCAL_LANE=1 VINGA_LOCAL_LLM_MODEL=llama3.1:8b
uv run pytest tests/local -q -ra`, with `faster-whisper` and `piper`
synced: `3 failed in 217.88s (0:03:37)`, every conversation given up
with `FirstTokenTimeout` (`.logs/local-lane-1.txt`). With the watchdog
raised to 29 s, under the 30 s bound above: `3 failed in 353.15s
(0:05:53)`, the same way (`.logs/local-lane-2-watchdog29.txt`). The
lane's prompts carry the memory tools and its speech engines share the
CPU, so on this machine it does not reach a first token in time.

Not run: LM Studio, vLLM (a desktop application and a GPU server),
Groq, OpenRouter, Together (no keys). The guide says so in its own
words.

### Inventories

Untruncated, under `.logs/` in the implementer's worktree.

- `qwen3` outside `docs/plans/` and `CHANGELOG.md` at `94df0ddb`
  (`.logs/qwen3-sites.txt`): 71 lines, positions only; none changed.
- D8a's sweep over `docs/run/llm.md` for secret-named expansions,
  `curl -u` or `-H`, command substitution, `printf`, `export` and
  `-e NAME=` (`.logs/d8a-llm.txt`): 0 positions. The guide's key
  procedures are an editor and a restart, or the client's own prompt.
- Runner and vendor addresses, quoted from their documentation on
  2026-10-06 (`.logs/runner-docs.txt`).

### Verification

On agentpi, from the worktree root unless noted:

- `python3 scripts/check_doc_links.py .`: `checked 328 files, 0 failures`, exit 0.
- `python3 scripts/check_run_use_pages.py .`: `checked 35 Run and Use pages, 0 findings`, exit 0 (34 before, plus `llm.md`).
- `python3 scripts/fold_changelog.py check .`: `checked 1 fragments, 0 failures`, exit 0.
- `uv run pytest tests/census -q` from `vinga-server/`: run last, after
  this section; its outcome is in the hand-back rather than here.
- Not run: `uv run ruff check .` and the unit lane, since M1 changes no
  code and no test.
