# Servers

The platform runs on more than one server. Each server is independent: its own deploy API, its own
registered owners, its own app names, its own shared services and backups. The rules your files
must follow ([the contract](contract.md)) are the same on every server; a few values and options
differ.

Choosing a server needs **workflow v1.1.0 or later** (`@v1` once it is released). Until then every
app deploys to the apps server.

## Which server

| Server | For | Your app's own hostname |
|--------|-----|-------------------------|
| `apps` (default) | internal tools and services of shirtracer | `<name>.apps.platform.shirtracer.gmbh` |
| `shops` | the shops | `<name>.apps.<the shops server's domain>` (announced with the server) |

If you don't know which one, it is `apps`. The shops server is announced when it is available; a
deploy to it before that fails in the workflow's first step ("the server shops isn't available
yet").

## Choosing it

In your repository's `.github/workflows/deploy.yml`, under `with:`:

```yaml
    uses: shirtracer/platform-workflows/.github/workflows/app.yml@v1
    with:
      action: ${{ inputs.action || 'deploy' }}
      confirm: ${{ inputs.confirm || '' }}
      platform: shops # the server: apps (default) or shops
```

Without `platform` your app goes to `apps`, exactly as before. The value selects everything
together: the policy bundle your files are checked with, the server's deploy API, and the audience
of the identity token, so a token for one server is never accepted by another. Offboarding goes to
the same server.

The old input `controller-url` is deprecated: leave it out. If you set it, it must be the selected
server's deploy URL, otherwise the workflow fails.

## What differs

| | `apps` | `shops` |
|---|---|---|
| CPU and memory limits | required on every service; at most 4 CPUs and 8 GiB per service and per app (APP-C-LIMITS, APP-C-QUOTA-SVC, APP-C-QUOTA-APP) | optional, no maximum; limits you declare must still be valid |
| Other quotas (buckets, Postgres connections, lifecycle rules, RabbitMQ) | as in [Shared services](services.md#limits) | the same rules with the server's values |
| Access from abroad | only Germany, Austria, Switzerland and Luxembourg; elsewhere refused, except your `abroad_paths` ([Operations](operations.md#access-from-abroad)) | no geo-filter for now: open everywhere; `abroad_paths` is accepted and has no effect |
| Explicit domain (`domain:` other than your app name) | only a domain the admin has allowed for your app or your owner in the server's registry ([Registration](registration.md#changes-later)) | any free valid hostname that isn't a platform hostname |
| Certificate for the explicit domain | `certificate: true`, after the DNS check | the same |
| Owners and app names | registered on this server | registered on this server, separately |

**Explicit domains and certificates.** Your app's own hostname always works and always has a
certificate. An explicit domain (`domain: www.shop.example.com`) belongs to one app per server.
Without `certificate: true` it is served over HTTPS with the server's default certificate and
nothing is requested: fine behind a CDN in "Full" mode, a browser warning without one. With
`certificate: true` the deploy first checks the DNS: every A record must be the server's address
and there must be no AAAA record; otherwise the deploy is refused before anything changes
(`domain <host> resolves to …, expected …`). Then a certificate is requested for exactly that
hostname. `certificate` needs workflow v1.1.0 or later.

## Moving an app to another server

1. Offboard it on its current server (**Actions → deploy → Run workflow**, action `offboard`)
   while `platform` still names that server.
2. Change `platform` to the new server and push: the first deploy there claims the name on the new
   server (your owner must be registered there).

The data doesn't move with it: export it before step 1 and import it on the new server. If you
change `platform` first, the app keeps running on the old server and your workflow can no longer
offboard it there: ask the admin to remove it.

## The same name on two servers

Possible: each server decides about its own names. Avoid it anyway; an app's name together with
its server identifies it (in the docs, in Grafana, when you ask the admin).
