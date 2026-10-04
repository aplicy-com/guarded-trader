#!/usr/bin/env bash
# Host-level lockdown for the VPS (Ubuntu 24.04): ufw default-deny incoming
# (allow only tailscale0) and sshd bound to the Tailscale IP (+ loopback).
# Defence in depth behind the Hetzner firewall (risk S8).
#
# Usage (see docs/06-runbooks/provision-vps.md step 12a):
#   harden-host.sh --dry-run  [--ssh-connection "<\$SSH_CONNECTION>"]   print only
#   harden-host.sh --ssh-connection "<\$SSH_CONNECTION>"                apply
#   harden-host.sh --confirm                                            keep it
#   harden-host.sh --cloud-init [--allow-public-ssh-from CIDR]          first boot
#
# Why --ssh-connection: sudo strips SSH_CONNECTION, so pass it from the
# unprivileged shell: sudo bash harden-host.sh --ssh-connection "$SSH_CONNECTION"
#
# Anti-lockout (interactive mode):
#   * fails CLOSED unless this session arrived over the tailnet (client IP in
#     100.64.0.0/10, server address == our Tailscale IP, and the connection is
#     really present in `ss`);
#   * a rollback timer is scheduled AND verified before any change; unless you
#     run --confirm within 5 minutes it undoes everything;
#   * after the change it checks sshd listens only on the tailnet IP/loopback
#     and answers on the tailnet IP; otherwise it rolls back immediately.
# Re-running is safe.
set -euo pipefail

ROOT="${HARDEN_TEST_ROOT:-}"   # test seam only: prefixes file paths (empty on a real host)
ROLLBACK_SECS=300
ROLLBACK_BIN=$ROOT/usr/local/sbin/harden-host-rollback   # NOT /run: that is noexec
ROLLBACK_UNIT=harden-host-rollback
CONFIRM=$ROOT/run/harden-host.confirm
SOCK_DROPIN_DIR=$ROOT/etc/systemd/system/ssh.socket.d
SOCK_DROPIN=$SOCK_DROPIN_DIR/20-tailscale-only.conf
OLD_SSHD_DROPIN=$ROOT/etc/ssh/sshd_config.d/20-listen-tailscale.conf   # earlier version

DRY=0
ACTION=apply
CLOUD_INIT=0
ALLOW_CIDR=""
SSH_CONN="${SSH_CONNECTION:-}"
WOULD_ABORT=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --confirm) ACTION=confirm ;;
    --cloud-init) CLOUD_INIT=1 ;;
    --allow-public-ssh-from) ALLOW_CIDR="${2:?CIDR required}"; shift ;;
    --ssh-connection) SSH_CONN="${2:-}"; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '%s\n' "$*"; }
run() {
  if [ "$DRY" -eq 1 ]; then printf '[dry-run] %s\n' "$*"; else "$@"; fi
}
# write_file PATH MODE  (content on stdin)
write_file() {
  if [ "$DRY" -eq 1 ]; then
    printf '[dry-run] write %s (mode %s):\n' "$1" "$2"; sed 's/^/    | /'
  else
    cat >"$1"; chmod "$2" "$1"
  fi
}
# fail MSG: abort (dry-run: report and keep going so you see everything)
fail() {
  if [ "$DRY" -eq 1 ]; then say "WOULD ABORT: $*"; WOULD_ABORT=1; else say "ERROR: $*" >&2; exit 1; fi
}
is_tailnet_v4() {
  [[ "$1" =~ ^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]+\.[0-9]+$ ]]
}

emit_rollback_script() {
  cat <<RB
#!/bin/bash
# Written by harden-host.sh. Undoes the lockdown unless confirmed.
[ -e $CONFIRM ] && exit 0
rm -f $SOCK_DROPIN
systemctl daemon-reload
systemctl stop ssh.service ssh.socket
systemctl start ssh.socket
ufw --force disable
logger -t harden-host "NOT confirmed: rolled back (ufw off, ssh.socket on all addresses)"
RB
}

# ---------------------------------------------------------------- confirm ---
if [ "$ACTION" = confirm ]; then
  [ "$(id -u)" -eq 0 ] || { say "run as root (sudo)" >&2; exit 1; }
  touch "$CONFIRM"
  systemctl stop "$ROLLBACK_UNIT.timer" "$ROLLBACK_UNIT.service" 2>/dev/null || true
  systemctl reset-failed "$ROLLBACK_UNIT.timer" "$ROLLBACK_UNIT.service" 2>/dev/null || true
  rm -f "$ROLLBACK_BIN"
  say "Confirmed: lockdown kept, rollback cancelled."
  exit 0
fi

# -------------------------------------------------------------- preflight ---
[ "$DRY" -eq 1 ] || [ "$(id -u)" -eq 0 ] || fail "run as root (sudo)"

if ! command -v tailscale >/dev/null 2>&1; then
  fail "tailscale not installed"; TS_IP="100.64.0.1"
else
  TS_IP="$(tailscale ip -4 2>/dev/null | head -n1 || true)"
  is_tailnet_v4 "$TS_IP" || { fail "no valid Tailscale IPv4 (got '${TS_IP}'); is Tailscale up?"; TS_IP="100.64.0.1"; }
fi
ip link show tailscale0 >/dev/null 2>&1 || fail "tailscale0 interface missing"
systemctl cat ssh.socket >/dev/null 2>&1 || fail "ssh.socket unit not found (this script targets Ubuntu 24.04 socket-activated ssh)"
if ! command -v ufw >/dev/null 2>&1; then
  if [ "$DRY" -eq 1 ]; then say "[dry-run] would apt-get install ufw"; else apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ufw; fi
fi
if [ -n "$ALLOW_CIDR" ] && ! [[ "$ALLOW_CIDR" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]]; then
  fail "--allow-public-ssh-from needs an IPv4 CIDR, got '$ALLOW_CIDR'"
fi

if [ "$CLOUD_INIT" -eq 0 ]; then
  read -r CLI_IP CLI_PORT SRV_IP _ <<<"$SSH_CONN" || true
  if [ -z "${CLI_IP:-}" ] || [ -z "${SRV_IP:-}" ]; then
    fail "no SSH_CONNECTION. Fail closed. Run: sudo bash $0 --ssh-connection \"\$SSH_CONNECTION\" (from an SSH session over Tailscale)"
  else
    is_tailnet_v4 "$CLI_IP" || fail "client $CLI_IP is not in 100.64.0.0/10: you are not on the tailnet. Reconnect with 'make ssh'."
    [ "$SRV_IP" = "$TS_IP" ] || fail "session reached server address $SRV_IP, not the Tailscale IP $TS_IP. Connect to $TS_IP directly."
    if [ "$DRY" -eq 0 ] && ! ss -Htn state established '( sport = :22 )' | grep -qF -- "$CLI_IP:$CLI_PORT"; then
      fail "connection $CLI_IP:$CLI_PORT not found in 'ss' (stale or forged --ssh-connection)"
    fi
  fi
fi

# ------------------------------------------------- rollback timer (first) ---
if [ "$CLOUD_INIT" -eq 0 ]; then
  run rm -f "$CONFIRM"
  run systemctl stop "$ROLLBACK_UNIT.timer" "$ROLLBACK_UNIT.service" 2>/dev/null || true
  run systemctl reset-failed "$ROLLBACK_UNIT.timer" "$ROLLBACK_UNIT.service" 2>/dev/null || true
  run mkdir -p "$(dirname "$ROLLBACK_BIN")"
  emit_rollback_script | write_file "$ROLLBACK_BIN" 0700
  run systemd-run --quiet --unit="$ROLLBACK_UNIT" --on-active="${ROLLBACK_SECS}s" /bin/bash "$ROLLBACK_BIN"
  if [ "$DRY" -eq 1 ]; then
    say "[dry-run] would verify: systemctl is-active $ROLLBACK_UNIT.timer (abort before any change if not)"
  elif ! systemctl is-active --quiet "$ROLLBACK_UNIT.timer"; then
    rm -f "$ROLLBACK_BIN"; fail "rollback timer is not active; refusing to change anything"
  fi
fi

# ------------------------------------------------------------------- ufw ---
# tailscale0 is allowed BEFORE enabling, and no other inbound rule exists.
run ufw --force reset
run ufw default deny incoming
run ufw default allow outgoing
run ufw allow in on tailscale0
if [ -n "$ALLOW_CIDR" ]; then
  run ufw allow from "$ALLOW_CIDR" to any port 22 proto tcp comment 'bootstrap ssh'
fi
run ufw --force enable

# ------------------------------------------- sshd: bind via ssh.socket ---
# Ubuntu 24.04 starts sshd from ssh.socket (systemd holds :22), so sshd_config
# ListenAddress is ignored. We override the socket's ListenStream instead.
if [ -z "$ALLOW_CIDR" ]; then
  run rm -f "$OLD_SSHD_DROPIN"
  run mkdir -p "$SOCK_DROPIN_DIR"
  write_file "$SOCK_DROPIN" 0644 <<CONF
[Socket]
# Empty assignment clears the default 0.0.0.0:22 and [::]:22.
ListenStream=
ListenStream=${TS_IP}:22
ListenStream=127.0.0.1:22
# Bind even if tailscale0 has no address yet (early boot) instead of failing.
FreeBind=yes
CONF
  run systemctl daemon-reload
  # Stop the service first: a running sshd keeps the OLD 0.0.0.0:22 fd open.
  # Existing sessions survive (ssh.service uses KillMode=process).
  run systemctl stop ssh.service ssh.socket
  run systemctl start ssh.socket

  if [ "$DRY" -eq 1 ]; then
    say "[dry-run] would verify: port 22 listeners are only ${TS_IP}:22 and 127.0.0.1:22, and ${TS_IP}:22 returns an SSH banner; else run $ROLLBACK_BIN and exit 1"
  else
    sleep 1
    BAD="$(ss -Hltn '( sport = :22 )' | awk '{print $4}' | grep -vxF -e "${TS_IP}:22" -e "127.0.0.1:22" || true)"
    BANNER="$(timeout 5 bash -c "exec 3<>/dev/tcp/${TS_IP}/22; head -c 4 <&3" 2>/dev/null || true)"
    if [ -n "$BAD" ] || [ "$BANNER" != "SSH-" ]; then
      say "VERIFY FAILED. unexpected listeners: '${BAD}' banner: '${BANNER}'. Rolling back." >&2
      if [ -x "$ROLLBACK_BIN" ]; then /bin/bash "$ROLLBACK_BIN"; else
        rm -f "$SOCK_DROPIN"; systemctl daemon-reload; systemctl stop ssh.service ssh.socket; systemctl start ssh.socket; ufw --force disable
      fi
      exit 1
    fi
  fi
fi

# ---------------------------------------------------------------- report ---
if [ "$DRY" -eq 1 ]; then
  say; say "Dry run complete. Nothing was changed."
  [ "$WOULD_ABORT" -eq 0 ] || { say "At least one check above would abort a real run."; exit 3; }
  exit 0
fi
say; say "Applied. Port 22 listeners:"; ss -ltnp '( sport = :22 )' || true
ufw status verbose
if [ "$CLOUD_INIT" -eq 0 ]; then
  say
  say "AUTO-ROLLBACK in ${ROLLBACK_SECS}s unless you confirm."
  say "Open a NEW terminal, run 'make ssh'. If it works: sudo bash $0 --confirm"
fi
