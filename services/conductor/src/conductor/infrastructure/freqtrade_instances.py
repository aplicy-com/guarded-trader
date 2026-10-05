"""Builds the Freqtrade instances (read client + the separate write client)."""

from collections.abc import Callable

from conductor.adapters.freqtrade import FreqtradeControlClient, FreqtradeRestClient
from conductor.application.ingest import FreqtradeInstance
from conductor.infrastructure.config import Settings


def build_instances(settings: Settings) -> tuple[list[FreqtradeInstance], list[Callable[[], None]]]:
    url = str(settings.freqtrade_api_url)
    user = settings.freqtrade_username.get_secret_value()
    password = settings.freqtrade_password.get_secret_value()
    reader = FreqtradeRestClient(url, user, password)
    controller = FreqtradeControlClient(url, user, password)
    instance = FreqtradeInstance(settings.freqtrade_instance_name, reader, controller)
    return [instance], [reader.close, controller.close]
