from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from conductor.domain.tax import FxRate, to_cad, value_closed_trade

D = Decimal


def fx(rate: str, d: date = date(2026, 9, 11), requested: date | None = None) -> FxRate:
    return FxRate(requested or d, d, D(rate), "BoC")


def test_worked_example_matches_recorded_dry_run_trade() -> None:
    # ETH trade from the recorded fixture: stake 32.99997953 + fee 0.0527999672512,
    # close_profit_abs -1.36936162.
    v = value_closed_trade(
        stake_usd=D("32.99997953"),
        fee_open_usd=D("0.0527999672512"),
        close_profit_usd=D("-1.36936162"),
        open_fx=fx("1.3866"),
        close_fx=fx("1.3909", date(2026, 9, 14), date(2026, 9, 14)),
    )
    # Freqtrade reports open_trade_value 33.0527795 (rounded to 8 dp).
    assert abs(v.cost_usd - D("33.0527795")) < D("1e-8")
    assert v.cost_cad == D("45.83")
    assert v.proceeds_cad == D("44.07")
    assert v.gain_cad == D("-1.76")


def test_rounding_is_half_up_to_cents() -> None:
    assert to_cad(D("1"), D("1.005")) == D("1.01")
    assert to_cad(D("1"), D("1.0049")) == D("1.00")


@pytest.mark.parametrize("rate", ["0", "-1", "NaN"])
def test_bad_rate_rejected(rate: str) -> None:
    with pytest.raises(ValueError, match="fx rate"):
        value_closed_trade(
            stake_usd=D(10),
            fee_open_usd=D(0),
            close_profit_usd=D(1),
            open_fx=fx(rate),
            close_fx=fx("1.3"),
        )


def test_rate_from_the_future_rejected() -> None:
    bad = FxRate(date(2026, 9, 11), date(2026, 9, 12), D("1.3"), "BoC")
    with pytest.raises(ValueError, match="after"):
        value_closed_trade(
            stake_usd=D(10),
            fee_open_usd=D(0),
            close_profit_usd=D(1),
            open_fx=bad,
            close_fx=fx("1.3"),
        )


usd = st.decimals(min_value=D("0.01"), max_value=D(100000), places=8, allow_nan=False)
profit = st.decimals(min_value=D(-1000), max_value=D(1000), places=8, allow_nan=False)
rate = st.decimals(min_value=D("0.5"), max_value=D("2.5"), places=4, allow_nan=False)


@given(stake=usd, fee=usd, p=profit, r_open=rate, r_close=rate)
def test_report_always_foots_and_uses_cent_precision(
    stake: Decimal, fee: Decimal, p: Decimal, r_open: Decimal, r_close: Decimal
) -> None:
    v = value_closed_trade(
        stake_usd=stake,
        fee_open_usd=fee,
        close_profit_usd=p,
        open_fx=fx(str(r_open)),
        close_fx=fx(str(r_close)),
    )
    assert v.gain_cad == v.proceeds_cad - v.cost_cad
    assert v.net_proceeds_usd - v.cost_usd == p
    for cad in (v.cost_cad, v.proceeds_cad, v.gain_cad):
        assert cad == cad.quantize(D("0.01"))


@given(stake=usd, p=profit, r=rate)
def test_same_rate_gain_is_within_a_cent_of_usd_profit_times_rate(
    stake: Decimal, p: Decimal, r: Decimal
) -> None:
    v = value_closed_trade(
        stake_usd=stake,
        fee_open_usd=D(0),
        close_profit_usd=p,
        open_fx=fx(str(r)),
        close_fx=fx(str(r)),
    )
    assert abs(v.gain_cad - p * r) <= D("0.01")
