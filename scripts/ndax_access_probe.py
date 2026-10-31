#!/usr/bin/env python3
"""Probe what an NDAX API key can do, with DUMMY login/password, WITHOUT moving money or
sending an order. Spike only (spike/ndax, docs/research/06-ndax-feasibility.md).

Runs inside a throw-away Freqtrade container (ccxt is installed there; the key is in its
environment as NDAX_API_KEY / NDAX_API_SECRET / NDAX_UID, so it never touches a shell). Driven
by scripts/ndax-access-check.sh, which pipes this file to `python -`.

    python - --scope read-only    expect: balance + open-orders readable; order (fee quote),
                                  deposit and withdraw lookups all DENIED.

The question: ccxt.ndax lists `login` and `password` as required credentials and checks them
before every private call, although private calls are signed with uid + API key + secret
(HMAC). This probe gives ccxt obviously fake values (DUMMY_LOGIN / DUMMY_PASSWORD) and never
calls signIn / Authenticate, so the fake password is never even sent. The real NDAX password is
never read, asked for, or stored.

How each permission is probed. NDAX documents the permission each call needs
(https://apidoc.ndax.io/), so every probe is a read or a quote; nothing is created:
    ccxt fetch_balance        The real Freqtrade path: GetUserAccounts (sends the dummy login as
                              UserName) then GetAccountPositions. Answers "do dummies work?".
    GetUserAccounts           Same call without UserName, to find the account id if the ccxt
                              path fails only because of the dummy login.
    GetAccountPositions       balance       (Operator, Trading, AccountReadOnly)
    GetOpenOrders             open orders   (Operator, Trading, AccountReadOnly)
    GetOrderFee               orders        (Operator, Trading). A fee QUOTE, no order. NDAX has
                              no validate-only SendOrder, so SendOrder is never called.
    GetDepositInfo            deposit       an address lookup, GenerateNewKey=false.
    GetWithdrawFee            WITHDRAW      (Operator, Trading, Withdraw). A fee QUOTE only;
                              this script never creates a withdraw ticket. Anything other than
                              "denied" means the key may withdraw: the check fails and the key
                              must be deleted (NFR2, CLAUDE.md 0.2).
    GetUserPermissions        informational: undocumented in NDAX's docs; prints the permission
                              names if NDAX answers. Never judged.

Exit 0 only when every outcome matches the scope. The key is never printed (a short SHA-256
fingerprint is, so two runs can be compared).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

ALLOWED, DENIED, UNKNOWN = "allowed", "denied", "unknown"

# Fake values for ccxt's login/password credential check. Deliberately not an e-mail address and
# not anything a person would use as a password.
DUMMY_LOGIN = "dummy-login-not-used"
DUMMY_PASSWORD = "dummy-password-not-used"  # noqa: S105 - a placeholder, not a secret

EXPECTED: dict[str, dict[str, str]] = {
    "read-only": {
        "ccxt_balance": ALLOWED,
        "balance": ALLOWED,
        "open_orders": ALLOWED,
        "order": DENIED,
        "deposit": DENIED,
        "withdraw": DENIED,
    },
}
LABELS = {
    "ccxt_balance": "ccxt fetch_balance, dummy login/pw",
    "balance": "Balance (GetAccountPositions)",
    "open_orders": "Open orders (GetOpenOrders)",
    "order": "Orders (GetOrderFee quote)",
    "deposit": "Deposit (GetDepositInfo)",
    "withdraw": "WITHDRAW (GetWithdrawFee quote)",
}
OMS_ID = 1
PROBE_PRODUCT_ID = 1  # BTC on NDAX's OMS 1 (ccxt docs); any real product id works for a lookup


def classify(exc: Exception | None, status: int | None = None) -> str:
    """Turn a call's outcome into allowed / denied / unknown.

    NDAX (AlphaPoint) answers a missing permission with "Not Authorized" (errorcode 20) or an
    HTTP 401/403. That is also its answer to a bad key, so "denied" only means something once
    the balance read has proved the key works: evaluate() enforces that. An error about the
    *request* (bad parameter, not enough funds) means the permission check passed: allowed.
    404 (ccxt turns it into AuthenticationError), network, rate limit or server errors say
    nothing about permissions: unknown, never read as either.
    """
    if status == 404:
        return UNKNOWN
    if status in (401, 403):
        return DENIED
    if exc is None:
        return ALLOWED
    text = f"{type(exc).__name__} {exc}".lower()
    denied_markers = ("not authorized", "not_authorized", "unauthorized", "permission", "forbidden")
    if any(m in text for m in denied_markers):
        return DENIED
    unknown_markers = (
        "network", "timeout", "timed out", "ratelimit", "rate limit", "ddos", "unavailable",
        "connection", "temporary", "server error", "requires exchange.", "authenticationerror",
    )  # fmt: skip
    if any(m in text for m in unknown_markers):
        return UNKNOWN
    return ALLOWED


def evaluate(scope: str, outcomes: dict[str, str]) -> tuple[bool, list[str]]:
    """Compare outcomes with the scope. Returns (passed, report lines)."""
    if scope not in EXPECTED:
        raise ValueError(f"unknown scope {scope!r}")
    lines: list[str] = []
    if outcomes.get("balance") != ALLOWED:
        lines.append(
            "FAIL: cannot read the balance even with a direct signed call (key, secret or "
            "user id wrong, key disabled, or this host's IP refused). Nothing else can be judged."
        )
        return False, lines
    ok = True
    for name, want in EXPECTED[scope].items():
        got = outcomes.get(name, UNKNOWN)
        mark = "ok  " if got == want else "FAIL"
        lines.append(f"{mark} {LABELS[name]:36} got {got:8} expected {want}")
        if got == want:
            continue
        ok = False
        if name == "withdraw":
            lines.append(
                "     !!! THE KEY CAN WITHDRAW (or this could not be verified). Delete it on "
                "NDAX now and create a new one with withdraw permission OFF."
            )
        elif name == "deposit":
            lines.append("     !!! The key has deposit permission. Recreate it as read-only.")
        elif name == "order":
            lines.append("     !!! The key has trading permission; this scope is read-only.")
        elif name == "ccxt_balance":
            lines.append(
                "     ccxt's own path refused the dummy login/password (see the error above). "
                "The key itself works; ccxt/Freqtrade would need a patch to skip them."
            )
        elif got == UNKNOWN:
            lines.append("     (could not be determined: retry; a network/server error hides it)")
    return ok, lines


class Recorder:
    """Remembers the HTTP status of the last response (ccxt hides it in the exception)."""

    def __init__(self, exchange) -> None:
        self.status: int | None = None
        original = exchange.handle_errors

        def handle_errors(code, *rest):
            self.status = code
            return original(code, *rest)

        exchange.handle_errors = handle_errors


def call(recorder: Recorder | None, errors: dict[str, str], name: str, fn, *args):
    """Run one probe call. Returns (outcome, response). Errors are kept, short, for the report."""
    if recorder is not None:
        recorder.status = None
    try:
        response = fn(*args)
    except Exception as exc:
        errors[name] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return classify(exc, recorder.status if recorder else None), None
    return classify(None, recorder.status if recorder else None), response


def account_id_from(response: object) -> int | None:
    try:
        return int(response[0])  # type: ignore[index]
    except (TypeError, ValueError, IndexError, KeyError):
        return None


def probe(
    exchange, uid: str, recorder: Recorder | None = None
) -> tuple[dict[str, str], dict[str, str], object]:
    """Returns (outcomes, errors, permissions-or-None). Every call is a read or a quote."""
    out: dict[str, str] = {}
    err: dict[str, str] = {}
    out["ccxt_balance"], _ = call(recorder, err, "ccxt_balance", exchange.fetch_balance)
    accounts = getattr(exchange, "accounts", None) or []
    acct = account_id_from([a.get("id") for a in accounts if isinstance(a, dict)])
    if acct is None:
        _, resp = call(
            recorder, err, "accounts", exchange.privateGetGetUserAccounts,
            {"omsId": OMS_ID, "UserId": uid},
        )  # fmt: skip
        acct = account_id_from(resp)
    if acct is None:
        out["balance"] = UNKNOWN
        err.setdefault("balance", "no account id: GetUserAccounts did not answer")
        return out, err, None
    base = {"omsId": OMS_ID, "OMSId": OMS_ID, "AccountId": acct}
    out["balance"], _ = call(
        recorder, err, "balance", exchange.privateGetGetAccountPositions, dict(base)
    )
    out["open_orders"], _ = call(
        recorder, err, "open_orders", exchange.privateGetGetOpenOrders, dict(base)
    )
    out["order"], _ = call(
        recorder, err, "order", exchange.privateGetGetOrderFee,
        {**base, "InstrumentId": 1, "Quantity": 0.0001, "Price": 1, "OrderType": 2,
         "MakerTaker": "Taker", "Side": 0},
    )  # fmt: skip
    out["deposit"], _ = call(
        recorder, err, "deposit", exchange.privateGetGetDepositInfo,
        {**base, "ProductId": PROBE_PRODUCT_ID, "GenerateNewKey": False},
    )  # fmt: skip
    out["withdraw"], _ = call(
        recorder, err, "withdraw", exchange.privateGetGetWithdrawFee,
        {**base, "ProductId": PROBE_PRODUCT_ID, "Amount": 0.0001},
    )  # fmt: skip
    _, perms = call(
        recorder, err, "permissions_info", exchange.request, "GetUserPermissions", "private", "GET",
        {"UserId": uid},
    )  # fmt: skip
    return out, err, perms


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scope", choices=sorted(EXPECTED), required=True)
    args = ap.parse_args()
    key = os.environ.get("NDAX_API_KEY", "")
    secret = os.environ.get("NDAX_API_SECRET", "")
    uid = os.environ.get("NDAX_UID", "")
    if not key or not secret or not uid:
        print("FAIL: NDAX_API_KEY / NDAX_API_SECRET / NDAX_UID are empty in this container")
        return 1
    import ccxt

    exchange = ccxt.ndax(
        {
            "apiKey": key, "secret": secret, "uid": uid,
            "login": DUMMY_LOGIN, "password": DUMMY_PASSWORD,
            "enableRateLimit": True, "timeout": 20000,
        }
    )  # fmt: skip
    fingerprint = hashlib.sha256(key.encode()).hexdigest()[:12]
    print(f"ccxt {ccxt.__version__}  key fingerprint: {fingerprint}  scope: {args.scope}")
    outcomes, errors, perms = probe(exchange, uid, Recorder(exchange))
    for name, text in errors.items():
        print(f"  [{name}] {text.replace(key, '<key>').replace(secret, '<secret>')}")
    if perms is not None:
        print(f"  GetUserPermissions (informational): {perms}")
    else:
        print(
            "  GetUserPermissions (informational): no answer (endpoint not available to this key)"
        )
    ok, lines = evaluate(args.scope, outcomes)
    print("\n".join(lines))
    print(f"NDAX ACCESS CHECK {'PASS' if ok else 'FAIL'} ({args.scope})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
