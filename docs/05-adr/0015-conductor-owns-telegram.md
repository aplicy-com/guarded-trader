# ADR-0015: Conductor owns Telegram; Freqtrade's bot is disabled

## Status

Accepted — 2026-10-05 (work package 3A-4). Builds on
[`ADR-0014`](0014-conductor-write-surface-and-halt-state.md). Also records the
resolution of R4 AC4.2 (drawdown halts, never auto-flattens; see ADR-0014 item 6).

## Context and problem statement

Freqtrade's own Telegram bot (enabled in 2D for status) registers about 35
commands, including `/forceexit`, `/stop`, `/stopentry`, `/reload_config` and
`/delete`. Freqtrade 2026.8 has no per-command permission system: whoever can
message that bot as the configured chat can run all of them (verified against
its source in 2D). Conductor needs a control surface with an allowlist,
confirmation of destructive actions, and alerts that come from the ledger.

## Decision outcome

1. **Conductor owns the bot; Freqtrade's is disabled** (`telegram.enabled:
   false`). The existing bot and token are reused, but only Conductor polls with
   them. The compose file blanks every Telegram variable for the freqtrade
   container, so the token reaches the conductor container only. (One token can
   be polled by one process; two would get `409 Conflict`.)
2. **Long polling, outbound HTTPS only.** No webhook, no listening socket, so the
   no-inbound-ports posture (ADR-0011) is unchanged. Updates that arrived while
   Conductor was down are discarded on start: a stale `yes <code>` or command is
   never acted on later.
3. **Allowlist**: only `TELEGRAM_ALLOWED_CHAT_IDS`. Others get no reply (the bot
   does not reveal itself) and are logged by chat ID, never by message text.
   Conductor refuses to start with a token and no allowlist, or the reverse.
4. **Confirmed writes**: `/kill`, `/flatten`, `/resume` ask first; the same chat
   must answer `yes <random 4-char code>` within 60 s. One attempt per code; the
   chat ID is the operator identity in the ledger. Nothing can open or size a
   trade. Command logic is library-free (`application/telegram_commands.py`); the
   adapter only authenticates and delivers.
5. **Alerts are best effort and off the risk path.** They are queued and sent by
   a separate thread with dedupe (5 min) and a rate cap (10/min); every failure
   is logged and dropped. Risk checks, halts and enforcement never wait on, or
   fail because of, Telegram. Trade alerts derive from ledger transitions, so
   restarts and re-ingests never repeat them.
6. **Library: python-telegram-bot 22.8** (not aiogram). Reasons: it is built on
   `httpx`, which Conductor already depends on, so it adds exactly one new
   package (aiogram would add aiohttp and several more, a second HTTP stack in a
   small trading service); its `BaseRequest` seam let the tests drive the real
   bot through a fake Telegram transport; it is the most widely used and
   maintained option for a long-polling bot with a handful of commands, which is
   all this needs. The cost is its async API: it runs in its own thread and event
   loop while the rest of Conductor stays synchronous, and blocking use cases run
   via `asyncio.to_thread`.
7. **The token is a secret in a URL.** Telegram puts it in the request path, and
   libraries echo URLs. Logging redacts `bot<id>:<secret>` everywhere (structlog and
   stdlib), httpx/httpcore request logging is silenced, and error handling logs
   exception types only.

## Consequences

- `/resume` is the sensitive command (it re-enables trading). Its protection is the
  allowlist plus confirmation; a still-true breach re-halts within a minute.
  A compromised token or allow-listed account could resume or kill/flatten.
- Operator identity is the Telegram chat ID (trusted by allowlist), not a
  cryptographic signature.
- Freqtrade's own notifications are gone; the equivalents (trade opened/closed,
  halts, fence, unreachable) come from Conductor.
- `/approve <strategy-id>` (ADR-0007) is deferred to Phase 3B with the promotion engine.
