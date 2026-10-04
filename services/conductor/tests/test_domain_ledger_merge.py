from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from conductor.domain.ledger import LedgerTrade, merge_trade

D = Decimal
T0 = datetime(2026, 9, 11, 16, tzinfo=UTC)

OPEN = LedgerTrade(
    1, "ETH/USD", True, False, T0, None, D(2573), None, D("0.01"), D(33), None, None, None, None
)
CLOSED = replace(
    OPEN,
    is_open=False,
    close_date=T0,
    close_rate=D(2477),
    fee_open_cost=D("0.05"),
    fee_close_cost=D("0.08"),
    close_profit_abs=D("-1.36"),
    exit_reason="trailing_stop_loss",
)


def test_first_insert() -> None:
    assert merge_trade(None, OPEN) == OPEN


def test_open_then_closed_closes() -> None:
    assert merge_trade(OPEN, CLOSED) == CLOSED


def test_closed_is_final_and_reingest_is_idempotent() -> None:
    assert merge_trade(CLOSED, OPEN) == CLOSED
    assert merge_trade(CLOSED, CLOSED) == CLOSED


def test_open_to_open_keeps_known_fee() -> None:
    known = replace(OPEN, fee_open_cost=D("0.05"))
    updated = replace(OPEN, amount=D("0.02"))
    out = merge_trade(known, updated)
    assert out.amount == D("0.02")
    assert out.fee_open_cost == D("0.05")


def test_merge_is_idempotent() -> None:
    once = merge_trade(OPEN, OPEN)
    assert merge_trade(once, OPEN) == once
