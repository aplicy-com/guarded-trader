#!/usr/bin/env bash
# Restore drill for the nightly backups (docs/06-runbooks/restore-backup.md).
#
# Downloads the LATEST backup of the Conductor ledger and/or Freqtrade's DB from Backblaze B2,
# gunzips it, runs PRAGMA integrity_check, and prints row counts.
#
# Backups are namespaced by trading mode (ADR-0019), so you MUST say which one you want:
#   --mode live      backups/live/<source>/...      the $20 pilot ledger and live trade DB
#   --mode dry_run   backups/dry_run/<source>/...   the dry-run ledger and DB
#   --mode legacy    backups/<source>/...           dry-run backups made BEFORE the split
#                                                   (only until the first nightly run after it)
# There is no default: restoring the wrong mode's ledger is exactly the mistake this prevents.
#
# Run it from your Mac. It needs a B2 key that can LIST and READ (the key on the VPS is
# write-only and cannot do this). Supply the key in your shell for this one run; the script
# never writes it anywhere:
#
#   read -rs "RESTORE_B2_KEY_ID?Read key ID: ";  export RESTORE_B2_KEY_ID;  echo
#   read -rs "RESTORE_B2_APP_KEY?Read app key: "; export RESTORE_B2_APP_KEY; echo
#   export BACKUP_B2_BUCKET=...  BACKUP_B2_ENDPOINT=https://s3.<region>.backblazeb2.com
#   scripts/restore-test.sh --mode live|dry_run|legacy [conductor|freqtrade|all] [--keep DIR]
#   unset RESTORE_B2_KEY_ID RESTORE_B2_APP_KEY
#
# Needs: aws CLI (brew install awscli), sqlite3, gzip. Read-only toward B2: it only lists and
# downloads. Restored copies are removed on exit unless --keep DIR is given.
set -euo pipefail
umask 077

die() { echo "ERROR: $*" >&2; exit 1; }

WHAT=all
KEEP=""
MODE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) shift; [ $# -gt 0 ] || die "--mode needs live, dry_run or legacy"; MODE=$1 ;;
    conductor|freqtrade|all) WHAT=$1 ;;
    --keep) shift; [ $# -gt 0 ] || die "--keep needs a directory"; KEEP=$1 ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1 (use --mode M, conductor, freqtrade, all, --keep DIR)" ;;
  esac
  shift
done
case "$MODE" in
  live|dry_run) PREFIX_ROOT="backups/$MODE" ;;
  legacy) PREFIX_ROOT="backups" ;;
  "") die "--mode is required: live, dry_run or legacy (see the header of this script)" ;;
  *) die "--mode must be live, dry_run or legacy, not '$MODE'" ;;
esac

for v in BACKUP_B2_BUCKET BACKUP_B2_ENDPOINT RESTORE_B2_KEY_ID RESTORE_B2_APP_KEY; do
  [ -n "${!v:-}" ] || die "$v is not set (see the header of this script)"
done
command -v aws >/dev/null || die "aws CLI not found (brew install awscli)"
command -v sqlite3 >/dev/null || die "sqlite3 not found"
command -v gzip >/dev/null || die "gzip not found"
case "$BACKUP_B2_ENDPOINT" in https://*) ;; *) die "BACKUP_B2_ENDPOINT must be an https URL" ;; esac

# Credentials go to the aws CLI through its environment only; ignore any ~/.aws profile.
export AWS_ACCESS_KEY_ID=$RESTORE_B2_KEY_ID
export AWS_SECRET_ACCESS_KEY=$RESTORE_B2_APP_KEY
export AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null
export AWS_EC2_METADATA_DISABLED=true AWS_PAGER="" AWS_RETRY_MODE=standard
# SigV4 needs the right region; Backblaze encodes it in the endpoint host.
region=$(printf '%s' "$BACKUP_B2_ENDPOINT" | sed -n 's#^https://s3\.\([a-z0-9-]*\)\.backblazeb2\.com.*#\1#p')
export AWS_DEFAULT_REGION=${RESTORE_B2_REGION:-${region:-us-east-1}}
# B2's S3 API does not take the newer default checksum behaviour.
export AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required

s3() { aws --endpoint-url "$BACKUP_B2_ENDPOINT" "$@"; }

if [ -n "$KEEP" ]; then
  mkdir -p "$KEEP"; WORK=$(cd "$KEEP" && pwd)
else
  WORK=$(mktemp -d "${TMPDIR:-/tmp}/restore-test.XXXXXX")
  trap 'rm -rf "$WORK"' EXIT
fi

FAILED=0

# table name, then the row count, aligned
row_counts() {
  local db=$1 t n
  while IFS= read -r t; do
    n=$(sqlite3 -readonly "$db" "SELECT count(*) FROM \"$t\";")
    printf '    %-24s %s\n' "$t" "$n"
  done < <(sqlite3 -readonly "$db" "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
}

restore_one() {
  local label=$1 prefix="$PREFIX_ROOT/$1/" listing key stamp size_h age_h db
  echo "== $label  (mode: $MODE)"
  if ! listing=$(s3 s3api list-objects-v2 --bucket "$BACKUP_B2_BUCKET" --prefix "$prefix" \
        --query 'Contents[].[Key,LastModified]' --output text 2>&1); then
    echo "   FAILED: could not list s3://$BACKUP_B2_BUCKET/$prefix"
    echo "   ($(printf '%s' "$listing" | tail -1))"
    echo "   Is this a READ key? The VPS's backup key is write-only and cannot list."
    FAILED=1; return
  fi
  # Keys embed a UTC timestamp, so the lexicographically greatest key is the latest backup.
  listing=$(printf '%s\n' "$listing" | grep -v '^None' | grep . | sort | tail -1 || true)
  if [ -z "$listing" ]; then
    echo "   FAILED: no backups found under $prefix"
    [ "$MODE" != dry_run ] || echo "   (dry-run backups made before the mode split are under --mode legacy)"
    FAILED=1; return
  fi
  key=$(printf '%s' "$listing" | cut -f1); stamp=$(printf '%s' "$listing" | cut -f2)
  age_h=$(sqlite3 :memory: "SELECT (strftime('%s','now') - strftime('%s','$stamp')) / 3600;" 2>/dev/null || echo "?")
  echo "   latest : $key"
  echo "   stored : $stamp  (${age_h} h ago)"
  if [ "$age_h" != "?" ] && [ "$age_h" -gt 36 ]; then
    echo "   WARNING: the latest backup is older than 36 h; the nightly job is not running"
    FAILED=1
  fi
  if ! s3 s3 cp --only-show-errors "s3://$BACKUP_B2_BUCKET/$key" "$WORK/$label.sqlite.gz"; then
    echo "   FAILED: download"; FAILED=1; return
  fi
  size_h=$(wc -c < "$WORK/$label.sqlite.gz" | tr -d ' ')
  echo "   downloaded $size_h bytes"
  db="$WORK/$label.sqlite"
  if ! gunzip -c "$WORK/$label.sqlite.gz" > "$db"; then
    echo "   FAILED: gunzip (corrupt download?)"; FAILED=1; return
  fi
  local check
  check=$(sqlite3 -readonly "$db" 'PRAGMA integrity_check;' 2>&1 || true)
  if [ "$check" != "ok" ]; then
    echo "   FAILED: integrity_check: $(printf '%s' "$check" | head -3)"; FAILED=1; return
  fi
  echo "   integrity_check: ok"
  echo "   row counts:"
  row_counts "$db"
  if [ "$label" = conductor ]; then
    echo "   principal: $(sqlite3 -readonly "$db" 'SELECT amount || " " || currency FROM principal;')"
    echo "   halts still active in this copy: $(sqlite3 -readonly "$db" "SELECT coalesce((SELECT group_concat('#' || h.id || ' ' || h.halt_type, ', ') FROM halts h LEFT JOIN halt_clears c ON c.halt_id = h.id WHERE c.id IS NULL), '(none)');")"
    echo "   latest audit entry: $(sqlite3 -readonly "$db" 'SELECT coalesce((SELECT at || "  " || action FROM audit_log ORDER BY id DESC LIMIT 1), "(none)");')"
  fi
  [ -z "$KEEP" ] || echo "   kept at: $db"
}

case "$WHAT" in
  all) restore_one conductor; restore_one freqtrade ;;
  *) restore_one "$WHAT" ;;
esac

echo
if [ "$FAILED" -eq 0 ]; then echo "RESTORE TEST PASSED"; else echo "RESTORE TEST FAILED"; exit 1; fi
