"""Composition root: wires settings, DB, scheduler and adapters into the FastAPI app."""

import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI
from pydantic import ValidationError

from conductor import __version__
from conductor.adapters.boc_valet import BankOfCanadaFx
from conductor.adapters.healthchecks import LogHeartbeat
from conductor.adapters.telegram import LogNotifier
from conductor.application.fence import run_daily_fence
from conductor.application.ingest import FreqtradeInstance, run_ingest
from conductor.application.isolation import IsolationCheckUnavailableError
from conductor.application.ledger_ports import FxRateProvider, Ledger
from conductor.application.ports import Notifier
from conductor.application.risk import run_risk_cycle
from conductor.application.startup import run_startup_checks
from conductor.application.tax import value_closed_trades
from conductor.domain.capital import PrincipalMismatchError
from conductor.domain.isolation import AccountIsolationError
from conductor.domain.risk import RiskLimits
from conductor.infrastructure.config import Settings, load_settings
from conductor.infrastructure.db import create_db_engine, create_session_factory, journal_mode_probe
from conductor.infrastructure.freqtrade_instances import build_instances
from conductor.infrastructure.http import router
from conductor.infrastructure.ledger_repository import SqliteLedger
from conductor.infrastructure.logging import configure_logging
from conductor.infrastructure.scheduler import LedgerJobs, build_scheduler

log = structlog.get_logger()

# Startup refusals: the process must exit non-zero rather than serve (R1, R5).
STARTUP_REFUSALS = (PrincipalMismatchError, AccountIsolationError, IsolationCheckUnavailableError)


def utc_now() -> datetime:
    return datetime.now(UTC)


def create_app(
    settings: Settings | None = None,
    *,
    instances: list[FreqtradeInstance] | None = None,
    fx: FxRateProvider | None = None,
    notifier: Notifier | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> FastAPI:
    """Build the app and run the startup gate (raises one of STARTUP_REFUSALS to refuse)."""
    settings = settings or load_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    ledger: Ledger = SqliteLedger(session_factory)
    notifier = notifier or LogNotifier()

    closers: list[Callable[[], None]] = []
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

    limits = RiskLimits(
        daily_loss_limit_pct=settings.daily_loss_limit_pct,
        max_drawdown_pct=settings.max_drawdown_pct,
        consecutive_loss_limit=settings.consecutive_loss_limit,
        max_positions=settings.max_concurrent_positions,
    )
    jobs = LedgerJobs(
        ingest=lambda: run_ingest(ledger, instances, now=clock),
        fence=lambda: (
            run_ingest(ledger, instances, now=clock),  # fresh profit first, best effort
            run_daily_fence(
                ledger,
                daily_profit_cap=settings.daily_profit_cap_usd,
                manual_move_threshold=settings.manual_move_threshold_usd,
                now=clock,
            ),
        ),
        valuation=lambda: value_closed_trades(ledger, fx, now=clock),
        ingest_interval_seconds=settings.ingest_interval_seconds,
        risk=lambda: run_risk_cycle(ledger, instances, limits, now=clock, notifier=notifier),
        risk_interval_seconds=settings.risk_check_interval_seconds,
    )
    scheduler = build_scheduler(
        LogHeartbeat(),
        heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
        ledger_jobs=jobs,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info(
            "conductor_starting", version=__version__, trading_mode=settings.trading_mode.value
        )
        if settings.scheduler_enabled:
            scheduler.start()
        try:
            yield
        finally:
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
    app.state.db_probe = journal_mode_probe(engine)
    app.include_router(router)
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
