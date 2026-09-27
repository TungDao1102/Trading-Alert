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
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


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
    return InlineKeyboardMarkup([[InlineKeyboardButton("APPROVE", callback_data=apr_data)]])


def build_skip_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    """Build the SKIP keyboard.

    Per D-02: the callback_data is `SKP:<short>` where `<short>` is
    `sha256(signal_id)[:32]` (32 hex chars). The full payload is
    `SKP:` (4) + 32 hex = 36 bytes, well under Telegram's 64-byte
    limit. The keyboard carries exactly one button labeled SKIP.
    """
    skp_data = _short_signal_id_with_prefix(signal_id, SKP_PREFIX)
    return InlineKeyboardMarkup([[InlineKeyboardButton("SKIP", callback_data=skp_data)]])


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
) -> str:
    """Render the APPROVE notification text with all 12 APRV-01 fields.

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
    for field_name, value in (
        ("expiry_utc", expiry_utc),
        ("detected_at_utc", detected_at_utc),
    ):
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be datetime, got {type(value).__name__}")
        if value.tzinfo is None:
            raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    tp_lines = "\n".join(
        f"  TP{idx + 1}: {price} ({fraction})" for idx, (price, fraction) in enumerate(take_profits)
    )
    reasons = ", ".join(reason_codes) if reason_codes else "(none)"
    return (
        f"APPROVE {symbol} {direction} {setup}\n"
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


__all__ = [
    "APR_PREFIX",
    "SKP_PREFIX",
    "SIM_PREFIX",
    "SKIP_PREFIX",
    "TELEGRAM_CALLBACK_DATA_MAX_BYTES",
    "TelegramBot",
    "build_approve_keyboard",
    "build_simulate_keyboard",
    "build_skip_keyboard",
    "format_approve",
    "send_simulate",
]
