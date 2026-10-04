"""NFR6: CAD fair value of a closed trade. Pure; no I/O.

Records fair values only. It does NOT assume a CRA tax treatment (business
income vs capital gains is unresolved, see docs/09-tax-questions.md).
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class FxRate:
    """CAD per 1 USD for ``requested_date``, as published on ``rate_date`` (<= requested)."""

    requested_date: date
    rate_date: date
    rate: Decimal
    source: str


@dataclass(frozen=True, slots=True)
class CadValuation:
    cost_usd: Decimal
    net_proceeds_usd: Decimal
    open_fx: FxRate
    close_fx: FxRate
    cost_cad: Decimal
    proceeds_cad: Decimal
    gain_cad: Decimal


def to_cad(usd: Decimal, rate: Decimal) -> Decimal:
    return (usd * rate).quantize(CENT, rounding=ROUND_HALF_UP)


def value_closed_trade(
    *,
    stake_usd: Decimal,
    fee_open_usd: Decimal,
    close_profit_usd: Decimal,
    open_fx: FxRate,
    close_fx: FxRate,
) -> CadValuation:
    """Cost = stake + opening fee, converted at the open-date rate.

    Net proceeds = cost + realized profit (Freqtrade's profit is net of both
    fees), converted at the close-date rate. Gain is the difference of the two
    rounded CAD figures so the report always foots.
    """
    for fx in (open_fx, close_fx):
        if not fx.rate.is_finite() or fx.rate <= 0:
            raise ValueError("fx rate must be a finite value > 0")
        if fx.rate_date > fx.requested_date:
            raise ValueError("fx rate_date is after the requested date")
    cost_usd = stake_usd + fee_open_usd
    net_proceeds_usd = cost_usd + close_profit_usd
    cost_cad = to_cad(cost_usd, open_fx.rate)
    proceeds_cad = to_cad(net_proceeds_usd, close_fx.rate)
    return CadValuation(
        cost_usd=cost_usd,
        net_proceeds_usd=net_proceeds_usd,
        open_fx=open_fx,
        close_fx=close_fx,
        cost_cad=cost_cad,
        proceeds_cad=proceeds_cad,
        gain_cad=proceeds_cad - cost_cad,
    )
