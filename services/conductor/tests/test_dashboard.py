"""3A-5 dashboard: pages render from the ledger, and the surface is strictly read-only."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from conductor.application.backup import BACKUP_COMPLETED, BACKUP_FAILED
from conductor.application.dashboard import (
    EQUITY_MAX_POINTS,
    build_backup_view,
    downsample,
)
from conductor.application.heartbeat import HeartbeatLog
from conductor.application.ingest import FreqtradeInstance
from conductor.application.ledger_ports import AuditRow, EquitySnapshot
from conductor.domain.halt import HaltType
from conductor.domain.ledger import from_closed, from_open
from conductor.infrastructure.config import Settings
from conductor.infrastructure.dashboard import dashboard_router
from conductor.infrastructure.dashboard import routes as dash_routes
from conductor.infrastructure.http import router as http_router
from conductor.infrastructure.ledger_repository import SqliteLedger
from conductor.main import create_app
from fakes import Clock, FakeFreqtrade, FakeFx, closed_view, open_view

D = Decimal
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
PAGES = ["/", "/positions", "/halts", "/strategies", "/research"]
PARTIALS = ["/partials/overview", "/partials/positions"]


def make_client(settings: Settings, clock: Clock) -> TestClient:
    app = create_app(
        settings,
        instances=[FreqtradeInstance("primary", FakeFreqtrade(), FakeFreqtrade())],
        fx=FakeFx(),
        clock=clock,
    )
    return TestClient(app)


@pytest.fixture
def client(settings: Settings, clock: Clock) -> TestClient:
    with make_client(settings, clock) as c:
        yield c  # type: ignore[misc]


def seed(ledger: SqliteLedger) -> None:
    """A little history: two closed trades, one open, a halt (cleared), a halt (active),
    equity snapshots and a backup record."""
    with ledger.transaction() as repo:
        repo.upsert_trade("primary", from_closed(closed_view(1, "3.50")), NOW)
        repo.upsert_trade("primary", from_closed(closed_view(2, "-1.25", pair="SOL/USD")), NOW)
        repo.upsert_trade("primary", from_open(open_view(3, "BTC/USD")), NOW)
        h1 = repo.add_halt(
            HaltType.KILL_SWITCH, None, "manual kill", NOW - timedelta(days=2), "telegram:1"
        )
        repo.clear_halt(h1, NOW - timedelta(days=1), "telegram:1", "all clear")
        repo.add_halt(
            HaltType.DAILY_LOSS,
            "primary",
            "daily loss 3.2% >= 3%",
            NOW - timedelta(hours=1),
            "system",
        )
        for i in range(5):
            repo.add_snapshot(
                EquitySnapshot(
                    NOW - timedelta(hours=5 - i),
                    D(100),
                    D(2) + i,
                    D(1),
                    D(0),
                    D(2) + i,
                    D(100),
                    D(103) + i,
                )
            )
        repo.add_audit(
            NOW - timedelta(hours=9),
            "system",
            BACKUP_COMPLETED,
            {"label": "conductor", "key": "backups/conductor/x.gz", "sha256": "a" * 64},
        )


# --- pages render ---


@pytest.mark.parametrize("path", [*PAGES, *PARTIALS])
def test_every_page_renders_on_an_empty_ledger(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 200, path
    assert "text/html" in r.headers["content-type"]


def test_overview_shows_the_capital_figures_halt_state_and_monitoring(
    client: TestClient, ledger: SqliteLedger
) -> None:
    seed(ledger)
    html = client.get("/").text
    assert "$100.00" in html  # principal
    assert "TRADING HALTED" in html  # the active daily-loss halt
    assert "daily loss 3.2%" in html
    assert "Max deployed" in html and "Fenced" in html and "Working profit" in html
    assert "not configured" in html  # backups off in this test settings
    assert "none sent since start" in html  # no heartbeat has fired yet


def test_overview_without_halts_says_so(client: TestClient) -> None:
    html = client.get("/").text
    assert "No active halts" in html
    assert "TRADING HALTED" not in html


def test_positions_page_lists_open_and_closed_trades(
    client: TestClient, ledger: SqliteLedger
) -> None:
    seed(ledger)
    html = client.get("/positions").text
    assert "BTC/USD" in html  # open
    assert "$3.50" in html and "-$1.25" in html  # closed, signed
    assert "roi" in html


def test_halts_page_shows_halts_cleared_and_active_plus_audit_log(
    client: TestClient, ledger: SqliteLedger
) -> None:
    seed(ledger)
    html = client.get("/halts").text
    assert "kill_switch" in html and "all clear" not in html  # note is not shown, who/when is
    assert "ACTIVE" in html
    assert "telegram:1" in html
    assert BACKUP_COMPLETED in html  # the audit log section


def test_equity_json_is_decimal_strings_not_floats(
    client: TestClient, ledger: SqliteLedger
) -> None:
    seed(ledger)
    body = client.get("/data/equity.json").json()
    assert body["unit"] == "USD"
    assert [p["v"] for p in body["points"]] == ["103", "104", "105", "106", "107"]
    assert all(isinstance(p["v"], str) for p in body["points"])


def test_equity_json_only_covers_the_last_30_days(client: TestClient, ledger: SqliteLedger) -> None:
    with ledger.transaction() as repo:
        repo.add_snapshot(
            EquitySnapshot(NOW - timedelta(days=40), D(100), D(0), D(0), D(0), D(0), D(100), D(100))
        )
    assert client.get("/data/equity.json").json()["points"] == []


# --- heartbeat / backup status ---


def test_overview_reflects_the_heartbeat_log(client: TestClient) -> None:
    log: HeartbeatLog = client.app.state.heartbeat_log  # type: ignore[attr-defined]
    log.record(NOW - timedelta(minutes=2), "ok")
    assert (
        "ok" in client.get("/partials/overview").text
        and "2 min ago" in client.get("/partials/overview").text
    )
    log.record(NOW - timedelta(minutes=1), "fail_sent", "scheduler not running")
    html = client.get("/partials/overview").text
    assert "reported unhealthy" in html and "scheduler not running" in html
    log.record(NOW, "delivery_failed")
    assert "ping not delivered" in client.get("/partials/overview").text


def audit(i: int, at: datetime, action: str, **detail: object) -> AuditRow:
    return AuditRow(i, at, "system", action, detail)


def test_backup_view_fresh_stale_and_failing() -> None:
    fresh = build_backup_view(
        [
            audit(3, NOW - timedelta(hours=9), BACKUP_COMPLETED, label="conductor", key="k1"),
            audit(2, NOW - timedelta(hours=9), BACKUP_COMPLETED, label="freqtrade", key="k2"),
        ],
        configured=True,
        now=NOW,
    )
    assert not fresh.stale
    assert [s.label for s in fresh.sources] == ["conductor", "freqtrade"]
    assert not any(s.failing for s in fresh.sources)

    stale = build_backup_view(
        [audit(1, NOW - timedelta(hours=27), BACKUP_COMPLETED, label="conductor", key="k")],
        configured=True,
        now=NOW,
    )
    assert stale.stale
    assert build_backup_view([], configured=True, now=NOW).stale  # configured but never ran
    assert not build_backup_view([], configured=False, now=NOW).stale  # not configured: not "stale"

    failing = build_backup_view(
        [
            audit(
                5,
                NOW - timedelta(hours=1),
                BACKUP_FAILED,
                label="freqtrade",
                error="unable to open",
            ),
            audit(4, NOW - timedelta(hours=25), BACKUP_COMPLETED, label="freqtrade", key="old"),
        ],
        configured=True,
        now=NOW,
    )
    (src,) = failing.sources
    assert src.failing and src.last_error == "unable to open" and src.last_ok_key == "old"
    recovered = build_backup_view(
        [
            audit(6, NOW - timedelta(minutes=5), BACKUP_COMPLETED, label="freqtrade", key="new"),
            audit(5, NOW - timedelta(hours=1), BACKUP_FAILED, label="freqtrade", error="x"),
        ],
        configured=True,
        now=NOW,
    )
    assert not recovered.sources[0].failing


def test_overview_shows_backup_status_from_the_audit_log(
    settings: Settings, clock: Clock, ledger: SqliteLedger, db_path: Path
) -> None:
    from conftest import make_settings

    configured = make_settings(
        db_path,
        BACKUP_B2_BUCKET="b",
        BACKUP_B2_ENDPOINT="https://s3.us-west-004.backblazeb2.com",
        BACKUP_B2_KEY_ID="k",
        BACKUP_B2_APP_KEY="s",
    )
    seed(ledger)
    with make_client(configured, clock) as c:
        html = c.get("/").text
    assert "conductor:" in html and "9 h ago" in html
    assert "not configured" not in html


# --- thinning ---


def test_downsample_keeps_first_last_and_the_cap() -> None:
    items = list(range(5000))
    out = downsample(items, EQUITY_MAX_POINTS)
    assert len(out) <= EQUITY_MAX_POINTS
    assert out[0] == 0 and out[-1] == 4999
    assert out == sorted(out)
    assert downsample([1, 2, 3], 400) == [1, 2, 3]
    assert downsample([], 400) == []


# --- strictly read-only ---


def dashboard_paths() -> set[str]:
    return {*PAGES, *PARTIALS, "/data/equity.json"}


def test_dashboard_routes_are_get_only() -> None:
    seen = set()
    for route in dashboard_router.routes:
        assert isinstance(route, APIRoute)
        seen.add(route.path)
        assert route.methods == {"GET"}, (route.path, route.methods)
    assert seen == dashboard_paths()


@pytest.mark.parametrize("path", sorted(dashboard_paths()))
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_writes_are_rejected_on_every_dashboard_path(
    client: TestClient, path: str, method: str
) -> None:
    r = getattr(client, method)(path)
    assert r.status_code == 405, (method, path)


def test_the_whole_http_surface_is_read_only(client: TestClient) -> None:
    """Dashboard, /health, /capital and the static files: nothing accepts a write."""
    for router in (dashboard_router, http_router):
        for route in router.routes:
            assert isinstance(route, APIRoute)
            assert route.methods <= {"GET", "HEAD"}, (route.path, route.methods)
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/static/dashboard.css").status_code == 405


def test_templates_contain_no_forms_or_write_triggers() -> None:
    forbidden = re.compile(
        r"<form|<input|<button|<select|<textarea|hx-(post|put|patch|delete)", re.I
    )
    for tpl in (Path(dash_routes.HERE) / "templates").glob("*.html"):
        assert not forbidden.search(tpl.read_text()), tpl.name
    assert "fetch(" in (Path(dash_routes.HERE) / "static" / "dashboard.js").read_text()
    js = (Path(dash_routes.HERE) / "static" / "dashboard.js").read_text()
    assert "POST" not in js and "method:" not in js


def test_equity_chart_x_values_are_epoch_numbers() -> None:
    """With `parsing: false`, Chart.js needs numeric x; Date objects collapse the axis to 0..1."""
    js = (Path(dash_routes.HERE) / "static" / "dashboard.js").read_text()
    assert "parsing: false" in js
    assert "x: Date.parse(p.t)" in js
    assert "x: new Date(" not in js
    assert "min: Date.now() - 30 * 864e5" in js  # the "last 30 days" window, even for one point


def test_no_external_resources_are_referenced() -> None:
    """No CDN at runtime: every script/style/link is same-origin."""
    ext = re.compile(r"""(src|href)=["']https?://""", re.I)
    for tpl in (Path(dash_routes.HERE) / "templates").glob("*.html"):
        assert not ext.search(tpl.read_text()), tpl.name


def test_vendored_assets_are_served_locally(client: TestClient) -> None:
    for name in ("htmx.min.js", "chart.umd.min.js", "dashboard.js", "dashboard.css"):
        r = client.get(f"/static/{name}")
        assert r.status_code == 200, name
    assert "text/css" in client.get("/static/dashboard.css").headers["content-type"]


def test_pages_are_mobile_ready_and_escape_content(
    client: TestClient, ledger: SqliteLedger
) -> None:
    with ledger.transaction() as repo:
        repo.add_halt(HaltType.KILL_SWITCH, None, "<script>alert(1)</script>", NOW, "telegram:1")
    html = client.get("/halts").text
    assert 'name="viewport"' in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_security_headers_on_dashboard_pages(client: TestClient) -> None:
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert (
        "script-src 'self'" in csp and "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    )
    assert "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"
