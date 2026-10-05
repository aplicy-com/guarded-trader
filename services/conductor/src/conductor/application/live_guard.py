"""Live-pilot guards: Freqtrade's mode must match Conductor's, and R5 must hold before any start.

Two failure directions matter. Conductor thinking `dry_run` while Freqtrade trades for real would
let real orders happen under paper-trading assumptions (no isolation check, wrong ledger).
Conductor thinking `live` while Freqtrade is dry-running would record simulated trades as real
ones in the live ledger. Both are refused, at startup and again before Conductor ever starts a
freshly booted Freqtrade.
"""

from collections.abc import Callable

from conductor.application.ingest import FreqtradeInstance
from conductor.application.isolation import IsolationCheckUnavailableError, isolation_rows
from conductor.application.ledger_ports import Ledger
from conductor.domain.freqtrade_view import BotConfigView
from conductor.domain.trading_mode import TradingMode

# Returns why this instance must NOT be started now, or None if it may be.
StartGate = Callable[[FreqtradeInstance, BotConfigView], str | None]


class ModeMismatchError(RuntimeError):
    """Freqtrade's real mode contradicts TRADING_MODE: Conductor must not run (fail closed)."""


def mode_mismatch(mode: TradingMode, config: BotConfigView) -> str | None:
    """Why ``config`` contradicts ``mode``, or None if they agree."""
    if mode is TradingMode.DRY_RUN:
        if not config.dry_run:
            return (
                "Freqtrade has dry_run=false (REAL orders) but TRADING_MODE is dry_run: "
                "Conductor would run without its live protections"
            )
        return None
    problems: list[str] = []
    if config.dry_run:
        problems.append("Freqtrade has dry_run=true but TRADING_MODE is live")
    if config.exchange.lower() != "kraken":
        problems.append(f"exchange is {config.exchange!r}, expected kraken")
    if config.trading_mode != "spot":
        problems.append(f"trading_mode is {config.trading_mode!r}, expected spot")
    return "; ".join(problems) or None


def verify_mode(mode: TradingMode, instances: list[FreqtradeInstance]) -> None:
    """Startup: every reachable instance must agree with ``mode``.

    dry_run tolerates an unreachable Freqtrade (the compose healthcheck orders startup and the
    risk cycle reports reachability); live does not: unverified means no start.
    """
    for inst in instances:
        try:
            config = inst.reader.show_config()
        except Exception as exc:
            if mode is TradingMode.LIVE:
                raise IsolationCheckUnavailableError(
                    f"cannot read Freqtrade's config for {inst.name!r}; refusing live start"
                ) from exc
            continue
        problem = mode_mismatch(mode, config)
        if problem is not None:
            raise ModeMismatchError(f"{inst.name}: {problem}")


def make_start_gate(mode: TradingMode, ledger: Ledger) -> StartGate:
    """The gate Conductor applies before it starts a freshly booted Freqtrade."""

    def gate(inst: FreqtradeInstance, config: BotConfigView) -> str | None:
        problem = mode_mismatch(mode, config)
        if problem is not None:
            return problem
        if mode is not TradingMode.LIVE:
            return None
        try:
            rows = isolation_rows(ledger, inst)
        except Exception as exc:
            return f"cannot verify R5 account isolation ({type(exc).__name__})"
        bad = [f"{r.asset} unexplained {r.unexplained}" for r in rows if r.unexplained > 0]
        if bad:
            return "R5 account isolation: " + ", ".join(bad)
        return None

    return gate
