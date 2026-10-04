from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from conductor.domain.capital import compute_capital
from conductor.domain.fence import (
    manual_move_due,
    missed_fence_days,
    plan_fence,
    validate_transfer,
)

D = Decimal
money = st.decimals(min_value=D("-100000"), max_value=D("100000"), places=6, allow_nan=False)
non_negative = st.decimals(min_value=D(0), max_value=D("100000"), places=6, allow_nan=False)
NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


def test_plan_fence_examples() -> None:
    assert plan_fence(D(30), D(10)) == D(20)
    assert plan_fence(D(10), D(10)) == D(0)
    assert plan_fence(D(-5), D(10)) == D(0)
    assert plan_fence(D(5), D(0)) == D(5)


@given(working=money, cap=non_negative)
def test_after_fencing_working_profit_is_at_most_cap_and_fence_nonnegative(
    working: Decimal, cap: Decimal
) -> None:
    fenced = plan_fence(working, cap)
    assert fenced >= 0
    assert working - fenced <= max(cap, working)  # never makes working profit larger
    if working > cap:
        assert working - fenced == cap


@given(working=money, cap=non_negative)
def test_fencing_is_idempotent(working: Decimal, cap: Decimal) -> None:
    first = plan_fence(working, cap)
    assert plan_fence(working - first, cap) == 0


@given(
    principal=st.decimals(min_value=D(1), max_value=D(1000), places=2),
    realized=st.decimals(min_value=D(0), max_value=D(10000), places=2),
    cap=non_negative,
)
def test_fence_immediately_reduces_max_deployed_capital_to_principal_plus_cap(
    principal: Decimal, realized: Decimal, cap: Decimal
) -> None:
    # AC3.3: fenced funds leave max_deployed_capital in the same cycle.
    fenced = plan_fence(realized, cap)
    after = compute_capital(principal, realized, fenced)
    assert after.max_deployed_capital == principal + min(realized, cap)


def test_negative_cap_rejected() -> None:
    with pytest.raises(ValueError, match="cap"):
        plan_fence(D(1), D(-1))


def test_missed_fence_days() -> None:
    today = date(2026, 10, 10)
    assert missed_fence_days(None, today) == ()
    assert missed_fence_days(date(2026, 10, 10), today) == ()
    assert missed_fence_days(date(2026, 10, 9), today) == ()
    assert missed_fence_days(date(2026, 10, 7), today) == (date(2026, 10, 8), date(2026, 10, 9))


def test_move_due_by_threshold() -> None:
    r = manual_move_due(fenced_total=D(25), moved_total=D(0), threshold=D(25), now=NOW, since=NOW)
    assert (r.unmoved, r.over_threshold, r.month_elapsed, r.due) == (D(25), True, False, True)


def test_move_not_due_below_threshold_and_recent() -> None:
    r = manual_move_due(
        fenced_total=D(24),
        moved_total=D(0),
        threshold=D(25),
        now=NOW,
        since=NOW - timedelta(days=29),
    )
    assert r.due is False


def test_move_due_by_month_elapsed_even_below_threshold() -> None:
    r = manual_move_due(
        fenced_total=D(3),
        moved_total=D(0),
        threshold=D(25),
        now=NOW,
        since=NOW - timedelta(days=30),
    )
    assert (r.over_threshold, r.month_elapsed, r.due) == (False, True, True)


def test_nothing_unmoved_is_never_due() -> None:
    r = manual_move_due(
        fenced_total=D(50),
        moved_total=D(50),
        threshold=D(25),
        now=NOW,
        since=NOW - timedelta(days=90),
    )
    assert r.due is False


def test_move_due_rejects_overmoved() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        manual_move_due(fenced_total=D(1), moved_total=D(2), threshold=D(25), now=NOW, since=None)


def test_validate_transfer() -> None:
    validate_transfer(D(10), D(30), D(20))
    for amount, fenced, moved in [(D(11), D(30), D(20)), (D(0), D(30), D(0)), (D(-1), D(30), D(0))]:
        with pytest.raises(ValueError, match=r"transfer|amount"):
            validate_transfer(amount, fenced, moved)
