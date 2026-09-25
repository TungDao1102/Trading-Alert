"""Pure portfolio-gate function (Phase 5, plan 05-02).

Per D-03 + D-04 + RISK_MANAGEMENT §§4-5/8/12: `check_portfolio` evaluates
the cluster cap, aggregate cap, position count, and DAILY_STOP state in
fixed order (first failure wins). Uncertain inputs (None daily loss,
unreconciled positions, stale constraint snapshot) fail closed to
NO_TRADE with a reason code.

The function never imports the SDK, never reads a clock, never reads
the environment. The same call linked into backtest/paper/live produces
byte-identical outputs (parity fixture is the enforcement mechanism).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.core._decimal import _add
from src.domain.enums import DailyState, Direction, RejectionReason

from .types import OpenPosition, PortfolioVerdict, SizedResult

# V1 conservative cluster rule (D-03 + RESEARCH A3): directionally-aligned
# BTC/ETH/SOL/XRP positions count as one cluster. The candidate's symbol
# is supplied by the caller (the trade plan's symbol).
CLUSTER_SYMBOLS: frozenset[str] = frozenset(
    {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"}
)

_OK = "OK"


def _require_decimal(value: object, field_name: str) -> Decimal:
    """Reject non-Decimal values for money/qty/price inputs (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
    return value


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(
            f"{field_name} must be UTC, got offset {value.utcoffset()}"
        )


def _derive_daily_state(
    *,
    daily_loss_quote: Decimal,
    warning_threshold_quote: Decimal,
    stop_threshold_quote: Decimal,
) -> DailyState:
    """Derive the daily PnL state from the injected loss and thresholds.

    Boundaries (inclusive):
      - daily_loss < warning_threshold → NORMAL
      - warning_threshold <= daily_loss < stop_threshold → WARNING
      - daily_loss >= stop_threshold → DAILY_STOP
    """
    if daily_loss_quote >= stop_threshold_quote:
        return DailyState.DAILY_STOP
    if daily_loss_quote >= warning_threshold_quote:
        return DailyState.WARNING
    return DailyState.NORMAL


def _extract_thresholds(
    parameter_set: dict[str, Any],
) -> (
    tuple[int, Decimal, Decimal, Decimal, Decimal] | None
):
    """Read and type-check portfolio thresholds, fail-closed on violation.

    Returns `(max_open_positions, max_aggregate_open_risk, cluster_cap,
    daily_loss_warning_threshold, daily_loss_stop_threshold)` or `None`
    when the parameter set is malformed. `None` means the caller must
    emit an `UNCERTAIN_ACCOUNT_STATE` envelope — never `KeyError` (missing
    key), never silent truncation (`int(Decimal("2.9")) == 2`), never a
    `bool` smuggled through `isinstance(int)`.
    """
    try:
        max_open_positions = parameter_set["max_open_positions"]
        max_aggregate_open_risk = parameter_set["max_aggregate_open_risk"]
        cluster_cap = parameter_set["cluster_cap"]
        warning = parameter_set["daily_loss_warning_threshold"]
        stop = parameter_set["daily_loss_stop_threshold"]
    except KeyError:
        return None
    if isinstance(max_open_positions, bool) or not isinstance(
        max_open_positions, int
    ):
        return None
    for value in (max_aggregate_open_risk, cluster_cap, warning, stop):
        if not isinstance(value, Decimal):
            return None
    return (
        max_open_positions,
        max_aggregate_open_risk,
        cluster_cap,
        warning,
        stop,
    )


def check_portfolio(
    *,
    sized: SizedResult,
    candidate_symbol: str,
    candidate_position_side: str,
    open_positions: Sequence[OpenPosition],
    daily_loss_quote: Decimal | None,
    parameter_set: dict[str, Any],
    now_utc: datetime,
    ttl: timedelta,
    positions_reconciled: bool = True,
    constraint_observed_at_utc: datetime | None = None,
) -> PortfolioVerdict:
    """Evaluate portfolio gates in fixed order; first failure wins.

    Gate order (D-03):
      1. Fail-closed input validation (D-04): None daily loss,
         unreconciled positions, stale constraint snapshot.
      2. Cluster cap (V1 conservative rule).
      3. Aggregate cap.
      4. Position count.
      5. Daily state (DAILY_STOP blocks; WARNING passes with state).

    On pass: returns PortfolioVerdict with `is_no_trade=False`,
    `sized=sized`, `reason_code="OK"`, `daily_state=<derived>`.
    On fail: returns PortfolioVerdict with `is_no_trade=True`,
    `sized=None`, `reason_code=<gate code>`, `daily_state=<derived>`.

    The candidate's realized risk (`sized.realized_risk`) is ADDED to
    cluster and aggregate sums (Pitfall 6 — 05-01 checkpoint lock).
    The candidate is NOT counted in the position count (it is not yet
    a position).
    """
    # Validate inputs.
    _require_utc_aware(now_utc, "now_utc")
    candidate_risk = _require_decimal(sized.realized_risk, "sized.realized_risk")
    if candidate_position_side not in {d.value for d in Direction}:
        raise ValueError(
            "candidate_position_side must be a Direction value "
            f"(LONG/SHORT), got {candidate_position_side!r}"
        )

    # Read thresholds from the parameter set (registry-owned, never
    # hard-coded — D-03 + D-05). Malformed sets fail closed to an
    # UNCERTAIN_ACCOUNT_STATE envelope instead of raising KeyError,
    # truncating non-int numerics, or leaking TypeError to the caller.
    thresholds = _extract_thresholds(parameter_set)
    if thresholds is None:
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code=RejectionReason.UNCERTAIN_ACCOUNT_STATE.value,
            daily_state=DailyState.NORMAL,
        )
    (
        max_open_positions,
        max_aggregate_open_risk,
        cluster_cap,
        daily_loss_warning_threshold,
        daily_loss_stop_threshold,
    ) = thresholds

    # Sort positions deterministically (Pitfall 4 — non-deterministic
    # iteration). Sort by (symbol, position_side) so two position lists
    # with different insertion orders yield identical verdicts.
    sorted_positions = sorted(
        open_positions, key=lambda p: (p.symbol, p.position_side)
    )

    # Derive daily state from injected loss + thresholds BEFORE any
    # verdict below, so no fail-closed path masks DAILY_STOP from the
    # downstream SAFE_MODE consumers that read this field. Unknown loss
    # cannot derive — those verdicts keep NORMAL.
    if daily_loss_quote is None:
        derived_state = DailyState.NORMAL
    else:
        derived_state = _derive_daily_state(
            daily_loss_quote=daily_loss_quote,
            warning_threshold_quote=daily_loss_warning_threshold,
            stop_threshold_quote=daily_loss_stop_threshold,
        )

    # Short-circuit: if sizing/quantization already rejected, preserve
    # the upstream reason code (D-02 — pipeline short-circuits) while
    # carrying the derived daily state.
    if sized.is_no_trade:
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code=sized.reason_code,
            daily_state=derived_state,
        )

    if daily_loss_quote is None:
        # Fail-closed: unknown daily loss → UNCERTAIN_ACCOUNT_STATE.
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code=RejectionReason.UNCERTAIN_ACCOUNT_STATE.value,
            daily_state=derived_state,
        )
    if not positions_reconciled:
        # Fail-closed: unreconciled positions → UNCERTAIN_ACCOUNT_STATE.
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code=RejectionReason.UNCERTAIN_ACCOUNT_STATE.value,
            daily_state=derived_state,
        )
    if constraint_observed_at_utc is None:
        # Fail-closed: a missing freshness timestamp must not bypass the
        # §12 gate — an omitted argument is stale metadata, not fresh.
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code=RejectionReason.STALE_CONSTRAINTS.value,
            daily_state=derived_state,
        )
    _require_utc_aware(constraint_observed_at_utc, "constraint_observed_at_utc")
    age = now_utc - constraint_observed_at_utc
    if age > ttl or age < timedelta(0):
        # Fail-closed: stale constraint snapshot → STALE_CONSTRAINTS.
        # Negative age (future-dated snapshot: clock skew or corrupt
        # upstream metadata) fails closed the same way.
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code=RejectionReason.STALE_CONSTRAINTS.value,
            daily_state=derived_state,
        )

    # Thresholds in quote currency (registry values are rates of equity).
    # The caller is expected to pass `parameter_set` already loaded with
    # the rate values; we multiply by the candidate's equity context
    # only when the parameter set carries rates. For V1, the parameter
    # set carries rates and we multiply by the candidate's realized_risk
    # basis. To keep the gate math simple and the parity fixture
    # byte-exact, we treat the registry values as absolute quote amounts
    # when the parameter set provides them as such. The caller is
    # responsible for converting rates to absolute amounts before
    # calling check_portfolio (Phase-7+ caller concern).
    #
    # For V1 parity fixtures, the parameter_set values are passed as
    # absolute quote amounts (e.g. cluster_cap=50 USDT for equity=10000
    # with cluster_cap_rate=0.005). The caller (evaluate_risk) does the
    # rate-to-absolute conversion.
    cluster_cap_quote = cluster_cap
    max_aggregate_open_risk_quote = max_aggregate_open_risk
    warning_threshold_quote = daily_loss_warning_threshold
    stop_threshold_quote = daily_loss_stop_threshold

    daily_state = derived_state

    # Gate 1: cluster cap (V1 conservative rule — directionally-aligned
    # BTC/ETH/SOL/XRP counted as one cluster).
    candidate_in_cluster = candidate_symbol in CLUSTER_SYMBOLS
    cluster_open_risk = Decimal("0")
    if candidate_in_cluster:
        for p in sorted_positions:
            if (
                p.symbol in CLUSTER_SYMBOLS
                and p.position_side == candidate_position_side
            ):
                cluster_open_risk = _add(cluster_open_risk, p.open_risk)
    cluster_sum = _add(cluster_open_risk, candidate_risk)
    if cluster_sum > cluster_cap_quote:
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code=RejectionReason.CLUSTER_CAP_REJECT.value,
            daily_state=daily_state,
        )

    # Gate 2: aggregate cap (sum of all open-risk + candidate risk).
    aggregate_open_risk = Decimal("0")
    for p in sorted_positions:
        aggregate_open_risk = _add(aggregate_open_risk, p.open_risk)
    aggregate_sum = _add(aggregate_open_risk, candidate_risk)
    if aggregate_sum > max_aggregate_open_risk_quote:
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code=RejectionReason.AGGREGATE_CAP_REJECT.value,
            daily_state=daily_state,
        )

    # Gate 3: position count (open positions only — candidate is not
    # yet a position).
    if len(sorted_positions) >= max_open_positions:
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code=RejectionReason.MAX_POSITIONS_REJECT.value,
            daily_state=daily_state,
        )

    # Gate 4: daily state (DAILY_STOP blocks; WARNING passes with state).
    if daily_state == DailyState.DAILY_STOP:
        return PortfolioVerdict(
            is_no_trade=True,
            sized=None,
            reason_code=RejectionReason.DAILY_STOP_BLOCK.value,
            daily_state=daily_state,
        )

    # All gates passed.
    return PortfolioVerdict(
        is_no_trade=False,
        sized=sized,
        reason_code=_OK,
        daily_state=daily_state,
    )


__all__ = ["check_portfolio", "CLUSTER_SYMBOLS"]
