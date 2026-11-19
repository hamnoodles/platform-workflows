# Operations

## Deploys

A push to the default branch (`main` in the template) deploys; pull requests and other
branches only validate and build. The workflow
validates the contract, builds and pushes `ghcr.io/<owner>/<repo>:sha-<commit>` and sends the
deploy request; its summary shows the result and, on a refusal, why.

- **A short gap:** a deploy replaces your containers. Expect a few seconds without an answer:
  the route returns 404 until the new container's first health check passes. An app that starts
  fast keeps the gap short.
- **Waiting for health:** the platform waits up to 5 minutes for every routed service to become
  healthy.
- **Same commit again:** changes nothing. After changing a secret, push a new commit
  ([Secrets](secrets.md#changing-a-secret)).

## Build cache and cancelled runs

From workflow v1.3.0; nothing to set up.

- **The cache:** each build keeps a cache of its image layers in your package, as the tag
  `buildcache` (`ghcr.io/<owner>/<repo>:buildcache`), next to the `sha-<commit>` images. A change
  that only touches your code reuses the unchanged layers (base image, dependencies) and builds
  much faster. Every build on the default branch overwrites the cache; pull requests read it but
  never write it, and nothing from a pull request reaches it. The tag is never deployed.
- **No cache:** a first build, or a build that can't read the cache, simply runs without it. To
  force a build without cache, delete the `buildcache` version in the package settings (your
  repository → Packages → the package → Package settings → manage versions); the next push to the
  default branch builds from scratch and writes a new one.
- **Cancelled runs:** a newer push to the same branch, or a new commit on the same pull request,
  cancels the older run while it still validates or builds; it shows as *cancelled*. A deploy that
  has started always finishes; a newer deploy waits for it, and of several waiting deploys only
  the newest is sent. An offboard is never cancelled by a push.
- **Checks:** the run's jobs are `platform / validate and build` and, on the default branch,
  `platform / deploy`. If a branch rule of yours requires checks of the platform workflow, require
  `platform / validate and build`.

## Rollback

If the routed services don't become healthy, the platform puts the last healthy version back and
reports `failed` with the reason. Storage changes of the failed version stay (they only add
access). The first deploy has nothing to roll back to.

To keep a failing version running for debugging instead:

```yaml
deploy:
  rollback: false
```

To go back to an older version on purpose, revert the commit on `main` and push.

## Logs

Everything your services write to stdout and stderr is collected. Grafana
(`https://grafana.platform.shirtracer.gmbh`, platform login) → Explore → Loki:

```
{stack="<name>"}
{stack="<name>", service="<name>-web"} |= "error"
```

Grafana access needs membership in `grafana-viewers` ([Registration](registration.md)). App
teams never get access to the server.

## Metrics

Container metrics (CPU, memory, restarts) are collected for every app. For your own metrics,
label the service and keep it on the `apps` network:

```yaml
    labels:
      platform.metrics.port: "8000"
      platform.metrics.path: /metrics   # only if not /metrics
    networks: [proxy, apps]
```

The platform scrapes it every 30 s in Prometheus format; the series appear in Grafana with the
labels `stack` (your app), `service` and `container`.

## Calls between apps

Apps reach each other over the `apps` network by aliases, never by container names:

```yaml
services:
  shop-api:
    networks:
      apps:
        aliases: [shop-api]
```

Another app calls `http://shop-api:<port>/…`. Aliases are named `<name>-<suffix>`
([APP-C-ALIAS](contract.md#networks-and-names)).

**Calls over `apps` don't pass the platform login.** A request arriving over `apps` carries
whatever `X-authentik-*` headers the calling app put there, so never treat them as proof of a
user on a service other apps can reach. If such a service must know who calls it, authenticate
the caller yourself, e.g. a shared token stored as a secret in both apps:

```python
token = open("/run/secrets/SHOP_API_TOKEN").read()
if not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {token}"):
    abort(401)
```

## Starting and restarting

Trusted members of your team can get the Arcane Operator role (see status, start and restart
your app) through the `arcane-operators` group; ask the admin ([Registration](registration.md)).

## Template updates

Your repository is a copy of the template; it isn't updated by itself. When the template
changes (the workflow's release notes say so), compare and take over what applies:

- `.platform/platform.schema.json`: replace it with the template's copy (never edit it).
- `.github/workflows/deploy.yml`: keep `@v1`; take over changed inputs or permissions.
- `deploy/compose.yaml`, `Dockerfile`: only if you want the example's changes.

Patch and minor releases of the workflow reach you through `@v1` without any change. Pin
`@v1.x.y` only if you need an exact version, and move it yourself.

## Explicit domains

Your app's own hostname `<name>.apps.<server domain>` always works. For another hostname set
`domain:` in `platform.yaml`; where it is allowed and when it gets a certificate depends on the
server and on `certificate: true` ([Servers](servers.md#what-differs)). With `certificate: true`,
point the domain's DNS at the server first (A record only, no AAAA): the deploy checks it and is
refused before any change otherwise. Without it the domain is served with the server's default
certificate (behind a CDN in "Full" mode). Changing or removing `domain` takes effect with the
deploy; the old hostname stops answering.

## Access from abroad

This section applies to servers with the geo-filter (`apps`); see [Servers](servers.md#what-differs).
The platform answers only requests from addresses in Germany, Austria, Switzerland, Luxembourg
and the Netherlands (the allowed countries; Austria, Switzerland and Luxembourg since platform
release 1.2.1, the Netherlands since 2.0.0). Anyone else gets `403` with a short page (it still says "Zugriff nur aus Deutschland. /
Access is only possible from Germany."), for every app, the login and Grafana. Deploys are not
affected (GitHub's runners reach the platform), and neither are certificates.

A foreign service that calls your app (a payment provider's webhook, GitHub, a mail service) needs
its path opened in `platform.yaml`:

```yaml
abroad_paths: [/webhooks/stripe]
```

- Each path opens itself and everything below it (`/webhooks/stripe/events` too, not
  `/webhooks/stripex`); at most 10; never `/`: an app can't be opened entirely.
- Only for paths your app serves **without** the platform login (`auth: forward` sends visitors
  to the login, which stays closed abroad). Check the caller yourself, e.g. the webhook's
  signature.
- The change takes effect within a minute of the deploy; removing a path closes it again.
- Available with policy bundle 2.2.0 (platform release 1.1.0); older bundles refuse the field.

A user in an allowed country who gets the 403 page: their provider's addresses may be listed in
another country. Ask the platform admin with the user's public address and the time.

Country data: [IP Geolocation by DB-IP](https://db-ip.com), CC BY 4.0.

## Offboarding

Removing the app is never triggered by a push. In GitHub: **Actions → deploy → Run workflow**,
action `offboard`, and type the app name as confirmation. The platform then keeps a final
database backup, keeps the buckets until the offsite copy has them, and removes the app, its
route, credentials and access to the shared services. The name stays bound to your repository
until the admin purges the kept data ([Registration](registration.md#retiring-an-app)).

The offboard request goes to the server your workflow names (`platform`, default `apps`). To move
an app to another server, offboard it first, then change `platform`
([Servers](servers.md#moving-an-app-to-another-server)).
