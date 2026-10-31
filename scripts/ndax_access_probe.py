#!/usr/bin/env python3
"""Probe what an NDAX API key can do, with NO login or password, WITHOUT moving money or
sending an order. Spike only (spike/ndax, docs/research/06-ndax-feasibility.md).

Runs inside a throw-away Freqtrade container (ccxt is installed there; the key is in its
environment as NDAX_API_KEY / NDAX_API_SECRET / NDAX_UID, so it never touches a shell). Driven
by scripts/ndax-access-check.sh, which pipes this file to `python -`.

    python - --scope read-only    expect: balance + open orders readable; the order-fee and
                                  withdraw-fee quotes both explicitly DENIED ("Not Authorized").

No login. ccxt.ndax lists `login` and `password` as required credentials, but its private calls
are HMAC-signed with uid + API key + secret; `login` is only used by fetch_accounts (as UserName
on GetUserAccounts). This probe switches both requirements off and hands ccxt the numeric
account id up front (`accounts` + options.accountId), so fetch_accounts is never called. The id
comes from NDAX_ACCOUNT_ID if set, else from a key-signed GetUserAccounts with UserId only.

Every probe is a documented read or quote (https://apidoc.ndax.io/, names exactly as there):
    ccxt fetch_balance        The Freqtrade path with the account id pre-set: GetAccountPositions.
    GetAccountPositions       balance       (Operator, Trading, AccountReadOnly)
    GetOpenOrders             open orders   (Operator, Trading, AccountReadOnly)
    GetOrderFee               orders        (Operator, Trading). A fee QUOTE; SendOrder is never
                              called (NDAX has no validate-only order).
    GetWithdrawFee            WITHDRAW      (Operator, Trading, Withdraw). A fee QUOTE only; no
                              withdraw ticket is ever created.
    GetUserPermissions        informational: NOT in apidoc.ndax.io. Takes a UserId, so it reports
                              the user's permissions, not the key's.
Deposit is not probed: no documented read call is gated by the Deposit permission alone.

Outcomes are fail-closed. "allowed" = the call succeeded. "denied" = NDAX explicitly said
Not Authorized (errorcode 20) or HTTP 401/403. Anything else (404 "NOT FOUND", a parameter
error, a network error) = "unknown", which never counts as either. Note NDAX's HTTP gateway
answers 404 "NOT FOUND" to unauthenticated private calls and to unknown names alike, so a 404
proves nothing about a permission.

Exit 0 only when every outcome matches the scope. The key is never printed (a short SHA-256
fingerprint is, so two runs can be compared).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

ALLOWED, DENIED, UNKNOWN = "allowed", "denied", "unknown"

EXPECTED: dict[str, dict[str, str]] = {
    "read-only": {
        "ccxt_balance": ALLOWED,
        "balance": ALLOWED,
        "open_orders": ALLOWED,
        "order": DENIED,
        "withdraw": DENIED,
    },
}
LABELS = {
    "ccxt_balance": "ccxt fetch_balance, no login",
    "balance": "Balance (GetAccountPositions)",
    "open_orders": "Open orders (GetOpenOrders)",
    "order": "Orders (GetOrderFee quote)",
    "withdraw": "WITHDRAW (GetWithdrawFee quote)",
}
OMS_ID = 1
PROBE_INSTRUMENT_ID = 1  # BTCCAD on OMS 1 (public GetInstruments)
PROBE_PRODUCT_ID = 1  # BTC on OMS 1 (public GetProducts)


def is_error_envelope(response: object) -> bool:
    """AlphaPoint's failure shape: {"result": false, "errormsg": ..., "errorcode": n}."""
    if not isinstance(response, dict):
        return False
    return response.get("result") is False or bool(response.get("errormsg"))


def classify(exc: Exception | None, status: int | None = None, response: object = None) -> str:
    """Turn a call's outcome into allowed / denied / unknown. Fail-closed both ways:
    only a clean success is "allowed", only an explicit refusal is "denied"."""
    if status in (401, 403):
        return DENIED
    text = f"{type(exc).__name__} {exc}".lower() if exc is not None else ""
    if is_error_envelope(response):
        text += f" {response}".lower()
    if not text:
        return ALLOWED if status is None or 200 <= status < 300 else UNKNOWN
    if status == 404:
        return UNKNOWN  # NDAX's answer to unauthenticated calls and unknown names alike
    if any(m in text for m in ("not authorized", "not_authorized")):
        return DENIED
    return UNKNOWN


def evaluate(
    scope: str, outcomes: dict[str, str], permissions: object = None
) -> tuple[bool, list[str]]:
    """Compare outcomes with the scope. Returns (passed, report lines)."""
    if scope not in EXPECTED:
        raise ValueError(f"unknown scope {scope!r}")
    lines: list[str] = []
    if outcomes.get("balance") != ALLOWED:
        lines.append(
            "FAIL: cannot read the balance with a key-signed call (account id wrong, key, "
            "secret or user id wrong, key disabled, or this host's IP refused). Nothing else can "
            "be judged."
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
                "     !!! THE KEY CAN WITHDRAW, or this could not be verified. Delete it on NDAX "
                "now. Do not use NDAX live unless a re-run shows an explicit Not Authorized."
            )
        elif name == "order":
            lines.append(
                "     !!! The key has trading permission, or this could not be verified; this "
                "scope is read-only."
            )
        elif name == "ccxt_balance":
            lines.append(
                "     ccxt refused even with the account id pre-set (see the error above); the "
                "direct signed call works, so ccxt/Freqtrade config is the gap."
            )
        else:
            lines.append("     (not a clean success: see the error above)")
    if "withdraw" in str(permissions).lower():
        lines.append(
            "note GetUserPermissions lists Withdraw. It is per user, so it cannot show the key's "
            "scope; only an explicit Not Authorized on GetWithdrawFee does."
        )
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
    status = recorder.status if recorder else None
    outcome = classify(None, status, response)
    if outcome != ALLOWED:
        errors[name] = f"HTTP {status}: {str(response)[:200]}"
    return outcome, response


def parse_account_ids(response: object) -> list[int]:
    """GetUserAccounts answers a JSON list of integer account ids, e.g. [449]."""
    if not isinstance(response, list):
        return []
    ids: list[int] = []
    for item in response:
        if isinstance(item, bool):
            return []
        try:
            value = int(item)
        except (TypeError, ValueError):
            return []
        if value <= 0 or str(value) != str(item).strip():
            return []
        ids.append(value)
    return ids


def resolve_account_id(exchange, uid: str, configured: str, recorder, errors) -> int | None:
    """NDAX_ACCOUNT_ID if set, else the single id a key-signed GetUserAccounts returns."""
    if configured:
        return int(configured) if configured.isdigit() and int(configured) > 0 else None
    _, resp = call(
        recorder, errors, "accounts", exchange.privateGetGetUserAccounts,
        {"OMSId": OMS_ID, "UserId": uid},
    )  # fmt: skip
    ids = parse_account_ids(resp)
    if len(ids) != 1:
        errors.setdefault(
            "accounts", f"need exactly one account id, got {ids or resp!r}: set NDAX_ACCOUNT_ID"
        )
        return None
    return ids[0]


def preset_account(exchange, account_id: int) -> None:
    """Give ccxt the account id so it never calls fetch_accounts (the only login-using call)."""
    exchange.accounts = [{"id": str(account_id), "type": None, "currency": None, "info": None}]
    exchange.options["accountId"] = account_id
    exchange.options["omsId"] = OMS_ID


def probe(
    exchange, uid: str, configured_account: str = "", recorder: Recorder | None = None
) -> tuple[dict[str, str], dict[str, str], object, int | None]:
    """Returns (outcomes, errors, permissions-or-None, account id). Every call is a read or a
    quote."""
    out: dict[str, str] = {}
    err: dict[str, str] = {}
    acct = resolve_account_id(exchange, uid, configured_account, recorder, err)
    if acct is None:
        out["balance"] = UNKNOWN
        err.setdefault(
            "balance", "no valid account id (NDAX_ACCOUNT_ID must be a positive integer)"
        )
        return out, err, None, None
    preset_account(exchange, acct)
    base = {"OMSId": OMS_ID, "AccountId": acct}
    out["ccxt_balance"], _ = call(recorder, err, "ccxt_balance", exchange.fetch_balance)
    out["balance"], _ = call(
        recorder, err, "balance", exchange.privateGetGetAccountPositions, dict(base)
    )
    out["open_orders"], _ = call(
        recorder, err, "open_orders", exchange.privateGetGetOpenOrders, dict(base)
    )
    out["order"], _ = call(
        recorder, err, "order", exchange.privateGetGetOrderFee,
        {**base, "InstrumentId": PROBE_INSTRUMENT_ID, "ProductId": PROBE_PRODUCT_ID,
         "Amount": 0.0001, "Price": 1, "OrderType": 2, "MakerTaker": 2, "Side": 0},
    )  # fmt: skip
    out["withdraw"], _ = call(
        recorder, err, "withdraw", exchange.privateGetGetWithdrawFee,
        {**base, "ProductId": PROBE_PRODUCT_ID, "Amount": 0.0001},
    )  # fmt: skip
    _, perms = call(
        recorder, err, "permissions_info", exchange.request, "GetUserPermissions", "private", "GET",
        {"UserId": uid},
    )  # fmt: skip
    return out, err, perms, acct


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scope", choices=sorted(EXPECTED), required=True)
    args = ap.parse_args()
    key = os.environ.get("NDAX_API_KEY", "")
    secret = os.environ.get("NDAX_API_SECRET", "")
    uid = os.environ.get("NDAX_UID", "")
    configured_account = os.environ.get("NDAX_ACCOUNT_ID", "").strip()
    if not key or not secret or not uid:
        print("FAIL: NDAX_API_KEY / NDAX_API_SECRET / NDAX_UID are empty in this container")
        return 1
    import ccxt

    exchange = ccxt.ndax(
        {
            "apiKey": key, "secret": secret, "uid": uid,
            "requiredCredentials": {"login": False, "password": False},
            "enableRateLimit": True, "timeout": 20000,
        }
    )  # fmt: skip
    fingerprint = hashlib.sha256(key.encode()).hexdigest()[:12]
    print(f"ccxt {ccxt.__version__}  key fingerprint: {fingerprint}  scope: {args.scope}")
    outcomes, errors, perms, acct = probe(exchange, uid, configured_account, Recorder(exchange))
    source = "NDAX_ACCOUNT_ID" if configured_account else "GetUserAccounts (key-signed)"
    print(f"  account id: {acct if acct is not None else 'none'}  from {source}")
    for name, text in errors.items():
        print(f"  [{name}] {text.replace(key, '<key>').replace(secret, '<secret>')}")
    if perms is not None:
        print(f"  GetUserPermissions (informational, per user): {perms}")
    else:
        print("  GetUserPermissions (informational): no answer")
    ok, lines = evaluate(args.scope, outcomes, perms)
    print("\n".join(lines))
    print(f"NDAX ACCESS CHECK {'PASS' if ok else 'FAIL'} ({args.scope})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
