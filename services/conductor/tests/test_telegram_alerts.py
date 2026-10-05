"""Alert delivery: dedupe, rate limit, non-blocking, failure isolation, no token leaks."""

import json
import logging
import threading
import time
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
import structlog

from conductor.adapters.telegram import TelegramAlertNotifier, TelegramApi, TelegramError
from conductor.application.fence import run_daily_fence
from conductor.application.halts import clear_halt, kill_switch, nuclear
from conductor.application.ingest import FreqtradeInstance, run_ingest
from conductor.application.principal import ensure_principal
from conductor.application.reachability import ReachabilityTracker
from conductor.application.risk import run_risk_cycle
from conductor.domain.alert_policy import AlertPolicy
from conductor.domain.halt import HaltType
from conductor.domain.risk import RiskLimits
from conductor.infrastructure.ledger_repository import SqliteLedger
from conductor.infrastructure.logging import configure_logging, redact
from fakes import (
    BrokenNotifier,
    Clock,
    FakeFreqtrade,
    RecordingNotifier,
    closed_view,
    open_view,
)

D = Decimal
LIMITS = RiskLimits(D(3), D(10), 3, 2)
TOKEN = "123456789:AAH-fake_TOKEN_value_0123456789abcdefg"


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.fail = False
        self.gate: threading.Event | None = None

    def send_message(self, chat_id: int, text: str) -> None:
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail:
            raise TelegramError("boom")
        self.sent.append((chat_id, text))


@pytest.fixture(autouse=True)
def principal(ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier) -> None:
    ensure_principal(ledger, D(100), notifier=notifier, now=clock)


def make(
    sender: FakeSender, clock: Clock, chats: tuple[int, ...] = (1,), **policy: int
) -> TelegramAlertNotifier:
    return TelegramAlertNotifier(sender, chats, policy=AlertPolicy(**policy), clock=clock)


# ---- delivery policy --------------------------------------------------------------


def test_delivers_to_every_allowed_chat_only(clock: Clock) -> None:
    s = FakeSender()
    n = make(s, clock, (1, 2))
    n.send("hello")
    n.flush()
    assert sorted(s.sent) == [(1, "hello"), (2, "hello")]


def test_identical_alerts_are_deduped(clock: Clock) -> None:
    s = FakeSender()
    n = make(s, clock)
    for _ in range(5):
        n.send("HALT #1 x")
    n.flush()
    assert [t for _, t in s.sent] == ["HALT #1 x"]
    clock.at += timedelta(seconds=301)
    n.send("HALT #1 x")
    n.flush()
    assert len(s.sent) == 2


def test_storm_is_rate_limited_and_summarised(clock: Clock) -> None:
    s = FakeSender()
    n = make(s, clock, max_per_window=3, window_seconds=60)
    for i in range(10):
        n.send(f"m{i}")
    n.flush()
    assert len(s.sent) == 3
    clock.at += timedelta(seconds=61)
    n.send("after")
    n.flush()
    assert "7 alert(s) suppressed" in s.sent[-1][1]


def test_send_never_blocks_even_if_telegram_hangs(clock: Clock) -> None:
    s = FakeSender()
    s.gate = threading.Event()  # delivery is stuck
    n = make(s, clock)
    started = time.monotonic()
    for i in range(20):
        n.send(f"m{i}")
    assert time.monotonic() - started < 1.0
    s.gate.set()
    n.flush()


def test_a_full_queue_drops_instead_of_blocking(clock: Clock) -> None:
    s = FakeSender()
    s.gate = threading.Event()
    n = make(s, clock, dedupe_seconds=0, max_per_window=10_000)
    with structlog.testing.capture_logs() as logs:
        for i in range(300):
            n.send(f"m{i}")
    assert any(e["event"] == "alert_queue_full_dropped" for e in logs)
    s.gate.set()
    n.flush()


def test_delivery_failure_is_logged_and_never_raised(clock: Clock) -> None:
    s = FakeSender()
    s.fail = True
    n = make(s, clock)
    with structlog.testing.capture_logs() as logs:
        n.send("x")
        n.flush()
    assert any(e["event"] == "alert_delivery_failed" for e in logs)
    s.fail = False
    n.send("y")  # still alive afterwards
    n.flush()
    assert s.sent == [(1, "y")]


# ---- the sender itself --------------------------------------------------------------


def test_sender_posts_plain_text_json_to_sendmessage() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    TelegramApi(TOKEN, transport=httpx.MockTransport(handler)).send_message(5, "hi")
    (req,) = seen
    assert (req.method, req.url.path) == ("POST", f"/bot{TOKEN}/sendMessage")
    assert json.loads(req.content) == {
        "chat_id": 5,
        "text": "hi",
    }  # no parse_mode: no markup injection


def test_sender_truncates_over_long_messages() -> None:
    body: list[dict[str, object]] = []
    api = TelegramApi(
        TOKEN,
        transport=httpx.MockTransport(
            lambda r: (body.append(json.loads(r.content)), httpx.Response(200, json={}))[1]
        ),
    )
    api.send_message(1, "x" * 9000)
    assert len(str(body[0]["text"])) == 4000


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_sender_errors_never_contain_the_token(status: int) -> None:
    api = TelegramApi(TOKEN, transport=httpx.MockTransport(lambda r: httpx.Response(status)))
    with pytest.raises(TelegramError) as exc:
        api.send_message(1, "x")
    assert TOKEN not in str(exc.value)
    assert "bot" not in str(exc.value).lower().replace("sendmessage", "")


def test_network_errors_never_contain_the_token() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with pytest.raises(TelegramError) as exc:
        TelegramApi(TOKEN, transport=httpx.MockTransport(boom)).send_message(1, "x")
    assert TOKEN not in str(exc.value)
    assert TOKEN not in repr(exc.value.__cause__)


def test_redact_removes_bot_tokens_from_any_text() -> None:
    assert TOKEN.split(":")[1] not in redact(f"GET https://api.telegram.org/bot{TOKEN}/getUpdates")
    assert redact("nothing to see") == "nothing to see"


def test_logging_redacts_tokens_in_structlog_and_stdlib(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json=True)
    structlog.get_logger().error("x", url=f"https://api.telegram.org/bot{TOKEN}/sendMessage")
    logging.getLogger("telegram.ext").error(
        "polling https://api.telegram.org/bot%s/getUpdates", TOKEN
    )
    try:
        raise RuntimeError(f"https://api.telegram.org/bot{TOKEN}/getUpdates")
    except RuntimeError:
        logging.getLogger("telegram.ext").exception("boom")
    out = capsys.readouterr().out
    assert TOKEN.split(":")[1] not in out
    assert "bot<redacted>" in out


def test_httpx_request_logging_is_silenced() -> None:
    configure_logging("INFO", json=True)
    assert logging.getLogger("httpx").level >= logging.WARNING


# ---- alerts from the use cases --------------------------------------------------------


def cycle(
    ledger: SqliteLedger,
    inst: list[FreqtradeInstance],
    clock: Clock,
    n: object,
    tracker: ReachabilityTracker | None = None,
) -> object:
    return run_risk_cycle(ledger, inst, LIMITS, now=clock, notifier=n, tracker=tracker)  # type: ignore[arg-type]


def test_trade_opened_and_closed_alert_exactly_once(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    recent = clock.at - timedelta(minutes=5)
    freqtrade.open_trades = [open_view(1, "ETH/USD", open_date=recent)]
    run_ingest(ledger, instances, now=clock, notifier=notifier)
    run_ingest(ledger, instances, now=clock, notifier=notifier)  # same state again
    assert [m for m in notifier.sent if m.startswith("OPENED")] == [
        "OPENED primary ETH/USD 0.01 @ 2500 (stake 25.00 USD)"
    ]
    freqtrade.open_trades = []
    freqtrade.closed_trades = [closed_view(1, "2.50", pair="ETH/USD", close_date=clock.at)]
    run_ingest(ledger, instances, now=clock, notifier=notifier)
    run_ingest(ledger, instances, now=clock, notifier=notifier)
    assert [m for m in notifier.sent if m.startswith("CLOSED")] == [
        "CLOSED primary ETH/USD +2.50 USD (roi)"
    ]


def test_restart_does_not_repeat_trade_alerts(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
) -> None:
    freqtrade.open_trades = [open_view(1, open_date=clock.at - timedelta(minutes=5))]
    first = RecordingNotifier()
    run_ingest(ledger, instances, now=clock, notifier=first)
    second = RecordingNotifier()  # a fresh process, fresh in-memory dedupe, same ledger
    run_ingest(ledger, instances, now=clock, notifier=second)
    assert len(first.sent) == 1
    assert second.sent == []


def test_old_history_is_never_alerted(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.closed_trades = [closed_view(i, "1.00") for i in range(1, 30)]  # closed in September
    freqtrade.open_trades = [open_view(99, open_date=clock.at - timedelta(days=3))]
    run_ingest(ledger, instances, now=clock, notifier=notifier)
    assert notifier.sent == []


def test_halt_created_alert_and_cleared_alert(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(i, stake_amount=D(10)) for i in (1, 2, 3)]
    cycle(ledger, instances, clock, notifier)
    assert any(m.startswith("HALT #1 [max_positions]") for m in notifier.sent)
    clear_halt(
        ledger, instances, halt_id=1, operator="telegram:1", note=None, now=clock, notifier=notifier
    )
    assert any("HALT #1 [max_positions] cleared by telegram:1" in m for m in notifier.sent)


def test_nuclear_result_is_alerted_with_every_step(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.open_trades = [open_view(1)]
    nuclear(ledger, instances, operator="m", now=clock, notifier=notifier, sleep=lambda _s: None)
    result = [m for m in notifier.sent if m.startswith("NUCLEAR #1")]
    assert len(result) == 1
    assert "all steps ok" in result[0]
    assert "force_exit_all: ok" in result[0]


def test_kill_alerts_once_when_ok_and_again_only_on_failure(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    kill_switch(ledger, instances, operator="m", now=clock, notifier=notifier)
    assert len(notifier.sent) == 1
    ledger2_notifier = RecordingNotifier()
    freqtrade.fail = True
    from conductor.application.halts import engage_halt

    engage_halt(
        ledger,
        halt_type=HaltType.MAX_DRAWDOWN,
        reason="r",
        actor="s",
        now=clock,
        notifier=ledger2_notifier,
    )
    kill_switch(ledger, instances, operator="m", now=clock, notifier=ledger2_notifier)
    assert any("NOT every step succeeded" in m for m in ledger2_notifier.sent)


def test_fence_alerts_once_per_day(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    freqtrade.closed_trades = [closed_view(1, "40")]
    run_ingest(ledger, instances, now=clock)
    for _ in range(3):  # three runs the same UTC day (startup catch-up, restarts, ...)
        run_daily_fence(
            ledger,
            daily_profit_cap=D(10),
            manual_move_threshold=D(25),
            now=clock,
            notifier=notifier,
        )
    assert sum(m.startswith("FENCED 30.00 USD") for m in notifier.sent) == 1
    assert sum(m.startswith("MANUAL MOVE DUE") for m in notifier.sent) == 1


def test_missed_fence_days_are_alerted(
    ledger: SqliteLedger, clock: Clock, notifier: RecordingNotifier
) -> None:
    run_daily_fence(
        ledger, daily_profit_cap=D(10), manual_move_threshold=D(25), now=clock, notifier=notifier
    )
    clock.at += timedelta(days=3)
    run_daily_fence(
        ledger, daily_profit_cap=D(10), manual_move_threshold=D(25), now=clock, notifier=notifier
    )
    assert any("Fence run MISSED for 2 UTC day(s)" in m for m in notifier.sent)


def test_freqtrade_unreachable_over_ten_minutes_alerts_once_then_recovers(
    ledger: SqliteLedger,
    instances: list[FreqtradeInstance],
    freqtrade: FakeFreqtrade,
    clock: Clock,
    notifier: RecordingNotifier,
) -> None:
    tracker = ReachabilityTracker()
    freqtrade.fail = True
    for _ in range(14):  # a minute apart
        cycle(ledger, instances, clock, notifier, tracker)
        clock.at += timedelta(minutes=1)
    down = [m for m in notifier.sent if "unreachable" in m]
    assert len(down) == 1
    assert "10 min" in down[0]
    freqtrade.fail = False
    cycle(ledger, instances, clock, notifier, tracker)
    assert sum("reachable again" in m for m in notifier.sent) == 1


# ---- failure isolation ----------------------------------------------------------------


def test_a_dead_notifier_never_stops_the_risk_cycle(
    ledger: SqliteLedger, instances: list[FreqtradeInstance], freqtrade: FakeFreqtrade, clock: Clock
) -> None:
    broken = BrokenNotifier()
    freqtrade.open_trades = [open_view(i, stake_amount=D(10)) for i in (1, 2, 3)]
    r = cycle(ledger, instances, clock, broken, ReachabilityTracker())
    assert r.new_halt_ids == (1,)  # type: ignore[attr-defined]
    assert freqtrade.state == "paused"  # the halt was applied regardless of Telegram
    with ledger.transaction(write=False) as repo:
        assert [h.halt_type for h in repo.active_halts()] == [HaltType.MAX_POSITIONS]
    assert broken.attempts >= 1


def test_a_dead_notifier_never_stops_ingest(
    ledger: SqliteLedger, instances: list[FreqtradeInstance], freqtrade: FakeFreqtrade, clock: Clock
) -> None:
    freqtrade.open_trades = [open_view(1)]
    r = run_ingest(ledger, instances, now=clock, notifier=BrokenNotifier())
    assert (r.inserted, r.failed_instances) == (1, ())


def test_a_dead_notifier_never_stops_kill_nuclear_or_clear(
    ledger: SqliteLedger, instances: list[FreqtradeInstance], freqtrade: FakeFreqtrade, clock: Clock
) -> None:
    b = BrokenNotifier()
    assert kill_switch(ledger, instances, operator="m", now=clock, notifier=b).ok
    clear_halt(ledger, instances, halt_id=1, operator="m", note=None, now=clock, notifier=b)
    freqtrade.open_trades = [open_view(1)]
    assert nuclear(ledger, instances, operator="m", now=clock, notifier=b, sleep=lambda _s: None).ok
    assert freqtrade.state == "stopped"


def test_a_dead_notifier_never_stops_the_fence(
    ledger: SqliteLedger, instances: list[FreqtradeInstance], freqtrade: FakeFreqtrade, clock: Clock
) -> None:
    freqtrade.closed_trades = [closed_view(1, "40")]
    run_ingest(ledger, instances, now=clock)
    r = run_daily_fence(
        ledger,
        daily_profit_cap=D(10),
        manual_move_threshold=D(25),
        now=clock,
        notifier=BrokenNotifier(),
    )
    assert r.fenced_amount == D(30)
