"""Tests for the versioned symbol metadata module (02-04 Task 1).

The 02-04 plan calls out four behaviors (02-04-PLAN §tasks[1].behavior):

  1. Golden exchangeInfo fixture inserts one new version row per live-5
     symbol with Decimal tick and step.
  2. Second refresh with identical filters still inserts a new observed-at
     version rather than updating.
  3. Filter strings parse to Decimal exactly with no float conversion
     anywhere on the path.
  4. Unknown symbol fields outside the live-5 are ignored without failing
     the refresh.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/data/metadata.py` is implemented.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.adapters.binance_usdm import SymbolFilters
from src.data.backfill import LIVE_5
from src.data.metadata import refresh_symbol_metadata
from src.db.models import Base, SymbolMetadata


# --------------------------------------------------------------------------- #
# Test scaffold.
# --------------------------------------------------------------------------- #


def _mk_filters(
    symbol: str,
    *,
    tick: str = "0.10",
    step: str = "0.001",
    min_notional: str = "50",
) -> SymbolFilters:
    """Build a SymbolFilters instance for tests.

    Defaults match the live-5 Binance USDⓈ-M perpetual contract shape:
    tick=0.10, step=0.001, min_notional=50 USDT.
    """
    base_asset = symbol[:-4] if symbol.endswith("USDT") else symbol
    return SymbolFilters(
        symbol=symbol,
        contract_type="PERPETUAL",
        status="TRADING",
        onboard_time_utc=datetime(2020, 1, 1, tzinfo=UTC),
        price_tick_size=Decimal(tick),
        quantity_step_size=Decimal(step),
        min_quantity=Decimal(step),
        max_quantity=Decimal("1000"),
        min_notional=Decimal(min_notional),
        base_asset=base_asset,
        quote_asset="USDT",
        margin_asset="USDT",
        notional_constraints_json='{"filterType":"MIN_NOTIONAL","notional":"50"}',
        order_capabilities_json='{"order_types":["LIMIT","MARKET"]}',
        position_mode_snapshot_json='{"pricePrecision":2,"quantityPrecision":3}',
    )


@pytest.fixture
def session() -> Iterator[Session]:
    """In-memory SQLite session with the four-table schema applied.

    SQLite is fine for these tests because we only exercise the
    SQLAlchemy ORM mapping (Numeric → Decimal, TIMESTAMPTZ → datetime);
    no PostgreSQL-specific features (JSONB, partial indexes) are used.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


# --------------------------------------------------------------------------- #
# Test 1 — golden exchangeInfo inserts one new version row per live-5.
# --------------------------------------------------------------------------- #


def test_refresh_inserts_one_version_row_per_live5_symbol(session: Session) -> None:
    """Beh. 1: refreshing against the live-5 inserts exactly 5 version rows.

    Each row carries a Decimal tick/step (no float). The PK observed-at
    is the value passed to refresh_symbol_metadata (not now()).
    """
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    filters = [_mk_filters(sym) for sym in LIVE_5]

    inserted = refresh_symbol_metadata(session, filters, observed_at=observed)

    assert inserted == len(LIVE_5)

    rows = session.execute(
        select(SymbolMetadata).order_by(SymbolMetadata.symbol)
    ).scalars().all()
    assert len(rows) == len(LIVE_5)

    symbols_in_db = {r.symbol for r in rows}
    assert symbols_in_db == set(LIVE_5)

    for row in rows:
        assert row.metadata_observed_at_utc == observed
        assert isinstance(row.price_tick_size, Decimal)
        assert isinstance(row.quantity_step_size, Decimal)
        assert isinstance(row.min_quantity, Decimal)
        assert isinstance(row.min_notional, Decimal)


# --------------------------------------------------------------------------- #
# Test 2 — second refresh inserts a new version, never UPDATE.
# --------------------------------------------------------------------------- #


def test_second_refresh_inserts_new_observed_at_version(session: Session) -> None:
    """Beh. 2: even with identical filter values, each refresh inserts a new row.

    PK = (symbol, metadata_observed_at_utc), so two refreshes at different
    times produce two rows per symbol — versioned history, never UPDATE.
    """
    observed_a = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    observed_b = datetime(2026, 9, 19, 12, 5, tzinfo=UTC)
    filters = [_mk_filters("BTCUSDT")]

    refresh_symbol_metadata(session, filters, observed_at=observed_a)
    refresh_symbol_metadata(session, filters, observed_at=observed_b)

    rows = session.execute(
        select(SymbolMetadata)
        .where(SymbolMetadata.symbol == "BTCUSDT")
        .order_by(SymbolMetadata.metadata_observed_at_utc)
    ).scalars().all()

    assert len(rows) == 2
    assert rows[0].metadata_observed_at_utc == observed_a
    assert rows[1].metadata_observed_at_utc == observed_b
    # Values are equal (same filters) but row count doubled.
    assert rows[0].price_tick_size == rows[1].price_tick_size
    assert rows[0].quantity_step_size == rows[1].quantity_step_size


# --------------------------------------------------------------------------- #
# Test 3 — filter strings parse to Decimal exactly (no float roundoff).
# --------------------------------------------------------------------------- #


def test_filter_strings_parse_to_decimal_exactly(session: Session) -> None:
    """Beh. 3: values like 0.10 + 0.10 + 0.10 == 0.30 exactly, no float roundoff.

    In float arithmetic, 0.10 + 0.10 + 0.10 == 0.30000000000000004. If any
    intermediate in the parse path converted to float, the row's stored
    value would round off when summed. The Decimal path is exact.
    """
    filters = [_mk_filters("BTCUSDT", tick="0.10", step="0.001")]
    refresh_symbol_metadata(
        session, filters, observed_at=datetime(2026, 9, 19, tzinfo=UTC)
    )

    row = session.execute(
        select(SymbolMetadata).where(SymbolMetadata.symbol == "BTCUSDT")
    ).scalar_one()

    # Stored types must be Decimal — not float.
    assert isinstance(row.price_tick_size, Decimal)
    assert isinstance(row.quantity_step_size, Decimal)
    assert isinstance(row.min_quantity, Decimal)
    assert isinstance(row.min_notional, Decimal)

    # Decimal arithmetic is exact: 0.10 * 3 == 0.30.
    assert (row.price_tick_size + row.price_tick_size + row.price_tick_size) == Decimal(
        "0.30"
    )


def test_no_float_call_in_metadata_or_adapter() -> None:
    """Static guard: the metadata path must not contain explicit `float(` calls.

    D-05 + ENGINEERING_PRINCIPLES: float is banned for exchange-sensitive
    values. The `ms / 1000` in adapter._ms_to_utc uses Python's `/`
    operator (which returns float) but no explicit `float(...)` call —
    that is the only allowed float-touching code, and only on timestamps
    (not on prices/quantities/notional).
    """
    repo_root = Path(__file__).resolve().parent.parent
    for rel in ("src/data/metadata.py", "src/adapters/binance_usdm.py"):
        path = repo_root / rel
        src = path.read_text(encoding="utf-8")
        assert "float(" not in src, (
            f"{rel} must not contain an explicit `float(...)` call — "
            f"Decimal is the only allowed exchange-sensitive type"
        )


# --------------------------------------------------------------------------- #
# Test 4 — unknown symbols outside the live-5 are ignored.
# --------------------------------------------------------------------------- #


def test_unknown_symbols_outside_live5_are_ignored(session: Session) -> None:
    """Beh. 4: when a universe filter is supplied, only matching symbols are inserted.

    The function does NOT raise when given extra symbols; the universe
    parameter trims them out cleanly. Without `universe=`, the function
    inserts whatever it gets (the caller decides the universe).
    """
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

    # Mix of live-5 + non-live-5 — same SymbolFilters shape, no failure.
    all_filters = [
        _mk_filters("BTCUSDT"),
        _mk_filters("ETHUSDT"),
        _mk_filters("DOGEUSDT"),  # not in LIVE_5
        _mk_filters("SHIBUSDT"),  # not in LIVE_5
        _mk_filters("BNBUSDT"),
    ]

    # With universe=LIVE_5, only the 3 matching rows are inserted.
    inserted = refresh_symbol_metadata(
        session, all_filters, observed_at=observed, universe=LIVE_5
    )
    assert inserted == 3

    rows = session.execute(select(SymbolMetadata)).scalars().all()
    assert {r.symbol for r in rows} == {"BTCUSDT", "ETHUSDT", "BNBUSDT"}
