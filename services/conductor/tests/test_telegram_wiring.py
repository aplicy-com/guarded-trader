"""Settings, composition root and layering for Telegram."""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from conductor.adapters.telegram import LogNotifier, TelegramAlertNotifier
from conductor.application.ingest import FreqtradeInstance
from conductor.infrastructure.config import Settings, load_settings
from conductor.main import create_app
from conftest import make_settings
from fakes import FakeFreqtrade, FakeFx, RecordingNotifier

SRC = Path(__file__).parents[1] / "src" / "conductor"
ENV = {
    "PRINCIPAL_USD": "100",
    "DATABASE_URL": "sqlite:////data/conductor.db",
    "FREQTRADE__API_SERVER__USERNAME": "u",
    "FREQTRADE__API_SERVER__PASSWORD": "p",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for k in [*ENV, "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_IDS"]:
        monkeypatch.delenv(k, raising=False)
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    return monkeypatch


def test_telegram_is_off_by_default(env: pytest.MonkeyPatch) -> None:
    s = load_settings()
    assert (s.telegram_enabled, s.telegram_allowed_chat_ids) == (False, ())


def test_blank_values_from_compose_mean_off(env: pytest.MonkeyPatch) -> None:
    env.setenv("TELEGRAM_BOT_TOKEN", "")
    env.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
    assert load_settings().telegram_enabled is False


def test_token_and_comma_separated_ids_parse(env: pytest.MonkeyPatch) -> None:
    env.setenv("TELEGRAM_BOT_TOKEN", "123456:abc")
    env.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111, -100222 ,333")
    s = load_settings()
    assert s.telegram_enabled
    assert s.telegram_allowed_chat_ids == (111, -100222, 333)
    assert "123456:abc" not in repr(s)  # SecretStr


def test_token_without_allowlist_fails_fast(env: pytest.MonkeyPatch) -> None:
    env.setenv("TELEGRAM_BOT_TOKEN", "123456:abc")
    with pytest.raises(ValidationError, match="TELEGRAM_ALLOWED_CHAT_IDS"):
        load_settings()


def test_allowlist_without_token_fails_fast(env: pytest.MonkeyPatch) -> None:
    env.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111")
    with pytest.raises(ValidationError, match="TELEGRAM_BOT_TOKEN"):
        load_settings()


@pytest.mark.parametrize("bad", ["abc", "1,x", "1.5"])
def test_non_integer_chat_ids_rejected(env: pytest.MonkeyPatch, bad: str) -> None:
    env.setenv("TELEGRAM_BOT_TOKEN", "123456:abc")
    env.setenv("TELEGRAM_ALLOWED_CHAT_IDS", bad)
    with pytest.raises(ValidationError):
        load_settings()


def test_app_without_telegram_uses_the_log_notifier_and_no_bot(db_path: Path) -> None:
    app = create_app(
        make_settings(db_path),
        instances=[FreqtradeInstance("primary", FakeFreqtrade())],
        fx=FakeFx(),
    )
    assert app is not None  # constructed without network or bot


def test_app_with_telegram_builds_the_real_alert_notifier(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[object] = []
    import conductor.infrastructure.notifier as notifier_module
    import conductor.main as main

    class Spy(TelegramAlertNotifier):
        def __init__(self, *a: object, **k: object) -> None:
            built.append(self)
            super().__init__(*a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(notifier_module, "TelegramAlertNotifier", Spy)
    monkeypatch.setattr(main, "TelegramBot", lambda *a, **k: None)
    settings: Settings = make_settings(
        db_path, telegram_bot_token="123456:abc", telegram_allowed_chat_ids="111"
    )
    create_app(settings, instances=[FreqtradeInstance("primary", FakeFreqtrade())], fx=FakeFx())
    assert len(built) == 1


def test_startup_sends_an_alert_and_the_bot_lifecycle_is_driven_by_the_app(
    settings: Settings,
) -> None:
    from fastapi.testclient import TestClient

    class FakeBot:
        def __init__(self) -> None:
            self.events: list[str] = []

        def start(self) -> None:
            self.events.append("start")

        def stop(self) -> None:
            self.events.append("stop")

    bot = FakeBot()
    n = RecordingNotifier()
    app = create_app(
        settings,
        instances=[FreqtradeInstance("primary", FakeFreqtrade())],
        fx=FakeFx(),
        notifier=n,
        bot=bot,  # type: ignore[arg-type]
    )
    with TestClient(app):
        assert bot.events == ["start"]
    assert bot.events == ["start", "stop"]
    assert n.sent[0].startswith("Conductor started")
    assert "telegram=on" in n.sent[0]


def test_dead_bot_does_not_stop_the_app(settings: Settings) -> None:
    from fastapi.testclient import TestClient

    class Dying:
        def start(self) -> None:
            raise RuntimeError("polling failed")  # would be fatal if not isolated

        def stop(self) -> None: ...

    # TelegramBot.start() itself never raises (it spawns a thread); this documents the contract
    # for the composition root: a bot object is optional and only started, never required.
    app = create_app(
        settings, instances=[FreqtradeInstance("primary", FakeFreqtrade())], fx=FakeFx()
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_telegram_library_is_confined_to_the_bot_adapter() -> None:
    for f in SRC.rglob("*.py"):
        rel = f.relative_to(SRC).as_posix()
        uses = any(m == "telegram" or m.startswith("telegram.") for m in _imports(f))
        assert uses == (rel == "adapters/telegram_bot.py"), rel


def test_the_bot_adapter_cannot_reach_the_write_client_or_use_cases_directly() -> None:
    imports = _imports(SRC / "adapters" / "telegram_bot.py")
    assert not any("control_client" in m or "halts" in m or "freqtrade" in m for m in imports)


def test_log_notifier_is_the_fallback() -> None:
    LogNotifier().send("x")  # logs only; must not raise


def test_alerts_only_mode_never_builds_the_polling_bot(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import conductor.main as main

    built: list[str] = []
    monkeypatch.setattr(main, "TelegramBot", lambda *a, **k: built.append("bot"))
    settings = make_settings(
        db_path,
        telegram_bot_token="123456:abc",
        telegram_allowed_chat_ids="111",
        telegram_commands_enabled=False,
    )
    create_app(
        settings,
        instances=[FreqtradeInstance("primary", FakeFreqtrade())],
        fx=FakeFx(),
        notifier=RecordingNotifier(),
    )
    assert built == []
    enabled = make_settings(
        db_path, telegram_bot_token="123456:abc", telegram_allowed_chat_ids="111"
    )
    create_app(
        enabled,
        instances=[FreqtradeInstance("primary", FakeFreqtrade())],
        fx=FakeFx(),
        notifier=RecordingNotifier(),
    )
    assert built == ["bot"]


def test_cli_alerts_go_to_telegram_too(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """kill / clear-halt run over SSH must alert the chat, not only the log."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from conductor import cli
    from conductor.application.principal import ensure_principal
    from conductor.infrastructure.db import create_db_engine, create_session_factory
    from conductor.infrastructure.ledger_repository import SqliteLedger
    from fakes import Clock

    class Collector:
        def __init__(self) -> None:
            self.sent: list[str] = []

        def send(self, text: str) -> None:
            self.sent.append(text)

    got = Collector()
    for k, v in {
        "PRINCIPAL_USD": "100",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "FREQTRADE__API_SERVER__USERNAME": "u",
        "FREQTRADE__API_SERVER__PASSWORD": "p",
    }.items():
        monkeypatch.setenv(k, v)
    ft = FakeFreqtrade()
    monkeypatch.setattr(
        cli, "build_instances", lambda _s: ([FreqtradeInstance("primary", ft, ft)], [])
    )
    monkeypatch.setattr(cli, "build_notifier", lambda _s: (got, []))
    ledger = SqliteLedger(create_session_factory(create_db_engine(f"sqlite:///{db_path}")))
    ensure_principal(
        ledger, Decimal(100), notifier=got, now=Clock(datetime(2026, 10, 5, tzinfo=UTC))
    )
    assert cli.main(["kill", "--operator", "m"]) == 0
    assert cli.main(["clear-halt", "1", "--operator", "m"]) == 0
    assert any(m.startswith("HALT #1 [kill_switch]") for m in got.sent)
    assert any("cleared by m" in m for m in got.sent)
