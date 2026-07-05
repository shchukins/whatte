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
- The dashboard is protected with `Caddy` Basic Auth on `/dashboard`.
- A later option is Google OAuth restricted to a single allowed user email.
- The backend production runtime is on the VPS; `api.shchukin.de` remains the API surface and `shchukin.de/dashboard` is the internal monitoring surface.
- Old home-server watchdog / cron monitoring is legacy and should not be treated as primary production monitoring after the VPS move.

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
