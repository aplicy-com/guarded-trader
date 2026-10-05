"""Long-polling Telegram command bot (python-telegram-bot).

Outbound HTTPS only: `getUpdates` long polling, no webhook, no listening socket.
Authorization lives here and nowhere else: a message from a chat that is not in
the allowlist is ignored silently (nothing is sent back, so the bot does not even
confirm it exists) and logged by chat ID. Everything that passes is handed to the
library-free `CommandProcessor`.

The bot is best-effort: if it cannot start or crashes, Conductor and its risk
checks keep running; only the chat commands are unavailable.
"""

import asyncio
import threading
from collections.abc import Collection
from typing import Any

import structlog
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler, filters
from telegram.request import BaseRequest

from conductor.application.telegram_commands import CommandProcessor

log = structlog.get_logger()


class TelegramBot:
    def __init__(
        self,
        token: str,
        allowed_chat_ids: Collection[int],
        processor: CommandProcessor,
        *,
        request: BaseRequest | None = None,
        get_updates_request: BaseRequest | None = None,
    ) -> None:
        self._allowed = frozenset(allowed_chat_ids)
        self._processor = processor
        builder: ApplicationBuilder[Any, Any, Any, Any, Any, Any] = ApplicationBuilder().token(
            token
        )
        if request is not None:
            builder = builder.request(request)
        if get_updates_request is not None:
            builder = builder.get_updates_request(get_updates_request)
        self._app: Application[Any, Any, Any, Any, Any, Any] = builder.build()
        # Plain text only (commands included); edited messages and other update types are ignored.
        self._app.add_handler(
            MessageHandler(filters.TEXT & filters.UpdateType.MESSAGE, self._on_message)
        )
        self._app.add_error_handler(self._on_error)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()

    @property
    def application(self) -> Application[Any, Any, Any, Any, Any, Any]:
        return self._app

    # ---- update handling ------------------------------------------------------

    async def _on_message(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        message = update.effective_message
        chat_id = chat.id if chat is not None else None
        if chat_id is None or chat_id not in self._allowed:
            log.warning("telegram_unauthorized", chat_id=chat_id)  # never the message text
            return
        user = update.effective_user
        if message is None or not message.text or (user is not None and user.is_bot):
            return
        replies = await asyncio.to_thread(self._processor.handle, chat_id, message.text)
        for reply in replies:
            await message.reply_text(reply)

    async def _on_error(self, _update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Type only: library errors can embed request URLs, which contain the token.
        log.error("telegram_handler_error", error=type(context.error).__name__)

    # ---- lifecycle (own thread + event loop; Conductor itself is synchronous) -----

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="telegram-bot", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as exc:
            log.error("telegram_bot_stopped", error=type(exc).__name__)

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        async with self._app:
            await self._app.start()
            updater = self._app.updater
            if updater is None:
                raise RuntimeError("no updater")
            # Messages sent while we were down are DISCARDED: a stale "yes <code>" or
            # command must never be acted on later. -1 = retry forever on network errors.
            await updater.start_polling(
                drop_pending_updates=True, allowed_updates=["message"], bootstrap_retries=-1
            )
            self._ready.set()
            log.info("telegram_bot_polling", allowed_chats=len(self._allowed))
            await self._stop.wait()
            await updater.stop()
            await self._app.stop()

    def wait_ready(self, timeout: float = 10.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self, timeout: float = 10.0) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout)
