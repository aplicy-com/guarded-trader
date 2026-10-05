"""Risk cycle (3A-3): ingest, evaluate R4/R2/R7 from the ledger, halt, enforce.

One cycle, every `RISK_CHECK_INTERVAL_SECONDS`. After enforcing halts it starts a freshly
booted (paused) Freqtrade if no halt is active (`boot.start_if_clear`, ADR-0018).
Equity is the ledger's
(`principal + realized + unrealized`); Freqtrade's own numbers are never used
for the R4 limits. A breach creates a persisted halt and pauses entries; only a
human clears it (`halts.clear_halt`). After a clear, each breaker measures from
the clear (daily loss window start, drawdown peak, loss streak), so a human
re-enable resets that breaker without silencing it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import structlog

from conductor.application.boot import BootGuard, start_if_clear
from conductor.application.capital import capital_from_ledger
from conductor.application.halts import StepResult, enforce_halts, engage_halt
from conductor.application.ingest import FreqtradeInstance, IngestReport, run_ingest
from conductor.application.ledger_ports import EquitySnapshot, Ledger, LedgerRepo
from conductor.application.notify import safe_send
from conductor.application.ports import Notifier
from conductor.application.reachability import ReachabilityTracker
from conductor.domain.halt import HaltType
from conductor.domain.risk import (
    Breach,
    RiskInputs,
    RiskLimits,
    evaluate_risk,
    loss_streak,
)

log = structlog.get_logger()
Clock = Callable[[], datetime]
ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class RiskReport:
    ingest: IngestReport
    breaches: tuple[Breach, ...]
    new_halt_ids: tuple[int, ...]
    enforcement: tuple[StepResult, ...]
    equity_known: bool
    boot: tuple[StepResult, ...] = ()


def _equity_of(snap: EquitySnapshot | None, principal: Decimal) -> Decimal:
    """Ledger equity in force at a snapshot (realized-only if unrealized was unknown)."""
    if snap is None:
        return principal
    if snap.equity is not None:
        return snap.equity
    return snap.principal + snap.realized_profit


def build_risk_inputs(
    repo: LedgerRepo, instance_names: list[str], at: datetime, *, equity_known: bool
) -> RiskInputs:
    cap = capital_from_ledger(repo)
    latest = repo.latest_snapshot()
    equity_now = latest.equity if (equity_known and latest is not None) else None

    day_start = datetime(at.year, at.month, at.day, tzinfo=UTC)
    cleared = repo.last_clear_at(HaltType.DAILY_LOSS, None)
    window_start = max(day_start, cleared) if cleared else day_start
    start_snap = repo.snapshot_at(window_start)
    if start_snap is not None:
        start_equity = _equity_of(start_snap, cap.principal)
    else:
        # No ledger history yet at the window start (e.g. first day after deploy): the
        # starting equity is the principal plus what was already realized before it, so
        # an old loss is never mistaken for today's. Unrealized at that time is unknown (0).
        start_equity = cap.principal + repo.realized_profit_before(window_start)
    base = start_snap.max_deployed_capital if start_snap else cap.principal

    ref = repo.last_clear_at(HaltType.MAX_DRAWDOWN, None)
    seen = [s.equity for s in repo.snapshots_since(ref) if s.equity is not None]
    baseline = _equity_of(repo.snapshot_at(ref), cap.principal) if ref else cap.principal
    peak = max([baseline, *seen, *([equity_now] if equity_now is not None else [])])

    streaks = {
        name: loss_streak(
            repo.closed_profits(name, repo.last_clear_at(HaltType.CONSECUTIVE_LOSSES, name))
        )
        for name in instance_names
    }
    positions = repo.open_positions()
    return RiskInputs(
        equity_now=equity_now,
        daily_start_equity=start_equity,
        daily_base_capital=base if base > ZERO else cap.principal,
        equity_peak=peak,
        loss_streaks=streaks,
        open_positions=len(positions),
        open_exposure=sum((p.stake_amount for p in positions), ZERO),
        max_deployed_capital=cap.max_deployed_capital,
    )


def run_risk_cycle(
    ledger: Ledger,
    instances: list[FreqtradeInstance],
    limits: RiskLimits,
    *,
    now: Clock,
    notifier: Notifier,
    tracker: ReachabilityTracker | None = None,
    boot_guard: BootGuard | None = None,
) -> RiskReport:
    ingest = run_ingest(ledger, instances, now=now, notifier=notifier)
    if tracker is not None:
        for inst in instances:
            text = tracker.update(inst.name, inst.name not in ingest.failed_instances, now())
            if text is not None:
                safe_send(notifier, text)
    equity_known = not ingest.failed_instances
    if not equity_known:
        log.warning("risk_equity_unknown", failed_instances=list(ingest.failed_instances))
    at = now().astimezone(UTC)
    with ledger.transaction(write=False) as repo:
        inputs = build_risk_inputs(repo, [i.name for i in instances], at, equity_known=equity_known)
    breaches = evaluate_risk(limits, inputs)
    new_ids: list[int] = []
    for b in breaches:
        halt_id, created = engage_halt(
            ledger,
            halt_type=b.halt_type,
            reason=b.reason,
            actor="system",
            now=now,
            notifier=notifier,
            instance=b.instance,
        )
        if created:
            new_ids.append(halt_id)
    enforcement = enforce_halts(ledger, instances)
    boot: tuple[StepResult, ...] = ()
    if boot_guard is not None:  # last: this cycle's halts must already be in the ledger
        boot = start_if_clear(
            ledger, instances, boot_guard, equity_known=equity_known, notifier=notifier
        )
    return RiskReport(ingest, breaches, tuple(new_ids), enforcement, equity_known, boot)
