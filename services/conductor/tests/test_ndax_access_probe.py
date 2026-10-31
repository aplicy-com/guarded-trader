"""scripts/ndax_access_probe.py (spike/ndax): classification, scope judgement, and the
guarantee that it only ever reads or quotes."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import ClassVar

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
    assert (
        probe.classify(Boom('ndax {"result":false,"errormsg":"Not Authorized","errorcode":20}'))
        == "denied"
    )
    assert probe.classify(None, 401) == "denied" and probe.classify(Boom("x"), 403) == "denied"
    assert probe.classify(Boom('ndax {"errormsg":"Not_Enough_Funds"}')) == "allowed"  # passed
    assert probe.classify(Boom('ndax {"errormsg":"Invalid Request","errorcode":100}')) == "allowed"
    assert probe.classify(Boom("AuthenticationError ndax <html>"), 404) == "unknown"
    for text in ("timed out", 'ndax {"errormsg":"Server Error"}', "RateLimitExceeded"):
        assert probe.classify(Boom(text)) == "unknown", text


GOOD = {
    "ccxt_balance": "allowed", "balance": "allowed", "open_orders": "allowed",
    "order": "denied", "deposit": "denied", "withdraw": "denied",
}  # fmt: skip


def test_a_read_only_key_that_works_with_dummy_credentials_passes(probe: ModuleType) -> None:
    assert probe.evaluate("read-only", GOOD)[0] is True


def test_dummy_credentials_refused_by_ccxt_fails_but_says_the_key_works(probe: ModuleType) -> None:
    ok, lines = probe.evaluate("read-only", {**GOOD, "ccxt_balance": "unknown"})
    assert ok is False and any("dummy login/password" in line for line in lines)


@pytest.mark.parametrize("perm", ["withdraw", "deposit", "order"])
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


def test_the_probe_only_reads_or_quotes(probe: ModuleType) -> None:
    calls: list[str] = []

    class Spy:
        accounts: ClassVar[list] = []

        def __getattr__(self, name: str):
            def call(*a: object) -> object:
                calls.append(a[0] if name == "request" else name)  # type: ignore[arg-type]
                return [449] if name == "privateGetGetUserAccounts" else {}

            return call

    outcomes, _, _ = probe.probe(Spy(), "96")
    assert calls == [
        "fetch_balance",
        "privateGetGetUserAccounts",
        "privateGetGetAccountPositions",
        "privateGetGetOpenOrders",
        "privateGetGetOrderFee",
        "privateGetGetDepositInfo",
        "privateGetGetWithdrawFee",
        "GetUserPermissions",
    ]
    assert outcomes["balance"] == "allowed"
    code = SOURCE.read_text().split('"""', 2)[2]  # the module docstring may name what it avoids
    for forbidden in (
        "SendOrder", "CreateWithdrawTicket", "CreateDepositTicket", "Cancel", "ModifyOrder",
        "sign_in", "signIn", ".withdraw(", "create_order", "Authenticate",
    ):  # fmt: skip
        assert forbidden not in code, forbidden


def test_the_password_is_a_fixed_dummy_never_read_from_the_environment(probe: ModuleType) -> None:
    source = SOURCE.read_text()
    assert "NDAX_PASSWORD" not in source and "NDAX_LOGIN" not in source
    assert "dummy" in probe.DUMMY_LOGIN and "dummy" in probe.DUMMY_PASSWORD
    assert "@" not in probe.DUMMY_LOGIN
