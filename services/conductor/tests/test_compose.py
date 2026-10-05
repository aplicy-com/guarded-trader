"""Pins the deployment properties that keep the dashboard and secrets contained (3A-5)."""

from pathlib import Path

import yaml

COMPOSE = Path(__file__).parents[3] / "infra" / "docker-compose.yml"
SECRET_ENV = (
    "HEALTHCHECK_PING_URL",
    "BACKUP_B2_BUCKET",
    "BACKUP_B2_ENDPOINT",
    "BACKUP_B2_KEY_ID",
    "BACKUP_B2_APP_KEY",
    "BACKUP_B2_REGION",
)


def services() -> dict[str, dict[str, object]]:
    return yaml.safe_load(COMPOSE.read_text())["services"]  # type: ignore[no-any-return]


def test_the_dashboard_port_is_published_on_host_loopback_only() -> None:
    ports = services()["conductor"]["ports"]
    assert ports == ["127.0.0.1:8000:8000"]
    # No service may publish on anything but loopback (Docker bypasses ufw).
    for name, svc in services().items():
        for p in svc.get("ports", []):  # type: ignore[attr-defined]
            assert str(p).startswith("127.0.0.1:"), (name, p)


def test_observability_secrets_reach_conductor_only() -> None:
    svcs = services()
    ft_env = svcs["freqtrade"]["environment"]
    assert "env_file" in svcs["freqtrade"]  # it gets the whole .env, so each secret is blanked
    for var in SECRET_ENV:
        assert ft_env[var] == "", var  # type: ignore[index]
        assert var in svcs["conductor"]["environment"], var  # type: ignore[operator]
    assert "env_file" not in svcs["conductor"]


def test_freqtrade_data_is_mounted_into_conductor_read_only() -> None:
    mounts = [m for m in services()["conductor"]["volumes"] if "freqtrade" in str(m)]  # type: ignore[attr-defined]
    assert mounts == ["../services/freqtrade/user_data:/freqtrade-user-data:ro"]
    assert services()["conductor"]["read_only"] is True
