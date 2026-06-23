# EU Edge

This directory contains minimal public edge configuration for the EU VPS / edge node serving `shchukin.de`.

Current tracked config:

- [Caddyfile](/srv/human-engine/infra/eu-edge/Caddyfile)

Current minimal Caddy config:

```caddy
api.shchukin.de {
    respond "Human Engine Edge Server" 200
}
```

Manual install on the edge host:

```bash
sudo cp infra/eu-edge/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl https://api.shchukin.de
```

Notes:

- This repo change does not modify `/etc/caddy/Caddyfile` automatically.
- This is intentionally a minimal placeholder until the real reverse-proxy upstream is confirmed on the edge host.
