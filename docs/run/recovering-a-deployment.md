# Recovering a deployment that will not start

At the end of this guide you will have a server that boots and serves
again, rebuilt from a kept export with its credentials re-entered, and
you will have chosen on purpose which of the recorded data, if any, the
rebuild was allowed to take with it.

## When the server will not start

A configuration the server refuses to boot on (a stored secret no
configured key opens, an entity that cannot be loaded, a reference that
no longer resolves) leaves nothing to write through, because every
config command is a request to a server that is not answering. The way
back is not a surgical edit: stop the server, delete the database, start
it again on the empty one, import the export taken while the deployment
was healthy, re-enter each stored credential through the `secret set`
commands that export listed at its foot, and apply.

It is a rebuild rather than a repair, and the difference is real: it
puts back what the export says and nothing else, so a row nobody knew
about goes with the schema. A deployment that wants a surgical edit to
the stored rows has one, through ordinary SQL against the `domain`
schema as the server role. That is deliberately not wrapped in this
project's own grammar: a second way in with its own vocabulary is a
second thing to keep honest, and `psql` is already documented by the
people who wrote it.

## What the rebuild needs in hand

That is what makes `vinga-server config export` worth keeping in version
control beside the YAML file: it is the document the import takes. A
stored credential never travels in a read, so the export carries the
command that enters each of them rather than the value, and the values
come from wherever the deployment keeps its secrets.

If the deployment records conversations, or its agents remember
anything, and any of it is worth keeping, take a dump now, as
[Backing up and restoring the database](backups.md) describes. Both
resets below delete something, and a dump taken first is the one copy
either of them leaves.

## Choosing what to reset

There are two resets, and the difference between them is what
survives. Resetting the `domain` schema alone deletes the configuration
and keeps the conversation record and memory; dropping the whole
database deletes all three. Choose one before running anything below.

### Resetting the domain schema alone

**A dropped database takes the conversation record with it**, since
every schema lives in one. What is broken here is the domain half, so a
deployment that is recording and wants to keep what it recorded drops
that half alone, as the server role, and reruns the provisioning file
after it:

```bash
# Stop the server first, so nothing is using the schema while it goes.
docker stop vinga && docker rm vinga

# Drop the configuration schema as the server role, which owns it, on
# the deployment's own database: the vinga service names both, and
# ~/.pgpass holds the role's password.
PGSERVICE=vinga psql -c 'drop schema domain cascade;'
```

The rerun is the same either way, and the reason is the same: a
`create schema` is what puts the schema back under the server role's
ownership, and a dropped database also took the default privileges
that let `vinga_ro` read tables the server has not created yet. The
next boot then migrates from nothing, which is the state this
procedure needs and the state a first-ever boot is in.

From there the rest is the whole-database block below from its
provisioning rerun on: rerun the provisioning file, start the server,
import, re-enter the credentials and apply. Skip everything in it
before the provisioning rerun, which stops the server again and drops
the whole database.

### Dropping the whole database

```bash
# This deletes every schema: the configuration, the conversation record
# and memory. Stop the container that will not serve, and take the
# database away. Nothing is connected to it while the server is down,
# which is what lets it be dropped rather than emptied table by table.
# dropdb and createdb connect to a maintenance database rather than the
# one they act on, so it is named; the host, the admin role and its
# password come from the vinga-admin service and ~/.pgpass, exactly as
# for psql below, and never from the defaults of the machine you type on.
docker stop vinga && docker rm vinga
PGSERVICE=vinga-admin dropdb --maintenance-db=postgres "$VINGA_DB_NAME" &&
  PGSERVICE=vinga-admin createdb --maintenance-db=postgres \
    --owner "$VINGA_DB_USER" "$VINGA_DB_NAME"

# Rerun the provisioning file: dropping the database took the two
# schemas and their default privileges with it, while vinga_ro, which
# is an instance-level role, is still there. The file expects that and
# rotates it rather than failing. The connection and its password come
# from the vinga-admin service and ~/.pgpass, never from an argument.
PGSERVICE=vinga-admin psql -f deploy/postgres-init.sql

# Start it again, which boots clean on the empty database, then put the
# configuration back and re-enter the credentials it could not carry.
# Use the run command from running-in-a-container.md.
docker run -d --name vinga ...
docker exec -i vinga vinga-server config import -f - < deployment.yaml
docker exec -i vinga vinga-server \
  config provider secret set -- llm claude api_key
docker exec vinga vinga-server config apply
```

The import writes and stops, which is the whole of what it does: the
engines the document names are built by the apply on the last line, and
their credentials are the line before it.

## Coming from a build that kept its configuration in a file

**Coming from a build that kept its configuration in a local file, it
is the same rebuild with one ordering to get right: export first, then
upgrade.** This build reads Postgres and only Postgres. There is no
driver in it for the old file, no configuration key that would point
at one, and no importer, so an export attempted after the image has
rolled is an export from a server that will not start:

```bash
# With the build you are still running.
docker exec -i vinga vinga-server config export > deployment.yaml

# Then point VINGA_DB_* at an empty database, roll the image, and put
# the configuration back exactly as above: import the document, re-enter
# each stored credential from wherever the deployment keeps its secrets,
# and apply.
docker exec -i vinga vinga-server config import -f - < deployment.yaml
docker exec -i vinga vinga-server \
  config provider secret set -- llm claude api_key
docker exec vinga vinga-server config apply
```

**The conversation record does not come across, and nothing pretends
otherwise.** There is no export format for it and no importer, and
inventing one for a pre-release store was not worth the tool it would
have become. A deployment that wants to keep what it recorded copies
the old `conversations.db` aside before the upgrade and reads it with
`sqlite3`, which is a file it now owns rather than anything this
server will look at again. The same goes for the old `vinga.db` and
for both files' `-wal` and `-shm` sidecars: nothing in this build
touches them, nothing removes them, and they sit on the data volume
until somebody archives or deletes them deliberately.

The full procedure, step by step, is in
[`../reference/cli.md`](../reference/cli.md).
