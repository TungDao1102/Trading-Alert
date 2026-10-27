"""Telegram edge adapter — send-only wrapper (Phase 7, plan 07-04).

Per D-05: paper notifications are SIMULATE-only (send-only) in Phase 7;
APPROVE/SKIP callback hardening stays Phase 8. The Telegram `Bot` and
its types live behind this edge so the paper-core never imports
`python-telegram-bot` directly (RESEARCH §Pattern 3 — adapter-boundary
isolation, mirroring `src/adapters/binance_usdm.py`).

The adapter exposes `send_simulate(bot, *, chat_id, text, keyboard)`
which delegates to `bot.send_message(chat_id=chat_id, text=text,
reply_markup=keyboard)`. Tests inject a fake `bot` so unit tests
never touch the network.

The module also exposes `build_simulate_keyboard(signal_id)` which
constructs the inert callback-data labels. Phase 8 will replace the
literal "SIMULATE-recorded" label with a real handler binding; the
labels stay verbatim today because downstream code reads them.

Phase 8, plan 08-02 (D-02): the APPROVE/SKIP alert path. The module
now exposes `format_approve(...)` (a PTB-free text renderer) plus
`build_approve_keyboard(signal_id)` / `build_skip_keyboard(signal_id)`
which emit `APR:<short>` / `SKP:<short>` callback_data within Telegram's
64-byte limit. The text renderer mirrors `format_simulate` posture
exactly: same 12 APRV-01 fields, same fail-closed validation, same
Decimal str precision. The PTB-free renderer is the canonical
extension point so paper-core reuse keeps adapter isolation
(`src/paper/notify.py` never imports python-telegram-bot).
"""

from __future__ import annotations

import hashlib
import math
import warnings
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Literal, Protocol

from src.risk.money_at_stake import MONEY_AT_STAKE_MISSING, MoneyAtStake

if TYPE_CHECKING:
    from telegram import InlineKeyboardMarkup


class TelegramBot(Protocol):
    """Structural type for the Bot.send_message surface we consume.

    Mirrors the official `telegram.Bot.send_message` signature we use;
    tests inject a fake bot that records calls without hitting the
    network.
    """

    async def send_message(
        self,
        *,
        chat_id: str | int,
        text: str,
        reply_markup: InlineKeyboardMarkup,
    ) -> object: ...


async def send_simulate(
    bot: TelegramBot,
    *,
    chat_id: str | int,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> object:
    """Send a SIMULATE-style read-only notification.

    Calls `bot.send_message(chat_id=chat_id, text=text,
    reply_markup=keyboard)`. No inbound callbacks are consumed —
    callbacks are inert labels until Phase 8 hardens them.

    Returns the bot's response message object (typically a
    `telegram.Message`).
    """
    return await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
    )


def _short_signal_id(signal_id: str) -> str:
    """Compress a signal id to 32 hex chars (CR-05).

    Telegram enforces a 64-byte limit on `callback_data`; real signal
    ids already exceed it with the `SIM:`/`SKIP:` prefix. The sha256
    prefix is deterministic (same signal id → same short id) so
    duplicate sends stay idempotent. Phase-7 callbacks are inert
    labels (no inbound dispatch); Phase 8 must keep a short→full
    mapping when it binds real handlers.
    """
    return hashlib.sha256(signal_id.encode("utf-8")).hexdigest()[:32]


def build_simulate_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    """Build the SIMULATE keyboard with inert callback labels.

    Per D-05: callbacks are inert labels in Phase 7 (no inbound
    actions consumed). Phase 8 will replace the literal labels with
    real handler bindings. The label "SIMULATE-recorded" matches the
    Phase-8 APRV-01 contract so the wire format is stable.

    The keyboard carries exactly two buttons: a SIMULATE-recorded
    marker and a SKIP (Phase 8) marker. The operator sees both
    buttons but neither performs an action today.

    `callback_data` stays within Telegram's 64-byte limit via
    `_short_signal_id` (CR-05).

    Since Phase 23 no production path sends this keyboard; it stays for wire-format stability
    (use `build_decision_keyboard`).
    """
    short = _short_signal_id(signal_id)
    sim_data = f"SIM:{short}"
    skip_data = f"SKIP:{short}"
    for payload in (sim_data, skip_data):
        if len(payload.encode("utf-8")) > 64:
            raise ValueError(
                f"callback_data exceeds 64 bytes: {len(payload.encode('utf-8'))} bytes"
            )
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("SIMULATE-recorded", callback_data=sim_data),
                InlineKeyboardButton("SKIP (Phase 8)", callback_data=skip_data),
            ]
        ]
    )


# --------------------------------------------------------------------------- #
# Phase 8 plan 08-02 (D-02) — APPROVE/SKIP 12-field alert.
# --------------------------------------------------------------------------- #


# Telegram's hard callback_data limit (bytes, UTF-8).
TELEGRAM_CALLBACK_DATA_MAX_BYTES: int = 64

# Callback-data prefixes. APR/SKP are the live Phase-8 prefixes; SIM/SKIP
# remain the inert Phase-7 labels (D-02 wire-format stability).
APR_PREFIX: str = "APR:"
SKP_PREFIX: str = "SKP:"
SIM_PREFIX: str = "SIM:"
SKIP_PREFIX: str = "SKIP:"
# SHADOW confirm step (Phase 16, plan 16-11, D041): the second press after APPROVE.
CNF_PREFIX: str = "CNF:"
CXL_PREFIX: str = "CXL:"


def _short_signal_id_with_prefix(signal_id: str, prefix: str) -> str:
    """Compose a `prefix:<short>` callback_data within Telegram's 64-byte
    ceiling.

    The full payload is `prefix` (4 ASCII chars) + 32 hex chars = 36
    bytes — well under the 64-byte limit. Any caller passing a longer
    prefix triggers a ValueError so a future refactor cannot silently
    violate the ceiling.
    """
    if not isinstance(prefix, str) or len(prefix) == 0:
        raise ValueError("prefix must be a non-empty string")
    if len(prefix) > 16:
        # 16-byte prefix leaves room for 48 short-id chars; we only
        # use 32, so this guard is generous.
        raise ValueError(
            f"prefix too long ({len(prefix)} chars); Telegram limit "
            f"is {TELEGRAM_CALLBACK_DATA_MAX_BYTES} bytes"
        )
    if not isinstance(signal_id, str) or signal_id == "":
        raise ValueError("signal_id must be a non-empty string")
    short = _short_signal_id(signal_id)
    payload = f"{prefix}{short}"
    if len(payload.encode("utf-8")) > TELEGRAM_CALLBACK_DATA_MAX_BYTES:
        raise AssertionError(
            f"callback_data exceeds {TELEGRAM_CALLBACK_DATA_MAX_BYTES} "
            f"bytes: {len(payload.encode('utf-8'))} bytes"
        )
    return payload


def build_approve_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    """Build the APPROVE keyboard.

    Per D-02: the callback_data is `APR:<short>` where `<short>` is
    `sha256(signal_id)[:32]` (32 hex chars). The full payload is
    `APR:` (4) + 32 hex = 36 bytes, well under Telegram's 64-byte
    limit. The keyboard carries exactly one button labeled APPROVE;
    the SKIP button is a separate keyboard so each callback_data
    carries a single short id and the receiver parses one prefix at
    a time.

    Since Phase 23 no production path sends this single-button keyboard; the message carries
    `build_decision_keyboard` (APPROVE and SKIP in one row). It stays for wire-format stability.
    """
    apr_data = _short_signal_id_with_prefix(signal_id, APR_PREFIX)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([[InlineKeyboardButton("APPROVE", callback_data=apr_data)]])


def build_skip_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    """Build the SKIP keyboard.

    Per D-02: the callback_data is `SKP:<short>` where `<short>` is
    `sha256(signal_id)[:32]` (32 hex chars). The full payload is
    `SKP:` (4) + 32 hex = 36 bytes, well under Telegram's 64-byte
    limit. The keyboard carries exactly one button labeled SKIP.

    Since Phase 23 no production path sends this single-button keyboard; the message carries
    `build_decision_keyboard` (APPROVE and SKIP in one row). It stays for wire-format stability.
    """
    skp_data = _short_signal_id_with_prefix(signal_id, SKP_PREFIX)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([[InlineKeyboardButton("SKIP", callback_data=skp_data)]])


def build_decision_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    """Build the decision keyboard: one row, an APPROVE and a SKIP button, for every mode.

    One message carries both buttons in SHADOW, DEMO and LIVE (Phase 23, D-05). Button contract
    (Phase 16, plan 16-04, D-16, F-961): the live `APR:` and `SKP:` prefixes ONLY, so a SKIP press
    is recorded as SKIPPED and never as an inert SIMULATE label (F-405). Both buttons carry the
    same short id (`sha256(signal_id)[:32]`), so one short-id mapping backs the pair, and both are
    backed by a PENDING approval row. The SIMULATE-only keyboard (`build_simulate_keyboard`, inert
    `SIM:`/`SKIP:` data that resolves to SIMULATE_RECORDED and never advances an approval) stays
    in this module only for wire-format stability (Phase 7 D-05).

    Each payload is `APR:`/`SKP:` (4 bytes) + 32 hex = 36 bytes, under Telegram's 64-byte limit;
    `_short_signal_id_with_prefix` re-checks the ceiling.
    """
    apr_data = _short_signal_id_with_prefix(signal_id, APR_PREFIX)
    skp_data = _short_signal_id_with_prefix(signal_id, SKP_PREFIX)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("APPROVE", callback_data=apr_data),
                InlineKeyboardButton("SKIP", callback_data=skp_data),
            ]
        ]
    )


def build_shadow_decision_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    """The SHADOW decision keyboard: `build_decision_keyboard`, kept under its Phase 16 name."""
    return build_decision_keyboard(signal_id)


def build_confirm_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    """Build the SHADOW confirmation keyboard: one row, a CONFIRM and a CANCEL button.

    Phase 16, plan 16-11 (D041, L-13). The callback data is `CNF:<short>` / `CXL:<short>` with
    the same short id (`sha256(signal_id)[:32]`) as the alert it replaces, 36 bytes each. The
    confirm token itself never travels in the callback data: it is held in memory by the
    SHADOW confirm layer and looked up by this short id.
    """
    cnf_data = _short_signal_id_with_prefix(signal_id, CNF_PREFIX)
    cxl_data = _short_signal_id_with_prefix(signal_id, CXL_PREFIX)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("CONFIRM", callback_data=cnf_data),
                InlineKeyboardButton("CANCEL", callback_data=cxl_data),
            ]
        ]
    )


class TelegramTextBot(Protocol):
    """Structural type for the plain-text send and edit surface of `telegram.Bot`."""

    async def send_message(
        self,
        *,
        chat_id: str | int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> object: ...

    async def edit_message_text(
        self,
        *,
        chat_id: str | int,
        message_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> object: ...

    async def edit_message_reply_markup(
        self,
        *,
        chat_id: str | int,
        message_id: int,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> object: ...


# --------------------------------------------------------------------------- #
# Plan 16-04 (D-12, D-16): Telegram failures are classified HERE, once.
# --------------------------------------------------------------------------- #


class TelegramFailureKind(str, Enum):
    """How a Telegram call failed, as far as the SHADOW layer needs to know.

    `RATE_LIMITED` carries the server's retry_after. `MESSAGE_NOT_MODIFIED` is the benign edit of
    a message to identical text. `TRANSIENT` is a network fault or timeout (worth a bounded
    retry). `REJECTED` is a refusal a retry cannot fix (bad request, bot blocked, invalid token,
    chat migrated). `UNKNOWN` is everything else and is never swallowed.

    The mapping follows python-telegram-bot's documented exception classes; the wording of the
    live Bot API error texts is not verified against the live service here (recorded in
    docs/SOURCES.md by plan 16-17).
    """

    RATE_LIMITED = "RATE_LIMITED"
    MESSAGE_NOT_MODIFIED = "MESSAGE_NOT_MODIFIED"
    TRANSIENT = "TRANSIENT"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TelegramFailure:
    """A classified failure. `detail` is the exception CLASS NAME only: never message text."""

    kind: TelegramFailureKind
    retry_after_seconds: int | None
    detail: str


class TelegramSendError(Exception):
    """A send or edit failed; carries the classified failure (no python-telegram-bot type)."""

    def __init__(self, failure: TelegramFailure) -> None:
        super().__init__(f"telegram {failure.kind.value}: {failure.detail}")
        self.failure = failure


def _whole_seconds(value: object) -> int:
    """`RetryAfter.retry_after` is an int, or a timedelta once PTB_TIMEDELTA is on; round up."""
    seconds = value.total_seconds() if isinstance(value, timedelta) else float(str(value))
    return max(0, math.ceil(seconds))


def classify_telegram_error(exc: BaseException) -> TelegramFailure:
    """Map an exception to a `TelegramFailure` (the only place that knows PTB's classes).

    Order matters: python-telegram-bot's `BadRequest` and `TimedOut` are subclasses of
    `NetworkError`, so they are tested first.
    """
    from telegram import error as tg_error

    detail = type(exc).__name__
    if isinstance(exc, tg_error.RetryAfter):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # reading retry_after as int is deprecated in PTB 22.2
            retry_after = exc.retry_after
        return TelegramFailure(
            TelegramFailureKind.RATE_LIMITED, _whole_seconds(retry_after), detail
        )
    if isinstance(exc, tg_error.BadRequest):
        if "message is not modified" in str(exc).lower():
            return TelegramFailure(TelegramFailureKind.MESSAGE_NOT_MODIFIED, None, detail)
        return TelegramFailure(TelegramFailureKind.REJECTED, None, detail)
    if isinstance(exc, (tg_error.Forbidden, tg_error.InvalidToken, tg_error.ChatMigrated)):
        return TelegramFailure(TelegramFailureKind.REJECTED, None, detail)
    if isinstance(exc, (tg_error.NetworkError, tg_error.TimedOut)):
        return TelegramFailure(TelegramFailureKind.TRANSIENT, None, detail)
    return TelegramFailure(TelegramFailureKind.UNKNOWN, None, detail)


async def send_text(
    bot: TelegramTextBot,
    chat_id: str | int,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> object:
    """Send one text message, with an optional keyboard.

    Any failure other than a programming error (ValueError, KeyError, TypeError) is raised as a
    `TelegramSendError` carrying the classified failure. The original exception is not chained:
    its message may carry request details.
    """
    try:
        return await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
    except (ValueError, KeyError, TypeError):
        raise
    except Exception as exc:  # noqa: BLE001 - classified, never swallowed
        raise TelegramSendError(classify_telegram_error(exc)) from None


async def edit_text(
    bot: TelegramTextBot,
    chat_id: str | int,
    message_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> object:
    """Edit one message's text (same failure handling as `send_text`)."""
    try:
        return await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, reply_markup=keyboard
        )
    except (ValueError, KeyError, TypeError):
        raise
    except Exception as exc:  # noqa: BLE001 - classified, never swallowed
        raise TelegramSendError(classify_telegram_error(exc)) from None


async def edit_to_confirm_card(
    bot: TelegramTextBot,
    chat_id: str | int,
    message_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> object:
    """Edit the alert message into the SHADOW confirmation card (plan 16-11).

    A failure arrives as a `TelegramSendError` with a classified failure, exactly as for
    `edit_text` (`MESSAGE_NOT_MODIFIED` included: the caller decides that it counts as success).
    """
    return await edit_text(bot, chat_id, message_id, text, keyboard)


async def edit_reply_markup(
    bot: TelegramTextBot,
    chat_id: str | int,
    message_id: int,
    keyboard: InlineKeyboardMarkup | None = None,
) -> object:
    """Edit only the keyboard of one message (same failure handling as `send_text`)."""
    try:
        return await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=keyboard
        )
    except (ValueError, KeyError, TypeError):
        raise
    except Exception as exc:  # noqa: BLE001 - classified, never swallowed
        raise TelegramSendError(classify_telegram_error(exc)) from None


# --------------------------------------------------------------------------- #
# Phase 23, plan 23-07 (D-06, D-07): a decided message is made final, within a bound.
#
# These helpers wrap Telegram MESSAGE calls only. Nothing here, and nothing else in the Telegram
# adapters, imports or retries a placement: a placement is never re-sent (Q5, D080). The two
# bounds restate `NOTIFY_MAX_ATTEMPTS` and `NOTIFY_MAX_DELAY_SECONDS` of `src.paper.notify` (this
# adapter must not import the paper package); a test pins the equality.
# --------------------------------------------------------------------------- #

EDIT_MAX_ATTEMPTS: int = 3
TELEGRAM_RETRY_WAIT_CAP_SECONDS: int = 30

SleepFn = Callable[[float], Awaitable[None]]


def build_removed_keyboard() -> InlineKeyboardMarkup:
    """An explicit EMPTY inline keyboard: sent as `reply_markup` it removes the buttons.

    Whether an empty markup removes the keyboard on the live Bot API is research assumption A1
    (owner-run check, plan 23-13); `finalize_decided_message` falls back once to a keyboard-only
    edit, and the state-based stale-tap refusal is the real guarantee.
    """
    from telegram import InlineKeyboardMarkup

    return InlineKeyboardMarkup([])


@dataclass(frozen=True)
class BoundedOutcome:
    """The end of a bounded call: its result, the attempts made and the final failure (or None).

    `failure` is None on success, which includes a benign "message is not modified" (then
    `result` is None). `failure.detail` is an exception class name, never message text.
    """

    result: object | None
    attempts: int
    failure: TelegramFailure | None

    @property
    def ok(self) -> bool:
        return self.failure is None


async def call_bounded(
    op: Callable[[], Awaitable[object]],
    *,
    sleep: SleepFn,
    max_attempts: int = EDIT_MAX_ATTEMPTS,
    retry_after_cap_seconds: int = TELEGRAM_RETRY_WAIT_CAP_SECONDS,
    window_seconds: float | None = None,
) -> BoundedOutcome:
    """Await `op()` up to `max_attempts` times, honouring the server's RetryAfter.

    A failure is classified once (a `TelegramSendError` already carries its failure; a raw
    exception goes through `classify_telegram_error`; ValueError, KeyError and TypeError are
    programming errors and propagate). "Message is not modified" is success. RATE_LIMITED sleeps
    the server's `retry_after` and retries, but stops WITHOUT sleeping when it exceeds
    `retry_after_cap_seconds` or the remaining `window_seconds` (the total sleep budget, None =
    unbounded by a window). TRANSIENT retries without a sleep. REJECTED and UNKNOWN stop: a
    refusal is never retried. No sleep follows the last attempt. The outcome is returned, never
    raised. For messages only: never wrap a placement in this function (Q5, D080).
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    slept = 0.0
    attempts = 0
    while True:
        attempts += 1
        try:
            return BoundedOutcome(await op(), attempts, None)
        except (ValueError, KeyError, TypeError):
            raise
        except TelegramSendError as exc:
            failure = exc.failure
        except Exception as exc:  # noqa: BLE001 - classified, reported by class name only
            failure = classify_telegram_error(exc)
        if failure.kind is TelegramFailureKind.MESSAGE_NOT_MODIFIED:
            return BoundedOutcome(None, attempts, None)
        if attempts >= max_attempts:
            return BoundedOutcome(None, attempts, failure)
        if failure.kind is TelegramFailureKind.RATE_LIMITED:
            wait = failure.retry_after_seconds or 0
            if wait > retry_after_cap_seconds:
                return BoundedOutcome(None, attempts, failure)
            if window_seconds is not None and wait > window_seconds - slept:
                return BoundedOutcome(None, attempts, failure)
            await sleep(wait)
            slept += wait
            continue
        if failure.kind is TelegramFailureKind.TRANSIENT:
            continue
        return BoundedOutcome(None, attempts, failure)


async def send_text_bounded(
    bot: TelegramTextBot,
    chat_id: str | int,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
    *,
    sleep: SleepFn,
    max_attempts: int = EDIT_MAX_ATTEMPTS,
    retry_after_cap_seconds: int = TELEGRAM_RETRY_WAIT_CAP_SECONDS,
    window_seconds: float | None = None,
) -> BoundedOutcome:
    """Send one text message through `call_bounded` (`result` is the sent message)."""
    return await call_bounded(
        lambda: send_text(bot, chat_id, text, keyboard),
        sleep=sleep,
        max_attempts=max_attempts,
        retry_after_cap_seconds=retry_after_cap_seconds,
        window_seconds=window_seconds,
    )


@dataclass(frozen=True)
class FinalizeOutcome:
    """What `finalize_decided_message` achieved: `done`, the last `method` tried, the attempts."""

    done: bool
    method: Literal["edit_text", "edit_reply_markup"]
    attempts: int
    failure: TelegramFailure | None


async def finalize_decided_message(
    bot: TelegramTextBot,
    *,
    chat_id: str | int,
    message_id: int,
    text: str | None,
    sleep: SleepFn,
    max_attempts: int = EDIT_MAX_ATTEMPTS,
    retry_after_cap_seconds: int = TELEGRAM_RETRY_WAIT_CAP_SECONDS,
    window_seconds: float | None = None,
) -> FinalizeOutcome:
    """Make a decided message final: its final text AND no keyboard, in one `editMessageText`.

    With `text` the edit carries the empty keyboard as `reply_markup`; with `text` None (a restart
    lost it) only the keyboard is removed. A refused text edit falls back ONCE to a keyboard-only
    edit. The outcome is returned and never raised, so a failed removal never rolls back a
    decision (D-06, F-509, research Pitfall 6).
    """
    keyboard = build_removed_keyboard()

    async def _bounded(op: Callable[[], Awaitable[object]]) -> BoundedOutcome:
        return await call_bounded(
            op,
            sleep=sleep,
            max_attempts=max_attempts,
            retry_after_cap_seconds=retry_after_cap_seconds,
            window_seconds=window_seconds,
        )

    attempts = 0
    if text is not None:
        edited = await _bounded(lambda: edit_text(bot, chat_id, message_id, text, keyboard))
        attempts += edited.attempts
        if edited.failure is None:
            return FinalizeOutcome(True, "edit_text", attempts, None)
        if edited.failure.kind is not TelegramFailureKind.REJECTED:
            return FinalizeOutcome(False, "edit_text", attempts, edited.failure)
    removed = await _bounded(lambda: edit_reply_markup(bot, chat_id, message_id, keyboard))
    attempts += removed.attempts
    return FinalizeOutcome(removed.failure is None, "edit_reply_markup", attempts, removed.failure)


# --------------------------------------------------------------------------- #
# format_approve — PTB-free 12-field renderer (mirrors format_simulate).
# --------------------------------------------------------------------------- #


def format_utc(instant: datetime) -> str:
    """Show an instant as `YYYY-MM-DD HH:MM:SS UTC` (Phase 23, D-14; owner item O-3 is open).

    The suffix is explicit so no reader has to guess the zone. A naive instant is refused; an
    aware one in another zone is converted to UTC first.
    """
    if not isinstance(instant, datetime):
        raise TypeError(f"instant must be datetime, got {type(instant).__name__}")
    if instant.tzinfo is None:
        raise ValueError("instant must be UTC-aware, got naive datetime")
    return instant.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S") + " UTC"


def _approve_lines(
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
    approved_quantity: Decimal,
    mode_label: str | None = None,
    money_lines: tuple[str, ...] = (),
) -> list[str]:
    """Validate the fields fail-closed and return the APPROVE text as a list of lines.

    `mode_label` adds a `Mode: <label>` line directly after the first line and `money_lines`
    are inserted directly after the `Quantity:` line (D-13). Both are empty for
    `format_approve`, so its text is the 12-field message plus the quantity. Every validation
    of the original `format_approve` (WR-11) lives here, unchanged.
    """
    if not symbol:
        raise ValueError("symbol must be a non-empty string")
    if not direction:
        raise ValueError("direction must be a non-empty string")
    if not setup:
        raise ValueError("setup must be a non-empty string")
    if entry_min > entry_max:
        raise ValueError(f"entry_min ({entry_min}) must be <= entry_max ({entry_max})")
    if not take_profits:
        raise ValueError("take_profits must be a non-empty list")
    if not isinstance(stop_loss, Decimal) or stop_loss <= 0:
        raise ValueError(f"stop_loss must be a positive Decimal, got {stop_loss!r}")
    for field_name, value in (
        ("rr", rr),
        ("risk_pct", risk_pct),
        ("exposure_quote", exposure_quote),
    ):
        if not isinstance(value, Decimal) or value < 0:
            raise ValueError(f"{field_name} must be a non-negative Decimal, got {value!r}")
    for idx, (price, fraction) in enumerate(take_profits):
        if not isinstance(price, Decimal) or price <= 0:
            raise ValueError(f"take_profits[{idx}].price must be a positive Decimal, got {price!r}")
        if not isinstance(fraction, Decimal) or not (Decimal(0) < fraction <= Decimal(1)):
            raise ValueError(
                f"take_profits[{idx}].fraction must be a Decimal in (0, 1], got {fraction!r}"
            )
    if (
        not isinstance(approved_quantity, Decimal)
        or not approved_quantity.is_finite()
        or not approved_quantity > 0
    ):
        raise ValueError(
            "approved_quantity must be a finite Decimal greater than zero, "
            f"got {approved_quantity!r}"
        )
    if not isinstance(invalidation, str) or invalidation == "":
        raise ValueError("invalidation must be a non-empty string")
    if not isinstance(reason_codes, list) or not all(isinstance(r, str) for r in reason_codes):
        raise ValueError("reason_codes must be a list[str]")
    for code in reason_codes:
        if "\n" in code or "\r" in code:
            raise ValueError(f"reason_codes entry must not contain newlines: {code!r}")
    for ts_name, ts_value in (
        ("expiry_utc", expiry_utc),
        ("detected_at_utc", detected_at_utc),
    ):
        if not isinstance(ts_value, datetime):
            raise TypeError(f"{ts_name} must be datetime, got {type(ts_value).__name__}")
        if ts_value.tzinfo is None:
            raise ValueError(f"{ts_name} must be UTC-aware, got naive datetime")
    tp_lines = [
        f"  TP{idx + 1}: {price} ({fraction})" for idx, (price, fraction) in enumerate(take_profits)
    ]
    reasons = ", ".join(reason_codes) if reason_codes else "(none)"
    mode_lines = [] if mode_label is None else [f"Mode: {mode_label}"]
    return [
        f"APPROVE {symbol} {direction} {setup}",
        *mode_lines,
        f"Signal: {signal_id}",
        f"Detected: {format_utc(detected_at_utc)}",
        f"Entry: {entry_min}–{entry_max}",
        f"Quantity: {format(approved_quantity, 'f')}",
        *money_lines,
        f"SL: {stop_loss}",
        "TPs:",
        *tp_lines,
        f"R:R: {rr}",
        f"Risk: {risk_pct}",
        f"Expiry: {format_utc(expiry_utc)}",
        f"Invalidation: {invalidation}",
        f"Exposure: {exposure_quote} quote",
        f"Reasons: {reasons}",
    ]


def format_approve(
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
    approved_quantity: Decimal,
) -> str:
    """Render the APPROVE notification text with all 12 APRV-01 fields and the quantity.

    Per D-02 + TELEGRAM.md §4: the message carries exactly the 12
    fields (symbol, direction, setup, entry, SL, TP(s), R:R, risk
    percentage, expiry, invalidation, current exposure, reason codes).
    All Decimal values are formatted via `str()` preserving full
    precision (D-12). Since Phase 23 (D-14) the two times are shown as
    `YYYY-MM-DD HH:MM:SS UTC` with an explicit suffix and the message
    carries no display-zone note (owner item O-3 is open; docs/DECISIONS.md
    D025 names Asia/Ho_Chi_Minh as the presentation zone, which this text does
    not use). The SHADOW alert strips the `Detected:` and `Expiry:` lines and
    shows its own pairs, so SHADOW text is unchanged.

    The text is byte-stable: same inputs produce the same output
    (D-02 determinism). The format is a multi-line string with one
    field per line for operator readability. The text starts with
    "APPROVE " so the operator can identify the message type at a
    glance.

    The message also carries the approved quantity (D078 item (6)) on a `Quantity:`
    line directly after the `Entry:` line: the value stored as `approved_quantity` on the
    approval row, written in fixed-point notation with every digit of the Decimal and
    never rounded. `approved_quantity` is a required keyword; a value that is not a finite
    Decimal above zero raises ValueError, so no APPROVE message renders without it.

    The renderer is PTB-free: it does NOT import python-telegram-bot
    and is safe to call from `src/paper/notify.py` (adapter-boundary
    isolation). The keyboard builders live in this same module so
    the Phase-8 wire format is defined in one place.

    Fail-closed validation (WR-11): naive datetimes, empty TP lists,
    inverted entry bounds, and empty symbol/direction/setup raise
    ValueError loudly — a malformed APPROVE message must never
    render with a wrong expiry or an empty TP section.
    """
    return "\n".join(
        _approve_lines(
            symbol=symbol,
            direction=direction,
            setup=setup,
            entry_min=entry_min,
            entry_max=entry_max,
            stop_loss=stop_loss,
            take_profits=take_profits,
            rr=rr,
            risk_pct=risk_pct,
            expiry_utc=expiry_utc,
            invalidation=invalidation,
            exposure_quote=exposure_quote,
            reason_codes=reason_codes,
            signal_id=signal_id,
            detected_at_utc=detected_at_utc,
            approved_quantity=approved_quantity,
        )
    )


# --------------------------------------------------------------------------- #
# Money at stake (Phase 23, D-13, F-015): formatted from the STORED value, never recomputed.
# --------------------------------------------------------------------------- #

#: The two modes whose APPROVE request carries a `Mode:` line and the money block. SHADOW keeps
#: its own envelope (`src/paper/shadow.py`).
REQUEST_MODE_LABELS: tuple[str, ...] = ("DEMO", "LIVE")


def _money_or_refuse(money: object) -> MoneyAtStake:
    if not isinstance(money, MoneyAtStake):
        raise ValueError(
            f"{MONEY_AT_STAKE_MISSING}: money must be a MoneyAtStake, got {type(money).__name__}"
        )
    return money


def render_money_block(money: MoneyAtStake) -> tuple[str, ...]:
    """The money lines in the D-13 order: notional, margin, SL loss, one profit per TP, equity.

    Every amount is the stored Decimal written with `format(value, "f")`: no multiplication, no
    rounding, no exponent notation, no cost call. The quote asset is named on every amount and
    the time is shown through `format_utc`.
    """
    stored = _money_or_refuse(money)
    asset = stored.quote_asset
    profit_lines = tuple(
        f"Profit at {leg.label} ({format(leg.fraction, 'f')} of quantity): "
        f"{format(leg.profit_gross, 'f')} {asset} gross, "
        f"{format(leg.profit_net, 'f')} {asset} net of modeled costs"
        for leg in stored.take_profits
    )
    return (
        f"Notional: {format(stored.notional, 'f')} {asset}",
        f"Margin: {format(stored.initial_margin, 'f')} {asset} at {stored.leverage}x leverage "
        f"({stored.leverage_source})",
        f"Loss at SL: {format(stored.loss_at_stop_gross, 'f')} {asset} gross, "
        f"{format(stored.loss_at_stop_net, 'f')} {asset} net of modeled costs",
        *profit_lines,
        f"Equity used: {format(stored.equity, 'f')} {asset} ({stored.equity_source}, "
        f"observed {format_utc(stored.equity_observed_at_utc)})",
    )


def require_money_consistent(
    money: MoneyAtStake,
    *,
    direction: str,
    approved_quantity: Decimal,
    stop_loss: Decimal,
    take_profits: list[tuple[Decimal, Decimal]],
) -> None:
    """Refuse (ValueError naming the field) a money block that disagrees with the message.

    The money block is stored with the approval; the message fields come from the same plan. A
    difference means one of them is not the plan the operator would approve (F-015), so the
    message is never rendered.
    """
    stored = _money_or_refuse(money)
    if stored.side != direction:
        raise ValueError(f"money.side {stored.side!r} differs from direction {direction!r}")
    if stored.quantity != approved_quantity:
        raise ValueError(
            f"money.quantity {stored.quantity} differs from approved_quantity {approved_quantity}"
        )
    if stored.stop_loss_price != stop_loss:
        raise ValueError(
            f"money.stop_loss_price {stored.stop_loss_price} differs from stop_loss {stop_loss}"
        )
    if len(stored.take_profits) != len(take_profits):
        raise ValueError(
            f"money take_profits has {len(stored.take_profits)} legs, "
            f"the message has {len(take_profits)}"
        )
    for index, (leg, (price, fraction)) in enumerate(
        zip(stored.take_profits, take_profits, strict=True), start=1
    ):
        if leg.price != price:
            raise ValueError(f"money take_profits TP{index} price {leg.price} differs from {price}")
        if leg.fraction != fraction:
            raise ValueError(
                f"money take_profits TP{index} fraction {leg.fraction} differs from {fraction}"
            )


def format_approval_request(
    *,
    mode_label: str,
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
    approved_quantity: Decimal,
    money: MoneyAtStake,
) -> str:
    """The DEMO or LIVE APPROVE request: the 12 fields, the quantity and the money block.

    The text is `format_approve`'s with `Mode: <label>` after the first line and the money lines
    (`render_money_block`) directly after `Quantity:` (D-13). `money` is required and must agree
    with the quantity, stop, take-profit prices and fractions of the message; a missing money
    block (`MONEY_AT_STAKE_MISSING`), a different mode label or any mismatch raises ValueError,
    so the request is never sent.
    """
    if mode_label not in REQUEST_MODE_LABELS:
        raise ValueError(f"mode_label must be DEMO or LIVE, got {mode_label!r}")
    require_money_consistent(
        money,
        direction=direction,
        approved_quantity=approved_quantity,
        stop_loss=stop_loss,
        take_profits=take_profits,
    )
    return "\n".join(
        _approve_lines(
            symbol=symbol,
            direction=direction,
            setup=setup,
            entry_min=entry_min,
            entry_max=entry_max,
            stop_loss=stop_loss,
            take_profits=take_profits,
            rr=rr,
            risk_pct=risk_pct,
            expiry_utc=expiry_utc,
            invalidation=invalidation,
            exposure_quote=exposure_quote,
            reason_codes=reason_codes,
            signal_id=signal_id,
            detected_at_utc=detected_at_utc,
            approved_quantity=approved_quantity,
            mode_label=mode_label,
            money_lines=render_money_block(money),
        )
    )


# --------------------------------------------------------------------------- #
# The DEMO/LIVE confirmation card (Phase 23, plan 23-12; D041, D-09, D-11, D-12, D-13).
#
# The card replaces the request after APPROVE: it names what CONFIRM would hand to the execution
# step. Every amount is the STORED `MoneyAtStake` value written with `format(value, "f")`: nothing
# is multiplied or rounded here. Times are UTC with the suffix (D-14). The validity line carries
# the verdict of the placement gate's own rule, handed in as a code (None = passes).
# --------------------------------------------------------------------------- #

LiveConfirmOutcome = Literal["CONFIRMED", "CANCELLED", "EXPIRED", "REFUSED"]
_LIVE_CONFIRM_OUTCOMES: tuple[str, ...] = ("CONFIRMED", "CANCELLED", "EXPIRED", "REFUSED")


def _one_line(value: str, field: str) -> str:
    if not isinstance(value, str) or value == "" or "\n" in value or "\r" in value:
        raise ValueError(f"{field} must be a non-empty single line")
    return value


def _live_confirm_head(
    *, mode_label: str, symbol: str, side: str, money: MoneyAtStake
) -> list[str]:
    """The lines the card and every final text share: header, mode, quantity, notional, loss."""
    if mode_label not in REQUEST_MODE_LABELS:
        raise ValueError(f"mode_label must be DEMO or LIVE, got {mode_label!r}")
    _one_line(symbol, "symbol")
    stored = _money_or_refuse(money)
    if stored.side != side:
        raise ValueError(f"money.side {stored.side!r} differs from side {side!r}")
    asset = stored.quote_asset
    return [
        f"CONFIRM {symbol} {side}",
        f"Mode: {mode_label}",
        f"Quantity: {format(stored.quantity, 'f')}",
        f"Notional: {format(stored.notional, 'f')} {asset}",
        f"Loss at SL: {format(stored.loss_at_stop_gross, 'f')} {asset} gross, "
        f"{format(stored.loss_at_stop_net, 'f')} {asset} net of modeled costs",
    ]


def format_live_confirm_card(
    *,
    mode_label: str,
    symbol: str,
    side: str,
    money: MoneyAtStake,
    mark_price: Decimal | None,
    plan_expiry_utc: datetime,
    validity_verdict: str | None,
    now_utc: datetime,
    ttl_seconds: int,
) -> str:
    """The DEMO or LIVE confirmation card: mode, size, stored money, mark, validity, window.

    `mark_price` None is shown as `unavailable` (never a guessed number). `validity_verdict` is
    the code of the gate's remaining-validity rule or None when it passes; with the owner's minimum
    not configured it is `LIMITS_NOT_CONFIGURED` and the card says so (it never invents a minimum).
    """
    head = _live_confirm_head(mode_label=mode_label, symbol=symbol, side=side, money=money)
    stored = _money_or_refuse(money)
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        raise ValueError(f"ttl_seconds must be a positive integer, got {ttl_seconds!r}")
    expiry_text = format_utc(plan_expiry_utc)
    until_text = format_utc(now_utc + timedelta(seconds=ttl_seconds))
    if mark_price is None:
        mark_text = "unavailable"
    elif isinstance(mark_price, Decimal) and mark_price.is_finite():
        mark_text = format(mark_price, "f")
    else:
        raise ValueError(f"mark_price must be a finite Decimal or None, got {mark_price!r}")
    remaining = max(0, int((plan_expiry_utc - now_utc).total_seconds()))
    check = (
        "passes"
        if validity_verdict is None
        else f"refused ({_one_line(validity_verdict, 'validity_verdict')})"
    )
    return "\n".join(
        [
            *head,
            f"Mark price: {mark_text} (entry {format(stored.entry_price, 'f')}, "
            f"SL {format(stored.stop_loss_price, 'f')})",
            f"Remaining validity: {remaining} s to the plan expiry {expiry_text}; "
            f"placement check: {check}",
            f"Confirm until {until_text} ({ttl_seconds} s window)",
        ]
    )


def format_live_confirm_final(
    *,
    mode_label: str,
    symbol: str,
    side: str,
    money: MoneyAtStake,
    outcome: LiveConfirmOutcome,
    at_utc: datetime,
    user_id: int | str | None = None,
    reason: str | None = None,
    placement_lines: Sequence[str] = (),
) -> str:
    """The final text of a card that is decided: the shared head, then one outcome line.

    CONFIRMED and CANCELLED name the user; EXPIRED and REFUSED name the reason code. A CONFIRMED
    final always carries the placement lines (what the stored entry intent says, or that none is
    recorded yet); the other outcomes say that nothing was placed.
    """
    if outcome not in _LIVE_CONFIRM_OUTCOMES:
        raise ValueError(f"unknown confirm outcome {outcome!r}")
    head = _live_confirm_head(mode_label=mode_label, symbol=symbol, side=side, money=money)
    when = format_utc(at_utc)
    lines: list[str]
    if outcome in ("CONFIRMED", "CANCELLED"):
        if user_id is None or user_id == "":
            raise ValueError(f"{outcome} needs the user id")
        who = f"user {_one_line(str(user_id), 'user_id')}"
        if outcome == "CONFIRMED":
            if not placement_lines:
                raise ValueError("a CONFIRMED text needs its placement lines")
            lines = [f"CONFIRMED by {who} at {when}", *placement_lines]
        else:
            lines = [f"CANCELLED by {who} at {when}; nothing was placed"]
    else:
        code = _one_line(reason or "", "reason")
        if outcome == "EXPIRED":
            lines = [f"EXPIRED at {when}: no confirmation was taken ({code}); nothing was placed"]
        else:
            lines = [f"REFUSED at {when}: {code}; nothing was placed"]
    if outcome != "CONFIRMED" and placement_lines:
        raise ValueError("only a CONFIRMED text carries placement lines")
    return "\n".join([*head, *lines])


__all__ = [
    "APR_PREFIX",
    "CNF_PREFIX",
    "CXL_PREFIX",
    "SKP_PREFIX",
    "SIM_PREFIX",
    "SKIP_PREFIX",
    "TELEGRAM_CALLBACK_DATA_MAX_BYTES",
    "REQUEST_MODE_LABELS",
    "LiveConfirmOutcome",
    "TelegramBot",
    "TelegramFailure",
    "TelegramFailureKind",
    "TelegramSendError",
    "TelegramTextBot",
    "build_approve_keyboard",
    "build_confirm_keyboard",
    "build_decision_keyboard",
    "build_shadow_decision_keyboard",
    "build_simulate_keyboard",
    "build_skip_keyboard",
    "classify_telegram_error",
    "edit_text",
    "edit_to_confirm_card",
    "format_approval_request",
    "format_approve",
    "format_live_confirm_card",
    "format_live_confirm_final",
    "format_utc",
    "send_simulate",
    "render_money_block",
    "require_money_consistent",
    "send_text",
]
