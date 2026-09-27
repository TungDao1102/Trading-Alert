"""Paper SIMULATE notify — journal-first send-only Telegram (Phase 7, plan 07-04).

Per D-05: paper notifications are SIMULATE-only (send-only) in Phase 7;
APPROVE/SKIP callback hardening stays Phase 8. The notify module
formats the 12 APRV-01 fields and sends via the Telegram edge adapter
(`src/adapters/telegram_notify.py`). The paper-core never imports
`python-telegram-bot` directly — the adapter is the only module that
does (RESEARCH §Pattern 3 — adapter-boundary isolation).

Journal-first ordering (RESEARCH §Pitfall 5): the caller commits the
journal row BEFORE invoking `notify_simulate`. The notify function
sends via tenacity-bounded retries, then invokes the caller-supplied
`on_outcome` callback with the `NotifyOutcome` (success or failure).
The caller journals the outcome as a `JournalEvent`. Send exceptions
never raise into the loop — they are caught, journaled via
`on_outcome`, and the function returns normally.

The 12 APRV-01 fields (per `docs/integration/TELEGRAM.md` §4):
  1. symbol
  2. direction
  3. setup
  4. entry
  5. SL
  6. TP(s)
  7. R:R
  8. risk percentage
  9. expiry
 10. invalidation
 11. current exposure
 12. clear reason codes

The module imports nothing from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + `src/core/_decimal.py` only, mirroring
the Phase-4 D-10 / Phase-5 D-05 / Phase-6 D-05 / Phase-7.1 D-05
purity precedent. The Telegram `Bot` lives behind
`src/adapters/telegram_notify.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import structlog
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_random_exponential,
)

from src.adapters.telegram_notify import (
    TelegramBot,
    build_simulate_keyboard,
    send_simulate,
)

log = structlog.get_logger()

# --------------------------------------------------------------------------- #
# NotifyOutcome — what the caller journals after each send.
# --------------------------------------------------------------------------- #


class NotifyOutcomeKind(str, Enum):
    """Outcome of a SIMULATE send attempt (D-05).

    `SENT` — the bot accepted the message (response received).
    `FAILED` — the send raised an exception after the bounded retry
    budget was exhausted. The caller journals this as a JournalEvent
    with the exception class name in the payload.
    """

    SENT = "SENT"
    FAILED = "FAILED"


@dataclass(frozen=True)
class NotifyOutcome:
    """Outcome of a SIMULATE send attempt (D-05).

    The caller journals this as a `JournalEvent` (event_type =
    "NOTIFY_OUTCOME") with the outcome kind, signal_id, and any
    error class name. The notify function never raises into the loop
    on send failure — the outcome is the only signal the caller
    receives.
    """

    kind: NotifyOutcomeKind
    signal_id: str
    error_class: str  # "" on SENT, exception class name on FAILED
    attempts: int  # number of send attempts (1 = first try succeeded)


# --------------------------------------------------------------------------- #
# Bounded-retry constants (D-05 fail-closed posture).
# --------------------------------------------------------------------------- #


# Bounded retry ceilings for the Telegram send. Module-level named
# constants so the operator can audit them before the soak starts.
# Per D-05: never infinite retry on order-adjacent paths. The send
# is order-adjacent (it precedes the simulated approval), so the
# budget is tight.
NOTIFY_MAX_ATTEMPTS: int = 3
NOTIFY_MAX_DELAY_SECONDS: int = 30
NOTIFY_WAIT_MULTIPLIER_SECONDS: int = 1
NOTIFY_WAIT_MAX_SECONDS: int = 10


# --------------------------------------------------------------------------- #
# format_simulate — render the 12 APRV-01 fields.
# --------------------------------------------------------------------------- #


def format_simulate(
    *,
    symbol: str,
    direction: str,
    setup: str,
    entry_min: Decimal,
    entry_max: Decimal,
    stop_loss: Decimal,
    take_profits: list[tuple[Decimal, Decimal]],
    rr: Decimal,
    risk_pct: Decimal,
    expiry_utc: datetime,
    invalidation: str,
    exposure_quote: Decimal,
    reason_codes: list[str],
    signal_id: str,
    detected_at_utc: datetime,
) -> str:
    """Render the SIMULATE notification text with all 12 APRV-01 fields.

    Per D-05 + TELEGRAM.md §4: the message carries exactly the 12
    fields (symbol, direction, setup, entry, SL, TP(s), R:R, risk
    percentage, expiry, invalidation, current exposure, reason codes).
    All Decimal values are formatted via `str()` preserving full
    precision (D-12). Timestamps are UTC ISO with the
    `Asia/Ho_Chi_Minh` display-edge note.

    The text is byte-stable: same inputs produce the same output
    (D-02 determinism). The format is a multi-line string with one
    field per line for operator readability.

    Fail-closed validation (WR-11): naive datetimes, empty TP lists,
    inverted entry bounds, and empty symbol/direction/setup raise
    ValueError loudly — a malformed message must never render with a
    wrong expiry or an empty TP section.
    """
    if not symbol:
        raise ValueError("symbol must be a non-empty string")
    if not direction:
        raise ValueError("direction must be a non-empty string")
    if not setup:
        raise ValueError("setup must be a non-empty string")
    if entry_min > entry_max:
        raise ValueError(
            f"entry_min ({entry_min}) must be <= entry_max ({entry_max})"
        )
    if not take_profits:
        raise ValueError("take_profits must be a non-empty list")
    for field_name, value in (
        ("expiry_utc", expiry_utc),
        ("detected_at_utc", detected_at_utc),
    ):
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be datetime, got {type(value).__name__}")
        if value.tzinfo is None:
            raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    tp_lines = "\n".join(
        f"  TP{idx + 1}: {price} ({fraction})"
        for idx, (price, fraction) in enumerate(take_profits)
    )
    reasons = ", ".join(reason_codes) if reason_codes else "(none)"
    return (
        f"SIMULATE {symbol} {direction} {setup}\n"
        f"Signal: {signal_id}\n"
        f"Detected: {detected_at_utc.astimezone(UTC).isoformat()}\n"
        f"Entry: {entry_min}–{entry_max}\n"
        f"SL: {stop_loss}\n"
        f"TPs:\n{tp_lines}\n"
        f"R:R: {rr}\n"
        f"Risk: {risk_pct}\n"
        f"Expiry: {expiry_utc.astimezone(UTC).isoformat()}\n"
        f"Invalidation: {invalidation}\n"
        f"Exposure: {exposure_quote} quote\n"
        f"Reasons: {reasons}\n"
        f"Display: Asia/Ho_Chi_Minh (UTC internally)"
    )


# --------------------------------------------------------------------------- #
# notify_simulate — journal-first send with bounded retry.
# --------------------------------------------------------------------------- #


async def notify_simulate(
    *,
    bot: TelegramBot,
    chat_id: str | int,
    payload: dict[str, Any],
    on_outcome: Callable[[NotifyOutcome], None],
) -> NotifyOutcome:
    """Send a SIMULATE notification with journal-first ordering (D-05).

    The caller MUST have committed the journal row BEFORE invoking
    this function. The notify function sends via tenacity-bounded
    retries, then invokes `on_outcome` with the `NotifyOutcome`. The
    caller journals the outcome as a `JournalEvent`.

    Send exceptions never raise into the loop — they are caught,
    journaled via `on_outcome`, and the function returns normally
    with a `FAILED` outcome.

    Contract on malformed payloads (CR-07): missing keys or invalid
    values (ValueError/KeyError/TypeError from `format_simulate`)
    yield a `FAILED` outcome with `attempts=0` — never a raise, never
    a retry. `on_outcome` itself never triggers a resend: it runs
    outside the tenacity attempt, and its own exceptions are logged,
    never retried.

    Args:
        bot: The Telegram bot (injected; tests use a fake).
        chat_id: The authorized chat id (operator-provisioned).
        payload: The 12-field payload dict (see `format_simulate`).
        on_outcome: Callback invoked with the NotifyOutcome after
            the send completes (success or failure).

    Returns:
        The NotifyOutcome (also passed to `on_outcome`).
    """

    try:
        text = format_simulate(
            symbol=payload["symbol"],
            direction=payload["direction"],
            setup=payload["setup"],
            entry_min=payload["entry_min"],
            entry_max=payload["entry_max"],
            stop_loss=payload["stop_loss"],
            take_profits=payload["take_profits"],
            rr=payload["rr"],
            risk_pct=payload["risk_pct"],
            expiry_utc=payload["expiry_utc"],
            invalidation=payload["invalidation"],
            exposure_quote=payload["exposure_quote"],
            reason_codes=payload["reason_codes"],
            signal_id=payload["signal_id"],
            detected_at_utc=payload["detected_at_utc"],
        )
        keyboard = build_simulate_keyboard(payload["signal_id"])
        signal_id = payload["signal_id"]
    except (KeyError, ValueError, TypeError) as exc:
        outcome = NotifyOutcome(
            kind=NotifyOutcomeKind.FAILED,
            signal_id=str(payload.get("signal_id", "")),
            error_class=type(exc).__name__,
            attempts=0,
        )
        try:
            on_outcome(outcome)
        except Exception:
            log.exception("paper.notify.on_outcome_failed")
        return outcome

    attempts = 0
    last_error: Exception | None = None
    try:
        async for attempt in AsyncRetrying(
            stop=(
                stop_after_attempt(NOTIFY_MAX_ATTEMPTS)
                | stop_after_delay(NOTIFY_MAX_DELAY_SECONDS)
            ),
            wait=wait_random_exponential(
                multiplier=NOTIFY_WAIT_MULTIPLIER_SECONDS,
                max=NOTIFY_WAIT_MAX_SECONDS,
            ),
            # Transient faults only (WR-02): programming errors
            # (ValueError/KeyError/TypeError) fail immediately
            # instead of burning the retry budget.
            retry=retry_if_exception(
                lambda e: not isinstance(e, (ValueError, KeyError, TypeError))
            ),
            reraise=True,
        ):
            with attempt:
                attempts += 1
                await send_simulate(
                    bot,
                    chat_id=chat_id,
                    text=text,
                    keyboard=keyboard,
                )
    except RetryError as exc:
        # Unwrap to the root cause (WR-12): the tenacity wrapper
        # class is useless for triage; journal the real error.
        attempt_exc = exc.last_attempt.exception() if exc.last_attempt else None
        last_error = attempt_exc if isinstance(attempt_exc, Exception) else exc
    except Exception as exc:
        last_error = exc

    if last_error is None:
        outcome = NotifyOutcome(
            kind=NotifyOutcomeKind.SENT,
            signal_id=signal_id,
            error_class="",
            attempts=attempts,
        )
        try:
            on_outcome(outcome)
        except Exception:
            log.exception("paper.notify.on_outcome_failed")
        return outcome

    # Send failed after the bounded retry budget. Journal the outcome
    # and return normally — never raise into the loop.
    outcome = NotifyOutcome(
        kind=NotifyOutcomeKind.FAILED,
        signal_id=signal_id,
        error_class=type(last_error).__name__,
        attempts=attempts,
    )
    try:
        on_outcome(outcome)
    except Exception:
        log.exception("paper.notify.on_outcome_failed")
    return outcome


__all__ = [
    "NOTIFY_MAX_ATTEMPTS",
    "NOTIFY_MAX_DELAY_SECONDS",
    "NOTIFY_WAIT_MAX_SECONDS",
    "NOTIFY_WAIT_MULTIPLIER_SECONDS",
    "NotifyOutcome",
    "NotifyOutcomeKind",
    "format_simulate",
    "notify_simulate",
]
