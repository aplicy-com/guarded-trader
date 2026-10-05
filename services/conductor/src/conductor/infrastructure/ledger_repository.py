"""SQLite implementation of the ledger port (Conductor is the only writer)."""

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from conductor.application.ledger_ports import (
    EquitySnapshot,
    LedgerRepo,
    OpenPosition,
    TaxRow,
    TransferRecord,
    UnvaluedTrade,
    UpsertOutcome,
)
from conductor.domain.halt import Halt, HaltType
from conductor.domain.isolation import base_asset
from conductor.domain.ledger import LedgerTrade, merge_trade
from conductor.domain.tax import CadValuation, FxRate
from conductor.infrastructure import ledger_schema as t

ZERO = Decimal(0)
_TRADE_FIELDS = (
    "pair",
    "is_open",
    "is_short",
    "open_date",
    "close_date",
    "open_rate",
    "close_rate",
    "amount",
    "stake_amount",
    "fee_open_cost",
    "fee_close_cost",
    "close_profit_abs",
    "exit_reason",
)


def _to_trade(row: sa.Row[Any]) -> LedgerTrade:
    return LedgerTrade(ft_trade_id=row.ft_trade_id, **{f: getattr(row, f) for f in _TRADE_FIELDS})


class SqliteLedgerRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    # --- R1 ---
    def get_principal(self) -> Decimal | None:
        return self._s.execute(sa.select(t.principal.c.amount)).scalar_one_or_none()

    def set_principal(self, amount: Decimal, currency: str, at: datetime, source: str) -> None:
        self._s.execute(
            sa.insert(t.principal).values(
                id=1, amount=amount, currency=currency, set_at=at, source=source
            )
        )

    # --- trades ---
    def upsert_trade(self, instance: str, trade: LedgerTrade, now: datetime) -> UpsertOutcome:
        row = self._s.execute(
            sa.select(t.trades).where(
                t.trades.c.instance == instance, t.trades.c.ft_trade_id == trade.ft_trade_id
            )
        ).one_or_none()
        existing = _to_trade(row) if row is not None else None
        merged = merge_trade(existing, trade)
        values = {f: getattr(merged, f) for f in _TRADE_FIELDS}
        if row is None:
            self._s.execute(
                sa.insert(t.trades).values(
                    instance=instance,
                    ft_trade_id=trade.ft_trade_id,
                    first_seen_at=now,
                    updated_at=now,
                    **values,
                )
            )
            return "inserted"
        if merged == existing:
            return "unchanged"
        self._s.execute(
            sa.update(t.trades).where(t.trades.c.id == row.id).values(updated_at=now, **values)
        )
        return "updated"

    def realized_profit_total(self) -> Decimal:
        rows = self._s.execute(
            sa.select(t.trades.c.close_profit_abs).where(t.trades.c.is_open.is_(False))
        ).scalars()
        return sum((r for r in rows if r is not None), ZERO)

    def open_holdings(self) -> dict[str, Decimal]:
        rows = self._s.execute(
            sa.select(t.trades.c.pair, t.trades.c.amount).where(
                t.trades.c.is_open.is_(True), t.trades.c.is_short.is_(False)
            )
        )
        out: dict[str, Decimal] = {}
        for pair, amount in rows:
            asset = base_asset(pair)
            out[asset] = out.get(asset, ZERO) + amount
        return out

    # --- R3 ---
    def fenced_total(self) -> Decimal:
        rows = self._s.execute(sa.select(t.fence_events.c.fenced_amount)).scalars()
        return sum(rows, ZERO)

    def last_fence_date(self) -> date | None:
        rows = self._s.execute(sa.select(t.fence_events.c.fence_date)).scalars().all()
        return max(rows) if rows else None  # ISO text sorts, but compare as dates anyway

    def first_positive_fence_at(self) -> datetime | None:
        rows = self._s.execute(
            sa.select(t.fence_events.c.ran_at, t.fence_events.c.fenced_amount).order_by(
                t.fence_events.c.ran_at
            )
        )
        return next((at for at, amount in rows if amount > ZERO), None)

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
        res = self._s.execute(
            sa.insert(t.fence_events)
            .prefix_with("OR IGNORE")
            .values(
                fence_date=fence_date,
                ran_at=ran_at,
                daily_profit_cap=daily_profit_cap,
                working_profit_before=working_profit_before,
                fenced_amount=fenced_amount,
                missed_days=missed_days,
            )
        )
        return res.rowcount == 1  # type: ignore[attr-defined,no-any-return]

    def moved_total(self) -> Decimal:
        return sum(self._s.execute(sa.select(t.manual_transfers.c.amount)).scalars(), ZERO)

    def last_transfer_at(self) -> datetime | None:
        rows = self._s.execute(sa.select(t.manual_transfers.c.transferred_at)).scalars().all()
        return max(rows) if rows else None

    def add_transfer(self, record: TransferRecord, recorded_at: datetime) -> None:
        self._s.execute(
            sa.insert(t.manual_transfers).values(
                amount=record.amount,
                destination=record.destination,
                exchange_tx_id=record.exchange_tx_id,
                transferred_at=record.transferred_at,
                operator=record.operator,
                recorded_at=recorded_at,
                note=record.note,
            )
        )

    # --- risk ---
    def open_positions(self) -> list[OpenPosition]:
        rows = self._s.execute(
            sa.select(t.trades.c.instance, t.trades.c.pair, t.trades.c.stake_amount)
            .where(t.trades.c.is_open.is_(True))
            .order_by(t.trades.c.id)
        )
        return [OpenPosition(r.instance, r.pair, r.stake_amount) for r in rows]

    def closed_profits(self, instance: str, since: datetime | None) -> list[Decimal]:
        rows = self._s.execute(
            sa.select(t.trades.c.close_profit_abs, t.trades.c.close_date, t.trades.c.id).where(
                t.trades.c.instance == instance,
                t.trades.c.is_open.is_(False),
                t.trades.c.close_profit_abs.is_not(None),
            )
        ).all()
        keep = [
            r for r in rows if since is None or (r.close_date is not None and r.close_date > since)
        ]
        keep.sort(key=lambda r: (r.close_date, r.id))
        return [r.close_profit_abs for r in keep]

    def realized_profit_before(self, at: datetime) -> Decimal:
        rows = self._s.execute(
            sa.select(t.trades.c.close_profit_abs, t.trades.c.close_date).where(
                t.trades.c.is_open.is_(False), t.trades.c.close_profit_abs.is_not(None)
            )
        ).all()
        return sum(
            (r.close_profit_abs for r in rows if r.close_date is not None and r.close_date < at),
            ZERO,
        )

    def _snapshot_from(self, row: sa.Row[Any]) -> EquitySnapshot:
        return EquitySnapshot(**{f: getattr(row, f) for f in EquitySnapshot.__dataclass_fields__})

    def snapshot_at(self, at: datetime) -> EquitySnapshot | None:
        rows = self._s.execute(
            sa.select(t.equity_snapshots).order_by(t.equity_snapshots.c.id.desc())
        ).all()
        # taken_at is monotonic with id in practice; compare as datetimes to be exact
        candidates = [r for r in rows if r.taken_at <= at]
        return (
            self._snapshot_from(max(candidates, key=lambda r: (r.taken_at, r.id)))
            if candidates
            else None
        )

    def snapshots_since(self, since: datetime | None) -> list[EquitySnapshot]:
        rows = self._s.execute(
            sa.select(t.equity_snapshots).order_by(t.equity_snapshots.c.id)
        ).all()
        return [self._snapshot_from(r) for r in rows if since is None or r.taken_at >= since]

    # --- halts ---
    @staticmethod
    def _halt(row: sa.Row[Any]) -> Halt:
        return Halt(
            id=row.id,
            halt_type=HaltType(row.halt_type),
            instance=row.instance,
            reason=row.reason,
            created_at=row.created_at,
            created_by=row.created_by,
        )

    def add_halt(
        self, halt_type: HaltType, instance: str | None, reason: str, at: datetime, by: str
    ) -> int:
        halt_id: int = self._s.execute(
            sa.insert(t.halts)
            .values(
                halt_type=halt_type.value,
                instance=instance,
                reason=reason,
                created_at=at,
                created_by=by,
            )
            .returning(t.halts.c.id)
        ).scalar_one()
        return halt_id

    def active_halts(self) -> list[Halt]:
        rows = self._s.execute(
            sa.select(t.halts)
            .outerjoin(t.halt_clears, t.halt_clears.c.halt_id == t.halts.c.id)
            .where(t.halt_clears.c.id.is_(None))
            .order_by(t.halts.c.id)
        )
        return [self._halt(r) for r in rows]

    def get_halt(self, halt_id: int) -> Halt | None:
        row = self._s.execute(sa.select(t.halts).where(t.halts.c.id == halt_id)).one_or_none()
        return None if row is None else self._halt(row)

    def is_halt_active(self, halt_id: int) -> bool:
        cleared = self._s.execute(
            sa.select(t.halt_clears.c.id).where(t.halt_clears.c.halt_id == halt_id)
        ).first()
        return cleared is None and self.get_halt(halt_id) is not None

    def clear_halt(self, halt_id: int, at: datetime, operator: str, note: str | None) -> None:
        self._s.execute(
            sa.insert(t.halt_clears).values(
                halt_id=halt_id, cleared_at=at, operator=operator, note=note
            )
        )

    def last_clear_at(self, halt_type: HaltType, instance: str | None) -> datetime | None:
        cond = t.halts.c.instance.is_(None) if instance is None else t.halts.c.instance == instance
        rows = (
            self._s.execute(
                sa.select(t.halt_clears.c.cleared_at)
                .join(t.halts, t.halts.c.id == t.halt_clears.c.halt_id)
                .where(t.halts.c.halt_type == halt_type.value, cond)
            )
            .scalars()
            .all()
        )
        return max(rows) if rows else None

    def list_halts(self, limit: int) -> list[tuple[Halt, datetime | None, str | None]]:
        rows = self._s.execute(
            sa.select(t.halts, t.halt_clears.c.cleared_at, t.halt_clears.c.operator)
            .outerjoin(t.halt_clears, t.halt_clears.c.halt_id == t.halts.c.id)
            .order_by(t.halts.c.id.desc())
            .limit(limit)
        )
        return [(self._halt(r), r.cleared_at, r.operator) for r in rows]

    # --- snapshots / audit ---
    def latest_snapshot(self) -> EquitySnapshot | None:
        row = self._s.execute(
            sa.select(t.equity_snapshots).order_by(t.equity_snapshots.c.id.desc()).limit(1)
        ).one_or_none()
        if row is None:
            return None
        return EquitySnapshot(**{f: getattr(row, f) for f in EquitySnapshot.__dataclass_fields__})

    def add_snapshot(self, snapshot: EquitySnapshot) -> None:
        self._s.execute(
            sa.insert(t.equity_snapshots).values(
                **{f: getattr(snapshot, f) for f in EquitySnapshot.__dataclass_fields__}
            )
        )

    def add_audit(self, at: datetime, actor: str, action: str, detail: Mapping[str, Any]) -> None:
        self._s.execute(
            sa.insert(t.audit_log).values(
                at=at,
                actor=actor,
                action=action,
                detail=json.dumps(detail, sort_keys=True, default=str),
            )
        )

    # --- NFR6 ---
    def get_fx(self, requested: date) -> FxRate | None:
        row = self._s.execute(
            sa.select(t.fx_rates).where(t.fx_rates.c.requested_date == requested)
        ).one_or_none()
        if row is None:
            return None
        return FxRate(row.requested_date, row.rate_date, row.usd_cad, row.source)

    def put_fx(self, fx: FxRate, fetched_at: datetime) -> None:
        self._s.execute(
            sa.insert(t.fx_rates)
            .prefix_with("OR IGNORE")
            .values(
                requested_date=fx.requested_date,
                rate_date=fx.rate_date,
                usd_cad=fx.rate,
                source=fx.source,
                fetched_at=fetched_at,
            )
        )

    def unvalued_closed_trades(self) -> list[UnvaluedTrade]:
        tr, v = t.trades, t.trade_cad_valuations
        rows = self._s.execute(
            sa.select(tr)
            .outerjoin(v, v.c.trade_id == tr.c.id)
            .where(tr.c.is_open.is_(False), tr.c.close_date.is_not(None), v.c.trade_id.is_(None))
            .order_by(tr.c.close_date, tr.c.id)
        )
        return [
            UnvaluedTrade(
                trade_pk=r.id,
                instance=r.instance,
                ft_trade_id=r.ft_trade_id,
                pair=r.pair,
                open_date=r.open_date,
                close_date=r.close_date,
                stake_amount=r.stake_amount,
                fee_open_cost=r.fee_open_cost,
                close_profit_abs=r.close_profit_abs,
            )
            for r in rows
        ]

    def save_valuation(self, trade_pk: int, valuation: CadValuation, valued_at: datetime) -> None:
        self._s.execute(
            sa.insert(t.trade_cad_valuations).values(
                trade_id=trade_pk,
                cost_usd=valuation.cost_usd,
                net_proceeds_usd=valuation.net_proceeds_usd,
                open_fx_date=valuation.open_fx.rate_date,
                open_usd_cad=valuation.open_fx.rate,
                close_fx_date=valuation.close_fx.rate_date,
                close_usd_cad=valuation.close_fx.rate,
                cost_cad=valuation.cost_cad,
                proceeds_cad=valuation.proceeds_cad,
                gain_cad=valuation.gain_cad,
                valued_at=valued_at,
            )
        )

    def tax_rows(self) -> list[TaxRow]:
        tr, v = t.trades, t.trade_cad_valuations
        rows = self._s.execute(
            sa.select(tr, v).join(v, v.c.trade_id == tr.c.id).order_by(tr.c.close_date, tr.c.id)
        )
        out: list[TaxRow] = []
        for r in rows:
            open_fx = FxRate(r.open_date.date(), r.open_fx_date, r.open_usd_cad, "BankOfCanada")
            close_fx = FxRate(r.close_date.date(), r.close_fx_date, r.close_usd_cad, "BankOfCanada")
            out.append(
                TaxRow(
                    instance=r.instance,
                    ft_trade_id=r.ft_trade_id,
                    pair=r.pair,
                    open_date=r.open_date,
                    close_date=r.close_date,
                    amount=r.amount,
                    exit_reason=r.exit_reason,
                    valuation=CadValuation(
                        cost_usd=r.cost_usd,
                        net_proceeds_usd=r.net_proceeds_usd,
                        open_fx=open_fx,
                        close_fx=close_fx,
                        cost_cad=r.cost_cad,
                        proceeds_cad=r.proceeds_cad,
                        gain_cad=r.gain_cad,
                    ),
                )
            )
        return out


class SqliteLedger:
    """Transaction factory. Write transactions take SQLite's write lock up front
    (BEGIN IMMEDIATE), so a read-then-write sequence (e.g. "is this transfer
    within the unmoved balance?") cannot interleave with another writer."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    @contextmanager
    def transaction(self, *, write: bool = True) -> Iterator[LedgerRepo]:
        with self._factory() as session:
            try:
                if write:
                    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                yield SqliteLedgerRepo(session)
                session.commit()
            except BaseException:
                session.rollback()
                raise
