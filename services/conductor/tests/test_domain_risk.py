"""R4 second layer, R2 exposure and R7 group cap: boundaries and properties."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from conductor.domain.halt import Halt, HaltType, entries_blocked
from conductor.domain.risk import (
    RiskInputs,
    RiskLimits,
    daily_loss_breached,
    drawdown_breached,
    drawdown_pct,
    evaluate_risk,
    exposure_exceeds_capital,
    loss_streak,
    positions_exceed_group_cap,
)

D = Decimal
pos = st.decimals(min_value=D("0.01"), max_value=D(100000), places=4, allow_nan=False)
LIMITS = RiskLimits(D(3), D(10), 3, 2)


def inputs(**kw: object) -> RiskInputs:
    base: dict[str, object] = {
        "equity_now": D(100),
        "daily_start_equity": D(100),
        "daily_base_capital": D(100),
        "equity_peak": D(100),
        "loss_streaks": {},
        "open_positions": 0,
        "open_exposure": D(0),
        "max_deployed_capital": D(100),
    }
    return RiskInputs(**{**base, **kw})  # type: ignore[arg-type]


def test_daily_loss_boundary_is_inclusive() -> None:
    assert not daily_loss_breached(D("97.01"), D(100), D(100), D(3))
    assert daily_loss_breached(D("97"), D(100), D(100), D(3))
    assert daily_loss_breached(D("90"), D(100), D(100), D(3))


def test_a_gain_is_never_a_daily_loss() -> None:
    assert not daily_loss_breached(D(150), D(100), D(100), D(3))


@given(start=pos, base=pos, limit=st.decimals(min_value=D("0.1"), max_value=D(50), places=2))
def test_daily_loss_matches_the_percentage_definition(
    start: Decimal, base: Decimal, limit: Decimal
) -> None:
    threshold = base * limit / 100
    assert daily_loss_breached(start - threshold, start, base, limit)
    assert not daily_loss_breached(start - threshold + D("0.0001"), start, base, limit)


@given(start=pos, a=pos, b=pos, base=pos, limit=pos)
def test_daily_loss_is_monotonic_in_equity(
    start: Decimal, a: Decimal, b: Decimal, base: Decimal, limit: Decimal
) -> None:
    lo, hi = sorted((a, b))
    if not daily_loss_breached(lo, start, base, limit):
        assert not daily_loss_breached(hi, start, base, limit)


def test_drawdown_boundary_and_at_peak() -> None:
    assert drawdown_pct(D(100), D(100)) == 0
    assert drawdown_pct(D(100), D(120)) == 0
    assert not drawdown_breached(D(100), D("90.01"), D(10))
    assert drawdown_breached(D(100), D(90), D(10))


@given(peak=pos, now=pos, limit=st.decimals(min_value=D("0.1"), max_value=D(99), places=2))
def test_drawdown_is_never_negative_and_consistent(
    peak: Decimal, now: Decimal, limit: Decimal
) -> None:
    dd = drawdown_pct(peak, now)
    assert dd >= 0
    assert drawdown_breached(peak, now, limit) == (dd >= limit)


@pytest.mark.parametrize(
    ("profits", "streak"),
    [
        ([], 0),
        ([D(1)], 0),
        ([D(-1)], 1),
        ([D(1), D(-1), D(-2)], 2),
        ([D(-1), D(-1), D(1)], 0),
        ([D(-1), D(0), D(-1)], 1),
        ([D(-1)] * 5, 5),
    ],
)
def test_loss_streak(profits: list[Decimal], streak: int) -> None:
    assert loss_streak(profits) == streak


@given(st.lists(st.decimals(min_value=D(-5), max_value=D(5), places=2), max_size=30))
def test_loss_streak_is_the_trailing_run_of_negatives(profits: list[Decimal]) -> None:
    n = loss_streak(profits)
    assert all(p < 0 for p in profits[len(profits) - n :])
    assert n == len(profits) or profits[len(profits) - n - 1] >= 0


def test_exposure_and_group_cap_boundaries() -> None:
    assert not exposure_exceeds_capital(D(100), D(100))
    assert exposure_exceeds_capital(D("100.01"), D(100))
    assert not positions_exceed_group_cap(2, 2)
    assert positions_exceed_group_cap(3, 2)


def test_healthy_account_has_no_breach() -> None:
    assert evaluate_risk(LIMITS, inputs()) == ()


def test_each_rule_fires_alone_with_the_right_type_and_scope() -> None:
    cases = {
        HaltType.DAILY_LOSS: inputs(equity_now=D(96), equity_peak=D(96)),
        HaltType.MAX_DRAWDOWN: inputs(
            equity_now=D(85), daily_start_equity=D(85), equity_peak=D(100)
        ),
        HaltType.CONSECUTIVE_LOSSES: inputs(loss_streaks={"a": 3, "b": 1}),
        HaltType.CAPITAL_EXCEEDED: inputs(open_exposure=D(101)),
        HaltType.MAX_POSITIONS: inputs(open_positions=3),
    }
    for expected, i in cases.items():
        (b,) = evaluate_risk(LIMITS, i)
        assert b.halt_type is expected
    (streak,) = evaluate_risk(LIMITS, cases[HaltType.CONSECUTIVE_LOSSES])
    assert streak.instance == "a"
    assert all(
        evaluate_risk(LIMITS, cases[t])[0].instance is None
        for t in cases
        if t is not HaltType.CONSECUTIVE_LOSSES
    )


def test_unknown_equity_skips_equity_rules_but_not_position_rules() -> None:
    out = evaluate_risk(LIMITS, inputs(equity_now=None, open_positions=5))
    assert [b.halt_type for b in out] == [HaltType.MAX_POSITIONS]


def test_limits_are_validated() -> None:
    for bad in (
        {"daily_loss_limit_pct": D(0)},
        {"max_drawdown_pct": D("NaN")},
        {"consecutive_loss_limit": 0},
        {"max_positions": 0},
    ):
        with pytest.raises(ValueError, match="must be"):
            RiskLimits(
                **{
                    "daily_loss_limit_pct": D(3),
                    "max_drawdown_pct": D(10),
                    "consecutive_loss_limit": 3,
                    "max_positions": 2,
                    **bad,
                }
            )  # type: ignore[arg-type]


def test_entries_blocked_scope() -> None:
    from datetime import UTC, datetime

    at = datetime(2026, 10, 5, tzinfo=UTC)
    all_inst = Halt(1, HaltType.KILL_SWITCH, None, "r", at, "op")
    one = Halt(2, HaltType.CONSECUTIVE_LOSSES, "a", "r", at, "system")
    assert entries_blocked([all_inst], "x")
    assert entries_blocked([one], "a")
    assert not entries_blocked([one], "b")
    assert not entries_blocked([], "a")
