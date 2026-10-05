#!/usr/bin/env python3
"""Probe what a Kraken API key can do, WITHOUT moving money or leaving an order behind.

Runs inside the Freqtrade container (ccxt is installed there; the key is in its environment as
FREQTRADE__EXCHANGE__KEY / SECRET, so it never touches a shell). Driven by
scripts/kraken-access-check.sh, which pipes this file to `python -`.

    python - --scope query-only   expect: balance + open-orders readable; add-order, deposit and
                                  withdraw all DENIED. (First test of access from the VPS IP.)
    python - --scope trade        expect: balance + open-orders readable; add-order ALLOWED
                                  (validate-only); deposit and withdraw DENIED. (The real key.)

How each permission is probed (every call is read-only or validate-only):
    Balance, OpenOrders        Query funds / Query open orders.
    AddOrder validate=true     Create orders. validate=true makes Kraken check the order and
                               discard it. The order is ALSO below Kraken's minimum cost, so even
                               if validate were ever dropped it could not be accepted or fill.
    DepositMethods             Funding: deposit. A listing only.
    WithdrawInfo               Funding: withdraw. A fee QUOTE only; this script never calls
                               Withdraw and cannot move funds. Anything other than
                               "permission denied" means the key HAS withdraw permission: the
                               check fails and the key must be deleted (NFR2, CLAUDE.md 0.2).

Exit 0 only when every outcome matches the scope. The key itself is never printed (a short
SHA-256 fingerprint is, so two runs can be compared).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from decimal import Decimal

ALLOWED, DENIED, UNKNOWN = "allowed", "denied", "unknown"

# What each scope must look like. A permission the key must NOT have is only ever "denied".
EXPECTED: dict[str, dict[str, str]] = {
    "query-only": {
        "balance": ALLOWED,
        "open_orders": ALLOWED,
        "add_order": DENIED,
        "deposit": DENIED,
        "withdraw": DENIED,
    },
    "trade": {
        "balance": ALLOWED,
        "open_orders": ALLOWED,
        "add_order": ALLOWED,
        "deposit": DENIED,
        "withdraw": DENIED,
    },
}
LABELS = {
    "balance": "Query funds (Balance)",
    "open_orders": "Query open orders",
    "add_order": "Create orders (validate-only)",
    "deposit": "Funding: deposit",
    "withdraw": "Funding: WITHDRAW",
}
# Orders for which a mistake would still be harmless: BTC at $1 for the minimum volume is
# 0.00005 USD, far below Kraken's 0.5 USD minimum cost.
PROBE_ORDER = {
    "pair": "XBTUSD",
    "type": "buy",
    "ordertype": "limit",
    "price": "1.0",
    "volume": "0.00005",
    "validate": True,
}


def max_probe_notional_usd() -> Decimal:
    return Decimal(PROBE_ORDER["price"]) * Decimal(PROBE_ORDER["volume"])  # type: ignore[arg-type]


def classify(exc: Exception | None) -> str:
    """Turn a call's outcome into allowed / denied / unknown.

    No error, or an error about the *request* (insufficient funds, minimum not met, unknown
    withdrawal key...) means the permission check passed: allowed. "Permission denied" is
    denied. Anything that says nothing about permissions (network, bad key/signature, rate
    limit, exchange down) is unknown: never read as either.
    """
    if exc is None:
        return ALLOWED
    text = f"{type(exc).__name__} {exc}".lower()
    if "permission denied" in text or "permissiondenied" in text:
        return DENIED
    unknown_markers = (
        "invalid key", "invalid signature", "invalid nonce", "authenticationerror",
        "network", "timeout", "timed out", "ratelimit", "rate limit", "ddos",
        "unavailable", "connection", "temporary", "internal error", "service:",
    )  # fmt: skip
    if any(m in text for m in unknown_markers):
        return UNKNOWN
    return ALLOWED


def evaluate(scope: str, outcomes: dict[str, str]) -> tuple[bool, list[str]]:
    """Compare outcomes with the scope. Returns (passed, report lines)."""
    if scope not in EXPECTED:
        raise ValueError(f"unknown scope {scope!r}")
    expected = EXPECTED[scope]
    lines: list[str] = []
    ok = True
    if outcomes.get("balance") != ALLOWED:
        lines.append(
            "FAIL: cannot read the balance (key invalid, wrong secret, or this host's IP is not "
            "whitelisted). Nothing else can be judged."
        )
        return False, lines
    for name, want in expected.items():
        got = outcomes.get(name, UNKNOWN)
        mark = "ok  " if got == want else "FAIL"
        lines.append(f"{mark} {LABELS[name]:32} got {got:8} expected {want}")
        if got != want:
            ok = False
            if name == "withdraw" and got != DENIED:
                lines.append(
                    "     !!! THE KEY CAN WITHDRAW (or this could not be verified). Delete it "
                    "on Kraken now and create a new one without Funding permissions."
                )
            elif name == "deposit" and got != DENIED:
                lines.append("     !!! The key has funding permission. Recreate it without any.")
            elif got == UNKNOWN:
                lines.append("     (could not be determined: retry; a network/auth error hides it)")
    return ok, lines


def call(fn, *args) -> str:  # noqa: ANN001
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001 - every failure is classified, none is swallowed
        return classify(exc)
    return classify(None)


def probe(exchange) -> dict[str, str]:  # noqa: ANN001
    return {
        "balance": call(exchange.privatePostBalance),
        "open_orders": call(exchange.privatePostOpenOrders),
        "add_order": call(exchange.privatePostAddOrder, dict(PROBE_ORDER)),
        "deposit": call(exchange.privatePostDepositMethods, {"asset": "ZUSD"}),
        "withdraw": call(
            exchange.privatePostWithdrawInfo,
            {"asset": "XXBT", "key": "access-probe-nonexistent", "amount": "0.0001"},
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scope", choices=sorted(EXPECTED), required=True)
    args = ap.parse_args()
    key = os.environ.get("FREQTRADE__EXCHANGE__KEY", "")
    secret = os.environ.get("FREQTRADE__EXCHANGE__SECRET", "")
    if not key or not secret:
        print("FAIL: FREQTRADE__EXCHANGE__KEY / SECRET are empty in this container")
        return 1
    import ccxt

    exchange = ccxt.kraken({"apiKey": key, "secret": secret, "enableRateLimit": True, "timeout": 20000})
    print(f"key fingerprint: {hashlib.sha256(key.encode()).hexdigest()[:12]}  scope: {args.scope}")
    ok, lines = evaluate(args.scope, probe(exchange))
    print("\n".join(lines))
    print(f"KRAKEN ACCESS CHECK {'PASS' if ok else 'FAIL'} ({args.scope})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
