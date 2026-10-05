"""Read-only dashboard read-models (3A-5).

Everything here opens ledger transactions with ``write=False`` and returns plain
dataclasses; the web layer only renders them. Nothing in this module can change state.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from conductor.application.backup import BACKUP_COMPLETED, BACKUP_FAILED
from conductor.application.capital import capital_from_ledger
from conductor.application.heartbeat import HeartbeatLog
from conductor.application.ledger_ports import (
    AuditRow,
    ClosedTradeSummary,
    EquitySnapshot,
    Ledger,
    OpenTradeRow,
)
from conductor.domain.halt import Halt

# A nightly job: more than a day plus slack without a success is stale.
BACKUP_STALE_AFTER = timedelta(hours=26)
EQUITY_WINDOW_DAYS = 30
EQUITY_MAX_POINTS = 400
BACKUP_AUDIT_SCAN = 200


@dataclass(frozen=True, slots=True)
class CurvePoint:
    at: datetime
    equity: Decimal


@dataclass(frozen=True, slots=True)
class HeartbeatView:
    outcome: str | None  # None = nothing sent since this process started
    last_attempt_at: datetime | None
    last_ok_at: datetime | None
    reason: str


@dataclass(frozen=True, slots=True)
class BackupSourceView:
    label: str
    last_ok_at: datetime | None
    last_ok_key: str | None
    last_failed_at: datetime | None
    last_error: str | None

    @property
    def failing(self) -> bool:
        return self.last_failed_at is not None and (
            self.last_ok_at is None or self.last_failed_at > self.last_ok_at
        )


@dataclass(frozen=True, slots=True)
class BackupView:
    configured: bool
    sources: tuple[BackupSourceView, ...]
    stale: bool  # configured, but no success within BACKUP_STALE_AFTER (or none ever)


@dataclass(frozen=True, slots=True)
class OverviewView:
    as_of: datetime
    trading_mode: str
    principal: Decimal
    realized_profit: Decimal
    unrealized_profit: Decimal | None
    equity: Decimal | None
    fenced_total: Decimal
    working_profit: Decimal
    max_deployed_capital: Decimal
    active_halts: tuple[Halt, ...]
    open_positions: int
    heartbeat: HeartbeatView
    backup: BackupView

    @property
    def halted(self) -> bool:
        return bool(self.active_halts)


@dataclass(frozen=True, slots=True)
class PositionsView:
    open_trades: tuple[OpenTradeRow, ...]
    closed_trades: tuple[ClosedTradeSummary, ...]


@dataclass(frozen=True, slots=True)
class HaltRow:
    halt: Halt
    cleared_at: datetime | None
    cleared_by: str | None


@dataclass(frozen=True, slots=True)
class HaltsView:
    halts: tuple[HaltRow, ...]
    audit: tuple[AuditRow, ...]


def downsample[T](items: list[T], max_points: int) -> list[T]:
    """Evenly thin ``items`` to at most ``max_points``, always keeping the first and last."""
    n = len(items)
    if max_points < 2 or n <= max_points:
        return list(items)
    step = (n - 1) / (max_points - 1)
    picked = sorted({round(i * step) for i in range(max_points)} | {0, n - 1})
    return [items[i] for i in picked]


def _equity_of(snap: EquitySnapshot) -> Decimal:
    if snap.equity is not None:
        return snap.equity
    return snap.principal + snap.realized_profit  # unrealized unknown: realized-only


def build_backup_view(audit: list[AuditRow], *, configured: bool, now: datetime) -> BackupView:
    labels: dict[str, dict[str, object]] = {}
    for row in audit:  # newest first: the first row seen per (label, kind) is the latest
        label = str(row.detail.get("label", "?"))
        entry = labels.setdefault(label, {})
        if row.action == BACKUP_COMPLETED and "ok" not in entry:
            entry["ok"] = row
        elif row.action == BACKUP_FAILED and "failed" not in entry:
            entry["failed"] = row
    sources = []
    for label in sorted(labels):
        ok = labels[label].get("ok")
        failed = labels[label].get("failed")
        sources.append(
            BackupSourceView(
                label=label,
                last_ok_at=ok.at if isinstance(ok, AuditRow) else None,
                last_ok_key=str(ok.detail.get("key")) if isinstance(ok, AuditRow) else None,
                last_failed_at=failed.at if isinstance(failed, AuditRow) else None,
                last_error=str(failed.detail.get("error"))
                if isinstance(failed, AuditRow)
                else None,
            )
        )
    newest_ok = max((s.last_ok_at for s in sources if s.last_ok_at), default=None)
    stale = configured and (newest_ok is None or now - newest_ok > BACKUP_STALE_AFTER)
    return BackupView(configured=configured, sources=tuple(sources), stale=stale)


def build_overview(
    ledger: Ledger,
    *,
    now: datetime,
    trading_mode: str,
    heartbeat: HeartbeatLog | None,
    backup_configured: bool,
) -> OverviewView:
    """Raises ``PrincipalNotSetError`` if the ledger has no principal yet."""
    with ledger.transaction(write=False) as repo:
        cap = capital_from_ledger(repo)
        latest = repo.latest_snapshot()
        halts = repo.active_halts()
        positions = len(repo.open_positions())
        audit = repo.recent_audit(BACKUP_AUDIT_SCAN, actions=(BACKUP_COMPLETED, BACKUP_FAILED))
    attempt, ok_at, outcome, reason = (
        heartbeat.snapshot() if heartbeat is not None else (None, None, None, "")
    )
    return OverviewView(
        as_of=now,
        trading_mode=trading_mode,
        principal=cap.principal,
        realized_profit=cap.realized_profit,
        unrealized_profit=latest.unrealized_profit if latest else None,
        equity=latest.equity if latest else None,
        fenced_total=cap.fenced_total,
        working_profit=cap.working_profit,
        max_deployed_capital=cap.max_deployed_capital,
        active_halts=tuple(halts),
        open_positions=positions,
        heartbeat=HeartbeatView(outcome, attempt, ok_at, reason),
        backup=build_backup_view(audit, configured=backup_configured, now=now),
    )


def build_equity_curve(
    ledger: Ledger,
    *,
    now: datetime,
    days: int = EQUITY_WINDOW_DAYS,
    max_points: int = EQUITY_MAX_POINTS,
) -> list[CurvePoint]:
    with ledger.transaction(write=False) as repo:
        snaps = repo.snapshots_since(now - timedelta(days=days))
    return downsample([CurvePoint(s.taken_at, _equity_of(s)) for s in snaps], max_points)


def build_positions(ledger: Ledger, *, closed_limit: int = 50) -> PositionsView:
    with ledger.transaction(write=False) as repo:
        return PositionsView(
            open_trades=tuple(repo.open_trade_rows()),
            closed_trades=tuple(repo.recent_closed_trades(closed_limit)),
        )


def build_halts(ledger: Ledger, *, halt_limit: int = 50, audit_limit: int = 100) -> HaltsView:
    with ledger.transaction(write=False) as repo:
        return HaltsView(
            halts=tuple(HaltRow(h, c, by) for h, c, by in repo.list_halts(halt_limit)),
            audit=tuple(repo.recent_audit(audit_limit)),
        )
