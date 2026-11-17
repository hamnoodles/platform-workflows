# Shared services

The platform runs one Postgres, one Redis, one S3 store (Silo) and one RabbitMQ broker for all apps. Declare what
your app uses in `platform.yaml` → `services`, put the services that use them on the `storage`
network, and read the credentials from files ([Secrets](secrets.md)). Removing a service from
`platform.yaml` revokes access and keeps the data.

## Connection settings

Fixed values, fine as environment variables:

| Service | Settings | Credential files |
|---------|----------|------------------|
| Postgres | host `storage-postgres`, port `5432`, database and user = app name | `POSTGRES_PASSWORD`, `DATABASE_URL` |
| Redis | host `storage-redis`, port `6379`, user = app name | `REDIS_PASSWORD`, `REDIS_URL` |
| Silo (S3) | endpoint `http://storage-silo:9000`, region `us-east-1`, path-style addressing, bucket = app name | `S3_ACCESS_KEY`, `S3_SECRET_KEY` |
| RabbitMQ | host `storage-rabbitmq`, port `5672` (AMQP 0-9-1 and 1.0, no TLS on the internal network), vhost = app name, user `app-<name>` | `RABBITMQ_PASSWORD`, `RABBITMQ_URL` (`amqp://app-<name>:…@storage-rabbitmq:5672/<name>`) |

## Postgres

```yaml
services:
  postgres:
    extensions: [pg_trgm, citext]
```

| Your app can | Your app cannot |
|--------------|-----------------|
| own its database `<name>`: create, alter and drop tables, schemas, indexes, views; run migrations | touch other databases; act as superuser; create databases or roles |
| use the extensions it lists | install extensions not on the list |

Allowed extensions: `btree_gin`, `btree_gist`, `citext`, `cube`, `earthdistance`,
`fuzzystrmatch`, `hstore`, `intarray`, `isn`, `lo`, `ltree`, `pg_trgm`, `pgcrypto`, `seg`,
`tablefunc`, `unaccent`, `uuid-ossp`. The platform creates them in your database at the deploy;
removing one from `platform.yaml` never drops it. Need another one? Ask the admin
([Registration](registration.md)).

At most **50 connections** per app; size your connection pools across all replicas below that.
Your database is backed up by the platform (daily, with point-in-time recovery); a restore is
done by the admin on request.

### Looking into your database (pgAdmin)

Your team can open your app's database in the browser at
[pgadmin.platform.shirtracer.gmbh](https://pgadmin.platform.shirtracer.gmbh), with your normal
platform login (Authentik, with its second factor). Nobody gets a database password, and your
app's credentials are never shown there.

- **Who**: the app's managers (`access.managers` in `platform.yaml`) and the members of the
  Authentik group `<name>-db`. The platform creates that group for every app with Postgres; your
  managers add and remove people in it themselves (Authentik → Directory → Groups → `<name>-db`),
  like your app's other groups. Being in your app's access groups alone does not give database
  access. An app with `auth: none` has no managers on the platform: ask the platform admin to add
  or remove people in `<name>-db`.
- **What you see**: after login, the group `<name>` with one entry `<name>`; connect without a
  password. You see no other app's database and can't connect to one, even with a server you add
  yourself.
- **What you can do**: everything your app can, on your app's database only: read and change
  data, create and alter tables, run SQL. **This is production data**: there is no undo apart
  from a restore by the admin. Tables you create belong to your app, so your app can use them.
- **Limits**: at most 5 connections for your whole team, a statement is cancelled after 5
  minutes, and a transaction left open is ended after 10 minutes (so a forgotten pgAdmin tab
  never blocks your app for long). These limits count separately from your app's 50 connections.
- **Logging out and leaving**: sessions end after 8 hours. Someone removed from `<name>-db` can't
  open a new connection from then on; the admin can also switch your team's database access off
  and on again at once.
- **From abroad**: like everything on the platform, pgAdmin answers only in the allowed countries
  (Germany, Austria, Switzerland, Luxembourg, the Netherlands; [Operations](operations.md#access-from-abroad)).

pgAdmin keeps no data of its own besides your preferences; downloads and uploads in its file
manager are gone after a restart.

## Redis

```yaml
services:
  redis: true
```

| Your app can | Your app cannot |
|--------------|-----------------|
| any keys and pub/sub channels under `<name>:` | other prefixes |
| normal data commands | admin and dangerous commands (`KEYS`, `FLUSHALL`, `FLUSHDB`, `CONFIG`, …); use `SCAN` instead of `KEYS` |

Redis is a **cache**: it survives restarts but isn't backed up. Keep anything you can't
rebuild in Postgres or Silo.

## Silo

```yaml
services:
  s3: true
```

| Your app can | Your app cannot |
|--------------|-----------------|
| read and write objects in the bucket `<name>` | other apps' buckets |
| create and delete buckets `<name>-*` (e.g. `shop-uploads`) | buckets without its prefix; users and policies |

Keep to at most **20 buckets** `<name>-*`: Silo can't enforce a count, so the platform reports
more and the admin follows up. Buckets are copied offsite with the platform's backups.

### Letting objects expire (lifecycle rules)

Needs policy bundle **2.3.0** (platform release 1.2.0). Objects in a bucket can expire: declare
the rules under `s3` instead of `s3: true`:

```yaml
services:
  s3:
    lifecycle:
      - bucket: shop            # <name> or <name>-<suffix>
        prefix: exports/        # optional: only objects whose name starts with it
        expire_days: 30
      - bucket: shop-tmp        # no prefix: every object in the bucket
        expire_days: 1
```

- **Fields**: `bucket` is your app's bucket `<name>` or `<name>-<suffix>` (lower-case letters,
  digits and single hyphens; no dots); `prefix` is a plain object name prefix (no leading `/`, no
  `*`, `?` or `[`, no `..`); `expire_days` is a whole number from 1 to 3650. At most **10 rules**
  per app; two rules with the same bucket and prefix are refused. The policy checks all of it in
  CI and again on the server.
- **What expires**: an object whose last write (upload or overwrite, not a read) is older than
  `expire_days`. The storage server removes it in its background lifecycle pass, so expect it
  within about a day after the period, not to the minute.
- **Not reversible on the server**: an expired object is gone there. The offsite copy keeps what
  it has already pulled (it never mirrors deletions) until its own snapshot retention drops it,
  so the platform admin can recover an object for a while. Lifecycle rules are no way to delete
  data everywhere.
- **The manifest is the whole truth**: each deploy sets exactly the declared rules on every
  bucket of your app and removes any other rule. A rule removed from the manifest is gone after the
  next deploy; objects that would have expired stay. A declared bucket that doesn't exist yet is
  created by the deploy.
- **Overlapping prefixes** in one bucket (`tmp/` 1 day, `tmp/large/` 7 days) both apply: an object
  matching both expires at the shorter period.
- **Lowering a period** (30 → 7 days) removes every object older than the new period under that
  prefix at the next pass, all at once.
- **Removing `s3`** (or offboarding) leaves the rules in place, like the data. `platform app
  purge` removes the buckets with their rules.
- **Incomplete multipart uploads** are removed by the storage server after 24 hours, in every
  bucket, without a rule; an upload that takes longer than that is aborted.

## RabbitMQ

Needs policy bundle **2.3.0** (platform release 1.2.0).

```yaml
services:
  rabbitmq: true
  # or, with your own limits (each optional; the defaults below otherwise):
  # rabbitmq:
  #   limits: {connections: 50, queues: 50, queue_bytes: 67108864}
```

| Your app can | Your app cannot |
|--------------|-----------------|
| declare, use and delete exchanges, queues and bindings in its vhost `<name>`; publish and consume | open another app's vhost or `/`; manage users, vhosts, limits or policies |
| classic and quorum queues | streams (refused node-wide); transient non-exclusive queues (refused by RabbitMQ 4) |

Read `RABBITMQ_URL` (or build the URL from the settings and `RABBITMQ_PASSWORD`) when you connect,
and reconnect with retries: the broker restarts at upgrades.

**Durability.** Messages in a **durable** queue that were published as **persistent** survive a
restart of the broker. Use **quorum queues** (`x-queue-type: quorum`) for anything that matters, and
publisher confirms to know a message arrived. Messages are **not backed up**: if the broker's
volume is lost, the queues come back empty (your vhost, user and limits are rebuilt by the
platform). RabbitMQ is transport, not storage: anything you can't lose belongs in Postgres or Silo
until it has been processed.

**Limits.** One broker serves every app, so each vhost has limits that keep one app's backlog from
blocking the others:

| Limit | Default | Maximum | At the limit |
|-------|---------|---------|--------------|
| `connections` | 50 | 200 | a new connection is refused (`530 NOT_ALLOWED … connection limit`) |
| `queues` | 50 | 200 | declaring another queue fails (`406 PRECONDITION_FAILED … queue limit`) |
| `queue_bytes` (each queue) | 64 MiB | 1 GiB | publishes to that queue are **refused** (with publisher confirms: a nack); nothing already queued is dropped |

`queues × queue_bytes` may be at most **8 GiB** (e.g. 200 queues of 40 MiB, or 8 queues of 1 GiB);
the policy checks all of it in CI and again on the server. Lowering a limit below what you use
deletes nothing: existing connections and queues stay; new ones (or publishes) are refused until
you are back under it. A queue argument like `x-max-length-bytes` can only lower your cap, not
raise it. Errors to expect in your logs: `541 … feature flag is disabled` when declaring a stream,
`541 … transient_nonexcl_queues is deprecated` for a non-durable, non-exclusive queue.

**Removing `rabbitmq`** (or offboarding) deletes your user, which closes your connections; the vhost
with its queues and messages stays. Adding the service again gives your app a new password for the
same vhost. `platform app purge` deletes the vhost.

### Looking into your queues (RabbitMQ UI)

`https://rabbitmq.platform.shirtracer.gmbh`, logged in with your platform account. Your app's
managers and the members of its group `<name>-mq` (created at the first deploy with the broker;
the managers add people in Authentik like for `<name>-users`) see your vhost only: queues with
their message and consumer counts, exchanges and bindings. You can look at messages, publish test
messages, purge and delete queues. You don't see your app's connections (the broker shows them only
to the platform admin, who can close one for you), users, limits or other apps. A person removed
from the group loses access within minutes. Purging deletes messages for good.

## Limits

| Limit | Value |
|-------|-------|
| CPU and memory per service | 4 CPUs, 8 GiB (policy 2.2.0; 2 CPUs, 2 GiB before) |
| CPU and memory per app (limits × replicas) | 4 CPUs, 8 GiB |
| Postgres connections per app | 50 |
| Buckets per app | 20 |
| RabbitMQ per app | 50 connections, 50 queues, 64 MiB per queue by default; up to 200, 200, 1 GiB and 8 GiB in all ([RabbitMQ](#rabbitmq)) |

The first two are checked before the deploy ([APP-C-QUOTA-SVC, APP-C-QUOTA-APP](contract.md#images-and-resources)).

## Stateless apps

Containers have no volumes and are replaced at every deploy. State lives in Postgres or Silo
(Redis is a cache, RabbitMQ is transport);
temporary files go into a `tmpfs` mount:

```yaml
    tmpfs:
      - /tmp
```
