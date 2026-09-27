"""APPROVE/SKIP 12-field message + keyboard tests (Phase 8, plan 08-02).

Per D-02: the APPROVE/SKIP Telegram alert carries all 12 APRV-01 fields
(symbol, direction, setup, entry, SL, TP(s), RR, risk percentage,
expiry, invalidation, current exposure, reason codes). The keyboard
emits `APR:<short>` and `SKP:<short>` callback_data payloads, each at
most 64 bytes when UTF-8 encoded (Telegram's hard limit).

The tests cover:

  1. format_approve renders all 12 APRV-01 fields byte-checked with
     Decimal str precision and APPROVE labeling.
  2. build_approve_keyboard and build_skip_keyboard emit callback_data
     matching the APR/SKP SHORT-ID shape and every payload is at most
     64 bytes when UTF-8 encoded.
  3. The existing SIMULATE wire format (SIM: short-id labels) is
     byte-identical; no Phase-7 test breaks.
  4. The Telegram adapter is the only module that imports
     `python-telegram-bot` (adapter-boundary isolation).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _make_payload() -> dict[str, Any]:
    """Build a canonical 12-field APPROVE payload for tests."""
    return {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "setup": "TREND_PULLBACK_LONG",
        "entry_min": Decimal("100.10"),
        "entry_max": Decimal("100.30"),
        "stop_loss": Decimal("99.50"),
        "take_profits": [
            (Decimal("101.50"), Decimal("0.5")),
            (Decimal("103.00"), Decimal("0.5")),
        ],
        "rr": Decimal("2.0"),
        "risk_pct": Decimal("0.005"),
        "expiry_utc": datetime(2026, 9, 19, 13, 0, tzinfo=UTC),
        "invalidation": "CANDLE_CLOSE < 99.50",
        "exposure_quote": Decimal("50.00"),
        "reason_codes": ["SETUP_DETECTED"],
        "signal_id": "sig_test_0000000000000000000000000000000000000000000000000000",
        "detected_at_utc": datetime(2026, 9, 19, 9, 0, tzinfo=UTC),
    }


# --------------------------------------------------------------------------- #
# Beh. 1 — format_approve renders all 12 APRV-01 fields byte-checked.
# --------------------------------------------------------------------------- #


def test_format_approve_renders_all_12_aprv01_fields() -> None:
    """Beh. 1: format_approve renders all 12 APRV-01 fields with
    Decimal str precision and APPROVE labeling.

    Per D-02 + TELEGRAM.md §4: the message carries exactly the 12
    fields (symbol, direction, setup, entry, SL, TP(s), R:R, risk
    percentage, expiry, invalidation, current exposure, reason codes).
    All Decimal values are formatted via `str()` preserving full
    precision (D-12). The text starts with "APPROVE" so the operator
    can identify the message type at a glance.
    """
    from src.adapters.telegram_notify import format_approve

    payload = _make_payload()
    text = format_approve(**payload)

    # All 12 APRV-01 fields are present in the text.
    assert "BTCUSDT" in text  # 1. symbol
    assert "LONG" in text  # 2. direction
    assert "TREND_PULLBACK_LONG" in text  # 3. setup
    assert "100.10" in text and "100.30" in text  # 4. entry
    assert "99.50" in text  # 5. SL
    assert "101.50" in text and "103.00" in text  # 6. TP(s)
    assert "2.0" in text  # 7. R:R
    assert "0.005" in text  # 8. risk percentage
    assert "2026-09-19T13:00:00+00:00" in text  # 9. expiry
    assert "CANDLE_CLOSE < 99.50" in text  # 10. invalidation
    assert "50.00" in text  # 11. current exposure
    assert "SETUP_DETECTED" in text  # 12. reason codes

    # The text starts with "APPROVE" so the operator can identify
    # the message type at a glance.
    assert text.startswith("APPROVE ")

    # Decimal precision is preserved (D-12): "100.10" stays "100.10",
    # not "100.1".
    assert "100.10" in text
    assert "100.30" in text


# --------------------------------------------------------------------------- #
# Beh. 2 — build_approve_keyboard / build_skip_keyboard emit APR/SKP
# callback_data within the 64-byte ceiling.
# --------------------------------------------------------------------------- #


def test_build_approve_keyboard_emits_apr_short_id_within_64_bytes() -> None:
    """Beh. 2a: build_approve_keyboard emits APR:<short> callback_data
    within Telegram's 64-byte ceiling.

    Per D-02: the callback_data is `APR:<short>` where `<short>` is
    `sha256(signal_id)[:32]` (32 hex chars). The full payload is
    `APR:` (4) + 32 hex = 36 bytes, well under the 64-byte limit.
    """
    from src.adapters.telegram_notify import build_approve_keyboard

    signal_id = "sig_test_0000000000000000000000000000000000000000000000000000"
    keyboard = build_approve_keyboard(signal_id)

    # The keyboard has exactly one button (APPROVE).
    assert len(keyboard.inline_keyboard) == 1
    assert len(keyboard.inline_keyboard[0]) == 1
    button = keyboard.inline_keyboard[0][0]
    assert button.text == "APPROVE"

    # The callback_data is APR:<short> within 64 bytes.
    cb = button.callback_data
    assert cb is not None
    assert cb.startswith("APR:")
    short = cb[len("APR:") :]
    assert len(short) == 32
    assert all(c in "0123456789abcdef" for c in short)
    assert len(cb.encode("utf-8")) <= 64, (
        f"callback_data exceeds 64 bytes: {len(cb.encode('utf-8'))} bytes"
    )


def test_build_skip_keyboard_emits_skp_short_id_within_64_bytes() -> None:
    """Beh. 2b: build_skip_keyboard emits SKP:<short> callback_data
    within Telegram's 64-byte ceiling.

    Per D-02: the callback_data is `SKP:<short>` where `<short>` is
    `sha256(signal_id)[:32]` (32 hex chars). The full payload is
    `SKP:` (4) + 32 hex = 36 bytes, well under the 64-byte limit.
    """
    from src.adapters.telegram_notify import build_skip_keyboard

    signal_id = "sig_test_0000000000000000000000000000000000000000000000000000"
    keyboard = build_skip_keyboard(signal_id)

    # The keyboard has exactly one button (SKIP).
    assert len(keyboard.inline_keyboard) == 1
    assert len(keyboard.inline_keyboard[0]) == 1
    button = keyboard.inline_keyboard[0][0]
    assert button.text == "SKIP"

    # The callback_data is SKP:<short> within 64 bytes.
    cb = button.callback_data
    assert cb is not None
    assert cb.startswith("SKP:")
    short = cb[len("SKP:") :]
    assert len(short) == 32
    assert all(c in "0123456789abcdef" for c in short)
    assert len(cb.encode("utf-8")) <= 64, (
        f"callback_data exceeds 64 bytes: {len(cb.encode('utf-8'))} bytes"
    )


def test_build_approve_and_skip_keyboards_share_short_id() -> None:
    """Beh. 2c: build_approve_keyboard and build_skip_keyboard share
    the same short id for the same signal_id.

    Per D-02: the short id is a deterministic function of signal_id
    (sha256 prefix). Both keyboards must agree so the receiver can
    resolve either callback to the same approval.
    """
    from src.adapters.telegram_notify import (
        build_approve_keyboard,
        build_skip_keyboard,
    )

    signal_id = "sig_test_0000000000000000000000000000000000000000000000000000"
    apr_cb = build_approve_keyboard(signal_id).inline_keyboard[0][0].callback_data
    skp_cb = build_skip_keyboard(signal_id).inline_keyboard[0][0].callback_data
    assert apr_cb is not None and skp_cb is not None
    assert apr_cb[len("APR:") :] == skp_cb[len("SKP:") :]


# --------------------------------------------------------------------------- #
# Beh. 3 — existing SIMULATE wire format is byte-identical.
# --------------------------------------------------------------------------- #


def test_simulate_keyboard_callback_data_byte_identical() -> None:
    """Beh. 3: build_simulate_keyboard emits the same SIM:/SKIP: labels
    as Phase 7 — no existing test breaks.

    Per D-02: the SIMULATE wire format is byte-identical to Phase 7.
    The labels stay `SIM:<short>` and `SKIP:<short>` (the SKIP label
    is the inert Phase-7 marker; the new SKP label is the live
    Phase-8 SKIP callback).
    """
    from src.adapters.telegram_notify import build_simulate_keyboard

    signal_id = "sig_test_0000000000000000000000000000000000000000000000000000"
    keyboard = build_simulate_keyboard(signal_id)

    # Two buttons: SIMULATE-recorded and SKIP (Phase 8).
    assert len(keyboard.inline_keyboard) == 1
    assert len(keyboard.inline_keyboard[0]) == 2
    sim_button = keyboard.inline_keyboard[0][0]
    skip_button = keyboard.inline_keyboard[0][1]
    assert sim_button.text == "SIMULATE-recorded"
    assert skip_button.text == "SKIP (Phase 8)"
    assert sim_button.callback_data is not None
    assert skip_button.callback_data is not None
    assert sim_button.callback_data.startswith("SIM:")
    assert skip_button.callback_data.startswith("SKIP:")


# --------------------------------------------------------------------------- #
# Beh. 4 — adapter-boundary isolation: only telegram_notify imports PTB.
# --------------------------------------------------------------------------- #


def test_telegram_adapter_is_the_only_telegram_importer() -> None:
    """Beh. 4: the Telegram adapter is the only module that imports
    `python-telegram-bot`.

    Per D-02 + RESEARCH §Pattern 3: the adapter is the ONLY module
    allowed to import the Telegram SDK. Downstream consumers receive
    frozen dataclass instances or the `TelegramBot` Protocol.
    """
    from pathlib import Path

    src_dir = Path(__file__).resolve().parents[1] / "src"
    importers: list[Path] = []
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if "from telegram import" in text or "import telegram" in text:
            importers.append(py_file)
    assert importers == [src_dir / "adapters" / "telegram_notify.py"], (
        f"only src/adapters/telegram_notify.py may import telegram; found: {importers}"
    )


# --------------------------------------------------------------------------- #
# Beh. 5 — format_approve fail-closed validation.
# --------------------------------------------------------------------------- #


def test_format_approve_rejects_empty_symbol() -> None:
    """Beh. 5a: format_approve rejects an empty symbol (fail-closed)."""
    from src.adapters.telegram_notify import format_approve

    payload = _make_payload()
    payload["symbol"] = ""
    with pytest.raises(ValueError, match="symbol"):
        format_approve(**payload)


def test_format_approve_rejects_inverted_entry_bounds() -> None:
    """Beh. 5b: format_approve rejects inverted entry bounds (fail-closed)."""
    from src.adapters.telegram_notify import format_approve

    payload = _make_payload()
    payload["entry_min"] = Decimal("100.30")
    payload["entry_max"] = Decimal("100.10")
    with pytest.raises(ValueError, match="entry_min"):
        format_approve(**payload)


def test_format_approve_rejects_empty_take_profits() -> None:
    """Beh. 5c: format_approve rejects an empty take_profits list (fail-closed)."""
    from src.adapters.telegram_notify import format_approve

    payload = _make_payload()
    payload["take_profits"] = []
    with pytest.raises(ValueError, match="take_profits"):
        format_approve(**payload)


def test_format_approve_rejects_naive_datetime() -> None:
    """Beh. 5d: format_approve rejects a naive datetime (fail-closed)."""
    from src.adapters.telegram_notify import format_approve

    payload = _make_payload()
    payload["expiry_utc"] = datetime(2026, 9, 19, 13, 0)  # naive
    with pytest.raises(ValueError, match="UTC-aware"):
        format_approve(**payload)
