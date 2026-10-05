"""R5 exclusions (live pilot): pre-existing balances the system must never treat as its own.

Append-only, like the other fact tables: an exclusion is something the operator declared, with
their name and a time. The amount in force for an asset is its most recent row (0 withdraws an
exclusion), so history is never edited. Not reversible, for the same reason as 0002/0003.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "isolation_exclusions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset", sa.String, nullable=False),
        sa.Column("amount", sa.String, nullable=False),
        sa.Column("recorded_at", sa.String, nullable=False),
        sa.Column("operator", sa.String, nullable=False),
        sa.Column("note", sa.String),
        sa.CheckConstraint("CAST(amount AS REAL) >= 0", name="ck_exclusion_non_negative"),
    )
    for verb in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER isolation_exclusions_no_{verb.lower()} BEFORE {verb} ON "
            f"isolation_exclusions BEGIN SELECT RAISE(ABORT, "
            f"'isolation_exclusions is append-only'); END"
        )


def downgrade() -> None:
    raise RuntimeError("0004_isolation_exclusions is not reversible: restore from backup")
