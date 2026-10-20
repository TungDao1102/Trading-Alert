"""Execution manager — pure orchestration of approve→risk→place (Phase 9, plan 09-01).

Per D-01/D-05: the execution manager is a pure function of inputs plus
injected `now_utc`. It gates every placement on the Phase-8 approval
binding (chat→expiry→hash→version→token), then runs the identical
Phase-5 risk pipeline, then calls the adapter placement surface in
fixed order. First-failure-wins reason codes are preserved byte-identically.

The module is dependency-free: stdlib + `src/approval/*` + `src/risk/*` +
`src/execution/order_ids.py` + `src/execution/placement.py` +
`src/execution/intent_store.py` (a Protocol) + `src/execution/binding.py`,
`src/execution/pre_placement.py`, `src/execution/live_context.py` (Phase 19 pure cores) +
`src/persistence/errors.py` (pure exception classes) only. No Binance SDK, no SQLAlchemy,
no Pydantic, no Polars, no structlog.

Phase 19 (plan 19-13): what the human approved is what the exchange receives. One required
keyword, `live_context` (`LivePlacementContext`), carries the persisted Signal, the plan
constraint snapshot, the execution limits, the protection registry and the injected live
values. The new gates all run BEFORE the approval is consumed, so a refusal leaves no ENTRY
intent row and a later call with corrected inputs can still place; the stored-outcome replay
stays first and never sees them (APRV-02).

Phase 19 (plan 19-15, D-10): the single protection model. The manager places ONLY the LIMIT
entry, as GTD with `goodTillDate` from the plan expiry (the exchange ends the entry itself, D-05),
and hands the acknowledged entry to the protection coordinator through
`live_context.protection_registry.register_resting_entry`. The `closePosition` stop is placed
after the FIRST FILL by `src/execution/protection.py` (Demo rejects it with -4509 while the
position is flat), so there is no entry-time stop and no STOP_LOSS intent here. A hand-off that
fails enters SAFE_MODE (PROTECTION_HANDOFF_FAILED), cancels the entry and returns
RECONCILIATION_REQUIRED. An entry left ENTRY_STATE_UNKNOWN by Q5 is handed over too, flagged
`entry_state_unknown` (19-REVIEW WR-05, owner): its intent stays UNKNOWN, SAFE_MODE stays in
force and the entry is never re-sent; the coordinator protects a fill if the entry turns out to
exist. O-01 stays open: this module does not enable live orders; LIVE stays
blocked until the owner accepts the D055 closure draft and runs the Demo probes.

Phase 17 (D-13/D-14): the approval is consumed durably by writing the ENTRY execution intent
BEFORE `place_entry` runs, through the `ExecutionIntentStore` Protocol (the STOP_LOSS intent of
F-703 is now written by the coordinator before its own `place_algo_protective`). A replayed
APPROVE returns the stored outcome with zero adapter calls, after the identity checks and before
the expiry gate (D-16).

The exchange is NOT a duplicate-entry guard: Binance treats `newClientOrderId` as
unique only among OPEN orders, so a FILLED or CANCELED entry frees its id and a
replay would be accepted again (F-126, F-951). The persisted execution intent is the
guard; the deterministic ids only let a probe find an order whose response was lost.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from src.approval.binding import check_binding_full, check_binding_identity
from src.domain.algo_status import is_protection_confirmed
from src.domain.approval import Approval
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    ExecutionIntentStatus,
    LiveInputsStatus,
    OrderRole,
    RejectionReason,
    TradePlanStatus,
)
from src.domain.exchange_errors import (
    CallKind,
    ExchangeErrorCategory,
    PreSendRefusal,
    classify,
)
from src.domain.journal import JournalEvent, content_hash_event_id
from src.domain.lot_filters import LotFilters
from src.execution.binding import (
    PLAN_SYMBOL_MISMATCH,
    QUANTITY_ABOVE_APPROVED,
    STALE_SETUP,
    bind_plan,
    check_quantity_bound,
    check_snapped_geometry,
    check_working_type,
    take_profit_levels,
)
from src.execution.constraint_snapshot import snapshot_is_valid_for_live
from src.execution.intent_store import ExecutionIntentStore, IntentRecord
from src.execution.live_context import LivePlacementContext
from src.execution.lot_split import lot_filters_from_plan_snapshot
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.execution.placement import (
    ProtectiveTemplate,
    derive_limit_price,
    derive_sl_trigger_price,
    entry_limit_rounding,
    quantize_price,
    size_protectives_to_filled_qty,
    sl_trigger_rounding,
)
from src.execution.pre_placement import (
    LIMITS_NOT_CONFIGURED,
    PrePlacementInputs,
    check_position_mode,
    evaluate_pre_placement,
    good_till_date_ms,
)
from src.execution.protection import RestingEntry
from src.execution.tp_sizing import TakeProfitSizing, size_take_profits
from src.persistence.errors import IntentStateConflict, PersistenceError
from src.risk.cost_rates import FEE_SOURCE_ACCOUNT_MAX, CostRates
from src.risk.gating import evaluate_risk

# --------------------------------------------------------------------------- #
# Live-5 scope guard (09-04): every placement path is scoped to the
# smallest-capital live-5 universe. Non-live-5 symbols raise ValueError
# BEFORE any adapter call — this is a hard scope boundary, not a
# fail-closed reject envelope, because a non-live-5 symbol reaching
# this far is a programming error, not a market condition.
# --------------------------------------------------------------------------- #

LIVE5_SYMBOLS: frozenset[str] = frozenset({"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"})


def _require_live5_symbol(symbol: str) -> None:
    """Raise ValueError before any adapter call for a non-live-5 symbol."""
    if symbol not in LIVE5_SYMBOLS:
        raise ValueError(
            f"symbol {symbol!r} is not in the live-5 universe "
            f"({sorted(LIVE5_SYMBOLS)}) — live placement scope violation"
        )


# --------------------------------------------------------------------------- #
# Protocol-typed adapter surface — the manager never imports the SDK.
# --------------------------------------------------------------------------- #


class ExecutionAdapter(Protocol):
    """The surface the manager calls on the adapter.

    The real `BinanceUsdmAdapter` implements this protocol; tests inject
    a `FakeExecutionAdapter` that records every call. The manager never
    imports the Binance SDK — only the adapter does. Phase 19 (plan 19-13) adds the
    pre-placement reads: the live mark price, the open normal and algo orders and (19-REVIEW
    WR-02) the open positions of the symbol; plan 19-15 adds `error_facts`, the SDK-free route to
    the exchange error taxonomy.
    """

    async def place_entry(self, **kwargs: Any) -> Any: ...

    async def place_algo_protective(self, **kwargs: Any) -> Any: ...

    async def query_order_by_client(self, *, symbol: str, orig_client_order_id: str) -> Any: ...

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any: ...

    async def get_position_mode(self) -> Any: ...

    async def cancel_normal_order(self, *, symbol: str, orig_client_order_id: str) -> Any: ...

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> Any: ...

    async def get_mark_price(self, *, symbol: str) -> Any: ...

    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> Any: ...

    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> Any: ...

    async def snapshot_positions(self, *, symbol: str | None = None) -> Any: ...

    def error_facts(self, exc: BaseException) -> Any:
        """The Phase 18 `ErrorFacts` (class, int code, Retry-After) of `exc`; facts only (D-21)."""
        ...


# --------------------------------------------------------------------------- #
# Outcome envelope — discriminated PASS-or-NO_TRADE with reason code.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExecutionOutcome:
    """The result of `execute_approved_plan`.

    `is_no_trade=True` carries a canonical RejectionReason value in
    `reason_code` (APPROVAL_EXPIRED, STALE_SETUP, INVALIDATED, or any
    risk reason code). `is_no_trade=False` carries reason_code="OK".
    """

    is_no_trade: bool
    reason_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason_code, str) or self.reason_code == "":
            raise ValueError("reason_code must be a non-empty string")
        if self.is_no_trade:
            if self.reason_code == "OK":
                raise ValueError("ExecutionOutcome: is_no_trade=True requires reason_code != 'OK'")
        else:
            if self.reason_code != "OK":
                raise ValueError(
                    f"ExecutionOutcome: is_no_trade=False requires reason_code='OK', "
                    f"got {self.reason_code!r}"
                )


# --------------------------------------------------------------------------- #
# Position-mode mapping (09-REVIEW WR-02).
# --------------------------------------------------------------------------- #

POSITION_MODE_ONE_WAY = "ONE_WAY"
POSITION_MODE_HEDGE = "HEDGE"


def resolve_position_mode(result: Any) -> str:
    """Map the adapter's `PositionModeResult` to "ONE_WAY" / "HEDGE".

    The single mapping point between the adapter's
    `dual_side_position: bool` (True = hedge) and the execution core's
    mode vocabulary. Anything that is not a literal bool raises — an
    unknown account mode must never be guessed.
    """
    dual_side_position = _get_attr_or_key(result, "dual_side_position")
    if not isinstance(dual_side_position, bool):
        raise ValueError(
            f"resolve_position_mode: dual_side_position must be bool, got {dual_side_position!r}"
        )
    return POSITION_MODE_HEDGE if dual_side_position else POSITION_MODE_ONE_WAY


# --------------------------------------------------------------------------- #
# No-blind-recovery entry placement (EXECUTION_SPEC §10, 09-REVIEW CR-09, Q5).
# --------------------------------------------------------------------------- #

_ENTRY_STATE_PLACED = "ENTRY_PLACED"
_ENTRY_STATE_EXISTS = "ENTRY_EXISTS"
_ENTRY_STATE_UNKNOWN = "ENTRY_STATE_UNKNOWN"
# Plan 19-15 (D-21): the two states the Phase 18 taxonomy adds on the entry path.
_ENTRY_STATE_REFUSED = "ENTRY_REFUSED_BEFORE_SEND"
_ENTRY_STATE_REJECTED = "ENTRY_REJECTED_DEFINITIVE"
# The epoch of `goodTillDate` (epoch milliseconds), used to turn it back into a UTC instant.
_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Plain NO_TRADE reason: a request the gate, the drift guard or a missing signed-call policy
# refused before anything reached the exchange (src/WR-02).
ENTRY_REFUSED_BEFORE_SEND: str = "ENTRY_REFUSED_BEFORE_SEND"


@dataclass(frozen=True)
class _EntryPlacement:
    """State of the entry after placement plus the exchange identity, when known."""

    state: str
    exchange_order_id: str | None = None
    exchange_status: str | None = None


def _text_or_none(value: Any) -> str | None:
    """Exchange identity text for the intent row; absent or empty is None."""
    if value is None:
        return None
    text = str(value)
    return text or None


def _placement_failure_category(
    adapter: ExecutionAdapter, exc: BaseException
) -> ExchangeErrorCategory:
    """The taxonomy category of a failed placement, from facts only (D-21).

    The adapter turns the exception into class, int code and Retry-After; `classify` decides
    from those and the call kind. Nothing here reads exception message text. A failure to
    obtain or classify the facts is UNKNOWN_EXCHANGE_ERROR (fail closed).
    """
    try:
        return classify(adapter.error_facts(exc), CallKind.PLACEMENT)
    except Exception:  # noqa: BLE001 — an unclassifiable failure is an unknown one
        return ExchangeErrorCategory.UNKNOWN_EXCHANGE_ERROR


async def _place_entry_no_blind_retry(
    *,
    adapter: ExecutionAdapter,
    entry_kwargs: dict[str, Any],
) -> _EntryPlacement:
    """Place the entry exactly once; on ambiguity probe once by client id (Q5).

    Q5 (owner decision 2026-10-20): each approval sends exactly ONE `place_entry` POST and no
    code path sends it again, whatever the error and whatever the probe answers. There is no
    loop, no recursion and no attempt-count knob here.

    The returned `state` is one of:
      - `ENTRY_PLACED`  — the adapter acknowledged the order.
      - `ENTRY_EXISTS`  — placement was ambiguous but the probe found it.
      - `ENTRY_STATE_UNKNOWN` — placement was ambiguous and the probe found nothing, raised
        or returned an indeterminate result (fail closed: caller enters SAFE_MODE).
      - `ENTRY_REFUSED_BEFORE_SEND` — a `PreSendRefusal` (REST gate pause or ban, entries
        blocked by the drift guard, missing signed-call policy): nothing reached the exchange,
        so no probe (D-21, src/WR-02).
      - `ENTRY_REJECTED_DEFINITIVE` — the exchange answered REJECTED_DEFINITIVE on a placement
        (for example -1106, -4016, -4024): no probe.

    Any other exception from `place_entry` (timeout, 5xx, auth, rate limit, an unmapped
    error) and a `None` response are ambiguous: the order may have been accepted. The probe
    reads `found` by ATTRIBUTE (the real adapter returns an `OrderProbe` dataclass); anything
    other than a literal `True` is not a hand-off.

    Why `found=False` right after an ambiguous error is UNKNOWN and not absence: the client
    order id is unique only among OPEN orders, Binance documents no idempotency and no
    immediate query visibility for a new order, and error -1007 reads "Send status unknown;
    execution status unknown". The entry is a GTD LIMIT and its stop is placed only after a
    fill (D-10), so a resting entry that nobody tracks could fill with no stop. Failing closed
    costs at worst a missed trade. The caller therefore still hands an UNKNOWN entry to the
    protection coordinator (19-REVIEW WR-05), which watches it without ever re-sending it.
    """
    try:
        response = await adapter.place_entry(**entry_kwargs)
    except PreSendRefusal:
        return _EntryPlacement(state=_ENTRY_STATE_REFUSED)
    except Exception as exc:  # noqa: BLE001 — classified by facts; ambiguous ones are probed
        category = _placement_failure_category(adapter, exc)
        if category is ExchangeErrorCategory.REJECTED_DEFINITIVE:
            return _EntryPlacement(state=_ENTRY_STATE_REJECTED)
        response = None
    if response is not None:
        return _EntryPlacement(
            state=_ENTRY_STATE_PLACED,
            exchange_order_id=_text_or_none(
                _get_attr_or_key(response, "exchange_order_id")
                or _get_attr_or_key(response, "order_id")
            ),
            exchange_status=_text_or_none(_get_attr_or_key(response, "status")),
        )
    try:
        probe = await adapter.query_order_by_client(
            symbol=entry_kwargs["symbol"],
            orig_client_order_id=entry_kwargs["new_client_order_id"],
        )
    except Exception:  # noqa: BLE001 — unknown existence fails closed
        return _EntryPlacement(state=_ENTRY_STATE_UNKNOWN)
    if _get_attr_or_key(probe, "found") is True:
        return _EntryPlacement(
            state=_ENTRY_STATE_EXISTS,
            exchange_order_id=_text_or_none(_get_attr_or_key(probe, "order_id")),
            exchange_status=_text_or_none(_get_attr_or_key(probe, "status")),
        )
    return _EntryPlacement(state=_ENTRY_STATE_UNKNOWN)


# --------------------------------------------------------------------------- #
# Approval → plan authorization (09-REVIEW CR-08).
# --------------------------------------------------------------------------- #


def _check_approval_authorizes_plan(
    *,
    callback: Any,
    approval: Approval,
    trade_plan: Any,
    expiry_utc: datetime,
) -> ExecutionOutcome | None:
    """Return a NO_TRADE outcome unless `approval` authorizes `trade_plan`.

    `check_binding_full` (Phase 8) validates chat / expiry / hash /
    version / token, but not the decision itself nor the identity of the
    plan the manager is about to place. This check closes both gaps:

      1. Decision: the approval row must be an APPROVE whose `result`
         AND `status` are APPROVED, and the pressed button (when the
         callback carries it) must be APPROVE. Anything else (SKIP /
         CANCEL / PENDING / REJECTED rows with a valid token) →
         INVALIDATED.
      2. Plan identity: the executed plan's `plan_hash` must equal the
         callback's and the approval's `request_hash`, its
         `trade_plan_id` must equal the approval's, and the expiry the
         binding was checked against must be the plan's OWN
         `expiry_utc` (never a fresher caller-supplied value) →
         otherwise STALE_SETUP.

    Consumption of the approval is the persisted ENTRY execution intent
    (Phase 17, D-13): `execute_approved_plan` writes it through the
    `ExecutionIntentStore` before `place_entry`, so an at-least-once Telegram
    replay re-plays the stored outcome instead of re-running the pipeline.
    This function only decides authorization; it consumes nothing.
    """
    callback_action = getattr(callback, "action", None)
    if (
        approval.action != ApprovalAction.APPROVE
        or approval.result != ApprovalResult.APPROVED
        or approval.status != ApprovalResult.APPROVED
        or (callback_action is not None and callback_action != ApprovalAction.APPROVE)
    ):
        return ExecutionOutcome(is_no_trade=True, reason_code=RejectionReason.INVALIDATED.value)
    if (
        trade_plan.plan_hash != callback.plan_hash
        or trade_plan.plan_hash != approval.request_hash
        or trade_plan.trade_plan_id != approval.trade_plan_id
        or trade_plan.expiry_utc != expiry_utc
    ):
        return ExecutionOutcome(is_no_trade=True, reason_code=RejectionReason.STALE_SETUP.value)
    return None


# The live-state gate inputs the caller supplies (WR-05); everything else
# the placement gates judge is derived from the risk inputs/verdict.
_GATE_KWARG_KEYS: frozenset[str] = frozenset(
    {"open_algo_count", "planned_leg_count", "positions_reconciled"}
)


def _live_cost_rates_are_verified(
    *, cost_rates: CostRates, candidate_symbol: str, now_utc: datetime
) -> bool:
    """True only for ACCOUNT_MAX rates whose commission provenance holds now.

    The label alone is not proof (12-REVIEW WR-01): the rates must carry the
    commission symbol and observation window, the symbol must be the one being
    placed, and `now_utc` must lie inside [observed_at, expires_at] so a
    commission resolved long before approval cannot size a live order.
    """
    if cost_rates.fee_source != FEE_SOURCE_ACCOUNT_MAX:
        return False
    observed = cost_rates.commission_observed_at_utc
    expires = cost_rates.commission_expires_at_utc
    if cost_rates.account_symbol != candidate_symbol or observed is None or expires is None:
        return False
    return observed <= now_utc <= expires


# --------------------------------------------------------------------------- #
# Public entry point — execute_approved_plan.
# --------------------------------------------------------------------------- #


async def execute_approved_plan(
    *,
    callback: Any,
    approval: Approval,
    authorized_chat_id: int,
    expiry_utc: datetime,
    approval_strategy_version: str,
    approval_parameter_set_id: str,
    approval_parameter_set_hash: str,
    now_utc: datetime,
    adapter: ExecutionAdapter,
    risk_kwargs: dict[str, Any],
    safe_mode_controller: Any,
    journal: Any,
    enablement: Any,
    gate_kwargs: dict[str, Any],
    intent_store: ExecutionIntentStore,
    live_context: LivePlacementContext,
) -> ExecutionOutcome:
    """Run the fixed-order pipeline: binding → enablement → SAFE_MODE → gates → risk → place.

    Per D-01/D-03/D-04/D-05: the manager is a pure function of inputs
    plus injected `now_utc`. It never reads the wall clock, never
    imports the SDK, and never mutates its inputs. First-failure-wins:
    the first gate that rejects short-circuits with its reason code
    preserved byte-identically.

    Gate order (fixed, never reordered):
      0. Identity (chat→hash→version→token, `check_binding_identity`), then the
         stored-outcome lookup: an already-consumed approval returns its stored
         outcome with zero adapter calls, even after the plan expiry, and a
         caller that fails identity never learns the stored state (D-15, D-16).
      1. Approval binding (`check_binding_full`; adds the expiry gate).
      1b. Approval authorizes this plan (decision APPROVE, plan hash and id, own expiry).
      1c. Plan binding (Phase 19, D-01..D-04, APRV-01): `bind_plan` re-derives the plan hash,
          ties the plan to its Signal and the approval's strategy version and parameter set,
          and compares the caller's symbol and side with the Signal; then the plan constraint
          snapshot's working type must be MARK_PRICE. Symbol and side used below come from the
          bound plan, never from a caller value.
      2. Enablement guard (LIVE_ORDERS_DISABLED → DISABLED).
      2b. Execution limits ready (D-07, D-13): any NOT_CONFIGURED limit is NO_TRADE
          LIMITS_NOT_CONFIGURED, before SAFE_MODE, risk and every adapter call.
      3. SAFE_MODE guard (`guard_new_entries` → RECONCILIATION_REQUIRED).
      4. Live cost-rate gate (D-11, D-12): `cost_rates.fee_source` must be
         ACCOUNT_MAX, and the commission it was resolved from must be for
         the candidate symbol and still unexpired at `now_utc` (12-REVIEW
         WR-01), else NO_TRADE UNCERTAIN_ACCOUNT_STATE before any risk or
         adapter work.
      5. Risk pipeline (evaluate_risk with the identical Phase-5 inputs).
      6. Placement-time gates (headroom, stale, uncertain, portfolio),
         evaluated on the risk verdict's own `sized` (WR-05).
      Phase 19 pre-placement gates, all BEFORE the approval is consumed (a refusal leaves no
      ENTRY intent row, so a later call with corrected inputs can still place). The pure
      refusals come first (no adapter call), then the four reads, then the position mode:
      5b. Quantity bound (D-02, RISK-04): the sized quantity may not exceed the approved plan
          quantity; it is refused as QUANTITY_ABOVE_APPROVED, never clipped.
      5c. Snapped geometry (D-03): after the tick snap the stop must still sit outside the
          zone (GEOMETRY_INVALID_AFTER_SNAP).
      5d. TP1 sizeable at the sized quantity (O-03 auto default, backtest D-27): the frozen
          protective sizing must accept it, else NO_TRADE with its MIN_QTY_REJECT or
          NOTIONAL_REJECT; there is no single-take-profit fallback.
      5e. Live reads (mark price, open normal orders, open algo orders and open positions of
          the symbol, 19-REVIEW WR-02; a failed read is "not available"), then the injected
          clock (19-REVIEW CR-01), and `evaluate_pre_placement`: plan status, invalidation,
          remaining validity, same-symbol and account-wide unprotected checks, mark price
          (D-05, D-06, D-08, D-09, D-11).
      5f. Position mode (D-02, D-14): an unreadable mode is UNCERTAIN_ACCOUNT_STATE and a
          Hedge account is HEDGE_MODE_UNSUPPORTED, both before anything is consumed.
      7. Consume the approval (ENTRY intent), then place the GTD LIMIT entry and hand it to the
         protection registry (plan 19-15, D-10). No protective order is placed here: the stop
         is placed after the first fill by `src/execution/protection.py`.

    This function exists ONLY to place real orders, so every live-safety
    gate is REQUIRED (09-REVIEW CR-07): there is no `None` default that
    skips enablement, SAFE_MODE, or the placement-time gates (which carry
    the reconciliation check). Backtest/paper use their own entry points.

    Args:
        callback: The Telegram callback payload (from Phase-8 binding).
        approval: The approval row being acted on.
        authorized_chat_id: The chat id authorized for this account.
        expiry_utc: The approval's expiry (from the parent TradePlan).
        approval_strategy_version: The strategy version on the parent.
        approval_parameter_set_id: The parameter set id on the parent.
        approval_parameter_set_hash: The parameter set hash on the parent.
        now_utc: The current UTC-aware datetime (injected for determinism).
        adapter: The Protocol-typed adapter surface.
        risk_kwargs: The kwargs to pass to `evaluate_risk` (trade_plan,
            candidate_position_side, account_state, constraint_snapshot,
            open_positions, daily_loss_quote, now_utc, ttl, cost_rates
            (`CostRates` from `resolve_live_cost_rates`),
            min_stop_distance_rate, max_cost_to_risk,
            minimum_risk_utilization_after_rounding, parameter_set).
        safe_mode_controller: Required `SafeModeController`-like object.
            An entry whose exchange state cannot be determined forces
            SAFE_MODE (EXECUTION_SPEC §10 no-blind-recovery), and an
            acknowledged entry that cannot be handed to the protection
            coordinator forces SAFE_MODE (PROTECTION_HANDOFF_FAILED).
        journal: The journal layer (duck-typed `.record(event)`) used
            for the journal-first cancel of an entry that could not be handed over.
        enablement: Required `LiveEnablementController` for the
            LIVE_ORDERS_DISABLED gate (None raises ValueError).
        gate_kwargs: Required live-state inputs for `decide_placement`
            that the risk inputs do not carry — exactly
            `open_algo_count`, `planned_leg_count` and
            `positions_reconciled` (None or any other key raises
            ValueError). Everything else the gates judge (sized result,
            constraint snapshot, symbol, side, positions, daily loss,
            TTL, parameter set) is taken from `risk_kwargs` / the risk
            verdict and the single `now_utc` (09-REVIEW WR-05), so the
            gates can never judge a different order than the one placed.
        intent_store: Required `ExecutionIntentStore` (None raises
            ValueError; there is no in-memory default, D-02, 09-REVIEW
            CR-07). The approval is consumed by writing the ENTRY intent
            BEFORE `place_entry` (D-13, D-14); a second call with the same
            approval returns the stored outcome with zero adapter calls
            (D-15), even after a restart. The store is synchronous and is
            called directly on the event loop (short indexed queries; the
            engine bounds connect, lock wait, statement, pool checkout and a
            half-open socket with `connect_timeout`, `lock_timeout`,
            `statement_timeout`, `pool_timeout` and TCP keepalives, see
            `src.persistence.engine`; a call can still block the loop for up
            to the longest of those bounds, and Phase 24 may wrap it in
            `asyncio.to_thread`). Store failures fail closed on both sides of
            placement: before the entry is sent a `PersistenceError` returns
            NO_TRADE (`RECONCILIATION_REQUIRED`, or `INVALIDATED` for an
            `IntentStateConflict` at consume, i.e. a second approval of the same
            plan) and nothing is placed; after the entry may exist the manager
            enters SAFE_MODE (`DB_FAILURE`), still hands the entry to the
            protection coordinator (protection outranks the audit row, D034)
            and returns `RECONCILIATION_REQUIRED`. Only `PersistenceError` is
            caught: a crash (any `BaseException`) propagates untouched.

    Returns:
        An `ExecutionOutcome` with `is_no_trade` and `reason_code`.
    """
    _require_safe_mode_controller(safe_mode_controller, "execute_approved_plan")
    if intent_store is None:
        raise ValueError("execute_approved_plan: intent_store is required (fail closed)")
    if live_context is None:
        raise ValueError("execute_approved_plan: live_context is required (fail closed)")
    if not isinstance(live_context, LivePlacementContext):
        raise TypeError("execute_approved_plan: live_context must be a LivePlacementContext")
    if enablement is None:
        raise ValueError("execute_approved_plan: enablement is required (fail closed)")
    if gate_kwargs is None:
        raise ValueError("execute_approved_plan: gate_kwargs is required (fail closed)")
    if set(gate_kwargs) != _GATE_KWARG_KEYS:
        raise ValueError(
            f"execute_approved_plan: gate_kwargs keys must be exactly "
            f"{sorted(_GATE_KWARG_KEYS)}, got {sorted(gate_kwargs)}"
        )
    if risk_kwargs.get("now_utc") != now_utc:
        raise ValueError(
            "execute_approved_plan: risk_kwargs['now_utc'] must equal now_utc "
            "(one clock for binding, risk and gates)"
        )

    # Gate 0 (D-16): identity BEFORE any state lookup. A wrong chat, plan hash,
    # version/parameter set or token is rejected here, so the stored outcome below
    # is never revealed to a caller that cannot prove who it is.
    identity = check_binding_identity(
        callback=callback,
        approval=approval,
        authorized_chat_id=authorized_chat_id,
        approval_strategy_version=approval_strategy_version,
        approval_parameter_set_id=approval_parameter_set_id,
        approval_parameter_set_hash=approval_parameter_set_hash,
    )
    if not identity.ok:
        return ExecutionOutcome(
            is_no_trade=True,
            reason_code=identity.reason_code.value
            if identity.reason_code is not None
            else RejectionReason.INVALIDATED.value,
        )

    # Replay (D-15, Open Q2): an approval whose ENTRY intent already exists was
    # consumed by an earlier call (or process). Return the stored outcome with ZERO
    # adapter calls, BEFORE the expiry gate (an already-executed plan replays after
    # its expiry); the exchange clientOrderId dedup is never consulted. An
    # unreadable store fails closed.
    try:
        stored_entry = intent_store.get_entry(approval_id=approval.approval_id)
    except PersistenceError:
        return _reconciliation_required()
    if stored_entry is not None:
        return _stored_entry_outcome(stored_entry)

    # Gate 1: full approval binding (identity again plus the expiry gate).
    binding = check_binding_full(
        callback=callback,
        approval=approval,
        authorized_chat_id=authorized_chat_id,
        now_utc=now_utc,
        expiry_utc=expiry_utc,
        approval_strategy_version=approval_strategy_version,
        approval_parameter_set_id=approval_parameter_set_id,
        approval_parameter_set_hash=approval_parameter_set_hash,
    )
    if not binding.ok:
        return ExecutionOutcome(
            is_no_trade=True,
            reason_code=binding.reason_code.value
            if binding.reason_code is not None
            else RejectionReason.INVALIDATED.value,
        )

    # Gate 1b (09-REVIEW CR-08): the binding proves the callback belongs
    # to this approval row; it does NOT prove the row is an APPROVE that
    # resolved to APPROVED, nor that the plan about to be executed is the
    # plan that was approved. Both are checked before any order.
    approval_verdict = _check_approval_authorizes_plan(
        callback=callback,
        approval=approval,
        trade_plan=risk_kwargs["trade_plan"],
        expiry_utc=expiry_utc,
    )
    if approval_verdict is not None:
        return approval_verdict

    # Gate 1c (Phase 19, D-01..D-04, APRV-01, F-302): bind the approved plan to the symbol and
    # side that reach the exchange. The TradePlan has neither field, so the persisted Signal
    # supplies them; the plan hash is re-derived, and the caller's symbol and side are only
    # COMPARED with the Signal's, never used. Pure: no adapter call, nothing consumed.
    binding_verdict = bind_plan(
        trade_plan=risk_kwargs["trade_plan"],
        signal=live_context.signal,
        callback_plan_hash=callback.plan_hash,
        approval_request_hash=approval.request_hash,
        approval_strategy_version=approval_strategy_version,
        approval_parameter_set_id=approval_parameter_set_id,
        approval_parameter_set_hash=approval_parameter_set_hash,
        plan_snapshot_symbol=live_context.plan_constraint_snapshot.symbol,
        plan_snapshot_trade_plan_id=live_context.plan_constraint_snapshot.trade_plan_id,
        caller_symbol=risk_kwargs["constraint_snapshot"].symbol,
        caller_side=risk_kwargs["candidate_position_side"],
    )
    if not binding_verdict.ok or binding_verdict.bound is None:
        return ExecutionOutcome(is_no_trade=True, reason_code=binding_verdict.reason_code)
    bound = binding_verdict.bound
    working_type_reason = check_working_type(live_context.plan_constraint_snapshot.working_type)
    if working_type_reason is not None:
        return ExecutionOutcome(is_no_trade=True, reason_code=working_type_reason)

    # Gate 2: enablement guard (LIVE_ORDERS_DISABLED → DISABLED).
    enablement_verdict = enablement.guard_placement(
        plan_hash=approval.trade_plan_id,
    )
    if enablement_verdict.is_no_trade:
        return ExecutionOutcome(
            is_no_trade=True,
            reason_code=enablement_verdict.reason_code or "DISABLED",
        )

    # Gate 2b (D-07, D-13, T-19-34): the owner's execution limits must all be set. No default
    # exists anywhere in src, so an unset file refuses every live and Demo placement here,
    # before SAFE_MODE, risk and any adapter call.
    if live_context.execution_limits.unset_keys():
        return ExecutionOutcome(is_no_trade=True, reason_code=LIMITS_NOT_CONFIGURED)

    # Gate 3: SAFE_MODE guard (09-REVIEW CR-07) — SAFE_MODE blocks new
    # entries even when live orders are still enabled (e.g. right after
    # an ENTRY_WITHOUT_PROTECTIVE divergence).
    safe_mode_verdict = safe_mode_controller.guard_new_entries(trade_plan=risk_kwargs["trade_plan"])
    if safe_mode_verdict.is_no_trade:
        return ExecutionOutcome(
            is_no_trade=True,
            reason_code=safe_mode_verdict.reason_code
            or RejectionReason.RECONCILIATION_REQUIRED.value,
        )

    # Gate 4a: live cost-rate gate. Live never sizes a real order with
    # unverified account fees and never falls back to the parameter rate
    # (D-11, D-12): a PARAMETER source is a NO_TRADE, not a downgrade.
    # Backtest and paper call evaluate_risk directly with PARAMETER rates.
    if "modeled_costs_per_unit" in risk_kwargs:
        raise TypeError(
            "execute_approved_plan: risk_kwargs['modeled_costs_per_unit'] was "
            "removed; pass cost_rates from resolve_live_cost_rates"
        )
    cost_rates = risk_kwargs.get("cost_rates")
    if not isinstance(cost_rates, CostRates):
        raise TypeError(
            "execute_approved_plan: risk_kwargs['cost_rates'] must be a CostRates "
            f"from resolve_live_cost_rates, got {type(cost_rates).__name__}"
        )
    if not _live_cost_rates_are_verified(
        cost_rates=cost_rates,
        candidate_symbol=risk_kwargs["constraint_snapshot"].symbol,
        now_utc=now_utc,
    ):
        return ExecutionOutcome(
            is_no_trade=True,
            reason_code=RejectionReason.UNCERTAIN_ACCOUNT_STATE.value,
        )

    # Gate 4b: risk pipeline (identical Phase-5 call).
    verdict = evaluate_risk(**risk_kwargs)
    if verdict.is_no_trade:
        return ExecutionOutcome(
            is_no_trade=True,
            reason_code=verdict.reason_code,
        )
    sized = verdict.sized
    if sized is None or sized.quantity is None:  # PASS verdict always carries a sized qty
        raise RuntimeError("execute_approved_plan: PASS risk verdict without a sized quantity")

    # Gate 5: placement-time gates (headroom, stale, uncertain, portfolio)
    # judged on EXACTLY what will be placed (09-REVIEW WR-05): the risk
    # verdict's own `sized`, the same constraint snapshot / symbol / side /
    # parameter set / position set, and the manager's single `now_utc`.
    from src.execution.gates import decide_placement

    gate_verdict = decide_placement(
        constraint_snapshot=risk_kwargs["constraint_snapshot"],
        open_algo_count=gate_kwargs["open_algo_count"],
        planned_leg_count=gate_kwargs["planned_leg_count"],
        reconciled_positions=risk_kwargs["open_positions"],
        daily_loss_quote=risk_kwargs["daily_loss_quote"],
        positions_reconciled=gate_kwargs["positions_reconciled"],
        now_utc=now_utc,
        ttl=risk_kwargs["ttl"],
        sized=sized,
        candidate_symbol=risk_kwargs["constraint_snapshot"].symbol,
        candidate_position_side=risk_kwargs["candidate_position_side"],
        parameter_set=risk_kwargs["parameter_set"],
    )
    if gate_verdict.is_no_trade:
        return ExecutionOutcome(
            is_no_trade=True,
            reason_code=gate_verdict.reason_code,
        )

    # Gate 6 setup: the plan, the snapshot and the bound symbol. A symbol outside the live-5
    # universe is a programming error and raises before any adapter call.
    trade_plan = risk_kwargs["trade_plan"]
    constraint_snapshot = risk_kwargs["constraint_snapshot"]
    _require_live5_symbol(bound.symbol)

    # Derive the deterministic entry ID from the plan hash (the SL's `xa-`
    # id is derived inside `_place_protective_leg`).
    entry_client_order_id = derive_client_order_id(
        plan_hash=trade_plan.plan_hash, role=OrderRole.ENTRY.value
    )

    # Derive placement prices (Decimal-only), snapped onto the exchange
    # tick grid (09-REVIEW WR-01): a zone mid can be half a tick off and
    # Binance rejects off-grid prices. BUY limits floor / SELL limits ceil
    # (never pay up); the SL trigger rounds toward the entry (tighter stop,
    # realized risk never exceeds the sized risk).
    candidate_side = bound.side
    limit_price = quantize_price(
        price=derive_limit_price(
            entry_min_price=trade_plan.entry_min_price,
            entry_max_price=trade_plan.entry_max_price,
        ),
        price_tick_size=constraint_snapshot.price_tick_size,
        direction=entry_limit_rounding(candidate_position_side=candidate_side),
    )
    sl_trigger_price = quantize_price(
        price=derive_sl_trigger_price(stop_loss_price=trade_plan.stop_loss_price),
        price_tick_size=constraint_snapshot.price_tick_size,
        direction=sl_trigger_rounding(candidate_position_side=candidate_side),
    )

    # The quantized quantity from the risk verdict.
    quantity: Decimal = sized.quantity

    # The order sides come from the bound plan (Gate 1c), never from a caller value.
    entry_side = bound.entry_side
    sl_side = bound.exit_side

    # Gate 5b (D-02, RISK-04, T-19-32): never place more than the human approved. The sized
    # quantity above the plan quantity is refused whole; there is no clipping. An approved
    # quantity that is not positive can approve nothing, so it is refused the same way.
    if (
        bound.approved_quantity <= Decimal("0")
        or check_quantity_bound(
            placement_quantity=quantity, approved_quantity=bound.approved_quantity
        )
        == QUANTITY_ABOVE_APPROVED
    ):
        return ExecutionOutcome(is_no_trade=True, reason_code=QUANTITY_ABOVE_APPROVED)

    # Gate 5c (D-03, G4-020): the planner knows no tick size, so check the geometry AFTER the
    # snap: the limit stays in the zone and the stop stays strictly outside it.
    geometry_reason = check_snapped_geometry(
        side=bound.side,
        limit_price=limit_price,
        sl_trigger_price=sl_trigger_price,
        entry_min_price=trade_plan.entry_min_price,
        entry_max_price=trade_plan.entry_max_price,
    )
    if geometry_reason is not None:
        return ExecutionOutcome(is_no_trade=True, reason_code=geometry_reason)

    # Gate 5d (O-03 auto default, backtest D-27): the plan needs a sizeable TP1 at the quantity
    # it places. The FROZEN protective sizing is called as is (One-way, the only supported
    # mode); a rejection is the plan's NO_TRADE, with no single-take-profit fallback. A plan
    # whose take-profit levels cannot be read is unusable (fail closed).
    try:
        tp1_trigger_price, tp2_trigger_price = take_profit_levels(trade_plan)
    except ValueError:
        return ExecutionOutcome(is_no_trade=True, reason_code=STALE_SETUP)
    tp_sizing = size_protectives_to_filled_qty(
        filled_quantity=quantity,
        protective_template=ProtectiveTemplate(
            stop_loss_trigger_price=sl_trigger_price,
            tp1_trigger_price=tp1_trigger_price,
            tp2_trigger_price=tp2_trigger_price,
            tp1_quantity_fraction=live_context.tp1_quantity_fraction,
        ),
        constraint_snapshot=constraint_snapshot,
        position_mode=POSITION_MODE_ONE_WAY,
        candidate_position_side=bound.side,
    )
    if tp_sizing.is_no_trade:
        return ExecutionOutcome(is_no_trade=True, reason_code=tp_sizing.reason_code)

    # Gate 5e (D-05, D-06, D-08, D-09, D-11, RISK-04): the four live reads, then the pure
    # pre-placement evaluation. A read that fails is "not available" and refuses (fail
    # closed); nothing here consumes the approval.
    mark_reading = await _read_or_none(lambda: adapter.get_mark_price(symbol=bound.symbol))
    normal_orders = await _read_or_none(
        lambda: adapter.snapshot_open_normal_orders(symbol=bound.symbol)
    )
    algo_orders = await _read_or_none(
        lambda: adapter.snapshot_open_algo_orders(symbol=bound.symbol)
    )
    # 19-REVIEW WR-02: the same-symbol position check reads the exchange, not only the caller's
    # reconciled list (a manual position or one left by an UNKNOWN entry is seen); an unreadable
    # read refuses SYMBOL_STATE_UNAVAILABLE.
    positions = await _read_or_none(lambda: adapter.snapshot_positions(symbol=bound.symbol))
    try:
        any_unprotected = bool(live_context.protection_registry.blocks_new_entries())
    except Exception:  # noqa: BLE001 — an unreadable registry blocks (fail closed)
        any_unprotected = True
    # 19-REVIEW CR-01: the mark age is measured at an instant read from the injected clock
    # AFTER the live reads, never against `now_utc` (taken before them). An unreadable clock is
    # "not available" and refuses.
    mark_checked_at_utc = _clock_or_none(live_context.clock)
    pre_placement_reason = evaluate_pre_placement(
        PrePlacementInputs(
            side=bound.side,
            plan_status=_plan_status(trade_plan),
            signal_invalidated=live_context.signal.invalidated_at_utc is not None,
            trade_plan=trade_plan,
            latest_closed_bar_close=live_context.latest_closed_bar_close,
            expiry_utc=trade_plan.expiry_utc,
            now_utc=now_utc,
            min_remaining_validity_seconds=(
                live_context.execution_limits.min_remaining_validity_seconds
            ),
            gtd_clock_margin=live_context.gtd_clock_margin,
            position_symbols=_position_symbols(
                bound.symbol,
                positions,
                frozenset(p.symbol for p in risk_kwargs["open_positions"]),
            ),
            open_order_symbols=_open_order_symbols(bound.symbol, (normal_orders, algo_orders)),
            any_unprotected=any_unprotected,
            symbol=bound.symbol,
            mark_price=_mark_price_of(mark_reading),
            mark_time_utc=_mark_time_of(mark_reading),
            mark_checked_at_utc=mark_checked_at_utc,
            max_mark_price_age_ms=live_context.execution_limits.max_mark_price_age_ms,
            sl_trigger_price=sl_trigger_price,
            entry_min_price=trade_plan.entry_min_price,
            entry_max_price=trade_plan.entry_max_price,
        )
    )
    if pre_placement_reason is not None:
        return ExecutionOutcome(is_no_trade=True, reason_code=pre_placement_reason)

    # Gate 5f (09-REVIEW WR-02, D-02, D-14): position mode is re-detected at placement time,
    # never assumed. An undeterminable mode fails closed before any order. A Hedge account is
    # refused: Hedge is unverified and not enabled in V1 (the hedge payload builders stay
    # proven offline in tests/test_execution_modes.py).
    try:
        position_mode = resolve_position_mode(await adapter.get_position_mode())
    except Exception:  # noqa: BLE001 — unknown account mode → no order
        return ExecutionOutcome(
            is_no_trade=True, reason_code=RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
        )
    position_mode_reason = check_position_mode(position_mode)
    if position_mode_reason is not None:
        return ExecutionOutcome(is_no_trade=True, reason_code=position_mode_reason)
    order_position_side = "BOTH"  # One-way is the only supported mode past gate 5f.

    # Gate 5g (plan 19-15, D-10): build the hand-off record BEFORE anything is consumed or sent.
    # A plan the protection coordinator would refuse by construction (for example a TP1 share of
    # the whole position) must not reach the exchange only to be cancelled afterwards. Pure: no
    # adapter call, nothing consumed.
    try:
        good_till_ms = good_till_date_ms(trade_plan.expiry_utc)
        resting_entry = RestingEntry(
            approval_id=approval.approval_id,
            trade_plan_id=trade_plan.trade_plan_id,
            plan_hash=trade_plan.plan_hash,
            symbol=bound.symbol,
            side=bound.side,
            entry_side=entry_side,
            exit_side=sl_side,
            entry_client_order_id=entry_client_order_id,
            entry_quantity=quantity,
            sl_trigger_price=sl_trigger_price,
            tp1_trigger_price=tp1_trigger_price,
            tp2_trigger_price=tp2_trigger_price,
            tp1_quantity_fraction=live_context.tp1_quantity_fraction,
            working_type=live_context.plan_constraint_snapshot.working_type,
            position_mode=position_mode,
            plan_constraint_snapshot=live_context.plan_constraint_snapshot,
            snapshot_ttl=risk_kwargs["ttl"],
            registered_at_utc=now_utc,
            # The `goodTillDate` the entry is sent with (19-REVIEW WR-05: the coordinator measures
            # the owner grace of an ENTRY_STATE_UNKNOWN entry from it).
            entry_good_till_utc=_UNIX_EPOCH + timedelta(milliseconds=good_till_ms),
        )
    except (TypeError, ValueError):
        return ExecutionOutcome(is_no_trade=True, reason_code=PROTECTION_INPUTS_INVALID)

    # Write-ahead (D-13, D-14 steps 1-2): consume the approval by committing the
    # ENTRY intent (INTENDED) BEFORE any order leaves. Pre-placement NO_TRADE
    # verdicts above never consume (research Open Q1). Losing the race, or
    # finding the row already there, returns the stored outcome without any
    # order placement. A store failure here fails closed: nothing was sent.
    try:
        consumed = intent_store.consume_and_record_entry_intent(
            approval_id=approval.approval_id,
            trade_plan_id=trade_plan.trade_plan_id,
            plan_hash=trade_plan.plan_hash,
            client_order_id=entry_client_order_id,
            symbol=bound.symbol,
            side=entry_side,
            intended_quantity=quantity,
            intended_price=limit_price,
            now_utc=now_utc,
            sized_realized_risk=sized.realized_risk,
        )
    except IntentStateConflict:
        # A second approval for the same plan (or another unique arbiter): the plan
        # is already spoken for, so this approval cannot authorize an order.
        return ExecutionOutcome(is_no_trade=True, reason_code=RejectionReason.INVALIDATED.value)
    except PersistenceError:
        return _reconciliation_required()
    if not consumed:
        try:
            existing_entry = intent_store.get_entry(approval_id=approval.approval_id)
        except PersistenceError:
            return _reconciliation_required()
        if existing_entry is None:  # lost the race yet nothing stored: fail closed
            return _reconciliation_required()
        return _stored_entry_outcome(existing_entry)

    # Post-consume store handling. Before `place_entry` a store failure only stops the
    # placement; once the entry may exist a store failure enters SAFE_MODE(DB_FAILURE)
    # exactly once and every later store write is skipped (the protective leg is still
    # placed: protection outranks the audit row, D034). Only `PersistenceError` is
    # caught here; a crash (any BaseException) must propagate untouched.
    store_failed = False

    def _enter_safe_mode(reason: str) -> None:
        """Enter SAFE_MODE without letting its audit row abort the protection steps.

        The controller sets its in-memory flag BEFORE journaling, so when the journal
        itself fails (the same database that just failed) only the audit row is lost.
        Protection outranks the audit row (D034, 17-REVIEW CR-01): the stop loss and the
        unprotected-entry cancel must still run. Only `Exception` is caught; a crash
        (any `BaseException`) propagates untouched.
        """
        try:
            safe_mode_controller.enter_safe_mode(reason=reason, now_utc=now_utc)
        except Exception:  # noqa: BLE001, S110 — flag already set; only the audit row is lost
            pass

    def _store_write(write: Callable[[], object]) -> bool:
        """Run one post-acknowledgement store write; False means the store failed."""
        nonlocal store_failed
        if store_failed:
            return False
        try:
            write()
        except PersistenceError:
            store_failed = True
            _enter_safe_mode(_DB_FAILURE)
            return False
        return True

    def _finish(outcome: ExecutionOutcome) -> ExecutionOutcome:
        """Persist the exact outcome on the ENTRY row, then return it (D-15).

        With a failed store the outcome cannot be persisted and the local state is
        not trustworthy, so the caller gets RECONCILIATION_REQUIRED instead.
        """
        recorded = _store_write(
            lambda: intent_store.finalize_entry_outcome(
                approval_id=approval.approval_id,
                is_no_trade=outcome.is_no_trade,
                reason_code=outcome.reason_code,
                now_utc=now_utc,
            )
        )
        return outcome if recorded else _reconciliation_required()

    # Committed SENT before the call: a crash while `place_entry` is in flight
    # leaves a durable row that restart recovery reads as unresolved (F-703).
    try:
        intent_store.mark_sent(
            approval_id=approval.approval_id, role=OrderRole.ENTRY.value, now_utc=now_utc
        )
    except PersistenceError:
        return _reconciliation_required()  # nothing was sent; the INTENDED row stays unresolved

    # Place the entry: LIMIT, GTD with goodTillDate = the plan expiry floored to the second
    # (D-05, T-19-41: the exchange itself ends the entry when the plan expires, even if this
    # process dies). No protective order is sent here (D-10): the closePosition stop is placed
    # by the protection coordinator after the first fill, because Demo rejects it with -4509
    # while the position is flat.
    # 09-REVIEW CR-06: every adapter call is awaited on the caller running event
    # loop (python-telegram-bot / FastAPI). No nested `asyncio.run` — it raises
    # inside a running loop and would tear down loop-bound adapter resources.
    entry_placement = await _place_entry_no_blind_retry(
        adapter=adapter,
        entry_kwargs={
            "symbol": bound.symbol,
            "side": entry_side,
            "position_side": order_position_side,
            "time_in_force": "GTD",
            "good_till_date": good_till_ms,
            "quantity": quantity,
            "price": limit_price,
            "new_client_order_id": entry_client_order_id,
        },
    )
    entry_state = entry_placement.state
    if entry_state == _ENTRY_STATE_UNKNOWN:
        # The probe could not tell, or did not find the order right after an ambiguous error,
        # which is not proof of absence (Q5). The entry is never re-sent; SAFE_MODE
        # ENTRY_STATE_UNKNOWN blocks new entries while reconciliation (Phase 20) resolves the
        # truth, and the intent stays UNKNOWN (never rewritten to ACKED).
        _enter_safe_mode(_ENTRY_STATE_UNKNOWN)
        _store_write(
            lambda: intent_store.record_result(
                approval_id=approval.approval_id,
                role=OrderRole.ENTRY.value,
                status=ExecutionIntentStatus.UNKNOWN,
                exchange_order_id=None,
                exchange_status=None,
                now_utc=now_utc,
            )
        )
        # 19-REVIEW WR-05 (owner): the GTD LIMIT may exist, so it is still handed to the
        # protection coordinator, flagged ENTRY_STATE_UNKNOWN. The coordinator never sends an
        # entry; if it finds the entry open or filled it protects the fill (stop, then cancel
        # the remainder) under SAFE_MODE, and a not-found answer only keeps it waiting. A failed
        # hand-off is handled exactly like the ACKED one below (SAFE_MODE, cancel by id).
        try:
            live_context.protection_registry.register_resting_entry(
                replace(resting_entry, entry_state_unknown=True)
            )
        except Exception:  # noqa: BLE001 — any failure to hand the entry over is fail-closed
            _enter_safe_mode(_PROTECTION_HANDOFF_FAILED)
            try:
                await expire_pending_entry(
                    plan_hash=trade_plan.plan_hash,
                    symbol=bound.symbol,
                    adapter=adapter,
                    journal=journal,
                    now_utc=now_utc,
                    trigger_reason="protection_handoff_failed",
                )
            except Exception:  # noqa: BLE001, S110 — journaled in expire_pending_entry
                pass
        return _finish(_reconciliation_required())
    if entry_state == _ENTRY_STATE_REFUSED:
        # Nothing was sent (a PreSendRefusal): no probe, no SAFE_MODE, nothing to hand off.
        # The ENTRY intent was SENT before the call, so it is closed as REJECTED.
        _store_write(
            lambda: intent_store.record_result(
                approval_id=approval.approval_id,
                role=OrderRole.ENTRY.value,
                status=ExecutionIntentStatus.REJECTED,
                exchange_order_id=None,
                exchange_status=None,
                now_utc=now_utc,
            )
        )
        return _finish(ExecutionOutcome(is_no_trade=True, reason_code=ENTRY_REFUSED_BEFORE_SEND))
    if entry_state == _ENTRY_STATE_REJECTED:
        # Definitively rejected by the exchange, so no exposure exists: NO_TRADE without
        # SAFE_MODE.
        _store_write(
            lambda: intent_store.record_result(
                approval_id=approval.approval_id,
                role=OrderRole.ENTRY.value,
                status=ExecutionIntentStatus.REJECTED,
                exchange_order_id=None,
                exchange_status=None,
                now_utc=now_utc,
            )
        )
        return _finish(
            ExecutionOutcome(
                is_no_trade=True, reason_code=RejectionReason.EXCHANGE_CONSTRAINT.value
            )
        )
    _store_write(
        lambda: intent_store.record_result(
            approval_id=approval.approval_id,
            role=OrderRole.ENTRY.value,
            status=ExecutionIntentStatus.ACKED,
            exchange_order_id=entry_placement.exchange_order_id,
            exchange_status=entry_placement.exchange_status,
            now_utc=now_utc,
        )
    )

    # Hand-off (D-10, T-19-39): the entry is on the exchange (acknowledged or found by the
    # probe), so the protection coordinator takes it from here: on the first fill it writes the
    # STOP_LOSS intent and places the closePosition stop. A store failure above never skips
    # this step (protection outranks the audit row, D034). If the hand-off itself fails nobody
    # would watch the resting entry, so SAFE_MODE is entered FIRST, the entry is cancelled by
    # its deterministic id (journal-first) and the caller gets RECONCILIATION_REQUIRED. The
    # cancel's own failure is journaled inside `expire_pending_entry` and must not mask the
    # outcome: SAFE_MODE is in force and reconciliation resolves any residual exposure.
    try:
        live_context.protection_registry.register_resting_entry(resting_entry)
    except Exception:  # noqa: BLE001 — any failure to hand the entry over is fail-closed
        _enter_safe_mode(_PROTECTION_HANDOFF_FAILED)
        try:
            await expire_pending_entry(
                plan_hash=trade_plan.plan_hash,
                symbol=bound.symbol,
                adapter=adapter,
                journal=journal,
                now_utc=now_utc,
                trigger_reason="protection_handoff_failed",
            )
        except Exception:  # noqa: BLE001, S110 — journaled in expire_pending_entry
            pass
        return _finish(_reconciliation_required())

    return _finish(ExecutionOutcome(is_no_trade=False, reason_code="OK"))


async def _read_or_none(read: Callable[[], Awaitable[Any]]) -> Any:
    """Await one live read; a failed read is `None`, which every consumer treats as unavailable."""
    try:
        return await read()
    except Exception:  # noqa: BLE001 — fail closed: an unreadable value refuses the placement
        return None


def _plan_status(trade_plan: Any) -> TradePlanStatus:
    """The plan lifecycle status; anything else is a programming error (loud, before orders)."""
    status = trade_plan.status
    if not isinstance(status, TradePlanStatus):
        raise TypeError("execute_approved_plan: trade_plan.status must be a TradePlanStatus")
    return status


def _utc_or_none(value: Any) -> datetime | None:
    """A UTC-aware datetime as UTC, or `None` for anything else (naive, wrong type)."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(UTC)


def _clock_or_none(clock: Callable[[], datetime]) -> datetime | None:
    """One reading of the injected clock as UTC; a failing or naive clock is `None` (refuses)."""
    try:
        value = clock()
    except Exception:  # noqa: BLE001 — fail closed: an unreadable clock refuses the placement
        return None
    return _utc_or_none(value)


def _mark_price_of(reading: Any) -> Decimal | None:
    """The mark price of an adapter reading; a missing, non-Decimal or non-positive one is None."""
    price = _get_attr_or_key(reading, "mark_price") if reading is not None else None
    if not isinstance(price, Decimal) or not price.is_finite() or price <= Decimal("0"):
        return None
    return price


def _mark_time_of(reading: Any) -> datetime | None:
    """The exchange time of an adapter reading as UTC, or `None` when it is unusable."""
    if reading is None:
        return None
    return _utc_or_none(_get_attr_or_key(reading, "exchange_time_utc"))


def _open_order_symbols(symbol: str, row_sets: tuple[Any, ...]) -> frozenset[str] | None:
    """The symbols that have an open order, or `None` when any snapshot could not be read.

    A snapshot is unusable unless it is a list or tuple (an empty one is a valid "no orders").
    A row that carries no symbol cannot be told apart from the requested one, so it counts as
    on `symbol` (fail closed).
    """
    symbols: set[str] = set()
    for rows in row_sets:
        if not isinstance(rows, list | tuple):
            return None
        for row in rows:
            row_symbol = _get_attr_or_key(row, "symbol")
            symbols.add(row_symbol if isinstance(row_symbol, str) and row_symbol else symbol)
    return frozenset(symbols)


def _position_symbols(symbol: str, rows: Any, reconciled: frozenset[str]) -> frozenset[str] | None:
    """The symbols with an open position: the live read plus the caller's reconciled list.

    `None` when the live position snapshot could not be read or is not a list or tuple (an
    empty one is a valid "no position"). A row counts unless its amount is a Decimal zero: a
    missing or unreadable amount counts as a position, and a row that carries no symbol counts
    as on `symbol` (fail closed, 19-REVIEW WR-02).
    """
    if not isinstance(rows, list | tuple):
        return None
    symbols: set[str] = set(reconciled)
    for row in rows:
        amount = _get_attr_or_key(row, "position_amt")
        if isinstance(amount, Decimal) and amount.is_finite() and amount == Decimal("0"):
            continue
        row_symbol = _get_attr_or_key(row, "symbol")
        symbols.add(row_symbol if isinstance(row_symbol, str) and row_symbol else symbol)
    return frozenset(symbols)


def _reconciliation_required() -> ExecutionOutcome:
    """The fail-closed outcome for an unreadable or unwritable store (D-04, D034)."""
    return ExecutionOutcome(
        is_no_trade=True, reason_code=RejectionReason.RECONCILIATION_REQUIRED.value
    )


def _stored_entry_outcome(record: IntentRecord) -> ExecutionOutcome:
    """The persisted outcome of an already-consumed approval (D-15).

    An ENTRY row without a recorded outcome (crash between the write-ahead steps and
    `finalize_entry_outcome`) is unresolved: the entry may exist on the exchange, so
    the replay fails closed with RECONCILIATION_REQUIRED and never touches the adapter.
    """
    if record.outcome is not None:
        return ExecutionOutcome(
            is_no_trade=record.outcome.is_no_trade, reason_code=record.outcome.reason_code
        )
    return ExecutionOutcome(
        is_no_trade=True, reason_code=RejectionReason.RECONCILIATION_REQUIRED.value
    )


# --------------------------------------------------------------------------- #
# Protective confirmation (09-04).
#
# Per EXECUTION_SPEC §6: after entry fill, the system must verify the
# expected protective stop exists and is active. If protection cannot
# be confirmed, the reconciler forces SAFE_MODE and the position is
# never assumed protected. The sweeper stays cancel-only and never
# places rescue protection (D-02 for the sweeper). For the position itself D034
# supersedes D-02: the automatic close is src/execution/emergency_close.py.
# --------------------------------------------------------------------------- #

_REQUIRED_PROTECTIVE_ROLES: frozenset[str] = frozenset(
    {OrderRole.STOP_LOSS.value, OrderRole.TAKE_PROFIT_1.value, OrderRole.TAKE_PROFIT_2.value}
)

_ENTRY_WITHOUT_PROTECTIVE: str = "ENTRY_WITHOUT_PROTECTIVE"

# Plain NO_TRADE reason when the hand-off record cannot be built from the approved plan (gate 5g).
PROTECTION_INPUTS_INVALID: str = "PROTECTION_INPUTS_INVALID"

# SAFE_MODE reason when an ACKED entry could not be handed to the protection coordinator
# (plan 19-15, D-10, T-19-39).
_PROTECTION_HANDOFF_FAILED: str = "PROTECTION_HANDOFF_FAILED"

# SAFE_MODE reason when the operational database fails after an entry may exist
# (GLOSSARY section 9.4; the same literal `src/ops/drills.py` uses).
_DB_FAILURE: str = "DB_FAILURE"


@dataclass(frozen=True)
class ProtectiveConfirmationVerdict:
    """Discriminated PASS-or-NO_TRADE envelope for protective confirmation.

    `is_no_trade=True` carries `ENTRY_WITHOUT_PROTECTIVE` in
    `reason_code` — the canonical divergence kind the Phase-8
    reconciler's SAFE_MODE composition consumes (never a rescue
    placement). `is_no_trade=False` carries `reason_code="OK"`.
    """

    is_no_trade: bool
    reason_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason_code, str) or self.reason_code == "":
            raise ValueError("reason_code must be a non-empty string")
        if self.is_no_trade and self.reason_code != _ENTRY_WITHOUT_PROTECTIVE:
            raise ValueError(
                "ProtectiveConfirmationVerdict: is_no_trade=True requires "
                f"reason_code={_ENTRY_WITHOUT_PROTECTIVE!r}"
            )
        if not self.is_no_trade and self.reason_code != "OK":
            raise ValueError(
                "ProtectiveConfirmationVerdict: is_no_trade=False requires reason_code='OK'"
            )


def _require_safe_mode_controller(safe_mode_controller: Any, caller: str) -> None:
    """Fail closed when no SAFE_MODE controller is wired (09-REVIEW CR-02).

    A missing controller would silently drop the ENTRY_WITHOUT_PROTECTIVE
    signal on the most safety-critical path, so it is a programming
    error, raised before any adapter call.
    """
    if safe_mode_controller is None:
        raise ValueError(
            f"{caller}: safe_mode_controller is required (fail closed — an "
            "unprotected entry must always be able to force SAFE_MODE)"
        )


def require_protective_confirmation(
    *,
    confirmed_roles: frozenset[str],
    safe_mode_controller: Any,
    now_utc: datetime,
) -> ProtectiveConfirmationVerdict:
    """Hold ENTRY_WITHOUT_PROTECTIVE when SL/TP1/TP2 are not all confirmed.

    Per EXECUTION_SPEC §6 + D-02: entry fills without a confirmed SL,
    TP1, AND TP2 leg force the reconciler's SAFE_MODE composition via
    `safe_mode_controller.enter_safe_mode(...)`. This function never
    places a rescue order — it only signals the divergence.

    Args:
        confirmed_roles: The set of `OrderRole` values confirmed on the
            exchange (e.g. `{"STOP_LOSS", "TAKE_PROFIT_1"}`).
        safe_mode_controller: Required `SafeModeController`-like object
            (Protocol-typed via duck typing: only `enter_safe_mode` is
            called). `None` raises ValueError (fail closed — the
            ENTRY_WITHOUT_PROTECTIVE signal must never be dropped).
        now_utc: The current UTC-aware datetime (injected, never the
            wall clock).

    Returns:
        `ProtectiveConfirmationVerdict(is_no_trade=False, reason_code="OK")`
        when all three protective roles are confirmed; otherwise
        `ProtectiveConfirmationVerdict(is_no_trade=True,
        reason_code="ENTRY_WITHOUT_PROTECTIVE")`.
    """
    _require_safe_mode_controller(safe_mode_controller, "require_protective_confirmation")
    if _REQUIRED_PROTECTIVE_ROLES.issubset(confirmed_roles):
        return ProtectiveConfirmationVerdict(is_no_trade=False, reason_code="OK")
    safe_mode_controller.enter_safe_mode(reason=_ENTRY_WITHOUT_PROTECTIVE, now_utc=now_utc)
    return ProtectiveConfirmationVerdict(is_no_trade=True, reason_code=_ENTRY_WITHOUT_PROTECTIVE)


# Which algo-order status counts as "exists and active" (EXECUTION_SPEC §6.1)
# is decided by the classification table in `src/domain/algo_status.py`
# (plan 18-06, D-07): only the class ACTIVE confirms protection, and an
# unseen, empty or missing status is UNKNOWN (fail closed).


def _get_attr_or_key(obj: Any, name: str) -> Any:
    """Read `name` from a dataclass-style object or a dict-style payload."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _is_leg_confirmed(response: Any) -> bool:
    """True when a `place_algo_protective` response confirms the leg.

    09-REVIEW WR-03: the real adapter returns an `AlgoPlacementResult`
    DATACLASS (and maps a missing status to ""), so `algo_status` is read
    by attribute OR key, and confirmation asks `is_protection_confirmed`
    (class ACTIVE only, `src/domain/algo_status.py`): `None`, "", every
    status whose class is not ACTIVE and any unknown value are all
    unconfirmed (fail closed, never assume protection exists).
    """
    if response is None:
        return False
    return is_protection_confirmed(_get_attr_or_key(response, "algo_status"))


@dataclass(frozen=True)
class _LegAttempt:
    """How one query-first protective leg placement ended (`_attempt_protective_leg`)."""

    confirmed: bool
    detail: str | None
    placement_error: Exception | None = None


async def _attempt_protective_leg(
    *,
    adapter: ExecutionAdapter,
    symbol: str,
    plan_hash: str,
    role: str,
    leg: dict[str, Any],
) -> _LegAttempt:
    """Place one protective leg query-first; report whether the response confirms it.

    Fail closed (09-REVIEW CR-02): an adapter exception is NOT a confirmation. It is treated
    exactly like an unconfirmed response so the caller always enters SAFE_MODE and returns an
    `AttachOutcome` instead of a bare exception. `detail` records the role and exception TYPE
    only (never the message, which may carry request material); a placement exception is also
    returned so the caller can read it through the error taxonomy (D-21).
    """
    client_algo_id = derive_algo_client_id(plan_hash=plan_hash, role=role)

    # 09-REVIEW CR-04: query-by-ID FIRST. The deterministic `xa-` id is shared with every later
    # attach call for the same plan. Binance only dedups clientAlgoId among OPEN orders, so
    # re-placing an existing leg is rejected as a duplicate. An existing ACTIVE leg is therefore
    # adopted (single owner, no duplicate); an existing NON-active leg (triggered / canceled /
    # expired) is unconfirmed and is not re-placed by this function (the automatic reaction to a
    # lost protective is the coordinator's, D034); an unknown probe outcome fails closed.
    try:
        probe = await adapter.query_algo_order_by_client(client_algo_id=client_algo_id)
    except Exception as exc:  # noqa: BLE001 — unknown existence is unconfirmed
        return _LegAttempt(confirmed=False, detail=f"{role}: probe {type(exc).__name__}")
    probe_found = _get_attr_or_key(probe, "found")
    if probe_found is True:
        status = _get_attr_or_key(probe, "algo_status")
        if is_protection_confirmed(status):
            return _LegAttempt(confirmed=True, detail=None)
        return _LegAttempt(confirmed=False, detail=f"{role}: existing leg status {status!r}")
    if probe_found is not False:
        return _LegAttempt(confirmed=False, detail=f"{role}: probe outcome unknown")

    try:
        response = await adapter.place_algo_protective(
            symbol=symbol,
            client_algo_id=client_algo_id,
            **leg,
        )
    except Exception as exc:  # noqa: BLE001 — any adapter failure is an unconfirmed leg
        return _LegAttempt(
            confirmed=False, detail=f"{role}: {type(exc).__name__}", placement_error=exc
        )
    return _LegAttempt(confirmed=_is_leg_confirmed(response), detail=None)


async def _place_protective_leg(
    *,
    adapter: ExecutionAdapter,
    symbol: str,
    plan_hash: str,
    role: str,
    leg: dict[str, Any],
) -> tuple[bool, str | None]:
    """Place one protective leg; return `(confirmed, failure_detail)` (see `_attempt_...`)."""
    attempt = await _attempt_protective_leg(
        adapter=adapter, symbol=symbol, plan_hash=plan_hash, role=role, leg=leg
    )
    return (attempt.confirmed, attempt.detail)


async def _confirm_leg_by_rest(
    *, adapter: ExecutionAdapter, client_algo_id: str, role: str
) -> tuple[str | None, str | None]:
    """REST-confirm one leg (D-11): `(failure_detail, algo_status)`; ACTIVE class only.

    A placement response, HTTP success or an ALGO_UPDATE alone never counts as protection.
    """
    try:
        probe = await adapter.query_algo_order_by_client(client_algo_id=client_algo_id)
    except Exception as exc:  # noqa: BLE001 — an unreadable leg is unconfirmed
        return (f"{role}: confirm probe {type(exc).__name__}", None)
    status = _get_attr_or_key(probe, "algo_status")
    if _get_attr_or_key(probe, "found") is True and is_protection_confirmed(status):
        return (None, None if status is None else str(status))
    return (f"{role}: not confirmed by REST", None)


@dataclass(frozen=True)
class AttachOutcome:
    """Result of `attach_protectives_to_fill(...)`.

    `is_no_trade=True` carries `NO_FILL`, `PLAN_SYMBOL_MISMATCH` or `ENTRY_WITHOUT_PROTECTIVE`
    in `reason_code` — a position whose take-profit legs could not be placed is ALWAYS
    reported as ENTRY_WITHOUT_PROTECTIVE (09-REVIEW CR-03), even when the root cause is a TP
    sizing rejection. Every no-trade outcome except `NO_FILL` has already entered SAFE_MODE.
    `sized` is the `TakeProfitSizing` used to place the legs; when TP sizing was rejected it is
    the rejected sizing (its `reason_code` carries MIN_QTY_REJECT / NOTIONAL_REJECT).
    `placed_legs` lists the `OrderRole` values confirmed by REST, in the order they were
    confirmed (the adopted STOP_LOSS first). `failure_detail` names the leg role and the
    exception type when a leg placement raised, or the refusal text (audit trail — never the
    exception message, which may carry request material).
    """

    is_no_trade: bool
    reason_code: str
    sized: TakeProfitSizing | None
    placed_legs: tuple[str, ...]
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reason_code, str) or self.reason_code == "":
            raise ValueError("reason_code must be a non-empty string")
        if self.is_no_trade and self.reason_code == "OK":
            raise ValueError("AttachOutcome: is_no_trade=True requires reason_code != 'OK'")
        if not self.is_no_trade and self.reason_code != "OK":
            raise ValueError("AttachOutcome: is_no_trade=False requires reason_code='OK'")


_ONE_WAY_MODE = "ONE_WAY"


def _intent_result_status(
    adapter: ExecutionAdapter, error: Exception | None
) -> ExecutionIntentStatus:
    """REJECTED when nothing was sent or the exchange definitively refused; UNKNOWN otherwise."""
    if isinstance(error, PreSendRefusal):
        return ExecutionIntentStatus.REJECTED
    if error is not None:
        try:
            category = classify(adapter.error_facts(error), CallKind.PLACEMENT)
        except Exception:  # noqa: BLE001 — an unclassifiable failure is ambiguous
            return ExecutionIntentStatus.UNKNOWN
        if category is ExchangeErrorCategory.REJECTED_DEFINITIVE:
            return ExecutionIntentStatus.REJECTED
    return ExecutionIntentStatus.UNKNOWN


async def attach_protectives_to_fill(
    *,
    entry: RestingEntry,
    position_quantity: Decimal,
    live_lot_filters: LotFilters | None,
    adapter: ExecutionAdapter,
    intent_store: ExecutionIntentStore,
    now_utc: datetime,
    safe_mode_controller: Any,
) -> AttachOutcome:
    """Place TP1 and TP2 on a REST-confirmed stop, sized from the real position (plan 19-16).

    The take-profit step of the single protection model (D-10): the protection coordinator calls
    it once the entry is terminal and the closePosition stop is confirmed ACTIVE by REST. It is
    bound to the `RestingEntry` built from the bound plan (D-01): symbol, side, plan hash, trigger
    prices, TP1 fraction, working type and the plan constraint snapshot all come from `entry`;
    an entry whose snapshot or the live filters disagree with it (symbol, trade plan id) is
    refused with `PLAN_SYMBOL_MISMATCH` before any adapter call. Pipeline (fixed order):

      1. Bind check, `position_quantity` check, position-mode check (One-way only, D-14).
      2. The stop: `query_algo_order_by_client` must answer class ACTIVE (D-11). This function
         NEVER places or cancels a stop (D-17, T-19-42); an absent, non-active or unreadable
         stop holds `ENTRY_WITHOUT_PROTECTIVE` + SAFE_MODE and places no take profit.
      3. The plan snapshot must be valid for live (`snapshot_is_valid_for_live`, D-20). A stale
         but COMPLETE snapshot is re-sized with `live_lot_filters` (the live exchangeInfo read of
         the caller); an INCOMPLETE one, or a stale one without live filters, is refused. With
         real data margin type, leverage and equity stay unknown until Phases 21-22, so every
         placement is refused into this hold until then (fail closed, recorded in 19-17).
      4. `size_take_profits` from `position_quantity` (the reconciled REST position, D-18) with
         `entry.tp1_quantity_fraction`; an un-sizeable TP1 (minQty / MIN_NOTIONAL) is the
         CR-03 hold, there is no single-TP fallback (O-03).
      5. Per leg, TP1 then TP2: the intent is written ahead (INTENDED then SENT, TP1 with its
         quantity) BEFORE the placement; the leg is placed query-first by its deterministic
         `xa-` id (an existing ACTIVE leg is adopted, never duplicated); the leg counts as
         confirmed only when a REST query answers ACTIVE, and the intent then becomes ACKED.
         A failed leg stops the sequence (TP2 is not attempted after TP1 fails) and holds
         `ENTRY_WITHOUT_PROTECTIVE`; the confirmed stop and any confirmed leg are kept.

    TP1 is never resized afterwards: the legs are placed only once the entry is terminal
    (G2-032, 19-NOTES "TP legs"). A failing intent write before a placement places nothing for
    that leg; a failing result write after it enters SAFE_MODE(DB_FAILURE) once and keeps the
    confirmed leg (protection outranks the audit row, D034).

    D-17: the earlier claim of this docstring, a blanket D-02 rule that nothing is ever placed
    as a rescue, is corrected. D034 supersedes D-02: the automatic reaction to a lost or
    unconfirmed stop is the separate emergency close (`src/execution/emergency_close.py`, driven
    by the protection coordinator); `emergency_manual_close` keeps its operator role. Neither is
    called from here, and this function itself only adds take-profit legs.

    Args:
        entry: The resting entry built from the bound plan (`RestingEntry`).
        position_quantity: The absolute REST position quantity, a positive Decimal.
        live_lot_filters: The live `LotFilters` of `entry.symbol`, or None.
        adapter: The Protocol-typed adapter surface.
        intent_store: The execution intent store (write-ahead rows of the TP legs).
        now_utc: The current UTC-aware datetime (injected).
        safe_mode_controller: Required `SafeModeController`-like object for the
            ENTRY_WITHOUT_PROTECTIVE composition (None raises ValueError before any adapter call).

    Returns:
        An `AttachOutcome`: OK with `placed_legs == (STOP_LOSS, TAKE_PROFIT_1, TAKE_PROFIT_2)`,
        `NO_FILL` for a non-positive quantity, or a no-trade hold with SAFE_MODE entered.

    Raises:
        TypeError: `entry` is not a `RestingEntry` or `position_quantity` is not a Decimal.
        ValueError: the symbol is not in the live-5 universe or `safe_mode_controller` is None.
    """
    if not isinstance(entry, RestingEntry):
        raise TypeError("attach_protectives_to_fill: entry must be a RestingEntry")
    if not isinstance(position_quantity, Decimal) or not position_quantity.is_finite():
        raise TypeError("attach_protectives_to_fill: position_quantity must be a finite Decimal")
    _require_live5_symbol(entry.symbol)
    _require_safe_mode_controller(safe_mode_controller, "attach_protectives_to_fill")

    def hold(
        detail: str,
        *,
        placed: tuple[str, ...] = (),
        sized: TakeProfitSizing | None = None,
        reason_code: str = _ENTRY_WITHOUT_PROTECTIVE,
    ) -> AttachOutcome:
        # Enters SAFE_MODE with ENTRY_WITHOUT_PROTECTIVE: not all three legs are confirmed.
        require_protective_confirmation(
            confirmed_roles=frozenset(placed),
            safe_mode_controller=safe_mode_controller,
            now_utc=now_utc,
        )
        return AttachOutcome(
            is_no_trade=True,
            reason_code=reason_code,
            sized=sized,
            placed_legs=placed,
            failure_detail=detail,
        )

    # 1. D-01: the entry must agree with its own snapshot and filters, before any adapter call.
    snapshot = entry.plan_constraint_snapshot
    if (
        snapshot.symbol != entry.symbol
        or snapshot.trade_plan_id != entry.trade_plan_id
        or (live_lot_filters is not None and live_lot_filters.symbol != entry.symbol)
    ):
        return hold("entry, plan snapshot and filters disagree", reason_code=PLAN_SYMBOL_MISMATCH)
    if position_quantity <= Decimal("0"):
        return AttachOutcome(is_no_trade=True, reason_code="NO_FILL", sized=None, placed_legs=())
    if entry.position_mode != _ONE_WAY_MODE:
        return hold(f"position mode {entry.position_mode} is not supported")

    # 2. D-11 / D-17: the stop must be ACTIVE by REST; it is adopted, never placed here.
    stop_id = derive_algo_client_id(plan_hash=entry.plan_hash, role=OrderRole.STOP_LOSS.value)
    try:
        stop_probe = await adapter.query_algo_order_by_client(client_algo_id=stop_id)
    except Exception as exc:  # noqa: BLE001 — an unreadable stop is not a confirmed stop
        return hold(f"{OrderRole.STOP_LOSS.value}: probe {type(exc).__name__}")
    stop_found = _get_attr_or_key(stop_probe, "found")
    if stop_found is False:
        return hold(f"{OrderRole.STOP_LOSS.value}: not found")
    if stop_found is not True:
        return hold(f"{OrderRole.STOP_LOSS.value}: probe outcome unknown")
    stop_status = _get_attr_or_key(stop_probe, "algo_status")
    if not is_protection_confirmed(stop_status):
        return hold(f"{OrderRole.STOP_LOSS.value}: existing leg status {stop_status!r}")
    confirmed_roles: list[str] = [OrderRole.STOP_LOSS.value]

    # 3. D-20 / G4-038: snapshot validity, stale-but-complete re-size, incomplete refusal.
    filters: LotFilters | None
    if snapshot_is_valid_for_live(snapshot, now_utc=now_utc, ttl=entry.snapshot_ttl):
        filters = lot_filters_from_plan_snapshot(snapshot)
        if filters is None:  # unreachable for a COMPLETE snapshot; refused rather than guessed
            return hold("plan snapshot filters are unknown", placed=tuple(confirmed_roles))
    elif snapshot.live_inputs_status is not LiveInputsStatus.COMPLETE:
        return hold(
            "plan snapshot is INCOMPLETE and not valid for live", placed=tuple(confirmed_roles)
        )
    elif live_lot_filters is None:
        return hold(
            "plan snapshot is stale and no live filters were read", placed=tuple(confirmed_roles)
        )
    else:
        filters = live_lot_filters

    # 4. D-18 / D-19: TP legs from the reconciled position, floored onto the exchange filters.
    try:
        sizing = size_take_profits(
            position_quantity=position_quantity,
            tp1_trigger_price=entry.tp1_trigger_price,
            tp2_trigger_price=entry.tp2_trigger_price,
            tp1_quantity_fraction=entry.tp1_quantity_fraction,
            filters=filters,
            side=entry.side,
            position_mode=entry.position_mode,
            working_type=entry.working_type,
        )
    except (TypeError, ValueError) as exc:
        return hold(
            f"{OrderRole.TAKE_PROFIT_1.value} sizing: {type(exc).__name__}",
            placed=tuple(confirmed_roles),
        )
    if sizing.is_no_trade:
        # 09-REVIEW CR-03: TP1 is un-sizeable (min-qty / min-notional) but the position exists
        # and its stop is confirmed: keep the stop, hold, carry the rejected sizing for audit.
        return hold(
            f"{OrderRole.TAKE_PROFIT_1.value} sizing: {sizing.reason_code}",
            placed=tuple(confirmed_roles),
            sized=sizing,
        )
    assert sizing.tp1_leg is not None and sizing.tp2_leg is not None  # is_no_trade is False

    # 5. Write-ahead, query-first placement, REST confirmation: TP1, then TP2.
    store_failed = False

    def store_result_write(
        role: str, status: ExecutionIntentStatus, exchange_status: str | None
    ) -> None:
        """A result write after a placement; its failure never undoes a confirmed leg (D034)."""
        nonlocal store_failed
        if store_failed:
            return
        try:
            intent_store.record_result(
                approval_id=entry.approval_id,
                role=role,
                status=status,
                exchange_order_id=None,
                exchange_status=exchange_status,
                now_utc=now_utc,
            )
        except IntentStateConflict:
            return  # the row is already past this state (an earlier attach call)
        except PersistenceError:
            store_failed = True
            try:
                safe_mode_controller.enter_safe_mode(reason=_DB_FAILURE, now_utc=now_utc)
            except Exception:  # noqa: BLE001, S110 — the flag is set first; only its row is lost
                pass

    for role, leg, intended_quantity in (
        (OrderRole.TAKE_PROFIT_1.value, sizing.tp1_leg, sizing.tp1_quantity),
        (OrderRole.TAKE_PROFIT_2.value, sizing.tp2_leg, None),
    ):
        leg_id = derive_algo_client_id(plan_hash=entry.plan_hash, role=role)
        try:
            intent_store.record_protective_intent(
                approval_id=entry.approval_id,
                role=role,
                trade_plan_id=entry.trade_plan_id,
                plan_hash=entry.plan_hash,
                algo_client_id=leg_id,
                symbol=entry.symbol,
                side=entry.exit_side,
                intended_price=leg["trigger_price"],
                now_utc=now_utc,
                intended_quantity=intended_quantity,
            )
            try:
                intent_store.mark_sent(approval_id=entry.approval_id, role=role, now_utc=now_utc)
            except IntentStateConflict:
                pass  # already SENT or past it (an earlier attach call): not a store failure
        except PersistenceError as exc:
            # No durable intent, no order: the leg is not sent (write-ahead, D-20).
            return hold(
                f"{role}: intent store {type(exc).__name__}",
                placed=tuple(confirmed_roles),
                sized=sizing,
            )
        attempt = await _attempt_protective_leg(
            adapter=adapter, symbol=entry.symbol, plan_hash=entry.plan_hash, role=role, leg=leg
        )
        failure = attempt.detail
        exchange_status: str | None = None
        if attempt.confirmed:
            failure, exchange_status = await _confirm_leg_by_rest(
                adapter=adapter, client_algo_id=leg_id, role=role
            )
        if failure is not None or not attempt.confirmed:
            store_result_write(
                role,
                _intent_result_status(adapter, attempt.placement_error),
                None,
            )
            # No further legs are attempted. The confirmed stop (and any confirmed leg) is
            # kept; nothing is cancelled and no stop is placed from here (D-17).
            return hold(
                failure if failure is not None else f"{role}: not confirmed",
                placed=tuple(confirmed_roles),
                sized=sizing,
            )
        store_result_write(role, ExecutionIntentStatus.ACKED, exchange_status)
        confirmed_roles.append(role)

    confirmation = require_protective_confirmation(
        confirmed_roles=frozenset(confirmed_roles),
        safe_mode_controller=safe_mode_controller,
        now_utc=now_utc,
    )
    return AttachOutcome(
        is_no_trade=confirmation.is_no_trade,
        reason_code=confirmation.reason_code,
        sized=sizing,
        placed_legs=tuple(confirmed_roles),
    )


# --------------------------------------------------------------------------- #
# Pending-entry expiry + protective cancel wiring (09-04, EXECUTION_SPEC §4).
# --------------------------------------------------------------------------- #

_EXPIRY_TRIGGERS: frozenset[str] = frozenset(
    {
        "expiry_time",
        "invalidation",
        "superseded_plan",
        "mode_change",
        "operator_close",
        # 09-REVIEW CR-05: the entry was acknowledged but its entry-time
        # SL could not be confirmed — the entry is canceled fail-closed.
        "protective_unconfirmed",
        # Plan 19-15 (D-10, T-19-39): the entry was acknowledged but could not be handed to
        # the protection coordinator — nobody would watch it, so it is canceled fail-closed.
        "protection_handoff_failed",
    }
)


def _build_cancel_event(
    *,
    event_type: str,
    entity_type: str,
    identifier: str,
    symbol: str,
    trigger_reason: str,
    phase: str,
    now_utc: datetime,
    error_type: str | None = None,
) -> JournalEvent:
    """Build one pre/post-cancel JournalEvent (journal-first pattern).

    Mirrors `src/reconcile/sweeper.py`'s pre-image-before / post-image-
    after pattern: the caller journals this event, THEN issues the
    cancel call, THEN journals the post-image twin (or a
    `cancel_failed` twin carrying the exception TYPE — never its message,
    which may carry request material).
    """
    payload: dict[str, str] = {
        "symbol": symbol,
        "identifier": identifier,
        "trigger_reason": trigger_reason,
        "phase": phase,
    }
    if error_type is not None:
        payload["error_type"] = error_type
    payload_json = json.dumps(payload, separators=(",", ":"))
    return JournalEvent(
        # 09-REVIEW WR-09: content-hash id (no same-millisecond PK collision).
        journal_event_id=content_hash_event_id(
            prefix=event_type.lower(),
            event_type=event_type,
            entity_id=identifier,
            occurred_at_utc=now_utc,
            payload_json=payload_json,
        ),
        occurred_at_utc=now_utc,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=identifier,
        correlation_id=f"execution_{event_type.lower()}",
        payload_json=payload_json,
    )


async def expire_pending_entry(
    *,
    plan_hash: str,
    symbol: str,
    adapter: ExecutionAdapter,
    journal: Any,
    now_utc: datetime,
    trigger_reason: str,
) -> None:
    """Cancel a stale pending LIMIT entry via its deterministic `x-` id.

    Per EXECUTION_SPEC §4: an unfilled entry must be canceled on any of
    five triggers — expiry time, invalidation, superseded plan, mode
    change, or operator close. Journals the pre-image BEFORE the cancel
    call and the post-image AFTER (journal-first pattern, D-05
    extended). A failing cancel journals a `cancel_failed` event and
    re-raises (never silently swallowed).

    The cancel goes through the adapter's real
    `cancel_normal_order(*, symbol, orig_client_order_id)` surface
    (09-REVIEW CR-10), which already treats "already canceled" as
    success.

    Args:
        plan_hash: The 64-char SHA-256 plan hash.
        symbol: The live-5 symbol (raises before any adapter call if
            not in `LIVE5_SYMBOLS`).
        adapter: The Protocol-typed adapter surface.
        journal: The journal layer (duck-typed `.record(event)`).
        now_utc: The current UTC-aware datetime (injected).
        trigger_reason: One of the five canonical EXECUTION_SPEC §4
            triggers.

    Raises:
        ValueError: `symbol` is not in the live-5 universe, or
            `trigger_reason` is not a canonical trigger.
        Exception: the adapter cancel error (after journaling it).
    """
    _require_live5_symbol(symbol)
    if trigger_reason not in _EXPIRY_TRIGGERS:
        raise ValueError(
            f"expire_pending_entry: unknown trigger_reason {trigger_reason!r} "
            f"(known: {sorted(_EXPIRY_TRIGGERS)})"
        )
    client_order_id = derive_client_order_id(plan_hash=plan_hash, role=OrderRole.ENTRY.value)

    journal.record(
        _build_cancel_event(
            event_type="ENTRY_EXPIRY",
            entity_type="Order",
            identifier=client_order_id,
            symbol=symbol,
            trigger_reason=trigger_reason,
            phase="pre_cancel",
            now_utc=now_utc,
        )
    )
    try:
        await adapter.cancel_normal_order(symbol=symbol, orig_client_order_id=client_order_id)
    except Exception as exc:
        journal.record(
            _build_cancel_event(
                event_type="ENTRY_EXPIRY",
                entity_type="Order",
                identifier=client_order_id,
                symbol=symbol,
                trigger_reason=trigger_reason,
                phase="cancel_failed",
                now_utc=now_utc,
                error_type=type(exc).__name__,
            )
        )
        raise
    journal.record(
        _build_cancel_event(
            event_type="ENTRY_EXPIRY",
            entity_type="Order",
            identifier=client_order_id,
            symbol=symbol,
            trigger_reason=trigger_reason,
            phase="post_cancel",
            now_utc=now_utc,
        )
    )


async def cancel_untriggered_protectives(
    *,
    plan_hash: str,
    symbol: str,
    adapter: ExecutionAdapter,
    journal: Any,
    now_utc: datetime,
) -> None:
    """Cancel the SL/TP1/TP2 algo legs via their deterministic `xa-` ids.

    Per EXECUTION_SPEC §11 (manual emergency controls) + §4: cancels
    every protective leg by its deterministic algo client id, one at a
    time in SL → TP1 → TP2 order, journaling the pre-image BEFORE and
    the post-image AFTER each cancel call (journal-first pattern).

    Per-leg isolation (09-REVIEW CR-10): one failing cancel never leaves
    the remaining legs live — every leg is attempted, each failure is
    journaled as `cancel_failed`, and all failures are raised together
    as an `ExceptionGroup` after the last leg.

    Args:
        plan_hash: The 64-char SHA-256 plan hash.
        symbol: The live-5 symbol (raises before any adapter call if
            not in `LIVE5_SYMBOLS`).
        adapter: The Protocol-typed adapter surface.
        journal: The journal layer (duck-typed `.record(event)`).
        now_utc: The current UTC-aware datetime (injected).

    Raises:
        ExceptionGroup: one or more leg cancels failed (all legs were
            still attempted).
    """
    _require_live5_symbol(symbol)
    errors: list[Exception] = []
    for role in (
        OrderRole.STOP_LOSS.value,
        OrderRole.TAKE_PROFIT_1.value,
        OrderRole.TAKE_PROFIT_2.value,
    ):
        client_algo_id = derive_algo_client_id(plan_hash=plan_hash, role=role)
        journal.record(
            _build_cancel_event(
                event_type="PROTECTIVE_CANCEL",
                entity_type="OpenAlgoOrder",
                identifier=client_algo_id,
                symbol=symbol,
                trigger_reason=role,
                phase="pre_cancel",
                now_utc=now_utc,
            )
        )
        try:
            await adapter.cancel_algo_order(symbol=symbol, client_algo_id=client_algo_id)
        except Exception as exc:  # noqa: BLE001 — isolate, journal, raise as group
            errors.append(exc)
            journal.record(
                _build_cancel_event(
                    event_type="PROTECTIVE_CANCEL",
                    entity_type="OpenAlgoOrder",
                    identifier=client_algo_id,
                    symbol=symbol,
                    trigger_reason=role,
                    phase="cancel_failed",
                    now_utc=now_utc,
                    error_type=type(exc).__name__,
                )
            )
            continue
        journal.record(
            _build_cancel_event(
                event_type="PROTECTIVE_CANCEL",
                entity_type="OpenAlgoOrder",
                identifier=client_algo_id,
                symbol=symbol,
                trigger_reason=role,
                phase="post_cancel",
                now_utc=now_utc,
            )
        )
    if errors:
        raise ExceptionGroup("cancel_untriggered_protectives: cancel incomplete", errors)


# --------------------------------------------------------------------------- #
# Manual emergency controls (09-04, EXECUTION_SPEC §11).
# --------------------------------------------------------------------------- #


def safe_mode_freeze(*, safe_mode_controller: Any, reason: str, now_utc: datetime) -> None:
    """Switch the system to SAFE_MODE (EXECUTION_SPEC §11 control 4).

    A thin, explicit wrapper over `SafeModeController.enter_safe_mode`
    so the manual-emergency call sites read as EXECUTION_SPEC §11
    controls rather than reconciler internals.
    """
    safe_mode_controller.enter_safe_mode(reason=reason, now_utc=now_utc)


async def emergency_manual_close(
    *,
    plan_hash: str,
    symbol: str,
    adapter: ExecutionAdapter,
    journal: Any,
    enablement: Any,
    safe_mode_controller: Any,
    operator_id: str,
    now_utc: datetime,
) -> None:
    """Run the EXECUTION_SPEC §11 manual emergency control sequence.

    Per EXECUTION_SPEC §11, the tool must provide a safe way to: cancel
    pending strategy orders, disable new live orders, close strategy-
    generated positions per explicit operator action, and switch to
    SAFE_MODE. This function runs all four, in fixed order (never
    reordered) — BLOCKING FIRST (09-REVIEW CR-10), so no cancel failure
    can ever leave new entries enabled:

      1. `enablement.disable(...)` — flip `LIVE_ORDERS_DISABLED` back
         to true (journal-first, per `LiveEnablementController`).
      2. `safe_mode_freeze(...)` — enter SAFE_MODE so monitoring and
         reconciliation continue while entries stay blocked.
      3. `expire_pending_entry` (trigger_reason="operator_close") —
         cancel the pending LIMIT entry, if any.
      4. `cancel_untriggered_protectives` — cancel the SL/TP1/TP2 algo
         legs, if any.

    Every step is isolated: a failure in any step never prevents the
    later steps from running. All failures are raised together as one
    `ExceptionGroup` after the full sequence ran (each cancel failure is
    also journaled by the step itself).

    Closing the strategy-generated POSITION itself (vs. its pending
    orders) is an operator-directed exchange action outside this
    function's adapter surface (`ExecutionAdapter` has no
    close-position method) — the operator closes the position through
    the exchange UI/API directly; this function's job is to make that
    safe by cancelling every order that could otherwise fight the
    manual close.

    Args:
        plan_hash: The 64-char SHA-256 plan hash.
        symbol: The live-5 symbol (raises before any adapter call if
            not in `LIVE5_SYMBOLS`).
        adapter: The Protocol-typed adapter surface.
        journal: The journal layer (duck-typed `.record(event)`).
        enablement: The `LiveEnablementController` (duck-typed
            `.disable(operator_id=..., now_utc=...)`).
        safe_mode_controller: The `SafeModeController` (duck-typed
            `.enter_safe_mode(reason=..., now_utc=...)`).
        operator_id: The operator id performing the manual close
            (audit-trail discipline — never empty).
        now_utc: The current UTC-aware datetime (injected).

    Raises:
        ExceptionGroup: one or more steps failed (every step was still
            attempted, blocking steps first).
    """
    _require_live5_symbol(symbol)
    errors: list[Exception] = []

    # Steps 1-2: block new entries FIRST.
    try:
        enablement.disable(operator_id=operator_id, now_utc=now_utc)
    except Exception as exc:  # noqa: BLE001 — isolate; SAFE_MODE must still run
        errors.append(exc)
    try:
        safe_mode_freeze(
            safe_mode_controller=safe_mode_controller,
            reason="MANUAL_CLOSE",
            now_utc=now_utc,
        )
    except Exception as exc:  # noqa: BLE001 — isolate; cancels must still run
        errors.append(exc)

    # Steps 3-4: cancel pending strategy orders, each step isolated.
    try:
        await expire_pending_entry(
            plan_hash=plan_hash,
            symbol=symbol,
            adapter=adapter,
            journal=journal,
            now_utc=now_utc,
            trigger_reason="operator_close",
        )
    except Exception as exc:  # noqa: BLE001 — isolate; protectives must still be canceled
        errors.append(exc)
    try:
        await cancel_untriggered_protectives(
            plan_hash=plan_hash,
            symbol=symbol,
            adapter=adapter,
            journal=journal,
            now_utc=now_utc,
        )
    except Exception as exc:  # noqa: BLE001 — collected below
        errors.append(exc)

    if errors:
        raise ExceptionGroup("emergency_manual_close: sequence incomplete", errors)


__all__ = [
    "POSITION_MODE_HEDGE",
    "POSITION_MODE_ONE_WAY",
    "resolve_position_mode",
    "ExecutionAdapter",
    "ExecutionOutcome",
    "execute_approved_plan",
    "LIVE5_SYMBOLS",
    "ProtectiveConfirmationVerdict",
    "require_protective_confirmation",
    "AttachOutcome",
    "attach_protectives_to_fill",
    "expire_pending_entry",
    "cancel_untriggered_protectives",
    "safe_mode_freeze",
    "emergency_manual_close",
]
