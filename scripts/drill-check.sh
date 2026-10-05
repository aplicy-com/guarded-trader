#!/usr/bin/env bash
# One-command state check for the 3A-6 drills (docs/drills/README.md). Run it ON THE VPS,
# from /opt/ai-trading-agent. Read-only: it changes nothing and talks to no exchange.
#
#   scripts/drill-check.sh                          full report
#   scripts/drill-check.sh --brief                  one SUMMARY line
#   scripts/drill-check.sh --watch [SECONDS]        SUMMARY line every 5 s (or SECONDS); Ctrl-C to stop
#   scripts/drill-check.sh --expect-state paused --expect-halts 1 [--expect-positions N]
#                                                   prints PASS/FAIL, exit 1 on any mismatch
#
# Prints: halt state (from the ledger, via Conductor's own CLI), Freqtrade's state and open
# positions (from Freqtrade's REST API, called from inside its own container so the API
# password never leaves it), and the heartbeat as Conductor's dashboard reports it.
#
# Freqtrade states: running | paused (= /stopentry, what the kill switch sets) | stopped.
# The heartbeat is held in Conductor's memory only: after a Conductor restart it reads
# "none sent since start" until the first ping (up to 5 min).
set -uo pipefail

FT=ai-trading-agent-freqtrade
CD=ai-trading-agent-conductor
CD_IMAGE=ai-trading-agent-conductor:0.1.0
LEDGER_VOLUME=infra_conductor-data

MODE=full
WATCH_EVERY=5
EXPECT_STATE=""
EXPECT_HALTS=""
EXPECT_POSITIONS=""

die() { echo "ERROR: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --brief) MODE=brief ;;
    --watch) MODE=watch
             if [ $# -gt 1 ] && [[ "$2" =~ ^[0-9]+$ ]]; then WATCH_EVERY=$2; shift; fi ;;
    --expect-state)     shift; EXPECT_STATE=${1:?--expect-state needs running|paused|stopped} ;;
    --expect-halts)     shift; EXPECT_HALTS=${1:?--expect-halts needs a number} ;;
    --expect-positions) shift; EXPECT_POSITIONS=${1:?--expect-positions needs a number} ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done
[ -z "$EXPECT_HALTS" ] || [[ "$EXPECT_HALTS" =~ ^[0-9]+$ ]] || die "--expect-halts needs a number"
[ -z "$EXPECT_POSITIONS" ] || [[ "$EXPECT_POSITIONS" =~ ^[0-9]+$ ]] || die "--expect-positions needs a number"
case "$EXPECT_STATE" in ""|running|paused|stopped) ;; *) die "--expect-state: running, paused or stopped" ;; esac
command -v docker >/dev/null || die "docker not found (run this on the VPS)"
command -v python3 >/dev/null || die "python3 not found on the host"

running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]; }

# --- Freqtrade: state + open positions, one JSON line from inside its container -----------
# Credentials come from the container's own environment (env_file), never from this shell.
FT_PROBE=$(cat <<'PY'
import base64, json, os, urllib.request
base = "http://127.0.0.1:8080/api/v1"
tok = base64.b64encode(
    f"{os.environ['FREQTRADE__API_SERVER__USERNAME']}:{os.environ['FREQTRADE__API_SERVER__PASSWORD']}".encode()
).decode()
def get(path):
    req = urllib.request.Request(base + path, headers={"Authorization": "Basic " + tok})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.load(r)
try:
    cfg = get("/show_config")
    trades = get("/status")
    print(json.dumps({
        "ok": True,
        "state": cfg.get("state", "unknown"),
        "dry_run": cfg.get("dry_run"),
        "positions": [
            {"id": t.get("trade_id"), "pair": t.get("pair"), "stake": t.get("stake_amount"),
             "open_orders": bool(t.get("has_open_orders"))} for t in trades],
    }))
except Exception as exc:
    print(json.dumps({"ok": False, "error": type(exc).__name__}))
PY
)

ft_json() {
  if ! running "$FT"; then echo '{"ok": false, "error": "container not running"}'; return; fi
  local out
  out=$(printf '%s\n' "$FT_PROBE" | docker exec -i "$FT" python - 2>/dev/null) \
    || out='{"ok": false, "error": "probe failed"}'
  [ -n "$out" ] && echo "$out" || echo '{"ok": false, "error": "no output"}'
}

HALTS_PY=$(cat <<'PY'
import sqlite3, sys
all_ = sys.argv[1] == "--all"
db = sqlite3.connect("file:/data/conductor.db?mode=ro", uri=True)
rows = db.execute(
    "SELECT h.id, h.halt_type, coalesce(h.instance, 'all instances'), h.reason, c.cleared_at, c.operator "
    "FROM halts h LEFT JOIN halt_clears c ON c.halt_id = h.id ORDER BY h.id DESC LIMIT 200"
).fetchall()
n = 0
for i, t, inst, why, at, op in rows:
    if at is not None and not all_:
        continue
    print(f"#{i} {t} [{inst}] " + ("ACTIVE" if at is None else f"cleared {at} by {op}") + f" :: {why}")
    n += 1
if not n:
    print("no active halts")
PY
)

# --- Halts: Conductor's CLI when it is up; a read-only ledger peek when it is stopped ------
halts_text() {  # $1 = "" (active) | --all
  if running "$CD"; then
    docker exec "$CD" python -m conductor.cli halts $1 2>&1
  elif docker image inspect "$CD_IMAGE" >/dev/null 2>&1 && docker volume inspect "$LEDGER_VOLUME" >/dev/null 2>&1; then
    # Conductor is stopped, so nothing else is writing the ledger.
    printf '%s\n' "$HALTS_PY" | docker run --rm -i --entrypoint python -v "$LEDGER_VOLUME":/data \
      "$CD_IMAGE" - "${1:-active}" 2>&1 | sed 's/^/(conductor stopped; read from ledger) /'
  else
    echo "UNREADABLE: conductor container stopped and the ledger volume/image is missing"
  fi
}

# --- Heartbeat: the dashboard's own Monitoring box, via the Conductor container -----------
heartbeat_text() {
  if ! running "$CD"; then echo "n/a (conductor container not running)"; return; fi
  docker exec "$CD" python -c '
import re, urllib.request
try:
    html = urllib.request.urlopen("http://127.0.0.1:8000/partials/overview", timeout=5).read().decode()
except Exception as exc:
    print("unreadable:", type(exc).__name__); raise SystemExit
text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
m = re.search(r"Heartbeat (.*?) Backups", text)
print(m.group(1).strip() if m else "not found on dashboard")
' 2>&1
}

health_text() {
  if ! running "$CD"; then echo "n/a"; return; fi
  docker exec "$CD" python -c '
import urllib.request
try:
    print(urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5).read().decode()[:300])
except Exception as exc:
    print("unreadable:", type(exc).__name__)
' 2>&1
}

# --- Data counts: lets a rebuild/restore be compared before and after ----------------------
LEDGER_PROBE=$(cat <<'PY'
import sqlite3
db = sqlite3.connect("file:/data/conductor.db?mode=ro", uri=True)
one = lambda q: db.execute(q).fetchone()[0]
print("principal=%s trades=%s halts=%s (active %s) audit_entries=%s" % (
    one("SELECT coalesce((SELECT amount || ' ' || currency FROM principal LIMIT 1), 'NONE')"),
    one("SELECT count(*) FROM trades"), one("SELECT count(*) FROM halts"),
    one("SELECT count(*) FROM halts h LEFT JOIN halt_clears c ON c.halt_id = h.id WHERE c.id IS NULL"),
    one("SELECT count(*) FROM audit_log")))
PY
)
FT_DB_PROBE=$(cat <<'PY'
import sqlite3
db = sqlite3.connect("file:/freqtrade/user_data/tradesv3.dryrun.sqlite?mode=ro", uri=True)
print("trades=%s (open %s)" % (db.execute("SELECT count(*) FROM trades").fetchone()[0],
                              db.execute("SELECT count(*) FROM trades WHERE is_open = 1").fetchone()[0]))
PY
)
counts_text() {
  local l f
  if running "$CD"; then
    l=$(printf '%s\n' "$LEDGER_PROBE" | docker exec -i "$CD" python - 2>&1 | tail -1)
  else l="n/a (conductor not running)"; fi
  if running "$FT"; then
    f=$(printf '%s\n' "$FT_DB_PROBE" | docker exec -i "$FT" python - 2>&1 | tail -1)
  else f="n/a (freqtrade not running)"; fi
  echo "   ledger:       $l"
  echo "   freqtrade db: $f"
}

# --- Collect ------------------------------------------------------------------------------
collect() {
  FTJ=$(ft_json)
  eval "$(printf '%s' "$FTJ" | python3 -c '
import json, shlex, sys
d = json.load(sys.stdin)
print("FT_OK=%s" % ("1" if d.get("ok") else "0"))
print("FT_STATE=%s" % shlex.quote(d.get("state", "unreachable") if d.get("ok") else "unreachable(" + str(d.get("error")) + ")"))
print("FT_DRY=%s" % shlex.quote(str(d.get("dry_run"))))
print("FT_POSITIONS=%d" % len(d.get("positions", [])))
for p in d.get("positions", []):
    print("FT_POS_LINES+=(%s)" % shlex.quote("  #%s %s stake %s%s" % (p["id"], p["pair"], p["stake"], "  [open order]" if p["open_orders"] else "")))
' 2>/dev/null)" || { FT_OK=0; FT_STATE="unreachable(parse)"; FT_DRY="?"; FT_POSITIONS="?"; }
  HALTS_ACTIVE_TEXT=$(halts_text "")
  if printf '%s' "$HALTS_ACTIVE_TEXT" | grep -q 'UNREADABLE'; then HALT_COUNT="?"
  else HALT_COUNT=$(printf '%s\n' "$HALTS_ACTIVE_TEXT" | grep -c '\] ACTIVE ::' || true); fi
  HB=$(heartbeat_text)
}

summary() {
  printf 'SUMMARY %s halts=%s freqtrade=%s positions=%s dry_run=%s heartbeat="%s"\n' \
    "$(date -u +%H:%M:%SZ)" "$HALT_COUNT" "$FT_STATE" "$FT_POSITIONS" "$FT_DRY" "$HB"
}

FT_POS_LINES=()

if [ "$MODE" = watch ]; then
  echo "Watching every ${WATCH_EVERY}s. Ctrl-C to stop."
  while true; do FT_POS_LINES=(); collect; summary; sleep "$WATCH_EVERY"; done
fi

collect

if [ "$MODE" = full ]; then
  echo "== drill-check  $(date -u '+%Y-%m-%d %H:%M:%SZ')  host $(hostname)"
  echo
  echo "-- containers"
  docker ps -a --filter name=ai-trading-agent --format '  {{.Names}}  {{.Status}}'
  echo
  echo "-- halts (active)"
  printf '%s\n' "$HALTS_ACTIVE_TEXT" | sed 's/^/  /'
  echo "-- halts (recent, incl. cleared)"
  halts_text "--all" | head -6 | sed 's/^/  /'
  echo
  echo "-- freqtrade   state: $FT_STATE   dry_run: $FT_DRY"
  echo "   open positions: $FT_POSITIONS"
  for line in "${FT_POS_LINES[@]:-}"; do [ -n "$line" ] && echo "$line"; done
  echo
  echo "-- data (compare before/after a restore)"
  counts_text
  echo
  echo "-- conductor"
  echo "   health: $(health_text)"
  echo "   heartbeat: $HB"
  if running "$CD"; then
    echo "   recent heartbeat/halt log lines:"
    docker logs --since 20m "$CD" 2>&1 | grep -Ei 'heartbeat|halt_|job_failed' | tail -5 | cut -c1-200 | sed 's/^/     /'
  fi
  echo
fi
summary

# --- Expectations ---------------------------------------------------------------------------
if [ -n "$EXPECT_STATE$EXPECT_HALTS$EXPECT_POSITIONS" ]; then
  bad=0
  if [ -n "$EXPECT_STATE" ] && [ "$FT_STATE" != "$EXPECT_STATE" ]; then
    echo "MISMATCH: freqtrade state is '$FT_STATE', expected '$EXPECT_STATE'"; bad=1; fi
  if [ -n "$EXPECT_HALTS" ] && [ "$HALT_COUNT" != "$EXPECT_HALTS" ]; then
    echo "MISMATCH: active halts is '$HALT_COUNT', expected '$EXPECT_HALTS'"; bad=1; fi
  if [ -n "$EXPECT_POSITIONS" ] && [ "$FT_POSITIONS" != "$EXPECT_POSITIONS" ]; then
    echo "MISMATCH: open positions is '$FT_POSITIONS', expected '$EXPECT_POSITIONS'"; bad=1; fi
  if [ "$bad" -eq 0 ]; then echo "CHECK PASS"; else echo "CHECK FAIL"; exit 1; fi
fi
