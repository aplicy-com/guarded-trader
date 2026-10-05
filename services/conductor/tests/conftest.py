import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from conductor.application.ingest import FreqtradeInstance
from conductor.infrastructure.config import Settings
from conductor.infrastructure.db import create_db_engine, create_session_factory
from conductor.infrastructure.ledger_repository import SqliteLedger
from fakes import Clock, FakeFreqtrade, FakeFx, RecordingNotifier

ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "freqtrade"


@pytest.fixture
def fixture_json() -> Callable[[str], Any]:
    def load(name: str) -> Any:
        return json.loads((FIXTURES / f"{name}.json").read_text())

    return load


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One real `alembic upgrade head` per test session; tests copy the result."""
    db = tmp_path_factory.mktemp("template") / "template.db"
    out = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={"DATABASE_URL": f"sqlite:///{db}", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    return db


@pytest.fixture
def db_path(tmp_path: Path, migrated_template: Path) -> Path:
    dest = tmp_path / "conductor.db"
    shutil.copy(migrated_template, dest)
    return dest


def make_settings(db: Path, **overrides: Any) -> Settings:
    return Settings.model_validate(
        {
            "principal_usd": "100",
            "database_url": f"sqlite:///{db}",
            "FREQTRADE__API_SERVER__USERNAME": "u",
            "FREQTRADE__API_SERVER__PASSWORD": "p",
            "scheduler_enabled": False,
            **overrides,
        }
    )


@pytest.fixture
def settings(db_path: Path) -> Settings:
    return make_settings(db_path)


@pytest.fixture
def ledger(db_path: Path) -> SqliteLedger:
    return SqliteLedger(create_session_factory(create_db_engine(f"sqlite:///{db_path}")))


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 10, 4, 12, 0, tzinfo=UTC))


@pytest.fixture
def freqtrade() -> FakeFreqtrade:
    return FakeFreqtrade()


@pytest.fixture
def instances(freqtrade: FakeFreqtrade) -> list[FreqtradeInstance]:
    return [FreqtradeInstance("primary", freqtrade, freqtrade)]


@pytest.fixture
def fx() -> FakeFx:
    return FakeFx()


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()
