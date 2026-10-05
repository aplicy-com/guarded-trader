from enum import StrEnum


class TradingMode(StrEnum):
    """Runtime mode. Must default to DRY_RUN everywhere (CLAUDE.md, .env.example)."""

    DRY_RUN = "dry_run"
    LIVE = "live"


LIVE_BANNER = "*** LIVE: REAL MONEY ***"


def mode_banner(mode: TradingMode) -> str:
    """Prefix for operator-facing text: loud in live, empty in dry-run (nothing to warn about)."""
    return f"{LIVE_BANNER} " if mode is TradingMode.LIVE else ""
