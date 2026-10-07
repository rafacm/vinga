# Upgrading a deployment

At the end of this guide you will have rolled a new image in the one
order that works, rerunning the provisioning file before the new image
boots, and you will be able to tell from outside which build each
deployment is running.

## Before rolling a new image

**Rerun the provisioning file when a release moves it, before starting
the new image.** The upgrade order is always the same: rerun the
updated [`deploy/postgres-init.sql`](../../deploy/postgres-init.sql),
then boot. Every statement in the file is written to be run again, so a
rerun over a database that already has everything is a no-op.

It runs the way it ran the first time, under
[Providing the database](database.md#the-configuration-database-in-a-deployment),
with the same service file and password file.

**Issue invite links again after the restart.** An invite link lives
in the running server's memory, so a restart, an upgrade included, ends
every one not yet opened; run `vinga device invite` for a fresh one.

## Which build is running

`version` is the package version and has read `0.1.0` since the package
skeleton. `revision` is which build of it, and it is the field that
distinguishes one deploy from another.

```console
$ curl -s localhost:8003/healthz
{"status":"ok","version":"0.1.0","revision":"a1b2c3d4e5f6"}
```

**A running pod's revision equals its image tag's suffix**: a container
from the image tagged `sha-9fd3de5e1c4b` reports `9fd3de5e1c4b`, so a
post-deploy check is an equality check. CI passes the same twelve
characters `docker/metadata-action` puts in the tag, computed from one
expression, so the two cannot drift. It used to pass the full 40-character SHA,
which made the match a prefix check; a deployment scripted it as
equality, which is the natural reading, and got a false failure.

It also rides every `session_open` event, which is the widest payoff for
one field: the JSON logs already ship to a collector, so every session is
attributable to a build rather than only the ones somebody thought to
investigate. Two field recordings that behaved differently are otherwise
indistinguishable from one code change and two different rooms. The OTA
reply carries it too, under `server`, which is the one place a device is
told what it is about to talk to.

The value is resolved once at startup, in this order:

1. `VINGA_REVISION`. The published image bakes in the commit its tags
   are computed from, so `/healthz` and the image's `sha-` tag agree.
2. `git describe --always --dirty`, which covers running from a working
   tree. A tree with uncommitted changes reports `-dirty`, because a
   build running code that is not any commit is exactly when knowing
   matters.
3. `unknown`. An image built with no build argument runs and says it does
   not know; it never fails to start over it.

Building an image yourself:

```console
docker build --build-arg VINGA_REVISION=$(git rev-parse --short HEAD) -t vinga-server .
```

## Past releases

What a particular release asked of an operator is in that release's
[changelog](../../CHANGELOG.md) entry, never here. Read the entries
between the build you run and the one you are moving to before you
roll. The releases that moved the provisioning file or forced a step:

- [2026-09-12](../../CHANGELOG.md#2026-09-12): `server.local_only`
  becomes `server.data_boundary`, and an entry's `egress` becomes
  `reach`.
- [2026-08-30](../../CHANGELOG.md#2026-08-30): memory moves into the
  database, in a `memory` schema, and gains scopes.
- [2026-08-28](../../CHANGELOG.md#2026-08-28): the conversation store's
  schema is renamed from `conversations` to `record`.
- [2026-08-11](../../CHANGELOG.md#2026-08-11): the configuration API's
  secret, then named `SAMTAL_API_SECRET`.
