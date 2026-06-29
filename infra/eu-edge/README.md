# EU Edge

This directory contains the public edge configuration for the Hetzner EU VPS serving the `shchukin.de` domains.

Tracked edge config:

- [Caddyfile](/srv/human-engine/infra/eu-edge/Caddyfile)
- [deploy.sh](/srv/human-engine/infra/eu-edge/deploy.sh)

Current routing model:

- `shchukin.de` is the main web domain for user/admin web surfaces.
- `shchukin.de/dashboard` is the current internal dashboard path.
- `api.shchukin.de` remains the technical API domain.
- both public surfaces proxy to the local backend upstream at `127.0.0.1:8000`

Current public split:

- `shchukin.de/dashboard` -> FastAPI SSR internal dashboard
- `api.shchukin.de` -> FastAPI technical API endpoints, Strava OAuth callback, Telegram webhook, HealthKit sync, `/healthz`, and API docs when enabled

Operational notes:

- Caddy owns TLS termination and reverse proxying on the edge host.
- The dashboard is rendered by FastAPI via Jinja2 templates; Caddy only routes the request.
- The dashboard is currently unauthenticated. This must not be treated as production-secure.
- The immediate planned protection step is `Caddy` Basic Auth for `/dashboard`.
- A later option is Google OAuth restricted to a single allowed user email.

Manual deploy on the edge host:

```bash
sudo cp infra/eu-edge/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl -fsSL https://api.shchukin.de/healthz
```

Deploy script behavior:

- installs the tracked `Caddyfile`
- validates the config before reload
- reloads `caddy`
- checks `https://api.shchukin.de/healthz`

Notes:

- This repo does not store real passwords, tokens, or edge credentials.
- This repo change does not modify `/etc/caddy/Caddyfile` automatically unless the deploy procedure is run on the host.
