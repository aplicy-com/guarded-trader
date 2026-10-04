"""Ledger tables (SQLAlchemy Core) and the column types that keep money exact.

SQLite has no exact decimal type, and a column with NUMERIC affinity silently
coerces to binary floating point. So money is stored as canonical decimal TEXT
(`Money`) and always handled as `Decimal`; floats are rejected at the boundary.
Timestamps are stored as ISO-8601 UTC text (`UtcDateTime`); naive datetimes
are rejected. Dates (fence day, FX day) are ISO `YYYY-MM-DD` text.

`migrations/versions/0002_ledger.py` is the authoritative DDL (it also installs
the append-only triggers); `tests/test_ledger_schema.py` fails if this module
and the migration drift apart.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.engine import Dialect


class Money(sa.types.TypeDecorator[Decimal]):
    """Exact `Decimal` <-> canonical TEXT (never float)."""

    impl = sa.String
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise TypeError(f"Money requires Decimal, got {type(value).__name__}")
        if not value.is_finite():
            raise ValueError("Money must be finite")
        return format(value, "f")

    def process_result_value(self, value: str | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else Decimal(value)


class UtcDateTime(sa.types.TypeDecorator[datetime]):
    """Timezone-aware datetime <-> ISO-8601 UTC TEXT (fixed width, so it sorts)."""

    impl = sa.String
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetime rejected; timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat(timespec="microseconds")

    def process_result_value(self, value: str | None, dialect: Dialect) -> datetime | None:
        return None if value is None else datetime.fromisoformat(value).astimezone(UTC)


class IsoDate(sa.types.TypeDecorator[date]):
    impl = sa.String
    cache_ok = True

    def process_bind_param(self, value: date | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            raise TypeError("IsoDate requires a date, not a datetime")
        return value.isoformat()

    def process_result_value(self, value: str | None, dialect: Dialect) -> date | None:
        return None if value is None else date.fromisoformat(value)


metadata = sa.MetaData()

principal = sa.Table(
    "principal",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("amount", Money, nullable=False),
    sa.Column("currency", sa.String, nullable=False),
    sa.Column("set_at", UtcDateTime, nullable=False),
    sa.Column("source", sa.String, nullable=False),
    sa.CheckConstraint("id = 1", name="ck_principal_single_row"),
    sa.CheckConstraint("CAST(amount AS REAL) > 0", name="ck_principal_positive"),
)

trades = sa.Table(
    "trades",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("instance", sa.String, nullable=False),
    sa.Column("ft_trade_id", sa.Integer, nullable=False),
    sa.Column("pair", sa.String, nullable=False),
    sa.Column("is_open", sa.Boolean, nullable=False),
    sa.Column("is_short", sa.Boolean, nullable=False),
    sa.Column("open_date", UtcDateTime, nullable=False),
    sa.Column("close_date", UtcDateTime),
    sa.Column("open_rate", Money, nullable=False),
    sa.Column("close_rate", Money),
    sa.Column("amount", Money, nullable=False),
    sa.Column("stake_amount", Money, nullable=False),
    sa.Column("fee_open_cost", Money),
    sa.Column("fee_close_cost", Money),
    sa.Column("close_profit_abs", Money),
    sa.Column("exit_reason", sa.String),
    sa.Column("first_seen_at", UtcDateTime, nullable=False),
    sa.Column("updated_at", UtcDateTime, nullable=False),
    sa.UniqueConstraint("instance", "ft_trade_id", name="uq_trades_instance_ft_trade_id"),
)

equity_snapshots = sa.Table(
    "equity_snapshots",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("taken_at", UtcDateTime, nullable=False),
    sa.Column("principal", Money, nullable=False),
    sa.Column("realized_profit", Money, nullable=False),
    sa.Column("unrealized_profit", Money),  # NULL when an instance was unreachable
    sa.Column("fenced_total", Money, nullable=False),
    sa.Column("working_profit", Money, nullable=False),
    sa.Column("max_deployed_capital", Money, nullable=False),
    sa.Column("equity", Money),  # principal + realized + unrealized; NULL with unrealized
)
sa.Index("ix_equity_snapshots_taken_at", equity_snapshots.c.taken_at)

fence_events = sa.Table(
    "fence_events",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("fence_date", IsoDate, nullable=False, unique=True),  # one run per UTC day
    sa.Column("ran_at", UtcDateTime, nullable=False),
    sa.Column("daily_profit_cap", Money),  # NULL: cap not configured, nothing fenced
    sa.Column("working_profit_before", Money, nullable=False),
    sa.Column("fenced_amount", Money, nullable=False),  # 0 when nothing was fenced
    sa.Column("missed_days", sa.Integer, nullable=False),
)

manual_transfers = sa.Table(
    "manual_transfers",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("amount", Money, nullable=False),
    sa.Column("destination", sa.String, nullable=False),
    sa.Column("exchange_tx_id", sa.String, nullable=False, unique=True),
    sa.Column("transferred_at", UtcDateTime, nullable=False),
    sa.Column("operator", sa.String, nullable=False),
    sa.Column("recorded_at", UtcDateTime, nullable=False),
    sa.Column("note", sa.String),
)

audit_log = sa.Table(
    "audit_log",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("at", UtcDateTime, nullable=False),
    sa.Column("actor", sa.String, nullable=False),
    sa.Column("action", sa.String, nullable=False),
    sa.Column("detail", sa.String, nullable=False),  # JSON text
)

fx_rates = sa.Table(
    "fx_rates",
    metadata,
    sa.Column("requested_date", IsoDate, primary_key=True),
    sa.Column("rate_date", IsoDate, nullable=False),
    sa.Column("usd_cad", Money, nullable=False),
    sa.Column("source", sa.String, nullable=False),
    sa.Column("fetched_at", UtcDateTime, nullable=False),
)

trade_cad_valuations = sa.Table(
    "trade_cad_valuations",
    metadata,
    sa.Column("trade_id", sa.Integer, sa.ForeignKey("trades.id"), primary_key=True),
    sa.Column("cost_usd", Money, nullable=False),
    sa.Column("net_proceeds_usd", Money, nullable=False),
    sa.Column("open_fx_date", IsoDate, nullable=False),
    sa.Column("open_usd_cad", Money, nullable=False),
    sa.Column("close_fx_date", IsoDate, nullable=False),
    sa.Column("close_usd_cad", Money, nullable=False),
    sa.Column("cost_cad", Money, nullable=False),
    sa.Column("proceeds_cad", Money, nullable=False),
    sa.Column("gain_cad", Money, nullable=False),
    sa.Column("valued_at", UtcDateTime, nullable=False),
)

# Tables that may never be UPDATEd or DELETEd once written (enforced by triggers).
APPEND_ONLY_TABLES: tuple[str, ...] = (
    "principal",
    "fence_events",
    "manual_transfers",
    "audit_log",
)

TABLE_NAMES: frozenset[str] = frozenset(metadata.tables)
