"""The polling bot through a fake Telegram transport (python-telegram-bot's own request layer)."""

import asyncio
import json
from typing import Any

import pytest
from telegram import Update
from telegram.request import BaseRequest, RequestData

from conductor.adapters.telegram_bot import TelegramBot
from conductor.application.ingest import FreqtradeInstance
from conductor.application.principal import ensure_principal
from conductor.application.telegram_commands import CommandProcessor
from conductor.domain.confirmation import ConfirmationBook
from conductor.domain.trading_mode import TradingMode
from conductor.infrastructure.ledger_repository import SqliteLedger
from fakes import Clock, FakeFreqtrade, RecordingNotifier

ALLOWED = 111
STRANGER = 222


class FakeTelegram(BaseRequest):
    """Stands in for api.telegram.org: records every outgoing method call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def initialize(self) -> None: ...
    async def shutdown(self) -> None: ...

    @property
    def read_timeout(self) -> float:
        return 5.0

    async def do_request(  # type: ignore[override]
        self, url: str, method: str, request_data: RequestData | None = None, **_kw: Any
    ) -> tuple[int, bytes]:
        name = url.rsplit("/", 1)[-1]
        params = dict(request_data.parameters) if request_data else {}
        self.calls.append((name, params))
        result: Any = True
        if name == "getMe":
            result = {"id": 1, "is_bot": True, "first_name": "c", "username": "c_bot"}
        elif name == "sendMessage":
            result = {
                "message_id": 7,
                "date": 0,
                "chat": {"id": params["chat_id"], "type": "private"},
                "text": params["text"],
            }
        return 200, json.dumps({"ok": True, "result": result}).encode()

    @property
    def sent(self) -> list[dict[str, Any]]:
        return [p for n, p in self.calls if n == "sendMessage"]


@pytest.fixture(autouse=True)
def principal(ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier) -> None:
    ensure_principal(ledger, __import__("decimal").Decimal(100), notifier=notifier, now=clock)


@pytest.fixture
def transport() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def bot(
    transport: FakeTelegram,
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    clock: Clock,
    notifier: RecordingNotifier,
) -> TelegramBot:
    processor = CommandProcessor(
        ledger=ledger,
        instances=instances,
        trading_mode=TradingMode.DRY_RUN,
        notifier=notifier,
        now=clock,
        book=ConfirmationBook(code_factory=lambda: "AB12"),
        sleep=lambda _s: None,
    )
    return TelegramBot(
        "123456:TEST-TOKEN-not-real-but-long-enough-xx",
        [ALLOWED],
        processor,
        request=transport,
        get_updates_request=FakeTelegram(),
    )


def message(
    chat_id: int, text: str, *, is_bot: bool = False, edited: bool = False
) -> dict[str, Any]:
    msg = {
        "message_id": 1,
        "date": 0,
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": chat_id, "is_bot": is_bot, "first_name": "x"},
        "text": text,
    }
    return {"update_id": 1, ("edited_message" if edited else "message"): msg}


def deliver(bot: TelegramBot, *payloads: dict[str, Any]) -> None:
    async def run() -> None:
        app = bot.application
        async with app:
            for p in payloads:
                await app.process_update(Update.de_json(p, app.bot))

    asyncio.run(run())


def test_allowed_chat_gets_a_reply_in_its_own_chat(
    bot: TelegramBot, transport: FakeTelegram
) -> None:
    deliver(bot, message(ALLOWED, "/help"))
    assert len(transport.sent) == 1
    assert transport.sent[0]["chat_id"] == ALLOWED
    assert "Conductor commands" in transport.sent[0]["text"]


def test_other_chat_is_ignored_silently_and_nothing_runs(
    bot: TelegramBot, transport: FakeTelegram, freqtrade: FakeFreqtrade
) -> None:
    deliver(
        bot, message(STRANGER, "/kill"), message(STRANGER, "yes AB12"), message(STRANGER, "/status")
    )
    assert transport.sent == []  # not even a refusal: the bot does not reveal itself
    assert freqtrade.control_calls == []


def test_unauthorized_attempts_are_logged_by_chat_id_without_the_text(
    bot: TelegramBot, transport: FakeTelegram
) -> None:
    import structlog

    with structlog.testing.capture_logs() as logs:
        deliver(bot, message(STRANGER, "/kill secret-ish text"))
    (entry,) = [e for e in logs if e["event"] == "telegram_unauthorized"]
    assert entry["chat_id"] == STRANGER
    assert "secret-ish" not in json.dumps(entry)


def test_stranger_cannot_confirm_the_allowed_chats_pending_kill(
    bot: TelegramBot, transport: FakeTelegram, freqtrade: FakeFreqtrade
) -> None:
    deliver(bot, message(ALLOWED, "/kill"), message(STRANGER, "yes AB12"))
    assert [m["chat_id"] for m in transport.sent] == [ALLOWED]  # only the prompt
    assert freqtrade.control_calls == []


def test_full_confirmation_flow_over_the_wire(
    bot: TelegramBot, transport: FakeTelegram, freqtrade: FakeFreqtrade
) -> None:
    deliver(bot, message(ALLOWED, "/kill"), message(ALLOWED, "yes AB12"))
    assert "yes AB12" in transport.sent[0]["text"]
    assert "all steps ok" in transport.sent[1]["text"]
    assert freqtrade.state == "paused"


def test_wrong_code_over_the_wire_runs_nothing(
    bot: TelegramBot, transport: FakeTelegram, freqtrade: FakeFreqtrade
) -> None:
    deliver(bot, message(ALLOWED, "/flatten"), message(ALLOWED, "yes NOPE"))
    assert "Wrong code" in transport.sent[1]["text"]
    assert freqtrade.control_calls == []


def test_edited_messages_and_other_bots_are_ignored(
    bot: TelegramBot, transport: FakeTelegram, freqtrade: FakeFreqtrade
) -> None:
    deliver(bot, message(ALLOWED, "/kill", edited=True), message(ALLOWED, "/kill", is_bot=True))
    assert transport.sent == []
    assert freqtrade.control_calls == []


def test_a_broken_handler_never_replies_with_internals(
    bot: TelegramBot, transport: FakeTelegram, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> list[str]:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(bot._processor, "handle", boom)
    deliver(bot, message(ALLOWED, "/status"))
    assert transport.sent == []


def test_long_polling_only_never_a_webhook_and_no_listening_socket(bot: TelegramBot) -> None:
    import inspect

    from conductor.adapters import telegram_bot

    src = inspect.getsource(telegram_bot)
    assert "start_polling" in src
    assert "start_webhook" not in src
    assert "set_webhook" not in src
