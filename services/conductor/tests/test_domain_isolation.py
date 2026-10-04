"""R5 startup balance check against seeded exchange-balance fixtures."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from conductor.domain.isolation import (
    AccountIsolationError,
    base_asset,
    check_account_isolation,
)

D = Decimal
WL = ["BTC/USD", "ETH/USD", "SOL/USD"]


def test_clean_account_passes() -> None:
    assert check_account_isolation(WL, {"USD": D(100)}, {}) == ()


def test_system_bought_holdings_are_explained() -> None:
    assert check_account_isolation(WL, {"ETH": D("0.5")}, {"ETH": D("0.5")}) == ()


def test_preexisting_balance_in_whitelisted_pair_is_flagged() -> None:
    (v,) = check_account_isolation(WL, {"BTC": D("0.01")}, {})
    assert (v.pair, v.asset, v.unexplained) == ("BTC/USD", "BTC", D("0.01"))


def test_excess_over_ledger_holding_is_flagged_with_exact_amount() -> None:
    (v,) = check_account_isolation(WL, {"ETH": D("0.7")}, {"ETH": D("0.5")})
    assert v.unexplained == D("0.2")


def test_shortfall_in_one_asset_cannot_mask_excess_in_another() -> None:
    # AC5.5: ETH is short by 0.5, BTC is in excess by 0.01 -> BTC still flagged.
    out = check_account_isolation(
        WL, {"ETH": D(0), "BTC": D("0.01")}, {"ETH": D("0.5"), "BTC": D(0)}
    )
    assert [v.asset for v in out] == ["BTC"]


def test_non_whitelisted_assets_are_ignored() -> None:
    assert check_account_isolation(WL, {"DOGE": D(1000)}, {}) == ()


def test_explicit_exclusion_clears_exactly_that_amount() -> None:
    assert check_account_isolation(WL, {"BTC": D("0.01")}, {}, {"BTC": D("0.01")}) == ()
    (v,) = check_account_isolation(WL, {"BTC": D("0.02")}, {}, {"BTC": D("0.01")})
    assert v.unexplained == D("0.01")


def test_tolerance() -> None:
    assert check_account_isolation(WL, {"BTC": D("0.001")}, {}, tolerance=D("0.001")) == ()
    assert check_account_isolation(WL, {"BTC": D("0.0011")}, {}, tolerance=D("0.001"))


def test_negative_tolerance_rejected() -> None:
    with pytest.raises(ValueError, match="tolerance"):
        check_account_isolation(WL, {}, {}, tolerance=D(-1))


def test_base_asset() -> None:
    assert base_asset("ETH/USD") == "ETH"
    assert base_asset("ETH/USD:USD") == "ETH"
    for bad in ("ETHUSD", "/USD"):
        with pytest.raises(ValueError, match="spot pair"):
            base_asset(bad)


def test_error_message_names_pair_and_amount() -> None:
    v = check_account_isolation(WL, {"BTC": D("0.01")}, {})
    msg = str(AccountIsolationError(v))
    assert "BTC/USD" in msg
    assert "0.01" in msg


amounts = st.decimals(min_value=D(0), max_value=D(1000), places=8, allow_nan=False)


@given(
    balances=st.fixed_dictionaries({"BTC": amounts, "ETH": amounts, "SOL": amounts}),
    held=st.fixed_dictionaries({"BTC": amounts, "ETH": amounts, "SOL": amounts}),
)
def test_per_asset_verdict_is_independent_of_other_assets(
    balances: dict[str, Decimal], held: dict[str, Decimal]
) -> None:
    flagged = {v.asset for v in check_account_isolation(WL, balances, held)}
    assert flagged == {a for a in balances if balances[a] > held[a]}
