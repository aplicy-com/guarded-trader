from enum import StrEnum


class TradingMode(StrEnum):
    """Runtime mode. Must default to DRY_RUN everywhere (CLAUDE.md, .env.example)."""

    DRY_RUN = "dry_run"
    LIVE = "live"
