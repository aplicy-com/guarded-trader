"""Halt state (3A-3): persisted halts and their human clears.

Both tables are append-only (triggers abort UPDATE/DELETE), like the 0002
audit tables: a halt is a fact; clearing it is another fact with an operator.
Not reversible, for the same reason as 0002.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

APPEND_ONLY = ("halts", "halt_clears")


def upgrade() -> None:
    op.create_table(
        "halts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("halt_type", sa.String, nullable=False),
        sa.Column("instance", sa.String),
        sa.Column("reason", sa.String, nullable=False),
        sa.Column("created_at", sa.String, nullable=False),
        sa.Column("created_by", sa.String, nullable=False),
    )
    op.create_table(
        "halt_clears",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("halt_id", sa.Integer, sa.ForeignKey("halts.id"), nullable=False, unique=True),
        sa.Column("cleared_at", sa.String, nullable=False),
        sa.Column("operator", sa.String, nullable=False),
        sa.Column("note", sa.String),
    )
    for table in APPEND_ONLY:
        for verb in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
            )


def downgrade() -> None:
    raise RuntimeError("0003_halts is not reversible: restore the ledger from backup")
