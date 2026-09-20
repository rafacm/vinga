### Changed

- The command-spellings census runs in a lane of its own, `tests/census`, which declares no storage. It reads no database row and never did, but it lived under the unit tests and inherited their declaration, so the documentation workflow carried a Postgres service container for it. That container is gone. The census still runs in both workflows, so every change is still covered by it.
