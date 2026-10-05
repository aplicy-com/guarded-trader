"""Confirmation state machine, alert policy and reachability tracker."""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from conductor.application.reachability import ReachabilityTracker
from conductor.domain.alert_policy import AlertPolicy
from conductor.domain.confirmation import (
    CODE_ALPHABET,
    ConfirmationBook,
    Outcome,
    random_code,
)

T0 = datetime(2026, 10, 5, 12, tzinfo=UTC)


def book(code: str = "AB12") -> ConfirmationBook:
    return ConfirmationBook(code_factory=lambda: code)


def test_correct_code_confirms_the_exact_action() -> None:
    b = book()
    p = b.request(1, "kill", T0)
    r = b.confirm(1, f"yes {p.code}", T0 + timedelta(seconds=59))
    assert (r.outcome, r.action) == (Outcome.CONFIRMED, "kill")


def test_case_insensitive_and_whitespace_tolerant() -> None:
    b = book("AB12")
    b.request(1, "kill", T0)
    assert b.confirm(1, "  YES   ab12 ", T0).outcome is Outcome.CONFIRMED


def test_wrong_code_does_not_confirm_and_consumes_the_request() -> None:
    b = book()
    b.request(1, "flatten", T0)
    r = b.confirm(1, "yes ZZZZ", T0)
    assert (r.outcome, r.action) == (Outcome.WRONG_CODE, None)
    assert b.confirm(1, "yes AB12", T0).outcome is Outcome.NOTHING_PENDING  # one try only


def test_expired_after_sixty_seconds_even_with_the_right_code() -> None:
    b = book()
    b.request(1, "kill", T0)
    assert b.confirm(1, "yes AB12", T0 + timedelta(seconds=61)).outcome is Outcome.EXPIRED
    assert b.pending_for(1) is None


def test_exactly_at_the_deadline_is_still_valid() -> None:
    b = book()
    b.request(1, "kill", T0)
    assert b.confirm(1, "yes AB12", T0 + timedelta(seconds=60)).outcome is Outcome.CONFIRMED


def test_nothing_pending() -> None:
    assert book().confirm(1, "yes AB12", T0).outcome is Outcome.NOTHING_PENDING


@pytest.mark.parametrize(
    "text", ["yes", "yes AB12 now", "no AB12", "/kill", "AB12", "", "yess AB12"]
)
def test_non_confirmations_are_ignored_and_keep_the_pending_request(text: str) -> None:
    b = book()
    b.request(1, "kill", T0)
    assert b.confirm(1, text, T0).outcome is Outcome.NOT_A_CONFIRMATION
    assert b.pending_for(1) is not None


def test_a_code_is_bound_to_the_asking_chat() -> None:
    b = book()
    b.request(1, "kill", T0)
    assert b.confirm(2, "yes AB12", T0).outcome is Outcome.NOTHING_PENDING
    assert b.confirm(1, "yes AB12", T0).outcome is Outcome.CONFIRMED


def test_a_confirmation_cannot_be_replayed() -> None:
    b = book()
    b.request(1, "kill", T0)
    assert b.confirm(1, "yes AB12", T0).outcome is Outcome.CONFIRMED
    assert b.confirm(1, "yes AB12", T0).outcome is Outcome.NOTHING_PENDING


def test_new_request_replaces_the_old_one() -> None:
    codes = iter(["AAAA", "BBBB"])
    b = ConfirmationBook(code_factory=lambda: next(codes))
    b.request(1, "kill", T0)
    b.request(1, "flatten", T0)
    assert b.confirm(1, "yes AAAA", T0).outcome is Outcome.WRONG_CODE


def test_cancel() -> None:
    b = book()
    b.request(1, "kill", T0)
    assert b.cancel(1) is True
    assert b.cancel(1) is False


@given(st.integers(min_value=0, max_value=200))
def test_random_codes_use_the_safe_alphabet(_: int) -> None:
    c = random_code()
    assert len(c) == 4
    assert set(c) <= set(CODE_ALPHABET)


@given(st.text(max_size=20))
def test_arbitrary_text_never_confirms_without_the_code(text: str) -> None:
    b = book("QQQQ")
    b.request(1, "kill", T0)
    r = b.confirm(1, text, T0)
    if r.outcome is Outcome.CONFIRMED:
        assert text.split()[1].upper() == "QQQQ"


# ---- alert policy ---------------------------------------------------------------


def test_identical_alerts_are_deduped_within_the_window_then_allowed_again() -> None:
    p = AlertPolicy(dedupe_seconds=300)
    assert p.admit("HALT x", T0).send
    assert not p.admit("HALT x", T0 + timedelta(seconds=299)).send
    assert p.admit("HALT x", T0 + timedelta(seconds=301)).send


def test_different_alerts_are_not_deduped() -> None:
    p = AlertPolicy()
    assert p.admit("a", T0).send
    assert p.admit("b", T0).send


def test_rate_limit_caps_a_storm_and_reports_the_overflow_once() -> None:
    p = AlertPolicy(max_per_window=3, window_seconds=60)
    results = [p.admit(f"m{i}", T0) for i in range(10)]
    assert [r.send for r in results] == [True] * 3 + [False] * 7
    later = p.admit("after", T0 + timedelta(seconds=61))
    assert later.send
    assert "7 alert(s) suppressed" in later.prefix
    assert p.admit("again", T0 + timedelta(seconds=62)).prefix == ""


@given(st.lists(st.integers(min_value=0, max_value=400), max_size=60))
def test_never_exceeds_the_rate_limit(offsets: list[int]) -> None:
    p = AlertPolicy(dedupe_seconds=0, max_per_window=5, window_seconds=60)
    sent: list[datetime] = []
    for i, off in enumerate(sorted(offsets)):
        now = T0 + timedelta(seconds=off)
        if p.admit(f"m{i}", now).send:
            sent.append(now)
    for t in sent:
        assert sum(1 for u in sent if timedelta(0) <= t - u < timedelta(seconds=60)) <= 5


def test_invalid_policy_rejected() -> None:
    with pytest.raises(ValueError, match="policy"):
        AlertPolicy(max_per_window=0)


# ---- reachability ---------------------------------------------------------------


def test_alerts_once_after_ten_minutes_and_once_on_recovery() -> None:
    t = ReachabilityTracker()
    assert t.update("a", False, T0) is None
    assert t.update("a", False, T0 + timedelta(minutes=9, seconds=59)) is None
    msg = t.update("a", False, T0 + timedelta(minutes=10))
    assert msg is not None
    assert "unreachable for 10 min" in msg
    assert t.update("a", False, T0 + timedelta(minutes=30)) is None  # no repeat
    assert "reachable again" in (t.update("a", True, T0 + timedelta(minutes=31)) or "")
    assert t.update("a", True, T0 + timedelta(minutes=32)) is None


def test_a_blip_resets_the_clock_and_never_alerts() -> None:
    t = ReachabilityTracker()
    t.update("a", False, T0)
    t.update("a", True, T0 + timedelta(minutes=8))
    assert t.update("a", False, T0 + timedelta(minutes=9)) is None
    assert t.update("a", False, T0 + timedelta(minutes=18)) is None  # 9 min into the new outage
    assert t.update("a", True, T0 + timedelta(minutes=19)) is None  # never alerted: silent


def test_instances_are_independent() -> None:
    t = ReachabilityTracker()
    t.update("a", False, T0)
    t.update("b", True, T0)
    assert t.update("a", False, T0 + timedelta(minutes=11)) is not None
    assert t.update("b", True, T0 + timedelta(minutes=11)) is None
