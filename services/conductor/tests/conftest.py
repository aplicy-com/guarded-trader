import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from conductor.infrastructure.config import Settings

FIXTURES = Path(__file__).parent / "fixtures" / "freqtrade"


@pytest.fixture
def fixture_json() -> Callable[[str], Any]:
    def load(name: str) -> Any:
        return json.loads((FIXTURES / f"{name}.json").read_text())

    return load


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.model_validate(
        {
            "principal_usd": "100",
            "database_url": f"sqlite:///{tmp_path / 'conductor.db'}",
            "FREQTRADE__API_SERVER__USERNAME": "u",
            "FREQTRADE__API_SERVER__PASSWORD": "p",
            "scheduler_enabled": False,
        }
    )
