#!/usr/bin/env bash
# Run the web app locally and expose it on the internet via Cloudflare Tunnel.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${PORT:-8080}"
URL="http://127.0.0.1:${PORT}"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Install cloudflared first:"
  echo "  brew install cloudflared"
  exit 1
fi

if ! curl -sf "${URL}/api/health" >/dev/null 2>&1; then
  echo "Starting app on ${URL} ..."
  if [[ -f "$ROOT/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$ROOT/.venv/bin/activate"
  fi
  python -m src.cli serve --no-reload &
  APP_PID=$!
  trap 'kill "$APP_PID" 2>/dev/null || true' EXIT
  for _ in $(seq 1 30); do
    if curl -sf "${URL}/api/health" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if ! curl -sf "${URL}/api/health" >/dev/null 2>&1; then
    echo "App did not start. Is Ollama running? Run: ollama pull llama3.2"
    exit 1
  fi
else
  echo "App already running at ${URL}"
fi

echo ""
echo "Opening Cloudflare Tunnel → ${URL}"
echo "Copy the https://....trycloudflare.com URL below to share the app."
echo "Keep this terminal open while the tunnel is active."
echo ""

exec cloudflared tunnel --url "$URL"
