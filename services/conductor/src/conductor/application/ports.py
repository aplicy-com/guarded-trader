"""Ports: what the application needs from the outside world.

Adapters implement these. The Freqtrade port is deliberately READ-ONLY: the
Conductor never places, modifies or cancels an exchange order (ADR-0003).
Control actions (stopentry, forceexit, reload_config) are added in 3A-3
as separate, explicitly named ports so that reading never implies writing.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Protocol

from conductor.domain.freqtrade_view import (
    BotConfigView,
    OpenTradeView,
    ProfitSummary,
    TradesPage,
)


class FreqtradeReader(Protocol):
    def ping(self) -> bool: ...
    def show_config(self) -> BotConfigView: ...
    def status(self) -> tuple[OpenTradeView, ...]: ...
    def trades(self, *, limit: int = 500, offset: int = 0) -> TradesPage: ...
    def profit(self) -> ProfitSummary: ...
    def balances(self) -> Mapping[str, Decimal]:
        """Exchange balance per currency code (total, free + in orders)."""
        ...

    def whitelist(self) -> tuple[str, ...]: ...


class FreqtradeController(Protocol):
    """The ONLY write surface toward Freqtrade (3A-3). Deliberately tiny.

    Entry-blocking and flattening only: nothing here can open a position,
    change configuration, or touch anything but bot state and existing orders.
    """

    def pause_entries(self) -> None:
        """Stop new entries (Freqtrade `stopentry`); open trades are still managed."""
        ...

    def resume(self) -> None:
        """Resume entries (Freqtrade `start`). Only ever called after a human clears a halt."""
        ...

    def stop(self) -> None: ...
    def cancel_open_order(self, trade_id: int) -> None: ...
    def force_exit_all(self) -> None:
        """Market-exit every open trade."""
        ...


class Notifier(Protocol):
    """Operator-facing alerts (Telegram from 3A-4)."""

    def send(self, text: str) -> None: ...


class Heartbeat(Protocol):
    """Outbound dead-man's-switch ping (healthchecks.io, 3A-5). Push, never pull."""

    def ok(self) -> None:
        """Conductor is alive and healthy."""
        ...

    def fail(self, reason: str) -> None:
        """Conductor is alive but unhealthy: signal failure now instead of by silence."""
        ...


class LlmClient(Protocol):
    """Text in, text out. Deliberately no tools and no exchange access (ADR-0003).

    Future implementations: claude-code-headless and anthropic-api. Every
    prompt/response must be logged with a content hash by the caller
    (CLAUDE.md §4).
    """

    def complete(self, prompt: str) -> str: ...
