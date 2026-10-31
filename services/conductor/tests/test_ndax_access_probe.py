"""scripts/ndax_access_probe.py (spike/ndax): classification, scope judgement, and the
guarantee that it only ever reads or quotes."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "scripts" / "ndax_access_probe.py"


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ndax_access_probe", SOURCE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ndax_access_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


class Boom(Exception):
    pass


def test_classify(probe: ModuleType) -> None:
    assert probe.classify(None) == "allowed"
    assert probe.classify(None, 200, [{"ProductId": 1}]) == "allowed"
    assert (
        probe.classify(Boom('ndax {"result":false,"errormsg":"Not Authorized","errorcode":20}'))
        == "denied"
    )
    assert probe.classify(None, 401) == "denied" and probe.classify(Boom("x"), 403) == "denied"
    assert probe.classify(None, 200, {"result": False, "errormsg": "Not Authorized"}) == "denied"


@pytest.mark.parametrize(
    ("exc", "status", "response"),
    [
        # the VPS run: a request error is NOT a success, whatever the permission check did
        (Boom('ndax {"errormsg":"OMSId and AccountId must be Integers"}'), 200, None),
        (None, 200, {"result": False, "errormsg": "OMSId and AccountId must be Integers"}),
        (None, 200, {"result": False, "errormsg": "", "errorcode": 101}),
        (Boom('ndax {"errormsg":"Not_Enough_Funds"}'), 200, None),
        (Boom('ndax {"errormsg":"Invalid Request","errorcode":100}'), 200, None),
        # NDAX answers 404 NOT FOUND to unauthenticated calls and unknown names alike
        (Boom("AuthenticationError ndax NOT FOUND"), 404, None),
        (None, 500, None),
        (Boom("timed out"), None, None),
        (Boom('ndax {"errormsg":"Server Error"}'), None, None),
        (Boom("RateLimitExceeded"), None, None),
    ],
)
def test_anything_but_success_or_explicit_refusal_is_unknown(
    probe: ModuleType, exc: Exception | None, status: int | None, response: object
) -> None:
    assert probe.classify(exc, status, response) == "unknown"


def test_parse_account_ids(probe: ModuleType) -> None:
    assert probe.parse_account_ids([449]) == [449]
    assert probe.parse_account_ids([449, 450]) == [449, 450]
    for bad in ({"result": False}, None, "449", [True], ["x"], [0], [-1], [4.5]):
        assert probe.parse_account_ids(bad) == [], bad


GOOD = {
    "ccxt_balance": "allowed", "balance": "allowed", "open_orders": "allowed",
    "order": "denied", "withdraw": "denied",
}  # fmt: skip


def test_a_read_only_key_that_works_without_login_passes(probe: ModuleType) -> None:
    assert probe.evaluate("read-only", GOOD)[0] is True


def test_ccxt_path_refused_fails_but_says_the_key_works(probe: ModuleType) -> None:
    ok, lines = probe.evaluate("read-only", {**GOOD, "ccxt_balance": "unknown"})
    assert ok is False and any("account id pre-set" in line for line in lines)


@pytest.mark.parametrize("name", ["balance", "open_orders"])
def test_unreadable_reads_fail(probe: ModuleType, name: str) -> None:
    assert probe.evaluate("read-only", {**GOOD, name: "unknown"})[0] is False


def test_user_permissions_listing_withdraw_is_flagged_not_trusted(probe: ModuleType) -> None:
    ok, lines = probe.evaluate("read-only", GOOD, ["Deposit", "Trading", "Withdraw"])
    assert ok is True and any("cannot show the key" in line for line in lines)
    assert probe.evaluate("read-only", {**GOOD, "withdraw": "unknown"}, ["Withdraw"])[0] is False


@pytest.mark.parametrize("perm", ["withdraw", "order"])
@pytest.mark.parametrize("got", ["allowed", "unknown"])
def test_any_extra_permission_or_unverifiable_one_fails_loudly(
    probe: ModuleType, perm: str, got: str
) -> None:
    ok, lines = probe.evaluate("read-only", {**GOOD, perm: got})
    assert ok is False and any("!!!" in line for line in lines)
    if perm == "withdraw":
        assert any("CAN WITHDRAW" in line and "Delete it" in line for line in lines)


def test_unreadable_balance_fails_before_judging_anything(probe: ModuleType) -> None:
    ok, lines = probe.evaluate("read-only", {**GOOD, "balance": "denied"})
    assert ok is False and len(lines) == 1
    assert probe.evaluate("read-only", {})[0] is False


class Spy:
    """Stands in for ccxt.ndax: records every call, answers GetUserAccounts with [449]."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.accounts: object = None
        self.options: dict = {}

    def __getattr__(self, name: str):
        def call(*a: object) -> object:
            label = a[0] if name == "request" else name
            self.calls.append((label, a[-1] if a else None))  # type: ignore[arg-type]
            return [449] if name == "privateGetGetUserAccounts" else []

        return call


def test_the_probe_only_reads_or_quotes(probe: ModuleType) -> None:
    spy = Spy()
    outcomes, _, _, acct = probe.probe(spy, "96")
    assert [c[0] for c in spy.calls] == [
        "privateGetGetUserAccounts",
        "fetch_balance",
        "privateGetGetAccountPositions",
        "privateGetGetOpenOrders",
        "privateGetGetOrderFee",
        "privateGetGetWithdrawFee",
        "GetUserPermissions",
    ]
    assert acct == 449 and outcomes["balance"] == "allowed"
    code = SOURCE.read_text().split('"""', 2)[2]  # the module docstring may name what it avoids
    for forbidden in (
        "SendOrder", "CreateWithdrawTicket", "CreateDepositTicket", "Cancel", "ModifyOrder",
        "sign_in", "signIn", ".withdraw(", "create_order", "Authenticate",
    ):  # fmt: skip
        assert forbidden not in code, forbidden


def test_account_id_is_preset_so_ccxt_never_needs_a_login(probe: ModuleType) -> None:
    spy = Spy()
    probe.probe(spy, "96")
    assert spy.accounts == [{"id": "449", "type": None, "currency": None, "info": None}]
    assert spy.options == {"accountId": 449, "omsId": 1}
    assert "fetch_accounts" not in [c[0] for c in spy.calls]
    sent = dict(spy.calls)
    # exactly the documented key casing, once each: no omsId + OMSId duplicate
    assert sent["privateGetGetAccountPositions"] == {"OMSId": 1, "AccountId": 449}
    assert sent["privateGetGetUserAccounts"] == {"OMSId": 1, "UserId": "96"}
    assert "UserName" not in str(spy.calls)


def test_configured_account_id_skips_the_lookup_and_bad_ones_stop(probe: ModuleType) -> None:
    spy = Spy()
    _, _, _, acct = probe.probe(spy, "96", "512")
    assert acct == 512 and "privateGetGetUserAccounts" not in [c[0] for c in spy.calls]
    for bad in ("abc", "0", "-3", "4.5"):
        spy = Spy()
        outcomes, _, _, acct = probe.probe(spy, "96", bad)
        assert acct is None and spy.calls == [] and outcomes["balance"] == "unknown"


class TwoAccountsSpy(Spy):
    def __getattr__(self, name: str):
        if name == "privateGetGetUserAccounts":
            return lambda *a: [449, 450]
        return super().__getattr__(name)


def test_several_accounts_without_a_configured_id_stop(probe: ModuleType) -> None:
    _, errors, _, acct = probe.probe(TwoAccountsSpy(), "96")
    assert acct is None and "NDAX_ACCOUNT_ID" in errors["accounts"]


def test_no_login_or_password_is_used_or_read(probe: ModuleType) -> None:
    source = SOURCE.read_text()
    assert "NDAX_PASSWORD" not in source and "NDAX_LOGIN" not in source
    assert '"login": False, "password": False' in source
    assert "DUMMY" not in source and '"login": "' not in source
