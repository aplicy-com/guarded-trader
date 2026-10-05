#!/usr/bin/env bash
# Switch this server between the dry-run stack and the LIVE pilot stack (ADR-0019).
# Run it ON THE VPS, from /opt/ai-trading-agent. The full procedure is
# docs/06-runbooks/go-live-pilot.md.
#
#   scripts/trading-mode.sh status
#   scripts/trading-mode.sh live         dry-run -> live. Refuses unless EVERY gate passes
#   scripts/trading-mode.sh dry-run      live -> dry-run. Refuses while a real position/order is open
#   scripts/trading-mode.sh cli ARGS...  run `conductor.cli ARGS` against the LIVE ledger
#                                        (e.g. exclude-balance, isolation-check, capital)
#
# `live` gates, in order (nothing is stopped or changed until the first four pass):
#   1. SOAK     72 h since infra/live/soak-start with no system-raised halt, none active
#   2. KEY      Kraken key verified from this host: read + create/cancel orders, NO funding/withdraw
#   3. LEDGER   the live ledger is fresh (volume absent or empty, or principal exactly 20 USD);
#               the dry-run ledger is never carried over
#   4. ARCHIVE  the dry-run ledger and Freqtrade DB are archived to archive/ and verified
#   then the dry-run stack stops, Freqtrade starts in LIVE config PAUSED, and:
#   5. MODE     Freqtrade reports dry_run=false and state paused
#   6. R5       isolation-check against the REAL Kraken balances passes
#   only then does the live Conductor start (it starts Freqtrade itself when no halt is active).
# If gate 5 or 6 fails the server stays in `live-pending` with only the paused live Freqtrade up
# (it cannot trade). Fix it (docs/06-runbooks/start-stop.md "R5 abort"), re-run `live`, or run
# `dry-run` to back out.
#
# There is deliberately no flag that skips a gate or shortens the soak.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
cd "$ROOT" || exit 2

LIVE_PRINCIPAL=20
CD=ai-trading-agent-conductor
FT=ai-trading-agent-freqtrade
CD_IMAGE=ai-trading-agent-conductor:0.1.0
DRY_VOLUME=infra_conductor-data
LIVE_VOLUME=infra_conductor-data-live
MODE_FILE=.trading-mode
SOAK_FILE=infra/live/soak-start
ARCHIVE_DIR=archive
# Test hook only: lets tests substitute the key check. Not an operator setting.
KRAKEN_ACCESS_CHECK=${KRAKEN_ACCESS_CHECK:-$HERE/kraken-access-check.sh}

DRY=(docker compose --env-file .env -f infra/docker-compose.yml)
LIVE=(docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.live.yml)

say()  { printf '%s\n' "$*"; }
fail() { printf 'REFUSED: %s\n' "$*" >&2; exit 1; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 2; }

MODE=dry-run
[ -f "$MODE_FILE" ] && MODE=$(tr -d '[:space:]' < "$MODE_FILE")
case "$MODE" in dry-run|live|live-pending) ;; *) die "$MODE_FILE says '$MODE' (expected dry-run, live or live-pending)" ;; esac
set_mode() { printf '%s\n' "$1" > "$MODE_FILE"; MODE=$1; }
running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]; }

[ -f .env ] || die ".env not found in $ROOT (run from the app directory on the VPS)"
command -v docker >/dev/null || die "docker not found (run this on the VPS)"

# What Freqtrade says about itself, read from inside its container so the API password never
# leaves it. Prints "dry_run=<True|False> state=<state> positions=<n> orders=<n>" or "unreachable".
ft_self() {
  docker exec -i "$FT" python - <<'PY' 2>/dev/null || echo unreachable
import base64, json, os, urllib.request
base = "http://127.0.0.1:8080/api/v1"
tok = base64.b64encode(
    f"{os.environ['FREQTRADE__API_SERVER__USERNAME']}:{os.environ['FREQTRADE__API_SERVER__PASSWORD']}".encode()
).decode()
def get(p):
    r = urllib.request.Request(base + p, headers={"Authorization": "Basic " + tok})
    return json.load(urllib.request.urlopen(r, timeout=8))
try:
    c, t = get("/show_config"), get("/status")
    print("dry_run=%s state=%s positions=%d orders=%d" % (
        c.get("dry_run"), c.get("state"), len(t), sum(1 for x in t if x.get("has_open_orders"))))
except Exception:
    print("unreachable")
PY
}

wait_healthy() {  # $1 container, $2 seconds
  local i=0
  while [ "$i" -lt "$2" ]; do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null)" = "healthy" ] && return 0
    sleep 2; i=$((i + 2))
  done
  return 1
}

# ---- gates ----------------------------------------------------------------------------------

gate_soak() {
  [ -f "$SOAK_FILE" ] || { say "FAIL soak: $SOAK_FILE is missing"; return 1; }
  local started; started=$(tr -d '[:space:]' < "$SOAK_FILE")
  if ! running "$CD"; then say "FAIL soak: the dry-run conductor is not running (its ledger holds the soak record)"; return 1; fi
  local out rc
  out=$(docker exec "$CD" python -m conductor.cli soak-check --started-at "$started" 2>&1); rc=$?
  printf '%s\n' "$out" | sed 's/^/  /'
  [ "$rc" -eq 0 ] && { say "PASS soak"; return 0; }
  say "FAIL soak"; return 1
}

gate_key() {
  local out rc
  out=$("$KRAKEN_ACCESS_CHECK" --scope trade 2>&1); rc=$?
  printf '%s\n' "$out" | sed 's/^/  /'
  [ "$rc" -eq 0 ] && { say "PASS key scopes"; return 0; }
  say "FAIL key scopes"; return 1
}

LEDGER_PROBE=$(cat <<'PY'
import sqlite3
try:
    db = sqlite3.connect("file:/data/conductor.db?mode=ro", uri=True)
    row = db.execute("SELECT amount FROM principal").fetchone()
    trades = db.execute("SELECT count(*) FROM trades").fetchone()[0]
    print("principal=%s trades=%s" % (row[0] if row else "NONE", trades))
except sqlite3.Error:
    print("principal=NONE trades=0")
PY
)

gate_ledger() {
  if ! docker volume inspect "$LIVE_VOLUME" >/dev/null 2>&1; then
    say "PASS ledger: no live volume yet (a fresh one is created empty)"; return 0
  fi
  local out
  out=$(printf '%s\n' "$LEDGER_PROBE" | docker run --rm -i --entrypoint python -v "$LIVE_VOLUME":/data:ro "$CD_IMAGE" - 2>&1 | tail -1)
  say "  live ledger: $out"
  case "$out" in
    "principal=NONE trades=0") say "PASS ledger: live volume exists but is empty"; return 0 ;;
    "principal=$LIVE_PRINCIPAL "*|"principal=$LIVE_PRINCIPAL.0 "*|"principal=$LIVE_PRINCIPAL.00 "*)
      say "PASS ledger: live ledger with principal $LIVE_PRINCIPAL (a re-run)"; return 0 ;;
  esac
  say "FAIL ledger: the live volume is not a fresh/own ledger ($out). Never reuse a dry-run or foreign ledger."
  return 1
}

archive_dry_run() {  # stack must be stopped (consistent files)
  local ts; ts=$(date -u +%Y%m%dT%H%M%SZ)
  mkdir -p "$ARCHIVE_DIR" && chmod 700 "$ARCHIVE_DIR" || return 1
  local ledger_tgz="$ARCHIVE_DIR/dry-run-ledger-$ts.tgz" ft_tgz="$ARCHIVE_DIR/dry-run-freqtrade-$ts.tgz"
  ( umask 077
    docker run --rm --entrypoint tar -v "$DRY_VOLUME":/data:ro "$CD_IMAGE" -czf - -C /data . > "$ledger_tgz" ) || return 1
  tar tzf "$ledger_tgz" 2>/dev/null | grep -q 'conductor.db' || { say "archive of the ledger is missing conductor.db"; return 1; }
  ( umask 077
    cd services/freqtrade/user_data 2>/dev/null && tar czf - tradesv3.dryrun.sqlite* > "$OLDPWD/$ft_tgz" ) 2>/dev/null
  chmod 600 "$ledger_tgz" "$ft_tgz" 2>/dev/null
  tar tzf "$ft_tgz" 2>/dev/null | grep -q 'tradesv3.dryrun.sqlite' || { say "archive of Freqtrade's DB is missing tradesv3.dryrun.sqlite"; return 1; }
  say "  archived: $ledger_tgz and $ft_tgz"
}

# ---- commands -------------------------------------------------------------------------------

cmd_status() {
  local mode=$MODE
  say "mode: $mode"
  docker ps -a --filter name=ai-trading-agent --format '  {{.Names}}  {{.Status}}'
  if running "$FT"; then say "freqtrade: $(ft_self)"; fi
}

cmd_live() {
  local mode=$MODE
  [ "$mode" = live ] && { say "already live."; cmd_status; return 0; }

  say "== Gates (nothing has been stopped or changed yet)"
  local bad=0
  if [ "$mode" = dry-run ]; then
    gate_soak || bad=1
  else
    say "SKIP soak: already passed on the way into live-pending"
  fi
  gate_key || bad=1
  gate_ledger || bad=1
  [ "$bad" -eq 0 ] || fail "one or more gates failed; nothing was changed"

  if [ "$mode" = dry-run ]; then
    say "== Stopping the dry-run stack and archiving its ledger"
    "${DRY[@]}" down || fail "could not stop the dry-run stack"
    if ! archive_dry_run; then
      "${DRY[@]}" up -d
      fail "archive failed; the dry-run stack was restarted and nothing else changed"
    fi
    set_mode live-pending
  fi

  say "== Starting Freqtrade in LIVE config, paused (it cannot trade yet)"
  "${LIVE[@]}" up -d --no-deps --build freqtrade || fail "freqtrade did not start; mode stays live-pending"
  wait_healthy "$FT" 180 || fail "freqtrade is not healthy after 180 s; mode stays live-pending (docker logs $FT)"
  local self; self=$(ft_self)
  say "  freqtrade says: $self"
  case "$self" in
    "dry_run=False state=paused "*) ;;
    *) fail "gate MODE: expected dry_run=False and state=paused, got '$self'. Staying live-pending; the bot is not trading." ;;
  esac
  say "PASS mode"

  say "== R5 account isolation against the real Kraken balances"
  local out rc
  out=$("${LIVE[@]}" run --rm --no-deps -T --entrypoint sh conductor \
        -c 'alembic upgrade head >/dev/null 2>&1 && exec python -m conductor.cli isolation-check' 2>&1); rc=$?
  printf '%s\n' "$out" | sed 's/^/  /'
  if [ "$rc" -ne 0 ]; then
    fail "R5 gate failed. Staying live-pending with only the paused live Freqtrade up. Clear it per docs/06-runbooks/start-stop.md ('R5 abort'), then re-run: scripts/trading-mode.sh live (or back out: scripts/trading-mode.sh dry-run)"
  fi
  say "PASS R5"

  say "== Starting the live Conductor"
  "${LIVE[@]}" up -d --no-deps conductor || fail "conductor did not start; mode stays live-pending"
  set_mode live
  say "LIVE. Conductor starts Freqtrade itself once it sees no active halt. Watch: scripts/drill-check.sh --watch"
  say "Telegram and the dashboard now show the LIVE banner. Kill switch: /kill. Back out: scripts/trading-mode.sh dry-run"
}

cmd_dry_run() {
  local mode=$MODE
  [ "$mode" = dry-run ] && { say "already dry-run."; cmd_status; return 0; }
  if [ "$mode" = live ]; then
    if ! running "$FT"; then
      fail "the live Freqtrade is not running, so open real positions/orders cannot be checked. Check Kraken by hand and start it (scripts/compose.sh up -d) first."
    fi
    local self; self=$(ft_self)
    say "freqtrade says: $self"
    case "$self" in
      *" positions=0 orders=0") ;;
      unreachable) fail "cannot read Freqtrade, so open real positions/orders cannot be ruled out. Do not switch." ;;
      *) fail "real positions or orders are open ($self). Flatten first: /flatten (docs/06-runbooks/nuclear-protocol.md), confirm flat on Kraken, then re-run." ;;
    esac
  fi
  say "== Stopping the live stack"
  "${LIVE[@]}" down || fail "could not stop the live stack"
  set_mode dry-run
  say "== Starting the dry-run stack (the live ledger volume $LIVE_VOLUME is kept, untouched)"
  "${DRY[@]}" up -d || fail "dry-run stack did not start; mode is dry-run, start it with scripts/compose.sh up -d"
  say "DRY-RUN. The Kraken key is still in .env: remove it (go-live-pilot.md) if live is over."
}

cmd_cli() {
  [ "$MODE" != dry-run ] || fail "mode is dry-run: the live ledger is not in use. (Use 'docker exec $CD python -m conductor.cli ...' for the dry-run ledger.)"
  if running "$CD"; then
    exec docker exec "$CD" python -m conductor.cli "$@"
  fi
  exec "${LIVE[@]}" run --rm --no-deps -T --entrypoint sh conductor \
    -c 'alembic upgrade head >/dev/null 2>&1 && exec python -m conductor.cli "$@"' conductor-cli "$@"
}

case "${1:-}" in
  status)   [ $# -eq 1 ] || die "status takes no arguments"; cmd_status ;;
  live)     [ $# -eq 1 ] || die "live takes no arguments: gates cannot be skipped or tuned"; cmd_live ;;
  dry-run)  [ $# -eq 1 ] || die "dry-run takes no arguments"; cmd_dry_run ;;
  cli)      shift; cmd_cli "$@" ;;
  -h|--help|"") sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "unknown command: $1 (status | live | dry-run | cli)" ;;
esac
