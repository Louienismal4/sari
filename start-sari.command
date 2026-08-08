#!/bin/bash

set -euo pipefail

cd -- "$(dirname -- "$0")"

show_startup_error() {
  local exit_code=$?
  trap - ERR
  echo
  echo "Sari could not start. Review the error above, then run:"
  echo "  docker compose ps"
  echo "  docker compose logs --tail=100 backend ocr-gateway cloudflared"
  echo
  read -r -p "Press Enter to close..."
  exit "$exit_code"
}

trap show_startup_error ERR

if [[ ! -f .env ]]; then
  echo "Cannot start Sari: the project-root .env file is missing."
  echo "Create it from .env.example, then add DATABASE_URL and OCR_SERVICE_TOKEN."
  read -r -p "Press Enter to close..."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Cannot start Sari: Docker is not installed or is not available in PATH."
  read -r -p "Press Enter to close..."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Cannot start Sari: Docker Desktop is not running."
  echo "Open Docker Desktop, wait until it is ready, then double-click this file again."
  read -r -p "Press Enter to close..."
  exit 1
fi

compose_args=(up -d --build --wait)
tunnel_enabled=false
tunnel_token="$(awk -F= '$1 ~ /^[[:space:]]*CLOUDFLARE_TUNNEL_TOKEN$/ { print substr($0, index($0, "=") + 1) }' .env | tail -n 1)"
tunnel_token="${tunnel_token%$'\r'}"
tunnel_token="${tunnel_token#\"}"
tunnel_token="${tunnel_token%\"}"
tunnel_token="${tunnel_token#\'}"
tunnel_token="${tunnel_token%\'}"

if [[ -n "$tunnel_token" ]]; then
  if [[ "$tunnel_token" != eyJ* || ${#tunnel_token} -lt 100 ]]; then
    echo "Cannot start the Cloudflare tunnel: CLOUDFLARE_TUNNEL_TOKEN is a placeholder or invalid."
    echo "In Cloudflare, open Networking > Tunnels, select the tunnel, choose Add a replica,"
    echo "then copy only the long eyJ... token into the project-root .env file."
    read -r -p "Press Enter to close..."
    exit 1
  fi
  compose_args=(--profile tunnel "${compose_args[@]}")
  tunnel_enabled=true
fi

echo "Building and starting the Sari backend and OCR service..."
docker compose "${compose_args[@]}"

echo
echo "Sari is ready."
echo "Backend: http://127.0.0.1:8000"
echo "API docs: http://127.0.0.1:8000/docs"
echo "OCR gateway: http://127.0.0.1:8090"
if [[ "$tunnel_enabled" == true ]]; then
  echo "Public API: https://api.louienismal.com"
else
  echo "Cloudflare tunnel: skipped (add a rotated CLOUDFLARE_TUNNEL_TOKEN to .env)"
fi
echo
read -r -p "Press Enter to close this window..."
