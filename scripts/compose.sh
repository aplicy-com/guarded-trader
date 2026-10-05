#!/usr/bin/env bash
# `docker compose` for THIS server's current mode. Run on the VPS from /opt/ai-trading-agent.
#
#   scripts/compose.sh up -d --build        same arguments as docker compose
#
# The mode is the one word in .trading-mode (dry-run | live | live-pending; no file = dry-run),
# written only by scripts/trading-mode.sh. In live and live-pending the live override is added,
# so a plain `up -d` can never silently swap a live stack for the dry-run one. (It would fail
# safe either way: the dry-run stack cannot place real orders.)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
MODE=dry-run
[ -f .trading-mode ] && MODE=$(tr -d '[:space:]' < .trading-mode)
FILES=(-f infra/docker-compose.yml)
case "$MODE" in
  dry-run) ;;
  live|live-pending) FILES+=(-f infra/docker-compose.live.yml) ;;
  *) echo "ERROR: .trading-mode says '$MODE' (expected dry-run, live or live-pending)" >&2; exit 2 ;;
esac
exec docker compose --env-file .env "${FILES[@]}" "$@"
