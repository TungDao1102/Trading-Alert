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
"""

from __future__ import annotations

import hashlib
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
    assert len(sim_data.encode("utf-8")) <= 64
    assert len(skip_data.encode("utf-8")) <= 64
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "SIMULATE-recorded", callback_data=sim_data
                ),
                InlineKeyboardButton(
                    "SKIP (Phase 8)", callback_data=skip_data
                ),
            ]
        ]
    )


__all__ = [
    "TelegramBot",
    "build_simulate_keyboard",
    "send_simulate",
]
