"""Live-row normalizer: Signal / TradePlan / Order / Fill -> R-valued TradeOutcome
(Phase 10, plan 10-06, JRN-01, RESEARCH P9 / assumption A7, threat T-10-17).

NET PNL DEFINITION (explicit, never implied). For a CLOSED position the net PnL
of one TradePlan is::

    net_pnl = sum(fill.realized_pnl over every fill of the plan)
              - sum(fill.commission over every fill of the plan)

and it is computed ONLY when every fill's `commission_asset` equals `QUOTE_ASSET`
("USDT"). A fill with any other commission asset (e.g. BNB) makes the outcome
INCOMPLETE(COMMISSION_ASSET_NOT_QUOTE): no price conversion is ever attempted and
no converted number is shown. Funding payments are not part of any `Fill`, so
funding is excluded from this net PnL and is stated as excluded, never imputed.
R is then `net_pnl / TradePlan.risk_budget` via the shared Phase-6 R helper; a
non-positive risk budget is INCOMPLETE(NO_RISK_VALUE).

EXCHANGE-SEMANTICS GATE (fail closed). The rule above is only correct if Binance's
`realizedPnl` EXCLUDES commission and `commission` is denominated in
`commissionAsset`. Project rule: exchange semantics are re-verified against the
current official docs and never taken from memory (AGENTS.md, Exchange authority).

Verification attempt recorded for this plan:

- Source: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Account-Trade-List
- Retrieval date: 2026-09-29.
- Result: NOT VERIFIED. The official page is a client-rendered application shell
  (the HTTP body carries no field text; a request with a query string returns an
  empty HTTP 202 challenge) and the legacy binance-docs.github.io site only
  redirects to it, so the field definitions could not be read. The installed
  official SDK (binance-sdk-derivatives-trading-usds-futures) documents the fields
  only as "Realized Pnl." and "Commission."; a third-party mirror of the docs
  defines `commission` as "the fee that was paid on a trade" and
  `commissionAsset` as "the asset the commission fees were deducted from" but
  says nothing about whether `realizedPnl` is gross or net of commission.

Because the semantics are NOT VERIFIED, `LIVE_NET_PNL_SEMANTICS_VERIFIED` is
False and the normalizer fails closed: `realized_pnl` is None for every outcome
and every closed signal is listed with UNVERIFIED_EXCHANGE_SEMANTICS, so live R
renders INCOMPLETE. Price, time and quantity fields stay populated so MFE/MAE and
latency analytics keep working. Flip the flag to True only together with a
recorded citation of the docs text confirming both properties above.

Pure code: frozen domain dataclasses in, frozen dataclasses out, Decimal-only
arithmetic through the pinned helpers, no database, adapter, clock or randomness.
Evidence is always labelled LIVE and is never pooled with other kinds (D-05).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.analytics.types import AnalyticsInputError, EvidenceKind, IncompleteReason, TradeOutcome
from src.core._decimal import _add, _div, _mul, _sub
from src.domain.canonical import sha256_hex
from src.domain.enums import OrderRole
from src.domain.fill import Fill
from src.domain.order import Order
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan

QUOTE_ASSET = "USDT"
# Fail closed until the docs verification described in the module docstring exists.
LIVE_NET_PNL_SEMANTICS_VERIFIED: bool = False
LIVE_NET_PNL_SEMANTICS_NOTE = (
    "Binance realizedPnl / commission semantics NOT VERIFIED against the current "
    "official docs (developers.binance.com Account-Trade-List, retrieval attempt "
    "2026-09-29 could not read the field definitions); live R is INCOMPLETE "
    "(UNVERIFIED_EXCHANGE_SEMANTICS). Funding is excluded from net PnL."
)

_ZERO = Decimal(0)
_DIRECTIONS = frozenset({"LONG", "SHORT"})
_ENTRY_ROLE = OrderRole.ENTRY.value
_EXIT_KINDS: dict[str, str] = {
    OrderRole.STOP_LOSS.value: "SL",
    OrderRole.TAKE_PROFIT_1.value: "TP1",
    OrderRole.TAKE_PROFIT_2.value: "TP2",
}
_ENTRY_KIND = "ENTRY_FILLED"


@dataclass(frozen=True)
class LiveOutcomeResult:
    """Live outcomes (sorted by trade_id) plus signal-level INCOMPLETE listings."""

    outcomes: tuple[TradeOutcome, ...]
    incomplete: tuple[tuple[str, IncompleteReason], ...]

    def digest(self) -> str:
        return sha256_hex(
            {
                "outcomes": [
                    {
                        "evidence": outcome.evidence,
                        "trade_id": outcome.trade_id,
                        "signal_id": outcome.signal_id,
                        "strategy_version": outcome.strategy_version,
                        "parameter_set_hash": outcome.parameter_set_hash,
                        "symbol": outcome.symbol,
                        "direction": outcome.direction,
                        "entry_kind": outcome.entry_kind,
                        "entry_price": outcome.entry_price,
                        "entry_time_utc": outcome.entry_time_utc,
                        "exit_kind": outcome.exit_kind,
                        "exit_price": outcome.exit_price,
                        "exit_time_utc": outcome.exit_time_utc,
                        "quantity": outcome.quantity,
                        "realized_pnl": outcome.realized_pnl,
                        "realized_risk": outcome.realized_risk,
                        "fallback_applied": outcome.fallback_applied,
                    }
                    for outcome in self.outcomes
                ],
                "incomplete": [[signal_id, reason] for signal_id, reason in self.incomplete],
            }
        )


def _fill_key(fill: Fill) -> tuple[datetime, str]:
    return (fill.fill_time_utc, fill.fill_id)


def _total_quantity(fills: Sequence[Fill]) -> Decimal:
    total = _ZERO
    for fill in fills:
        total = _add(total, fill.fill_quantity)
    return total


def _weighted_price(fills: Sequence[Fill]) -> Decimal:
    notional = _ZERO
    for fill in fills:
        notional = _add(notional, _mul(fill.fill_price, fill.fill_quantity))
    return _div(notional, _total_quantity(fills))


def _net_pnl(fills: Sequence[Fill]) -> Decimal:
    gross = _ZERO
    commission = _ZERO
    for fill in fills:
        gross = _add(gross, fill.realized_pnl)
        commission = _add(commission, fill.commission)
    return _sub(gross, commission)


def normalize_live_outcomes(
    signals: Sequence[Signal],
    plans: Sequence[TradePlan],
    orders: Sequence[Order],
    fills: Sequence[Fill],
) -> LiveOutcomeResult:
    """Normalize live rows into LIVE TradeOutcomes under the documented net-PnL rules.

    One candidate per TradePlan with at least one ENTRY-role order that has a fill.
    Every input is ordered by an explicit total key, so output never depends on
    input order. Unmatched fills (no known order) are ignored; the join counting
    stays in the lifecycle normalizer. A duplicate signal_id or trade_plan_id
    fails closed with `AnalyticsInputError`.
    """
    signal_by_id: dict[str, Signal] = {}
    for signal in sorted(signals, key=lambda item: item.signal_id):
        if signal.signal_id in signal_by_id:
            raise AnalyticsInputError(f"duplicate signal_id {signal.signal_id!r}")
        signal_by_id[signal.signal_id] = signal
    ordered_plans = sorted(plans, key=lambda item: item.trade_plan_id)
    for previous, current in zip(ordered_plans, ordered_plans[1:], strict=False):
        if previous.trade_plan_id == current.trade_plan_id:
            raise AnalyticsInputError(f"duplicate trade_plan_id {current.trade_plan_id!r}")

    orders_by_plan: dict[str, list[Order]] = {}
    for order in sorted(orders, key=lambda item: (item.submitted_at_utc, item.order_id)):
        if order.trade_plan_id is not None:
            orders_by_plan.setdefault(order.trade_plan_id, []).append(order)
    fills_by_order: dict[str, list[Fill]] = {}
    for fill in sorted(fills, key=_fill_key):
        fills_by_order.setdefault(fill.order_id, []).append(fill)

    outcomes: list[TradeOutcome] = []
    incomplete: set[tuple[str, IncompleteReason]] = set()
    for plan in ordered_plans:
        plan_orders = orders_by_plan.get(plan.trade_plan_id, [])
        role_by_order = {order.order_id: order.order_role for order in plan_orders}
        entry_fills = sorted(
            (
                fill
                for order in plan_orders
                if order.order_role == _ENTRY_ROLE
                for fill in fills_by_order.get(order.order_id, [])
            ),
            key=_fill_key,
        )
        if not entry_fills:
            continue  # not a candidate: no entry order with a fill
        exit_fills = sorted(
            (
                fill
                for order in plan_orders
                if order.order_role in _EXIT_KINDS
                for fill in fills_by_order.get(order.order_id, [])
            ),
            key=_fill_key,
        )
        owner = signal_by_id.get(plan.signal_id)
        if owner is None:
            incomplete.add((plan.signal_id, IncompleteReason.UNMATCHED_JOIN))
            continue
        if owner.direction not in _DIRECTIONS or any(
            fill.fill_quantity <= _ZERO for fill in (*entry_fills, *exit_fills)
        ):
            incomplete.add((plan.signal_id, IncompleteReason.MALFORMED_ROW))
            continue

        entry_quantity = _total_quantity(entry_fills)
        closed = bool(exit_fills) and _total_quantity(exit_fills) >= entry_quantity
        exit_price: Decimal | None = None
        exit_time: datetime | None = None
        exit_kind: str | None = None
        realized_pnl: Decimal | None = None
        if not closed:
            incomplete.add((plan.signal_id, IncompleteReason.OPEN_POSITION))
        else:
            latest = exit_fills[-1]
            exit_price = _weighted_price(exit_fills)
            exit_time = latest.fill_time_utc
            exit_kind = _EXIT_KINDS[role_by_order[latest.order_id]]
            all_fills = [*entry_fills, *exit_fills]
            quote_only = all(fill.commission_asset == QUOTE_ASSET for fill in all_fills)
            if not quote_only:
                incomplete.add((plan.signal_id, IncompleteReason.COMMISSION_ASSET_NOT_QUOTE))
            if not LIVE_NET_PNL_SEMANTICS_VERIFIED:
                incomplete.add((plan.signal_id, IncompleteReason.UNVERIFIED_EXCHANGE_SEMANTICS))
            elif quote_only:
                realized_pnl = _net_pnl(all_fills)
        realized_risk: Decimal | None = plan.risk_budget
        if plan.risk_budget <= _ZERO:
            realized_risk = None
            incomplete.add((plan.signal_id, IncompleteReason.NO_RISK_VALUE))

        outcomes.append(
            TradeOutcome(
                evidence=EvidenceKind.LIVE,
                trade_id=plan.trade_plan_id,
                signal_id=plan.signal_id,
                strategy_version=owner.strategy_version,
                parameter_set_hash=owner.parameter_set_hash,
                symbol=owner.symbol,
                direction=owner.direction,
                entry_kind=_ENTRY_KIND,
                entry_price=_weighted_price(entry_fills),
                entry_time_utc=entry_fills[0].fill_time_utc,
                exit_kind=exit_kind,
                exit_price=exit_price,
                exit_time_utc=exit_time,
                quantity=entry_quantity,
                realized_pnl=realized_pnl,
                realized_risk=realized_risk,
                fallback_applied=False,
            )
        )
    return LiveOutcomeResult(
        outcomes=tuple(outcomes),
        incomplete=tuple(sorted(incomplete, key=lambda item: (item[0], item[1].value))),
    )
