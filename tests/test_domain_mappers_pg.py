"""Live-PostgreSQL mapper enforcement tests (Phase 3 WR-11, rebuilt in Phase 17-01).

Covers the PG-vs-SQLite gaps the SQLite suite cannot exercise: VARCHAR length
enforcement, TIMESTAMPTZ round-trip, duplicate-PK and fills `(order_id,
exchange_trade_id)` unique-constraint races, and NUMERIC(38,18) overflow.

Every test runs on a generated, alembic-built `t17_<hex>_test` database (the
`pg_db` fixture owns skip-or-fail; nothing here builds or drops a schema). Parent
rows are inserted before children (Signal -> TradePlan -> Order -> Fill) with
GLOSSARY-valid values, so the tests stay valid once plan 02 adds foreign keys and
enum CHECK constraints.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session
from src.db.mappers import signal_from_row, signal_to_row
from src.db.models import FillRow, OrderRow, SignalRow, TradePlanRow
from src.domain.enums import SignalStatus
from src.domain.signal import Signal
from src.persistence.engine import make_sync_engine

SIGNAL_ID = "a" * 64
PLAN_ID = "c" * 64
ORDER_ID = "1" * 64


@pytest.fixture
def pg_session(pg_db: str) -> Iterator[Session]:
    """A Session on a fresh alembic-built disposable database."""
    engine = make_sync_engine(pg_db)
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def _sample_signal() -> Signal:
    return Signal(
        signal_id=SIGNAL_ID,
        strategy_id="trend-pullback",
        strategy_version="v1.0.0",
        parameter_set_id="baseline-v1",
        parameter_set_hash="b" * 64,
        symbol="BTCUSDT",
        direction="LONG",
        setup_type="TREND_PULLBACK_LONG",
        source_timeframe="1h",
        source_candle_close_utc=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
        detected_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        status=SignalStatus.DETECTED,
        expires_at_utc=datetime(2026, 9, 19, 16, 0, tzinfo=UTC),
        invalidated_at_utc=None,
    )


def _plan_row(**overrides: object) -> TradePlanRow:
    values: dict[str, object] = {
        "trade_plan_id": PLAN_ID,
        "signal_id": SIGNAL_ID,
        "trade_plan_version": "v1.0.0",
        "entry_model": "LIMIT_ZONE",
        "entry_min_price": Decimal("50000"),
        "entry_max_price": Decimal("50100"),
        "stop_loss_price": Decimal("49500"),
        "take_profit_json": "[]",
        "invalidation_rule_json": "{}",
        "expiry_utc": datetime(2026, 9, 19, 16, 0, tzinfo=UTC),
        "expected_rr_json": "{}",
        "risk_rate": Decimal("0.005"),
        "risk_budget": Decimal("4"),
        "suggested_quantity": Decimal("0.08"),
        "quantity_before_rounding": Decimal("0.08"),
        "quantity_after_rounding": Decimal("0.08"),
        "quantization_decision": "ACCEPTED",
        "plan_hash": "d" * 64,
        "status": "READY",
        "created_at_utc": datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
    }
    values.update(overrides)
    return TradePlanRow(**values)


def _order_row() -> OrderRow:
    return OrderRow(
        order_id=ORDER_ID,
        trade_plan_id=PLAN_ID,
        position_id=None,
        parent_order_id=None,
        order_role="ENTRY",
        exchange="BINANCE_USDM",
        symbol="BTCUSDT",
        side="BUY",
        position_side="BOTH",
        order_type="LIMIT",
        time_in_force="GTC",
        quantity=Decimal("0.08"),
        price=Decimal("50050"),
        stop_price=None,
        close_position=False,
        reduce_only=False,
        client_order_id="x-" + "d" * 32 + "EN",
        exchange_order_id=None,
        algo_client_id=None,
        exchange_status="NEW",
        local_status="NEW",
        submitted_at_utc=datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        updated_at_utc=datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        canceled_at_utc=None,
    )


def _insert_parent_chain(session: Session) -> None:
    """Signal -> TradePlan -> Order, flushed in dependency order and committed."""
    session.add(signal_to_row(_sample_signal()))
    session.flush()
    session.add(_plan_row())
    session.flush()
    session.add(_order_row())
    session.commit()


def _fill_kwargs() -> dict[str, object]:
    return {
        "fill_id": "2" * 64,
        "order_id": ORDER_ID,
        "exchange_trade_id": "trade-1",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "BOTH",
        "fill_price": Decimal("50050"),
        "fill_quantity": Decimal("0.08"),
        "quote_quantity": Decimal("4004"),
        "commission": Decimal("0.00008"),
        "commission_asset": "USDT",
        "realized_pnl": Decimal("0"),
        "fill_time_utc": datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        "is_maker": False,
    }


def test_tz_round_trip_preserves_utc(pg_session: Session) -> None:
    """Beh. 1: TIMESTAMPTZ round-trip keeps UTC offsets."""
    signal = _sample_signal()
    pg_session.add(signal_to_row(signal))
    pg_session.commit()
    pg_session.expire_all()
    row = pg_session.get(SignalRow, signal.signal_id)
    assert row is not None
    offset = row.source_candle_close_utc.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0
    assert signal_from_row(row) == signal


def test_status_length_enforced(pg_session: Session) -> None:
    """Beh. 2: an over-wide status into the VARCHAR status column raises on PG."""
    row = signal_to_row(_sample_signal())
    row.status = "X" * 40
    pg_session.add(row)
    with pytest.raises((DataError, IntegrityError)):
        pg_session.commit()


def test_duplicate_signal_pk_raises(pg_session: Session) -> None:
    """Beh. 3: duplicate signal_id raises IntegrityError."""
    pg_session.add(signal_to_row(_sample_signal()))
    pg_session.commit()
    pg_session.add(signal_to_row(_sample_signal()))
    with pytest.raises(IntegrityError):
        pg_session.commit()


def test_fills_order_trade_unique_pair_raises(pg_session: Session) -> None:
    """Beh. 4: duplicate (order_id, exchange_trade_id) raises."""
    _insert_parent_chain(pg_session)
    kwargs = _fill_kwargs()
    pg_session.add(FillRow(**kwargs))
    pg_session.commit()
    pg_session.add(FillRow(**{**kwargs, "fill_id": "3" * 64}))
    with pytest.raises(IntegrityError):
        pg_session.commit()


def test_numeric_38_18_overflow_raises(pg_session: Session) -> None:
    """Beh. 5: >20 integer digits into NUMERIC(38,18) raises on PG."""
    pg_session.add(signal_to_row(_sample_signal()))
    pg_session.commit()
    pg_session.add(_plan_row(entry_min_price=Decimal("1" + "0" * 25)))
    with pytest.raises((DataError, IntegrityError)):
        pg_session.commit()
