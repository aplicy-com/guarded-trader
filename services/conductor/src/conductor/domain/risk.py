"""Second-layer risk rules (R4), exposure (R2) and the correlation guard (R7).

Pure functions over numbers the application derives from the ledger. Equity is
the ledger's ``principal + realized + unrealized``, never Freqtrade's own view.
Limits are percentages as written in the requirements (3 means 3%). A limit is
breached at or beyond the threshold (conservative).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from conductor.domain.halt import HaltType

ZERO = Decimal(0)
HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class RiskLimits:
    daily_loss_limit_pct: Decimal  # draft 3
    max_drawdown_pct: Decimal  # draft 10
    consecutive_loss_limit: int  # draft 3
    max_positions: int  # R7, draft 2

    def __post_init__(self) -> None:
        for name in ("daily_loss_limit_pct", "max_drawdown_pct"):
            v: Decimal = getattr(self, name)
            if not v.is_finite() or v <= ZERO:
                raise ValueError(f"{name} must be a finite value > 0")
        if self.consecutive_loss_limit < 1:
            raise ValueError("consecutive_loss_limit must be >= 1")
        if self.max_positions < 1:
            raise ValueError("max_positions must be >= 1")


@dataclass(frozen=True, slots=True)
class Breach:
    halt_type: HaltType
    instance: str | None
    reason: str


def daily_loss_breached(
    equity_now: Decimal, equity_window_start: Decimal, base_capital: Decimal, limit_pct: Decimal
) -> bool:
    """Loss over the window (realized + unrealized) as a % of trading capital >= limit."""
    if base_capital <= ZERO:
        raise ValueError("base_capital must be > 0")
    loss = equity_window_start - equity_now
    return loss > ZERO and loss / base_capital * HUNDRED >= limit_pct


def drawdown_pct(equity_peak: Decimal, equity_now: Decimal) -> Decimal:
    """Percent below the running peak (0 when at or above it)."""
    if equity_peak <= ZERO:
        raise ValueError("equity_peak must be > 0")
    return max(ZERO, (equity_peak - equity_now) / equity_peak * HUNDRED)


def drawdown_breached(equity_peak: Decimal, equity_now: Decimal, limit_pct: Decimal) -> bool:
    return drawdown_pct(equity_peak, equity_now) >= limit_pct


def loss_streak(profits_oldest_first: Sequence[Decimal]) -> int:
    """Trailing run of losing trades. A break-even or winning trade ends the run."""
    streak = 0
    for p in reversed(profits_oldest_first):
        if p < ZERO:
            streak += 1
        else:
            break
    return streak


def exposure_exceeds_capital(open_exposure: Decimal, max_deployed_capital: Decimal) -> bool:
    return open_exposure > max_deployed_capital


def positions_exceed_group_cap(open_positions: int, max_positions: int) -> bool:
    """R7: every whitelisted pair is one exposure group."""
    return open_positions > max_positions


@dataclass(frozen=True, slots=True)
class RiskInputs:
    equity_now: Decimal | None  # None: unknown (e.g. an instance was unreachable)
    daily_start_equity: Decimal
    daily_base_capital: Decimal
    equity_peak: Decimal
    loss_streaks: Mapping[str, int]  # per instance, since that breaker was last cleared
    open_positions: int
    open_exposure: Decimal
    max_deployed_capital: Decimal


def evaluate_risk(limits: RiskLimits, i: RiskInputs) -> tuple[Breach, ...]:
    """Every limit currently breached, in a fixed order. Never raises on unknown equity."""
    out: list[Breach] = []
    if i.equity_now is not None:
        if daily_loss_breached(
            i.equity_now, i.daily_start_equity, i.daily_base_capital, limits.daily_loss_limit_pct
        ):
            out.append(
                Breach(
                    HaltType.DAILY_LOSS,
                    None,
                    f"equity {i.equity_now} vs {i.daily_start_equity} at window start: loss "
                    f">= {limits.daily_loss_limit_pct}% of {i.daily_base_capital}",
                )
            )
        if drawdown_breached(i.equity_peak, i.equity_now, limits.max_drawdown_pct):
            out.append(
                Breach(
                    HaltType.MAX_DRAWDOWN,
                    None,
                    f"equity {i.equity_now} is {drawdown_pct(i.equity_peak, i.equity_now):.2f}% "
                    f"below peak {i.equity_peak} (limit {limits.max_drawdown_pct}%)",
                )
            )
    for instance in sorted(i.loss_streaks):
        n = i.loss_streaks[instance]
        if n >= limits.consecutive_loss_limit:
            out.append(
                Breach(
                    HaltType.CONSECUTIVE_LOSSES,
                    instance,
                    f"{n} losing trades in a row on {instance} "
                    f"(limit {limits.consecutive_loss_limit})",
                )
            )
    if exposure_exceeds_capital(i.open_exposure, i.max_deployed_capital):
        out.append(
            Breach(
                HaltType.CAPITAL_EXCEEDED,
                None,
                f"open exposure {i.open_exposure} > max_deployed_capital {i.max_deployed_capital}",
            )
        )
    if positions_exceed_group_cap(i.open_positions, limits.max_positions):
        out.append(
            Breach(
                HaltType.MAX_POSITIONS,
                None,
                f"{i.open_positions} open positions > group cap {limits.max_positions} (R7)",
            )
        )
    return tuple(out)
