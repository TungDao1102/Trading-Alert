"""Placement-time gates (Phase 9, plan 09-03).

Per D-03: every placement revalidates live constraints from exchangeInfo
at placement time, evaluates portfolio caps and DAILY_STOP against the
live/reconciled position set, and runs under the LIVE_ORDERS_DISABLED
default-disabled enablement gate. Headroom, DAILY_STOP, stale-snapshot,
uncertain-state, and disabled-flag rejects all land as fail-closed
reason codes before any order call.

The module is dependency-free: stdlib + Decimal + `src/risk/*` only.
No Binance SDK, no SQLAlchemy, no Pydantic, no Polars.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.domain.enums import DailyState, RejectionReason
from src.risk.portfolio import check_portfolio, derive_daily_state
from src.risk.types import ConstraintSnapshot, OpenPosition, SizedResult

# --------------------------------------------------------------------------- #
# Headroom limit per Binance USDⓈ-M Futures: 200 open conditional orders across all
# symbols (account-wide, not per symbol).
#
# Per D-03: headroom equality (count + legs == 200) is assumed reject to keep
# operational headroom. The check is `count + legs >= 200` so the boundary
# case (exactly 200) also rejects.
#
# Binance removed the `MAX_NUM_ALGO_ORDERS` exchangeInfo filter on 2025-12-29 and
# documents the limit as account-wide (docs/trading/EXECUTION_SPEC.md section 12,
# docs/SOURCES.md), so there is no filter to read and this literal is the documented
# value. The open algo-order count the caller passes in must be account-wide
# (no symbol filter); its live producer is owned by ROADMAP Phase 24. Re-verify the
# limit against the current Binance change-log before wiring it.
# --------------------------------------------------------------------------- #

HEADROOM_LIMIT: int = 200

_OK = "OK"


# --------------------------------------------------------------------------- #
# Frozen dataclass — the public placement-gate contract.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PlacementGateVerdict:
    """Discriminated PASS-or-NO_TRADE envelope emitted by `decide_placement`.

    `is_no_trade=True` carries a canonical RejectionReason value in
    `reason_code` (EXCHANGE_CONSTRAINT, STALE_CONSTRAINTS,
    UNCERTAIN_ACCOUNT_STATE, DAILY_STOP_BLOCK, CLUSTER_CAP_REJECT,
    AGGREGATE_CAP_REJECT, MAX_POSITIONS_REJECT) and `sized=None`.
    `is_no_trade=False` carries `reason_code="OK"` and the SizedResult
    forwarded for downstream placement.
    """

    is_no_trade: bool
    reason_code: str
    sized: SizedResult | None
    daily_state: DailyState

    def __post_init__(self) -> None:
        if not isinstance(self.reason_code, str) or self.reason_code == "":
            raise ValueError("reason_code must be a non-empty string")
        valid_codes = {r.value for r in RejectionReason} | {_OK}
        if self.reason_code not in valid_codes:
            raise ValueError(f"PlacementGateVerdict: unknown reason_code {self.reason_code!r}")
        if not isinstance(self.daily_state, DailyState):
            raise TypeError(
                f"daily_state must be DailyState, got {type(self.daily_state).__name__}"
            )
        if self.is_no_trade:
            if self.sized is not None:
                raise ValueError("PlacementGateVerdict: is_no_trade=True requires sized=None")
        else:
            if self.sized is None:
                raise ValueError("PlacementGateVerdict: is_no_trade=False requires sized")
            if self.reason_code != _OK:
                raise ValueError(
                    f"PlacementGateVerdict: is_no_trade=False requires "
                    f"reason_code='OK', got {self.reason_code!r}"
                )


# --------------------------------------------------------------------------- #
# Public entry point — decide_placement.
# --------------------------------------------------------------------------- #


def decide_placement(
    *,
    constraint_snapshot: ConstraintSnapshot,
    open_algo_count: int,
    planned_leg_count: int,
    reconciled_positions: Sequence[OpenPosition],
    daily_loss_quote: Decimal | None,
    positions_reconciled: bool,
    now_utc: datetime,
    ttl: timedelta,
    sized: SizedResult,
    candidate_symbol: str,
    candidate_position_side: str,
    parameter_set: dict[str, Any],
) -> PlacementGateVerdict:
    """Evaluate placement-time gates in fixed order; first failure wins.

    Gate order (D-03):
      1. exchangeInfo revalidation (tick/stepSize/min_qty/min_notional > 0).
      2. Headroom: `open_algo_count + planned_leg_count >= 200` →
         EXCHANGE_CONSTRAINT (operational headroom margin).
      3. Stale constraints: `now_utc - metadata_observed_at_utc > ttl` →
         STALE_CONSTRAINTS.
      4. Uncertain account state: `None daily_loss_quote` or
         `not positions_reconciled` → UNCERTAIN_ACCOUNT_STATE.
      5. Portfolio enforcement (per-trade sizing, cluster cap, aggregate
         cap, position count, daily state) via `check_portfolio`.

    On pass: returns `PlacementGateVerdict` with `is_no_trade=False`,
    `sized=sized`, `reason_code="OK"`, `daily_state=<derived>`.
    On fail: returns `PlacementGateVerdict` with `is_no_trade=True`,
    `sized=None`, `reason_code=<gate code>`, `daily_state=<derived>`.

    Args:
        constraint_snapshot: The exchangeInfo-derived constraints.
        open_algo_count: The live open algo count from
            `snapshot_open_algo_orders` (caller-supplied).
        planned_leg_count: The number of legs the placement will add
            (entry + SL + TP1 + TP2 = 4 for a full plan; 1 for entry-only).
        reconciled_positions: The live reconciled position set.
        daily_loss_quote: The current daily loss in quote currency, or
            None if unknown.
        positions_reconciled: Whether the position set is reconciled.
        now_utc: The current UTC-aware datetime.
        ttl: The constraint snapshot TTL.
        sized: The SizedResult from the risk pipeline.
        candidate_symbol: The candidate trade plan's symbol.
        candidate_position_side: The candidate trade plan's position side.
        parameter_set: The portfolio thresholds (absolute quote amounts).

    Returns:
        A `PlacementGateVerdict` with the gate outcome.
    """
    # 09-REVIEW WR-06: corrupt counts fail loudly (a negative count would
    # silently widen the headroom), and the daily state is derived BEFORE
    # any early return so no fail-closed gate masks DAILY_STOP from the
    # downstream SAFE_MODE consumers (mirrors `check_portfolio`).
    for name, count in (
        ("open_algo_count", open_algo_count),
        ("planned_leg_count", planned_leg_count),
    ):
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"decide_placement: {name} must be an int >= 0, got {count!r}")
    daily_state = derive_daily_state(daily_loss_quote=daily_loss_quote, parameter_set=parameter_set)

    # Gate 1: exchangeInfo revalidation.
    # ConstraintSnapshot.__post_init__ already validates positive values,
    # but we re-check here as a fail-closed guard against any future
    # construction path that bypasses the dataclass guard.
    if (
        constraint_snapshot.price_tick_size <= Decimal("0")
        or constraint_snapshot.quantity_step_size <= Decimal("0")
        or constraint_snapshot.min_quantity <= Decimal("0")
        or constraint_snapshot.min_notional <= Decimal("0")
    ):
        return PlacementGateVerdict(
            is_no_trade=True,
            reason_code=RejectionReason.EXCHANGE_CONSTRAINT.value,
            sized=None,
            daily_state=daily_state,
        )

    # Gate 2: headroom check.
    # Per D-03: open_algo_count + planned_leg_count >= 200 → EXCHANGE_CONSTRAINT.
    # The boundary case (exactly 200) also rejects to keep operational headroom.
    if open_algo_count + planned_leg_count >= HEADROOM_LIMIT:
        return PlacementGateVerdict(
            is_no_trade=True,
            reason_code=RejectionReason.EXCHANGE_CONSTRAINT.value,
            sized=None,
            daily_state=daily_state,
        )

    # Gate 3: stale constraints.
    # now_utc - metadata_observed_at_utc > ttl → STALE_CONSTRAINTS.
    # Negative age (future-dated snapshot: clock skew or corrupt upstream
    # metadata) fails closed the same way.
    age = now_utc - constraint_snapshot.metadata_observed_at_utc
    if age > ttl or age < timedelta(0):
        return PlacementGateVerdict(
            is_no_trade=True,
            reason_code=RejectionReason.STALE_CONSTRAINTS.value,
            sized=None,
            daily_state=daily_state,
        )

    # Gate 4: uncertain account state.
    # None daily_loss_quote or not positions_reconciled → UNCERTAIN_ACCOUNT_STATE.
    if daily_loss_quote is None or not positions_reconciled:
        return PlacementGateVerdict(
            is_no_trade=True,
            reason_code=RejectionReason.UNCERTAIN_ACCOUNT_STATE.value,
            sized=None,
            daily_state=daily_state,
        )

    # Gate 5: portfolio enforcement via check_portfolio.
    # check_portfolio evaluates per-trade sizing, cluster cap, aggregate
    # cap, position count, and daily state in fixed order (first failure
    # wins). The SizedResult is forwarded; on pass, the SizedResult is
    # returned in the verdict for downstream placement.
    portfolio_verdict = check_portfolio(
        sized=sized,
        candidate_symbol=candidate_symbol,
        candidate_position_side=candidate_position_side,
        open_positions=reconciled_positions,
        daily_loss_quote=daily_loss_quote,
        parameter_set=parameter_set,
        now_utc=now_utc,
        ttl=ttl,
        positions_reconciled=positions_reconciled,
        constraint_observed_at_utc=constraint_snapshot.metadata_observed_at_utc,
    )

    if portfolio_verdict.is_no_trade:
        return PlacementGateVerdict(
            is_no_trade=True,
            reason_code=portfolio_verdict.reason_code,
            sized=None,
            daily_state=portfolio_verdict.daily_state,
        )

    # All gates passed.
    return PlacementGateVerdict(
        is_no_trade=False,
        reason_code=_OK,
        sized=portfolio_verdict.sized,
        daily_state=portfolio_verdict.daily_state,
    )


__all__ = ["decide_placement", "PlacementGateVerdict", "HEADROOM_LIMIT"]
