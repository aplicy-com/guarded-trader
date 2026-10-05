"""Two-step confirmation for destructive chat commands. Pure; no I/O.

A write command first only *asks*: it stores a pending action under the
asking chat with a random code and a deadline. The action may run only if the
SAME chat answers `yes <code>` before the deadline. A wrong code or a late answer
consumes it (nothing runs); unrelated text is ignored and it simply expires.
Nothing executes without passing through `confirm`.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I: easy to read on a phone
CODE_LENGTH = 4
CONFIRM_WINDOW_SECONDS = 60


def random_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


@dataclass(frozen=True, slots=True)
class PendingAction:
    chat_id: int
    action: str  # e.g. "kill", "flatten", "resume:7"
    code: str
    expires_at: datetime


class Outcome(StrEnum):
    CONFIRMED = "confirmed"
    WRONG_CODE = "wrong_code"
    EXPIRED = "expired"
    NOTHING_PENDING = "nothing_pending"
    NOT_A_CONFIRMATION = "not_a_confirmation"


@dataclass(frozen=True, slots=True)
class ConfirmResult:
    outcome: Outcome
    action: str | None = None  # set only when CONFIRMED


class ConfirmationBook:
    """At most one pending action per chat; a new request replaces the old one."""

    def __init__(
        self,
        *,
        window_seconds: int = CONFIRM_WINDOW_SECONDS,
        code_factory: Callable[[], str] = random_code,
    ) -> None:
        self._window = timedelta(seconds=window_seconds)
        self._code = code_factory
        self._pending: dict[int, PendingAction] = {}

    def request(self, chat_id: int, action: str, now: datetime) -> PendingAction:
        pending = PendingAction(chat_id, action, self._code(), now + self._window)
        self._pending[chat_id] = pending
        return pending

    def confirm(self, chat_id: int, text: str, now: datetime) -> ConfirmResult:
        parts = text.strip().split()
        if len(parts) != 2 or parts[0].lower() != "yes":
            return ConfirmResult(Outcome.NOT_A_CONFIRMATION)
        pending = self._pending.pop(chat_id, None)  # any answer consumes it: one try only
        if pending is None:
            return ConfirmResult(Outcome.NOTHING_PENDING)
        if now > pending.expires_at:
            return ConfirmResult(Outcome.EXPIRED)
        if parts[1].upper() != pending.code:
            return ConfirmResult(Outcome.WRONG_CODE)
        return ConfirmResult(Outcome.CONFIRMED, pending.action)

    def cancel(self, chat_id: int) -> bool:
        return self._pending.pop(chat_id, None) is not None

    def pending_for(self, chat_id: int) -> PendingAction | None:
        return self._pending.get(chat_id)
