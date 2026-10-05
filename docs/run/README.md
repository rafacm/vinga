# Task guides

One page per task a person running vinga-server does, each opening with
what you will have at the end and linking the generated
[reference](../reference/) for every key, route and event it names
rather than restating it. They are grouped by what you are doing.

The server's providers, tools, memory, prompts, configuration API,
security defaults, conversation behavior and observability are in the
[server README](../../vinga-server/README.md).

## Deploying

- [Running vinga in a container](running-in-a-container.md): the
  single container and what it needs, one replica, the two mounts, and
  which image variant and tag to deploy.
- [Backing up and restoring the database](backups.md): a `pg_dump`
  taken while the server runs, the restore, and the keys it needs.
- [Setting limits and probes](limits-and-probes.md): how many
  conversations one server holds and for how long, how a shutdown
  drains, and which probe an orchestrator restarts on and which it
  routes traffic by.
