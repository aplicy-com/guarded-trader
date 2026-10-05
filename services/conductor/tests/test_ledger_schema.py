"""Schema, exact-money storage, UTC timestamps, append-only enforcement."""

import sqlite3
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa

from conductor.infrastructure import ledger_schema as t
from conductor.infrastructure.ledger_repository import SqliteLedger

D = Decimal
NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


def test_migration_matches_sqlalchemy_metadata(db_path: Path) -> None:
    """The hand-written migration and ledger_schema.py must not drift."""
    engine = sa.create_engine(f"sqlite:///{db_path}")
    insp = sa.inspect(engine)
    for table in t.metadata.tables.values():
        migrated = {c["name"]: c for c in insp.get_columns(table.name)}
        assert set(migrated) == {c.name for c in table.columns}, table.name
        for col in table.columns:
            assert migrated[col.name]["nullable"] == (col.nullable and not col.primary_key), (
                table.name,
                col.name,
            )
            assert str(migrated[col.name]["type"]).upper() in {"VARCHAR", "INTEGER", "BOOLEAN"}, (
                table.name,
                col.name,
            )
        assert {tuple(u["column_names"]) for u in insp.get_unique_constraints(table.name)} >= {
            tuple(c.name for c in u.columns)
            for u in table.constraints
            if isinstance(u, sa.UniqueConstraint)
        }


def test_money_is_exact_not_float(ledger: SqliteLedger, db_path: Path) -> None:
    amount = D("0.1") + D("0.2")  # 0.3 exactly in Decimal; 0.30000000000000004 in float
    with ledger.transaction() as repo:
        repo.set_principal(amount, "USD", NOW, "test")
    raw = (
        sqlite3.connect(db_path).execute("SELECT amount, typeof(amount) FROM principal").fetchone()
    )
    assert raw == ("0.3", "text")
    with ledger.transaction(write=False) as repo:
        got = repo.get_principal()
    assert got == D("0.3")
    assert isinstance(got, Decimal)


def test_money_type_rejects_float_and_non_finite() -> None:
    money = t.Money()
    with pytest.raises(TypeError, match="Decimal"):
        money.process_bind_param(0.1, None)  # type: ignore[arg-type]
    for bad in (D("NaN"), D("Infinity")):
        with pytest.raises(ValueError, match="finite"):
            money.process_bind_param(bad, None)  # type: ignore[arg-type]
    assert money.process_bind_param(D("1E-8"), None) == "0.00000001"  # type: ignore[arg-type]


def test_timestamps_are_utc_and_naive_rejected() -> None:
    dt = t.UtcDateTime()
    eastern = timezone(timedelta(hours=-4))
    stored = dt.process_bind_param(datetime(2026, 10, 4, 8, 0, tzinfo=eastern), None)  # type: ignore[arg-type]
    assert stored == "2026-10-04T12:00:00.000000+00:00"
    back = dt.process_result_value(stored, None)  # type: ignore[arg-type]
    assert back == datetime(2026, 10, 4, 12, tzinfo=UTC)
    assert back is not None
    assert back.utcoffset() == timedelta(0)
    with pytest.raises(ValueError, match="naive"):
        dt.process_bind_param(datetime(2026, 10, 4, 12), None)  # type: ignore[arg-type]


def test_isodate_rejects_datetime() -> None:
    with pytest.raises(TypeError):
        t.IsoDate().process_bind_param(NOW, None)  # type: ignore[arg-type]
    assert t.IsoDate().process_bind_param(date(2026, 1, 2), None) == "2026-01-02"  # type: ignore[arg-type]


@pytest.mark.parametrize("table", t.APPEND_ONLY_TABLES)
def test_append_only_tables_reject_update_and_delete(
    ledger: SqliteLedger, db_path: Path, table: str
) -> None:
    with ledger.transaction() as repo:
        repo.set_principal(D(100), "USD", NOW, "test")
        repo.add_audit(NOW, "a", "x", {})
        repo.add_fence_event(
            fence_date=date(2026, 10, 4),
            ran_at=NOW,
            daily_profit_cap=None,
            working_profit_before=D(0),
            fenced_amount=D(0),
            missed_days=0,
        )
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO manual_transfers (amount, destination, exchange_tx_id,"
        " transferred_at, operator, recorded_at) VALUES ('1', 'd', 'tx', 'x', 'o', 'x')"
    )
    conn.execute(
        "INSERT INTO halts (halt_type, reason, created_at, created_by)"
        " VALUES ('kill_switch','r','x','o')"
    )
    conn.execute("INSERT INTO halt_clears (halt_id, cleared_at, operator) VALUES (1, 'x', 'o')")
    conn.commit()
    for stmt in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):  # noqa: S608
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(stmt)


def test_principal_is_single_row_and_positive(ledger: SqliteLedger) -> None:
    with ledger.transaction() as repo:
        repo.set_principal(D(100), "USD", NOW, "test")
    with pytest.raises(sa.exc.IntegrityError), ledger.transaction() as repo:
        repo.set_principal(D(200), "USD", NOW, "test")
    with ledger.transaction(write=False) as repo:
        assert repo.get_principal() == D(100)


def test_non_positive_principal_rejected_by_database(ledger: SqliteLedger) -> None:
    with pytest.raises(sa.exc.IntegrityError), ledger.transaction() as repo:
        repo.set_principal(D(0), "USD", NOW, "test")


def test_downgrade_refuses_to_destroy_the_ledger(db_path: Path) -> None:
    root = Path(__file__).parents[1]
    out = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0001"],
        cwd=root,
        env={"DATABASE_URL": f"sqlite:///{db_path}", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode != 0
    assert "not reversible" in out.stderr
    assert sqlite3.connect(db_path).execute(
        "SELECT count(*) FROM sqlite_master WHERE name='principal'"
    ).fetchone() == (1,)


def test_write_transaction_takes_the_write_lock_before_any_write(
    ledger: SqliteLedger, db_path: Path
) -> None:
    """The transfer overdraw check reads then writes; that is only safe if the write
    lock is held from the start of the transaction (BEGIN IMMEDIATE), not at first write."""
    other_engine = sa.create_engine(f"sqlite:///{db_path}")

    @sa.event.listens_for(other_engine, "connect")
    def _short_timeout(dbapi_conn: sqlite3.Connection, _rec: object) -> None:
        dbapi_conn.execute("PRAGMA busy_timeout=50")

    other = SqliteLedger(sa.orm.sessionmaker(other_engine))
    with ledger.transaction() as repo:
        repo.get_principal()  # a read only: no write has happened yet
        with pytest.raises(sa.exc.OperationalError, match="locked"), other.transaction():
            pass
        # readers are not blocked (WAL)
        with other.transaction(write=False) as reader:
            assert reader.get_principal() is None
    with other.transaction():  # lock released after commit
        pass
