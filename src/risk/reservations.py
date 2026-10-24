"""Portfolio-cap reservations: the pure inputs of the cap gate (Phase 21, plan 21-06).

Decisions D-15, D-16, D-17. The portfolio caps (max open positions, aggregate open risk, cluster
cap) must count every plan that holds risk, not only the filled positions: an approved plan that
is not yet placed and a resting entry hold risk too. Each plan owns ONE reservation row for its
whole life:

    REQUESTED  issued, not counted
    RESERVED   approved, counted
    PLACED     entry consumed and sent, counted
    OPEN       filled, counted
    RELEASED   terminal, not counted

RELEASED is reachable from every other status through `RELEASE_SOURCE_STATUSES`, so no counted
reservation is left without an exit (D-16). The reserved amount is `SizedResult.realized_risk`
(the sized risk after rounding), never the risk budget (Pitfall 9).

This module is pure: it reads no clock, builds no float and imports only the stdlib, `src.domain`,
`src.core` and `src.risk`. Locking and persistence are plan 21-12, the approval transaction is
plan 21-15, the release job is wired in Phase 24. `reservation_verdict` reuses `check_portfolio`
so the gate order and the reason codes are the ones backtest and paper use.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any

from src.domain.enums import DailyState, Direction, QuantizationDecision, RejectionReason
from src.risk.portfolio import check_portfolio
from src.risk.types import OpenPosition, PortfolioVerdict, SizedResult

_SIDES = frozenset({d.value for d in Direction})
_PLAN_HASH = re.compile(r"[0-9a-f]{64}")


class ReservationStatus(str, Enum):
    """The lifecycle status of a reservation row (the CHECK of migration 0011 copies these)."""

    REQUESTED = "REQUESTED"
    RESERVED = "RESERVED"
    PLACED = "PLACED"
    OPEN = "OPEN"
    RELEASED = "RELEASED"


# The statuses the caps count. REQUESTED is issued but not approved; RELEASED is terminal.
COUNTED_STATUSES: frozenset[ReservationStatus] = frozenset(
    {ReservationStatus.RESERVED, ReservationStatus.PLACED, ReservationStatus.OPEN}
)


class ReleaseReason(str, Enum):
    """Why a reservation was released: one reason per terminal plan state (D-16).

    The values are copied by the CHECK of migration 0011 (plan 21-12). The permitted source
    statuses of each reason are in `RELEASE_SOURCE_STATUSES`.
    """

    # The approval decision: SKIP / CANCEL / EXPIRE of a PENDING approval, released in the
    # approval transaction of plan 21-15.
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVAL_SKIPPED = "APPROVAL_SKIPPED"
    # TradePlanStatus terminal states of a plan that was never placed. PLAN_EXPIRED also covers
    # an APPROVED plan whose expiry passed without its approval being consumed (the status
    # mapping is plan 21-11).
    PLAN_EXPIRED = "PLAN_EXPIRED"
    PLAN_INVALIDATED = "PLAN_INVALIDATED"
    PLAN_SUPERSEDED = "PLAN_SUPERSEDED"
    # A final pre-placement refusal of an approved plan (plan 21-11 lists which refusals are
    # final; a non-final refusal such as LIMITS_NOT_CONFIGURED keeps the reservation counted
    # until PLAN_EXPIRED releases it).
    PLACEMENT_REFUSED = "PLACEMENT_REFUSED"
    # An entry intent REJECTED by the exchange or refused after consumption (RESERVED when the
    # POST was never acknowledged, PLACED otherwise).
    ENTRY_REJECTED = "ENTRY_REJECTED"
    # A resting entry that ended (cancelled, expired, DAILY_STOP) with no fill.
    ENTRY_ENDED_NO_FILL = "ENTRY_ENDED_NO_FILL"
    # A filled position that is flat again.
    POSITION_CLOSED = "POSITION_CLOSED"


_S = ReservationStatus
_R = ReleaseReason

# The permitted source statuses of each release reason (read-only; the store of plan 21-12
# enforces it). A PLACED or OPEN row is never released by a plan-status reason: the entry may
# still fill or the position is live, so only the exchange outcome releases it. POSITION_CLOSED
# is permitted from PLACED as well as OPEN (review WR-10): a closed position implies its entry
# filled, and when the first fill was missed (a stream gap, a restart between the fill and
# `mark_open`) the row is still PLACED, so without this source it would stay counted until a table
# edit. Every status except RELEASED is the source of at least one reason and RELEASED is never a
# source, so no counted reservation is left without an exit (D-16). There is no operator release
# reason: it would need a new CHECK value (a migration) and is left to the owner.
RELEASE_SOURCE_STATUSES: Mapping[ReleaseReason, frozenset[ReservationStatus]] = MappingProxyType(
    {
        _R.APPROVAL_SKIPPED: frozenset({_S.REQUESTED}),
        _R.APPROVAL_EXPIRED: frozenset({_S.REQUESTED}),
        _R.PLAN_EXPIRED: frozenset({_S.REQUESTED, _S.RESERVED}),
        _R.PLAN_INVALIDATED: frozenset({_S.REQUESTED, _S.RESERVED}),
        _R.PLAN_SUPERSEDED: frozenset({_S.REQUESTED, _S.RESERVED}),
        _R.PLACEMENT_REFUSED: frozenset({_S.RESERVED}),
        _R.ENTRY_REJECTED: frozenset({_S.RESERVED, _S.PLACED}),
        _R.ENTRY_ENDED_NO_FILL: frozenset({_S.PLACED}),
        _R.POSITION_CLOSED: frozenset({_S.PLACED, _S.OPEN}),
    }
)


def _require_non_empty(value: object, name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{name} must be a non-empty string")


def _require_side(value: object) -> None:
    if value not in _SIDES:
        raise ValueError(f"position_side must be LONG or SHORT, got {value!r}")


def _require_finite_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite, got {value}")
    return value


@dataclass(frozen=True)
class ReservationRequest:
    """A plan asking to reserve its sized risk (all fields come from the hashed plan)."""

    trade_plan_id: str
    plan_hash: str
    symbol: str
    position_side: str
    quantity: Decimal
    realized_risk: Decimal
    required_margin: Decimal | None = None
    margin_entry_price: Decimal | None = None
    margin_leverage: int | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.trade_plan_id, "trade_plan_id")
        _require_non_empty(self.symbol, "symbol")
        if not isinstance(self.plan_hash, str) or _PLAN_HASH.fullmatch(self.plan_hash) is None:
            raise ValueError("plan_hash must be 64 lower-case hex characters")
        _require_side(self.position_side)
        if _require_finite_decimal(self.quantity, "quantity") <= Decimal("0"):
            raise ValueError(f"quantity must be > 0, got {self.quantity}")
        if _require_finite_decimal(self.realized_risk, "realized_risk") <= Decimal("0"):
            raise ValueError(f"realized_risk must be > 0, got {self.realized_risk}")
        self._require_margin_trio()

    def _require_margin_trio(self) -> None:
        """The margin trio is all None (the Phase 21 form) or all set (plan 22-08, D-14)."""
        trio = (self.required_margin, self.margin_entry_price, self.margin_leverage)
        if all(value is None for value in trio):
            return
        if any(value is None for value in trio):
            raise ValueError(
                "required_margin, margin_entry_price and margin_leverage are all set or all None"
            )
        for name, amount in (
            ("required_margin", self.required_margin),
            ("margin_entry_price", self.margin_entry_price),
        ):
            if _require_finite_decimal(amount, name) <= Decimal("0"):
                raise ValueError(f"{name} must be > 0, got {amount}")
        leverage = self.margin_leverage
        if isinstance(leverage, bool) or not isinstance(leverage, int):
            raise TypeError(f"margin_leverage must be int, got {type(leverage).__name__}")
        if leverage < 1:
            raise ValueError(f"margin_leverage must be >= 1, got {leverage}")


@dataclass(frozen=True)
class CountedReservation:
    """One reservation row the caps count (status RESERVED, PLACED or OPEN)."""

    trade_plan_id: str
    plan_hash: str
    symbol: str
    position_side: str
    status: ReservationStatus
    open_risk: Decimal

    def __post_init__(self) -> None:
        _require_non_empty(self.trade_plan_id, "trade_plan_id")
        _require_non_empty(self.symbol, "symbol")
        if not isinstance(self.plan_hash, str) or _PLAN_HASH.fullmatch(self.plan_hash) is None:
            raise ValueError("plan_hash must be 64 lower-case hex characters")
        _require_side(self.position_side)
        if not isinstance(self.status, ReservationStatus) or self.status not in COUNTED_STATUSES:
            raise ValueError(f"status {self.status!r} is not a counted status")
        if _require_finite_decimal(self.open_risk, "open_risk") < Decimal("0"):
            raise ValueError(f"open_risk must be >= 0, got {self.open_risk}")


@dataclass(frozen=True)
class ExchangeExposure:
    """One exchange position as a signed quantity (positive LONG, negative SHORT)."""

    symbol: str
    signed_quantity: Decimal

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        _require_finite_decimal(self.signed_quantity, "signed_quantity")


def _as_open_position(row: CountedReservation) -> OpenPosition:
    return OpenPosition(
        symbol=row.symbol,
        position_side=row.position_side,
        open_risk=row.open_risk,
        daily_pnl_contribution=Decimal("0"),
    )


def _positions_without(
    counted: Sequence[CountedReservation], exclude_trade_plan_id: str
) -> tuple[OpenPosition, ...]:
    """The OpenPosition rows of `counted` minus the excluded plan, in a deterministic order."""
    kept = sorted(
        (row for row in counted if row.trade_plan_id != exclude_trade_plan_id),
        key=lambda row: (row.symbol, row.position_side, row.trade_plan_id),
    )
    return tuple(_as_open_position(row) for row in kept)


def open_positions_from_reservations(
    *,
    counted: Sequence[CountedReservation],
    exclude_trade_plan_id: str,
    exchange_exposures: Sequence[ExchangeExposure],
) -> tuple[OpenPosition, ...] | None:
    """The open-position view the caps judge: every counted reservation but the excluded plan.

    RESERVED (approved, unplaced), PLACED (resting entry) and OPEN (filled) rows all count with
    their sized realized risk (D-15). Fail closed: an exchange position (non-zero exposure) that
    no PLACED or OPEN row on the same symbol and side explains makes the view unknown (None),
    never a smaller count. The excluded plan's own row still explains an exposure, since at
    placement time the candidate's row is already PLACED or OPEN. Rows are sorted by
    (symbol, position_side, trade_plan_id).
    """
    explaining = {
        (row.symbol, row.position_side)
        for row in counted
        if row.status in (ReservationStatus.PLACED, ReservationStatus.OPEN)
    }
    for exposure in exchange_exposures:
        if exposure.signed_quantity == Decimal("0"):
            continue
        side = (
            Direction.LONG.value
            if exposure.signed_quantity > Decimal("0")
            else Direction.SHORT.value
        )
        if (exposure.symbol, side) not in explaining:
            return None
    return _positions_without(counted, exclude_trade_plan_id)


def reservation_verdict(
    *,
    request: ReservationRequest,
    counted: Sequence[CountedReservation],
    daily_loss_quote: Decimal | None,
    stop_latched: bool,
    thresholds: dict[str, Any],
    now_utc: datetime,
) -> PortfolioVerdict:
    """Judge a reservation request against the counted rows through the shared `check_portfolio`.

    While the day is latched the answer is DAILY_STOP_BLOCK with daily state DAILY_STOP (D-14);
    an unknown day loss is UNCERTAIN_ACCOUNT_STATE (inside `check_portfolio`). The request's own
    row (same `trade_plan_id`) is excluded from the rows it is judged against, because
    `check_portfolio` already adds the candidate's risk: a plan that fits exactly still passes
    at placement time, when its own row is already counted (Pitfall 2). The reserved amount is
    the request's sized realized risk (Pitfall 9).

    Constraint freshness and position reconciliation are NOT this gate's business: they are
    placement-time gates (`src/execution/gates.py` `decide_placement`). This call therefore
    passes `positions_reconciled=True`, `constraint_observed_at_utc=now_utc` and a zero TTL.
    `thresholds` are ABSOLUTE quote amounts, as `check_portfolio` requires.
    """
    if stop_latched:
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code=RejectionReason.DAILY_STOP_BLOCK.value,
            daily_state=DailyState.DAILY_STOP,
        )
    sized = SizedResult(
        is_no_trade=False,
        quantity=request.quantity,
        quantity_before_rounding=request.quantity,
        quantity_after_rounding=request.quantity,
        quantization_decision=QuantizationDecision.ACCEPTED.value,
        realized_risk=request.realized_risk,
    )
    return check_portfolio(
        sized=sized,
        candidate_symbol=request.symbol,
        candidate_position_side=request.position_side,
        open_positions=_positions_without(counted, request.trade_plan_id),
        daily_loss_quote=daily_loss_quote,
        parameter_set=thresholds,
        now_utc=now_utc,
        ttl=timedelta(0),
        positions_reconciled=True,
        constraint_observed_at_utc=now_utc,
    )


__all__ = [
    "COUNTED_STATUSES",
    "RELEASE_SOURCE_STATUSES",
    "CountedReservation",
    "ExchangeExposure",
    "ReleaseReason",
    "ReservationRequest",
    "ReservationStatus",
    "open_positions_from_reservations",
    "reservation_verdict",
]
