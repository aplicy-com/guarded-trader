"""Composition root: wires settings, DB, scheduler and adapters into the FastAPI app."""

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from pydantic import ValidationError

from conductor import __version__
from conductor.adapters.healthchecks import LogHeartbeat
from conductor.infrastructure.config import Settings, load_settings
from conductor.infrastructure.db import create_db_engine, create_session_factory, journal_mode_probe
from conductor.infrastructure.http import router
from conductor.infrastructure.logging import configure_logging
from conductor.infrastructure.scheduler import build_scheduler

log = structlog.get_logger()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    engine = create_db_engine(settings.database_url)
    scheduler = build_scheduler(
        LogHeartbeat(), heartbeat_interval_seconds=settings.heartbeat_interval_seconds
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
    app.state.session_factory = create_session_factory(engine)
    app.state.scheduler = scheduler
    app.state.db_probe = journal_mode_probe(engine)
    app.include_router(router)
    return app


def app_factory() -> FastAPI:
    """uvicorn --factory entrypoint. Exits non-zero with a clear message on bad config."""
    try:
        return create_app()
    except ValidationError as exc:
        # Print field names + reasons only; never echo values (they may be secrets).
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "settings"
            print(f"CONFIG ERROR: {loc}: {err['msg']}", file=sys.stderr)
        sys.exit(1)
