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

import dataclasses
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


class CapturingSession:
    """Wraps a SQLAlchemy session and records every `add()` call.

    SQLite stores NUMERIC as REAL (loses precision) and TIMESTAMP without
    tzinfo (drops the timezone). To assert on the values the metadata
    module ACTUALLY wrote — not the lossy SQLite roundtrip — we snapshot
    a deep copy of the SymbolMetadata instance at `add()` time (BEFORE
    the commit that triggers SQLAlchemy's post-flush refresh from the
    DB). Production uses PostgreSQL NUMERIC(38,18) + TIMESTAMPTZ which
    preserve both exactly.
    """

    def __init__(self, real: Session) -> None:
        self._real = real
        self.added: list[SymbolMetadata] = []

    def add(self, obj: object) -> None:
        if isinstance(obj, SymbolMetadata):
            # Snapshot via attribute copy (SymbolMetadata is a frozen
            # ORM instance; we cannot replace fields after construction,
            # so we build a sibling instance carrying the same field
            # values). This MUST run before the caller commits — post-
            # commit the object's attributes reflect the SQLite roundtrip.
            self.added.append(
                SymbolMetadata(
                    symbol=obj.symbol,
                    metadata_observed_at_utc=obj.metadata_observed_at_utc,
                    status=obj.status,
                    contract_type=obj.contract_type,
                    onboard_time_utc=obj.onboard_time_utc,
                    price_tick_size=obj.price_tick_size,
                    quantity_step_size=obj.quantity_step_size,
                    min_quantity=obj.min_quantity,
                    max_quantity=obj.max_quantity,
                    min_notional=obj.min_notional,
                    notional_constraints_json=obj.notional_constraints_json,
                    order_capabilities_json=obj.order_capabilities_json,
                    position_mode_snapshot_json=obj.position_mode_snapshot_json,
                    base_asset=obj.base_asset,
                    quote_asset=obj.quote_asset,
                    margin_asset=obj.margin_asset,
                )
            )
        return self._real.add(obj)

    def commit(self) -> None:
        return self._real.commit()

    def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self._real.execute(*args, **kwargs)

    def rollback(self) -> None:
        return self._real.rollback()

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


# --------------------------------------------------------------------------- #
# Test 1 — golden exchangeInfo inserts one new version row per live-5.
# --------------------------------------------------------------------------- #


def test_refresh_inserts_one_version_row_per_live5_symbol(session: Session) -> None:
    """Beh. 1: refreshing against the live-5 inserts exactly 5 version rows.

    Each row carries a Decimal tick/step (no float). The PK observed-at
    is the value passed to refresh_symbol_metadata (not now()).

    Note: we assert on the captured SymbolMetadata instances (NOT the
    SQLite roundtrip), because SQLite's REAL storage for NUMERIC drops
    precision. Production uses PostgreSQL NUMERIC(38,18) which preserves
    the Decimal exactly.
    """
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    filters = [_mk_filters(sym) for sym in LIVE_5]
    cap = CapturingSession(session)

    inserted = refresh_symbol_metadata(cap, filters, observed_at=observed)

    assert inserted == len(LIVE_5)
    assert len(cap.added) == len(LIVE_5)

    symbols_captured = {r.symbol for r in cap.added}
    assert symbols_captured == set(LIVE_5)

    for row in cap.added:
        assert row.metadata_observed_at_utc == observed
        assert isinstance(row.price_tick_size, Decimal)
        assert isinstance(row.quantity_step_size, Decimal)
        assert isinstance(row.min_quantity, Decimal)
        assert isinstance(row.min_notional, Decimal)

    # Sanity: rows are also persisted (count via real session).

    rows_persisted = (
        session.execute(select(SymbolMetadata).order_by(SymbolMetadata.symbol)).scalars().all()
    )
    assert len(rows_persisted) == len(LIVE_5)


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
    cap = CapturingSession(session)

    refresh_symbol_metadata(cap, filters, observed_at=observed_a)
    refresh_symbol_metadata(cap, filters, observed_at=observed_b)

    # Captured set: exactly two rows with the right observed_at values.
    assert len(cap.added) == 2
    observed_times = sorted(r.metadata_observed_at_utc for r in cap.added)
    assert observed_times == [observed_a, observed_b]
    # Values are equal (same filters) but row count doubled.
    assert cap.added[0].price_tick_size == cap.added[1].price_tick_size
    assert cap.added[0].quantity_step_size == cap.added[1].quantity_step_size


# --------------------------------------------------------------------------- #
# Test 3 — filter strings parse to Decimal exactly (no float roundoff).
# --------------------------------------------------------------------------- #


def test_filter_strings_parse_to_decimal_exactly(session: Session) -> None:
    """Beh. 3: values like 0.10 + 0.10 + 0.10 == 0.30 exactly, no float roundoff.

    In float arithmetic, 0.10 + 0.10 + 0.10 == 0.30000000000000004. If any
    intermediate in the parse path converted to float, the row's stored
    value would round off when summed. The Decimal path is exact.

    Note: we inspect the captured SymbolMetadata (BEFORE the SQLite
    roundtrip) — SQLite's REAL storage for NUMERIC drops precision.
    Production uses PostgreSQL NUMERIC(38,18) which is exact.
    """
    filters = [_mk_filters("BTCUSDT", tick="0.10", step="0.001")]
    cap = CapturingSession(session)

    refresh_symbol_metadata(cap, filters, observed_at=datetime(2026, 9, 19, tzinfo=UTC))

    assert len(cap.added) == 1
    row = cap.added[0]

    # Stored types must be Decimal — not float.
    assert isinstance(row.price_tick_size, Decimal)
    assert isinstance(row.quantity_step_size, Decimal)
    assert isinstance(row.min_quantity, Decimal)
    assert isinstance(row.min_notional, Decimal)

    # Decimal arithmetic is exact: 0.10 * 3 == 0.30.
    assert (row.price_tick_size + row.price_tick_size + row.price_tick_size) == Decimal("0.30")


def _find_float_calls(src: str) -> list[tuple[int, str]]:
    """AST-walk source and return `(line_no, line_text)` for every call to `float(...)`.

    Skips strings and comments (the AST doesn't see them at all).
    """
    import ast

    calls: list[tuple[int, str]] = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # Direct call: float(...)
            if isinstance(func, ast.Name) and func.id == "float":
                calls.append((node.lineno, src.splitlines()[node.lineno - 1].strip()))
    return calls


def test_no_float_call_in_metadata_or_adapter() -> None:
    """Static guard: the metadata path must not contain any explicit `float(...)` call.

    D-05 + ENGINEERING_PRINCIPLES: float is banned for exchange-sensitive
    values. The `ms / 1000` in adapter._ms_to_utc uses Python's `/`
    operator (which returns float implicitly) but no explicit `float(...)`
    call — that is the only allowed float-touching code, and only on
    timestamps (not on prices/quantities/notional).
    """
    repo_root = Path(__file__).resolve().parent.parent
    for rel in ("src/data/metadata.py", "src/adapters/binance_usdm.py"):
        path = repo_root / rel
        src = path.read_text(encoding="utf-8")
        offenders = _find_float_calls(src)
        assert not offenders, (
            f"{rel} must not contain any explicit `float(...)` call — "
            f"Decimal is the only allowed exchange-sensitive type. "
            f"Found: {offenders}"
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
    cap = CapturingSession(session)

    # With universe=LIVE_5, only the 3 matching rows are inserted.
    inserted = refresh_symbol_metadata(cap, all_filters, observed_at=observed, universe=LIVE_5)
    assert inserted == 3
    assert {r.symbol for r in cap.added} == {"BTCUSDT", "ETHUSDT", "BNBUSDT"}


# --------------------------------------------------------------------------- #
# Phase 13 (D-10, D-29): delisted / non-TRADING research symbols, width guard.
# --------------------------------------------------------------------------- #


def _variant(symbol: str, **overrides: object) -> SymbolFilters:
    return dataclasses.replace(_mk_filters(symbol), **overrides)  # type: ignore[arg-type]


def _research_filters() -> list[SymbolFilters]:
    return [
        _variant(
            "FTTUSDT",
            status="SETTLING",
            delivery_date_ms=1_668_398_400_000,
        ),
        _variant("NEWUSDT", status="PENDING_TRADING"),
        _variant("BTCUSDT"),
        # 17 characters: longer than symbol_metadata.contract_type (String(16)).
        _variant("XAUUSDT", contract_type="TRADIFI_PERPETUAL"),
    ]


def test_refresh_inserts_rows_for_settling_and_pending_symbols(session: Session) -> None:
    """D-10: delisted / non-TRADING universe symbols get versioned INSERT rows."""
    universe = {"FTTUSDT", "NEWUSDT", "BTCUSDT"}
    cap = CapturingSession(session)
    first = datetime(2026, 9, 30, 1, 0, tzinfo=UTC)
    second = datetime(2026, 9, 30, 1, 5, tzinfo=UTC)

    assert (
        refresh_symbol_metadata(cap, _research_filters(), observed_at=first, universe=universe) == 3
    )
    statuses = {r.symbol: r.status for r in cap.added}
    assert statuses == {
        "FTTUSDT": "SETTLING",
        "NEWUSDT": "PENDING_TRADING",
        "BTCUSDT": "TRADING",
    }

    assert (
        refresh_symbol_metadata(cap, _research_filters(), observed_at=second, universe=universe)
        == 3
    )
    rows = session.execute(select(SymbolMetadata)).scalars().all()
    assert len(rows) == 6  # three new versions, none of the first ones updated
    assert sorted({r.metadata_observed_at_utc.replace(tzinfo=UTC) for r in rows}) == [
        first,
        second,
    ]
    assert "XAUUSDT" not in {r.symbol for r in rows}


def test_tradifi_contract_type_filtered_by_universe(session: Session) -> None:
    """A 17-character contract type is harmless while its symbol is outside the universe."""
    cap = CapturingSession(session)

    inserted = refresh_symbol_metadata(
        cap,
        _research_filters(),
        observed_at=datetime(2026, 9, 30, tzinfo=UTC),
        universe={"BTCUSDT"},
    )

    assert inserted == 1
    assert {r.symbol for r in cap.added} == {"BTCUSDT"}


@pytest.mark.parametrize("field", ["contract_type", "status"])
def test_overlong_metadata_text_raises_not_truncates(session: Session, field: str) -> None:
    """A universe row wider than String(16) raises and nothing is committed (T-13-30)."""
    overlong = "TRADIFI_PERPETUAL"  # 17 characters
    assert len(overlong) > 16
    filters = [_variant("BTCUSDT"), _variant("XAUUSDT", **{field: overlong})]
    cap = CapturingSession(session)

    with pytest.raises(ValueError, match=rf"XAUUSDT.*{field}"):
        refresh_symbol_metadata(
            cap,
            filters,
            observed_at=datetime(2026, 9, 30, tzinfo=UTC),
            universe={"BTCUSDT", "XAUUSDT"},
        )

    assert cap.added == []
    assert session.execute(select(SymbolMetadata)).scalars().all() == []
