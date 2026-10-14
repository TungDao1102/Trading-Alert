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

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from src.analytics.types import (
    AnalyticsInputError,
    EvidenceKind,
    IncompleteReason,
    TradeOutcome,
    _optional_decimal,
    _optional_utc,
    _require_count,
    _require_non_empty,
)
from src.core._decimal import _add, _div, _mul
from src.domain.approval import Approval
from src.domain.canonical import sha256_hex
from src.domain.enums import ApprovalResult, OrderRole
from src.domain.fill import Fill
from src.domain.journal import JournalEvent
from src.domain.order import Order
from src.domain.signal import Signal
from src.paper.attribution import AttributionKind
from src.paper.journal import PaperRecord

_DIRECTIONS = frozenset({"LONG", "SHORT"})
_EXPIRED_REASON = "EXPIRED"
_BACKTEST_FILLED_KINDS = frozenset({"ENTRY_FILLED", "PARTIAL_FILL"})
# v2 vocabulary (D-34); TOUCH_NO_FILL stays for old evidence, v2 records only carry it as a
# per-plan counter and the boundary validator refuses it as a kind.
_BACKTEST_UNFILLED_KINDS = frozenset(
    {
        "TOUCH_NO_FILL",
        "EXPIRED",
        "INVALIDATION_CANCEL",
        "DAILY_STOP_CANCEL",
        "PENDING_AT_DATA_END",
        # semantics.SETTLEMENT_CANCEL (quick 261014-nnl): a RESTING plan cancelled at the
        # terminal instant of its symbol; the literal matches this module's literal style.
        "SETTLEMENT_CANCEL",
    }
)
_ENTRY_EXPIRY_EVENT_TYPE = "ENTRY_EXPIRY"
_PHASE_POST_CANCEL = "post_cancel"
_JOIN_APPROVAL_SIGNAL = "approval->signal"
_JOIN_ENTRY_ORDER_APPROVAL = "entry_order->approval"
_JOIN_FILL_ORDER = "fill->order"
_JOIN_EXPIRY_ORDER = "expiry_event->order"


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
    delivery_requested: datetime | None = None
    entry_filled: bool | None = None
    if user_sim is not None:
        path = LifecyclePath.USER_EXECUTED
        approval_result = ApprovalResult.APPROVED
        approved_at = user_sim.approval_acted_at_utc
        order_at = user_sim.order_submitted_at_utc
        fill_at = user_sim.fill_time_utc
        reason_code = user_sim.reason_code
        # D-15 / P15: a record whose approval was measured (a SHADOW human action carries the
        # request time next to the acted time) is reported as measured; only a record with no
        # human action keeps the fixed-constant approval time and the synthetic-lag flag.
        delivery_requested = user_sim.approval_requested_at_utc
        synthetic_lag = delivery_requested is None
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
        delivery_requested_at_utc=delivery_requested,
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


def exclude_test_only(records: Sequence[PaperRecord]) -> tuple[tuple[PaperRecord, ...], int]:
    """The paper rows that are not rehearsal rows, and how many `test_only` rows were dropped.

    REV-03 (D063 item 3): a `test_only` record is produced by a test and never counts as a
    signal, a trade, a delay or an outcome. The edge calls this once and hands the same kept
    rows to every paper normalizer, so each count sees the same filtered set; the dropped
    number is printed in the report.
    """
    kept = tuple(record for record in records if not record.test_only)
    return kept, len(records) - len(kept)


def paper_delay_is_synthetic(records: Sequence[LifecycleRecord]) -> bool:
    """True when a PAPER section's approval delay is (or may be) the fixed constant.

    A section whose user-executed records are all measured is not labelled SYNTHETIC LAG
    (D-15, P15). A section with a synthetic user-executed record, and a section with no
    user-executed record at all (nothing measured to show), keep the label as before.
    """
    user = [record for record in records if record.path is LifecyclePath.USER_EXECUTED]
    return not user or any(record.synthetic_lag for record in user)


def normalize_paper_lifecycle(records: Sequence[PaperRecord]) -> tuple[LifecycleRecord, ...]:
    """Group paper rows by signal_id into LifecycleRecords sorted by signal_id.

    NO_TRADE rows (signal_id None) are not lifecycle records and are skipped
    here (they are counted elsewhere). `test_only` rehearsal rows are dropped first
    (REV-03). A user-executed row whose approval was measured (SHADOW human action)
    carries the measured request and acted times and `synthetic_lag=False`; one with
    no human action carries the fixed approval-delay constant and `synthetic_lag=True`.
    """
    groups: dict[str, list[PaperRecord]] = {}
    for record in exclude_test_only(records)[0]:
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
    EXPIRED / INVALIDATION_CANCEL / DAILY_STOP_CANCEL / SETTLEMENT_CANCEL /
    PENDING_AT_DATA_END (and the old TOUCH_NO_FILL); `expired_without_fill` is True
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


# --------------------------------------------------------------------------- #
# Live lifecycle (frozen domain dataclasses in, frozen dataclasses out).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class JoinAccount:
    """How many rows of one join matched / did not match (never silently dropped)."""

    name: str
    matched: int
    unmatched: int

    def __post_init__(self) -> None:
        _require_non_empty(self.name, "name")
        _require_count(self.matched, "matched")
        _require_count(self.unmatched, "unmatched")

    def digest(self) -> str:
        return sha256_hex({"name": self.name, "matched": self.matched, "unmatched": self.unmatched})


@dataclass(frozen=True)
class LiveLifecycleResult:
    """Live lifecycle records plus join accounting and rejected-row counts."""

    records: tuple[LifecycleRecord, ...]
    joins: tuple[JoinAccount, ...]
    rejected: tuple[tuple[str, int], ...]

    def digest(self) -> str:
        return sha256_hex(
            {
                "records": [record.digest() for record in self.records],
                "joins": [join.digest() for join in self.joins],
                "rejected": [[reason, count] for reason, count in self.rejected],
            }
        )


def _event_sort_key(event: JournalEvent) -> tuple[datetime, str, str, str]:
    """Total order for journal events; journal_event_id alone is never the key."""
    return (event.occurred_at_utc, event.event_type, event.entity_id, event.journal_event_id)


def _entry_expiry_phase(event: JournalEvent) -> str | None:
    """The allow-listed `phase` of an ENTRY_EXPIRY payload, or None when malformed.

    Only `phase` and `identifier` are read (allow-list, ASVS V5): no payload free
    text is ever copied out. A payload that is not valid JSON, not an object,
    lacks a string `phase`, or names an `identifier` different from the event's
    entity_id is malformed and counted by the caller, never fatal.
    """
    try:
        payload = json.loads(event.payload_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    phase = payload.get("phase")
    if not isinstance(phase, str) or phase == "":
        return None
    identifier = payload.get("identifier")
    if identifier is not None and identifier != event.entity_id:
        return None
    return phase


def _weighted_entry_price(fills: Sequence[Fill]) -> Decimal | None:
    total_qty = Decimal(0)
    notional = Decimal(0)
    for fill in fills:
        total_qty = _add(total_qty, fill.fill_quantity)
        notional = _add(notional, _mul(fill.fill_price, fill.fill_quantity))
    if total_qty == Decimal(0):
        return None
    return _div(notional, total_qty)


def _live_record(
    signal: Signal,
    approval: Approval | None,
    entry_order: Order | None,
    order_fills: Sequence[Fill],
    expired_client_ids: frozenset[str],
) -> LifecycleRecord:
    approval_result = None if approval is None else approval.result
    path = LifecyclePath.SYSTEM_ONLY
    reason_code = ""
    if approval is not None and approval_result is ApprovalResult.APPROVED:
        path = LifecyclePath.USER_EXECUTED
    elif approval is not None and approval_result is ApprovalResult.SKIPPED:
        path = LifecyclePath.OPPORTUNITY
        reason_code = approval.action.value
    elif approval is not None and approval_result is ApprovalResult.EXPIRED:
        path = LifecyclePath.OPPORTUNITY
        reason_code = _EXPIRED_REASON
    approved = path is LifecyclePath.USER_EXECUTED
    order = entry_order if approved else None
    filled = list(order_fills) if order is not None else []
    entry_filled: bool | None = None
    expired_without_fill: bool | None = None
    if order is not None:
        entry_filled = len(filled) > 0
        expired_without_fill = (
            order.client_order_id is not None
            and order.client_order_id in expired_client_ids
            and not filled
        )
    return LifecycleRecord(
        evidence=EvidenceKind.LIVE,
        source_id=signal.signal_id,
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        strategy_version=signal.strategy_version,
        direction=signal.direction,
        path=path,
        approval_result=approval_result,
        signal_detected_at_utc=signal.detected_at_utc,
        # Approval.requested_at_utc is a delivery-REQUEST proxy, not a read receipt.
        delivery_requested_at_utc=None if approval is None else approval.requested_at_utc,
        # Only an APPROVED decision has an approval time; a skip is not "approved".
        approved_at_utc=None if approval is None or not approved else approval.acted_at_utc,
        order_submitted_at_utc=None if order is None else order.submitted_at_utc,
        fill_time_utc=filled[0].fill_time_utc if filled else None,
        intended_entry_price=None if order is None else order.price,
        actual_entry_price=_weighted_entry_price(filled) if filled else None,
        entry_filled=entry_filled,
        expired_without_fill=expired_without_fill,
        reason_code=reason_code,
        synthetic_lag=False,
        epoch_id=None,
    )


def normalize_live_lifecycle(
    signals: Sequence[Signal],
    approvals: Sequence[Approval],
    orders: Sequence[Order],
    fills: Sequence[Fill],
    expiry_events: Sequence[JournalEvent],
) -> LiveLifecycleResult:
    """Normalize live rows into LifecycleRecords with explicit join accounting.

    Every input sequence is sorted by an explicit total key before use, so the
    output is independent of input order. The latest approval per signal (by
    requested_at_utc, approval_id) selects the entry order (order_role ENTRY and
    matching trade_plan_id; the latest submitted wins). Rows that cannot be
    joined are counted in `joins`; malformed rows are counted in `rejected` and
    never raise. No database access: frozen dataclasses in, frozen dataclasses out.
    """
    rejected: dict[str, int] = {}

    def reject(reason: IncompleteReason) -> None:
        rejected[reason.value] = rejected.get(reason.value, 0) + 1

    ordered_signals = sorted(signals, key=lambda item: item.signal_id)
    for previous, current in zip(ordered_signals, ordered_signals[1:], strict=False):
        if previous.signal_id == current.signal_id:
            raise AnalyticsInputError(f"duplicate signal_id {current.signal_id!r}")
    signal_ids = frozenset(item.signal_id for item in ordered_signals)

    ordered_approvals = sorted(
        approvals, key=lambda item: (item.requested_at_utc, item.approval_id)
    )
    latest_approval: dict[str, Approval] = {}
    for decided in ordered_approvals:
        latest_approval[decided.signal_id] = decided
    approval_matched = sum(1 for item in ordered_approvals if item.signal_id in signal_ids)
    plan_ids = frozenset(item.trade_plan_id for item in ordered_approvals)

    ordered_orders = sorted(orders, key=lambda item: (item.submitted_at_utc, item.order_id))
    entry_orders = [item for item in ordered_orders if item.order_role == OrderRole.ENTRY.value]
    entry_matched = sum(
        1
        for item in entry_orders
        if item.trade_plan_id is not None and item.trade_plan_id in plan_ids
    )
    order_ids = frozenset(item.order_id for item in ordered_orders)

    fills_by_order: dict[str, list[Fill]] = {}
    fill_matched = 0
    fill_unmatched = 0
    for fill in sorted(fills, key=lambda item: (item.fill_time_utc, item.fill_id)):
        if fill.fill_quantity <= Decimal(0):
            reject(IncompleteReason.MALFORMED_ROW)
            continue
        if fill.order_id in order_ids:
            fill_matched += 1
            fills_by_order.setdefault(fill.order_id, []).append(fill)
        else:
            fill_unmatched += 1

    entry_client_ids = frozenset(
        item.client_order_id for item in entry_orders if item.client_order_id is not None
    )
    expired_client_ids: set[str] = set()
    expiry_matched = 0
    expiry_unmatched = 0
    for event in sorted(
        (item for item in expiry_events if item.event_type == _ENTRY_EXPIRY_EVENT_TYPE),
        key=_event_sort_key,
    ):
        phase = _entry_expiry_phase(event)
        if phase is None:
            reject(IncompleteReason.MALFORMED_ROW)
            continue
        if phase != _PHASE_POST_CANCEL:
            continue  # pre_cancel / cancel_failed twins are never expiries
        if event.entity_id in entry_client_ids:
            expiry_matched += 1
            expired_client_ids.add(event.entity_id)
        else:
            expiry_unmatched += 1

    records: list[LifecycleRecord] = []
    for signal in ordered_signals:
        if signal.direction not in _DIRECTIONS:
            reject(IncompleteReason.MALFORMED_ROW)
            continue
        approval = latest_approval.get(signal.signal_id)
        entry_order: Order | None = None
        if approval is not None:
            candidates = [o for o in entry_orders if o.trade_plan_id == approval.trade_plan_id]
            entry_order = candidates[-1] if candidates else None
        records.append(
            _live_record(
                signal,
                approval,
                entry_order,
                [] if entry_order is None else fills_by_order.get(entry_order.order_id, []),
                frozenset(expired_client_ids),
            )
        )

    joins = (
        JoinAccount(
            _JOIN_APPROVAL_SIGNAL, approval_matched, len(ordered_approvals) - approval_matched
        ),
        JoinAccount(_JOIN_ENTRY_ORDER_APPROVAL, entry_matched, len(entry_orders) - entry_matched),
        JoinAccount(_JOIN_FILL_ORDER, fill_matched, fill_unmatched),
        JoinAccount(_JOIN_EXPIRY_ORDER, expiry_matched, expiry_unmatched),
    )
    return LiveLifecycleResult(
        records=tuple(records),
        joins=joins,
        rejected=tuple(sorted(rejected.items())),
    )
