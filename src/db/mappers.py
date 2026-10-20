"""Thin total mappers between domain entities and ORM rows (Phase 3, plans 03-01 + 03-04).

Per D-02: PostgreSQL tables mirror the domain 1:1 via a separate ORM
layer. Thin mapper functions translate domain ↔ row; no ORM class IS
the domain model.

Mappers are total (every field mapped) and round-trip tested:
`from_row(to_row(x)) == x`.

Enum translation is the only bridge between domain Enums and row
strings: `Enum.value` for storage, `Enum(value)` for restore (raises
ValueError on unknown — D-10).
"""

from __future__ import annotations

from src.approval.mapping import ShortIdMapping
from src.db.models import (
    ApprovalRow,
    FillRow,
    JournalEventRow,
    OrderRow,
    PositionRow,
    ShortIdMappingRow,
    SignalRow,
    TradePlanRow,
)
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalConsumptionStatus,
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

# ---------- Signal -----------------------------------------------------------


def signal_to_row(s: Signal) -> SignalRow:
    """Convert a domain Signal to its ORM row representation.

    `status` is stored as `SignalStatus.value` (the string) for ORM
    portability. The `from_row` path reconstructs the Enum via
    `SignalStatus(value)` — unknown values raise ValueError (D-10).
    """
    return SignalRow(
        signal_id=s.signal_id,
        strategy_id=s.strategy_id,
        strategy_version=s.strategy_version,
        parameter_set_id=s.parameter_set_id,
        parameter_set_hash=s.parameter_set_hash,
        symbol=s.symbol,
        direction=s.direction,
        setup_type=s.setup_type,
        source_timeframe=s.source_timeframe,
        source_candle_close_utc=s.source_candle_close_utc,
        detected_at_utc=s.detected_at_utc,
        status=s.status.value,
        expires_at_utc=s.expires_at_utc,
        invalidated_at_utc=s.invalidated_at_utc,
    )


def signal_from_row(r: SignalRow) -> Signal:
    """Convert an ORM SignalRow back to a domain Signal.

    `status` is reconstructed via `SignalStatus(value)` — unknown
    values raise ValueError (D-10 boundary contract).
    """
    return Signal(
        signal_id=r.signal_id,
        strategy_id=r.strategy_id,
        strategy_version=r.strategy_version,
        parameter_set_id=r.parameter_set_id,
        parameter_set_hash=r.parameter_set_hash,
        symbol=r.symbol,
        direction=r.direction,
        setup_type=r.setup_type,
        source_timeframe=r.source_timeframe,
        source_candle_close_utc=r.source_candle_close_utc,
        detected_at_utc=r.detected_at_utc,
        status=SignalStatus(r.status),
        expires_at_utc=r.expires_at_utc,
        invalidated_at_utc=r.invalidated_at_utc,
    )


# ---------- TradePlan --------------------------------------------------------


def trade_plan_to_row(t: TradePlan) -> TradePlanRow:
    """Convert a domain TradePlan to its ORM row representation.

    `status` is stored as `TradePlanStatus.value` (D-10/D-11).
    """
    return TradePlanRow(
        trade_plan_id=t.trade_plan_id,
        signal_id=t.signal_id,
        trade_plan_version=t.trade_plan_version,
        entry_model=t.entry_model,
        entry_min_price=t.entry_min_price,
        entry_max_price=t.entry_max_price,
        stop_loss_price=t.stop_loss_price,
        take_profit_json=t.take_profit_json,
        invalidation_rule_json=t.invalidation_rule_json,
        expiry_utc=t.expiry_utc,
        expected_rr_json=t.expected_rr_json,
        risk_rate=t.risk_rate,
        risk_budget=t.risk_budget,
        suggested_quantity=t.suggested_quantity,
        quantity_before_rounding=t.quantity_before_rounding,
        quantity_after_rounding=t.quantity_after_rounding,
        quantization_decision=t.quantization_decision,
        plan_hash=t.plan_hash,
        status=t.status.value,
        created_at_utc=t.created_at_utc,
    )


def trade_plan_from_row(r: TradePlanRow) -> TradePlan:
    """Convert an ORM TradePlanRow back to a domain TradePlan.

    `status` is reconstructed via `TradePlanStatus(value)` — unknown
    values raise ValueError (D-10 boundary contract).
    """
    return TradePlan(
        trade_plan_id=r.trade_plan_id,
        signal_id=r.signal_id,
        trade_plan_version=r.trade_plan_version,
        entry_model=r.entry_model,
        entry_min_price=r.entry_min_price,
        entry_max_price=r.entry_max_price,
        stop_loss_price=r.stop_loss_price,
        take_profit_json=r.take_profit_json,
        invalidation_rule_json=r.invalidation_rule_json,
        expiry_utc=r.expiry_utc,
        expected_rr_json=r.expected_rr_json,
        risk_rate=r.risk_rate,
        risk_budget=r.risk_budget,
        suggested_quantity=r.suggested_quantity,
        quantity_before_rounding=r.quantity_before_rounding,
        quantity_after_rounding=r.quantity_after_rounding,
        quantization_decision=r.quantization_decision,
        plan_hash=r.plan_hash,
        status=TradePlanStatus(r.status),
        created_at_utc=r.created_at_utc,
    )


# ---------- Approval ---------------------------------------------------------


def approval_to_row(a: Approval) -> ApprovalRow:
    """Convert a domain Approval to its ORM row representation.

    `action`, `result`, and `status` are stored as their Enum values
    (D-10/D-11). `status` alone answers state.
    """
    return ApprovalRow(
        approval_id=a.approval_id,
        trade_plan_id=a.trade_plan_id,
        signal_id=a.signal_id,
        action=a.action.value,
        result=a.result.value,
        status=a.status.value,
        approval_token_hash=a.approval_token_hash,
        requested_at_utc=a.requested_at_utc,
        acted_at_utc=a.acted_at_utc,
        actor_id=a.actor_id,
        telegram_message_id=a.telegram_message_id,
        request_hash=a.request_hash,
        consumption_status=a.consumption_status.value,
        consumed_at_utc=a.consumed_at_utc,
        approved_quantity=a.approved_quantity,
    )


def approval_from_row(r: ApprovalRow) -> Approval:
    """Convert an ORM ApprovalRow back to a domain Approval.

    `action`, `result`, and `status` are reconstructed via their
    respective Enum constructors — unknown values raise ValueError
    (D-10 boundary contract).
    """
    return Approval(
        approval_id=r.approval_id,
        trade_plan_id=r.trade_plan_id,
        signal_id=r.signal_id,
        action=ApprovalAction(r.action),
        result=ApprovalResult(r.result),
        status=ApprovalResult(r.status),
        approval_token_hash=r.approval_token_hash,
        requested_at_utc=r.requested_at_utc,
        acted_at_utc=r.acted_at_utc,
        actor_id=r.actor_id,
        telegram_message_id=r.telegram_message_id,
        request_hash=r.request_hash,
        consumption_status=ApprovalConsumptionStatus(r.consumption_status),
        consumed_at_utc=r.consumed_at_utc,
        approved_quantity=r.approved_quantity,
    )


# ---------- Order ------------------------------------------------------------


def order_to_row(o: Order) -> OrderRow:
    """Convert a domain Order to its ORM row representation.

    `local_status` is stored as `OrderStatus.value`; `exchange_status`
    is a raw string from Binance (D-10).
    """
    return OrderRow(
        order_id=o.order_id,
        trade_plan_id=o.trade_plan_id,
        position_id=o.position_id,
        parent_order_id=o.parent_order_id,
        order_role=o.order_role,
        exchange=o.exchange,
        symbol=o.symbol,
        side=o.side,
        position_side=o.position_side,
        order_type=o.order_type,
        time_in_force=o.time_in_force,
        quantity=o.quantity,
        price=o.price,
        stop_price=o.stop_price,
        close_position=o.close_position,
        reduce_only=o.reduce_only,
        client_order_id=o.client_order_id,
        exchange_order_id=o.exchange_order_id,
        algo_client_id=o.algo_client_id,
        exchange_status=o.exchange_status,
        local_status=o.local_status.value,
        submitted_at_utc=o.submitted_at_utc,
        updated_at_utc=o.updated_at_utc,
        canceled_at_utc=o.canceled_at_utc,
    )


def order_from_row(r: OrderRow) -> Order:
    """Convert an ORM OrderRow back to a domain Order.

    `local_status` is reconstructed via `OrderStatus(value)` — unknown
    values raise ValueError (D-10 boundary contract).
    """
    return Order(
        order_id=r.order_id,
        trade_plan_id=r.trade_plan_id,
        position_id=r.position_id,
        parent_order_id=r.parent_order_id,
        order_role=r.order_role,
        exchange=r.exchange,
        symbol=r.symbol,
        side=r.side,
        position_side=r.position_side,
        order_type=r.order_type,
        time_in_force=r.time_in_force,
        quantity=r.quantity,
        price=r.price,
        stop_price=r.stop_price,
        close_position=r.close_position,
        reduce_only=r.reduce_only,
        client_order_id=r.client_order_id,
        exchange_order_id=r.exchange_order_id,
        algo_client_id=r.algo_client_id,
        exchange_status=r.exchange_status,
        local_status=OrderStatus(r.local_status),
        submitted_at_utc=r.submitted_at_utc,
        updated_at_utc=r.updated_at_utc,
        canceled_at_utc=r.canceled_at_utc,
    )


# ---------- Fill -------------------------------------------------------------


def fill_to_row(f: Fill) -> FillRow:
    """Convert a domain Fill to its ORM row representation.

    Fills are events with no status field (DATA_MODEL §2.8).
    """
    return FillRow(
        fill_id=f.fill_id,
        order_id=f.order_id,
        exchange_trade_id=f.exchange_trade_id,
        symbol=f.symbol,
        side=f.side,
        position_side=f.position_side,
        fill_price=f.fill_price,
        fill_quantity=f.fill_quantity,
        quote_quantity=f.quote_quantity,
        commission=f.commission,
        commission_asset=f.commission_asset,
        realized_pnl=f.realized_pnl,
        fill_time_utc=f.fill_time_utc,
        is_maker=f.is_maker,
    )


def fill_from_row(r: FillRow) -> Fill:
    """Convert an ORM FillRow back to a domain Fill."""
    return Fill(
        fill_id=r.fill_id,
        order_id=r.order_id,
        exchange_trade_id=r.exchange_trade_id,
        symbol=r.symbol,
        side=r.side,
        position_side=r.position_side,
        fill_price=r.fill_price,
        fill_quantity=r.fill_quantity,
        quote_quantity=r.quote_quantity,
        commission=r.commission,
        commission_asset=r.commission_asset,
        realized_pnl=r.realized_pnl,
        fill_time_utc=r.fill_time_utc,
        is_maker=r.is_maker,
    )


# ---------- Position ---------------------------------------------------------


def position_to_row(p: Position) -> PositionRow:
    """Convert a domain Position to its ORM row representation.

    `status` is stored as `PositionStatus.value` (D-10/D-11).
    """
    return PositionRow(
        position_id=p.position_id,
        symbol=p.symbol,
        position_side=p.position_side,
        mode=p.mode,
        quantity=p.quantity,
        entry_price=p.entry_price,
        break_even_price=p.break_even_price,
        unrealized_pnl=p.unrealized_pnl,
        realized_pnl=p.realized_pnl,
        opened_at_utc=p.opened_at_utc,
        updated_at_utc=p.updated_at_utc,
        closed_at_utc=p.closed_at_utc,
        status=p.status.value,
    )


def position_from_row(r: PositionRow) -> Position:
    """Convert an ORM PositionRow back to a domain Position.

    `status` is reconstructed via `PositionStatus(value)` — unknown
    values raise ValueError (D-10 boundary contract).
    """
    return Position(
        position_id=r.position_id,
        symbol=r.symbol,
        position_side=r.position_side,
        mode=r.mode,
        quantity=r.quantity,
        entry_price=r.entry_price,
        break_even_price=r.break_even_price,
        unrealized_pnl=r.unrealized_pnl,
        realized_pnl=r.realized_pnl,
        opened_at_utc=r.opened_at_utc,
        updated_at_utc=r.updated_at_utc,
        closed_at_utc=r.closed_at_utc,
        status=PositionStatus(r.status),
    )


# ---------- JournalEvent -----------------------------------------------------


def journal_to_row(j: JournalEvent) -> JournalEventRow:
    """Convert a domain JournalEvent to its ORM row representation.

    JournalEvent is append-only and never substitutes for current-state
    tables (DATA_MODEL §2.10).
    """
    return JournalEventRow(
        journal_event_id=j.journal_event_id,
        occurred_at_utc=j.occurred_at_utc,
        event_type=j.event_type,
        entity_type=j.entity_type,
        entity_id=j.entity_id,
        correlation_id=j.correlation_id,
        signal_id=j.signal_id,
        trade_plan_id=j.trade_plan_id,
        approval_id=j.approval_id,
        order_id=j.order_id,
        position_id=j.position_id,
        payload_json=j.payload_json,
        created_at_utc=j.created_at_utc,
    )


def journal_from_row(r: JournalEventRow) -> JournalEvent:
    """Convert an ORM JournalEventRow back to a domain JournalEvent."""
    return JournalEvent(
        journal_event_id=r.journal_event_id,
        occurred_at_utc=r.occurred_at_utc,
        event_type=r.event_type,
        entity_type=r.entity_type,
        entity_id=r.entity_id,
        correlation_id=r.correlation_id,
        signal_id=r.signal_id,
        trade_plan_id=r.trade_plan_id,
        approval_id=r.approval_id,
        order_id=r.order_id,
        position_id=r.position_id,
        payload_json=r.payload_json,
        created_at_utc=r.created_at_utc,
    )


__all__ = [
    "signal_to_row",
    "signal_from_row",
    "trade_plan_to_row",
    "trade_plan_from_row",
    "approval_to_row",
    "approval_from_row",
    "order_to_row",
    "order_from_row",
    "fill_to_row",
    "fill_from_row",
    "position_to_row",
    "position_from_row",
    "journal_to_row",
    "journal_from_row",
    "short_id_mapping_to_row",
    "short_id_mapping_from_row",
]


# ---------- ShortIdMapping ---------------------------------------------------


def short_id_mapping_to_row(m: ShortIdMapping) -> ShortIdMappingRow:
    """Convert a domain ShortIdMapping to its ORM row representation.

    Per D-02: the row carries the deterministic short_id (PK), the
    full signal_id and trade_plan_id, and the UTC-aware created_at_utc.
    No enum translation needed — all four fields are plain strings
    or UTC-aware datetimes, matching the rest of the mappers'
    "round-trippable" contract.
    """
    return ShortIdMappingRow(
        short_id=m.short_id,
        signal_id=m.signal_id,
        trade_plan_id=m.trade_plan_id,
        created_at_utc=m.created_at_utc,
    )


def short_id_mapping_from_row(r: ShortIdMappingRow) -> ShortIdMapping:
    """Convert an ORM ShortIdMappingRow back to a domain ShortIdMapping.

    Round-trip contract: `short_id_mapping_from_row(short_id_mapping_to_row(m))
    == m`. The validator on `ShortIdMapping.__post_init__` runs again on
    construction, so any future drift in `created_at_utc` timezone
    awareness fails loudly at the type boundary.
    """
    return ShortIdMapping(
        short_id=r.short_id,
        signal_id=r.signal_id,
        trade_plan_id=r.trade_plan_id,
        created_at_utc=r.created_at_utc,
    )
