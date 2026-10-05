import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from conductor.infrastructure.db import create_db_engine
from conductor.infrastructure.ledger_schema import TABLE_NAMES

ROOT = Path(__file__).parents[1]


def test_engine_uses_wal_and_foreign_keys(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'x.db'}")
    with engine.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
        assert c.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_alembic_upgrade_head_applies_ledger_schema(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    env = {"DATABASE_URL": f"sqlite:///{db}", "PATH": "/usr/bin:/bin"}
    out = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    with create_engine(f"sqlite:///{db}").connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0004"
        tables = {
            r[0] for r in c.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
    assert tables == {"alembic_version", *TABLE_NAMES}
