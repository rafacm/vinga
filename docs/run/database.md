# Providing the database

At the end of this guide you will have a Postgres database the server
can reach and migrate, provisioned with the three schemas it owns and
the read-only role an analyst uses, and a way to read what was said
without the server's credentials.

## The configuration database in a deployment

Three things a deployment has to get right about it, none of which the
server can decide for you. The rest of what a deployment decides about
its database has a guide of its own: the master key in
[Securing a deployment](security.md#the-master-key), dumps and
restores in [Backing up and restoring the database](backups.md), and
the rerun before a new image boots in
[Upgrading a deployment](upgrading.md).

**The database is yours to provide, and five variables name it.**
`VINGA_DB_HOST`, `VINGA_DB_PORT`, `VINGA_DB_NAME` and `VINGA_DB_USER`
go wherever the deployment keeps its environment, and
`VINGA_DB_PASSWORD` goes wherever it keeps its secrets, beside
`VINGA_AUTH_SECRET`, `VINGA_API_SECRET` and `VINGA_MASTER_KEY`, since
that is what it is. `VINGA_DB_URL` replaces all five when a
deployment's convention is one connection string, and is a secret for
the same reason: a URL carries a password in its authority and can
carry another in its query. **The shipped default password is `vinga`,
which is a development convenience on an instance bound to loopback
and never anything else**; set a real one before anything reachable
runs on it.

Every key of that family, with its environment spelling and its
default, is in the reference under
[`server.database`](../reference/server-config.md#serverdatabase).

**What the server role needs is ordinary DML and nothing exotic.** No
`CREATEDB`: the server migrates schemas, never databases, so the
database exists before it starts. Run
[`deploy/postgres-init.sql`](../../deploy/postgres-init.sql) against it
once, which creates the `domain`, `record` and `memory` schemas
`WITH AUTHORIZATION` to the server role and provisions the read-only
`vinga_ro` role beside them:

```bash
PGSERVICE=vinga-admin psql -f deploy/postgres-init.sql
```

The connection and its password come from a libpq service file and a
password file rather than from the command line, where the process
table and the shell's history would keep them. `~/.pg_service.conf`
names the instance and the role allowed to provision it:

```ini
[vinga-admin]
host=db.internal
port=5432
dbname=vinga
user=postgres
```

and `~/.pgpass`, readable by you alone (`chmod 0600`), holds that
role's password on one line of the form `host:port:*:user:password`.
The `*` matches any database name, which the role needs because
`dropdb` and `createdb` connect to a maintenance database (`postgres`)
rather than to the one they act on. The same two files serve every
`psql`, `pg_dump`, `pg_restore`, `dropdb` and `createdb` an
administrator runs against this instance.

A second service, `[vinga]`, with the same `host`, `port` and `dbname`
and `user` set to the server role (the `VINGA_DB_USER` value), is for
the rare statement that has to run as the role that owns the schemas,
such as the configuration-only reset in
[Recovering a deployment that will not start](recovering-a-deployment.md);
its password goes in `~/.pgpass` beside the first.

The executor needs to be able to create roles and to create schemas in
that database (a superuser, or the database's owner with `CREATEROLE`);
the server role needs neither, because it is given schemas it already
owns. Provisioning them any other way works as long as the server role
owns them: `CREATE` on the database does not grant it `CREATE` inside a
schema somebody else owns, which is where Alembic would then fail to
make its tables. Grant the server role `CREATE` on the database
instead, and it creates the schemas itself at first boot. Either
way, **rerun that file after any database reset**: a `dropdb`/`createdb`
takes the schemas and the database-local default privileges with it,
while the instance-level `vinga_ro` role survives, which is why every
statement in the file is written to be run again.

## Reading what was said

**Reading what was said is a `vinga_ro` session, never the server's.**
The instance has no reason to be reachable from anywhere but the
server, so the way in is a port forward for the length of a session,
or a one-shot `psql` beside the database on its own host:

```bash
psql "postgresql://vinga_ro@127.0.0.1:5432/vinga" \
  -c 'select * from record.turns order by id desc limit 20'
```

Always that role, and not the one the server connects as. `vinga_ro`
can read the conversation record and nothing else: the `domain` schema
holds the stored secrets' ciphertexts, and it is not granted there. It
also carries the timeouts that stop a forgotten session from holding a
lock the next boot's migration needs. Give it a real password
(`VINGA_DB_RO_PASSWORD` when the provisioning file is run) for the
same reason the server role gets one; the compose default of
`vinga_ro` is a loopback convenience.
