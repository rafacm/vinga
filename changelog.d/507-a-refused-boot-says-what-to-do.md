### Changed

- **A boot refused by a stored row it cannot read now says what to do
  about it** (#507). Such a row makes the server print the entry it
  could not read and exit 1, and until now the obvious next step was a
  `vinga mcp-server delete` or `vinga provider delete` that cannot run:
  every command is a request to the configuration API, and that API is
  behind the boot that is refusing. The refusal now carries a second
  line naming both ways back: with a `vinga-server config export` taken
  while the deployment was healthy, start a server on an empty domain
  schema, import that document, enter each stored credential again and
  apply it; without one, correct or delete the addressed row with SQL as
  the role the server connects as. Both procedures are written out in
  `docs/reference/cli.md`. The line is printed only for a row that
  cannot be read as configuration, and never for a database this server
  cannot reach, a schema privilege it does not have or any other storage
  failure, whose configuration is healthy and whose remedy is not a
  rebuild.
- **The row that triggers it arrives from a restore or a hand edit
  rather than from this project.** The reported shape is an MCP or
  provider entry whose `reach` is not one of `host`, `network` or
  `internet`, which the migration that introduced `reach` deliberately
  carries across instead of aborting, on the grounds that aborting would
  lock an operator out of the one door to the row. Nothing here changes
  what refuses or when: a deployment that boots today goes on booting,
  and one that does not gets a second sentence.
- **One observability value changes with it.** The configuration API
  answers an unreadable stored row with the same 500 and the same
  sentence it always has, but the `failure` field of the
  `api_storage_error` event now names the more specific class
  (`StoredConfigUnreadableError`) instead of `StorageError` for that
  case. A consumer matching on the old spelling for this failure needs
  the new one; `StorageError` still appears for a database that cannot
  be reached.
