"""Read-only dashboard (3A-5): FastAPI + Jinja + HTMX, Chart.js vendored.

GET routes only, no forms, no write actions: every write stays on Telegram behind a
confirmation. Reachable only over Tailscale
(docs/05-adr/0017-read-only-dashboard-over-tailscale.md).
"""

from conductor.infrastructure.dashboard.routes import dashboard_router, static_files

__all__ = ["dashboard_router", "static_files"]
