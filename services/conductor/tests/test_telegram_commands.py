"""Chat commands: read output, and the confirmation gate in front of every write."""

import sqlite3
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from conductor.application.halts import engage_halt
from conductor.application.ingest import FreqtradeInstance, run_ingest
from conductor.application.principal import ensure_principal
from conductor.application.telegram_commands import CommandProcessor
from conductor.domain.confirmation import ConfirmationBook
from conductor.domain.halt import HaltType
from conductor.domain.trading_mode import TradingMode
from conductor.infrastructure.ledger_repository import SqliteLedger
from fakes import Clock, FakeFreqtrade, RecordingNotifier, closed_view, open_view

D = Decimal
CHAT = 4242


@pytest.fixture(autouse=True)
def principal(ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier) -> None:
    ensure_principal(ledger, D(100), notifier=notifier, now=clock)


@pytest.fixture
def bot(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    clock: Clock,
    notifier: RecordingNotifier,
) -> CommandProcessor:
    return CommandProcessor(
        ledger=ledger,
        instances=instances,
        trading_mode=TradingMode.DRY_RUN,
        notifier=notifier,
        now=clock,
        book=ConfirmationBook(code_factory=lambda: "AB12"),
        sleep=lambda _s: None,
    )


def one(replies: list[str]) -> str:
    assert len(replies) == 1
    return replies[0]


def halts(ledger: SqliteLedger) -> list[tuple[int, HaltType]]:
    with ledger.transaction(write=False) as repo:
        return [(h.id, h.halt_type) for h in repo.active_halts()]


# ---- read commands ----------------------------------------------------------------


def test_help_lists_commands_and_says_nothing_can_open_a_trade(bot: CommandProcessor) -> None:
    text = one(bot.handle(CHAT, "/help"))
    for cmd in ("/status", "/capital", "/halts", "/trades", "/kill", "/flatten", "/resume"):
        assert cmd in text
    assert "open a trade" in text


def test_status_shows_mode_halts_positions_state_and_pnl(
    bot: CommandProcessor,
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(1, "ETH/USD", stake_amount=D(25), profit_abs=D("1.5"))]
    run_ingest(ledger, instances, now=clock)
    engage_halt(
        ledger,
        halt_type=HaltType.KILL_SWITCH,
        reason="manual",
        actor="op",
        now=clock,
        notifier=notifier,
    )
    text = one(bot.handle(CHAT, "/status"))
    assert "Mode: dry_run" in text
    assert "HALTED (1)" in text
    assert "kill_switch" in text
    assert "Freqtrade primary: running" in text
    assert "ETH/USD stake 25.00 USD" in text
    assert "Today P&L (UTC): +1.50 USD" in text


def test_status_when_everything_is_quiet(bot: CommandProcessor) -> None:
    text = one(bot.handle(CHAT, "/status"))
    assert "Halts: none" in text
    assert "Open positions: none" in text


def test_status_survives_an_unreachable_freqtrade(
    bot: CommandProcessor, freqtrade: FakeFreqtrade
) -> None:
    freqtrade.fail = True
    assert "Freqtrade primary: unreachable" in one(bot.handle(CHAT, "/status"))


def test_capital(
    bot: CommandProcessor,
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
) -> None:
    freqtrade.closed_trades = [closed_view(1, "5")]
    run_ingest(ledger, instances, now=clock)
    text = one(bot.handle(CHAT, "/capital"))
    assert "Principal: 100.00 USD" in text
    assert "Max deployed capital: 105.00 USD" in text


def test_halts_and_trades(
    bot: CommandProcessor,
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    assert one(bot.handle(CHAT, "/halts")) == "No active halts."
    assert one(bot.handle(CHAT, "/trades")) == "No closed trades yet."
    freqtrade.closed_trades = [closed_view(i, "1.00") for i in range(1, 14)]
    run_ingest(ledger, instances, now=clock)
    engage_halt(
        ledger,
        halt_type=HaltType.MAX_POSITIONS,
        reason="r7",
        actor="system",
        now=clock,
        notifier=notifier,
    )
    assert "max_positions" in one(bot.handle(CHAT, "/halts"))
    assert len(one(bot.handle(CHAT, "/trades")).splitlines()) == 10


def test_command_with_bot_suffix_and_odd_case(bot: CommandProcessor) -> None:
    assert "Mode:" in one(bot.handle(CHAT, "/STATUS@MyConductorBot"))


def test_plain_chatter_is_ignored(bot: CommandProcessor) -> None:
    assert bot.handle(CHAT, "hello there") == []


# ---- nothing opens a trade -----------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "/forceenter BTC/USD",
        "/forcebuy BTC/USD",
        "/buy",
        "/long BTC/USD",
        "/stopentry",
        "/reload_config",
        "/stop",
        "/forceexit all",
        "/delete 1",
    ],
)
def test_there_is_no_way_to_open_or_alter_anything_else(
    bot: CommandProcessor, freqtrade: FakeFreqtrade, cmd: str
) -> None:
    assert "Unknown command" in one(bot.handle(CHAT, cmd))
    assert freqtrade.control_calls == []


def test_start_is_just_the_telegram_greeting_not_a_freqtrade_start(
    bot: CommandProcessor, freqtrade: FakeFreqtrade
) -> None:
    assert "Conductor commands" in one(bot.handle(CHAT, "/start"))
    assert freqtrade.control_calls == []


# ---- writes need confirmation ---------------------------------------------------------


@pytest.mark.parametrize("cmd", ["/kill", "/flatten"])
def test_write_commands_only_ask(
    bot: CommandProcessor, ledger: SqliteLedger, freqtrade: FakeFreqtrade, cmd: str
) -> None:
    reply = one(bot.handle(CHAT, cmd))
    assert "yes AB12" in reply
    assert "60 s" in reply
    assert freqtrade.control_calls == []
    assert halts(ledger) == []


def test_resume_only_asks_and_never_resumes_without_confirmation(
    bot: CommandProcessor,
    ledger: SqliteLedger,
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    engage_halt(
        ledger, halt_type=HaltType.KILL_SWITCH, reason="r", actor="op", now=clock, notifier=notifier
    )
    freqtrade.state = "paused"
    assert "yes AB12" in one(bot.handle(CHAT, "/resume 1"))
    assert halts(ledger) == [(1, HaltType.KILL_SWITCH)]
    assert freqtrade.state == "paused"
    assert freqtrade.control_calls == []


def test_correct_code_runs_the_kill_switch_as_that_chat(
    bot: CommandProcessor,
    ledger: SqliteLedger,
    freqtrade: FakeFreqtrade,
    db_path: Path,
    notifier: RecordingNotifier,
) -> None:
    bot.handle(CHAT, "/kill")
    reply = one(bot.handle(CHAT, "yes AB12"))
    assert "all steps ok" in reply
    assert freqtrade.state == "paused"
    assert halts(ledger) == [(1, HaltType.KILL_SWITCH)]
    row = sqlite3.connect(db_path).execute("SELECT created_by FROM halts").fetchone()
    assert row == (f"telegram:{CHAT}",)


def test_flatten_runs_the_nuclear_sequence(
    bot: CommandProcessor, freqtrade: FakeFreqtrade, notifier: RecordingNotifier
) -> None:
    freqtrade.open_trades = [open_view(1, has_open_orders=True), open_view(2)]
    bot.handle(CHAT, "/flatten")
    reply = one(bot.handle(CHAT, "yes AB12"))
    assert "Nuclear #1: all steps ok" in reply
    assert freqtrade.control_calls == ["pause_entries", "cancel:1", "force_exit_all", "stop"]
    assert any(m.startswith("HALT #1 [nuclear]") for m in notifier.sent)


def test_resume_with_confirmation_clears_as_that_chat_and_resumes(
    bot: CommandProcessor,
    ledger: SqliteLedger,
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
    db_path: Path,
) -> None:
    engage_halt(
        ledger, halt_type=HaltType.KILL_SWITCH, reason="r", actor="op", now=clock, notifier=notifier
    )
    freqtrade.state = "paused"
    bot.handle(CHAT, "/resume 1")
    reply = one(bot.handle(CHAT, "yes AB12"))
    assert "Cleared halt #1" in reply
    assert freqtrade.state == "running"
    assert halts(ledger) == []
    assert sqlite3.connect(db_path).execute(
        "SELECT operator, note FROM halt_clears"
    ).fetchone() == (
        f"telegram:{CHAT}",
        "via telegram",
    )
    assert any("cleared by telegram" in m for m in notifier.sent)


@pytest.mark.parametrize("arg", ["", "abc", "-1", "1.5"])
def test_resume_needs_a_numeric_halt_id(bot: CommandProcessor, arg: str) -> None:
    assert "Usage: /resume <halt_id>" in one(bot.handle(CHAT, f"/resume {arg}"))


def test_resume_unknown_halt(bot: CommandProcessor) -> None:
    assert "No halt #99" in one(bot.handle(CHAT, "/resume 99"))


def test_wrong_code_does_nothing_and_cannot_be_retried(
    bot: CommandProcessor, ledger: SqliteLedger, freqtrade: FakeFreqtrade
) -> None:
    bot.handle(CHAT, "/kill")
    assert "Wrong code" in one(bot.handle(CHAT, "yes ZZZZ"))
    assert one(bot.handle(CHAT, "yes AB12")) == "Nothing is waiting for confirmation."
    assert freqtrade.control_calls == []
    assert halts(ledger) == []


def test_timeout_does_nothing(
    bot: CommandProcessor, ledger: SqliteLedger, freqtrade: FakeFreqtrade, clock: Clock
) -> None:
    bot.handle(CHAT, "/flatten")
    clock.at += timedelta(seconds=61)
    assert "expired" in one(bot.handle(CHAT, "yes AB12"))
    assert freqtrade.control_calls == []
    assert halts(ledger) == []


def test_another_chat_cannot_confirm_my_request(
    bot: CommandProcessor, freqtrade: FakeFreqtrade
) -> None:
    bot.handle(CHAT, "/kill")
    assert one(bot.handle(999, "yes AB12")) == "Nothing is waiting for confirmation."
    assert freqtrade.control_calls == []


def test_a_double_yes_runs_the_action_once(bot: CommandProcessor, freqtrade: FakeFreqtrade) -> None:
    bot.handle(CHAT, "/kill")
    bot.handle(CHAT, "yes AB12")
    bot.handle(CHAT, "yes AB12")
    assert freqtrade.control_calls == ["pause_entries"]


def test_unrelated_text_leaves_the_pending_request_to_expire(
    bot: CommandProcessor, freqtrade: FakeFreqtrade
) -> None:
    bot.handle(CHAT, "/kill")
    assert bot.handle(CHAT, "what?") == []
    assert freqtrade.control_calls == []  # still nothing ran


def test_a_failing_use_case_reports_and_does_not_crash(
    bot: CommandProcessor, freqtrade: FakeFreqtrade
) -> None:
    freqtrade.fail = True
    bot.handle(CHAT, "/kill")
    reply = one(bot.handle(CHAT, "yes AB12"))
    assert "NOT every step succeeded" in reply


def test_flatten_result_is_sent_once_as_the_reply_not_also_as_an_alert(
    bot: CommandProcessor, freqtrade: FakeFreqtrade, notifier: RecordingNotifier
) -> None:
    freqtrade.open_trades = [open_view(1)]
    bot.handle(CHAT, "/flatten")
    assert "Nuclear #1" in one(bot.handle(CHAT, "yes AB12"))
    assert not any("NUCLEAR #1" in m for m in notifier.sent)
    assert any(m.startswith("HALT #1") for m in notifier.sent)  # the halt alert still goes out


def test_failed_kill_result_is_sent_once_as_the_reply(
    bot: CommandProcessor, freqtrade: FakeFreqtrade, notifier: RecordingNotifier
) -> None:
    freqtrade.fail = True
    bot.handle(CHAT, "/kill")
    assert "NOT every step succeeded" in one(bot.handle(CHAT, "yes AB12"))
    assert not any("KILL SWITCH #1" in m for m in notifier.sent)


def test_resume_of_an_already_cleared_halt_says_so_without_asking_for_a_code(
    bot: CommandProcessor,
    ledger: SqliteLedger,
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    for halt_type in (HaltType.KILL_SWITCH, HaltType.NUCLEAR):
        engage_halt(
            ledger,
            halt_type=halt_type,
            reason="r",
            actor="op",
            now=clock,
            notifier=notifier,
        )
    freqtrade.state = "paused"
    bot.handle(CHAT, "/resume 1")
    bot.handle(CHAT, "yes AB12")  # clears #1
    assert halts(ledger) == [(2, HaltType.NUCLEAR)]
    freqtrade.control_calls.clear()

    reply = one(bot.handle(CHAT, "/resume 1"))
    assert "already cleared" in reply
    assert "#2 nuclear" in reply
    assert "yes " not in reply  # no confirmation code was issued
    assert one(bot.handle(CHAT, "yes AB12")) == "Nothing is waiting for confirmation."
    assert freqtrade.control_calls == []


def test_resume_of_a_cleared_halt_with_nothing_active(
    bot: CommandProcessor,
    ledger: SqliteLedger,
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    engage_halt(
        ledger, halt_type=HaltType.KILL_SWITCH, reason="r", actor="op", now=clock, notifier=notifier
    )
    freqtrade.state = "paused"
    bot.handle(CHAT, "/resume 1")
    bot.handle(CHAT, "yes AB12")
    reply = one(bot.handle(CHAT, "/resume 1"))
    assert "already cleared" in reply and "No active halts" in reply
