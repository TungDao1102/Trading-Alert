"""Live-PostgreSQL mapper enforcement tests (Phase 3, WR-11).

Gated on `TEST_DATABASE_URL`: the whole module skips without it.
Covers the PG-vs-SQLite gaps the SQLite suite cannot exercise:
VARCHAR length enforcement, TIMESTAMPTZ round-trip, duplicate-PK and
fills `(order_id, exchange_trade_id)` unique-constraint races, and
NUMERIC(38,18) overflow.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from src.db.mappers import signal_from_row, signal_to_row
from src.db.models import Base, FillRow, SignalRow
from src.domain.enums import SignalStatus
from src.domain.signal import Signal

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="live-PG mapper tests require TEST_DATABASE_URL",
)


@pytest.fixture
def pg_session() -> Iterator[Session]:
    """PostgreSQL session with a fresh seven-table schema."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _sample_signal() -> Signal:
    return Signal(
        signal_id="a" * 64,
        strategy_id="trend-pullback",
        strategy_version="v1.0.0",
        parameter_set_id="baseline-v1",
        parameter_set_hash="b" * 64,
        symbol="BTCUSDT",
        direction="LONG",
        setup_type="pullback",
        source_timeframe="1h",
        source_candle_close_utc=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
        detected_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        status=SignalStatus.DETECTED,
        expires_at_utc=datetime(2026, 9, 19, 16, 0, tzinfo=UTC),
        invalidated_at_utc=None,
    )


def test_tz_round_trip_preserves_utc(pg_session: Session) -> None:
    """Beh. 1: TIMESTAMPTZ round-trip keeps UTC offsets."""
    signal = _sample_signal()
    pg_session.add(signal_to_row(signal))
    pg_session.commit()
    row = pg_session.get(SignalRow, signal.signal_id)
    assert row is not None
    assert row.source_candle_close_utc.utcoffset() is not None
    assert row.source_candle_close_utc.utcoffset().total_seconds() == 0
    assert signal_from_row(row) == signal


def test_status_length_enforced(pg_session: Session) -> None:
    """Beh. 2: 20-char status into String(16) raises on PG."""
    row = signal_to_row(_sample_signal())
    row.status = "X" * 20
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
    kwargs = {
        "fill_id": "2" * 64,
        "order_id": "1" * 64,
        "exchange_trade_id": "trade-1",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "LONG",
        "fill_price": Decimal("50050"),
        "fill_quantity": Decimal("0.08"),
        "quote_quantity": Decimal("4004"),
        "commission": Decimal("0.00008"),
        "commission_asset": "USDT",
        "realized_pnl": Decimal("0"),
        "fill_time_utc": datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        "is_maker": False,
    }
    pg_session.add(FillRow(**kwargs))
    pg_session.commit()
    pg_session.add(FillRow(**{**kwargs, "fill_id": "3" * 64}))
    with pytest.raises(IntegrityError):
        pg_session.commit()


def test_numeric_38_18_overflow_raises(pg_session: Session) -> None:
    """Beh. 5: >20 integer digits into NUMERIC(38,18) raises on PG."""
    row = signal_to_row(_sample_signal())
    assert isinstance(row, SignalRow)
    pg_session.add(row)
    pg_session.commit()
    from src.db.models import TradePlanRow

    pg_session.add(
        TradePlanRow(
            trade_plan_id="c" * 64,
            signal_id="a" * 64,
            trade_plan_version="v1.0.0",
            entry_model="LIMIT_ZONE",
            entry_min_price=Decimal("1" + "0" * 25),
            entry_max_price=Decimal("50100"),
            stop_loss_price=Decimal("49500"),
            take_profit_json="[]",
            invalidation_rule_json="{}",
            expiry_utc=datetime(2026, 9, 19, 16, 0, tzinfo=UTC),
            expected_rr_json="{}",
            risk_rate=Decimal("0.005"),
            risk_budget=Decimal("4"),
            suggested_quantity=Decimal("0.08"),
            quantity_before_rounding=Decimal("0.08"),
            quantity_after_rounding=Decimal("0.08"),
            quantization_decision="ACCEPT",
            plan_hash="d" * 64,
            status="READY",
            created_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        )
    )
    with pytest.raises((DataError, IntegrityError)):
        pg_session.commit()
