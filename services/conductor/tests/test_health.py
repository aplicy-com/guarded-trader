from fastapi.testclient import TestClient

from conductor.application.ingest import FreqtradeInstance
from conductor.infrastructure.config import Settings
from conductor.main import create_app
from fakes import FakeFreqtrade, FakeFx


def create(settings: Settings):  # type: ignore[no-untyped-def]
    return create_app(
        settings, instances=[FreqtradeInstance("primary", FakeFreqtrade())], fx=FakeFx()
    )


def test_health_ok_with_wal_and_scheduler_disabled(settings: Settings) -> None:
    with TestClient(create(settings)) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db_journal_mode"] == "wal"
    assert body["trading_mode"] == "dry_run"
    assert body["scheduler_running"] is False


def test_health_reports_scheduler_running_when_enabled(settings: Settings) -> None:
    enabled = settings.model_copy(update={"scheduler_enabled": True})
    with TestClient(create(enabled)) as client:
        body = client.get("/health").json()
    assert body["scheduler_running"] is True
    assert body["status"] == "ok"


def test_health_503_when_scheduler_required_but_not_running(settings: Settings) -> None:
    enabled = settings.model_copy(update={"scheduler_enabled": True})
    app = create(enabled)
    # No lifespan entered => scheduler never started.
    r = TestClient(app).get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "unhealthy"


def test_docs_and_openapi_are_not_exposed(settings: Settings) -> None:
    with TestClient(create(settings)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
