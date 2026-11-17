# Servers

The platform runs on more than one server. Each server is independent: its own deploy API, its own
registered owners, its own app names, its own shared services and backups. The rules your files
must follow ([the contract](contract.md)) are the same on every server; a few values and options
differ.

Every app calls the workflow at `@v1`; the input `platform` chooses the server.

## Which server

| Server | For | Your app's own hostname |
|--------|-----|-------------------------|
| `apps` (default) | internal tools and services of shirtracer | `<name>.apps.platform.shirtracer.gmbh` |
| `shops` | the shops | `<name>.apps.shops.shirtracer.gmbh` |

If you don't know which one, it is `apps`.

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
| Access from abroad | only Germany, Austria, Switzerland, Luxembourg and the Netherlands; elsewhere refused, except your `abroad_paths` ([Operations](operations.md#access-from-abroad)) | no geo-filter for now: open everywhere; `abroad_paths` is accepted and has no effect |
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
hostname.

## Moving an app to another server

1. Offboard it on its current server (**Actions → deploy → Run workflow**, action `offboard`)
   while `platform` still names that server.
2. Change `platform` to the new server and push: the first deploy there claims the name on the new
   server (your owner must be registered there).

The data doesn't move with it: export it before step 1 and import it on the new server. If you
change `platform` first, the app keeps running on the old server and your workflow can no longer
offboard it there: ask the admin to remove it.

## The first shops

The shops server is new: the first shop teams are its first users.

1. **Registration**: your GitHub owner must be registered on the shops server. The organization
   `shirtracer` is; for a personal account ask the platform admin ([Registration](registration.md)).
2. **Your repository**: from the [template](https://github.com/shirtracer/platform-app-template) as
   usual; in `.github/workflows/deploy.yml` call `…/app.yml@v1` with `platform: shops` (above).
3. **Limits**: none on the shops server; leave `deploy.resources.limits` out or set your own.
4. **Your domain**: `domain: www.your-shop.example` in `platform.yaml`. Point its DNS at the shops server
   (an A record for `5.9.113.248`, no AAAA), then add `certificate: true` for a certificate of its own;
   behind a CDN in "Full" mode the server's default certificate is enough.
5. **Problems**: something the platform refuses that it shouldn't, or a deploy that fails on the
   platform's side: tell the platform admin with the workflow run's link. Fixes come as patch
   releases; nothing in your repository has to change for them.

## The same name on two servers

Possible: each server decides about its own names. Avoid it anyway; an app's name together with
its server identifies it (in the docs, in Grafana, when you ask the admin).
