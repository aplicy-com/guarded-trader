import pytest
from pydantic import ValidationError

from conductor.domain.trading_mode import TradingMode
from conductor.infrastructure.config import Settings, load_settings

REQUIRED = {
    "PRINCIPAL_USD": "100",
    "DATABASE_URL": "sqlite:////data/conductor.db",
    "FREQTRADE__API_SERVER__USERNAME": "user",
    "FREQTRADE__API_SERVER__PASSWORD": "pass",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [*REQUIRED, "TRADING_MODE", "HEARTBEAT_INTERVAL_SECONDS", "LLM_BACKEND"]:
        monkeypatch.delenv(key, raising=False)


def _set(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for k, v in {**REQUIRED, **overrides}.items():
        monkeypatch.setenv(k, v)


def test_valid_env_loads_with_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch)
    s = load_settings()
    assert s.trading_mode is TradingMode.DRY_RUN
    assert str(s.principal_usd) == "100"
    assert s.heartbeat_interval_seconds == 300
    assert s.llm_backend == "none"
    assert s.freqtrade_password.get_secret_value() == "pass"


@pytest.mark.parametrize("missing", list(REQUIRED))
def test_missing_required_value_fails_fast(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    _set(monkeypatch)
    monkeypatch.delenv(missing)
    with pytest.raises(ValidationError):
        load_settings()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("PRINCIPAL_USD", "0"),
        ("PRINCIPAL_USD", "-5"),
        ("PRINCIPAL_USD", "abc"),
        ("DATABASE_URL", "postgresql://x/y"),
        ("TRADING_MODE", "yolo"),
        ("HEARTBEAT_INTERVAL_SECONDS", "5"),
        ("LLM_BACKEND", "openai"),
        ("FREQTRADE__API_SERVER__PASSWORD", "   "),
    ],
)
def test_invalid_value_is_rejected(monkeypatch: pytest.MonkeyPatch, key: str, value: str) -> None:
    _set(monkeypatch, **{key: value})
    with pytest.raises(ValidationError):
        load_settings()


def test_trading_mode_live_is_accepted_only_when_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, TRADING_MODE="live")
    assert load_settings().trading_mode is TradingMode.LIVE


def test_secrets_are_not_leaked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch)
    assert "pass" not in repr(load_settings()).replace("password", "")


def test_settings_class_has_no_default_for_required_fields() -> None:
    for name in ("principal_usd", "database_url", "freqtrade_username", "freqtrade_password"):
        assert Settings.model_fields[name].is_required()
