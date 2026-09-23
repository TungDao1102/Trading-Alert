"""Tests for the remaining six domain entities (Phase 3, plan 03-02).

Per D-01/D-10/D-11/D-12: TradePlan, Approval, Order, Fill, Position, and
JournalEvent are frozen pure-Python dataclasses with Decimal money/qty/price
fields, timezone-aware UTC datetime fields, and Enum status fields. No
`Optional` status; `Optional` is reserved for "transition never happened"
timestamps only.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/domain/{trade_plan,approval,order,fill,position,journal}.py`
are implemented.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

# --------------------------------------------------------------------------- #
# Helpers — shared construction kwargs for the discipline tests.
# --------------------------------------------------------------------------- #

UTC_NOW = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
UTC_LATER = datetime(2026, 9, 19, 4, 0, tzinfo=UTC)


def _trade_plan_kwargs() -> dict:
    """Return a complete kwargs dict for constructing a TradePlan."""
    from src.domain.enums import TradePlanStatus

    return {
        "trade_plan_id": "a" * 64,
        "signal_id": "b" * 64,
        "trade_plan_version": "v1",
        "entry_model": "LIMIT_ZONE",
        "entry_min_price": Decimal("50000.00"),
        "entry_max_price": Decimal("50100.00"),
        "stop_loss_price": Decimal("49500.00"),
        "take_profit_json": '{"levels":[{"price":"51000.00","qty":"0.5"}]}',
        "invalidation_rule_json": '{"type":"close_below_stop"}',
        "expiry_utc": UTC_LATER,
        "expected_rr_json": '{"rr":2.5}',
        "risk_rate": Decimal("0.005"),
        "risk_budget": Decimal("50.00"),
        "suggested_quantity": Decimal("0.100"),
        "quantity_before_rounding": Decimal("0.123456"),
        "quantity_after_rounding": Decimal("0.100"),
        "quantization_decision": "ACCEPTED",
        "plan_hash": "c" * 64,
        "status": TradePlanStatus.READY,
        "created_at_utc": UTC_NOW,
    }


def _approval_kwargs() -> dict:
    """Return a complete kwargs dict for constructing an Approval."""
    from src.domain.enums import ApprovalAction, ApprovalResult

    return {
        "approval_id": "d" * 64,
        "trade_plan_id": "a" * 64,
        "signal_id": "b" * 64,
        "action": ApprovalAction.APPROVE,
        "result": ApprovalResult.PENDING,
        "status": ApprovalResult.PENDING,
        "approval_token_hash": "e" * 64,
        "requested_at_utc": UTC_NOW,
        "acted_at_utc": None,
        "actor_id": "user:12345",
        "telegram_message_id": None,
        "request_hash": "f" * 64,
    }


def _order_kwargs() -> dict:
    """Return a complete kwargs dict for constructing an Order."""
    from src.domain.enums import OrderStatus

    return {
        "order_id": "1" * 64,
        "trade_plan_id": "a" * 64,
        "position_id": None,
        "parent_order_id": None,
        "order_role": "ENTRY",
        "exchange": "BINANCE",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "LONG",
        "order_type": "LIMIT",
        "time_in_force": "GTC",
        "quantity": Decimal("0.100"),
        "price": Decimal("50050.00"),
        "stop_price": None,
        "close_position": False,
        "reduce_only": False,
        "client_order_id": "client-1",
        "exchange_order_id": None,
        "algo_client_id": None,
        "exchange_status": "NEW",
        "local_status": OrderStatus.NEW,
        "submitted_at_utc": UTC_NOW,
        "updated_at_utc": UTC_NOW,
        "canceled_at_utc": None,
    }


def _fill_kwargs() -> dict:
    """Return a complete kwargs dict for constructing a Fill."""
    return {
        "fill_id": "2" * 64,
        "order_id": "1" * 64,
        "exchange_trade_id": "trade-1",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "position_side": "LONG",
        "fill_price": Decimal("50050.00"),
        "fill_quantity": Decimal("0.100"),
        "quote_quantity": Decimal("5005.00"),
        "commission": Decimal("0.005"),
        "commission_asset": "USDT",
        "realized_pnl": Decimal("0"),
        "fill_time_utc": UTC_NOW,
        "is_maker": False,
    }


def _position_kwargs() -> dict:
    """Return a complete kwargs dict for constructing a Position."""
    from src.domain.enums import PositionStatus

    return {
        "position_id": "3" * 64,
        "symbol": "BTCUSDT",
        "position_side": "LONG",
        "mode": "ONE_WAY",
        "quantity": Decimal("0.100"),
        "entry_price": Decimal("50050.00"),
        "break_even_price": Decimal("50050.00"),
        "unrealized_pnl": Decimal("0"),
        "realized_pnl": Decimal("0"),
        "opened_at_utc": UTC_NOW,
        "updated_at_utc": UTC_NOW,
        "closed_at_utc": None,
        "status": PositionStatus.OPEN,
    }


def _journal_kwargs() -> dict:
    """Return a complete kwargs dict for constructing a JournalEvent."""
    return {
        "journal_event_id": "4" * 64,
        "occurred_at_utc": UTC_NOW,
        "event_type": "SIGNAL_DETECTED",
        "entity_type": "SIGNAL",
        "entity_id": "b" * 64,
        "correlation_id": "5" * 64,
        "signal_id": "b" * 64,
        "trade_plan_id": None,
        "approval_id": None,
        "order_id": None,
        "position_id": None,
        "payload_json": '{"foo":"bar"}',
        "created_at_utc": UTC_NOW,
    }


def _signal_kwargs() -> dict:
    """Return a complete kwargs dict for constructing a Signal."""
    from src.domain.enums import SignalStatus

    return {
        "signal_id": "b" * 64,
        "strategy_id": "trend-pullback",
        "strategy_version": "v1.0.0",
        "parameter_set_id": "baseline-v1",
        "parameter_set_hash": "c" * 64,
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "setup_type": "pullback",
        "source_timeframe": "1h",
        "source_candle_close_utc": UTC_NOW,
        "detected_at_utc": UTC_NOW,
        "status": SignalStatus.DETECTED,
        "expires_at_utc": UTC_LATER,
        "invalidated_at_utc": None,
    }


# --------------------------------------------------------------------------- #
# Test 1 — TradePlan is frozen (mutation raises FrozenInstanceError).
# --------------------------------------------------------------------------- #


def test_trade_plan_is_frozen() -> None:
    """Beh. 1: TradePlan mutation raises FrozenInstanceError (D-01)."""
    from src.domain.trade_plan import TradePlan

    plan = TradePlan(**_trade_plan_kwargs())
    with pytest.raises(FrozenInstanceError):
        plan.status = "APPROVED"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Test 2 — TradePlan money fields reject non-Decimal construction.
# --------------------------------------------------------------------------- #


def test_trade_plan_money_fields_reject_non_decimal() -> None:
    """Beh. 2: TradePlan money fields reject non-Decimal construction.

    D-12: float is banned for exchange-sensitive values. The
    discipline tests pin the Decimal-only invariant.
    """
    from src.domain.trade_plan import TradePlan

    bad_kwargs = _trade_plan_kwargs()
    bad_kwargs["entry_min_price"] = 50000.0  # float!
    with pytest.raises((TypeError, ValueError)):
        TradePlan(**bad_kwargs)


# --------------------------------------------------------------------------- #
# Test 3 — TradePlan status is a TradePlanStatus enum.
# --------------------------------------------------------------------------- #


def test_trade_plan_status_is_enum() -> None:
    """Beh. 3: TradePlan.status is a TradePlanStatus enum (D-10)."""
    from src.domain.enums import TradePlanStatus
    from src.domain.trade_plan import TradePlan

    plan = TradePlan(**_trade_plan_kwargs())
    assert isinstance(plan.status, TradePlanStatus)
    assert plan.status == TradePlanStatus.READY


# --------------------------------------------------------------------------- #
# Test 4 — Approval is frozen.
# --------------------------------------------------------------------------- #


def test_approval_is_frozen() -> None:
    """Beh. 4: Approval mutation raises FrozenInstanceError (D-01)."""
    from src.domain.approval import Approval

    approval = Approval(**_approval_kwargs())
    with pytest.raises(FrozenInstanceError):
        approval.status = "APPROVED"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Test 5 — Approval status reads correctly with acted_at_utc left as None.
# --------------------------------------------------------------------------- #


def test_approval_status_reads_correctly_when_pending() -> None:
    """Beh. 5: Approval.status answers state alone (D-11).

    When acted_at_utc is None, status must be PENDING — never inferred
    from the nullable timestamp.
    """
    from src.domain.approval import Approval
    from src.domain.enums import ApprovalResult

    approval = Approval(**_approval_kwargs())
    assert approval.acted_at_utc is None
    assert approval.status == ApprovalResult.PENDING
    assert approval.result == ApprovalResult.PENDING


# --------------------------------------------------------------------------- #
# Test 6 — Approval action is an ApprovalAction enum.
# --------------------------------------------------------------------------- #


def test_approval_action_is_enum() -> None:
    """Beh. 6: Approval.action is an ApprovalAction enum (D-10)."""
    from src.domain.approval import Approval
    from src.domain.enums import ApprovalAction

    approval = Approval(**_approval_kwargs())
    assert isinstance(approval.action, ApprovalAction)
    assert approval.action == ApprovalAction.APPROVE


# --------------------------------------------------------------------------- #
# Test 7 — Order is frozen.
# --------------------------------------------------------------------------- #


def test_order_is_frozen() -> None:
    """Beh. 7: Order mutation raises FrozenInstanceError (D-01)."""
    from src.domain.order import Order

    order = Order(**_order_kwargs())
    with pytest.raises(FrozenInstanceError):
        order.local_status = "FILLED"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Test 8 — Order money fields reject non-Decimal construction.
# --------------------------------------------------------------------------- #


def test_order_money_fields_reject_non_decimal() -> None:
    """Beh. 8: Order money fields reject non-Decimal construction (D-12)."""
    from src.domain.order import Order

    bad_kwargs = _order_kwargs()
    bad_kwargs["quantity"] = 0.1  # float!
    with pytest.raises((TypeError, ValueError)):
        Order(**bad_kwargs)


# --------------------------------------------------------------------------- #
# Test 9 — Order local_status is an OrderStatus enum.
# --------------------------------------------------------------------------- #


def test_order_local_status_is_enum() -> None:
    """Beh. 9: Order.local_status is an OrderStatus enum (D-10)."""
    from src.domain.enums import OrderStatus
    from src.domain.order import Order

    order = Order(**_order_kwargs())
    assert isinstance(order.local_status, OrderStatus)
    assert order.local_status == OrderStatus.NEW


# --------------------------------------------------------------------------- #
# Test 10 — Order carries three independent identifier fields.
# --------------------------------------------------------------------------- #


def test_order_carries_three_independent_identifier_fields() -> None:
    """Beh. 10: Order has client_order_id, exchange_order_id, algo_client_id.

    DATA_MODEL §2.7: Binance may use different identifiers for normal
    and algo orders; the three fields must be independently stored.
    """
    from src.domain.order import Order

    order = Order(**_order_kwargs())
    assert hasattr(order, "client_order_id")
    assert hasattr(order, "exchange_order_id")
    assert hasattr(order, "algo_client_id")
    # All three are independently nullable.
    assert order.client_order_id == "client-1"
    assert order.exchange_order_id is None
    assert order.algo_client_id is None


# --------------------------------------------------------------------------- #
# Test 11 — Seven entity classes import from src.domain in one statement.
# --------------------------------------------------------------------------- #


def test_seven_entities_importable_from_src_domain() -> None:
    """Beh. 11: All seven entities import from src.domain in one statement.

    D-01: barrel re-exports keep the import graph clean for Phase 4.
    """
    from src.domain import (
        Approval,
        Fill,
        JournalEvent,
        Order,
        Position,
        Signal,
        TradePlan,
    )

    assert Signal is not None
    assert TradePlan is not None
    assert Approval is not None
    assert Order is not None
    assert Fill is not None
    assert Position is not None
    assert JournalEvent is not None


# --------------------------------------------------------------------------- #
# Test 12 — Fill is frozen and has no status attribute.
# --------------------------------------------------------------------------- #


def test_fill_is_frozen() -> None:
    """Beh. 12: Fill mutation raises FrozenInstanceError (D-01)."""
    from src.domain.fill import Fill

    fill = Fill(**_fill_kwargs())
    with pytest.raises(FrozenInstanceError):
        fill.fill_price = Decimal("99999")  # type: ignore[misc]


def test_fill_has_no_status_attribute() -> None:
    """Beh. 12b: Fill has no status attribute (fills are events, not state).

    DATA_MODEL §2.8: fills are events with no status field.
    """
    from src.domain.fill import Fill

    fill = Fill(**_fill_kwargs())
    assert not hasattr(fill, "status")


# --------------------------------------------------------------------------- #
# Test 13 — Fill money fields reject non-Decimal construction.
# --------------------------------------------------------------------------- #


def test_fill_money_fields_reject_non_decimal() -> None:
    """Beh. 13: Fill money fields reject non-Decimal construction (D-12)."""
    from src.domain.fill import Fill

    bad_kwargs = _fill_kwargs()
    bad_kwargs["fill_price"] = 50050.0  # float!
    with pytest.raises((TypeError, ValueError)):
        Fill(**bad_kwargs)


# --------------------------------------------------------------------------- #
# Test 14 — Position is frozen.
# --------------------------------------------------------------------------- #


def test_position_is_frozen() -> None:
    """Beh. 14: Position mutation raises FrozenInstanceError (D-01)."""
    from src.domain.position import Position

    position = Position(**_position_kwargs())
    with pytest.raises(FrozenInstanceError):
        position.status = "CLOSED"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Test 15 — Position status is a PositionStatus enum.
# --------------------------------------------------------------------------- #


def test_position_status_is_enum() -> None:
    """Beh. 15: Position.status is a PositionStatus enum (D-10)."""
    from src.domain.enums import PositionStatus
    from src.domain.position import Position

    position = Position(**_position_kwargs())
    assert isinstance(position.status, PositionStatus)
    assert position.status == PositionStatus.OPEN


# --------------------------------------------------------------------------- #
# Test 16 — Position money fields reject non-Decimal construction.
# --------------------------------------------------------------------------- #


def test_position_money_fields_reject_non_decimal() -> None:
    """Beh. 16: Position money fields reject non-Decimal construction (D-12)."""
    from src.domain.position import Position

    bad_kwargs = _position_kwargs()
    bad_kwargs["entry_price"] = 50050.0  # float!
    with pytest.raises((TypeError, ValueError)):
        Position(**bad_kwargs)


# --------------------------------------------------------------------------- #
# Test 17 — JournalEvent is frozen.
# --------------------------------------------------------------------------- #


def test_journal_event_is_frozen() -> None:
    """Beh. 17: JournalEvent mutation raises FrozenInstanceError (D-01)."""
    from src.domain.journal import JournalEvent

    event = JournalEvent(**_journal_kwargs())
    with pytest.raises(FrozenInstanceError):
        event.event_type = "OTHER"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Test 18 — JournalEvent with empty event_type raises at construction.
# --------------------------------------------------------------------------- #


def test_journal_event_empty_event_type_raises() -> None:
    """Beh. 18: JournalEvent with empty event_type raises at construction.

    D-10/T-03-04: validated non-empty strings with empty rejected at
    construction; Enum promotion deferred to Phase 4.
    """
    from src.domain.journal import JournalEvent

    bad_kwargs = _journal_kwargs()
    bad_kwargs["event_type"] = ""  # empty!
    with pytest.raises((TypeError, ValueError)):
        JournalEvent(**bad_kwargs)


# --------------------------------------------------------------------------- #
# Test 19 — JournalEvent with empty entity_type raises at construction.
# --------------------------------------------------------------------------- #


def test_journal_event_empty_entity_type_raises() -> None:
    """Beh. 19: JournalEvent with empty entity_type raises at construction."""
    from src.domain.journal import JournalEvent

    bad_kwargs = _journal_kwargs()
    bad_kwargs["entity_type"] = ""  # empty!
    with pytest.raises((TypeError, ValueError)):
        JournalEvent(**bad_kwargs)


# --------------------------------------------------------------------------- #
# Test 20 — All seven entities have UTC-aware datetime fields.
# --------------------------------------------------------------------------- #


def test_all_entities_reject_naive_datetimes() -> None:
    """Beh. 20: All seven entities reject naive datetimes at construction.

    D-12: UTC `datetime` internally; naive datetimes are forbidden at
    the domain boundary.
    """
    from src.domain.approval import Approval
    from src.domain.fill import Fill
    from src.domain.journal import JournalEvent
    from src.domain.order import Order
    from src.domain.position import Position
    from src.domain.signal import Signal
    from src.domain.trade_plan import TradePlan

    naive = datetime(2026, 9, 19, 0, 0)  # naive!

    # Signal (CR-02: the root identity entity must reject naive datetimes
    # at the boundary, before they reach the canonical hash).
    bad = _signal_kwargs()
    bad["source_candle_close_utc"] = naive
    with pytest.raises((TypeError, ValueError)):
        Signal(**bad)

    # TradePlan
    bad = _trade_plan_kwargs()
    bad["expiry_utc"] = naive
    with pytest.raises((TypeError, ValueError)):
        TradePlan(**bad)

    # Approval
    bad = _approval_kwargs()
    bad["requested_at_utc"] = naive
    with pytest.raises((TypeError, ValueError)):
        Approval(**bad)

    # Order
    bad = _order_kwargs()
    bad["submitted_at_utc"] = naive
    with pytest.raises((TypeError, ValueError)):
        Order(**bad)

    # Fill
    bad = _fill_kwargs()
    bad["fill_time_utc"] = naive
    with pytest.raises((TypeError, ValueError)):
        Fill(**bad)

    # Position
    bad = _position_kwargs()
    bad["opened_at_utc"] = naive
    with pytest.raises((TypeError, ValueError)):
        Position(**bad)

    # JournalEvent
    bad = _journal_kwargs()
    bad["occurred_at_utc"] = naive
    with pytest.raises((TypeError, ValueError)):
        JournalEvent(**bad)


def test_all_entities_reject_non_utc_aware_datetimes() -> None:
    """Beh. 20b: all seven entities reject non-UTC aware datetimes (WR-02).

    A `+07:00`-aware datetime passes a naive-only check but must not
    reach domain state: hashes and DB rows assume UTC.
    """
    from datetime import timedelta, timezone

    from src.domain.approval import Approval
    from src.domain.fill import Fill
    from src.domain.journal import JournalEvent
    from src.domain.order import Order
    from src.domain.position import Position
    from src.domain.signal import Signal
    from src.domain.trade_plan import TradePlan

    plus7 = timezone(timedelta(hours=7))
    non_utc = datetime(2026, 9, 19, 7, 0, tzinfo=plus7)

    bad = _signal_kwargs()
    bad["source_candle_close_utc"] = non_utc
    with pytest.raises((TypeError, ValueError)):
        Signal(**bad)

    bad = _trade_plan_kwargs()
    bad["expiry_utc"] = non_utc
    with pytest.raises((TypeError, ValueError)):
        TradePlan(**bad)

    bad = _approval_kwargs()
    bad["requested_at_utc"] = non_utc
    with pytest.raises((TypeError, ValueError)):
        Approval(**bad)

    bad = _order_kwargs()
    bad["submitted_at_utc"] = non_utc
    with pytest.raises((TypeError, ValueError)):
        Order(**bad)

    bad = _fill_kwargs()
    bad["fill_time_utc"] = non_utc
    with pytest.raises((TypeError, ValueError)):
        Fill(**bad)

    bad = _position_kwargs()
    bad["opened_at_utc"] = non_utc
    with pytest.raises((TypeError, ValueError)):
        Position(**bad)

    bad = _journal_kwargs()
    bad["occurred_at_utc"] = non_utc
    with pytest.raises((TypeError, ValueError)):
        JournalEvent(**bad)


# --------------------------------------------------------------------------- #
# Test 21 — ApprovalResult enum values match the assumed set.
# --------------------------------------------------------------------------- #


def test_approval_result_values_match_assumed_set() -> None:
    """Beh. 21: ApprovalResult enum values are PENDING, APPROVED, SKIPPED, EXPIRED.

    Per the planner assumption (D-10): ApprovalStatus maps to the
    approval result lifecycle with this value set, flagged as assumed
    until user confirmation.
    """
    from src.domain.enums import ApprovalResult

    expected = {"PENDING", "APPROVED", "SKIPPED", "EXPIRED"}
    actual = {member.value for member in ApprovalResult}
    assert actual == expected


def test_documented_string_fields_reject_empty() -> None:
    """Beh. 22: docstring-promised non-empty strings reject "" (WR-03)."""
    from src.domain.fill import Fill
    from src.domain.order import Order
    from src.domain.position import Position
    from src.domain.signal import Signal
    from src.domain.trade_plan import TradePlan

    bad = _signal_kwargs()
    bad["symbol"] = ""
    with pytest.raises((TypeError, ValueError)):
        Signal(**bad)

    bad = _trade_plan_kwargs()
    bad["entry_model"] = ""
    with pytest.raises((TypeError, ValueError)):
        TradePlan(**bad)
    bad = _trade_plan_kwargs()
    bad["quantization_decision"] = ""
    with pytest.raises((TypeError, ValueError)):
        TradePlan(**bad)

    for field in (
        "order_role",
        "side",
        "position_side",
        "order_type",
        "time_in_force",
    ):
        bad = _order_kwargs()
        bad[field] = ""
        with pytest.raises((TypeError, ValueError)):
            Order(**bad)

    bad = _fill_kwargs()
    bad["side"] = ""
    with pytest.raises((TypeError, ValueError)):
        Fill(**bad)

    bad = _position_kwargs()
    bad["position_side"] = ""
    with pytest.raises((TypeError, ValueError)):
        Position(**bad)
    bad = _position_kwargs()
    bad["mode"] = ""
    with pytest.raises((TypeError, ValueError)):
        Position(**bad)


def test_approval_rejects_incoherent_status_timestamps() -> None:
    """Beh. 23: PENDING ⟺ acted_at_utc is None (WR-07)."""
    from src.domain.approval import Approval
    from src.domain.enums import ApprovalResult

    bad = _approval_kwargs()
    bad["acted_at_utc"] = UTC_NOW
    with pytest.raises((TypeError, ValueError)):
        Approval(**bad)

    bad = _approval_kwargs()
    bad["status"] = ApprovalResult.APPROVED
    bad["result"] = ApprovalResult.APPROVED
    with pytest.raises((TypeError, ValueError)):
        Approval(**bad)

    ok = _approval_kwargs()
    ok["status"] = ApprovalResult.APPROVED
    ok["result"] = ApprovalResult.APPROVED
    ok["acted_at_utc"] = UTC_NOW
    assert Approval(**ok).acted_at_utc == UTC_NOW
