### Added

- A search MCP fragment, `examples/mcp-server-search.yaml`, tuned for a device that answers out loud: one granted tool rather than the whole server, a timeout that bounds how much silence a call may cost, and guidance asking for few results, one or two spoken sentences, no URLs read aloud, and no searching for what a sibling tool already answers. Hosted rather than spawned, since the published image carries no runtime that can spawn a stdio MCP server.

### Changed

- The example fragments say where a tool grant is withheld, not only where it is defined. Granting search at `agent_defaults` gives it to every agent in a deployment, a bedtime storyteller and an agent a child talks to included, so both fragments now state that withholding is an ordinary configuration choice and which key makes it.
