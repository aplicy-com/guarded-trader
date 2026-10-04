"""Ledger schema (3A-2).

Money is exact decimal TEXT and timestamps are UTC ISO-8601 TEXT: see
conductor.infrastructure.ledger_schema. `principal`, `fence_events`,
`manual_transfers` and `audit_log` are append-only: triggers abort any
UPDATE or DELETE (R1 AC1.2 immutable principal; AC3.5 auditable events).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APPEND_ONLY = ("principal", "fence_events", "manual_transfers", "audit_log")


def upgrade() -> None:
    op.create_table(
        "principal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("amount", sa.String, nullable=False),
        sa.Column("currency", sa.String, nullable=False),
        sa.Column("set_at", sa.String, nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_principal_single_row"),
        sa.CheckConstraint("CAST(amount AS REAL) > 0", name="ck_principal_positive"),
    )
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("instance", sa.String, nullable=False),
        sa.Column("ft_trade_id", sa.Integer, nullable=False),
        sa.Column("pair", sa.String, nullable=False),
        sa.Column("is_open", sa.Boolean, nullable=False),
        sa.Column("is_short", sa.Boolean, nullable=False),
        sa.Column("open_date", sa.String, nullable=False),
        sa.Column("close_date", sa.String),
        sa.Column("open_rate", sa.String, nullable=False),
        sa.Column("close_rate", sa.String),
        sa.Column("amount", sa.String, nullable=False),
        sa.Column("stake_amount", sa.String, nullable=False),
        sa.Column("fee_open_cost", sa.String),
        sa.Column("fee_close_cost", sa.String),
        sa.Column("close_profit_abs", sa.String),
        sa.Column("exit_reason", sa.String),
        sa.Column("first_seen_at", sa.String, nullable=False),
        sa.Column("updated_at", sa.String, nullable=False),
        sa.UniqueConstraint("instance", "ft_trade_id", name="uq_trades_instance_ft_trade_id"),
    )
    op.create_table(
        "equity_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("taken_at", sa.String, nullable=False),
        sa.Column("principal", sa.String, nullable=False),
        sa.Column("realized_profit", sa.String, nullable=False),
        sa.Column("unrealized_profit", sa.String),
        sa.Column("fenced_total", sa.String, nullable=False),
        sa.Column("working_profit", sa.String, nullable=False),
        sa.Column("max_deployed_capital", sa.String, nullable=False),
        sa.Column("equity", sa.String),
    )
    op.create_index("ix_equity_snapshots_taken_at", "equity_snapshots", ["taken_at"])
    op.create_table(
        "fence_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fence_date", sa.String, nullable=False, unique=True),
        sa.Column("ran_at", sa.String, nullable=False),
        sa.Column("daily_profit_cap", sa.String),
        sa.Column("working_profit_before", sa.String, nullable=False),
        sa.Column("fenced_amount", sa.String, nullable=False),
        sa.Column("missed_days", sa.Integer, nullable=False),
    )
    op.create_table(
        "manual_transfers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("amount", sa.String, nullable=False),
        sa.Column("destination", sa.String, nullable=False),
        sa.Column("exchange_tx_id", sa.String, nullable=False, unique=True),
        sa.Column("transferred_at", sa.String, nullable=False),
        sa.Column("operator", sa.String, nullable=False),
        sa.Column("recorded_at", sa.String, nullable=False),
        sa.Column("note", sa.String),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("at", sa.String, nullable=False),
        sa.Column("actor", sa.String, nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("detail", sa.String, nullable=False),
    )
    op.create_table(
        "fx_rates",
        sa.Column("requested_date", sa.String, primary_key=True),
        sa.Column("rate_date", sa.String, nullable=False),
        sa.Column("usd_cad", sa.String, nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("fetched_at", sa.String, nullable=False),
    )
    op.create_table(
        "trade_cad_valuations",
        sa.Column("trade_id", sa.Integer, sa.ForeignKey("trades.id"), primary_key=True),
        sa.Column("cost_usd", sa.String, nullable=False),
        sa.Column("net_proceeds_usd", sa.String, nullable=False),
        sa.Column("open_fx_date", sa.String, nullable=False),
        sa.Column("open_usd_cad", sa.String, nullable=False),
        sa.Column("close_fx_date", sa.String, nullable=False),
        sa.Column("close_usd_cad", sa.String, nullable=False),
        sa.Column("cost_cad", sa.String, nullable=False),
        sa.Column("proceeds_cad", sa.String, nullable=False),
        sa.Column("gain_cad", sa.String, nullable=False),
        sa.Column("valued_at", sa.String, nullable=False),
    )
    for table in APPEND_ONLY:
        for verb in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
            )


def downgrade() -> None:
    # Dropping the ledger would destroy the audit trail. Restore from backup instead.
    raise RuntimeError("0002_ledger is not reversible: restore the ledger from backup")
