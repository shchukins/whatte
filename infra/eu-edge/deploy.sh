#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CADDY_SOURCE="${SCRIPT_DIR}/Caddyfile"
CADDY_TARGET="/etc/caddy/Caddyfile"

echo "[1/4] Checking source config..."
test -f "${CADDY_SOURCE}"

echo "[2/4] Installing Caddy configuration..."
sudo cp "${CADDY_SOURCE}" "${CADDY_TARGET}"

echo "[3/4] Validating Caddy configuration..."
sudo caddy validate --config "${CADDY_TARGET}"

echo "[4/4] Reloading Caddy..."
sudo systemctl reload caddy

echo
echo "[OK] EU Edge deployed"
curl -fsSL https://api.shchukin.de/healthz || true
echo
