#!/usr/bin/env bash
# Test the Kraken API key from THIS host (the VPS), read-only. Run it on the VPS, from
# /opt/ai-trading-agent.
#
#   scripts/kraken-access-check.sh --scope query-only   first key: can read, can do nothing else
#   scripts/kraken-access-check.sh --scope trade        real key: can read + create/cancel
#                                                       orders; NO deposit/withdraw/funding
#
# What it does: starts a throw-away Freqtrade container (the same image the bot uses) that gets
# the key from .env, and runs scripts/kraken_access_probe.py in it. Calls Balance and OpenOrders,
# a VALIDATE-ONLY AddOrder (Kraken discards it), and read-only deposit/withdraw lookups that fail
# with "permission denied" for a correctly scoped key. It never places an order, never starts the
# bot, and the key never appears in this shell or in the output.
#
# Exit 0 = PASS. Also prints this host's outbound IP: it must be the IP the key is whitelisted to.
set -uo pipefail

SCOPE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --scope) shift; SCOPE=${1:-} ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
case "$SCOPE" in query-only|trade) ;; *) echo "ERROR: --scope query-only|trade is required" >&2; exit 2 ;; esac

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
cd "$ROOT" || exit 2
[ -f .env ] || { echo "ERROR: .env not found in $ROOT (run from the app directory)" >&2; exit 2; }
command -v docker >/dev/null || { echo "ERROR: docker not found (run this on the VPS)" >&2; exit 2; }
# The key must be set, but is never read into this shell: compose interpolates it.
grep -q '^KRAKEN_API_KEY=.\+' .env && grep -q '^KRAKEN_API_SECRET=.\+' .env \
  || { echo "ERROR: KRAKEN_API_KEY / KRAKEN_API_SECRET are not set in .env" >&2; exit 2; }

# The VPS's static IPv4 the key is whitelisted to: from the environment, else from .env.
EXPECTED_IP=${KRAKEN_EXPECTED_IP:-$(sed -n 's/^KRAKEN_EXPECTED_IP=//p' .env | tail -1)}
[ -n "$EXPECTED_IP" ] || { echo "ERROR: KRAKEN_EXPECTED_IP is not set in .env (the VPS's static IPv4: terraform output ipv4)" >&2; exit 2; }

IP=$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || echo unknown)
echo "outbound IP of this host: $IP (key must be whitelisted to $EXPECTED_IP)"
if [ "$IP" != "$EXPECTED_IP" ]; then
  echo "WARNING: outbound IP differs from $EXPECTED_IP; an IP-restricted key will be refused" >&2
fi

COMPOSE=(docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.kraken-check.yml)
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint python freqtrade - --scope "$SCOPE" < "$HERE/kraken_access_probe.py"
