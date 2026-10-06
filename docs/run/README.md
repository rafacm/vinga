# Task guides

One page per task a person running vinga-server does, each opening with
what you will have at the end and linking the generated
[reference](../reference/) for every key, route and event it names
rather than restating it. They are grouped by what you are doing.

The server's configuration API, security defaults, conversation
behavior and observability are in the
[server README](../../vinga-server/README.md).

## Deploying

- [Running vinga in a container](running-in-a-container.md): the
  single container and what it needs, one replica, the two mounts, and
  which image variant and tag to deploy.
- [Providing the database](database.md): the Postgres a deployment
  brings, what the server role needs, the provisioning file, and
  reading the conversation record as `vinga_ro`.
- [Exposing a deployment](exposing-a-deployment.md): one port for
  everything, what a reverse proxy has to get right, and what happens
  to the configuration API at the edge.
- [Setting limits and probes](limits-and-probes.md): how many
  conversations one server holds and for how long, how a shutdown
  drains, and which probe an orchestrator restarts on and which it
  routes traffic by.
- [Securing a deployment](security.md): the master key that encrypts
  stored credentials, where it is escrowed, and rotating it.

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

- [Choosing providers](providers.md): which engine can serve each
  stage, which run on your host and which reach a vendor, and what an
  install carries for each.
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
  `vinga memory`, and switching memory off.
- [Composing what an agent is told](agents-and-prompts.md): previewing
  the whole system prompt block by block, and sharing text between
  agents as fragments.
- [Changing the configuration](configuration.md): why an edit to a
  running deployment is stored and not yet in effect, and the two ways
  it becomes effective.
- [Onboarding a device](onboarding-a-device.md): the short URL a board
  is given, checking what answers there, and binding the board by the
  code it shows.
