"""Live pilot (ADR-0019): the config files, compose override, key containment, sizing, soak gate."""

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from conductor import cli
from conductor.application.principal import ensure_principal
from conductor.application.soak import check_soak
from conductor.domain.halt import HaltType
from conductor.infrastructure.ledger_repository import SqliteLedger
from fakes import Clock, RecordingNotifier

REPO = Path(__file__).resolve().parents[3]
D = Decimal
LIVE_CONFIG = REPO / "services/freqtrade/user_data/config.live.json"
DRY_CONFIG = REPO / "services/freqtrade/user_data/config.dry_run.json"
BASE = REPO / "infra/docker-compose.yml"
LIVE = REPO / "infra/docker-compose.live.yml"
CHECK = REPO / "infra/docker-compose.kraken-check.yml"
HELD = {"ADA", "ETH", "DOT", "SC", "KAVA", "ACA", "XTZ", "USDC"}


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def yml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())  # type: ignore[no-any-return]


# ---- config.live.json -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live() -> dict:
    return json.loads(LIVE_CONFIG.read_text())  # type: ignore[no-any-return]


def test_live_config_is_really_live_and_boots_paused(live: dict) -> None:
    assert live["dry_run"] is False
    assert live["initial_state"] == "paused"  # ADR-0018: only Conductor starts it
    assert live["trading_mode"] == "spot"
    assert live["exchange"]["name"] == "kraken"
    assert live["force_entry_enable"] is False
    assert live["telegram"]["enabled"] is False  # Conductor owns the bot (ADR-0015)


def test_live_config_holds_no_secrets(live: dict) -> None:
    ex, api = live["exchange"], live["api_server"]
    assert ex["key"] == "" and ex["secret"] == ""
    assert api["username"] == "" and api["password"] == "" and api["jwt_secret_key"] == ""
    assert live["telegram"]["token"] == "" and live["telegram"]["chat_id"] == ""


def test_live_whitelist_excludes_every_held_asset_and_eth(live: dict) -> None:
    bases = {p.split("/")[0] for p in live["exchange"]["pair_whitelist"]}
    assert "ETH/USD" not in live["exchange"]["pair_whitelist"]
    assert not bases & HELD
    assert bases == {"BTC", "XRP", "SOL", "LINK", "LTC"}


def test_live_blacklist_covers_every_held_asset(live: dict) -> None:
    patterns = live["exchange"]["pair_blacklist"]
    for asset in HELD:
        assert f"{asset}/.*" in patterns, asset
    assert ".*/USDC" in patterns


def test_one_position_and_capital_below_principal(live: dict) -> None:
    assert live["max_open_trades"] == 1
    assert live["stake_amount"] == "unlimited"
    # Below the 20 USD principal: Kraken charges the entry fee on top of the order cost.
    assert 0 < live["available_capital"] < 20


def test_compose_position_cap_matches_freqtrade_max_open_trades(live: dict) -> None:
    env = yml(LIVE)["services"]["conductor"]["environment"]
    assert int(env["MAX_CONCURRENT_POSITIONS"]) == live["max_open_trades"]  # R7 two layers


def test_dry_run_config_is_untouched_by_the_pilot() -> None:
    dry = json.loads(DRY_CONFIG.read_text())
    assert dry["dry_run"] is True and dry["max_open_trades"] == 2
    assert "ETH/USD" in dry["exchange"]["pair_whitelist"]  # the soak run keeps its config


# ---- compose: separate ledger, key containment, pinned pilot values ------------------------------


def test_live_conductor_has_its_own_ledger_volume_and_pinned_values() -> None:
    base, live = yml(BASE), yml(LIVE)
    env = live["services"]["conductor"]["environment"]
    assert env["TRADING_MODE"] == "live"
    assert env["PRINCIPAL_USD"] == "20"
    assert env["DAILY_PROFIT_CAP_USD"] == "2"
    assert live["services"]["conductor"]["volumes"] == ["conductor-data-live:/data"]
    assert "conductor-data-live" in live["volumes"]
    assert "conductor-data:/data" in base["services"]["conductor"]["volumes"]
    assert "conductor-data-live" not in base.get("volumes", {})  # never reachable from dry-run
    assert base["services"]["conductor"]["environment"]["TRADING_MODE"].startswith("${TRADING_MODE")


def test_live_freqtrade_uses_the_live_config_and_its_own_trade_db() -> None:
    cmd = yml(LIVE)["services"]["freqtrade"]["command"]
    assert "config.live.json" in cmd and "config.dry_run.json" not in cmd
    assert "tradesv3.live.sqlite" in cmd and "dryrun" not in cmd
    assert "--strategy Baseline4h" in cmd
    base_cmd = yml(BASE)["services"]["freqtrade"]["command"]
    assert "tradesv3.dryrun.sqlite" in base_cmd  # the dry-run stack keeps its own DB


def test_live_conductor_backs_up_the_live_trade_db() -> None:
    env = yml(LIVE)["services"]["conductor"]["environment"]
    assert env["BACKUP_FREQTRADE_DB_PATH"].endswith("tradesv3.live.sqlite")


def test_the_kraken_key_reaches_freqtrade_only_and_only_in_live_or_check_overrides() -> None:
    base, live, check = yml(BASE), yml(LIVE), yml(CHECK)
    key_vars = ("FREQTRADE__EXCHANGE__KEY", "FREQTRADE__EXCHANGE__SECRET")
    raw = ("KRAKEN_API_KEY", "KRAKEN_API_SECRET")
    ft_env = base["services"]["freqtrade"]["environment"]
    for var in (*key_vars, *raw):
        assert ft_env[var] == "", var  # the dry-run container never holds the key, even raw
    assert "env_file" not in base["services"]["conductor"]
    for conductor_env in (
        base["services"]["conductor"]["environment"],
        live["services"]["conductor"]["environment"],
    ):
        assert not any("KRAKEN" in k or "EXCHANGE" in k for k in conductor_env)
    for override in (live, check):
        assert set(override["services"]) <= {"freqtrade", "conductor"}
        env = override["services"]["freqtrade"]["environment"]
        assert "${KRAKEN_API_KEY:?" in env["FREQTRADE__EXCHANGE__KEY"]
        assert "${KRAKEN_API_SECRET:?" in env["FREQTRADE__EXCHANGE__SECRET"]
    assert "conductor" not in check["services"]


def test_the_check_override_cannot_start_a_bot_or_publish_ports() -> None:
    svc = yml(CHECK)["services"]["freqtrade"]
    assert set(svc) == {"environment"}  # no command, ports or restart: it only hands over the key


def test_live_override_publishes_no_new_ports() -> None:
    for svc in yml(LIVE)["services"].values():
        assert "ports" not in svc


# ---- sizing at the real stake ----------------------------------------------------------------


@pytest.fixture(scope="module")
def sizing() -> ModuleType:
    return load_script("kraken_pilot_sizing")


# Kraken facts as recorded on 2026-10-05 (docs/research/04-live-pilot-sizing.md).
FACTS = {
    "BTC/USD": (85698.6, 5e-05, 0.5),
    "XRP/USD": (1.5016, 1.65, 0.5),
    "SOL/USD": (120.09, 0.06, 0.5),
    "LINK/USD": (13.9468, 0.55, 0.5),
    "LTC/USD": (70.29, 0.1, 0.5),
}


def rows(sizing: ModuleType, stake: float) -> list:
    return [sizing.size_pair(sizing.PairFacts(s, *f), stake) for s, f in FACTS.items()]


def test_every_whitelisted_pair_clears_the_real_stake_with_headroom(
    sizing: ModuleType, live: dict
) -> None:
    stake = sizing.stake_per_position(live["available_capital"], live["max_open_trades"])
    assert set(FACTS) == set(live["exchange"]["pair_whitelist"])
    assert all(r.clears for r in rows(sizing, stake))


def test_two_positions_would_not_clear_so_the_pilot_runs_one(
    sizing: ModuleType, live: dict
) -> None:
    two = sizing.stake_per_position(live["available_capital"], 2)
    failed = {r.symbol for r in rows(sizing, two) if not r.clears}
    assert failed == {"SOL/USD", "LINK/USD", "LTC/USD"}


def test_sizing_validation_rejects_a_held_whitelist_and_a_non_paused_config(
    sizing: ModuleType, live: dict
) -> None:
    assert sizing.validate_config(live) == []
    bad = json.loads(json.dumps(live))
    bad["exchange"]["pair_whitelist"].append("ETH/USD")
    bad["initial_state"] = "running"
    bad["dry_run"] = True
    bad["exchange"]["pair_blacklist"].remove("ADA/.*")
    problems = " | ".join(sizing.validate_config(bad))
    assert "ETH/USD is whitelisted" in problems
    assert "initial_state" in problems and "dry_run" in problems and "ADA" in problems


def test_sizing_rejects_nonsense_inputs(sizing: ModuleType) -> None:
    with pytest.raises(ValueError):
        sizing.stake_per_position(19, 0)
    with pytest.raises(ValueError):
        sizing.stake_per_position(0, 1)


# ---- Kraken key-scope probe --------------------------------------------------------------------


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    return load_script("kraken_access_probe")


class Boom(Exception):
    pass


def test_classify(probe: ModuleType) -> None:
    assert probe.classify(None) == "allowed"
    assert probe.classify(Boom('kraken {"error":["EGeneral:Permission denied"]}')) == "denied"
    assert probe.classify(Boom("EOrder:Insufficient funds")) == "allowed"  # permission passed
    assert probe.classify(Boom("EFunding:Unknown withdraw key")) == "allowed"  # => HAS withdraw
    for text in ("EAPI:Invalid key", "EAPI:Invalid signature", "timed out", "EService:Unavailable"):
        assert probe.classify(Boom(text)) == "unknown", text


GOOD_TRADE = {
    "balance": "allowed", "open_orders": "allowed", "add_order": "allowed",
    "deposit": "denied", "withdraw": "denied",
}  # fmt: skip
GOOD_QUERY = {**GOOD_TRADE, "add_order": "denied"}


def test_a_correctly_scoped_key_passes_each_scope(probe: ModuleType) -> None:
    assert probe.evaluate("trade", GOOD_TRADE)[0] is True
    assert probe.evaluate("query-only", GOOD_QUERY)[0] is True


def test_a_query_only_key_cannot_pass_as_the_trade_key_or_vice_versa(probe: ModuleType) -> None:
    assert probe.evaluate("trade", GOOD_QUERY)[0] is False  # cannot create orders yet
    ok, lines = probe.evaluate("query-only", GOOD_TRADE)
    assert ok is False and any("add_order" in line or "Create orders" in line for line in lines)


@pytest.mark.parametrize("scope", ["trade", "query-only"])
@pytest.mark.parametrize("perm", ["withdraw", "deposit"])
def test_any_funding_or_withdraw_permission_fails_loudly(
    probe: ModuleType, scope: str, perm: str
) -> None:
    outcomes = {**(GOOD_TRADE if scope == "trade" else GOOD_QUERY), perm: "allowed"}
    ok, lines = probe.evaluate(scope, outcomes)
    assert ok is False
    assert any("!!!" in line for line in lines)
    if perm == "withdraw":
        assert any("CAN WITHDRAW" in line and "Delete it" in line for line in lines)


def test_an_unverifiable_withdraw_check_is_a_failure_not_a_pass(probe: ModuleType) -> None:
    ok, lines = probe.evaluate("trade", {**GOOD_TRADE, "withdraw": "unknown"})
    assert ok is False and any("CAN WITHDRAW" in line for line in lines)


def test_unreadable_balance_fails_before_judging_anything(probe: ModuleType) -> None:
    ok, lines = probe.evaluate("trade", {**GOOD_TRADE, "balance": "unknown"})
    assert ok is False and len(lines) == 1 and "whitelisted" in lines[0]
    assert probe.evaluate("trade", {})[0] is False


def test_the_probe_order_is_validate_only_and_below_the_exchange_minimum(probe: ModuleType) -> None:
    assert probe.PROBE_ORDER["validate"] is True
    assert probe.max_probe_notional_usd() < D("0.5")  # Kraken's minimum cost: unfillable anyway


def test_the_probe_never_calls_a_withdraw_or_funding_mutation(probe: ModuleType) -> None:
    calls: list[str] = []

    class Spy:
        def __getattr__(self, name: str):
            def call(*_a: object) -> dict:
                calls.append(name)
                return {}

            return call

    probe.probe(Spy())
    assert sorted(calls) == [
        "privatePostAddOrder",
        "privatePostBalance",
        "privatePostDepositMethods",
        "privatePostOpenOrders",
        "privatePostWithdrawInfo",
    ]
    assert "privatePostWithdraw" not in calls  # the action itself is never called
    source = (REPO / "scripts" / "kraken_access_probe.py").read_text()
    for forbidden in ("privatePostWithdraw(", "privatePostWalletTransfer", "privatePostCancel"):
        assert forbidden not in source


# ---- soak gate --------------------------------------------------------------------------------

START = datetime(2026, 10, 5, 15, 29, tzinfo=UTC)


def halt(ledger: SqliteLedger, kind: HaltType, by: str, at: datetime) -> int:
    with ledger.transaction() as repo:
        return repo.add_halt(kind, None, "r", at, by)


def clear(ledger: SqliteLedger, halt_id: int, at: datetime) -> None:
    with ledger.transaction() as repo:
        repo.clear_halt(halt_id, at, "maduka", None)


def test_soak_needs_72_hours(ledger: SqliteLedger) -> None:
    short = check_soak(ledger, started_at=START, now=START + timedelta(hours=71, minutes=59))
    assert not short.time_met and not short.ok
    done = check_soak(ledger, started_at=START, now=START + timedelta(hours=72))
    assert done.time_met and done.clean and done.ok


def test_a_system_raised_halt_since_the_start_fails_the_soak(ledger: SqliteLedger) -> None:
    hid = halt(ledger, HaltType.DAILY_LOSS, "system", START + timedelta(hours=5))
    clear(ledger, hid, START + timedelta(hours=6))  # cleared, but it still happened
    s = check_soak(ledger, started_at=START, now=START + timedelta(hours=80))
    assert s.time_met and not s.clean and not s.ok and len(s.system_halts) == 1


def test_a_system_halt_before_the_start_does_not_count(ledger: SqliteLedger) -> None:
    hid = halt(ledger, HaltType.MAX_DRAWDOWN, "system", START - timedelta(days=1))
    clear(ledger, hid, START - timedelta(hours=20))
    assert check_soak(ledger, started_at=START, now=START + timedelta(hours=80)).ok


def test_human_halts_are_the_controls_working_not_a_dirty_soak(ledger: SqliteLedger) -> None:
    hid = halt(ledger, HaltType.KILL_SWITCH, "telegram:42", START + timedelta(minutes=5))
    clear(ledger, hid, START + timedelta(minutes=9))
    assert check_soak(ledger, started_at=START, now=START + timedelta(hours=80)).ok


def test_an_active_halt_blocks_the_soak_even_if_human(ledger: SqliteLedger) -> None:
    halt(ledger, HaltType.KILL_SWITCH, "telegram:42", START + timedelta(hours=30))
    s = check_soak(ledger, started_at=START, now=START + timedelta(hours=80))
    assert not s.ok and len(s.active_halts) == 1


def test_soak_rejects_naive_timestamps_and_bad_windows(ledger: SqliteLedger) -> None:
    with pytest.raises(ValueError):
        check_soak(ledger, started_at=datetime(2026, 10, 5), now=START)
    with pytest.raises(ValueError):
        check_soak(ledger, started_at=START, now=START, required=timedelta(0))


def test_soak_start_file_is_a_utc_instant_not_after_the_rebuild() -> None:
    text = (REPO / "infra/live/soak-start").read_text().strip()
    started = datetime.fromisoformat(text.replace("Z", "+00:00"))
    assert started.tzinfo is not None
    assert started == datetime(2026, 10, 5, 15, 29, tzinfo=UTC)


def test_cli_soak_check_exit_codes(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ledger: SqliteLedger,
    clock: Clock,
    notifier: RecordingNotifier,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for k, v in {
        "PRINCIPAL_USD": "100",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "FREQTRADE__API_SERVER__USERNAME": "u",
        "FREQTRADE__API_SERVER__PASSWORD": "p",
    }.items():
        monkeypatch.setenv(k, v)
    ensure_principal(ledger, D(100), notifier=notifier, now=clock)
    long_ago = (datetime.now(UTC) - timedelta(hours=100)).isoformat()
    assert cli.main(["soak-check", "--started-at", long_ago]) == 0
    assert "SOAK MET" in capsys.readouterr().out
    just_now = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert cli.main(["soak-check", "--started-at", just_now]) == 1
    assert "SOAK NOT MET" in capsys.readouterr().out
    with ledger.transaction() as repo:
        repo.add_halt(
            HaltType.MAX_DRAWDOWN, None, "r", datetime.now(UTC) - timedelta(hours=2), "system"
        )
    assert cli.main(["soak-check", "--started-at", long_ago]) == 1
    assert "SOAK NOT CLEAN" in capsys.readouterr().out
