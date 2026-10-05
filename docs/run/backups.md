# Backing up and restoring the database

At the end of this guide you will have a dump of everything vinga
stores, taken while the server keeps serving, a restore rehearsed on
something disposable, and the master keys that restore needs kept apart
from the dump.

## Taking a dump

**Backups are `pg_dump`, and the server keeps running through one.**
A dump reads inside one transaction with a snapshot of its own, so
what it writes is the database as of the moment it started, whatever
lands afterwards, and there is nothing to stop and nothing to quiesce:

```bash
pg_dump --format=custom --file "/backup/vinga-$(date +%F).dump" \
  "postgresql://vinga@db.internal:5432/vinga"
```

Every schema travels in one dump, because they are one database, and
that now includes what the agents were asked to remember: memory is a
schema rather than a directory, so a dump covers it and there is
nothing beside the database left to back up.
A restore is `pg_restore` into an empty database for the custom format
above (`pg_restore --dbname ...`), or `psql --file` for a plain-text
dump, and it is worth rehearsing on something disposable rather than
first attempting on the day it is needed.

## What a restore needs, and what a copy exposes

**A restore needs both halves of the secret.** The dump, and every
master key still required to decrypt what it holds, which is why the
keys are escrowed with the deployment's other environment secrets and
separately from the backup itself. A restored database with no key is
a configuration whose credentials will not open.

**What a copy of the database exposes.** No stored plaintext secret:
the encrypted values are ciphertext and the environment references are
variable names rather than values. It does expose the rest of the
domain configuration, which is to say the prompts, the endpoints and
the variable names, and, where recording is on, everything the
conversation record holds. Dumps belong in access-controlled storage,
not in a repository.
