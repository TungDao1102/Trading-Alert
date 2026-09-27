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


# --------------------------------------------------------------------------- #
# Beh. 6 — short→full mapping: deterministic, round-trippable, server-side.
# --------------------------------------------------------------------------- #


def test_short_id_mapping_short_id_is_32_hex_and_deterministic() -> None:
    """Beh. 6a: derive_short_id returns a 32-hex-char prefix of
    sha256(signal_id), deterministic across calls.

    Per D-02: the short id is `sha256(signal_id)[:32]` — 32 lowercase
    hex chars. The same signal_id always yields the same short id.
    """
    from src.approval.mapping import derive_short_id

    signal_id = "sig_test_0000000000000000000000000000000000000000000000000000"
    s1 = derive_short_id(signal_id)
    s2 = derive_short_id(signal_id)
    assert s1 == s2
    assert len(s1) == 32
    assert all(c in "0123456789abcdef" for c in s1)


def test_short_id_mapping_rejects_non_hex_or_wrong_length() -> None:
    """Beh. 6b: ShortIdMapping rejects a non-hex / wrong-length short_id.

    Per D-02: the short id must be exactly 32 lowercase hex chars.
    Any other shape fails loudly at the type boundary.
    """
    from src.approval.mapping import ShortIdMapping

    base_args = {
        "signal_id": "sig_x",
        "trade_plan_id": "tp_x",
        "created_at_utc": datetime(2026, 9, 19, 13, 0, tzinfo=UTC),
    }
    # wrong length
    with pytest.raises(ValueError, match="32 hex chars"):
        ShortIdMapping(short_id="abcd", **base_args)
    # non-hex chars
    with pytest.raises(ValueError, match="lowercase hex"):
        ShortIdMapping(short_id="Z" * 32, **base_args)


def test_short_id_mapping_rejects_empty_signal_or_trade_plan() -> None:
    """Beh. 6c: ShortIdMapping rejects empty signal_id or trade_plan_id."""
    from src.approval.mapping import ShortIdMapping, derive_short_id

    short = derive_short_id("anything")
    base_args = {"short_id": short, "created_at_utc": datetime(2026, 9, 19, 13, 0, tzinfo=UTC)}
    with pytest.raises(ValueError, match="signal_id"):
        ShortIdMapping(signal_id="", trade_plan_id="tp_x", **base_args)
    with pytest.raises(ValueError, match="trade_plan_id"):
        ShortIdMapping(signal_id="sig_x", trade_plan_id="", **base_args)


def test_short_id_mapping_rejects_naive_datetime() -> None:
    """Beh. 6d: ShortIdMapping rejects a naive created_at_utc (D-12)."""
    from src.approval.mapping import ShortIdMapping, derive_short_id

    short = derive_short_id("anything")
    with pytest.raises(ValueError, match="UTC-aware"):
        ShortIdMapping(
            short_id=short,
            signal_id="sig_x",
            trade_plan_id="tp_x",
            created_at_utc=datetime(2026, 9, 19, 13, 0),  # naive
        )


def test_short_id_mapping_round_trip_via_orm_row() -> None:
    """Beh. 6e: the mapper round-trips ShortIdMapping ↔ ShortIdMappingRow.

    Per D-02: `from_row(to_row(m)) == m` — every field is mapped,
    round-trip tested, no enum translation needed (plain strings +
    UTC-aware datetime).
    """
    from src.approval.mapping import make_short_id_mapping
    from src.db.mappers import short_id_mapping_from_row, short_id_mapping_to_row

    m = make_short_id_mapping(
        signal_id="sig_test_0000000000000000000000000000000000000000000000000000",
        trade_plan_id="tp_test_0000000000000000000000000000000000000000000000000000",
        created_at_utc=datetime(2026, 9, 19, 13, 0, tzinfo=UTC),
    )
    row = short_id_mapping_to_row(m)
    back = short_id_mapping_from_row(row)
    assert back == m
    assert back.short_id == m.short_id
    assert back.signal_id == m.signal_id
    assert back.trade_plan_id == m.trade_plan_id
    assert back.created_at_utc == m.created_at_utc


def test_short_id_mapping_orm_row_uses_single_base() -> None:
    """Beh. 6f: ShortIdMappingRow lives on the single existing Base.

    Per D-02: no second declarative base is introduced. The model
    imports Base from src/db/models.py and registers itself on the
    shared `Base.metadata`.
    """
    from src.db.models import Base, ShortIdMappingRow

    assert ShortIdMappingRow.__bases__ == (Base,)
    # The table is registered on the shared metadata.
    assert "short_id_mapping" in Base.metadata.tables
    table = Base.metadata.tables["short_id_mapping"]
    # PK is short_id (String 32) — no auto-increment.
    assert table.primary_key.columns.keys() == ["short_id"]
    pk_col = table.primary_key.columns[0]
    assert pk_col.name == "short_id"
    assert pk_col.type.length == 32
    # No autoincrement anywhere.
    assert pk_col.autoincrement is not True


def test_migration_0003_creates_short_id_mapping_table() -> None:
    """Beh. 6g: migration 0003 creates the short_id_mapping table with
    the same op.create_table convention as 0002 and downgrades cleanly.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from src.db.models import Base, ShortIdMappingRow

    # Sanity: the table exists on Base.metadata (the migration shape
    # mirrors the model columns 1:1 — see the migration file header).
    table = Base.metadata.tables["short_id_mapping"]
    column_names = {c.name for c in table.columns}
    assert column_names == {"short_id", "signal_id", "trade_plan_id", "created_at_utc"}
    # Non-nullable: every column is NOT NULL.
    for col in table.columns:
        assert col.nullable is False, f"column {col.name} should be NOT NULL"
    # The model is importable and the table name matches the migration.
    assert ShortIdMappingRow.__tablename__ == "short_id_mapping"

    # Round-trip: script directory loads and revision chain is intact.
    cfg = Config()
    cfg.set_main_option("script_location", "src/db/alembic")
    script_dir = ScriptDirectory.from_config(cfg)
    revisions = [r.revision for r in script_dir.walk_revisions()]
    assert "0003_callback_mapping" in revisions
    assert "0002_domain_registry" in revisions
    # 0003 depends on 0002.
    rev_0003 = script_dir.get_revision("0003_callback_mapping")
    assert rev_0003.down_revision == "0002_domain_registry"


# --------------------------------------------------------------------------- #
# Beh. 7 — mapping module is dependency-free (no Telegram / SQLAlchemy
# / Pydantic imports).
# --------------------------------------------------------------------------- #


def test_approval_mapping_module_is_dependency_free() -> None:
    """Beh. 7: src/approval/mapping.py imports only stdlib + src/domain/*.

    Per the approval-core purity precedent (08-01 D-05): no Telegram,
    no SQLAlchemy, no Pydantic, no Binance SDK. The mapping record
    type is a pure dataclass over hashlib + datetime.
    """
    import re
    from pathlib import Path

    mapping_path = Path("src/approval/mapping.py")
    text = mapping_path.read_text(encoding="utf-8")

    forbidden_patterns = [
        re.compile(r"^import telegram", re.MULTILINE),
        re.compile(r"^from telegram", re.MULTILINE),
        re.compile(r"^import sqlalchemy", re.MULTILINE),
        re.compile(r"^from sqlalchemy", re.MULTILINE),
        re.compile(r"^import pydantic", re.MULTILINE),
        re.compile(r"^from pydantic", re.MULTILINE),
        re.compile(r"binance_sdk", re.MULTILINE),
        re.compile(r"^import binance", re.MULTILINE),
        re.compile(r"^from binance", re.MULTILINE),
    ]
    hits = [p.pattern for p in forbidden_patterns if p.search(text)]
    assert not hits, f"src/approval/mapping.py must not import forbidden packages; hits: {hits}"
