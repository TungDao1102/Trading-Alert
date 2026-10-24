"""The live inputs the execution manager needs beyond the approval (Phase 19, plan 19-13).

`execute_approved_plan` binds the approved plan to the symbol, side and size that reach the
exchange (D-01..D-04, APRV-01), refuses while the owner's execution limits are unset (D-07,
D-13) and runs the pre-placement checks (D-05..D-09, D-11, D-14, RISK-04). Those gates need
values the Phase 9 signature never carried: the persisted `Signal`, the per-plan constraint
snapshot, the execution limits, the protection registry, the latest closed strategy-bar close,
the GTD clock margin, the TP1 fraction and the injected clock that times the live mark-price
read. `LivePlacementContext` bundles them into ONE required keyword so the signature churns once
and `_GATE_KWARG_KEYS` stays exactly as it was.

The dataclass is pure: it validates types and ranges and holds no number of its own. Every field
is keyword-only and every number-bearing field is required with no default (a default would be a
hidden decision), and the caller supplies the numbers: the limits come from the committed limits
file, the margin from the ratified drift limits, the fraction from the frozen backtest constant.
The one optional field is `alert_sink` (plan 20-22): no sink means no alert, never a changed flow.

Phase 22 (plan 22-15) adds the REQUIRED keyword `margin_guard`: the pre-entry margin guard
(`MarginGuardPort`, an object with an async `evaluate`) that `execute_approved_plan` calls at gate
5f2. The guard may mutate an account configuration (margin type, leverage), so it is reached only
after the enablement, limits and SAFE_MODE gates and never while live placement is disabled. It has
no `None` default that would skip the checks (the CR-07 rule stated in the manager docstring); the
four owner limits above are unchanged.

Recorded, not decided: Q6 - the latest closed bar close is injected (its producer is Phase 24);
`None` means "not available" and the invalidation check refuses it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.domain.signal import Signal
from src.execution.constraint_snapshot import PlanConstraintSnapshot
from src.execution.execution_limits import ExecutionLimits
from src.execution.margin_guard import MarginGuardPort
from src.execution.protection import ProtectionRegistry

_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass(frozen=True, kw_only=True)
class LivePlacementContext:
    """Everything `execute_approved_plan` needs beyond the approval, the plan and the risk inputs.

    Attributes:
        signal: The persisted Signal the plan was built from. Symbol and direction come from it
            (the TradePlan has neither field, research F2).
        plan_constraint_snapshot: The per-plan exchange constraints; its symbol and trade plan id
            are cross-checked by the binding and its working type must be MARK_PRICE.
        execution_limits: The four owner limits; any NOT_CONFIGURED value refuses the placement.
        protection_registry: The fill-driven protection coordinator's registry view;
            `blocks_new_entries()` feeds the account-wide unprotected-position check.
        latest_closed_bar_close: The latest closed strategy-bar close for the invalidation rule,
            or `None` when it is not available (the invalidation check then refuses).
        gtd_clock_margin: The drift margin added to the exchange's 600 second `goodTillDate` floor.
            The same ratified drift bound is the most a mark-price reading may be stamped ahead
            of `clock` (Binance's clock vs the local one) before it refuses as future-dated.
        tp1_quantity_fraction: The TP1 share of the position, in (0, 1].
        clock: The injected aware-UTC clock. The manager reads it AFTER the gate 5e live reads,
            so the mark-price age is measured at the placement instant, never against the
            `now_utc` taken before the read (19-REVIEW CR-01). The manager itself reads no
            wall clock.
        margin_guard: The Phase 22 pre-entry margin guard (a `MarginGuardPort`). REQUIRED: the
            manager awaits `margin_guard.evaluate(...)` at gate 5f2, after the position mode and
            before the approval is consumed. A pass supplies the exchange-verified margin type,
            leverage and equity for the in-memory plan snapshot; a refusal is NO_TRADE.
        alert_sink: Optional operator-alert sink with the `JournalFirstAlertSink.alert(...)` call
            shape. `execute_approved_plan` uses it only to alert a duplicate execution attempt
            (D-23); `None` sends nothing. A failing sink never changes the outcome.
    """

    signal: Signal
    plan_constraint_snapshot: PlanConstraintSnapshot
    execution_limits: ExecutionLimits
    protection_registry: ProtectionRegistry
    latest_closed_bar_close: Decimal | None
    gtd_clock_margin: timedelta
    tp1_quantity_fraction: Decimal
    clock: Callable[[], datetime]
    margin_guard: MarginGuardPort
    alert_sink: Any | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.signal, Signal):
            raise TypeError("signal must be a Signal")
        if not isinstance(self.plan_constraint_snapshot, PlanConstraintSnapshot):
            raise TypeError("plan_constraint_snapshot must be a PlanConstraintSnapshot")
        if not isinstance(self.execution_limits, ExecutionLimits):
            raise TypeError("execution_limits must be ExecutionLimits")
        if not callable(getattr(self.protection_registry, "blocks_new_entries", None)):
            raise TypeError("protection_registry must provide blocks_new_entries()")
        bar_close = self.latest_closed_bar_close
        if bar_close is not None:
            if not isinstance(bar_close, Decimal):
                raise TypeError("latest_closed_bar_close must be Decimal or None")
            if not bar_close.is_finite() or bar_close <= _ZERO:
                raise ValueError("latest_closed_bar_close must be finite and positive")
        if not isinstance(self.gtd_clock_margin, timedelta):
            raise TypeError("gtd_clock_margin must be a timedelta")
        if self.gtd_clock_margin < timedelta(0):
            raise ValueError("gtd_clock_margin must be >= 0")
        fraction = self.tp1_quantity_fraction
        if not isinstance(fraction, Decimal):
            raise TypeError("tp1_quantity_fraction must be Decimal")
        if not fraction.is_finite() or fraction <= _ZERO or fraction > _ONE:
            raise ValueError("tp1_quantity_fraction must be in (0, 1]")
        if not callable(self.clock):
            raise TypeError("clock must be a callable returning an aware UTC datetime")
        if not callable(getattr(self.margin_guard, "evaluate", None)):
            raise TypeError("margin_guard must provide an async evaluate(request)")
        if self.alert_sink is not None and not callable(getattr(self.alert_sink, "alert", None)):
            raise TypeError("alert_sink must provide alert(...) or be None")


__all__ = ["LivePlacementContext"]
