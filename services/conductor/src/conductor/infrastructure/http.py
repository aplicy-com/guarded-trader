from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from conductor import __version__
from conductor.application.capital import PrincipalNotSetError, get_capital
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


class CapitalResponse(BaseModel):
    """Decimal amounts as strings, so no client ever sees a float."""

    principal: str
    realized_profit: str
    fenced_total: str
    working_profit: str
    max_deployed_capital: str
    enforced: bool  # always False in 3A-2: computed only, nothing is written to Freqtrade


@router.get("/capital", response_model=CapitalResponse)
def capital(request: Request, response: Response) -> CapitalResponse:
    """Internal (no host port). R2 `max_deployed_capital`, computed from the ledger."""
    try:
        c = get_capital(request.app.state.ledger)
    except PrincipalNotSetError:
        response.status_code = 503
        raise HTTPException(status_code=503, detail="principal not recorded") from None
    return CapitalResponse(
        principal=str(c.principal),
        realized_profit=str(c.realized_profit),
        fenced_total=str(c.fenced_total),
        working_profit=str(c.working_profit),
        max_deployed_capital=str(c.max_deployed_capital),
        enforced=False,
    )
