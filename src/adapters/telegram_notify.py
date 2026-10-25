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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Literal, Protocol

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
    """
    skp_data = _short_signal_id_with_prefix(signal_id, SKP_PREFIX)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([[InlineKeyboardButton("SKIP", callback_data=skp_data)]])


def build_shadow_decision_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    """Build the SHADOW decision keyboard: one row, an APPROVE and a SKIP button.

    Button contract (Phase 16, plan 16-04, D-16, F-961): SHADOW alerts use the live `APR:` and
    `SKP:` prefixes ONLY. Both buttons carry the same short id (`sha256(signal_id)[:32]`), so one
    short-id mapping backs the pair, and both are backed by a PENDING approval row. The
    SIMULATE-only keyboard (`build_simulate_keyboard`, inert `SIM:`/`SKIP:` data that resolves to
    SIMULATE_RECORDED and never advances an approval) is never sent by SHADOW code; it stays in
    this module only for wire-format stability (Phase 7 D-05).

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
RETRY_AFTER_CAP_SECONDS: int = 30

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
    retry_after_cap_seconds: int = RETRY_AFTER_CAP_SECONDS,
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
    retry_after_cap_seconds: int = RETRY_AFTER_CAP_SECONDS,
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
    retry_after_cap_seconds: int = RETRY_AFTER_CAP_SECONDS,
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
    precision (D-12). Timestamps are UTC ISO with the
    `Asia/Ho_Chi_Minh` display-edge note.

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
    tp_lines = "\n".join(
        f"  TP{idx + 1}: {price} ({fraction})" for idx, (price, fraction) in enumerate(take_profits)
    )
    reasons = ", ".join(reason_codes) if reason_codes else "(none)"
    return (
        f"APPROVE {symbol} {direction} {setup}\n"
        f"Signal: {signal_id}\n"
        f"Detected: {detected_at_utc.astimezone(UTC).isoformat()}\n"
        f"Entry: {entry_min}–{entry_max}\n"
        f"Quantity: {format(approved_quantity, 'f')}\n"
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


__all__ = [
    "APR_PREFIX",
    "CNF_PREFIX",
    "CXL_PREFIX",
    "SKP_PREFIX",
    "SIM_PREFIX",
    "SKIP_PREFIX",
    "TELEGRAM_CALLBACK_DATA_MAX_BYTES",
    "TelegramBot",
    "TelegramFailure",
    "TelegramFailureKind",
    "TelegramSendError",
    "TelegramTextBot",
    "build_approve_keyboard",
    "build_confirm_keyboard",
    "build_shadow_decision_keyboard",
    "build_simulate_keyboard",
    "build_skip_keyboard",
    "classify_telegram_error",
    "edit_text",
    "edit_to_confirm_card",
    "format_approve",
    "send_simulate",
    "send_text",
]
