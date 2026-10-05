"""Builds the operator-alert notifier: Telegram when configured, else log-only."""

from collections.abc import Callable

from conductor.adapters.telegram import LogNotifier, TelegramAlertNotifier, TelegramApi
from conductor.application.ports import Notifier
from conductor.infrastructure.config import Settings


def build_notifier(settings: Settings) -> tuple[Notifier, list[Callable[[], None]]]:
    """Returns the notifier and the closers to run at shutdown (flush, then close the client).

    Alert delivery only: this never polls for commands, so it is safe to build in a short-lived
    CLI process alongside the running service.
    """
    if settings.telegram_bot_token is None:
        return LogNotifier(), []
    api = TelegramApi(settings.telegram_bot_token.get_secret_value())
    alerts = TelegramAlertNotifier(api, settings.telegram_allowed_chat_ids)
    return alerts, [alerts.close, api.close]
