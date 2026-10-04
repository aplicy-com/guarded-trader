from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from conductor import __version__
from conductor.application.health import check_health

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str
    trading_mode: str
    db_ok: bool
    db_journal_mode: str
    scheduler_running: bool


@router.get("/health", response_model=HealthResponse)
def health(request: Request, response: Response) -> HealthResponse:
    """Internal liveness/readiness. Not published to the host; used by the container healthcheck."""
    state = request.app.state
    report = check_health(
        state.db_probe,
        lambda: bool(state.scheduler.running),
        scheduler_required=state.settings.scheduler_enabled,
    )
    if not report.ok:
        response.status_code = 503
    return HealthResponse(
        status="ok" if report.ok else "unhealthy",
        version=__version__,
        trading_mode=state.settings.trading_mode.value,
        db_ok=report.db_ok,
        db_journal_mode=report.db_journal_mode,
        scheduler_running=report.scheduler_running,
    )
