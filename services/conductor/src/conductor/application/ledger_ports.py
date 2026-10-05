"""Ledger persistence port and the read-models it returns.

Use cases open one transaction at a time via `Ledger.transaction()`; everything
inside commits or rolls back together. Conductor is the only ledger writer.
"""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from conductor.domain.halt import Halt, HaltType
from conductor.domain.ledger import LedgerTrade
from conductor.domain.tax import CadValuation, FxRate

UpsertOutcome = Literal["inserted", "updated", "unchanged"]


@dataclass(frozen=True, slots=True)
class EquitySnapshot:
    taken_at: datetime
    principal: Decimal
    realized_profit: Decimal
    unrealized_profit: Decimal | None
    fenced_total: Decimal
    working_profit: Decimal
    max_deployed_capital: Decimal
    equity: Decimal | None

    def same_state(self, other: "EquitySnapshot") -> bool:
        """Equal in everything but the timestamp (used to skip duplicate snapshots)."""
        return replace(self, taken_at=other.taken_at) == other


@dataclass(frozen=True, slots=True)
class UnvaluedTrade:
    trade_pk: int
    instance: str
    ft_trade_id: int
    pair: str
    open_date: datetime
    close_date: datetime
    stake_amount: Decimal
    fee_open_cost: Decimal | None
    close_profit_abs: Decimal | None


@dataclass(frozen=True, slots=True)
class TaxRow:
    instance: str
    ft_trade_id: int
    pair: str
    open_date: datetime
    close_date: datetime
    amount: Decimal
    exit_reason: str | None
    valuation: CadValuation


@dataclass(frozen=True, slots=True)
class OpenPosition:
    instance: str
    pair: str
    stake_amount: Decimal


@dataclass(frozen=True, slots=True)
class OpenTradeRow:
    """An open position with the detail the dashboard shows."""

    instance: str
    pair: str
    open_date: datetime
    open_rate: Decimal
    amount: Decimal
    stake_amount: Decimal


@dataclass(frozen=True, slots=True)
class AuditRow:
    id: int
    at: datetime
    actor: str
    action: str
    detail: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ClosedTradeSummary:
    instance: str
    pair: str
    close_date: datetime
    profit: Decimal
    exit_reason: str | None


@dataclass(frozen=True, slots=True)
class TransferRecord:
    amount: Decimal
    destination: str
    exchange_tx_id: str
    transferred_at: datetime
    operator: str
    note: str | None


@dataclass(frozen=True, slots=True)
class ExclusionRecord:
    asset: str
    amount: Decimal
    recorded_at: datetime
    operator: str
    note: str | None


class LedgerRepo(Protocol):
    # R1
    def get_principal(self) -> Decimal | None: ...
    def set_principal(self, amount: Decimal, currency: str, at: datetime, source: str) -> None: ...

    # trades / R2 inputs
    def upsert_trade(self, instance: str, trade: LedgerTrade, now: datetime) -> UpsertOutcome: ...
    def realized_profit_total(self) -> Decimal: ...
    def open_holdings(self) -> dict[str, Decimal]:
        """Base-asset amounts held by open long trades the system itself opened."""
        ...

    # R5
    def exclusions(self) -> dict[str, Decimal]:
        """Pre-existing amount per asset declared not-the-system's by the operator (newest wins)."""
        ...

    def exclusion_history(self) -> list[ExclusionRecord]:
        """Every declaration, oldest first."""
        ...

    def add_exclusion(
        self, asset: str, amount: Decimal, at: datetime, operator: str, note: str | None
    ) -> None: ...

    # R3
    def fenced_total(self) -> Decimal: ...
    def last_fence_date(self) -> date | None: ...
    def first_positive_fence_at(self) -> datetime | None: ...
    def add_fence_event(
        self,
        *,
        fence_date: date,
        ran_at: datetime,
        daily_profit_cap: Decimal | None,
        working_profit_before: Decimal,
        fenced_amount: Decimal,
        missed_days: int,
    ) -> bool:
        """False (and nothing written) if a run for ``fence_date`` already exists."""
        ...

    def moved_total(self) -> Decimal: ...
    def last_transfer_at(self) -> datetime | None: ...
    def add_transfer(self, record: TransferRecord, recorded_at: datetime) -> None: ...

    # risk (3A-3)
    def open_positions(self) -> list[OpenPosition]: ...
    def open_trade_rows(self) -> list[OpenTradeRow]:
        """Open long positions, oldest first (dashboard)."""
        ...

    def closed_profits(self, instance: str, since: datetime | None) -> list[Decimal]:
        """Realized profit of closed trades (oldest first), closed after ``since``."""
        ...

    def realized_profit_before(self, at: datetime) -> Decimal:
        """Realized profit of trades closed strictly before ``at``."""
        ...

    def recent_closed_trades(self, limit: int) -> list[ClosedTradeSummary]:
        """Newest first."""
        ...

    def snapshot_at(self, at: datetime) -> EquitySnapshot | None:
        """The ledger state in force at ``at``: the latest snapshot taken at or before it."""
        ...

    def snapshots_since(self, since: datetime | None) -> list[EquitySnapshot]: ...

    # halts
    def add_halt(
        self, halt_type: HaltType, instance: str | None, reason: str, at: datetime, by: str
    ) -> int: ...
    def active_halts(self) -> list[Halt]: ...
    def get_halt(self, halt_id: int) -> Halt | None: ...
    def is_halt_active(self, halt_id: int) -> bool: ...
    def clear_halt(self, halt_id: int, at: datetime, operator: str, note: str | None) -> None: ...
    def last_clear_at(self, halt_type: HaltType, instance: str | None) -> datetime | None: ...
    def list_halts(self, limit: int) -> list[tuple[Halt, datetime | None, str | None]]:
        """Newest first: (halt, cleared_at, cleared_by)."""
        ...

    # snapshots, audit
    def latest_snapshot(self) -> EquitySnapshot | None: ...
    def add_snapshot(self, snapshot: EquitySnapshot) -> None: ...
    def add_audit(
        self, at: datetime, actor: str, action: str, detail: Mapping[str, Any]
    ) -> None: ...
    def recent_audit(self, limit: int, *, actions: Sequence[str] | None = None) -> list[AuditRow]:
        """Newest first; only the given ``actions`` if provided."""
        ...

    # NFR6
    def get_fx(self, requested: date) -> FxRate | None: ...
    def put_fx(self, fx: FxRate, fetched_at: datetime) -> None: ...
    def unvalued_closed_trades(self) -> list[UnvaluedTrade]: ...
    def save_valuation(
        self, trade_pk: int, valuation: CadValuation, valued_at: datetime
    ) -> None: ...
    def tax_rows(self) -> list[TaxRow]: ...


class Ledger(Protocol):
    def transaction(self, *, write: bool = True) -> AbstractContextManager[LedgerRepo]: ...


class FxUnavailableError(RuntimeError):
    """No usable USD/CAD rate could be obtained for the requested date."""


class FxRateProvider(Protocol):
    def usd_cad(self, on: date) -> FxRate:
        """Latest published rate on or before ``on`` (raises FxUnavailableError)."""
        ...
