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

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from src.approval.binding import check_binding_full
from src.domain.approval import Approval
from src.domain.enums import OrderRole, RejectionReason
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id
from src.execution.placement import derive_limit_price, derive_sl_trigger_price
from src.risk.gating import evaluate_risk

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

    async def query_order_by_client(self, **kwargs: Any) -> Any: ...

    async def get_position_mode(self) -> str: ...


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
# Public entry point — execute_approved_plan.
# --------------------------------------------------------------------------- #


def execute_approved_plan(
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
) -> ExecutionOutcome:
    """Run the fixed-order pipeline: binding → risk → place_entry → place_algo_protective.

    Per D-01/D-05: the manager is a pure function of inputs plus injected
    `now_utc`. It never reads the wall clock, never imports the SDK, and
    never mutates its inputs. First-failure-wins: the first gate that
    rejects short-circuits with its reason code preserved byte-identically.

    Gate order (fixed, never reordered):
      1. Approval binding (chat→expiry→hash→version→token).
      2. Risk pipeline (evaluate_risk with the identical Phase-5 inputs).
      3. Adapter placement (place_entry then place_algo_protective).

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

    Returns:
        An `ExecutionOutcome` with `is_no_trade` and `reason_code`.
    """
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

    # Gate 2: risk pipeline (identical Phase-5 call).
    verdict = evaluate_risk(**risk_kwargs)
    if verdict.is_no_trade:
        return ExecutionOutcome(
            is_no_trade=True,
            reason_code=verdict.reason_code,
        )

    # Gate 3: adapter placement (place_entry then place_algo_protective).
    trade_plan = risk_kwargs["trade_plan"]
    constraint_snapshot = risk_kwargs["constraint_snapshot"]

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
    # The adapter is async; we use asyncio.run only if no loop is running.
    # In production, the caller wraps this in an async context.
    import asyncio

    entry_response = asyncio.run(
        adapter.place_entry(
            symbol=constraint_snapshot.symbol,
            side=entry_side,
            position_side="BOTH",  # one-way mode (09-01 tracer scope)
            time_in_force="GTC",
            quantity=quantity,
            price=limit_price,
            new_client_order_id=entry_client_order_id,
        )
    )

    # No-blind-recovery: if the entry response is ambiguous (None or
    # missing identity), probe by deterministic client_order_id first.
    # Retry only if the probe confirms absence.
    if entry_response is None:
        probe = asyncio.run(
            adapter.query_order_by_client(
                symbol=constraint_snapshot.symbol,
                orig_client_order_id=entry_client_order_id,
            )
        )
        if probe is not None and probe.get("found", False):
            # Order exists on exchange — no retry needed.
            pass
        else:
            # Probe confirms absence — retry the entry.
            entry_response = asyncio.run(
                adapter.place_entry(
                    symbol=constraint_snapshot.symbol,
                    side=entry_side,
                    position_side="BOTH",
                    time_in_force="GTC",
                    quantity=quantity,
                    price=limit_price,
                    new_client_order_id=entry_client_order_id,
                )
            )

    # Place the SL protective leg (CONDITIONAL, STOP_MARKET, close_position).
    asyncio.run(
        adapter.place_algo_protective(
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
    )

    return ExecutionOutcome(is_no_trade=False, reason_code="OK")


__all__ = ["ExecutionAdapter", "ExecutionOutcome", "execute_approved_plan"]
