"""R1/R2 domain tests, incl. property-based tests of the capital formula."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from conductor.domain.capital import (
    PrincipalMismatchError,
    check_principal,
    compute_capital,
)

D = Decimal
money = st.decimals(min_value=D("-1000000"), max_value=D("1000000"), places=8, allow_nan=False)
positive = st.decimals(min_value=D("0.00000001"), max_value=D("1000000"), places=8, allow_nan=False)
non_negative = st.decimals(min_value=D(0), max_value=D("1000000"), places=8, allow_nan=False)


def test_worked_example() -> None:
    s = compute_capital(D(100), realized_profit=D(30), fenced_total=D(20))
    assert s.working_profit == D(10)
    assert s.max_deployed_capital == D(110)


@given(principal=positive, realized=money, fenced=non_negative)
def test_formula_and_fenced_subtracted_exactly_once(
    principal: Decimal, realized: Decimal, fenced: Decimal
) -> None:
    s = compute_capital(principal, realized, fenced)
    assert s.working_profit == realized - fenced
    assert s.max_deployed_capital == max(D(0), principal + realized - fenced)
    assert s.max_deployed_capital >= 0


@given(principal=positive, realized=non_negative, fenced=non_negative)
def test_never_exceeds_principal_plus_realized_profit(
    principal: Decimal, realized: Decimal, fenced: Decimal
) -> None:
    # No input other than realized profit can raise the ceiling above principal + profit.
    assert compute_capital(principal, realized, fenced).max_deployed_capital <= principal + realized


@given(principal=positive, realized=money, fenced=non_negative, extra=positive)
def test_fencing_more_never_raises_capital(
    principal: Decimal, realized: Decimal, fenced: Decimal, extra: Decimal
) -> None:
    before = compute_capital(principal, realized, fenced).max_deployed_capital
    after = compute_capital(principal, realized, fenced + extra).max_deployed_capital
    assert after <= before


@given(principal=positive, realized=money, fenced=non_negative, gain=positive)
def test_more_realized_profit_never_lowers_capital(
    principal: Decimal, realized: Decimal, fenced: Decimal, gain: Decimal
) -> None:
    lo = compute_capital(principal, realized, fenced).max_deployed_capital
    hi = compute_capital(principal, realized + gain, fenced).max_deployed_capital
    assert hi >= lo


@pytest.mark.parametrize(
    ("principal", "fenced"), [(D(0), D(0)), (D(-1), D(0)), (D(100), D(-1)), (D("NaN"), D(0))]
)
def test_invalid_inputs_rejected(principal: Decimal, fenced: Decimal) -> None:
    with pytest.raises(ValueError, match="must be"):
        compute_capital(principal, D(0), fenced)


def test_non_finite_profit_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        compute_capital(D(100), D("Infinity"), D(0))


def test_check_principal_first_run_requests_record() -> None:
    assert check_principal(None, D(100)) is True


def test_check_principal_same_value_is_noop_even_with_different_scale() -> None:
    assert check_principal(D("100"), D("100.00")) is False


@given(recorded=positive, configured=positive)
def test_check_principal_any_difference_raises(recorded: Decimal, configured: Decimal) -> None:
    if recorded == configured:
        assert check_principal(recorded, configured) is False
    else:
        with pytest.raises(PrincipalMismatchError):
            check_principal(recorded, configured)


@pytest.mark.parametrize("bad", [D(0), D(-5), D("NaN"), D("Infinity")])
def test_check_principal_rejects_invalid_configured(bad: Decimal) -> None:
    with pytest.raises(ValueError, match="configured principal"):
        check_principal(None, bad)
