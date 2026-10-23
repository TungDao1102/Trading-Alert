"""Live risk inputs for the placement manager (Phase 21, plan 21-11; D-02, D-05, D-14 to D-16).

`execute_approved_plan` takes four values from its caller today through ``risk_kwargs``: the
account state, the open positions, the daily loss and the parameter set. This module is the one
place that assembles them out of the Phase 21 live sources:

* the live equity result (plan 21-04, Binance ``totalMarginBalance``),
* the persisted day row and the day verdict (plan 21-05),
* the counted reservations and the exchange exposures (plan 21-06).

`build_live_risk_inputs` is pure. The manager signature is unchanged; Phase 24 composes the
builder with the stores and passes ``inputs.as_risk_kwargs()`` on. Phase 21 proves the builder.

Two equities, on purpose (Pattern 3, Pitfall 8). ``account_state`` holds the CURRENT resolved
equity: it sizes the trade. ``parameter_set`` holds the thresholds resolved against the
persisted DAY-START equity: they gate the trade. The backtest does the same: it feeds
``ledger.equity`` to sizing and ``ledger.thresholds`` (resolved against ``equity_at_day_start``)
to the gates. An intraday equity change therefore cannot move a threshold.

Parity with the backtest (D-02): for equal inputs the builder gives `check_portfolio` the same
open positions and thresholds as the backtest ledger. The remaining difference is the equity
basis: the live equity is the margin balance and includes unrealized PnL, the backtest equity
is realized-only. That is the owner item O-5; this module does not hide it.

Fail closed (F-012, D-14): an unknown equity, a missing day row, an unknown day verdict, a day
mismatch, invalid thresholds or an unexplained exchange position give NO_TRADE
``UNCERTAIN_ACCOUNT_STATE`` and no inputs; a latched day gives ``DAILY_STOP_BLOCK``. No default
value is ever substituted.

Freshness contract for the caller: the ``equity`` result must be resolved with a ``now_utc``
read from the injected clock AFTER ``LiveEquitySource.refresh()`` returns. The reading is
stamped at the start of ``refresh()``; a ``now`` captured before the refresh gives a negative
age, which is stale by design (plan 21-07, D-03).

The release mappings (bottom of the file) turn every terminal plan state into one
`ReleaseReason`; the callers are Phase 24 code (see each docstring). RELEASED is terminal.

The module reads no wall clock and imports no adapter, SDK or persistence module.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core.types import AccountState
from src.domain.enums import (
    ApprovalResult,
    DailyState,
    ExecutionIntentStatus,
    RejectionReason,
    TradePlanStatus,
)
from src.execution.pre_placement import (
    PLAN_INVALIDATED_BEFORE_PLACEMENT,
    PLAN_STATUS_INVALID,
    VALIDITY_TOO_SHORT,
)
from src.execution.protection import ProtectionState
from src.risk.daily_loss import DayRiskState, DayStateVerdict, day_thresholds
from src.risk.live_equity import LiveEquityResult
from src.risk.reservations import (
    CountedReservation,
    ExchangeExposure,
    ReleaseReason,
    open_positions_from_reservations,
)
from src.risk.types import OpenPosition

_OK = "OK"
_UNCERTAIN = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
_DAILY_STOP = RejectionReason.DAILY_STOP_BLOCK.value
_FAILED_REASONS = frozenset({_UNCERTAIN, _DAILY_STOP})

# Pre-placement refusals that can never clear for the plan (plan 21-11): the plan is terminal,
# the setup is invalidated, or the remaining validity (which only shrinks with time) is too
# short. Every other refusal is not final, so its reservation stays counted.
FINAL_PLACEMENT_REFUSALS: frozenset[str] = frozenset(
    {PLAN_STATUS_INVALID, PLAN_INVALIDATED_BEFORE_PLACEMENT, VALIDITY_TOO_SHORT}
)


@dataclass(frozen=True)
class LiveRiskInputs:
    """The four values `execute_approved_plan` takes from ``risk_kwargs`` for risk."""

    account_state: AccountState
    open_positions: tuple[OpenPosition, ...]
    daily_loss_quote: Decimal
    parameter_set: dict[str, Any]

    def as_risk_kwargs(self) -> dict[str, Any]:
        """Exactly the keys account_state, open_positions, daily_loss_quote, parameter_set."""
        return {
            "account_state": self.account_state,
            "open_positions": self.open_positions,
            "daily_loss_quote": self.daily_loss_quote,
            "parameter_set": dict(self.parameter_set),
        }


@dataclass(frozen=True)
class LiveRiskInputsResult:
    """Inputs, or a fail-closed NO_TRADE reason (the `live_commission` result style).

    ``inputs`` present requires ``reason_code == "OK"``; absent requires
    UNCERTAIN_ACCOUNT_STATE or DAILY_STOP_BLOCK.
    """

    inputs: LiveRiskInputs | None
    reason_code: str

    def __post_init__(self) -> None:
        if self.inputs is None:
            if self.reason_code not in _FAILED_REASONS:
                raise ValueError(
                    "a result without inputs needs UNCERTAIN_ACCOUNT_STATE or "
                    f"DAILY_STOP_BLOCK, got {self.reason_code!r}"
                )
        elif self.reason_code != _OK:
            raise ValueError(
                f"a result with inputs requires reason_code OK, got {self.reason_code!r}"
            )

    @property
    def is_no_trade(self) -> bool:
        return self.inputs is None


def _no_trade(reason_code: str) -> LiveRiskInputsResult:
    return LiveRiskInputsResult(inputs=None, reason_code=reason_code)


def build_live_risk_inputs(
    *,
    equity: LiveEquityResult,
    day: DayRiskState | None,
    verdict: DayStateVerdict | None,
    counted: Sequence[CountedReservation],
    exchange_exposures: Sequence[ExchangeExposure],
    candidate_trade_plan_id: str,
    parameter_set: dict[str, Any],
) -> LiveRiskInputsResult:
    """Assemble the manager's risk inputs from the live sources, or fail closed.

    ``parameter_set`` is the raw registry mapping (equity-fraction rates); the returned
    ``parameter_set`` holds absolute thresholds resolved against the persisted day-start base.
    The candidate's own reservation is excluded from ``open_positions`` (D-15, Pitfall 2):
    `check_portfolio` adds the candidate's risk itself.

    Order: equity unknown; day or verdict missing; verdict for another day; latched day
    (DAILY_STOP_BLOCK); verdict without a state; invalid thresholds; unexplained exchange
    exposure; unknown loss.
    """
    if equity.is_no_trade or equity.account_state is None:
        return _no_trade(_UNCERTAIN)
    if day is None or verdict is None:
        return _no_trade(_UNCERTAIN)
    if verdict.utc_day != day.utc_day:
        return _no_trade(_UNCERTAIN)
    if verdict.state is DailyState.DAILY_STOP:
        return _no_trade(_DAILY_STOP)
    if verdict.state is None or verdict.loss_quote is None:
        return _no_trade(_UNCERTAIN)
    thresholds = day_thresholds(parameter_set=parameter_set, day=day)
    if thresholds is None:
        return _no_trade(_UNCERTAIN)
    positions = open_positions_from_reservations(
        counted=counted,
        exclude_trade_plan_id=candidate_trade_plan_id,
        exchange_exposures=exchange_exposures,
    )
    if positions is None:
        return _no_trade(_UNCERTAIN)
    return LiveRiskInputsResult(
        inputs=LiveRiskInputs(
            account_state=equity.account_state,
            open_positions=positions,
            daily_loss_quote=verdict.loss_quote,
            parameter_set=thresholds,
        ),
        reason_code=_OK,
    )


# --------------------------------------------------------------------------- #
# Release-reason mappings (D-16): one reason per terminal plan state.
# --------------------------------------------------------------------------- #


def release_reason_for_approval_status(status: ApprovalResult) -> ReleaseReason | None:
    """Release reason of an approval decision; None while it is not a no-go.

    Caller (Phase 24): the approval expiry/skip path. EXPIRED -> APPROVAL_EXPIRED; SKIPPED
    (the SKIP and the CANCEL action both decide SKIPPED) -> APPROVAL_SKIPPED; PENDING and
    APPROVED -> None. RELEASED is terminal.

    Raises:
        TypeError: `status` is not an `ApprovalResult`.
    """
    if not isinstance(status, ApprovalResult):
        raise TypeError(f"status must be ApprovalResult, got {type(status).__name__}")
    if status is ApprovalResult.EXPIRED:
        return ReleaseReason.APPROVAL_EXPIRED
    if status is ApprovalResult.SKIPPED:
        return ReleaseReason.APPROVAL_SKIPPED
    return None


def _require_aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def release_reason_for_plan(
    *, status: TradePlanStatus, expiry_utc: datetime, now_utc: datetime
) -> ReleaseReason | None:
    """Release reason of a plan that was never placed (REQUESTED or RESERVED reservations).

    Caller (Phase 24): the plan expiry/invalidation sweep over unplaced reservations. An
    executed plan stays APPROVED (D051 item i), so the store refuses a plan-status reason on a
    PLACED or OPEN row. EXPIRED, INVALIDATED and SUPERSEDED map to their reasons whatever
    `now_utc` is; otherwise `now_utc >= expiry_utc` (the inclusive boundary of
    `check_binding_full`) is PLAN_EXPIRED, which releases an approved plan that was never
    consumed; otherwise None. RELEASED is terminal.

    Raises:
        TypeError: `status` is not a `TradePlanStatus`.
        ValueError: `expiry_utc` or `now_utc` is naive.
    """
    if not isinstance(status, TradePlanStatus):
        raise TypeError(f"status must be TradePlanStatus, got {type(status).__name__}")
    expiry = _require_aware(expiry_utc, "expiry_utc")
    now = _require_aware(now_utc, "now_utc")
    if status is TradePlanStatus.EXPIRED:
        return ReleaseReason.PLAN_EXPIRED
    if status is TradePlanStatus.INVALIDATED:
        return ReleaseReason.PLAN_INVALIDATED
    if status is TradePlanStatus.SUPERSEDED:
        return ReleaseReason.PLAN_SUPERSEDED
    if now >= expiry:
        return ReleaseReason.PLAN_EXPIRED
    return None


def release_reason_for_placement_refusal(reason_code: str) -> ReleaseReason | None:
    """PLACEMENT_REFUSED for a FINAL pre-placement refusal, else None.

    Caller (Phase 24): the manager's NO_TRADE outcome before consumption. Final refusals are
    `FINAL_PLACEMENT_REFUSALS`: PLAN_STATUS_INVALID (the plan is terminal),
    PLAN_INVALIDATED_BEFORE_PLACEMENT (the setup is invalidated) and VALIDITY_TOO_SHORT
    (remaining validity only shrinks). Every other refusal is not final (an owner can set a
    NOT_CONFIGURED limit, a price can come back into the zone, SAFE_MODE can clear), so it maps
    to None and the reservation stays counted (conservative) until `release_reason_for_plan`
    returns PLAN_EXPIRED at the plan expiry (D-16 for an approved plan never consumed).

    Raises:
        TypeError: `reason_code` is not a str.
    """
    if not isinstance(reason_code, str):
        raise TypeError(f"reason_code must be str, got {type(reason_code).__name__}")
    if reason_code in FINAL_PLACEMENT_REFUSALS:
        return ReleaseReason.PLACEMENT_REFUSED
    return None


def release_reason_for_entry_intent(status: ExecutionIntentStatus) -> ReleaseReason | None:
    """ENTRY_REJECTED for a REJECTED entry intent, else None.

    Caller (Phase 24): the intent finalizer. INTENDED, SENT, ACKED and UNKNOWN stay counted:
    an UNKNOWN entry may still fill. RELEASED is terminal.

    Raises:
        TypeError: `status` is not an `ExecutionIntentStatus`.
    """
    if not isinstance(status, ExecutionIntentStatus):
        raise TypeError(f"status must be ExecutionIntentStatus, got {type(status).__name__}")
    if status is ExecutionIntentStatus.REJECTED:
        return ReleaseReason.ENTRY_REJECTED
    return None


def release_reason_for_protection_state(state: ProtectionState) -> ReleaseReason | None:
    """Release reason of a protection state.

    Caller (Phase 24): the protection coordinator. ENTRY_ENDED_NO_FILL -> ENTRY_ENDED_NO_FILL;
    FLAT -> POSITION_CLOSED; every other state (including ENTRY_UNRESOLVED and CLOSE_FAILED,
    where exposure may remain) -> None. RELEASED is terminal.

    Raises:
        TypeError: `state` is not a `ProtectionState`.
    """
    if not isinstance(state, ProtectionState):
        raise TypeError(f"state must be ProtectionState, got {type(state).__name__}")
    if state is ProtectionState.ENTRY_ENDED_NO_FILL:
        return ReleaseReason.ENTRY_ENDED_NO_FILL
    if state is ProtectionState.FLAT:
        return ReleaseReason.POSITION_CLOSED
    return None


__all__ = [
    "FINAL_PLACEMENT_REFUSALS",
    "LiveRiskInputs",
    "LiveRiskInputsResult",
    "build_live_risk_inputs",
    "release_reason_for_approval_status",
    "release_reason_for_entry_intent",
    "release_reason_for_placement_refusal",
    "release_reason_for_plan",
    "release_reason_for_protection_state",
]
