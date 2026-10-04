#!/usr/bin/env bash
# Host-level lockdown for the VPS: ufw default-deny incoming (allow only
# tailscale0) and sshd bound to the Tailscale IP. Defence in depth behind the
# Hetzner firewall (risk S8). Run ON the VPS, over Tailscale:
#
#   scp -i ~/.ssh/ai_trader_vps scripts/harden-host.sh deploy@ai-trader-vps:/tmp/
#   ssh -i ~/.ssh/ai_trader_vps deploy@ai-trader-vps 'sudo bash /tmp/harden-host.sh'
#   # open a SECOND terminal, confirm `make ssh` still works, then in the first:
#   ssh -i ~/.ssh/ai_trader_vps deploy@ai-trader-vps 'sudo touch /run/harden-host.confirm'
#
# Anti-lockout: refuses to run unless you are connected over the tailnet, and
# schedules an automatic rollback in 5 minutes unless /run/harden-host.confirm
# exists. Re-running is safe (idempotent).
set -euo pipefail

ROLLBACK_SECS=300
DROPIN=/etc/ssh/sshd_config.d/20-listen-tailscale.conf
SYSCTL=/etc/sysctl.d/90-nonlocal-bind.conf
CONFIRM=/run/harden-host.confirm

[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }
command -v tailscale >/dev/null || { echo "tailscale not installed"; exit 1; }
command -v ufw >/dev/null || { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ufw; }

TS_IP="$(tailscale ip -4 | head -n1)"
[[ "$TS_IP" =~ ^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\. ]] || { echo "no valid Tailscale IPv4 (got '$TS_IP'); is Tailscale up?"; exit 1; }
ip link show tailscale0 >/dev/null 2>&1 || { echo "tailscale0 interface missing"; exit 1; }

# Refuse unless this very session arrived over the tailnet (not the public IP).
if [ -n "${SSH_CONNECTION:-}" ]; then
  SERVER_ADDR="$(awk '{print $3}' <<<"$SSH_CONNECTION")"
  [ "$SERVER_ADDR" = "$TS_IP" ] || { echo "connected via $SERVER_ADDR, not the Tailscale IP $TS_IP. Reconnect with: make ssh"; exit 1; }
else
  echo "SSH_CONNECTION unset (console?). Continuing; make sure you can reach $TS_IP afterwards."
fi

rm -f "$CONFIRM"

# 1) Rollback timer FIRST, so a mistake below still self-heals.
cat >/run/harden-host-rollback.sh <<RB
#!/bin/bash
[ -e $CONFIRM ] && exit 0
rm -f $DROPIN
ufw --force disable
systemctl restart ssh
logger -t harden-host "NOT confirmed: rolled back"
RB
chmod 700 /run/harden-host-rollback.sh
systemctl stop harden-host-rollback.timer 2>/dev/null || true
systemd-run --quiet --unit=harden-host-rollback --on-active="${ROLLBACK_SECS}s" /run/harden-host-rollback.sh

# 2) Let sshd bind the Tailscale IP even if it starts before tailscale0 is up.
echo 'net.ipv4.ip_nonlocal_bind = 1' >"$SYSCTL"
sysctl -q --system

# 3) ufw: tailscale0 allowed BEFORE enabling; no other inbound rules at all.
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0
ufw --force enable

# 4) sshd listens on the tailnet IP (+ loopback), nowhere else. Validate first.
printf 'ListenAddress %s\nListenAddress 127.0.0.1\n' "$TS_IP" >"$DROPIN"
if ! sshd -t; then rm -f "$DROPIN"; echo "sshd config invalid, reverted"; exit 1; fi
systemctl restart ssh   # existing sessions survive a restart

echo
echo "Applied. Listening sockets for sshd:"; ss -ltnp | grep -E ':22\b' || true
ufw status verbose
echo
echo "AUTO-ROLLBACK in ${ROLLBACK_SECS}s unless confirmed. In a NEW terminal run 'make ssh';"
echo "if it works: sudo touch $CONFIRM"
