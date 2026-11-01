"""The signal source of the live process: a Protocol and the Demo-smoke injector (D-18, OQ-2).

Phase 24, plan 24-14 (research C-4; owner answer 24-01 Q4 of 2026-10-31). The live topology had
no producer of a Signal and a TradePlan. `SignalSource` is that seam: the live loop asks it for
the next `SignalRequest` and hands the request to the approval request sender
(`src/live/approval_sender.py`). Per the owner's answer only ONE implementation ships here, the
Demo-smoke injector. A strategy-driven DEMO source (the SHADOW chain's detector feeding the same
Protocol) stays with the owner-named later phase and is NOT built or imported here: the
paper pipeline is not imported by this module.

`DemoSmokeSignalSource` derives the plan the way `scripts/demo_rehearsal.py:derive_plan` does
(that derivation moved behind the Protocol; the rehearsal is switched to this module by plan
24-29 and is not edited here). Every price, rate and quantity is a `Decimal`. The plan is a LONG
on the symbol whose entry sits on the PERCENT_PRICE band (scenario `far`, never fills) or just
above the mark (scenario `fill`), sized as the smallest quantity that passes the exchange
minimums, and the UNMODIFIED risk pipeline (`evaluate_risk`) is run on it: the equity is
back-solved so the pipeline returns exactly that quantity, and a pipeline that disagrees raises
`SignalDerivationError` instead of producing a request.

Identity (P-8): the Signal and TradePlan ids derive from the namespace `demo-smoke:v1`, the run
id, the symbol and a per-source sequence number. They can never equal a SHADOW id, which is the
content hash of the strategy identity tuple (`src.domain.ids.make_signal_id`). The rows start as
the lifecycle expects them: the Signal DETECTED (the sender moves it to NOTIFIED once the card is
sent, the D028 chain moves it on), the TradePlan APPROVAL_PENDING.

`SignalRequest.latest_closed_bar_close` travels with the plan: `LivePlacementContext` needs it at
placement. The money inputs travel too (`MoneyInputs`): the sender builds the money block from
the SIZED result of the pipeline, never from a recomputation (F-015).

No wall clock is read here: the instant of a derivation is an argument.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from typing import Any, Final, Protocol

from src.adapters.binance_public import SymbolFilters
from src.adapters.binance_usdm import CommissionRates
from src.backtest.semantics import TP1_QUANTITY_FRACTION
from src.core.planner import plan_hash_from_fields
from src.core.types import AccountState
from src.domain.canonical import sha256_hex
from src.domain.enums import QuantizationDecision, SignalStatus, TradePlanStatus
from src.domain.registry import ParameterSet
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.execution.manager import LIVE5_SYMBOLS
from src.execution.placement import PRICE_ROUND_DOWN, PRICE_ROUND_UP, quantize_price
from src.execution.symbol_config_guard import TARGET_LEVERAGE
from src.risk.cost_rates import (
    FEE_SOURCE_PARAMETER,
    CostRates,
    per_unit_round_trip_cost,
)
from src.risk.gating import evaluate_risk
from src.risk.live_commission import AccountCommission, resolve_live_cost_rates
from src.risk.money_at_stake import (
    EQUITY_SOURCE_PAPER_CONFIG,
    LEVERAGE_SOURCE_PAPER_CONFIG,
    MoneyAtStake,
    build_money_at_stake,
)
from src.risk.portfolio import resolve_absolute_thresholds
from src.risk.types import ConstraintSnapshot, SizedResult

DEMO_SMOKE_SETUP: Final = "DEMO_SMOKE"
DEMO_SMOKE_NAMESPACE: Final = "demo-smoke:v1"
DEMO_SMOKE_PLAN_VERSION: Final = "demo-smoke-v1"
DEMO_SMOKE_REASON_CODES: Final[tuple[str, ...]] = ("DEMO_ONLY", "DEMO_SMOKE")

SCENARIO_FAR: Final = "far"
SCENARIO_FILL: Final = "fill"
SCENARIOS: Final = (SCENARIO_FAR, SCENARIO_FILL)

# Rehearsal values (SR-4), named in one block so an operator can audit them. They are not
# strategy parameters and no backtest result chose them.
FAR_BAND_FRACTION: Final = Decimal("0.5")  # fraction of the PERCENT_PRICE band for the entry
# The entry zone reaches this far past the derive-time mark on the near side, so the live mark
# read at the pre-placement gate (after the approval tap) can still sit inside the zone.
MARK_ZONE_CUSHION_RATE: Final = Decimal("0.005")
SL_DISTANCE_RATE: Final = Decimal("0.015")
TP1_DISTANCE_RATE: Final = Decimal("0.03")
TP2_DISTANCE_RATE: Final = Decimal("0.06")
PLAN_EXPIRY_MARGIN: Final = timedelta(minutes=10)
SIGNAL_TIMEFRAME: Final = "1h"
_QUANTITY_SEARCH_LIMIT: Final = 10000
_PORTFOLIO_KEYS: Final = (
    "max_open_positions",
    "max_aggregate_open_risk",
    "cluster_cap",
    "daily_loss_warning_threshold",
    "daily_loss_stop_threshold",
)
_RR_PLACES: Final = Decimal("0.00000001")
_ONE: Final = Decimal("1")
_ZERO: Final = Decimal("0")


class SignalDerivationError(ValueError):
    """The smoke plan cannot be derived from the inputs (fail closed: no request exists)."""


@dataclass(frozen=True, kw_only=True)
class MoneyInputs:
    """What the sender needs to build the money block of one request, exactly once.

    `sized` is the output of the unmodified risk pipeline for the plan. `equity` is the equity the
    pipeline sized with. The smoke injector back-solves it (a rehearsal input), so its label is
    the configuration source, never `ACCOUNT_LIVE`.
    """

    sized: SizedResult
    take_profits: tuple[tuple[Decimal, Decimal], ...]
    cost_rates: CostRates
    equity: Decimal
    equity_observed_at_utc: datetime
    equity_source: str
    leverage: int
    leverage_source: str


@dataclass(frozen=True, kw_only=True)
class SignalRequest:
    """One approval request: the Signal and TradePlan rows to persist and what travels with them."""

    signal: Signal
    plan: TradePlan
    latest_closed_bar_close: datetime
    money_inputs: MoneyInputs
    exposure_quote: Decimal
    reason_codes: tuple[str, ...]
    # Plan 24-27: the PRICE the invalidation rule compares with the SL level at placement.
    # `latest_closed_bar_close` above is the bar's time; the Demo smoke has no strategy bar, so
    # it stands in the mark price it derived the plan from (a rehearsal input, not a market
    # fact). None means "not available" and the manager's invalidation check refuses.
    bar_close_price: Decimal | None = None


class SignalSource(Protocol):
    """Where approval requests come from.

    `next_request` returns the next request, or None when there is none right now. It never
    blocks. The live loop polls it; a source holds its own queue.
    """

    async def next_request(self) -> SignalRequest | None: ...


def build_request_money(request: SignalRequest) -> MoneyAtStake:
    """The money block of a request, built from the SIZED result carried with it (F-015).

    Raises:
        MoneyAtStakeUnavailable: a needed input is missing or unusable.
    """
    inputs = request.money_inputs
    return build_money_at_stake(
        side=request.signal.direction,
        sized=inputs.sized,
        stop_loss_price=request.plan.stop_loss_price,
        take_profits=list(inputs.take_profits),
        cost_rates=inputs.cost_rates,
        leverage=inputs.leverage,
        leverage_source=inputs.leverage_source,
        equity=inputs.equity,
        equity_source=inputs.equity_source,
        equity_observed_at_utc=inputs.equity_observed_at_utc,
    )


def demo_smoke_signal_id(*, run_id: str, symbol: str, sequence: int) -> str:
    """The Signal id of one smoke request: namespaced, so it is never a SHADOW id (P-8)."""
    return sha256_hex(
        {
            "namespace": DEMO_SMOKE_NAMESPACE,
            "run_id": run_id,
            "symbol": symbol,
            "sequence": sequence,
            "role": "signal",
        }
    )


def demo_smoke_trade_plan_id(signal_id: str) -> str:
    """The TradePlan id of one smoke request, derived from its Signal id."""
    return sha256_hex({"namespace": DEMO_SMOKE_NAMESPACE, "signal_id": signal_id, "role": "plan"})


def _ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value // step) * step


def _resolve_rates(
    *, parameter_set: ParameterSet, commission: CommissionRates, observed_at: datetime
) -> CostRates:
    """Live cost rates from the account commission (fail closed, never a zero fee)."""
    params = parameter_set.params
    parameter_rates = CostRates(
        fee_rate_entry=params["fee_rate_entry"],
        entry_slippage_rate=params["expected_slippage"],
        fee_rate_exit=params["fee_rate_exit"],
        exit_slippage_rate=params["exit_slippage_rate"],
        fee_source=FEE_SOURCE_PARAMETER,
    )
    resolved = resolve_live_cost_rates(
        parameter_rates=parameter_rates,
        account_commission=AccountCommission(
            symbol=commission.symbol,
            maker_rate=commission.maker_rate,
            taker_rate=commission.taker_rate,
            observed_at_utc=observed_at,
        ),
        candidate_symbol=commission.symbol,
        now_utc=observed_at,
        ttl=timedelta(seconds=int(params["commission_rate_ttl_seconds"])),
    )
    if resolved.rates is None:
        raise SignalDerivationError(f"live cost rates unavailable: {resolved.reason_code}")
    return resolved.rates


def _risk_kwargs(
    *,
    parameter_set: ParameterSet,
    trade_plan: TradePlan,
    constraints: ConstraintSnapshot,
    cost_rates: CostRates,
    equity: Decimal,
    risk_rate: Decimal,
    now_utc: datetime,
) -> dict[str, Any]:
    """The `evaluate_risk` inputs, with the five portfolio thresholds resolved to quote amounts."""
    params = parameter_set.params
    portfolio: dict[str, Any] = {key: params[key] for key in _PORTFOLIO_KEYS}
    return {
        "trade_plan": trade_plan,
        "candidate_position_side": "LONG",
        "account_state": AccountState(equity=equity, risk_rate=risk_rate),
        "constraint_snapshot": constraints,
        "open_positions": [],
        "daily_loss_quote": _ZERO,
        "now_utc": now_utc,
        "ttl": timedelta(seconds=int(params["constraint_snapshot_ttl_seconds"])),
        "cost_rates": cost_rates,
        "min_stop_distance_rate": params["min_stop_distance_rate"],
        "max_cost_to_risk": params["max_cost_to_risk"],
        "minimum_risk_utilization_after_rounding": params[
            "minimum_risk_utilization_after_rounding"
        ],
        "parameter_set": resolve_absolute_thresholds(parameter_set=portfolio, equity=equity),
    }


def _json(payload: Mapping[str, str]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class DemoSmokeSignalSource:
    """The one `SignalSource` of plan 24-14: requests injected by the Demo smoke, in order.

    `derive_request` builds a request from live Demo readings (exchange filters, the mark price,
    the account commission, the latest closed bar); `inject` queues one; `next_request` hands the
    queued requests out one at a time, oldest first, and returns None when the queue is empty.
    `submit` is `derive_request` then `inject`.
    """

    def __init__(
        self,
        *,
        run_id: str,
        parameter_set: ParameterSet,
        symbol: str = "BTCUSDT",
        approval_timeout_seconds: int = 300,
        leverage: int = TARGET_LEVERAGE,
    ) -> None:
        if not run_id:
            raise ValueError("run_id must not be empty")
        if symbol not in LIVE5_SYMBOLS:
            raise SignalDerivationError(f"{symbol} is not in the live-5 universe")
        if approval_timeout_seconds <= 0:
            raise ValueError("approval_timeout_seconds must be positive")
        if leverage < 1 or leverage > TARGET_LEVERAGE:
            raise ValueError(f"leverage must be within 1..{TARGET_LEVERAGE}")
        self._run_id = run_id
        self._parameter_set = parameter_set
        self._symbol = symbol
        self._approval_timeout_seconds = approval_timeout_seconds
        self._leverage = leverage
        self._sequence = 0
        self._queue: deque[SignalRequest] = deque()

    @property
    def pending(self) -> int:
        return len(self._queue)

    def inject(self, request: SignalRequest) -> None:
        """Queue one request (the smoke feeds the source; nothing is persisted or sent here)."""
        self._queue.append(request)

    def submit(
        self,
        *,
        scenario: str,
        filters: SymbolFilters,
        mark_price: Decimal,
        commission: CommissionRates,
        observed_at: datetime,
        latest_closed_bar_close: datetime,
    ) -> SignalRequest:
        """Derive one request and queue it. Returns the queued request."""
        request = self.derive_request(
            scenario=scenario,
            filters=filters,
            mark_price=mark_price,
            commission=commission,
            observed_at=observed_at,
            latest_closed_bar_close=latest_closed_bar_close,
        )
        self.inject(request)
        return request

    async def next_request(self) -> SignalRequest | None:
        return self._queue.popleft() if self._queue else None

    def derive_request(
        self,
        *,
        scenario: str,
        filters: SymbolFilters,
        mark_price: Decimal,
        commission: CommissionRates,
        observed_at: datetime,
        latest_closed_bar_close: datetime,
    ) -> SignalRequest:
        """Derive the plan and prove the unmodified risk pipeline sizes exactly it.

        Raises:
            SignalDerivationError: the inputs cannot give a plan that passes the exchange
                minimums, the zone contains no mark, or the risk pipeline disagrees.
        """
        if scenario not in SCENARIOS:
            raise SignalDerivationError(f"unknown scenario {scenario!r}")
        symbol = self._symbol
        if filters.symbol != symbol or commission.symbol != symbol:
            raise SignalDerivationError("filters and commission must belong to the source symbol")
        if mark_price <= _ZERO:
            raise SignalDerivationError("the mark price must be positive")
        params = self._parameter_set
        up = filters.percent_price_multiplier_up
        down = filters.percent_price_multiplier_down
        if scenario == SCENARIO_FILL:
            if up is None:
                raise SignalDerivationError("PERCENT_PRICE multiplierUp is missing")
            raw_entry = mark_price * (_ONE + (up - _ONE) * FAR_BAND_FRACTION)
        else:
            if down is None:
                raise SignalDerivationError("PERCENT_PRICE multiplierDown is missing")
            raw_entry = mark_price * (_ONE - (_ONE - down) * FAR_BAND_FRACTION)
        tick = filters.price_tick_size
        step = filters.quantity_step_size
        entry = quantize_price(price=raw_entry, price_tick_size=tick, direction=PRICE_ROUND_DOWN)
        # The risk pipeline sizes a LONG at the adverse zone edge `entry_max` (Phase 12 D-03).
        # The zone contains the mark for both scenarios; its mid is exactly `entry`, the price the
        # manager places at. Both edges are on the tick grid.
        if scenario == SCENARIO_FILL:
            entry_min = quantize_price(
                price=mark_price * (_ONE - MARK_ZONE_CUSHION_RATE),
                price_tick_size=tick,
                direction=PRICE_ROUND_DOWN,
            )
            entry_max = entry + (entry - entry_min)
        else:
            entry_max = quantize_price(
                price=mark_price * (_ONE + MARK_ZONE_CUSHION_RATE),
                price_tick_size=tick,
                direction=PRICE_ROUND_UP,
            )
            entry_min = entry - (entry_max - entry)
        if not _ZERO < entry_min < mark_price < entry_max:
            raise SignalDerivationError("the entry zone does not contain the mark price")
        # The stop is anchored below the zone and the targets at or above the mark, so neither
        # can trigger on placement even when the entry sits on the far side of the mark.
        stop = quantize_price(
            price=entry_min * (_ONE - SL_DISTANCE_RATE),
            price_tick_size=tick,
            direction=PRICE_ROUND_UP,
        )
        anchor = max(entry, mark_price)
        tp1 = quantize_price(
            price=anchor * (_ONE + TP1_DISTANCE_RATE),
            price_tick_size=tick,
            direction=PRICE_ROUND_DOWN,
        )
        tp2 = quantize_price(
            price=anchor * (_ONE + TP2_DISTANCE_RATE),
            price_tick_size=tick,
            direction=PRICE_ROUND_DOWN,
        )
        if not stop < entry_min or not stop < mark_price or not tp1 > mark_price or not tp2 > tp1:
            raise SignalDerivationError(
                "derived levels would trigger on placement or are unordered"
            )
        if scenario == SCENARIO_FILL and not entry > mark_price:
            raise SignalDerivationError("the fill entry is not above the mark price")
        if scenario == SCENARIO_FAR and not entry < mark_price:
            raise SignalDerivationError("the far entry is not below the mark price")

        quantity = _ceil_to_step(max(filters.min_quantity, filters.min_notional / entry), step)
        for _ in range(_QUANTITY_SEARCH_LIMIT):
            tp1_quantity = _floor_to_step(quantity * TP1_QUANTITY_FRACTION, step)
            if (
                quantity * entry >= filters.min_notional
                and tp1_quantity >= filters.min_quantity
                and tp1_quantity * tp1 >= filters.min_notional
            ):
                break
            quantity += step
        else:
            raise SignalDerivationError("no quantity passes the exchange minimums")
        if filters.max_quantity is not None and quantity > filters.max_quantity:
            raise SignalDerivationError("the smallest passing quantity exceeds the maximum")

        rates = _resolve_rates(parameter_set=params, commission=commission, observed_at=observed_at)
        risk_rate = params.params["risk_rate"]
        risk_per_unit = (entry_max - stop) + per_unit_round_trip_cost(
            side="LONG", entry_price=entry_max, stop_price=stop, rates=rates
        )
        # The pipeline sizes from equity, so back-solve the equity that makes it return exactly
        # this quantity, rounded UP to the cent. It is a smoke input, not an account reading.
        equity = _ceil_to_step(quantity * risk_per_unit / risk_rate, Decimal("0.01"))
        risk = entry - stop
        rr1 = ((tp1 - entry) / risk).quantize(_RR_PLACES, rounding=ROUND_DOWN)
        rr2 = ((tp2 - entry) / risk).quantize(_RR_PLACES, rounding=ROUND_DOWN)

        sequence = self._sequence
        signal_id = demo_smoke_signal_id(run_id=self._run_id, symbol=symbol, sequence=sequence)
        take_profit_json = _json({"tp1": str(tp1), "tp2": str(tp2)})
        # The execution binding re-derives the plan hash with the planner's own algorithm and the
        # pre-placement check reads a CANDLE_CLOSE invalidation rule (a bar closing below the
        # stop invalidates a LONG), so the plan carries both.
        invalidation_rule_json = _json({"basis": "CANDLE_CLOSE", "level": str(stop)})
        expiry_utc = (
            observed_at + timedelta(seconds=self._approval_timeout_seconds) + PLAN_EXPIRY_MARGIN
        )
        plan_hash = plan_hash_from_fields(
            signal_id=signal_id,
            entry_min_price=entry_min,
            entry_max_price=entry_max,
            stop_loss_price=stop,
            take_profit_json=take_profit_json,
            invalidation_rule_json=invalidation_rule_json,
            expiry_utc=expiry_utc,
        )
        trade_plan = TradePlan(
            trade_plan_id=demo_smoke_trade_plan_id(signal_id),
            signal_id=signal_id,
            trade_plan_version=DEMO_SMOKE_PLAN_VERSION,
            entry_model="LIMIT_ZONE",
            entry_min_price=entry_min,
            entry_max_price=entry_max,
            stop_loss_price=stop,
            take_profit_json=take_profit_json,
            invalidation_rule_json=invalidation_rule_json,
            expiry_utc=expiry_utc,
            expected_rr_json=_json({"tp1_rr": str(rr1), "tp2_rr": str(rr2)}),
            risk_rate=risk_rate,
            risk_budget=equity * risk_rate,
            suggested_quantity=quantity,
            quantity_before_rounding=quantity,
            quantity_after_rounding=quantity,
            quantization_decision=QuantizationDecision.ACCEPTED.value,
            plan_hash=plan_hash,
            status=TradePlanStatus.APPROVAL_PENDING,
            created_at_utc=observed_at,
        )
        constraints = ConstraintSnapshot(
            symbol=symbol,
            price_tick_size=tick,
            quantity_step_size=step,
            min_quantity=filters.min_quantity,
            min_notional=filters.min_notional,
            metadata_observed_at_utc=observed_at,
        )
        verdict = evaluate_risk(
            **_risk_kwargs(
                parameter_set=params,
                trade_plan=trade_plan,
                constraints=constraints,
                cost_rates=rates,
                equity=equity,
                risk_rate=risk_rate,
                now_utc=observed_at,
            )
        )
        sized = verdict.sized
        if verdict.is_no_trade or sized is None or sized.quantity != quantity:
            raise SignalDerivationError(
                f"the risk pipeline did not size the derived quantity: {verdict.reason_code}"
            )
        signal = Signal(
            signal_id=signal_id,
            strategy_id=params.strategy_id,
            strategy_version=params.strategy_version,
            parameter_set_id=params.parameter_set_id,
            parameter_set_hash=params.parameter_set_hash,
            symbol=symbol,
            direction="LONG",
            setup_type=DEMO_SMOKE_SETUP,
            source_timeframe=SIGNAL_TIMEFRAME,
            source_candle_close_utc=latest_closed_bar_close,
            detected_at_utc=observed_at,
            status=SignalStatus.DETECTED,
            expires_at_utc=expiry_utc,
        )
        self._sequence += 1
        return SignalRequest(
            signal=signal,
            plan=trade_plan,
            latest_closed_bar_close=latest_closed_bar_close,
            bar_close_price=mark_price,
            money_inputs=MoneyInputs(
                sized=sized,
                take_profits=_take_profits(tp1, tp2),
                cost_rates=rates,
                equity=equity,
                equity_observed_at_utc=observed_at,
                equity_source=EQUITY_SOURCE_PAPER_CONFIG,
                leverage=self._leverage,
                leverage_source=LEVERAGE_SOURCE_PAPER_CONFIG,
            ),
            exposure_quote=_ZERO,
            reason_codes=DEMO_SMOKE_REASON_CODES,
        )


def _take_profits(tp1: Decimal, tp2: Decimal) -> tuple[tuple[Decimal, Decimal], ...]:
    return ((tp1, TP1_QUANTITY_FRACTION), (tp2, _ONE - TP1_QUANTITY_FRACTION))


__all__ = [
    "DEMO_SMOKE_NAMESPACE",
    "DEMO_SMOKE_PLAN_VERSION",
    "DEMO_SMOKE_REASON_CODES",
    "DEMO_SMOKE_SETUP",
    "SCENARIOS",
    "SCENARIO_FAR",
    "SCENARIO_FILL",
    "DemoSmokeSignalSource",
    "MoneyInputs",
    "SignalDerivationError",
    "SignalRequest",
    "SignalSource",
    "build_request_money",
    "demo_smoke_signal_id",
    "demo_smoke_trade_plan_id",
]
