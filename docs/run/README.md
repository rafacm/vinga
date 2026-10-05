# Task guides

One page per task a person running vinga-server does, each opening with
what you will have at the end and linking the generated
[reference](../reference/) for every key, route and event it names
rather than restating it. They are grouped by what you are doing.

The server's providers, tools, memory, prompts, configuration API,
security defaults, conversation behavior and observability are in the
[server README](../../vinga-server/README.md).

## Deploying

- [Setting limits and probes](limits-and-probes.md): how many
  conversations one server holds and for how long, how a shutdown
  drains, and which probe an orchestrator restarts on and which it
  routes traffic by.
