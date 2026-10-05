"""Telegram command logic, independent of any Telegram library.

`handle(chat_id, text)` returns the reply lines; the bot adapter only decides
WHO may call it (the chat-ID allowlist) and delivers the replies. Every write
goes through the existing use cases (kill_switch, nuclear, clear_halt) and only
after a `yes <code>` confirmation from the same chat within 60 s. There is no
command that opens, modifies or sizes a trade.
"""

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import structlog

from conductor.application.capital import PrincipalNotSetError, capital_from_ledger
from conductor.application.halts import StepResult, clear_halt, kill_switch, nuclear
from conductor.application.ingest import FreqtradeInstance
from conductor.application.ledger_ports import Ledger
from conductor.application.ports import Notifier
from conductor.application.risk import build_risk_inputs
from conductor.domain.confirmation import ConfirmationBook, Outcome
from conductor.domain.trading_mode import TradingMode

log = structlog.get_logger()
Clock = Callable[[], datetime]

READ_COMMANDS = ("/status", "/capital", "/halts", "/trades", "/help")
WRITE_COMMANDS = ("/kill", "/flatten", "/resume")
ZERO = Decimal(0)

HELP = """Conductor commands
/status  halts, open positions, today's P&L, mode
/capital  principal, working profit, fenced, max deployed
/halts  active halts
/trades  last 10 closed trades
/kill  block new entries (asks to confirm)
/flatten  cancel orders, close ALL positions, stop (asks to confirm)
/resume <halt_id>  clear a halt and resume (asks to confirm)
Writes need: yes <code> within 60 s. Nothing here can open a trade."""


def usd(value: Decimal) -> str:
    return f"{value:.2f}"


def signed(value: Decimal) -> str:
    return f"{value:+.2f}"


class CommandProcessor:
    def __init__(
        self,
        *,
        ledger: Ledger,
        instances: list[FreqtradeInstance],
        trading_mode: TradingMode,
        notifier: Notifier,
        now: Clock = lambda: datetime.now(UTC),
        book: ConfirmationBook | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._ledger = ledger
        self._instances = instances
        self._mode = trading_mode
        self._notifier = notifier
        self._now = now
        self._book = book or ConfirmationBook()
        self._sleep = sleep
        self._lock = threading.Lock()

    # ---- entry point ----------------------------------------------------------

    def handle(self, chat_id: int, text: str) -> list[str]:
        text = text.strip()
        operator = f"telegram:{chat_id}"
        if text.lower().startswith("yes"):
            return self._on_confirmation(chat_id, text, operator)
        if not text.startswith("/"):
            return []
        command, _, arg = text.partition(" ")
        command = command.split("@")[0].lower()  # "/status@MyBot" in groups
        arg = arg.strip()
        try:
            if command in ("/help", "/start"):
                return [HELP]
            if command == "/status":
                return [self._status()]
            if command == "/capital":
                return [self._capital()]
            if command == "/halts":
                return [self._halts()]
            if command == "/trades":
                return [self._trades()]
            if command == "/kill":
                return [self._ask(chat_id, "kill", "KILL SWITCH: block all new entries")]
            if command == "/flatten":
                return [
                    self._ask(
                        chat_id,
                        "flatten",
                        "FLATTEN: cancel open orders, market-close ALL positions, stop the bot",
                    )
                ]
            if command == "/resume":
                return [self._ask_resume(chat_id, arg)]
        except Exception:
            log.exception("telegram_command_failed", command=command)
            return ["Command failed (see Conductor logs). Nothing was changed unless stated above."]
        return ["Unknown command. /help lists what exists."]

    # ---- confirmation ---------------------------------------------------------

    def _ask(self, chat_id: int, action: str, description: str) -> str:
        with self._lock:
            pending = self._book.request(chat_id, action, self._now())
        return (
            f"{description}\n"
            f"Reply `yes {pending.code}` within 60 s to confirm. Otherwise nothing happens."
        )

    def _on_confirmation(self, chat_id: int, text: str, operator: str) -> list[str]:
        with self._lock:  # pop-and-decide is atomic: a double "yes" can run the action once
            result = self._book.confirm(chat_id, text, self._now())
        if result.outcome is Outcome.NOT_A_CONFIRMATION:
            return []
        if result.outcome is Outcome.NOTHING_PENDING:
            return ["Nothing is waiting for confirmation."]
        if result.outcome is Outcome.EXPIRED:
            return ["Confirmation expired (60 s). Nothing was done. Send the command again."]
        if result.outcome is Outcome.WRONG_CODE:
            return ["Wrong code. Nothing was done. Send the command again."]
        if result.action is None:  # unreachable: CONFIRMED always carries its action
            return ["Nothing is waiting for confirmation."]
        log.warning("telegram_write_confirmed", action=result.action, operator=operator)
        return self._execute(result.action, operator)

    def _execute(self, action: str, operator: str) -> list[str]:
        try:
            if action == "kill":
                r = kill_switch(
                    self._ledger,
                    self._instances,
                    operator=operator,
                    now=self._now,
                    notifier=self._notifier,
                )
                return [self._steps(f"Kill switch #{r.halt_id}", r.ok, r.steps)]
            if action == "flatten":
                r = nuclear(
                    self._ledger,
                    self._instances,
                    operator=operator,
                    now=self._now,
                    notifier=self._notifier,
                    sleep=self._sleep,
                )
                return [self._steps(f"Nuclear #{r.halt_id}", r.ok, r.steps)]
            if action.startswith("resume:"):
                c = clear_halt(
                    self._ledger,
                    self._instances,
                    halt_id=int(action.split(":", 1)[1]),
                    operator=operator,
                    note="via telegram",
                    now=self._now,
                    notifier=self._notifier,
                )
                head = (
                    "Cleared" if c.newly_cleared else "Already cleared"
                ) + f" halt #{c.halt_id}."
                lines = [head]
                lines += [f"Still active: #{h.id} {h.halt_type.value}" for h in c.still_active]
                lines += [
                    f"  {s.instance}: {s.step}: {'ok' if s.ok else 'FAILED ' + s.detail}"
                    for s in c.resumed
                ]
                if not c.ok:
                    lines.append(
                        "Resume failed: Freqtrade stays paused (safe). Send /resume again."
                    )
                return ["\n".join(lines)]
        except Exception:
            log.exception("telegram_action_failed", action=action)
            return ["The action raised an error; check Conductor logs and /halts."]
        return ["Unknown action."]

    @staticmethod
    def _steps(title: str, ok: bool, steps: tuple[StepResult, ...]) -> str:
        lines = [f"{title}: " + ("all steps ok" if ok else "NOT every step succeeded")]
        lines += [
            f"  {s.instance}: {s.step}: {'ok' if s.ok else 'FAILED ' + s.detail}" for s in steps
        ]
        return "\n".join(lines)

    def _ask_resume(self, chat_id: int, arg: str) -> str:
        if not arg.isdigit():
            with self._ledger.transaction(write=False) as repo:
                active = repo.active_halts()
            listing = "\n".join(f"#{h.id} {h.halt_type.value}" for h in active) or "no active halts"
            return f"Usage: /resume <halt_id>\n{listing}"
        halt_id = int(arg)
        with self._ledger.transaction(write=False) as repo:
            halt = repo.get_halt(halt_id)
            still_active = repo.is_halt_active(halt_id)
        if halt is None:
            return f"No halt #{halt_id}. /halts lists active ones."
        what = "" if still_active else " (already cleared: this only re-sends resume to Freqtrade)"
        return self._ask(
            chat_id,
            f"resume:{halt_id}",
            f"RESUME: clear halt #{halt_id} [{halt.halt_type.value}] and resume trading{what}.\n"
            f"Reason was: {halt.reason}",
        )

    # ---- read commands --------------------------------------------------------

    def _status(self) -> str:
        at = self._now().astimezone(UTC)
        lines = [f"Mode: {self._mode.value}"]
        with self._ledger.transaction(write=False) as repo:
            halts = repo.active_halts()
            positions = repo.open_positions()
            inputs = build_risk_inputs(
                repo, [i.name for i in self._instances], at, equity_known=True
            )
        if halts:
            lines.append(f"HALTED ({len(halts)}):")
            lines += [f"  #{h.id} {h.halt_type.value}: {h.reason}" for h in halts]
        else:
            lines.append("Halts: none")
        for inst in self._instances:
            try:
                state = inst.reader.show_config().state or "unknown"
            except Exception:
                state = "unreachable"
            lines.append(f"Freqtrade {inst.name}: {state}")
        if positions:
            lines.append(f"Open positions ({len(positions)}):")
            lines += [f"  {p.instance} {p.pair} stake {usd(p.stake_amount)} USD" for p in positions]
        else:
            lines.append("Open positions: none")
        if inputs.equity_now is None:
            lines.append("Today P&L: unknown (no equity snapshot yet)")
        else:
            lines.append(
                f"Today P&L (UTC): {signed(inputs.equity_now - inputs.daily_start_equity)} USD "
                f"(equity {usd(inputs.equity_now)})"
            )
        return "\n".join(lines)

    def _capital(self) -> str:
        try:
            with self._ledger.transaction(write=False) as repo:
                c = capital_from_ledger(repo)
        except PrincipalNotSetError:
            return "Principal is not recorded yet."
        return (
            f"Principal: {usd(c.principal)} USD\n"
            f"Realized profit: {signed(c.realized_profit)} USD\n"
            f"Fenced: {usd(c.fenced_total)} USD\n"
            f"Working profit: {signed(c.working_profit)} USD\n"
            f"Max deployed capital: {usd(c.max_deployed_capital)} USD"
        )

    def _halts(self) -> str:
        with self._ledger.transaction(write=False) as repo:
            active = repo.active_halts()
        if not active:
            return "No active halts."
        return "\n".join(
            f"#{h.id} {h.halt_type.value} [{h.instance or 'all'}] since "
            f"{h.created_at:%Y-%m-%d %H:%M}Z by {h.created_by}: {h.reason}"
            for h in active
        )

    def _trades(self) -> str:
        with self._ledger.transaction(write=False) as repo:
            trades = repo.recent_closed_trades(10)
        if not trades:
            return "No closed trades yet."
        return "\n".join(
            f"{t.close_date:%m-%d %H:%M}Z {t.pair} {signed(t.profit)} USD "
            f"({t.exit_reason or 'n/a'})"
            for t in trades
        )
