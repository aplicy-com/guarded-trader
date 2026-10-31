"""Run the real CommandProcessor against in-memory fakes and dump a chat transcript as JSON.

Feeds docs/assets/telegram-halt-flow.png (see docs/assets/README.md). Usage:
    cd services/conductor && uv run python ../../scripts/docs_assets/telegram_transcript.py <out.json>
No network and no Telegram. CHAT is a made-up number, and it is replaced by <chat-id> in
the output anyway.
"""

import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "tests"))

from conductor.application.ingest import FreqtradeInstance, run_ingest
from conductor.application.principal import ensure_principal
from conductor.application.telegram_commands import CommandProcessor
from conductor.domain.confirmation import ConfirmationBook
from conductor.domain.trading_mode import TradingMode
from conductor.infrastructure.db import create_db_engine, create_session_factory
from conductor.infrastructure.ledger_repository import SqliteLedger
from fakes import Clock, FakeFreqtrade, RecordingNotifier, open_view

CHAT = 1000001
db = Path(tempfile.mkdtemp()) / "c.db"
subprocess.run(
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    env={"DATABASE_URL": f"sqlite:///{db}", "PATH": "/usr/bin:/bin"},
    check=True,
    capture_output=True,
)
ledger = SqliteLedger(create_session_factory(create_db_engine(f"sqlite:///{db}")))
clock = Clock(datetime(2026, 10, 30, 14, 2, tzinfo=UTC))
ft = FakeFreqtrade()
ft.open_trades = [
    open_view(1, "ETH/USD", stake_amount=Decimal(25), profit_abs=Decimal("0.42"))
]
instances = [FreqtradeInstance("primary", ft, ft)]
notifier = RecordingNotifier()
ensure_principal(ledger, Decimal(100), notifier=notifier, now=clock)
run_ingest(ledger, instances, now=clock)
notifier.sent.clear()
codes = iter(["K7Q2", "M3XP"])
bot = CommandProcessor(
    ledger=ledger,
    instances=instances,
    trading_mode=TradingMode.DRY_RUN,
    notifier=notifier,
    now=clock,
    book=ConfirmationBook(code_factory=lambda: next(codes)),
    sleep=lambda _s: None,
)

chat: list[dict[str, str]] = []
for text in ["/kill", "yes K7Q2", "/status", "/resume 1", "yes M3XP"]:
    clock.at += timedelta(seconds=20)
    chat.append({"from": "operator", "text": text, "at": f"{clock.at:%H:%M}"})
    before = len(notifier.sent)
    for reply in bot.handle(CHAT, text):
        chat.append({"from": "bot", "text": reply, "at": f"{clock.at:%H:%M}"})
    for alert in notifier.sent[before:]:
        chat.append({"from": "bot", "text": alert, "at": f"{clock.at:%H:%M}"})

out = json.dumps(chat, indent=1).replace(f"telegram:{CHAT}", "telegram:<chat-id>")
assert str(CHAT) not in out
Path(sys.argv[1]).write_text(out)
print(out)
