"""Mapper round-trip tests for all seven domain entities (Phase 3, plan 03-04).

Per D-02: PostgreSQL tables mirror the domain 1:1 via a separate ORM
layer. Thin mapper functions translate domain ↔ row; no ORM class IS
the domain model.

These tests verify:
  1. `from_row(to_row(x)) == x` for all seven entities (round-trip).
  2. Captured-snapshot precision assertions pass before SQLite roundtrip
     (SQLite stores NUMERIC as REAL — loses precision; production uses
     PostgreSQL NUMERIC(38,18) which is exact).
  3. Unknown status strings on restore raise ValueError (D-10).
  4. Nullable never-happened timestamps round-trip as None.

PG-vs-SQLite boundary: SQLite is fine for these tests because we only
exercise the SQLAlchemy ORM mapping (Numeric → Decimal, TIMESTAMPTZ →
datetime); no PostgreSQL-specific features (JSONB, partial indexes) are
used. The CapturingSession pattern snapshots the ORM instance BEFORE
the SQLite roundtrip so NUMERIC lossiness cannot hide mapper errors.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from src.db.mappers import (
    approval_from_row,
    approval_to_row,
    fill_from_row,
    fill_to_row,
    journal_from_row,
    journal_to_row,
    order_from_row,
    order_to_row,
    position_from_row,
    position_to_row,
    signal_from_row,
    signal_to_row,
    trade_plan_from_row,
    trade_plan_to_row,
)
from src.db.models import (
    ApprovalRow,
    Base,
    FillRow,
    JournalEventRow,
    OrderRow,
    PositionRow,
    SignalRow,
    TradePlanRow,
)
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    OrderStatus,
    PositionStatus,
    SignalStatus,
    TradePlanStatus,
)
from src.domain.fill import Fill
from src.domain.journal import JournalEvent
from src.domain.order import Order
from src.domain.position import Position
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan

# --------------------------------------------------------------------------- #
# Test scaffold.
# --------------------------------------------------------------------------- #


@pytest.fixture
def session() -> Iterator[Session]:
    """In-memory SQLite session with the seven-table schema applied.

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
    tzinfo (drops the timezone). To assert on the values the mapper
    ACTUALLY wrote — not the lossy SQLite roundtrip — we snapshot
    a deep copy of the ORM instance at `add()` time (BEFORE the commit
    that triggers SQLAlchemy's post-flush refresh from the DB).
    Production uses PostgreSQL NUMERIC(38,18) + TIMESTAMPTZ which
    preserve both exactly.
    """

    def __init__(self, real: Session) -> None:
        self._real = real
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        if isinstance(obj, SignalRow):
            self.added.append(
                SignalRow(
                    signal_id=obj.signal_id,
                    strategy_id=obj.strategy_id,
                    strategy_version=obj.strategy_version,
                    parameter_set_id=obj.parameter_set_id,
                    parameter_set_hash=obj.parameter_set_hash,
                    symbol=obj.symbol,
                    direction=obj.direction,
                    setup_type=obj.setup_type,
                    source_timeframe=obj.source_timeframe,
                    source_candle_close_utc=obj.source_candle_close_utc,
                    detected_at_utc=obj.detected_at_utc,
                    status=obj.status,
                    expires_at_utc=obj.expires_at_utc,
                    invalidated_at_utc=obj.invalidated_at_utc,
                )
            )
        elif isinstance(obj, TradePlanRow):
            self.added.append(
                TradePlanRow(
                    trade_plan_id=obj.trade_plan_id,
                    signal_id=obj.signal_id,
                    trade_plan_version=obj.trade_plan_version,
                    entry_model=obj.entry_model,
                    entry_min_price=obj.entry_min_price,
                    entry_max_price=obj.entry_max_price,
                    stop_loss_price=obj.stop_loss_price,
                    take_profit_json=obj.take_profit_json,
                    invalidation_rule_json=obj.invalidation_rule_json,
                    expiry_utc=obj.expiry_utc,
                    expected_rr_json=obj.expected_rr_json,
                    risk_rate=obj.risk_rate,
                    risk_budget=obj.risk_budget,
                    suggested_quantity=obj.suggested_quantity,
                    quantity_before_rounding=obj.quantity_before_rounding,
                    quantity_after_rounding=obj.quantity_after_rounding,
                    quantization_decision=obj.quantization_decision,
                    plan_hash=obj.plan_hash,
                    status=obj.status,
                    created_at_utc=obj.created_at_utc,
                )
            )
        elif isinstance(obj, ApprovalRow):
            self.added.append(
                ApprovalRow(
                    approval_id=obj.approval_id,
                    trade_plan_id=obj.trade_plan_id,
                    signal_id=obj.signal_id,
                    action=obj.action,
                    result=obj.result,
                    status=obj.status,
                    approval_token_hash=obj.approval_token_hash,
                    requested_at_utc=obj.requested_at_utc,
                    acted_at_utc=obj.acted_at_utc,
                    actor_id=obj.actor_id,
                    telegram_message_id=obj.telegram_message_id,
                    request_hash=obj.request_hash,
                )
            )
        elif isinstance(obj, OrderRow):
            self.added.append(
                OrderRow(
                    order_id=obj.order_id,
                    trade_plan_id=obj.trade_plan_id,
                    position_id=obj.position_id,
                    parent_order_id=obj.parent_order_id,
                    order_role=obj.order_role,
                    exchange=obj.exchange,
                    symbol=obj.symbol,
                    side=obj.side,
                    position_side=obj.position_side,
                    order_type=obj.order_type,
                    time_in_force=obj.time_in_force,
                    quantity=obj.quantity,
                    price=obj.price,
                    stop_price=obj.stop_price,
                    close_position=obj.close_position,
                    reduce_only=obj.reduce_only,
                    client_order_id=obj.client_order_id,
                    exchange_order_id=obj.exchange_order_id,
                    algo_client_id=obj.algo_client_id,
                    exchange_status=obj.exchange_status,
                    local_status=obj.local_status,
                    submitted_at_utc=obj.submitted_at_utc,
                    updated_at_utc=obj.updated_at_utc,
                    canceled_at_utc=obj.canceled_at_utc,
                )
            )
        elif isinstance(obj, FillRow):
            self.added.append(
                FillRow(
                    fill_id=obj.fill_id,
                    order_id=obj.order_id,
                    exchange_trade_id=obj.exchange_trade_id,
                    symbol=obj.symbol,
                    side=obj.side,
                    position_side=obj.position_side,
                    fill_price=obj.fill_price,
                    fill_quantity=obj.fill_quantity,
                    quote_quantity=obj.quote_quantity,
                    commission=obj.commission,
                    commission_asset=obj.commission_asset,
                    realized_pnl=obj.realized_pnl,
                    fill_time_utc=obj.fill_time_utc,
                    is_maker=obj.is_maker,
                )
            )
        elif isinstance(obj, PositionRow):
            self.added.append(
                PositionRow(
                    position_id=obj.position_id,
                    symbol=obj.symbol,
                    position_side=obj.position_side,
                    mode=obj.mode,
                    quantity=obj.quantity,
                    entry_price=obj.entry_price,
                    break_even_price=obj.break_even_price,
                    unrealized_pnl=obj.unrealized_pnl,
                    realized_pnl=obj.realized_pnl,
                    opened_at_utc=obj.opened_at_utc,
                    updated_at_utc=obj.updated_at_utc,
                    closed_at_utc=obj.closed_at_utc,
                    status=obj.status,
                )
            )
        elif isinstance(obj, JournalEventRow):
            self.added.append(
                JournalEventRow(
                    journal_event_id=obj.journal_event_id,
                    occurred_at_utc=obj.occurred_at_utc,
                    event_type=obj.event_type,
                    entity_type=obj.entity_type,
                    entity_id=obj.entity_id,
                    correlation_id=obj.correlation_id,
                    signal_id=obj.signal_id,
                    trade_plan_id=obj.trade_plan_id,
                    approval_id=obj.approval_id,
                    order_id=obj.order_id,
                    position_id=obj.position_id,
                    payload_json=obj.payload_json,
                    created_at_utc=obj.created_at_utc,
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
# Test fixtures — representative domain entities.
# --------------------------------------------------------------------------- #


@pytest.fixture
def sample_signal() -> Signal:
    """A representative Signal with boundary Decimal/UTC values."""
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


@pytest.fixture
def sample_trade_plan() -> TradePlan:
    """A representative TradePlan with boundary Decimal/UTC values."""
    return TradePlan(
        trade_plan_id="c" * 64,
        signal_id="a" * 64,
        trade_plan_version="v1.0.0",
        entry_model="LIMIT_ZONE",
        entry_min_price=Decimal("50000.000000000000000000"),
        entry_max_price=Decimal("50100.000000000000000000"),
        stop_loss_price=Decimal("49500.000000000000000000"),
        take_profit_json='[{"price":"51000.00","ratio":0.5}]',
        invalidation_rule_json='{"type":"candle_close_below","price":"49400.00"}',
        expiry_utc=datetime(2026, 9, 19, 16, 0, tzinfo=UTC),
        expected_rr_json='{"rr":2.0}',
        risk_rate=Decimal("0.005000000000000000"),
        risk_budget=Decimal("4.000000000000000000"),
        suggested_quantity=Decimal("0.080000000000000000"),
        quantity_before_rounding=Decimal("0.080000000000000000"),
        quantity_after_rounding=Decimal("0.080000000000000000"),
        quantization_decision="ACCEPT",
        plan_hash="d" * 64,
        status=TradePlanStatus.READY,
        created_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
    )


@pytest.fixture
def sample_approval() -> Approval:
    """A representative Approval with nullable acted_at_utc."""
    return Approval(
        approval_id="e" * 64,
        trade_plan_id="c" * 64,
        signal_id="a" * 64,
        action=ApprovalAction.APPROVE,
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        approval_token_hash="f" * 64,
        requested_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        acted_at_utc=None,
        actor_id="user-1",
        telegram_message_id=None,
        request_hash="0" * 64,
    )


@pytest.fixture
def sample_order() -> Order:
    """A representative Order with nullable price/stop_price/canceled."""
    return Order(
        order_id="1" * 64,
        trade_plan_id="c" * 64,
        position_id=None,
        parent_order_id=None,
        order_role="ENTRY",
        exchange="BINANCE",
        symbol="BTCUSDT",
        side="BUY",
        position_side="LONG",
        order_type="LIMIT",
        time_in_force="GTC",
        quantity=Decimal("0.080000000000000000"),
        price=Decimal("50050.000000000000000000"),
        stop_price=None,
        close_position=False,
        reduce_only=False,
        client_order_id="client-1",
        exchange_order_id=None,
        algo_client_id=None,
        exchange_status="NEW",
        local_status=OrderStatus.NEW,
        submitted_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        updated_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        canceled_at_utc=None,
    )


@pytest.fixture
def sample_fill() -> Fill:
    """A representative Fill with boundary Decimal values."""
    return Fill(
        fill_id="2" * 64,
        order_id="1" * 64,
        exchange_trade_id="trade-1",
        symbol="BTCUSDT",
        side="BUY",
        position_side="LONG",
        fill_price=Decimal("50050.000000000000000000"),
        fill_quantity=Decimal("0.080000000000000000"),
        quote_quantity=Decimal("4004.000000000000000000"),
        commission=Decimal("0.000080000000000000"),
        commission_asset="USDT",
        realized_pnl=Decimal("0.000000000000000000"),
        fill_time_utc=datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        is_maker=False,
    )


@pytest.fixture
def sample_position() -> Position:
    """A representative Position with nullable closed_at_utc."""
    return Position(
        position_id="3" * 64,
        symbol="BTCUSDT",
        position_side="LONG",
        mode="ONE_WAY",
        quantity=Decimal("0.080000000000000000"),
        entry_price=Decimal("50050.000000000000000000"),
        break_even_price=Decimal("50050.000000000000000000"),
        unrealized_pnl=Decimal("0.000000000000000000"),
        realized_pnl=Decimal("0.000000000000000000"),
        opened_at_utc=datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        updated_at_utc=datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        closed_at_utc=None,
        status=PositionStatus.OPEN,
    )


@pytest.fixture
def sample_journal_event() -> JournalEvent:
    """A representative JournalEvent with nullable linkage ids."""
    return JournalEvent(
        journal_event_id="4" * 64,
        occurred_at_utc=datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        event_type="ORDER_PLACED",
        entity_type="ORDER",
        entity_id="1" * 64,
        correlation_id="corr-1",
        signal_id="a" * 64,
        trade_plan_id="c" * 64,
        approval_id=None,
        order_id="1" * 64,
        position_id=None,
        payload_json='{"price":"50050.00"}',
        created_at_utc=datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
    )


# =========================================================================== #
# Round-trip tests — from_row(to_row(x)) == x for all seven entities.
# =========================================================================== #


def test_signal_round_trip(sample_signal: Signal) -> None:
    """Beh. 1: signal_from_row(signal_to_row(s)) == s."""
    row = signal_to_row(sample_signal)
    restored = signal_from_row(row)
    assert restored == sample_signal


def test_trade_plan_round_trip(sample_trade_plan: TradePlan) -> None:
    """Beh. 2: trade_plan_from_row(trade_plan_to_row(t)) == t."""
    row = trade_plan_to_row(sample_trade_plan)
    restored = trade_plan_from_row(row)
    assert restored == sample_trade_plan


def test_approval_round_trip(sample_approval: Approval) -> None:
    """Beh. 3: approval_from_row(approval_to_row(a)) == a."""
    row = approval_to_row(sample_approval)
    restored = approval_from_row(row)
    assert restored == sample_approval


def test_order_round_trip(sample_order: Order) -> None:
    """Beh. 4: order_from_row(order_to_row(o)) == o."""
    row = order_to_row(sample_order)
    restored = order_from_row(row)
    assert restored == sample_order


def test_fill_round_trip(sample_fill: Fill) -> None:
    """Beh. 5: fill_from_row(fill_to_row(f)) == f."""
    row = fill_to_row(sample_fill)
    restored = fill_from_row(row)
    assert restored == sample_fill


def test_position_round_trip(sample_position: Position) -> None:
    """Beh. 6: position_from_row(position_to_row(p)) == p."""
    row = position_to_row(sample_position)
    restored = position_from_row(row)
    assert restored == sample_position


def test_journal_event_round_trip(sample_journal_event: JournalEvent) -> None:
    """Beh. 7: journal_from_row(journal_to_row(j)) == j."""
    row = journal_to_row(sample_journal_event)
    restored = journal_from_row(row)
    assert restored == sample_journal_event


# =========================================================================== #
# Captured-snapshot precision assertions — verify mapper output BEFORE
# SQLite roundtrip (NUMERIC → REAL lossiness cannot hide mapper errors).
# =========================================================================== #


def test_signal_captured_snapshot_precision(
    session: Session, sample_signal: Signal
) -> None:
    """Beh. 8: captured SignalRow carries exact Decimal/UTC values."""
    cap = CapturingSession(session)
    cap.add(signal_to_row(sample_signal))
    assert len(cap.added) == 1
    row = cap.added[0]
    assert isinstance(row, SignalRow)
    assert row.signal_id == sample_signal.signal_id
    assert row.status == "DETECTED"
    assert row.source_candle_close_utc == sample_signal.source_candle_close_utc
    assert row.invalidated_at_utc is None


def test_trade_plan_captured_snapshot_precision(
    session: Session, sample_trade_plan: TradePlan
) -> None:
    """Beh. 9: captured TradePlanRow carries exact Decimal/UTC values."""
    cap = CapturingSession(session)
    cap.add(trade_plan_to_row(sample_trade_plan))
    assert len(cap.added) == 1
    row = cap.added[0]
    assert isinstance(row, TradePlanRow)
    assert row.entry_min_price == sample_trade_plan.entry_min_price
    assert row.entry_max_price == sample_trade_plan.entry_max_price
    assert row.stop_loss_price == sample_trade_plan.stop_loss_price
    assert row.status == "READY"


def test_approval_captured_snapshot_precision(
    session: Session, sample_approval: Approval
) -> None:
    """Beh. 10: captured ApprovalRow carries exact Enum/UTC values."""
    cap = CapturingSession(session)
    cap.add(approval_to_row(sample_approval))
    assert len(cap.added) == 1
    row = cap.added[0]
    assert isinstance(row, ApprovalRow)
    assert row.action == "APPROVE"
    assert row.result == "PENDING"
    assert row.status == "PENDING"
    assert row.acted_at_utc is None


def test_order_captured_snapshot_precision(
    session: Session, sample_order: Order
) -> None:
    """Beh. 11: captured OrderRow carries exact Decimal/Enum values."""
    cap = CapturingSession(session)
    cap.add(order_to_row(sample_order))
    assert len(cap.added) == 1
    row = cap.added[0]
    assert isinstance(row, OrderRow)
    assert row.quantity == sample_order.quantity
    assert row.price == sample_order.price
    assert row.local_status == "NEW"
    assert row.canceled_at_utc is None


def test_fill_captured_snapshot_precision(
    session: Session, sample_fill: Fill
) -> None:
    """Beh. 12: captured FillRow carries exact Decimal/UTC values."""
    cap = CapturingSession(session)
    cap.add(fill_to_row(sample_fill))
    assert len(cap.added) == 1
    row = cap.added[0]
    assert isinstance(row, FillRow)
    assert row.fill_price == sample_fill.fill_price
    assert row.fill_quantity == sample_fill.fill_quantity
    assert row.commission == sample_fill.commission
    assert row.is_maker is False


def test_position_captured_snapshot_precision(
    session: Session, sample_position: Position
) -> None:
    """Beh. 13: captured PositionRow carries exact Decimal/Enum values."""
    cap = CapturingSession(session)
    cap.add(position_to_row(sample_position))
    assert len(cap.added) == 1
    row = cap.added[0]
    assert isinstance(row, PositionRow)
    assert row.entry_price == sample_position.entry_price
    assert row.status == "OPEN"
    assert row.closed_at_utc is None


def test_journal_event_captured_snapshot_precision(
    session: Session, sample_journal_event: JournalEvent
) -> None:
    """Beh. 14: captured JournalEventRow carries exact UTC values."""
    cap = CapturingSession(session)
    cap.add(journal_to_row(sample_journal_event))
    assert len(cap.added) == 1
    row = cap.added[0]
    assert isinstance(row, JournalEventRow)
    assert row.event_type == "ORDER_PLACED"
    assert row.entity_type == "ORDER"
    assert row.occurred_at_utc == sample_journal_event.occurred_at_utc


# =========================================================================== #
# Unknown status rejection — Enum(value) raises ValueError on unknown.
# =========================================================================== #


def test_signal_unknown_status_raises() -> None:
    """Beh. 15: signal_from_row with unknown status raises ValueError."""
    row = SignalRow(
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
        status="UNKNOWN_STATUS",
        expires_at_utc=datetime(2026, 9, 19, 16, 0, tzinfo=UTC),
        invalidated_at_utc=None,
    )
    with pytest.raises(ValueError):
        signal_from_row(row)


def test_trade_plan_unknown_status_raises() -> None:
    """Beh. 16: trade_plan_from_row with unknown status raises ValueError."""
    row = TradePlanRow(
        trade_plan_id="c" * 64,
        signal_id="a" * 64,
        trade_plan_version="v1.0.0",
        entry_model="LIMIT_ZONE",
        entry_min_price=Decimal("50000"),
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
        status="UNKNOWN_STATUS",
        created_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
    )
    with pytest.raises(ValueError):
        trade_plan_from_row(row)


def test_approval_unknown_action_raises() -> None:
    """Beh. 17: approval_from_row with unknown action raises ValueError."""
    row = ApprovalRow(
        approval_id="e" * 64,
        trade_plan_id="c" * 64,
        signal_id="a" * 64,
        action="UNKNOWN_ACTION",
        result="PENDING",
        status="PENDING",
        approval_token_hash="f" * 64,
        requested_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        acted_at_utc=None,
        actor_id="user-1",
        telegram_message_id=None,
        request_hash="0" * 64,
    )
    with pytest.raises(ValueError):
        approval_from_row(row)


def test_approval_unknown_result_raises() -> None:
    """Beh. 18: approval_from_row with unknown result raises ValueError."""
    row = ApprovalRow(
        approval_id="e" * 64,
        trade_plan_id="c" * 64,
        signal_id="a" * 64,
        action="APPROVE",
        result="UNKNOWN_RESULT",
        status="PENDING",
        approval_token_hash="f" * 64,
        requested_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        acted_at_utc=None,
        actor_id="user-1",
        telegram_message_id=None,
        request_hash="0" * 64,
    )
    with pytest.raises(ValueError):
        approval_from_row(row)


def test_order_unknown_local_status_raises() -> None:
    """Beh. 19: order_from_row with unknown local_status raises ValueError."""
    row = OrderRow(
        order_id="1" * 64,
        trade_plan_id="c" * 64,
        position_id=None,
        parent_order_id=None,
        order_role="ENTRY",
        exchange="BINANCE",
        symbol="BTCUSDT",
        side="BUY",
        position_side="LONG",
        order_type="LIMIT",
        time_in_force="GTC",
        quantity=Decimal("0.08"),
        price=Decimal("50050"),
        stop_price=None,
        close_position=False,
        reduce_only=False,
        client_order_id="client-1",
        exchange_order_id=None,
        algo_client_id=None,
        exchange_status="NEW",
        local_status="UNKNOWN_STATUS",
        submitted_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        updated_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        canceled_at_utc=None,
    )
    with pytest.raises(ValueError):
        order_from_row(row)


def test_position_unknown_status_raises() -> None:
    """Beh. 20: position_from_row with unknown status raises ValueError."""
    row = PositionRow(
        position_id="3" * 64,
        symbol="BTCUSDT",
        position_side="LONG",
        mode="ONE_WAY",
        quantity=Decimal("0.08"),
        entry_price=Decimal("50050"),
        break_even_price=Decimal("50050"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        opened_at_utc=datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        updated_at_utc=datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        closed_at_utc=None,
        status="UNKNOWN_STATUS",
    )
    with pytest.raises(ValueError):
        position_from_row(row)


# =========================================================================== #
# Nullable never-happened timestamps round-trip as None.
# =========================================================================== #


def test_signal_invalidated_at_utc_none_round_trips() -> None:
    """Beh. 21: Signal.invalidated_at_utc=None round-trips as None."""
    s = Signal(
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
    row = signal_to_row(s)
    assert row.invalidated_at_utc is None
    restored = signal_from_row(row)
    assert restored.invalidated_at_utc is None


def test_approval_acted_at_utc_none_round_trips() -> None:
    """Beh. 22: Approval.acted_at_utc=None round-trips as None."""
    a = Approval(
        approval_id="e" * 64,
        trade_plan_id="c" * 64,
        signal_id="a" * 64,
        action=ApprovalAction.APPROVE,
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        approval_token_hash="f" * 64,
        requested_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        acted_at_utc=None,
        actor_id="user-1",
        telegram_message_id=None,
        request_hash="0" * 64,
    )
    row = approval_to_row(a)
    assert row.acted_at_utc is None
    assert row.telegram_message_id is None
    restored = approval_from_row(row)
    assert restored.acted_at_utc is None
    assert restored.telegram_message_id is None


def test_order_canceled_at_utc_none_round_trips() -> None:
    """Beh. 23: Order.canceled_at_utc=None round-trips as None."""
    o = Order(
        order_id="1" * 64,
        trade_plan_id="c" * 64,
        position_id=None,
        parent_order_id=None,
        order_role="ENTRY",
        exchange="BINANCE",
        symbol="BTCUSDT",
        side="BUY",
        position_side="LONG",
        order_type="LIMIT",
        time_in_force="GTC",
        quantity=Decimal("0.08"),
        price=Decimal("50050"),
        stop_price=None,
        close_position=False,
        reduce_only=False,
        client_order_id="client-1",
        exchange_order_id=None,
        algo_client_id=None,
        exchange_status="NEW",
        local_status=OrderStatus.NEW,
        submitted_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        updated_at_utc=datetime(2026, 9, 19, 12, 5, tzinfo=UTC),
        canceled_at_utc=None,
    )
    row = order_to_row(o)
    assert row.canceled_at_utc is None
    restored = order_from_row(row)
    assert restored.canceled_at_utc is None


def test_position_closed_at_utc_none_round_trips() -> None:
    """Beh. 24: Position.closed_at_utc=None round-trips as None."""
    p = Position(
        position_id="3" * 64,
        symbol="BTCUSDT",
        position_side="LONG",
        mode="ONE_WAY",
        quantity=Decimal("0.08"),
        entry_price=Decimal("50050"),
        break_even_price=Decimal("50050"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        opened_at_utc=datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        updated_at_utc=datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        closed_at_utc=None,
        status=PositionStatus.OPEN,
    )
    row = position_to_row(p)
    assert row.closed_at_utc is None
    restored = position_from_row(row)
    assert restored.closed_at_utc is None


def test_journal_event_message_id_none_round_trips() -> None:
    """Beh. 25: JournalEvent nullable linkage ids round-trip as None."""
    j = JournalEvent(
        journal_event_id="4" * 64,
        occurred_at_utc=datetime(2026, 9, 19, 12, 6, tzinfo=UTC),
        event_type="ORDER_PLACED",
        entity_type="ORDER",
        entity_id="1" * 64,
        correlation_id="corr-1",
        signal_id=None,
        trade_plan_id=None,
        approval_id=None,
        order_id=None,
        position_id=None,
        payload_json="{}",
        created_at_utc=None,
    )
    row = journal_to_row(j)
    assert row.signal_id is None
    assert row.trade_plan_id is None
    assert row.approval_id is None
    assert row.order_id is None
    assert row.position_id is None
    assert row.created_at_utc is None
    restored = journal_from_row(row)
    assert restored.signal_id is None
    assert restored.trade_plan_id is None
    assert restored.approval_id is None
    assert restored.order_id is None
    assert restored.position_id is None
    assert restored.created_at_utc is None
