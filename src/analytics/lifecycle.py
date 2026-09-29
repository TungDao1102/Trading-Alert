"""Per-signal lifecycle normalization (Phase 10, plan 10-03, D-02/D-05).

Paper, backtest and live evidence are each normalized into the same
`LifecycleRecord` contract so the execution-quality engine
(`src.analytics.latency`) can measure legs without knowing the source. Evidence
kinds stay separately labelled and are never pooled. Nothing is imputed: a
missing timestamp or price stays None and is counted INCOMPLETE downstream.

stdlib + Decimal + in-repo pure modules only; frozen dataclasses in, frozen
dataclasses out (no database access here, D-01).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from src.analytics.types import (
    AnalyticsInputError,
    EvidenceKind,
    TradeOutcome,
    _optional_decimal,
    _optional_utc,
    _require_non_empty,
)
from src.domain.canonical import sha256_hex
from src.domain.enums import ApprovalResult
from src.paper.attribution import AttributionKind
from src.paper.journal import PaperRecord

_DIRECTIONS = frozenset({"LONG", "SHORT"})
_EXPIRED_REASON = "EXPIRED"
_BACKTEST_FILLED_KINDS = frozenset({"ENTRY_FILLED", "PARTIAL_FILL"})
_BACKTEST_UNFILLED_KINDS = frozenset({"TOUCH_NO_FILL", "EXPIRED", "INVALIDATION_CANCEL"})


class LifecyclePath(str, Enum):
    """How a signal travelled: user-executed, an opportunity, or system-only."""

    USER_EXECUTED = "USER_EXECUTED"
    OPPORTUNITY = "OPPORTUNITY"
    SYSTEM_ONLY = "SYSTEM_ONLY"


@dataclass(frozen=True)
class LifecycleRecord:
    """One signal's normalized lifecycle for exactly one evidence kind.

    `delivery_requested_at_utc` is a delivery-request PROXY (live: the
    Approval.requested_at_utc), never a read receipt: no code journals a
    "seen" timestamp (RESEARCH P1). `synthetic_lag` is True when the approval
    time was derived from the fixed paper approval-delay constant rather than
    measured (RESEARCH P2).
    """

    evidence: EvidenceKind
    source_id: str
    signal_id: str | None
    symbol: str
    strategy_version: str
    direction: str | None
    path: LifecyclePath
    approval_result: ApprovalResult | None
    signal_detected_at_utc: datetime | None
    delivery_requested_at_utc: datetime | None
    approved_at_utc: datetime | None
    order_submitted_at_utc: datetime | None
    fill_time_utc: datetime | None
    intended_entry_price: Decimal | None
    actual_entry_price: Decimal | None
    entry_filled: bool | None
    expired_without_fill: bool | None
    reason_code: str
    synthetic_lag: bool
    epoch_id: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, EvidenceKind):
            raise AnalyticsInputError("evidence must be an EvidenceKind")
        _require_non_empty(self.source_id, "source_id")
        _require_non_empty(self.symbol, "symbol")
        _require_non_empty(self.strategy_version, "strategy_version")
        if self.direction is not None and self.direction not in _DIRECTIONS:
            raise AnalyticsInputError(
                f"direction must be LONG, SHORT or None, got {self.direction!r}"
            )
        if not isinstance(self.path, LifecyclePath):
            raise AnalyticsInputError("path must be a LifecyclePath")
        if self.approval_result is not None and not isinstance(
            self.approval_result, ApprovalResult
        ):
            raise AnalyticsInputError("approval_result must be an ApprovalResult or None")
        _optional_utc(self.signal_detected_at_utc, "signal_detected_at_utc")
        _optional_utc(self.delivery_requested_at_utc, "delivery_requested_at_utc")
        _optional_utc(self.approved_at_utc, "approved_at_utc")
        _optional_utc(self.order_submitted_at_utc, "order_submitted_at_utc")
        _optional_utc(self.fill_time_utc, "fill_time_utc")
        _optional_decimal(self.intended_entry_price, "intended_entry_price")
        _optional_decimal(self.actual_entry_price, "actual_entry_price")
        for name in ("entry_filled", "expired_without_fill"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise AnalyticsInputError(f"{name} must be a bool or None")
        if not isinstance(self.reason_code, str):
            raise AnalyticsInputError("reason_code must be a str")
        if not isinstance(self.synthetic_lag, bool):
            raise AnalyticsInputError("synthetic_lag must be a bool")

    def digest(self) -> str:
        return sha256_hex(
            {
                "evidence": self.evidence,
                "source_id": self.source_id,
                "signal_id": self.signal_id,
                "symbol": self.symbol,
                "strategy_version": self.strategy_version,
                "direction": self.direction,
                "path": self.path,
                "approval_result": self.approval_result,
                "signal_detected_at_utc": self.signal_detected_at_utc,
                "delivery_requested_at_utc": self.delivery_requested_at_utc,
                "approved_at_utc": self.approved_at_utc,
                "order_submitted_at_utc": self.order_submitted_at_utc,
                "fill_time_utc": self.fill_time_utc,
                "intended_entry_price": self.intended_entry_price,
                "actual_entry_price": self.actual_entry_price,
                "entry_filled": self.entry_filled,
                "expired_without_fill": self.expired_without_fill,
                "reason_code": self.reason_code,
                "synthetic_lag": self.synthetic_lag,
                "epoch_id": self.epoch_id,
            }
        )


def _normalize_paper_group(signal_id: str, rows: Sequence[PaperRecord]) -> LifecycleRecord:
    by_kind: dict[AttributionKind, PaperRecord] = {}
    for row in rows:
        if row.attribution in by_kind:
            raise AnalyticsInputError(
                f"duplicate {row.attribution.value} paper row for signal {signal_id!r}"
            )
        by_kind[row.attribution] = row
    system = by_kind.get(AttributionKind.SYSTEM)
    user_sim = by_kind.get(AttributionKind.USER_EXECUTED_SIM)
    opportunity = by_kind.get(AttributionKind.OPPORTUNITY)
    if user_sim is not None and opportunity is not None:
        raise AnalyticsInputError(
            f"signal {signal_id!r} has both user-executed-sim and opportunity rows"
        )
    base = system if system is not None else rows[0]
    detected = base.signal_detected_at_utc
    if detected is None:
        for row in rows:
            if row.signal_detected_at_utc is not None:
                detected = row.signal_detected_at_utc
                break
    approval_result: ApprovalResult | None = None
    approved_at: datetime | None = None
    order_at: datetime | None = None
    fill_at: datetime | None = None
    reason_code = base.reason_code
    synthetic_lag = False
    entry_filled: bool | None = None
    if user_sim is not None:
        path = LifecyclePath.USER_EXECUTED
        approval_result = ApprovalResult.APPROVED
        approved_at = user_sim.approval_acted_at_utc
        order_at = user_sim.order_submitted_at_utc
        fill_at = user_sim.fill_time_utc
        reason_code = user_sim.reason_code
        synthetic_lag = True
        if order_at is not None:
            entry_filled = fill_at is not None
    elif opportunity is not None:
        path = LifecyclePath.OPPORTUNITY
        reason_code = opportunity.reason_code
        approval_result = (
            ApprovalResult.EXPIRED if reason_code == _EXPIRED_REASON else ApprovalResult.SKIPPED
        )
    else:
        path = LifecyclePath.SYSTEM_ONLY
    return LifecycleRecord(
        evidence=EvidenceKind.PAPER,
        source_id=signal_id,
        signal_id=signal_id,
        symbol=base.symbol,
        strategy_version=base.strategy_version,
        direction=None,
        path=path,
        approval_result=approval_result,
        signal_detected_at_utc=detected,
        delivery_requested_at_utc=None,
        approved_at_utc=approved_at,
        order_submitted_at_utc=order_at,
        fill_time_utc=fill_at,
        intended_entry_price=None,
        actual_entry_price=None,
        entry_filled=entry_filled,
        expired_without_fill=None,
        reason_code=reason_code,
        synthetic_lag=synthetic_lag,
        epoch_id=base.epoch_id,
    )


def normalize_paper_lifecycle(records: Sequence[PaperRecord]) -> tuple[LifecycleRecord, ...]:
    """Group paper rows by signal_id into LifecycleRecords sorted by signal_id.

    NO_TRADE rows (signal_id None) are not lifecycle records and are skipped
    here (they are counted elsewhere). The paper approval time is the fixed
    approval-delay constant, so user-executed rows carry `synthetic_lag=True`.
    """
    groups: dict[str, list[PaperRecord]] = {}
    for record in records:
        if record.signal_id is None:
            continue
        groups.setdefault(record.signal_id, []).append(record)
    return tuple(_normalize_paper_group(sid, groups[sid]) for sid in sorted(groups))


def _normalize_backtest_outcome(outcome: TradeOutcome) -> LifecycleRecord:
    kind = outcome.entry_kind
    entry_filled: bool | None
    if kind is None:
        entry_filled = None
    elif kind in _BACKTEST_FILLED_KINDS:
        entry_filled = True
    elif kind in _BACKTEST_UNFILLED_KINDS:
        entry_filled = False
    else:
        raise AnalyticsInputError(
            f"unknown backtest entry_kind {kind!r} for trade {outcome.trade_id!r}"
        )
    return LifecycleRecord(
        evidence=EvidenceKind.BACKTEST,
        source_id=outcome.trade_id,
        signal_id=outcome.signal_id,
        symbol=outcome.symbol,
        strategy_version=outcome.strategy_version,
        direction=outcome.direction,
        path=LifecyclePath.SYSTEM_ONLY,
        approval_result=None,
        signal_detected_at_utc=None,
        delivery_requested_at_utc=None,
        approved_at_utc=None,
        order_submitted_at_utc=None,
        fill_time_utc=None,
        intended_entry_price=outcome.intended_entry_price,
        actual_entry_price=outcome.entry_price if entry_filled else None,
        entry_filled=entry_filled,
        expired_without_fill=None if kind is None else kind == "EXPIRED",
        reason_code="",
        synthetic_lag=False,
        epoch_id=None,
    )


def normalize_backtest_lifecycle(
    outcomes: Sequence[TradeOutcome],
) -> tuple[LifecycleRecord, ...]:
    """Backtest outcomes -> LifecycleRecords sorted by trade_id (all timestamps None).

    `entry_filled` is True for ENTRY_FILLED / PARTIAL_FILL and False for
    TOUCH_NO_FILL / EXPIRED / INVALIDATION_CANCEL; `expired_without_fill` is True
    only for EXPIRED. An unknown entry_kind or a duplicate trade_id fails closed.
    """
    records: list[LifecycleRecord] = []
    seen: set[str] = set()
    for outcome in sorted(outcomes, key=lambda item: item.trade_id):
        if outcome.evidence is not EvidenceKind.BACKTEST:
            raise AnalyticsInputError(
                f"trade {outcome.trade_id!r} is {outcome.evidence.value}, expected BACKTEST"
            )
        if outcome.trade_id in seen:
            raise AnalyticsInputError(f"duplicate trade_id {outcome.trade_id!r}")
        seen.add(outcome.trade_id)
        records.append(_normalize_backtest_outcome(outcome))
    return tuple(records)
