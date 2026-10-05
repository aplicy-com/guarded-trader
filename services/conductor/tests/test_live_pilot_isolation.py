"""R5 for the live pilot: exclusions, the CLI, the pre-start gate, the mode guard, LIVE banners."""

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conductor import cli
from conductor.application.boot import BootGuard, start_if_clear
from conductor.application.ingest import FreqtradeInstance
from conductor.application.isolation import (
    ExclusionError,
    isolation_rows,
    record_exclusion,
    run_startup_isolation_check,
)
from conductor.application.live_guard import (
    ModeMismatchError,
    make_start_gate,
    mode_mismatch,
    verify_mode,
)
from conductor.application.principal import ensure_principal
from conductor.application.telegram_commands import CommandProcessor
from conductor.domain.confirmation import ConfirmationBook
from conductor.domain.freqtrade_view import BotConfigView
from conductor.domain.isolation import AccountIsolationError, effective_exclusions
from conductor.domain.trading_mode import LIVE_BANNER, TradingMode, mode_banner
from conductor.infrastructure.ledger_repository import SqliteLedger
from conductor.main import create_app
from conftest import make_settings
from fakes import Clock, FakeFreqtrade, RecordingNotifier, open_view

D = Decimal
LIVE_PAIRS = ("BTC/USD", "XRP/USD", "SOL/USD", "LINK/USD", "LTC/USD")


@pytest.fixture
def live_ft() -> FakeFreqtrade:
    return FakeFreqtrade(
        pairs=LIVE_PAIRS, dry_run=False, balance_by_currency={"USD": D(20), "ETH": D("3")}
    )


@pytest.fixture
def live_instances(live_ft: FakeFreqtrade) -> list[FreqtradeInstance]:
    return [FreqtradeInstance("primary", live_ft, live_ft)]


# ---- exclusion ledger ---------------------------------------------------------------------


class Rec:
    def __init__(self, asset: str, amount: str) -> None:
        self.asset, self.amount = asset, D(amount)


def test_newest_declaration_wins_and_zero_withdraws() -> None:
    hist = [Rec("ETH", "3"), Rec("ADA", "100"), Rec("ETH", "2.5"), Rec("ADA", "0")]
    assert effective_exclusions(hist) == {"ETH": D("2.5")}


def test_exclusions_are_append_only_and_audited(
    ledger: SqliteLedger,
    live_instances: list[FreqtradeInstance],
    clock: Clock,
    db_path: Path,
) -> None:
    got = record_exclusion(
        ledger,
        live_instances[0],
        asset="eth",
        amount=None,
        operator="maduka",
        note="old",
        now=clock,
    )
    assert got == D("3")  # exactly what was unexplained
    with ledger.transaction(write=False) as repo:
        assert repo.exclusions() == {"ETH": D("3")}
        assert [(r.asset, r.operator) for r in repo.exclusion_history()] == [("ETH", "maduka")]
        audit = repo.recent_audit(5, actions=["isolation_exclusion_recorded"])
    assert audit and audit[0].actor == "operator:maduka"
    conn = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM isolation_exclusions")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE isolation_exclusions SET amount = '99'")


def test_cannot_exclude_more_than_the_account_holds(
    ledger: SqliteLedger, live_instances: list[FreqtradeInstance], clock: Clock
) -> None:
    with pytest.raises(ExclusionError, match="cannot exclude 5"):
        record_exclusion(
            ledger, live_instances[0], asset="ETH", amount=D(5), operator="m", note=None, now=clock
        )
    with pytest.raises(ExclusionError, match="cannot exclude 1"):  # nothing held at all
        record_exclusion(
            ledger, live_instances[0], asset="ADA", amount=D(1), operator="m", note=None, now=clock
        )
    with ledger.transaction(write=False) as repo:
        assert repo.exclusions() == {}


def test_cannot_exclude_the_systems_own_position(
    ledger: SqliteLedger, live_ft: FakeFreqtrade, clock: Clock, notifier: RecordingNotifier
) -> None:
    from conductor.application.ingest import run_ingest

    live_ft.open_trades = [open_view(1, "BTC/USD", amount="0.01")]
    live_ft.balance_by_currency = {"BTC": D("0.01")}
    inst = [FreqtradeInstance("primary", live_ft, live_ft)]
    run_ingest(ledger, inst, now=clock)
    with pytest.raises(ExclusionError):  # the whole 0.01 BTC is the system's own
        record_exclusion(
            ledger, inst[0], asset="BTC", amount=D("0.01"), operator="m", note=None, now=clock
        )


def test_amount_must_be_non_negative(
    ledger: SqliteLedger, live_instances: list[FreqtradeInstance], clock: Clock
) -> None:
    with pytest.raises(ExclusionError):
        record_exclusion(
            ledger, live_instances[0], asset="ETH", amount=D(-1), operator="m", note=None, now=clock
        )
    with pytest.raises(ExclusionError):
        record_exclusion(
            ledger, live_instances[0], asset="ETH", amount=D(1), operator=" ", note=None, now=clock
        )


# ---- startup check honours exclusions, per asset ---------------------------------------------


def test_startup_check_passes_only_after_the_balance_is_excluded(
    ledger: SqliteLedger,
    live_ft: FakeFreqtrade,
    live_instances: list[FreqtradeInstance],
    notifier: RecordingNotifier,
    clock: Clock,
) -> None:
    live_ft.pairs = (*LIVE_PAIRS, "ETH/USD")  # ETH is whitelisted here, to exercise the check
    with pytest.raises(AccountIsolationError, match="exclude-balance"):
        run_startup_isolation_check(
            TradingMode.LIVE, ledger, live_instances, notifier=notifier, now=clock
        )
    record_exclusion(
        ledger, live_instances[0], asset="ETH", amount=None, operator="m", note=None, now=clock
    )
    assert (
        run_startup_isolation_check(
            TradingMode.LIVE, ledger, live_instances, notifier=notifier, now=clock
        )
        == ()
    )


def test_an_exclusion_does_not_mask_a_different_asset(
    ledger: SqliteLedger,
    live_ft: FakeFreqtrade,
    live_instances: list[FreqtradeInstance],
    notifier: RecordingNotifier,
    clock: Clock,
) -> None:
    live_ft.pairs = (*LIVE_PAIRS, "ETH/USD")
    record_exclusion(
        ledger, live_instances[0], asset="ETH", amount=None, operator="m", note=None, now=clock
    )
    live_ft.balance_by_currency["XRP"] = D(40)  # someone deposited XRP: still unexplained
    with pytest.raises(AccountIsolationError, match="XRP"):
        run_startup_isolation_check(
            TradingMode.LIVE, ledger, live_instances, notifier=notifier, now=clock
        )


def test_isolation_rows_cover_every_whitelisted_asset(
    ledger: SqliteLedger, live_instances: list[FreqtradeInstance]
) -> None:
    rows = {r.asset: r for r in isolation_rows(ledger, live_instances[0])}
    assert set(rows) == {"BTC", "XRP", "SOL", "LINK", "LTC"}
    assert all(r.unexplained == 0 for r in rows.values())  # held ETH is not whitelisted


# ---- CLI --------------------------------------------------------------------------------------


@pytest.fixture
def cli_env(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ledger: SqliteLedger,
    clock: Clock,
    notifier: RecordingNotifier,
    live_instances: list[FreqtradeInstance],
) -> None:
    for k, v in {
        "PRINCIPAL_USD": "20",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "FREQTRADE__API_SERVER__USERNAME": "u",
        "FREQTRADE__API_SERVER__PASSWORD": "p",
    }.items():
        monkeypatch.setenv(k, v)
    ensure_principal(ledger, D(20), notifier=notifier, now=clock)
    monkeypatch.setattr(cli, "build_instances", lambda _s: (live_instances, []))


@pytest.mark.usefixtures("cli_env")
def test_cli_isolation_check_and_exclude_roundtrip(
    live_ft: FakeFreqtrade, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["isolation-check"]) == 0
    assert "R5 CHECK PASS" in capsys.readouterr().out
    live_ft.balance_by_currency["LTC"] = D("2")  # a whitelisted asset the system did not buy
    assert cli.main(["isolation-check"]) == 1
    assert "R5 CHECK FAIL: unexplained LTC" in capsys.readouterr().out
    assert cli.main(["exclude-balance", "--asset", "LTC", "--operator", "maduka"]) == 0
    assert "excluded 2 LTC" in capsys.readouterr().out
    assert cli.main(["isolation-check"]) == 0


@pytest.mark.usefixtures("cli_env")
def test_cli_exclude_refuses_more_than_held(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["exclude-balance", "--asset", "LTC", "--amount", "1", "--operator", "m"])
    assert code == 1
    assert "cannot exclude" in capsys.readouterr().err


def test_cli_exclude_needs_an_operator() -> None:
    with pytest.raises(SystemExit):
        cli.main(["exclude-balance", "--asset", "ETH"])


# ---- mode guard -----------------------------------------------------------------------------


def cfg(**kw: object) -> BotConfigView:
    base: dict[str, object] = {
        "bot_name": "b",
        "version": "v",
        "strategy": "S",
        "dry_run": False,
        "trading_mode": "spot",
        "stake_currency": "USD",
        "stake_amount": "unlimited",
        "max_open_trades": 1,
        "timeframe": "4h",
        "exchange": "kraken",
        "state": "paused",
    }
    return BotConfigView(**{**base, **kw})  # type: ignore[arg-type]


def test_mode_mismatch_matrix() -> None:
    assert mode_mismatch(TradingMode.LIVE, cfg()) is None
    assert mode_mismatch(TradingMode.DRY_RUN, cfg(dry_run=True)) is None
    assert "dry_run=true" in (mode_mismatch(TradingMode.LIVE, cfg(dry_run=True)) or "")
    assert "REAL orders" in (mode_mismatch(TradingMode.DRY_RUN, cfg(dry_run=False)) or "")
    assert "binance" in (mode_mismatch(TradingMode.LIVE, cfg(exchange="binance")) or "")
    assert "futures" in (mode_mismatch(TradingMode.LIVE, cfg(trading_mode="futures")) or "")


def test_dry_run_conductor_refuses_a_freqtrade_that_trades_for_real(
    live_instances: list[FreqtradeInstance],
) -> None:
    with pytest.raises(ModeMismatchError, match="REAL orders"):
        verify_mode(TradingMode.DRY_RUN, live_instances)


def test_dry_run_tolerates_an_unreachable_freqtrade() -> None:
    ft = FakeFreqtrade(fail=True)
    verify_mode(TradingMode.DRY_RUN, [FreqtradeInstance("primary", ft, ft)])


def test_create_app_refuses_live_against_a_dry_running_freqtrade(db_path: Path) -> None:
    ft = FakeFreqtrade(dry_run=True, balance_by_currency={"USD": D(20)})
    with pytest.raises(ModeMismatchError):
        create_app(
            make_settings(db_path, trading_mode="live", principal_usd="20"),
            instances=[FreqtradeInstance("primary", ft, ft)],
        )
    with sqlite3.connect(db_path) as conn:  # refused before any ledger write
        assert conn.execute("SELECT count(*) FROM principal").fetchone() == (0,)


# ---- pre-start gate (Freqtrade restarted while Conductor is up) ------------------------------


def boot_once(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    guard: BootGuard,
    notifier: RecordingNotifier,
    gate: object,
) -> tuple[object, ...]:
    return start_if_clear(
        ledger,
        instances,
        guard,
        equity_known=True,
        notifier=notifier,
        start_gate=gate,  # type: ignore[arg-type]
    )


def test_start_gate_withholds_a_start_while_r5_is_violated_then_allows_it(
    ledger: SqliteLedger,
    live_ft: FakeFreqtrade,
    live_instances: list[FreqtradeInstance],
    notifier: RecordingNotifier,
    clock: Clock,
) -> None:
    ensure_principal(ledger, D(20), notifier=notifier, now=clock)
    live_ft.state = "paused"
    live_ft.balance_by_currency["LTC"] = D("2")
    guard, gate = BootGuard(), make_start_gate(TradingMode.LIVE, ledger)

    results = boot_once(ledger, live_instances, guard, notifier, gate)
    assert live_ft.state == "paused" and "resume" not in live_ft.control_calls
    assert [(r.step, r.ok) for r in results] == [("boot_start", False)]  # type: ignore[attr-defined]
    assert sum("NOT started" in m for m in notifier.sent) == 1
    boot_once(ledger, live_instances, guard, notifier, gate)  # still vetoed: no second alert
    assert sum("NOT started" in m for m in notifier.sent) == 1

    record_exclusion(
        ledger, live_instances[0], asset="LTC", amount=None, operator="m", note=None, now=clock
    )
    boot_once(ledger, live_instances, guard, notifier, gate)
    assert live_ft.state == "running"


def test_start_gate_vetoes_on_a_mode_mismatch_and_on_unreadable_balances(
    ledger: SqliteLedger,
    live_ft: FakeFreqtrade,
    live_instances: list[FreqtradeInstance],
    notifier: RecordingNotifier,
) -> None:
    live_ft.state = "paused"
    live_ft.dry_run = True  # Freqtrade came back in the wrong mode
    boot_once(
        ledger, live_instances, BootGuard(), notifier, make_start_gate(TradingMode.LIVE, ledger)
    )
    assert live_ft.state == "paused"

    live_ft.dry_run = False

    def boom() -> dict[str, Decimal]:
        raise ConnectionError("down")

    live_ft.balances = boom  # type: ignore[method-assign]
    boot_once(
        ledger, live_instances, BootGuard(), notifier, make_start_gate(TradingMode.LIVE, ledger)
    )
    assert live_ft.state == "paused"


def test_a_broken_gate_vetoes_instead_of_allowing(
    ledger: SqliteLedger,
    live_ft: FakeFreqtrade,
    live_instances: list[FreqtradeInstance],
    notifier: RecordingNotifier,
) -> None:
    live_ft.state = "paused"

    def broken(_i: FreqtradeInstance, _c: BotConfigView) -> str | None:
        raise RuntimeError("bug")

    boot_once(ledger, live_instances, BootGuard(), notifier, broken)
    assert live_ft.state == "paused"


def test_dry_run_gate_does_not_check_balances(
    ledger: SqliteLedger, notifier: RecordingNotifier
) -> None:
    ft = FakeFreqtrade(state="paused", balance_by_currency={"BTC": D(9)})
    inst = [FreqtradeInstance("primary", ft, ft)]
    boot_once(ledger, inst, BootGuard(), notifier, make_start_gate(TradingMode.DRY_RUN, ledger))
    assert ft.state == "running" and "balances" not in ft.calls


# ---- LIVE banner ------------------------------------------------------------------------------


def test_banner_is_loud_in_live_and_empty_in_dry_run() -> None:
    assert mode_banner(TradingMode.LIVE).startswith(LIVE_BANNER)
    assert "REAL MONEY" in LIVE_BANNER
    assert mode_banner(TradingMode.DRY_RUN) == ""


def processor(
    ledger: SqliteLedger,
    inst: list[FreqtradeInstance],
    mode: TradingMode,
    notifier: RecordingNotifier,
    clock: Clock,
) -> CommandProcessor:
    return CommandProcessor(
        ledger=ledger,
        instances=inst,
        trading_mode=mode,
        notifier=notifier,
        now=clock,
        book=ConfirmationBook(code_factory=lambda: "AB12"),
        sleep=lambda _s: None,
    )


def test_telegram_shows_the_live_banner_on_status_help_and_every_confirmation(
    ledger: SqliteLedger,
    live_instances: list[FreqtradeInstance],
    notifier: RecordingNotifier,
    clock: Clock,
) -> None:
    ensure_principal(ledger, D(20), notifier=notifier, now=clock)
    bot = processor(ledger, live_instances, TradingMode.LIVE, notifier, clock)
    for text in ("/status", "/help", "/kill", "/flatten"):
        assert LIVE_BANNER in bot.handle(1, text)[0], text
    dry = processor(ledger, live_instances, TradingMode.DRY_RUN, notifier, clock)
    for text in ("/status", "/help", "/kill", "/flatten"):
        assert "REAL MONEY" not in dry.handle(1, text)[0], text


@pytest.mark.parametrize("mode", ["live", "dry_run"])
def test_dashboard_banner_only_in_live(db_path: Path, clock: Clock, mode: str) -> None:
    ft = FakeFreqtrade(dry_run=mode == "dry_run", balance_by_currency={"USD": D(20)})
    app = create_app(
        make_settings(db_path, trading_mode=mode, principal_usd="20"),
        instances=[FreqtradeInstance("primary", ft, ft)],
        clock=clock,
    )
    with TestClient(app) as c:
        for page in ("/", "/halts", "/partials/overview"):
            body = c.get(page).text
            assert ("REAL MONEY" in body) == (mode == "live"), page


def test_startup_message_carries_the_banner(
    db_path: Path, clock: Clock, notifier: RecordingNotifier
) -> None:
    ft = FakeFreqtrade(dry_run=False, balance_by_currency={"USD": D(20)})
    app = create_app(
        make_settings(db_path, trading_mode="live", principal_usd="20"),
        instances=[FreqtradeInstance("primary", ft, ft)],
        notifier=notifier,
        clock=clock,
    )
    with TestClient(app):
        pass
    assert any(m.startswith(LIVE_BANNER) and "Conductor started" in m for m in notifier.sent)
