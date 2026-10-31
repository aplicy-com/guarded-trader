#!/usr/bin/env bash
# Test an NDAX API key from THIS host (the VPS), read-only. Spike only (spike/ndax). Run it on
# the VPS, from /opt/ai-trading-agent.
#
#   scripts/ndax-access-check.sh --scope read-only   read-only key: can read, can do nothing else
#
# What it does: starts a throw-away Freqtrade container (the same image the bot uses) that gets
# NDAX_API_KEY / NDAX_API_SECRET / NDAX_UID from .env, and runs scripts/ndax_access_probe.py in
# it. ccxt gets DUMMY login/password values; the probe reports whether ccxt's private calls work
# with them. Every call is a read or a fee quote: no order, no deposit or withdraw ticket. The
# key never appears in this shell or in the output, and the real NDAX password is never used.
#
# Exit 0 = PASS. Also prints this host's outbound IP, for comparison with any IP restriction.
set -uo pipefail

SCOPE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --scope) shift; SCOPE=${1:-} ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
case "$SCOPE" in read-only) ;; *) echo "ERROR: --scope read-only is required" >&2; exit 2 ;; esac

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
cd "$ROOT" || exit 2
[ -f .env ] || { echo "ERROR: .env not found in $ROOT (run from the app directory)" >&2; exit 2; }
command -v docker >/dev/null || { echo "ERROR: docker not found (run this on the VPS)" >&2; exit 2; }
# The account password must never be in .env, even for this test.
if grep -Eq '^NDAX_(LOGIN|PASSWORD|USERNAME|EMAIL|TWOFA|2FA)[A-Z_]*=.+' .env; then
  echo "ERROR: .env holds an NDAX login/password/2FA value. Remove it: it is never needed" >&2
  exit 2
fi
# The key must be set, but is never read into this shell: compose interpolates it.
for v in NDAX_API_KEY NDAX_API_SECRET NDAX_UID; do
  grep -q "^$v=.\+" .env || { echo "ERROR: $v is not set in .env" >&2; exit 2; }
done

IP=$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || echo unknown)
echo "outbound IP of this host: $IP"

COMPOSE=(docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.ndax-check.yml)
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint python freqtrade - --scope "$SCOPE" < "$HERE/ndax_access_probe.py"
