# ADR-0017: Read-only dashboard, reachable only over Tailscale

## Status

Accepted — 2026-10-05 (work package 3A-5). Builds on
[`ADR-0011`](0011-vps-hosting-on-hetzner.md) (no public inbound ports; Tailscale
access) and [`ADR-0015`](0015-conductor-owns-telegram.md) (Telegram is the control
surface).

## Context and problem statement

Telegram answers "what is happening right now" well but is poor at history (equity
curve, trades, halts, audit log). The operator wants a page to look at from a phone
or laptop. A web UI is also the easiest way to add a write surface to a trading
system by accident, and the VPS has deliberately no public inbound ports.

## Decision outcome

1. **Strictly read-only.** Every dashboard route is a `GET`; the templates contain no
   form, input, button or `hx-post/put/patch/delete`; tests fail if that changes. All
   writes (kill, flatten, resume, approvals) stay on Telegram behind a confirmation
   code. The dashboard reads the ledger through read-only transactions.
2. **Stack: FastAPI + Jinja + HTMX, Chart.js vendored.** No JavaScript build step, no
   SPA, no CDN at runtime: `htmx.min.js` and `chart.umd.min.js` are checked in with
   their versions and hashes (`static/VENDORED.md`). Pages refresh their tables with
   HTMX `GET` polling every 30 s. A strict CSP (`default-src 'none'`,
   `script-src 'self'`, no inline script or style, `frame-ancestors 'none'`) is set on
   every response.
3. **The network is the authentication.** There is no login. The conductor container
   publishes `127.0.0.1:8000` on the host and `tailscale serve --bg --https=443
   http://127.0.0.1:8000` exposes it with a Tailscale-issued HTTPS certificate to the
   tailnet only (`tailscale funnel`, which is public, is never used). Tailnet ACLs
   limit which devices reach the VPS.
4. **Docker cannot expose it publicly**, by three independent layers, none of which
   is ufw (Docker's published ports bypass ufw's INPUT rules, so ufw is not relied on
   for container ports):
   - the compose file binds `127.0.0.1:8000`; Docker's DNAT rule matches only that
     destination address, so traffic aimed at the public IP is not forwarded to the
     container (`tests/test_compose.py` fails on any non-loopback publish);
   - the **Hetzner Cloud Firewall has zero inbound rules** and sits outside the host,
     so the packet is dropped before the host's iptables, including Docker's, ever
     sees it. This is the control that makes the bypass irrelevant, and the one the
     external `nmap` scan verifies;
   - `tailscale serve` listens on the tailnet interface only.

   A loopback publish has itself been reachable from other hosts on the same L2
   segment on some Docker versions (the `route_localnet` issue). The Cloud Firewall,
   not the loopback bind alone, is what rules that out.

## Alternatives considered

- **Bind the port to the VPS's Tailscale IP in compose.** No HTTPS, and the address is
  not known when Docker starts at boot (race with `tailscaled`). Rejected.
- **A reverse proxy (Caddy/nginx) with its own auth.** More software, more secrets,
  more attack surface than `tailscale serve`, for a single-user tool. Rejected.
- **SPA (React/Vue).** Needs a build toolchain and an npm dependency tree in a
  money-adjacent service; the pages are tables and one chart. Rejected.
- **Make it writable.** Rejected: a browser session is a weaker confirmation channel
  than Telegram's chat-ID allowlist plus one-time code, and nothing here needs it.

## Consequences

- Anyone on the tailnet who is allowed to reach port 443 on the VPS can read P&L,
  positions and the audit log. The tailnet ACL (security.md, operator action) is what
  narrows that; the app itself has no per-user control.
- A compromised container or other process on the VPS can still reach
  `127.0.0.1:8000`; the VPS's own trust boundary (`deploy` is root-equivalent) is
  unchanged.
- `/health` and `/capital` are served on the same port and are read-only too.
- One-time operator steps: enable HTTPS certificates for the tailnet and run
  `tailscale serve` on the VPS (cloud-init attempts it on first boot, but the
  already-running VPS and a fresh tailnet need it by hand,
  [`provision-vps.md`](../06-runbooks/provision-vps.md) step 24).
