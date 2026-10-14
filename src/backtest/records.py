"""Trade records, ledger bookings and the record builder (Phase 14, plan 14-01).

`TradeRecord` moves here unchanged (its first 26 fields keep name, type and order)
and gains trailing defaulted v2 fields: the signal close, the planned quantity, the
TP1 leg, the resolution time, per-plan counters and flags. `src.backtest.simulator`
re-exports it so every analytics and adapter import keeps working.

`booking_for_event` and `build_trade_record` sum the same per-leg numbers, so the
simulated ledger bookings and the record can never disagree:

    realized_pnl = gross_pnl - entry_fee - exit_fee - slippage_amount + funding_amount

`funding_amount` is the signed D-14 funding PnL (positive means received). The R
denominator comes from the single function `realized_risk_for_fill` (D-20). A
built record is validated before it leaves the builder (D-23).

The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/
SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only,
mirroring the Phase-4 D-10 / Phase-5 D-05 purity precedent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core._decimal import _add, _mul, _sub
from src.domain.canonical import sha256_hex
from src.domain.enums import RejectionReason
from src.risk.realized_risk import realized_risk_for_fill

from .costs import CostModel
from .lifecycle import (
    EVENT_CANCEL,
    EVENT_EXIT,
    EVENT_FILL,
    EVENT_PENDING,
    EVENT_TP1,
    PHASE_CLOSED,
    LifecycleEvent,
    PlanState,
)
from .semantics import (
    ENTRY_KINDS,
    EXIT_KINDS,
    EXIT_SETTLEMENT,
    EXIT_TP2,
    REJECT,
    SIMULATOR_SEMANTICS_VERSION,
)
from .validator import validate_trade_record

BOOKING_FILL = "FILL"
BOOKING_TP1 = "TP1"
BOOKING_EXIT = "EXIT"
# A cancel or a pending-at-data-end changes no cash: it books a zero amount at its own time.
BOOKING_CANCEL = "CANCEL"
BOOKING_PENDING = "PENDING"
# A funding payment books at its own fundingTime, between the fill and the exit.
BOOKING_FUNDING = "FUNDING"


@dataclass(frozen=True)
class TradeRecord:
    """One trade outcome emitted by the simulator.

    `entry_kind` is one of the `ENTRY_KINDS` of `src/backtest/semantics.py`
    ("ENTRY_FILLED", "PARTIAL_FILL", "EXPIRED", "INVALIDATION_CANCEL",
    "DAILY_STOP_CANCEL", "PENDING_AT_DATA_END", "REJECT", "SETTLEMENT_CANCEL") or, on
    records produced by the v1 simulator, "TOUCH_NO_FILL". `exit_kind` is one of "SL", "TP2",
    "END_OF_DATA", "SETTLEMENT" (v1: "SL", "TP1", "EOD") or None if the trade never filled.
    `outcome_kind` is "OK" for plans that ran their course and "REJECT" for
    risk-rejected plans.

    The trailing fields are the v2 additions (all defaulted so v1 construction keeps
    working): `signal_close_utc` (the close of the strategy bar that created the plan),
    `planned_quantity` (the sized quantity; `quantity` is what filled), the TP1 leg,
    `resolved_at_utc` (when the plan reached its terminal state), the
    `touch_no_fill_count` counter, the `gap_through_stop` and `constraints_extrapolated`
    flags, the signal `regime` and the number of funding events charged.
    """

    trade_id: str
    signal_id: str | None
    trade_plan_id: str | None
    strategy_version: str
    parameter_set_hash: str
    symbol: str
    direction: str
    entry_kind: str
    entry_price: Decimal | None
    entry_time_utc: datetime | None
    quantity: Decimal | None
    exit_kind: str | None
    exit_price: Decimal | None
    exit_time_utc: datetime | None
    realized_pnl: Decimal | None
    realized_risk: Decimal | None
    gross_pnl: Decimal | None
    entry_fee: Decimal | None
    exit_fee: Decimal | None
    funding_amount: Decimal | None
    slippage_amount: Decimal | None
    modeled_costs_per_unit: Decimal | None
    coverage_note: str | None
    fallback_applied: bool
    outcome_kind: str  # "OK" | "REJECT"
    reason_code: str  # canonical RejectionReason value or "OK"
    # --- v2 trailing fields (Phase 14, plan 14-01) ---
    signal_close_utc: datetime | None = None
    planned_quantity: Decimal | None = None
    tp1_quantity: Decimal | None = None
    tp1_price: Decimal | None = None
    tp1_time_utc: datetime | None = None
    resolved_at_utc: datetime | None = None
    touch_no_fill_count: int = 0
    gap_through_stop: bool = False
    constraints_extrapolated: bool = False
    regime: str | None = None
    funding_event_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Project to a canonical-JSON-safe dict for hashing."""
        out: dict[str, Any] = {}
        for k, v in self.__dict__.items():
            if isinstance(v, Decimal):
                out[k] = str(v)
            elif isinstance(v, datetime):
                out[k] = v.isoformat()
            else:
                out[k] = v
        return out


@dataclass(frozen=True)
class Booking:
    """One dated ledger booking of a lifecycle event (quote currency, signed)."""

    time_utc: datetime
    symbol: str
    trade_plan_id: str
    amount: Decimal
    kind: str


def _exit_slippage_rate(exit_kind: str | None, cost_model: CostModel) -> Decimal:
    """Slippage rate of a final exit leg: stop-style exits are worse than a resting limit.

    SL (a stop-market order) and END_OF_DATA (a forced market close, D046) use
    `exit_slippage_rate`; TP2 (a resting limit) uses `expected_slippage` (D-10). The TP1
    partial is not a final exit and takes `expected_slippage` directly. SETTLEMENT (a position
    closed at the declared terminal instant at a recorded bound, quick 261014-nnl) carries no
    slippage: the bound is the price, so no further adverse move is modeled on top of it. Both
    `booking_for_event` and `build_trade_record` reach this rule, so ledger and record agree.
    """
    if exit_kind not in EXIT_KINDS:
        raise ValueError(f"unknown exit_kind {exit_kind!r}: expected one of {sorted(EXIT_KINDS)}")
    if exit_kind == EXIT_SETTLEMENT:
        return Decimal("0")
    if exit_kind == EXIT_TP2:
        return cost_model.expected_slippage
    if cost_model.exit_slippage_rate is None:
        raise ValueError(
            "exit_slippage_rate is missing from the cost model: legacy 7-key "
            "models cannot book stop-exit slippage; use baseline-v5 or later"
        )
    return cost_model.exit_slippage_rate


def _gross(direction: str, entry_price: Decimal, exit_price: Decimal, quantity: Decimal) -> Decimal:
    if direction == "LONG":
        return _mul(_sub(exit_price, entry_price), quantity)
    return _mul(_sub(entry_price, exit_price), quantity)


def _entry_leg_cost(
    entry_price: Decimal, quantity: Decimal, cost_model: CostModel
) -> tuple[Decimal, Decimal]:
    """Return `(entry_fee, entry_slippage)` = `price x quantity x rate` (F-306)."""
    notional = _mul(entry_price, quantity)
    return (
        _mul(notional, cost_model.fee_rate_entry),
        _mul(notional, cost_model.expected_slippage),
    )


def _exit_leg_cost(
    exit_price: Decimal, quantity: Decimal, slippage_rate: Decimal, cost_model: CostModel
) -> tuple[Decimal, Decimal]:
    """Return `(exit_fee, exit_slippage)` of one exit leg at `slippage_rate`."""
    notional = _mul(exit_price, quantity)
    return (_mul(notional, cost_model.fee_rate_exit), _mul(notional, slippage_rate))


def _tp1_leg_cost(
    price: Decimal, quantity: Decimal, cost_model: CostModel
) -> tuple[Decimal, Decimal]:
    """Cost of the TP1 partial: a resting take-profit, so `expected_slippage` (D-10)."""
    return _exit_leg_cost(price, quantity, cost_model.expected_slippage, cost_model)


def _final_leg_cost(
    price: Decimal, quantity: Decimal, exit_kind: str | None, cost_model: CostModel
) -> tuple[Decimal, Decimal]:
    """Cost of the final leg of kind SL, TP2, END_OF_DATA or SETTLEMENT (anything else raises)."""
    return _exit_leg_cost(price, quantity, _exit_slippage_rate(exit_kind, cost_model), cost_model)


def booking_for_event(event: LifecycleEvent, *, state: PlanState, cost_model: CostModel) -> Booking:
    """Book one lifecycle event as a dated, signed ledger amount (D-18).

    CANCEL and PENDING events book a zero amount at their own time. FILL books minus the
    entry fee and entry slippage at the fill time. TP1 books the
    partial leg (gross on the TP1 quantity minus exit fee and `expected_slippage`
    slippage). EXIT books the final-leg gross PnL minus the exit fee and exit slippage at
    the exit time; SL and END_OF_DATA exits use `exit_slippage_rate`, TP2 uses
    `expected_slippage` (D-10) and SETTLEMENT uses zero slippage. Other event kinds raise
    `ValueError`.
    """
    if event.kind in (EVENT_CANCEL, EVENT_PENDING):
        return Booking(
            time_utc=event.time_utc,
            symbol=event.symbol,
            trade_plan_id=event.trade_plan_id,
            amount=Decimal("0"),
            kind=BOOKING_CANCEL if event.kind == EVENT_CANCEL else BOOKING_PENDING,
        )
    if event.price is None or event.quantity is None:
        raise ValueError(f"{event.kind} event needs a price and a quantity to be booked")
    if event.kind == EVENT_FILL:
        entry_fee, entry_slippage = _entry_leg_cost(event.price, event.quantity, cost_model)
        amount = _sub(Decimal("0"), _add(entry_fee, entry_slippage))
        return Booking(
            time_utc=event.time_utc,
            symbol=event.symbol,
            trade_plan_id=event.trade_plan_id,
            amount=amount,
            kind=BOOKING_FILL,
        )
    if event.kind in (EVENT_EXIT, EVENT_TP1):
        if state.entry_price is None:
            raise ValueError(f"{event.kind} event on a state that never filled")
        is_tp1 = event.kind == EVENT_TP1
        gross = _gross(state.direction, state.entry_price, event.price, event.quantity)
        if is_tp1:
            exit_fee, exit_slippage = _tp1_leg_cost(event.price, event.quantity, cost_model)
        else:
            exit_fee, exit_slippage = _final_leg_cost(
                event.price, event.quantity, event.exit_kind, cost_model
            )
        amount = _sub(_sub(gross, exit_fee), exit_slippage)
        return Booking(
            time_utc=event.time_utc,
            symbol=event.symbol,
            trade_plan_id=event.trade_plan_id,
            amount=amount,
            kind=BOOKING_TP1 if is_tp1 else BOOKING_EXIT,
        )
    raise ValueError(f"cannot book a {event.kind} event")


def _trade_id(
    *,
    state: PlanState,
    quantity: Decimal | None,
    outcome_kind: str,
    reason_code: str,
) -> str:
    """Deterministic id bound to the semantics version and every identifying field."""
    payload = {
        "simulator_semantics_version": SIMULATOR_SEMANTICS_VERSION,
        "trade_plan_id": state.plan.trade_plan_id,
        "symbol": state.symbol,
        "signal_close_utc": state.signal_close_utc,
        "entry_kind": state.entry_kind,
        "entry_time_utc": state.entry_time_utc,
        "quantity": quantity,
        "exit_kind": state.exit_kind,
        "exit_time_utc": state.exit_time_utc,
        "outcome_kind": outcome_kind,
        "reason_code": reason_code,
    }
    return sha256_hex(payload)


def build_trade_record(
    *,
    state: PlanState,
    strategy_version: str,
    parameter_set_hash: str,
    cost_model: CostModel,
    funding_amount: Decimal,
    funding_event_count: int,
    regime: str | None,
    constraints_extrapolated: bool,
) -> TradeRecord:
    """Build and validate the terminal `TradeRecord` of a CLOSED plan state.

    A filled state yields a costed record whose `realized_pnl` is
    `gross_pnl - entry_fee - exit_fee - slippage_amount + funding_amount` and whose
    `realized_risk` comes from `realized_risk_for_fill` (D-20). A plan that never
    filled yields a record with every trade field `None`. The record is validated
    (D-23) before it is returned, so an invalid record can never leave the builder.

    Raises:
        ValueError: the state is not terminal, the entry kind is unknown, or the exit
            kind is not one of `EXIT_KINDS`.
        TradeRecordInvariantError: the built record violates a temporal invariant.
    """
    if state.phase != PHASE_CLOSED:
        raise ValueError(f"build_trade_record needs a CLOSED state, got phase {state.phase!r}")
    if state.entry_kind not in ENTRY_KINDS:
        raise ValueError(
            f"unknown entry_kind {state.entry_kind!r}: expected one of {sorted(ENTRY_KINDS)}"
        )
    if not isinstance(funding_amount, Decimal):
        raise TypeError(f"funding_amount must be Decimal, got {type(funding_amount).__name__}")
    if funding_event_count < 0:
        raise ValueError(f"funding_event_count must be >= 0, got {funding_event_count}")

    common: dict[str, Any] = {
        "signal_id": state.plan.signal_id,
        "trade_plan_id": state.plan.trade_plan_id,
        "strategy_version": strategy_version,
        "parameter_set_hash": parameter_set_hash,
        "symbol": state.symbol,
        "direction": state.direction,
        "entry_kind": state.entry_kind,
        "modeled_costs_per_unit": None,
        "coverage_note": state.coverage_note,
        "fallback_applied": state.fallback_applied,
        "outcome_kind": "OK",
        "reason_code": "OK",
        "signal_close_utc": state.signal_close_utc,
        "planned_quantity": state.planned_quantity,
        "resolved_at_utc": state.resolved_at_utc,
        "touch_no_fill_count": state.touch_no_fill_count,
        "constraints_extrapolated": constraints_extrapolated,
        "regime": regime,
    }

    if state.entry_time_utc is None or state.entry_price is None:
        record = TradeRecord(
            trade_id=_trade_id(state=state, quantity=None, outcome_kind="OK", reason_code="OK"),
            entry_price=None,
            entry_time_utc=None,
            quantity=None,
            exit_kind=None,
            exit_price=None,
            exit_time_utc=None,
            realized_pnl=None,
            realized_risk=None,
            gross_pnl=None,
            entry_fee=None,
            exit_fee=None,
            funding_amount=None,
            slippage_amount=None,
            **common,
        )
        validate_trade_record(record, strict=True)
        return record

    if state.exit_price is None or state.exit_time_utc is None:
        raise ValueError("a filled CLOSED state needs an exit price and an exit time")
    quantity = state.fill_quantity
    entry_fee, entry_slippage = _entry_leg_cost(state.entry_price, quantity, cost_model)
    # Per-leg booking: the TP1 partial (when it happened) and the final leg on the remainder
    # are costed separately and summed, exactly as `booking_for_event` books them.
    tp1_quantity = state.tp1_quantity
    if tp1_quantity is None:
        final_quantity = quantity
        gross = _gross(state.direction, state.entry_price, state.exit_price, final_quantity)
        exit_fee, exit_slippage = _final_leg_cost(
            state.exit_price, final_quantity, state.exit_kind, cost_model
        )
    else:
        if state.tp1_price is None or state.tp1_time_utc is None:
            raise ValueError("a TP1 leg needs its price and time on the state")
        final_quantity = _sub(quantity, tp1_quantity)
        tp1_fee, tp1_slippage = _tp1_leg_cost(state.tp1_price, tp1_quantity, cost_model)
        final_fee, final_slippage = _final_leg_cost(
            state.exit_price, final_quantity, state.exit_kind, cost_model
        )
        gross = _add(
            _gross(state.direction, state.entry_price, state.tp1_price, tp1_quantity),
            _gross(state.direction, state.entry_price, state.exit_price, final_quantity),
        )
        exit_fee = _add(tp1_fee, final_fee)
        exit_slippage = _add(tp1_slippage, final_slippage)
    slippage = _add(entry_slippage, exit_slippage)
    realized_pnl = _add(_sub(_sub(_sub(gross, entry_fee), exit_fee), slippage), funding_amount)
    realized_risk = realized_risk_for_fill(
        sized_realized_risk=state.sized_realized_risk,
        planned_quantity=state.planned_quantity,
        filled_quantity=quantity,
    )
    record = TradeRecord(
        trade_id=_trade_id(state=state, quantity=quantity, outcome_kind="OK", reason_code="OK"),
        entry_price=state.entry_price,
        entry_time_utc=state.entry_time_utc,
        quantity=quantity,
        exit_kind=state.exit_kind,
        exit_price=state.exit_price,
        exit_time_utc=state.exit_time_utc,
        realized_pnl=realized_pnl,
        realized_risk=realized_risk,
        gross_pnl=gross,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        funding_amount=funding_amount,
        slippage_amount=slippage,
        tp1_quantity=state.tp1_quantity,
        tp1_price=state.tp1_price,
        tp1_time_utc=state.tp1_time_utc,
        gap_through_stop=state.gap_through_stop,
        funding_event_count=funding_event_count,
        **common,
    )
    validate_trade_record(record, strict=True)
    return record


_REJECT_REASONS = frozenset(reason.value for reason in RejectionReason)


def build_reject_record(
    *,
    signal_id: str | None,
    trade_plan_id: str | None,
    symbol: str,
    direction: str,
    reason_code: str,
    bar_close_utc: datetime,
    strategy_version: str,
    parameter_set_hash: str,
    modeled_costs_per_unit: Decimal | None = None,
    constraints_extrapolated: bool = False,
    regime: str | None = None,
) -> TradeRecord:
    """Build the REJECT record of a plan the planner, risk gates or protective sizing refused.

    A reject never rests and never fills: `outcome_kind` and `entry_kind` are "REJECT" and
    every trade field is `None`. `reason_code` must be a canonical `RejectionReason` value
    (a skipped re-signal is a summary counter, never a reject record, D-32). The id is
    bound to the semantics version, the signal, the symbol, the reason and the bar close,
    so a v1 reject can never collide with a v2 one.

    Raises:
        ValueError: `reason_code` is not a `RejectionReason` value.
        TradeRecordInvariantError: the built record violates a temporal invariant.
    """
    if reason_code not in _REJECT_REASONS:
        raise ValueError(
            f"reason_code {reason_code!r} is not a RejectionReason value: "
            "a skipped setup is counted in the run summary, not recorded as a reject"
        )
    payload = {
        "simulator_semantics_version": SIMULATOR_SEMANTICS_VERSION,
        "signal_id": signal_id,
        "symbol": symbol,
        "reason_code": reason_code,
        "bar_close_utc": bar_close_utc,
    }
    record = TradeRecord(
        trade_id=sha256_hex(payload),
        signal_id=signal_id,
        trade_plan_id=trade_plan_id,
        strategy_version=strategy_version,
        parameter_set_hash=parameter_set_hash,
        symbol=symbol,
        direction=direction,
        entry_kind=REJECT,
        entry_price=None,
        entry_time_utc=None,
        quantity=None,
        exit_kind=None,
        exit_price=None,
        exit_time_utc=None,
        realized_pnl=None,
        realized_risk=None,
        gross_pnl=None,
        entry_fee=None,
        exit_fee=None,
        funding_amount=None,
        slippage_amount=None,
        modeled_costs_per_unit=modeled_costs_per_unit,
        coverage_note=None,
        fallback_applied=False,
        outcome_kind=REJECT,
        reason_code=reason_code,
        signal_close_utc=bar_close_utc,
        resolved_at_utc=bar_close_utc,
        constraints_extrapolated=constraints_extrapolated,
        regime=regime,
    )
    validate_trade_record(record, strict=True)
    return record


__all__ = [
    "BOOKING_CANCEL",
    "BOOKING_EXIT",
    "BOOKING_FILL",
    "BOOKING_FUNDING",
    "BOOKING_PENDING",
    "BOOKING_TP1",
    "Booking",
    "TradeRecord",
    "booking_for_event",
    "build_reject_record",
    "build_trade_record",
]
