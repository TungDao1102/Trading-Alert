"""SHADOW paper ledger over the Phase 14 simulated ledger (Phase 16, plan 16-23, D-17, REV-07).

The paper loop never had a ledger (G4-010, D052 item i): every risk verdict saw an empty account.
`ShadowLedger` gives the SHADOW loop the state the backtest sizes against, so a multi-signal
history is sized against simulated positions and the simulated daily loss exactly as the engine
sizes it. It CALLS `src.backtest.ledger` (`Ledger.start`, `apply_booking`, `roll_to`,
`register_exposure`, `update_exposure`, `remove_exposure`, `open_positions_for_risk`,
`daily_loss_quote`) and never copies a rule of it; `src/backtest` is unchanged.

Equity rule (REV-07, D063 item 5): the initial equity is a required keyword input with no default
and this module holds no numeric equity literal. Paper initial equity equals the exact intended
initial live equity and is never chosen to reduce quantization rejections or to raise the trade
count; the value is set by the user in plan 16-34, never here.

Exposure timing: `register` registers the plan's sized realized risk when it is called, which is
what the engine does at signal time (`_size_and_register`). WHEN a plan that waits for APPROVE or
CONFIRM is registered and when a human decision releases it is the user's Q-C decision (plan
16-23, task 2); the lifecycle-driven updates (`apply_event`: fill, TP1, exit, cancel) follow the
engine exactly and do not depend on it.

Pure and deterministic: stdlib, Decimal and the Phase 14 ledger only; no clock (every instant is
an argument), no I/O, no float.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.backtest.ledger import (
    Ledger,
    apply_booking,
    daily_loss_quote,
    open_positions_for_risk,
    register_exposure,
    remove_exposure,
    roll_to,
    update_exposure,
)
from src.backtest.lifecycle import (
    EVENT_FILL,
    EVENT_TP1,
    LifecycleEvent,
    PlanState,
)
from src.backtest.records import Booking
from src.backtest.semantics import NO_TRADE_CONFLICT
from src.core._decimal import _sub
from src.risk.realized_risk import realized_risk_for_fill
from src.risk.types import OpenPosition

_OK = "OK"


@dataclass(frozen=True)
class RegisterResult:
    """Whether a plan could be registered, and the engine label when it could not."""

    registered: bool
    reason_code: str


class ShadowLedger:
    """The simulated account of the SHADOW loop (one instance per paper epoch).

    `initial_equity` is a required `Decimal` input: it has no default and no illustration value.
    `parameter_set_params` is the raw parameter-set mapping the Phase 14 ledger resolves its
    absolute thresholds from, and `started_at_utc` the UTC instant that opens day 1.
    """

    def __init__(
        self,
        *,
        initial_equity: Decimal,
        parameter_set_params: Mapping[str, Any],
        started_at_utc: datetime,
    ) -> None:
        self._ledger = Ledger.start(
            equity=initial_equity,
            parameter_set_params=dict(parameter_set_params),
            at_utc=started_at_utc,
        )
        # Quantity still carried per registered plan (the engine's `exposure_remaining`).
        self._remaining: dict[str, Decimal] = {}

    # ------------------------------------------------------------------ views

    @property
    def ledger(self) -> Ledger:
        """The current Phase 14 ledger value (immutable)."""
        return self._ledger

    @property
    def equity(self) -> Decimal:
        return self._ledger.equity

    @property
    def initial_equity(self) -> Decimal:
        return self._ledger.initial_equity

    def holds_symbol(self, symbol: str) -> bool:
        """True when a plan or position of `symbol` is registered (one active plan per symbol)."""
        return any(e.symbol == symbol for e in self._ledger.exposures)

    # ------------------------------------------------------------------ register

    def register(self, state: PlanState) -> RegisterResult:
        """Register a plan's sized realized risk, unless its symbol already holds one.

        One active plan or position per symbol (D-32): a second plan is refused with the
        engine's own label `CONFLICT_WITH_OPEN_POSITION` and nothing changes.
        """
        if self.holds_symbol(state.symbol):
            return RegisterResult(registered=False, reason_code=NO_TRADE_CONFLICT)
        plan_id = state.plan.trade_plan_id
        self._ledger = register_exposure(
            self._ledger,
            trade_plan_id=plan_id,
            symbol=state.symbol,
            position_side=state.direction,
            open_risk=state.sized_realized_risk,
        )
        self._remaining[plan_id] = state.planned_quantity
        return RegisterResult(registered=True, reason_code=_OK)

    # ------------------------------------------------------------------ bookings and events

    def apply(self, booking: Booking) -> None:
        """Book one dated amount (non-decreasing time order, as the Phase 14 ledger requires)."""
        self._ledger = apply_booking(self._ledger, booking)

    def apply_event(self, event: LifecycleEvent, *, start_state: PlanState) -> None:
        """Keep the exposure in step with a lifecycle event, as the engine does (D-18, D035).

        `start_state` is the plan state before the event. A FILL of a reduced quantity re-registers
        the exposure with the risk scaled to the filled share; a TP1 scales it to the remaining
        quantity; EXIT, CANCEL and PENDING release it.
        """
        plan_id = start_state.plan.trade_plan_id
        if event.kind == EVENT_FILL:
            if event.quantity is None:
                raise ValueError("a FILL event needs a quantity")
            self._remaining[plan_id] = event.quantity
            if start_state.fill_quantity != start_state.planned_quantity:
                scaled = realized_risk_for_fill(
                    sized_realized_risk=start_state.sized_realized_risk,
                    planned_quantity=start_state.planned_quantity,
                    filled_quantity=start_state.fill_quantity,
                )
                self._ledger = remove_exposure(self._ledger, trade_plan_id=plan_id)
                self._ledger = register_exposure(
                    self._ledger,
                    trade_plan_id=plan_id,
                    symbol=start_state.symbol,
                    position_side=start_state.direction,
                    open_risk=scaled,
                )
        elif event.kind == EVENT_TP1:
            if event.quantity is None:
                raise ValueError("a TP1 event needs a quantity")
            remaining = _sub(self._remaining[plan_id], event.quantity)
            self._remaining[plan_id] = remaining
            self._ledger = update_exposure(
                self._ledger,
                trade_plan_id=plan_id,
                filled_quantity=start_state.fill_quantity,
                remaining_quantity=remaining,
            )
        else:  # EXIT, CANCEL, PENDING: the plan no longer carries risk
            self._ledger = remove_exposure(self._ledger, trade_plan_id=plan_id)
            self._remaining.pop(plan_id, None)

    # ------------------------------------------------------------------ risk inputs

    def risk_inputs(self, now_utc: datetime) -> tuple[list[OpenPosition], Decimal]:
        """`(open_positions, daily_loss_quote)` for the next risk verdict at `now_utc`.

        Rolls the ledger to the UTC day of `now_utc` first, as the engine does before it
        evaluates a signal (day PnL resets, thresholds re-resolve against the day-start equity).
        """
        self._ledger = roll_to(self._ledger, now_utc)
        return open_positions_for_risk(self._ledger), daily_loss_quote(self._ledger)


__all__ = ["RegisterResult", "ShadowLedger"]
