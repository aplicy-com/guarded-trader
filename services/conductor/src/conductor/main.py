"""Composition root: wires settings, DB, scheduler and adapters into the FastAPI app."""

import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI, Request, Response
from pydantic import ValidationError

from conductor import __version__
from conductor.adapters.boc_valet import BankOfCanadaFx
from conductor.adapters.telegram_bot import TelegramBot
from conductor.application.backup import ObjectStore, run_backup
from conductor.application.fence import run_daily_fence
from conductor.application.health import check_health
from conductor.application.heartbeat import (
    HeartbeatDecision,
    HeartbeatLog,
    RiskCycleMonitor,
    decide_heartbeat,
)
from conductor.application.ingest import FreqtradeInstance, run_ingest
from conductor.application.isolation import IsolationCheckUnavailableError
from conductor.application.ledger_ports import FxRateProvider, Ledger
from conductor.application.notify import safe_send
from conductor.application.ports import Heartbeat, Notifier
from conductor.application.reachability import ReachabilityTracker
from conductor.application.risk import RiskReport, run_risk_cycle
from conductor.application.startup import run_startup_checks
from conductor.application.tax import value_closed_trades
from conductor.application.telegram_commands import CommandProcessor
from conductor.domain.capital import PrincipalMismatchError
from conductor.domain.isolation import AccountIsolationError
from conductor.domain.risk import RiskLimits
from conductor.infrastructure.config import Settings, load_settings
from conductor.infrastructure.dashboard import dashboard_router, static_files
from conductor.infrastructure.db import create_db_engine, create_session_factory, journal_mode_probe
from conductor.infrastructure.freqtrade_instances import build_instances
from conductor.infrastructure.http import router
from conductor.infrastructure.ledger_repository import SqliteLedger
from conductor.infrastructure.logging import configure_logging
from conductor.infrastructure.notifier import build_notifier
from conductor.infrastructure.observability import (
    build_backup_sources,
    build_heartbeat,
    build_object_store,
    build_snapshotter,
)
from conductor.infrastructure.scheduler import LedgerJobs, build_scheduler

log = structlog.get_logger()

# Startup refusals: the process must exit non-zero rather than serve (R1, R5).
STARTUP_REFUSALS = (PrincipalMismatchError, AccountIsolationError, IsolationCheckUnavailableError)


# The dashboard loads only its own files (htmx and Chart.js are vendored) and never framed.
DASHBOARD_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def create_app(
    settings: Settings | None = None,
    *,
    instances: list[FreqtradeInstance] | None = None,
    fx: FxRateProvider | None = None,
    notifier: Notifier | None = None,
    bot: TelegramBot | None = None,
    heartbeat: Heartbeat | None = None,
    backup_store: ObjectStore | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> FastAPI:
    """Build the app and run the startup gate (raises one of STARTUP_REFUSALS to refuse)."""
    settings = settings or load_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    ledger: Ledger = SqliteLedger(session_factory)

    closers: list[Callable[[], None]] = []
    token = settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else None
    if notifier is None:
        notifier, notifier_closers = build_notifier(settings)
        closers.extend(notifier_closers)
    if heartbeat is None:
        heartbeat, heartbeat_closers = build_heartbeat(settings)
        closers.extend(heartbeat_closers)
    if instances is None:
        instances, instance_closers = build_instances(settings)
        closers.extend(instance_closers)
    if fx is None:
        boc = BankOfCanadaFx()
        closers.append(boc.close)
        fx = boc

    try:
        run_startup_checks(
            mode=settings.trading_mode,
            ledger=ledger,
            instances=instances,
            notifier=notifier,
            principal=settings.principal_usd,
            now=clock,
        )
    except BaseException:
        engine.dispose()
        for close in closers:
            close()
        raise

    if bot is None and token is not None and settings.telegram_commands_enabled:
        bot = TelegramBot(
            token,
            settings.telegram_allowed_chat_ids,
            CommandProcessor(
                ledger=ledger,
                instances=instances,
                trading_mode=settings.trading_mode,
                notifier=notifier,
                now=clock,
            ),
        )
    tracker = ReachabilityTracker()
    risk_monitor = RiskCycleMonitor()
    heartbeat_log = HeartbeatLog()
    if backup_store is None and settings.backup_enabled:
        backup_store = build_object_store(settings)
    backup_job: Callable[[], object] | None = None
    if backup_store is not None:
        store = backup_store
        snapshotter = build_snapshotter()
        sources = build_backup_sources(settings)
        backup_job = lambda: run_backup(  # noqa: E731
            ledger, sources, snapshotter, store, now=clock, notifier=notifier
        )
    limits = RiskLimits(
        daily_loss_limit_pct=settings.daily_loss_limit_pct,
        max_drawdown_pct=settings.max_drawdown_pct,
        consecutive_loss_limit=settings.consecutive_loss_limit,
        max_positions=settings.max_concurrent_positions,
    )

    def run_risk() -> RiskReport:
        report = run_risk_cycle(
            ledger, instances, limits, now=clock, notifier=notifier, tracker=tracker
        )
        risk_monitor.record_success(clock())  # only reached if the cycle did not raise
        return report

    jobs = LedgerJobs(
        ingest=lambda: run_ingest(ledger, instances, now=clock, notifier=notifier),
        fence=lambda: (
            run_ingest(ledger, instances, now=clock, notifier=notifier),  # fresh profit first
            run_daily_fence(
                ledger,
                daily_profit_cap=settings.daily_profit_cap_usd,
                manual_move_threshold=settings.manual_move_threshold_usd,
                now=clock,
                notifier=notifier,
            ),
        ),
        valuation=lambda: value_closed_trades(ledger, fx, now=clock),
        ingest_interval_seconds=settings.ingest_interval_seconds,
        risk=run_risk,
        risk_interval_seconds=settings.risk_check_interval_seconds,
        backup=backup_job,
    )
    db_probe = journal_mode_probe(engine)

    def heartbeat_decision() -> HeartbeatDecision:
        report = check_health(
            db_probe,
            lambda: bool(scheduler.running),
            scheduler_required=settings.scheduler_enabled,
        )
        return decide_heartbeat(
            report,
            risk_monitor.last_success,
            clock(),
            risk_cycle_required=settings.scheduler_enabled,
        )

    scheduler = build_scheduler(
        heartbeat,
        heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
        ledger_jobs=jobs,
        heartbeat_decision=heartbeat_decision,
        heartbeat_history=heartbeat_log,
        clock=clock,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info(
            "conductor_starting", version=__version__, trading_mode=settings.trading_mode.value
        )
        if bot is not None:
            bot.start()  # best effort: a dead bot never affects the risk checks
        safe_send(
            notifier,
            f"Conductor started: v{__version__}, mode={settings.trading_mode.value}, "
            f"telegram={'on' if bot is not None else 'off'}, "
            f"heartbeat={'on' if settings.healthchecks_ping_url else 'off'}, "
            f"backup={'on' if backup_job is not None else 'off'}",
        )
        if settings.scheduler_enabled:
            scheduler.start()
        try:
            yield
        finally:
            if bot is not None:
                bot.stop()
            if scheduler.running:
                scheduler.shutdown(wait=False)
            engine.dispose()
            for close in closers:
                close()
            log.info("conductor_stopped")

    app = FastAPI(
        title="Conductor",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.ledger = ledger
    app.state.scheduler = scheduler
    app.state.db_probe = db_probe
    app.state.clock = clock
    app.state.heartbeat_log = heartbeat_log
    app.include_router(router)
    app.include_router(dashboard_router)
    app.mount("/static", static_files(), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[..., Awaitable[Response]]):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        for name, value in DASHBOARD_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    return app


def app_factory() -> FastAPI:
    """uvicorn --factory entrypoint. Exits non-zero with a clear message on bad config
    or when a startup safety check refuses to let Conductor run."""
    try:
        return create_app()
    except ValidationError as exc:
        # Print field names + reasons only; never echo values (they may be secrets).
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "settings"
            print(f"CONFIG ERROR: {loc}: {err['msg']}", file=sys.stderr)
        sys.exit(1)
    except STARTUP_REFUSALS as exc:
        print(f"STARTUP REFUSED: {exc}", file=sys.stderr)
        sys.exit(1)
