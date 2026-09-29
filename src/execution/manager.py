"""Execution manager — pure orchestration of approve→risk→place (Phase 9, plan 09-01).

Per D-01/D-05: the execution manager is a pure function of inputs plus
injected `now_utc`. It gates every placement on the Phase-8 approval
binding (chat→expiry→hash→version→token), then runs the identical
Phase-5 risk pipeline, then calls the adapter placement surface in
fixed order. First-failure-wins reason codes are preserved byte-identically.

The module is dependency-free: stdlib + `src/approval/*` + `src/risk/*` +
`src/execution/order_ids.py` + `src/execution/placement.py` only.
No Binance SDK, no SQLAlchemy, no Pydantic, no Polars, no structlog.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from src.approval.binding import check_binding_full
from src.domain.approval import Approval
from src.domain.enums import OrderRole, RejectionReason
from src.domain.journal import JournalEvent
from src.execution.fill_monitor import CurrentPositionView, fold_fills
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.execution.placement import (
    ProtectiveSizing,
    ProtectiveTemplate,
    build_sl_leg,
    derive_limit_price,
    derive_sl_trigger_price,
    size_protectives_to_filled_qty,
)
from src.risk.gating import evaluate_risk
from src.risk.types import ConstraintSnapshot

# --------------------------------------------------------------------------- #
# Live-5 scope guard (09-04): every placement path is scoped to the
# smallest-capital live-5 universe. Non-live-5 symbols raise ValueError
# BEFORE any adapter call — this is a hard scope boundary, not a
# fail-closed reject envelope, because a non-live-5 symbol reaching
# this far is a programming error, not a market condition.
# --------------------------------------------------------------------------- #

LIVE5_SYMBOLS: frozenset[str] = frozenset(
    {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"}
)


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
    """The four-method surface the manager calls on the adapter.

    The real `BinanceUsdmAdapter` implements this protocol; tests inject
    a `FakeExecutionAdapter` that records every call. The manager never
    imports the Binance SDK — only the adapter does.
    """

    async def place_entry(self, **kwargs: Any) -> Any: ...

    async def place_algo_protective(self, **kwargs: Any) -> Any: ...

    async def query_order_by_client(self, *, symbol: str, orig_client_order_id: str) -> Any: ...

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any: ...

    async def get_position_mode(self) -> str: ...

    async def cancel_order(self, *, symbol: str, client_order_id: str) -> Any: ...

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> Any: ...


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
# No-blind-recovery entry placement (EXECUTION_SPEC §10, 09-REVIEW CR-09).
# --------------------------------------------------------------------------- #

_ENTRY_STATE_PLACED = "ENTRY_PLACED"
_ENTRY_STATE_EXISTS = "ENTRY_EXISTS"
_ENTRY_STATE_ABSENT = "ENTRY_ABSENT"
_ENTRY_STATE_UNKNOWN = "ENTRY_STATE_UNKNOWN"

# Total `place_entry` attempts. A retry happens ONLY after a probe by the
# deterministic client id DEFINITIVELY reports the order absent
# (`found is False`); the adapter itself never retries placement.
_ENTRY_MAX_ATTEMPTS: int = 2


async def _place_entry_no_blind_retry(
    *,
    adapter: ExecutionAdapter,
    entry_kwargs: dict[str, Any],
) -> str:
    """Place the entry; on ANY ambiguity probe by client id before retrying.

    Returns one of:
      - `ENTRY_PLACED`  — the adapter acknowledged the order.
      - `ENTRY_EXISTS`  — placement was ambiguous but the probe found it.
      - `ENTRY_ABSENT`  — every attempt was ambiguous and every probe
        DEFINITIVELY reported absence (no exposure exists).
      - `ENTRY_STATE_UNKNOWN` — a probe raised or returned an
        indeterminate result (fail closed: caller enters SAFE_MODE).

    An exception from `place_entry` (timeout, 5xx, rejection, identity-
    less response) and a `None` response are both ambiguous: the order
    may have been accepted. The probe reads `found` by ATTRIBUTE (the
    real adapter returns an `OrderProbe` dataclass) — anything other
    than a literal `True`/`False` is unknown.
    """
    client_order_id = entry_kwargs["new_client_order_id"]
    for _attempt in range(_ENTRY_MAX_ATTEMPTS):
        try:
            response = await adapter.place_entry(**entry_kwargs)
        except Exception:  # noqa: BLE001 — ambiguous: probe decides
            response = None
        if response is not None:
            return _ENTRY_STATE_PLACED
        try:
            probe = await adapter.query_order_by_client(
                symbol=entry_kwargs["symbol"],
                orig_client_order_id=client_order_id,
            )
        except Exception:  # noqa: BLE001 — unknown existence fails closed
            return _ENTRY_STATE_UNKNOWN
        found = _get_attr_or_key(probe, "found")
        if found is True:
            return _ENTRY_STATE_EXISTS
        if found is not False:
            return _ENTRY_STATE_UNKNOWN
        # Definitive absence: the next loop iteration may retry.
    return _ENTRY_STATE_ABSENT


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
    enablement: Any | None = None,
    gate_kwargs: dict[str, Any] | None = None,
) -> ExecutionOutcome:
    """Run the fixed-order pipeline: binding → enablement → gates → risk → place.

    Per D-01/D-03/D-04/D-05: the manager is a pure function of inputs
    plus injected `now_utc`. It never reads the wall clock, never
    imports the SDK, and never mutates its inputs. First-failure-wins:
    the first gate that rejects short-circuits with its reason code
    preserved byte-identically.

    Gate order (fixed, never reordered):
      1. Approval binding (chat→expiry→hash→version→token).
      2. Enablement guard (LIVE_ORDERS_DISABLED → DISABLED).
      3. Placement-time gates (headroom, stale, uncertain, portfolio).
      4. Risk pipeline (evaluate_risk with the identical Phase-5 inputs).
      5. Adapter placement (place_entry then place_algo_protective).

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
            account_state, constraint_snapshot, open_positions,
            daily_loss_quote, ttl, modeled_costs_per_unit,
            minimum_risk_utilization_after_rounding, parameter_set).
        safe_mode_controller: Required `SafeModeController`-like object.
            An entry whose exchange state cannot be determined forces
            SAFE_MODE (EXECUTION_SPEC §10 no-blind-recovery).
        enablement: Optional `LiveEnablementController` for the
            LIVE_ORDERS_DISABLED gate. When None, the gate is skipped
            (backtest/paper compatibility).
        gate_kwargs: Optional kwargs for `decide_placement`
            (open_algo_count, planned_leg_count, reconciled_positions,
            positions_reconciled, sized, candidate_symbol,
            candidate_position_side, parameter_set). When None, the
            gate is skipped (backtest/paper compatibility).

    Returns:
        An `ExecutionOutcome` with `is_no_trade` and `reason_code`.
    """
    _require_safe_mode_controller(safe_mode_controller, "execute_approved_plan")

    # Gate 1: approval binding (chat→expiry→hash→version→token).
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

    # Gate 2: enablement guard (LIVE_ORDERS_DISABLED → DISABLED).
    if enablement is not None:
        enablement_verdict = enablement.guard_placement(
            plan_hash=approval.trade_plan_id,
        )
        if enablement_verdict.is_no_trade:
            return ExecutionOutcome(
                is_no_trade=True,
                reason_code=enablement_verdict.reason_code or "DISABLED",
            )

    # Gate 3: placement-time gates (headroom, stale, uncertain, portfolio).
    if gate_kwargs is not None:
        from src.execution.gates import decide_placement

        gate_verdict = decide_placement(**gate_kwargs)
        if gate_verdict.is_no_trade:
            return ExecutionOutcome(
                is_no_trade=True,
                reason_code=gate_verdict.reason_code,
            )

    # Gate 4: risk pipeline (identical Phase-5 call).
    verdict = evaluate_risk(**risk_kwargs)
    if verdict.is_no_trade:
        return ExecutionOutcome(
            is_no_trade=True,
            reason_code=verdict.reason_code,
        )

    # Gate 5: adapter placement (place_entry then place_algo_protective).
    trade_plan = risk_kwargs["trade_plan"]
    constraint_snapshot = risk_kwargs["constraint_snapshot"]
    _require_live5_symbol(constraint_snapshot.symbol)

    # Derive deterministic IDs from the plan hash.
    entry_client_order_id = derive_client_order_id(
        plan_hash=trade_plan.plan_hash, role=OrderRole.ENTRY.value
    )
    sl_algo_client_id = derive_algo_client_id(
        plan_hash=trade_plan.plan_hash, role=OrderRole.STOP_LOSS.value
    )

    # Derive placement prices (Decimal-only).
    limit_price = derive_limit_price(
        entry_min_price=trade_plan.entry_min_price,
        entry_max_price=trade_plan.entry_max_price,
    )
    sl_trigger_price = derive_sl_trigger_price(stop_loss_price=trade_plan.stop_loss_price)

    # The quantized quantity from the risk verdict.
    assert verdict.sized is not None
    assert verdict.sized.quantity is not None
    quantity: Decimal = verdict.sized.quantity

    # Determine side from the candidate position side.
    candidate_side = risk_kwargs["candidate_position_side"]
    entry_side = "BUY" if candidate_side == "LONG" else "SELL"
    sl_side = "SELL" if candidate_side == "LONG" else "BUY"

    # Place the entry (LIMIT, GTC).
    # 09-REVIEW CR-06: every adapter call is awaited on the caller's
    # running event loop (python-telegram-bot / FastAPI). No nested
    # `asyncio.run` — it raises inside a running loop and would tear
    # down loop-bound adapter resources between the entry and the SL.
    entry_state = await _place_entry_no_blind_retry(
        adapter=adapter,
        entry_kwargs={
            "symbol": constraint_snapshot.symbol,
            "side": entry_side,
            "position_side": "BOTH",  # one-way mode (09-01 tracer scope)
            "time_in_force": "GTC",
            "quantity": quantity,
            "price": limit_price,
            "new_client_order_id": entry_client_order_id,
        },
    )
    if entry_state == _ENTRY_STATE_UNKNOWN:
        # Fail closed: the entry may or may not exist on the exchange and
        # the probe could not tell. No SL, no retry — SAFE_MODE blocks new
        # entries while reconciliation resolves the truth.
        safe_mode_controller.enter_safe_mode(reason=_ENTRY_STATE_UNKNOWN, now_utc=now_utc)
        return ExecutionOutcome(
            is_no_trade=True, reason_code=RejectionReason.RECONCILIATION_REQUIRED.value
        )
    if entry_state == _ENTRY_STATE_ABSENT:
        # Definitively not on the exchange after bounded attempts — no
        # exposure exists, so NO_TRADE without SAFE_MODE.
        return ExecutionOutcome(
            is_no_trade=True, reason_code=RejectionReason.EXCHANGE_CONSTRAINT.value
        )

    # Place the SL protective leg (CONDITIONAL, STOP_MARKET, close_position).
    await adapter.place_algo_protective(
        symbol=constraint_snapshot.symbol,
        side=sl_side,
        algo_type="CONDITIONAL",
        type="STOP_MARKET",
        position_side="BOTH",
        trigger_price=sl_trigger_price,
        close_position=True,
        quantity=None,
        working_type="MARK_PRICE",
        client_algo_id=sl_algo_client_id,
    )

    return ExecutionOutcome(is_no_trade=False, reason_code="OK")


# --------------------------------------------------------------------------- #
# Protective confirmation (09-04).
#
# Per EXECUTION_SPEC §6: after entry fill, the system must verify the
# expected protective stop exists and is active. If protection cannot
# be confirmed, the reconciler forces SAFE_MODE and the position is
# never assumed protected. The sweeper stays cancel-only and never
# places rescue protection (D-02).
# --------------------------------------------------------------------------- #

_REQUIRED_PROTECTIVE_ROLES: frozenset[str] = frozenset(
    {OrderRole.STOP_LOSS.value, OrderRole.TAKE_PROFIT_1.value, OrderRole.TAKE_PROFIT_2.value}
)

_ENTRY_WITHOUT_PROTECTIVE: str = "ENTRY_WITHOUT_PROTECTIVE"


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
                "ProtectiveConfirmationVerdict: is_no_trade=False requires "
                "reason_code='OK'"
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
    return ProtectiveConfirmationVerdict(
        is_no_trade=True, reason_code=_ENTRY_WITHOUT_PROTECTIVE
    )


# Algo-order statuses that count as "exists and active" (EXECUTION_SPEC §6).
# Allow-list, fail closed: anything else (TRIGGERED, FINISHED, CANCELED,
# REJECTED, EXPIRED, "" …) is unconfirmed. "NEW" is the only status the
# repo's recorded fixtures carry for a live untriggered algo order; any
# additional active state must be re-verified against current Binance
# Algo-order docs before it is added here.
_ACTIVE_ALGO_STATUSES: frozenset[str] = frozenset({"NEW"})


def _get_attr_or_key(obj: Any, name: str) -> Any:
    """Read `name` from a dataclass-style object or a dict-style payload."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _is_leg_confirmed(response: Any) -> bool:
    """True when a `place_algo_protective` response confirms the leg.

    A `None` response, or a dict-shaped response carrying a rejected/
    expired/canceled `algo_status`, is treated as unconfirmed
    (fail-closed — never assume protection exists).
    """
    if response is None:
        return False
    if isinstance(response, dict):
        status = response.get("algo_status")
        if status in (None, "REJECTED", "EXPIRED", "CANCELED"):
            return False
        return True
    return True


async def _place_protective_leg(
    *,
    adapter: ExecutionAdapter,
    symbol: str,
    plan_hash: str,
    role: str,
    leg: dict[str, Any],
) -> tuple[bool, str | None]:
    """Place one protective leg; return `(confirmed, failure_detail)`.

    Fail closed (09-REVIEW CR-02): an adapter exception is NOT a
    confirmation. It is treated exactly like an unconfirmed response so
    the caller always enters SAFE_MODE and returns an `AttachOutcome`
    instead of a bare exception. `failure_detail` records the role and
    exception TYPE only (never the message, which may carry request
    material).
    """
    client_algo_id = derive_algo_client_id(plan_hash=plan_hash, role=role)

    # 09-REVIEW CR-04: query-by-ID FIRST. The deterministic `xa-` id is
    # shared with the entry-time SL placed by `execute_approved_plan` and
    # with every later attach call for the same plan (partial fills
    # arrive incrementally). Binance only dedups clientAlgoId among OPEN
    # orders, so re-placing an existing leg is rejected as a duplicate.
    # An existing ACTIVE leg is therefore adopted as confirmed (single
    # owner, no duplicate); an existing NON-active leg (triggered /
    # canceled / expired) is unconfirmed and never re-placed (no rescue
    # placement, D-02); an unknown probe outcome fails closed.
    try:
        probe = await adapter.query_algo_order_by_client(client_algo_id=client_algo_id)
    except Exception as exc:  # noqa: BLE001 — unknown existence is unconfirmed
        return (False, f"{role}: probe {type(exc).__name__}")
    probe_found = _get_attr_or_key(probe, "found")
    if probe_found is True:
        status = _get_attr_or_key(probe, "algo_status")
        if status in _ACTIVE_ALGO_STATUSES:
            return (True, None)
        return (False, f"{role}: existing leg status {status!r}")
    if probe_found is not False:
        return (False, f"{role}: probe outcome unknown")

    try:
        response = await adapter.place_algo_protective(
            symbol=symbol,
            client_algo_id=client_algo_id,
            **leg,
        )
    except Exception as exc:  # noqa: BLE001 — any adapter failure is an unconfirmed leg
        return (False, f"{role}: {type(exc).__name__}")
    return (_is_leg_confirmed(response), None)


@dataclass(frozen=True)
class AttachOutcome:
    """Result of `attach_protectives_to_fill(...)`.

    `is_no_trade=True` carries `NO_FILL` or `ENTRY_WITHOUT_PROTECTIVE`
    in `reason_code` — a fill that could not be fully protected is
    ALWAYS reported as ENTRY_WITHOUT_PROTECTIVE (09-REVIEW CR-03), even
    when the root cause is a TP sizing rejection.
    `sized` is the `ProtectiveSizing` used to place the legs; when TP
    sizing was rejected it is the rejected sizing (its `reason_code`
    carries MIN_QTY_REJECT / NOTIONAL_REJECT / EXCHANGE_CONSTRAINT).
    `placed_legs` lists the `OrderRole` values successfully confirmed on
    the exchange, in the order they were placed. `failure_detail` names
    the leg role and the exception type when a leg placement raised, or
    the TP sizing rejection (audit trail — never the exception message,
    which may carry request material).
    """

    is_no_trade: bool
    reason_code: str
    sized: ProtectiveSizing | None
    placed_legs: tuple[str, ...]
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reason_code, str) or self.reason_code == "":
            raise ValueError("reason_code must be a non-empty string")
        if self.is_no_trade and self.reason_code == "OK":
            raise ValueError(
                "AttachOutcome: is_no_trade=True requires reason_code != 'OK'"
            )
        if not self.is_no_trade and self.reason_code != "OK":
            raise ValueError(
                "AttachOutcome: is_no_trade=False requires reason_code='OK'"
            )


async def attach_protectives_to_fill(
    *,
    fill_events: Sequence[Any],
    current_position_view: CurrentPositionView,
    has_protective: bool,
    protective_template: ProtectiveTemplate,
    constraint_snapshot: ConstraintSnapshot,
    position_mode: str,
    candidate_position_side: str,
    plan_hash: str,
    adapter: ExecutionAdapter,
    now_utc: datetime,
    safe_mode_controller: Any,
) -> AttachOutcome:
    """Fold entry fills, size protectives to filled qty, place + confirm.

    Per D-02 + EXECUTION_SPEC §5/§6: the Wave-3 successor path that
    attaches all three protective legs (SL, TP1, TP2) once real fill
    events arrive — sized against the actual FOLDED filled quantity,
    never the planned quantity. Pipeline (fixed order, never
    reordered):

      1. `fold_fills` — idempotent fold of `fill_events` (replayed or
         out-of-order events collapse to one filled quantity).
      2. `size_protectives_to_filled_qty` — mode-correct SL/TP1/TP2
         leg parameters sized to the folded filled quantity.
      3. Per-leg query-by-ID (`adapter.query_algo_order_by_client`),
         then `adapter.place_algo_protective` only when the leg does not
         exist yet, with a deterministic `xa-` algo client id (SL, then
         TP1, then TP2 — never reordered). An existing ACTIVE leg (e.g.
         the entry-time SL, or a leg from an earlier attach call for the
         same plan) is adopted, never duplicated. NOTE: an existing TP1
         keeps the size of the fill it was first attached to; resizing
         TP1 on later partial fills (cancel-then-replace with a
         versioned id) is a pending design decision (09-REVIEW CR-04).
         Confirmation failure on any leg — including an
         adapter EXCEPTION (timeout, rejection, duplicate id, identity-
         less response) — holds `ENTRY_WITHOUT_PROTECTIVE` immediately
         and forces SAFE_MODE; no further legs are attempted and no
         rescue placement is ever issued (D-02).

    Args:
        fill_events: The fill events to fold (see `fold_fills`).
        current_position_view: The current position view before this
            fold (see `fold_fills`).
        has_protective: Whether a protective was already attached
            before this fold (forwarded to `fold_fills`).
        protective_template: The protective levels + TP1 split.
        constraint_snapshot: The exchangeInfo-derived constraints.
        position_mode: "ONE_WAY" or "HEDGE".
        candidate_position_side: "LONG" or "SHORT".
        plan_hash: The 64-char SHA-256 plan hash (deterministic ID
            derivation).
        adapter: The Protocol-typed adapter surface.
        now_utc: The current UTC-aware datetime (injected).
        safe_mode_controller: Required `SafeModeController`-like object
            for the ENTRY_WITHOUT_PROTECTIVE composition (None raises
            ValueError before any adapter call — fail closed).

    Returns:
        An `AttachOutcome` with the fold+size+place+confirm result.
    """
    _require_live5_symbol(constraint_snapshot.symbol)
    _require_safe_mode_controller(safe_mode_controller, "attach_protectives_to_fill")

    folded = fold_fills(
        fill_events=fill_events,
        current_position_view=current_position_view,
        has_protective=has_protective,
    )
    if folded.filled_quantity <= Decimal("0"):
        return AttachOutcome(
            is_no_trade=True, reason_code="NO_FILL", sized=None, placed_legs=()
        )

    sizing = size_protectives_to_filled_qty(
        filled_quantity=folded.filled_quantity,
        protective_template=protective_template,
        constraint_snapshot=constraint_snapshot,
        position_mode=position_mode,
        candidate_position_side=candidate_position_side,
    )
    if sizing.is_no_trade:
        # 09-REVIEW CR-03: TP1 is un-sizeable (min-qty / min-notional),
        # but a fill EXISTS. The close-all SL does not depend on quantity,
        # so it is always placed first; the missing TP legs then hold
        # ENTRY_WITHOUT_PROTECTIVE + SAFE_MODE (never a plain sizing
        # reason code while a live fill may have no stop). The rejected
        # sizing is carried in `sized` so its reason code stays auditable.
        sl_leg = build_sl_leg(
            protective_template=protective_template,
            position_mode=position_mode,
            candidate_position_side=candidate_position_side,
        )
        sl_confirmed, sl_failure = await _place_protective_leg(
            adapter=adapter,
            symbol=constraint_snapshot.symbol,
            plan_hash=plan_hash,
            role=OrderRole.STOP_LOSS.value,
            leg=sl_leg,
        )
        placed = (OrderRole.STOP_LOSS.value,) if sl_confirmed else ()
        require_protective_confirmation(
            confirmed_roles=frozenset(placed),
            safe_mode_controller=safe_mode_controller,
            now_utc=now_utc,
        )
        return AttachOutcome(
            is_no_trade=True,
            reason_code=_ENTRY_WITHOUT_PROTECTIVE,
            sized=sizing,
            placed_legs=placed,
            failure_detail=(
                sl_failure
                if sl_failure is not None
                else f"{OrderRole.TAKE_PROFIT_1.value} sizing: {sizing.reason_code}"
            ),
        )

    confirmed_roles: list[str] = []
    role_leg_pairs = (
        (OrderRole.STOP_LOSS.value, sizing.sl_leg),
        (OrderRole.TAKE_PROFIT_1.value, sizing.tp1_leg),
        (OrderRole.TAKE_PROFIT_2.value, sizing.tp2_leg),
    )
    for role, leg in role_leg_pairs:
        if leg is None:  # unreachable: sizing.is_no_trade is False
            raise RuntimeError(f"attach_protectives_to_fill: {role} leg missing from sizing")
        confirmed, failure_detail = await _place_protective_leg(
            adapter=adapter,
            symbol=constraint_snapshot.symbol,
            plan_hash=plan_hash,
            role=role,
            leg=leg,
        )
        if not confirmed:
            # Unconfirmed leg: hold ENTRY_WITHOUT_PROTECTIVE immediately.
            # No further legs are attempted; no rescue placement is
            # ever issued (D-02) — the sweeper stays cancel-only.
            require_protective_confirmation(
                confirmed_roles=frozenset(confirmed_roles),
                safe_mode_controller=safe_mode_controller,
                now_utc=now_utc,
            )
            return AttachOutcome(
                is_no_trade=True,
                reason_code=_ENTRY_WITHOUT_PROTECTIVE,
                sized=sizing,
                placed_legs=tuple(confirmed_roles),
                failure_detail=failure_detail,
            )
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
) -> JournalEvent:
    """Build one pre/post-cancel JournalEvent (journal-first pattern).

    Mirrors `src/reconcile/sweeper.py`'s pre-image-before / post-image-
    after pattern: the caller journals this event, THEN issues the
    cancel call, THEN journals the post-image twin.
    """
    payload = {
        "symbol": symbol,
        "identifier": identifier,
        "trigger_reason": trigger_reason,
        "phase": phase,
    }
    return JournalEvent(
        journal_event_id=(
            f"{event_type.lower()}_{phase}_{identifier}_{int(now_utc.timestamp() * 1000)}"
        ),
        occurred_at_utc=now_utc,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=identifier,
        correlation_id=f"execution_{event_type.lower()}",
        payload_json=json.dumps(payload, separators=(",", ":")),
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
    extended).

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
    await adapter.cancel_order(symbol=symbol, client_order_id=client_order_id)
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

    Args:
        plan_hash: The 64-char SHA-256 plan hash.
        symbol: The live-5 symbol (raises before any adapter call if
            not in `LIVE5_SYMBOLS`).
        adapter: The Protocol-typed adapter surface.
        journal: The journal layer (duck-typed `.record(event)`).
        now_utc: The current UTC-aware datetime (injected).
    """
    _require_live5_symbol(symbol)
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
        await adapter.cancel_algo_order(symbol=symbol, client_algo_id=client_algo_id)
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
    reordered):

      1. `expire_pending_entry` (trigger_reason="operator_close") —
         cancel the pending LIMIT entry, if any.
      2. `cancel_untriggered_protectives` — cancel the SL/TP1/TP2 algo
         legs, if any.
      3. `enablement.disable(...)` — flip `LIVE_ORDERS_DISABLED` back
         to true (journal-first, per `LiveEnablementController`).
      4. `safe_mode_freeze(...)` — enter SAFE_MODE so monitoring and
         reconciliation continue while entries stay blocked.

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
    """
    _require_live5_symbol(symbol)
    await expire_pending_entry(
        plan_hash=plan_hash,
        symbol=symbol,
        adapter=adapter,
        journal=journal,
        now_utc=now_utc,
        trigger_reason="operator_close",
    )
    await cancel_untriggered_protectives(
        plan_hash=plan_hash,
        symbol=symbol,
        adapter=adapter,
        journal=journal,
        now_utc=now_utc,
    )
    enablement.disable(operator_id=operator_id, now_utc=now_utc)
    safe_mode_freeze(
        safe_mode_controller=safe_mode_controller,
        reason="MANUAL_CLOSE",
        now_utc=now_utc,
    )


__all__ = [
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
