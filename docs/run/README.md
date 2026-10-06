# Task guides

One page per task a person running vinga-server does, each opening with
what you will have at the end and linking the generated
[reference](../reference/) for every key, route and event it names
rather than restating it. They are grouped by what you are doing.

Changing the server rather than running it is
[Contributing to vinga](../contributing.md).

## Handing the work to a coding agent

- [Running vinga with a coding agent](with-a-coding-agent.md): for a
  coding agent working on a person's behalf, and read before this
  index: which version of these guides to read, the order of the work,
  the steps that stay the person's, and proving a reply comes back.

## Deploying

- [Running vinga in a container](running-in-a-container.md): the
  single container and what it needs, one replica, the two mounts, and
  which image variant and tag to deploy.
- [Providing the database](database.md): the Postgres a deployment
  brings, what the server role needs, the provisioning file, how the
  server is told where it is, and reading the conversation record as
  `vinga_ro`.
- [Exposing a deployment](exposing-a-deployment.md): one port for
  everything, what a reverse proxy has to get right (the onboarding key
  kept out of its log, the browser page on a secure context), and what
  happens to the configuration API at the edge.
- [Setting limits and probes](limits-and-probes.md): how many
  conversations one server holds and for how long, how a shutdown
  drains, and which probe an orchestrator restarts on and which it
  routes traffic by.
- [Securing a deployment](security.md): where each credential is
  kept, the master key and its rotation, the hosts a configuration
  reaches, device authentication and the OTA endpoint, everything the
  server exposes, and the data boundary.

## Keeping a deployment running

- [Upgrading a deployment](upgrading.md): rerunning the provisioning
  file before a new image boots, which build is running, and where
  each past release's own upgrade notes are.
- [Backing up and restoring the database](backups.md): a `pg_dump`
  taken while the server runs, the restore, and the keys it needs.
- [Recovering a deployment that will not start](recovering-a-deployment.md):
  what to have in hand, the choice between resetting the configuration
  alone and dropping the whole database, and the rebuild from a kept
  export.

## Configuring

- [Configuring a deployment](configuration.md): the server half in a
  file and the domain half in the database, writing a whole deployment
  from one document, when an edit takes effect, and installing it
  without a restart.
- [Using the configuration API](configuration-api.md): the bearer
  token, the families of routes and where each is specified, what a
  write's answer and a refusal carry, and how the `vinga` client finds
  a server.
- [Choosing providers](providers.md): which engine can serve each
  stage, which run on your host and which reach a vendor, and what an
  install carries for each.
- [Choosing the model an agent thinks with](llm.md): what a model has
  to do for a voice agent, the local default and its measurements, and
  pointing an agent at Ollama, another local runner, Anthropic, OpenAI
  or a compatible service, with its key kept out of every command.
- [Choosing how an agent hears](speech-recognition.md): the local and
  the cloud transcription engines measured against each other, and
  setting OpenAI's vocabulary and languages.
- [Giving an agent a voice](voices.md): how long each voice keeps a
  device silent before a reply, and configuring ElevenLabs or OpenAI.
- [Giving an agent tools](tools-and-mcp.md): MCP servers and their
  transports, per-tool grants, guidance for the model, the builtins,
  and which servers are connected.
- [Configuring what an agent remembers](memory.md): facts, device notes
  and the conversation ledger, reading and correcting them with
  `vinga memory`, which providers they are sent to, and switching
  memory off.
- [Composing what an agent is told](agents-and-prompts.md): previewing
  the whole system prompt block by block, and sharing text between
  agents as fragments.
- [Tuning when a turn ends](turn-taking.md): how a device listens
  while a reply plays, what it takes for speech to interrupt one, and
  giving one agent a patient endpointer.
- [Masking slow replies and saying when one fails](slow-and-failed-replies.md):
  the filled pause a slow reply plays, the fixed phrase a failed one
  says, and what each costs at a start and an apply.
- [Onboarding a device](onboarding-a-device.md): the short URL a board
  is given, checking what answers there, binding the board by the code
  it shows, and the try link that binds a browser.

## Observing

- [Reading logs and traces](logs-and-traces.md): the log format, the
  index of events and when each fires, watching a board or the whole
  server live, and exporting traces to Jaeger, Langfuse or both.
- [Capturing a session](capturing-a-session.md): recording microphone
  and speaker on one timeline with the decisions beside them, for a
  problem no test lane can reproduce.
- [Pricing a conversation](conversation-cost.md): the usage each stage
  reports, and the model definitions a backend needs to price it.
- [Recording conversations](conversation-store.md): what the
  conversation store keeps and for how long, resuming a past
  conversation, erasing one on demand, and reading the record.
