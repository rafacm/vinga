# Task guides

One page per task a person running vinga-server does, each opening with
what you will have at the end and linking the generated
[reference](../reference/) for every key, route and event it names
rather than restating it. They are grouped by what you are doing.

The server's providers, tools, memory, prompts, configuration API,
security defaults, conversation behavior and observability are in the
[server README](../../vinga-server/README.md).

## Deploying

- [Providing the database](database.md): the Postgres a deployment
  brings, what the server role needs, the provisioning file, and
  reading the conversation record as `vinga_ro`.
- [Running vinga in a container](running-in-a-container.md): the
  single container and what it needs, one replica, the two mounts, and
  which image variant and tag to deploy.
- [Backing up and restoring the database](backups.md): a `pg_dump`
  taken while the server runs, the restore, and the keys it needs.
- [Upgrading a deployment](upgrading.md): rerunning the provisioning
  file before a new image boots, the API secret, which build is
  running, and where each past release's own upgrade notes are.
- [Recovering a deployment that will not start](recovering-a-deployment.md):
  what to have in hand, the choice between resetting the configuration
  alone and dropping the whole database, and the rebuild from a kept
  export.
- [Securing a deployment](security.md): the master key that encrypts
  stored credentials, where it is escrowed, and rotating it.

## Configuring

- [Changing the configuration](configuration.md): why an edit to a
  running deployment is stored and not yet in effect, and the two ways
  it becomes effective.
- [Setting limits and probes](limits-and-probes.md): how many
  conversations one server holds and for how long, how a shutdown
  drains, and which probe an orchestrator restarts on and which it
  routes traffic by.
