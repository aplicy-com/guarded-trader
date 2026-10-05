from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from conductor.application.capital import PrincipalNotSetError
from conductor.application.dashboard import (
    build_equity_curve,
    build_halts,
    build_overview,
    build_positions,
)
from conductor.domain.trading_mode import TradingMode

HERE = Path(__file__).parent
CENT = Decimal("0.01")
# Dashboard reads are all GETs: HEAD comes for free, anything else is a 405.
dashboard_router = APIRouter()


def usd(value: Decimal | None) -> str:
    if value is None:
        return "n/a"
    q = value.quantize(CENT, rounding=ROUND_HALF_EVEN)
    return f"-${-q:,.2f}" if q < 0 else f"${q:,.2f}"


def stamp(value: datetime | None) -> str:
    return "never" if value is None else value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def ago(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "never"
    seconds = int((now - value).total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} min ago"
    if seconds < 36 * 3600:
        return f"{round(seconds / 3600)} h ago"
    return f"{round(seconds / 86400)} d ago"


def sign_class(value: Decimal | None) -> str:
    if value is None or value == 0:
        return ""
    return "pos" if value > 0 else "neg"


templates = Jinja2Templates(directory=str(HERE / "templates"))  # autoescape on for .html
templates.env.filters.update({"usd": usd, "stamp": stamp, "ago": ago, "sign": sign_class})


def static_files() -> StaticFiles:
    return StaticFiles(directory=str(HERE / "static"))


def _render(request: Request, name: str, **context: Any) -> HTMLResponse:
    now = request.app.state.clock()
    live = request.app.state.settings.trading_mode is TradingMode.LIVE
    return templates.TemplateResponse(
        request, name, {"now": now, "live": live, "active": context.pop("active", ""), **context}
    )


def _overview(request: Request) -> Any:
    state = request.app.state
    try:
        return build_overview(
            state.ledger,
            now=state.clock(),
            trading_mode=state.settings.trading_mode.value,
            heartbeat=state.heartbeat_log,
            backup_configured=state.settings.backup_enabled,
        )
    except PrincipalNotSetError:
        raise HTTPException(status_code=503, detail="principal not recorded yet") from None


@dashboard_router.get("/", response_class=HTMLResponse)
def overview_page(request: Request) -> HTMLResponse:
    return _render(request, "overview.html", active="overview", o=_overview(request))


@dashboard_router.get("/partials/overview", response_class=HTMLResponse)
def overview_partial(request: Request) -> HTMLResponse:
    return _render(request, "_overview.html", o=_overview(request))


@dashboard_router.get("/data/equity.json")
def equity_json(request: Request) -> JSONResponse:
    state = request.app.state
    points = build_equity_curve(state.ledger, now=state.clock())
    return JSONResponse(
        {
            "unit": "USD",
            "points": [{"t": p.at.astimezone(UTC).isoformat(), "v": str(p.equity)} for p in points],
        }
    )


@dashboard_router.get("/positions", response_class=HTMLResponse)
def positions_page(request: Request) -> HTMLResponse:
    return _render(
        request,
        "positions.html",
        active="positions",
        p=build_positions(request.app.state.ledger),
    )


@dashboard_router.get("/partials/positions", response_class=HTMLResponse)
def positions_partial(request: Request) -> HTMLResponse:
    return _render(request, "_positions.html", p=build_positions(request.app.state.ledger))


@dashboard_router.get("/halts", response_class=HTMLResponse)
def halts_page(request: Request) -> HTMLResponse:
    return _render(request, "halts.html", active="halts", h=build_halts(request.app.state.ledger))


@dashboard_router.get("/strategies", response_class=HTMLResponse)
def strategies_page(request: Request) -> HTMLResponse:
    return _render(request, "placeholder.html", active="strategies", title="Strategies & pipeline")


@dashboard_router.get("/research", response_class=HTMLResponse)
def research_page(request: Request) -> HTMLResponse:
    return _render(request, "placeholder.html", active="research", title="Research runs")
