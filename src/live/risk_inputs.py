"""The live risk-input producer (plan 24-16; D-21, D-24, 24-01 Q9, DECISIONS D084, D085, D087).

`LiveRiskInputProducer` implements the `PlacementInputsSource` port of
`src/live/execution_service.py`. After a CONFIRM, `for_plan(approval, plan, confirmed_at_utc)`
assembles, from exchange and store truth and only by calling the Phase 21 and 22 libraries,
everything `execute_approved_plan` needs besides the approval and the token: the risk kwargs, the
gate kwargs and the `LivePlacementContext`. It recomputes no equity, no loss and no exposure
itself. Any missing, unreadable or stale input is a
`PlacementRefusal` with a plain reason (fail closed); nothing is sent to the exchange by this module
(the symbol configuration POST belongs to the margin guard, which the manager calls only after its
enablement, limits and SAFE_MODE gates).

Order (WR-04, D-03). The reads that take time come first (exchangeInfo, positions, open orders, the
reservations, the day), then the equity is refreshed, THEN the clock is read once: that value is
`now_utc` of the whole placement (the builder's age check, `risk_kwargs["now_utc"]`,
`PlacementInputs.now_utc`). A clock read before the refresh would precede the reading's stamp and be
stale by design.

Where each input comes from:

* equity: `LiveEquitySource.refresh()` then `resolve(...)` (the smaller of wallet and margin
  balance, D086), bounded by `account.max_equity_age_ms`;
* daily loss: `LiveDayRiskService.evaluate(...)` (the day row, the sticky D033 state, the loss
  `None` when a backfill did not complete within `account.max_daily_loss_age_ms`, D087);
* open positions: the counted reservations (RESERVED, PLACED, OPEN, Phase 21) explained against the
  exchange positions by `build_live_risk_inputs`; an unexplained exchange position is NO_TRADE;
* the 200 conditional-order headroom: the count of ALL open algo orders of the account goes into
  `gate_kwargs["open_algo_count"]` with the three planned legs; `decide_placement` judges it;
* the commission: the injected `cost_rates_for` callable (a cache of `GET /commissionRate`); a
  NO_TRADE result refuses;
* the symbol constraints: `exchangeInfo` for the signal's symbol (a TRADING PERPETUAL); the margin
  type, leverage and equity of the plan snapshot stay unknown here and are completed by the
  manager from the margin guard's verdict (gate 5g), which is what makes the snapshot valid for live
  and lets the coordinator place TP1 and TP2;
* the margin guard: when none is injected the real `MarginGuard` is composed from the configuration
  guard (`TARGET_LEVERAGE` 5 ISOLATED, D085), the bracket cache, the equity source and the
  reservation claims.

`read_pre_placement_inputs` is the one function that reads the exchange for gate 5e (mark price,
last price, open orders, open algo orders, positions, position mode). The producer takes its
positions and orders from it and the CONFIRM prefetch (plan 24-17, bound by plan 24-27) turns the
same readings into `ConfirmInputs` with `confirm_inputs_from_readings`.

`build_liquidation_watch` returns the post-fill liquidation watch with the policy the owner chose
(24-01 Q9, D085 O-4): a failed check CLOSES the position. `backfill_day_risk` is the scheduler task
body that keeps the daily loss known (D087).

The module reads no wall clock (the clock is injected), imports no SDK and keeps no exception text:
only the exception class name is kept in `last_error_type`.
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog

from src.backtest.semantics import TP1_QUANTITY_FRACTION
from src.domain.enums import SignalStatus, TradePlanStatus
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.execution.account_equity import LiveEquitySource
from src.execution.confirm_recheck import ConfirmInputs
from src.execution.constraint_snapshot import ExchangeFilterExtras, build_plan_constraint_snapshot
from src.execution.day_risk_service import LiveDayRiskService
from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
from src.execution.liquidation_watch import (
    BracketSource,
    EntryFeeRateSource,
    LiquidationFailurePolicy,
    LiquidationWatch,
)
from src.execution.live_context import LivePlacementContext
from src.execution.live_risk_inputs import build_live_risk_inputs
from src.execution.manager import (
    ExecutionAdapter,
    _last_price_of,
    _last_time_of,
    _mark_price_of,
    _mark_time_of,
    _open_order_symbols,
    _position_symbols,
    resolve_position_mode,
)
from src.execution.margin_guard import (
    BracketPort,
    ClaimsPort,
    ConfigGuardPort,
    MarginGuard,
    MarginGuardPort,
)
from src.execution.pre_placement import PrePlacementInputs
from src.execution.protection import ProtectionRegistry
from src.live.execution_service import PlacementInputs, PlacementRefusal
from src.reconcile.feed_freshness import DriftLimitsLike
from src.risk.daily_loss import DayRiskState
from src.risk.live_commission import LiveCostRatesResult
from src.risk.reservations import CountedReservation, ExchangeExposure, ReservationStatus
from src.risk.types import ConstraintSnapshot

log = structlog.get_logger(__name__)

# Plain refusal reasons of the producer (the builder's own codes, UNCERTAIN_ACCOUNT_STATE and
# DAILY_STOP_BLOCK, and the cost-rate result's code pass through unchanged).
REFUSAL_SIGNAL_CONTEXT_UNAVAILABLE: Final[str] = "SIGNAL_CONTEXT_UNAVAILABLE"
REFUSAL_EXCHANGE_STATE_UNAVAILABLE: Final[str] = "EXCHANGE_STATE_UNAVAILABLE"
REFUSAL_RESERVATIONS_UNAVAILABLE: Final[str] = "RESERVATIONS_UNAVAILABLE"
REFUSAL_SYMBOL_NOT_TRADABLE: Final[str] = "SYMBOL_NOT_TRADABLE"
REFUSAL_BRACKETS_UNAVAILABLE: Final[str] = "BRACKETS_UNAVAILABLE"
REFUSAL_CLOCK_UNAVAILABLE: Final[str] = "CLOCK_UNAVAILABLE"
REFUSAL_PRODUCER_ERROR: Final[str] = "PLACEMENT_INPUTS_ERROR"

# The planned conditional legs of one plan: the stop and the two take profits.
PLANNED_LEG_COUNT: Final[int] = 3

# The five equity-fraction thresholds `build_live_risk_inputs` resolves against the day-start base.
PORTFOLIO_PARAMETER_KEYS: Final[tuple[str, ...]] = (
    "max_open_positions",
    "max_aggregate_open_risk",
    "cluster_cap",
    "daily_loss_warning_threshold",
    "daily_loss_stop_threshold",
)
# Every other registry value the producer reads.
REQUIRED_PARAMETER_KEYS: Final[tuple[str, ...]] = (
    "risk_rate",
    "constraint_snapshot_ttl_seconds",
    "min_stop_distance_rate",
    "max_cost_to_risk",
    "minimum_risk_utilization_after_rounding",
    *PORTFOLIO_PARAMETER_KEYS,
)
# The registry values the cost-rate helper reads.
COST_PARAMETER_KEYS: Final[tuple[str, ...]] = (
    "fee_rate_entry",
    "expected_slippage",
    "fee_rate_exit",
    "exit_slippage_rate",
    "commission_rate_ttl_seconds",
)

_ONE_MS = timedelta(milliseconds=1)
_TRADING: Final[str] = "TRADING"
_PERPETUAL: Final[str] = "PERPETUAL"
_WORKING_TYPE: Final[str] = "MARK_PRICE"
_COUNTED_ON_EXCHANGE = (ReservationStatus.PLACED, ReservationStatus.OPEN)


# --------------------------------------------------------------------------- #
# Ports
# --------------------------------------------------------------------------- #


class ProducerAdapter(ExecutionAdapter, Protocol):
    """The execution adapter reads plus `exchange_info` (the real `BinanceUsdmAdapter` has it)."""

    async def exchange_info(self, symbols: Sequence[str] | None = None) -> Sequence[Any]: ...


class ReservationReader(ClaimsPort, Protocol):
    """The stored reservations: the counted rows (caps) and the margin claims (margin guard).

    Both calls are plain calls; an awaitable result is accepted so the composition may run the
    synchronous SQL store behind the store executor (plan 24-05).
    """

    def list_counted(self) -> Any: ...


@dataclass(frozen=True, kw_only=True)
class PlanSignalContext:
    """What the signal request carries for a plan: the persisted Signal and the bar close.

    `latest_closed_bar_close` is the close of the latest closed strategy bar for the invalidation
    rule (None means "not available" and the manager's invalidation check refuses it).
    """

    signal: Signal
    latest_closed_bar_close: Decimal | None


# Looks the context up by the plan (an in-process map filled by the signal source).
SignalContextLookup = Callable[[TradePlan], PlanSignalContext | None]

# (symbol, now_utc) -> the live cost rates or a NO_TRADE reason (a sync or an async callable).
CostRatesFor = Callable[[str, datetime], "LiveCostRatesResult | Awaitable[LiveCostRatesResult]"]


async def _settled(value: Any) -> Any:
    """`value`, awaited when it is awaitable."""
    if inspect.isawaitable(value):
        return await value
    return value


def _field(row: Any, name: str) -> Any:
    """An attribute of a reading row, or the key of a mapping row."""
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


# --------------------------------------------------------------------------- #
# The shared pre-placement read
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, kw_only=True)
class PrePlacementReadings:
    """The raw exchange readings of gate 5e; `None` is a read that failed (fail closed).

    `position_mode` is the manager's vocabulary ("ONE_WAY" / "HEDGE") or None when unreadable.
    `checked_at_utc` is the injected clock read AFTER every read (the price ages are measured
    against it, 19-REVIEW CR-01), or None when the clock was unreadable. The three order and
    position snapshots cover ALL symbols of the account.
    """

    symbol: str
    mark: Any
    last: Any
    normal_orders: Any
    algo_orders: Any
    positions: Any
    position_mode: str | None
    checked_at_utc: datetime | None


async def _read_or_none(read: Callable[[], Awaitable[Any]]) -> Any:
    try:
        return await read()
    except Exception:  # noqa: BLE001 - fail closed: an unreadable value is "not available"
        return None


async def read_pre_placement_inputs(
    adapter: ExecutionAdapter, symbol: str, clock: Callable[[], datetime]
) -> PrePlacementReadings:
    """Read the six gate 5e inputs through the adapter, once each, and stamp them.

    Shared by the CONFIRM prefetch and the producer so the two never read differently. A failing
    read is `None` in the result (never an exception, never a default); the clock is read once,
    after the last read.
    """
    mark = await _read_or_none(lambda: adapter.get_mark_price(symbol=symbol))
    last = await _read_or_none(lambda: adapter.get_last_price(symbol=symbol))
    normal_orders = await _read_or_none(lambda: adapter.snapshot_open_normal_orders())
    algo_orders = await _read_or_none(lambda: adapter.snapshot_open_algo_orders())
    positions = await _read_or_none(lambda: adapter.snapshot_positions())
    try:
        position_mode: str | None = resolve_position_mode(await adapter.get_position_mode())
    except Exception:  # noqa: BLE001 - an undeterminable mode is "not available"
        position_mode = None
    try:
        checked_at: datetime | None = clock()
    except Exception:  # noqa: BLE001 - an unreadable clock refuses downstream
        checked_at = None
    return PrePlacementReadings(
        symbol=symbol,
        mark=mark,
        last=last,
        normal_orders=normal_orders,
        algo_orders=algo_orders,
        positions=positions,
        position_mode=position_mode,
        checked_at_utc=checked_at,
    )


class PositionModeUnavailable(ValueError):  # noqa: N818 - a state of the world, not a bug
    """The position mode could not be read, so no `ConfirmInputs` can be built (fail closed)."""


def confirm_inputs_from_readings(
    readings: PrePlacementReadings,
    *,
    signal: Signal,
    plan: TradePlan,
    execution_limits: ExecutionLimits,
    latest_closed_bar_close: Decimal | None,
    gtd_clock_margin: timedelta,
    protections: ProtectionRegistry,
    reconciled_symbols: frozenset[str] = frozenset(),
) -> ConfirmInputs:
    """Turn the readings into the `ConfirmInputs` the CONFIRM recheck takes (single use).

    Uses the manager's own reading helpers, so gate 5e and the CONFIRM recheck interpret a
    reading identically. The plan status is APPROVED (an approval exists); an unprotected-position
    check that raises counts as "unprotected". Raises `PositionModeUnavailable` when the mode is
    unknown; the caller then puts nothing and the recheck refuses CONFIRM_INPUTS_UNAVAILABLE.
    """
    if readings.position_mode is None:
        raise PositionModeUnavailable("position mode unavailable")
    symbol = readings.symbol
    try:
        any_unprotected = bool(protections.blocks_new_entries())
    except Exception:  # noqa: BLE001 - an unreadable registry blocks (fail closed)
        any_unprotected = True
    checked_at = readings.checked_at_utc
    pre = PrePlacementInputs(
        side=signal.direction,
        plan_status=TradePlanStatus.APPROVED,
        signal_invalidated=signal.invalidated_at_utc is not None,
        trade_plan=plan,
        latest_closed_bar_close=latest_closed_bar_close,
        expiry_utc=plan.expiry_utc,
        now_utc=checked_at if checked_at is not None else plan.created_at_utc,
        min_remaining_validity_seconds=execution_limits.min_remaining_validity_seconds,
        gtd_clock_margin=gtd_clock_margin,
        position_symbols=_position_symbols(symbol, readings.positions, reconciled_symbols),
        open_order_symbols=_open_order_symbols(
            symbol, (readings.normal_orders, readings.algo_orders)
        ),
        any_unprotected=any_unprotected,
        symbol=symbol,
        mark_price=_mark_price_of(readings.mark),
        mark_time_utc=_mark_time_of(readings.mark),
        mark_checked_at_utc=checked_at,
        max_mark_price_age_ms=execution_limits.max_mark_price_age_ms,
        last_price=_last_price_of(readings.last, symbol),
        last_time_utc=_last_time_of(readings.last, symbol),
        last_checked_at_utc=checked_at,
        max_last_price_age_ms=execution_limits.max_last_price_age_ms,
        sl_trigger_price=plan.stop_loss_price,
        entry_min_price=plan.entry_min_price,
        entry_max_price=plan.entry_max_price,
    )
    return ConfirmInputs(pre_placement=pre, position_mode=readings.position_mode)


# --------------------------------------------------------------------------- #
# The liquidation watch (D-24 resolved by R-1 and 24-01 Q9) and the D087 backfill
# --------------------------------------------------------------------------- #


def build_liquidation_watch(
    *,
    brackets: BracketSource,
    fee_rates: EntryFeeRateSource,
    limits: ExecutionLimits,
) -> LiquidationWatch:
    """The post-fill liquidation watch with the owner's policy: a failed check CLOSES (Q9, O-4).

    CONTEXT D-24 proposed alert-only; the owner took D085 O-4 instead, so the policy is
    `CLOSE_POSITION`. The coordinator (plan 24-27 passes this watch) closes the position through
    its CLOSE_REQUIRED path and raises the critical alert. Raises `ExecutionLimitsNotConfigured`
    while `margin.liquidation_buffer_bps` is unset.
    """
    return LiquidationWatch(
        brackets=brackets,
        fee_rates=fee_rates,
        limits=limits,
        policy=LiquidationFailurePolicy.CLOSE_POSITION,
    )


async def backfill_day_risk(day_risk: LiveDayRiskService, now_utc: datetime) -> str | None:
    """One day-risk backfill: the scheduler task body that keeps the daily loss known (D087).

    The cadence is half of `account.max_daily_loss_age_ms`, set by the scheduler specs (plan
    24-27). A single call, no retry. Never raises out of the scheduler: a failure is logged by
    exception class name only and returned (None means the backfill completed). A stale known loss
    still refuses (NO_TRADE) if this has not run in time.
    """
    error_class: str | None
    try:
        await day_risk.backfill(now_utc=now_utc)
    except Exception as exc:  # noqa: BLE001 - the scheduler must never see a raise
        error_class = type(exc).__name__
    else:
        error_class = day_risk.last_error_type
    if error_class is not None:
        log.warning("live_day_risk_backfill_failed", error_class=error_class)
    return error_class


def make_cost_rates_for(
    *,
    commission_for: Callable[[str], Any],
    parameter_set: Mapping[str, Any],
) -> CostRatesFor:
    """A `cost_rates_for` callable over the commission cache and the registry rates.

    `commission_for(symbol)` is `CommissionCache.account_commission_for` (an `AccountCommission`
    or None). The result is `resolve_live_cost_rates`: per-side max(parameter, account taker), or
    a NO_TRADE reason for a missing, wrong-symbol, stale or future-dated commission.
    """
    from src.risk.cost_rates import FEE_SOURCE_PARAMETER, CostRates
    from src.risk.live_commission import resolve_live_cost_rates

    missing = [key for key in COST_PARAMETER_KEYS if key not in parameter_set]
    if missing:
        raise ValueError(f"parameter set lacks cost keys: {', '.join(missing)}")
    parameter_rates = CostRates(
        fee_rate_entry=parameter_set["fee_rate_entry"],
        entry_slippage_rate=parameter_set["expected_slippage"],
        fee_rate_exit=parameter_set["fee_rate_exit"],
        exit_slippage_rate=parameter_set["exit_slippage_rate"],
        fee_source=FEE_SOURCE_PARAMETER,
    )
    ttl = timedelta(seconds=int(parameter_set["commission_rate_ttl_seconds"]))

    def cost_rates_for(symbol: str, now_utc: datetime) -> LiveCostRatesResult:
        return resolve_live_cost_rates(
            parameter_rates=parameter_rates,
            account_commission=commission_for(symbol),
            candidate_symbol=symbol,
            now_utc=now_utc,
            ttl=ttl,
        )

    return cost_rates_for


# --------------------------------------------------------------------------- #
# The producer
# --------------------------------------------------------------------------- #


def _exposures(positions: Any) -> tuple[ExchangeExposure, ...] | None:
    """The non-zero exchange positions as signed exposures, or None when the read is unusable."""
    if not isinstance(positions, list | tuple):
        return None
    found: list[ExchangeExposure] = []
    for row in positions:
        symbol = _field(row, "symbol")
        amount = _field(row, "position_amt")
        if not isinstance(symbol, str) or symbol == "":
            return None
        if not isinstance(amount, Decimal) or not amount.is_finite():
            return None
        if amount != Decimal(0):
            found.append(ExchangeExposure(symbol=symbol, signed_quantity=amount))
    return tuple(found)


def _count_of(rows: Any) -> int | None:
    return len(rows) if isinstance(rows, list | tuple) else None


class LiveRiskInputProducer:
    """The `PlacementInputsSource` of the live process; see the module docstring."""

    def __init__(
        self,
        *,
        adapter: ProducerAdapter,
        equity: LiveEquitySource,
        day_risk: LiveDayRiskService,
        config_guard: ConfigGuardPort,
        brackets: BracketPort,
        reservations: ReservationReader,
        protections: ProtectionRegistry,
        cost_rates_for: CostRatesFor,
        parameter_set: Mapping[str, Any],
        execution_limits: ExecutionLimits,
        drift_limits: DriftLimitsLike,
        alert_sink: Any | None,
        clock: Callable[[], datetime],
        signal_context_for: SignalContextLookup,
        margin_guard: MarginGuardPort | None = None,
    ) -> None:
        age_ms = execution_limits.account_max_equity_age_ms
        if age_ms is None:
            raise ExecutionLimitsNotConfigured(("account.max_equity_age_ms",))
        missing = [key for key in REQUIRED_PARAMETER_KEYS if key not in parameter_set]
        if missing:
            raise ValueError(f"parameter set lacks keys: {', '.join(missing)}")
        self._adapter = adapter
        self._equity = equity
        self._day_risk = day_risk
        self._brackets = brackets
        self._reservations = reservations
        self._protections = protections
        self._cost_rates_for = cost_rates_for
        self._params = dict(parameter_set)
        self._limits = execution_limits
        self._alert_sink = alert_sink
        self._clock = clock
        self._signal_context_for = signal_context_for
        self._max_equity_age = age_ms * _ONE_MS
        self._gtd_clock_margin = timedelta(
            milliseconds=max(drift_limits.ahead_limit_ms, drift_limits.behind_limit_ms)
        )
        self._ttl = timedelta(seconds=int(self._params["constraint_snapshot_ttl_seconds"]))
        self._margin_guard: MarginGuardPort = (
            margin_guard
            if margin_guard is not None
            else MarginGuard(
                config_guard=config_guard,
                brackets=brackets,
                account=equity,
                claims=reservations,
                clock=clock,
                limits=execution_limits,
            )
        )
        self._last_error_type: str | None = None

    @property
    def margin_guard(self) -> MarginGuardPort:
        return self._margin_guard

    @property
    def last_error_type(self) -> str | None:
        """Type name of the last unexpected failure of `for_plan`; never a message."""
        return self._last_error_type

    async def for_plan(
        self, approval: Any, plan: TradePlan, confirmed_at_utc: datetime
    ) -> PlacementInputs | PlacementRefusal:
        """The placement inputs of one confirmed plan, or the reason nothing may be placed."""
        del approval, confirmed_at_utc  # the instant is read here, after the equity refresh
        try:
            return await self._assemble(plan)
        except Exception as exc:  # noqa: BLE001 - any unexpected failure is a refusal, never a pass
            self._last_error_type = type(exc).__name__
            return PlacementRefusal(reason=REFUSAL_PRODUCER_ERROR)

    # ---- the assembly -------------------------------------------------------------------- #

    async def _assemble(self, plan: TradePlan) -> PlacementInputs | PlacementRefusal:
        context = self._signal_context_for(plan)
        if context is None or context.signal.signal_id != plan.signal_id:
            return PlacementRefusal(reason=REFUSAL_SIGNAL_CONTEXT_UNAVAILABLE)
        signal = context.signal
        symbol = signal.symbol

        # 1. The exchange: the symbol's constraints, then the shared pre-placement readings.
        captured_at = self._clock()
        try:
            listed = await self._adapter.exchange_info([symbol])
        except Exception as exc:  # noqa: BLE001 - no constraints, no trade
            self._last_error_type = type(exc).__name__
            return PlacementRefusal(reason=REFUSAL_EXCHANGE_STATE_UNAVAILABLE)
        filters = next((row for row in listed if _field(row, "symbol") == symbol), None)
        if filters is None:
            return PlacementRefusal(reason=REFUSAL_EXCHANGE_STATE_UNAVAILABLE)
        if _field(filters, "status") != _TRADING or _field(filters, "contract_type") != _PERPETUAL:
            return PlacementRefusal(reason=REFUSAL_SYMBOL_NOT_TRADABLE)
        readings = await read_pre_placement_inputs(self._adapter, symbol, self._clock)
        exposures = _exposures(readings.positions)
        algo_count = _count_of(readings.algo_orders)
        normal_count = _count_of(readings.normal_orders)
        if exposures is None or algo_count is None or normal_count is None:
            return PlacementRefusal(reason=REFUSAL_EXCHANGE_STATE_UNAVAILABLE)

        # 2. The reservations (the caps' open positions) and whether any exposure exists.
        try:
            counted: tuple[CountedReservation, ...] = tuple(
                await _settled(self._reservations.list_counted())
            )
        except Exception as exc:  # noqa: BLE001 - unreadable reservations are unknown exposure
            self._last_error_type = type(exc).__name__
            return PlacementRefusal(reason=REFUSAL_RESERVATIONS_UNAVAILABLE)
        exposure = bool(
            exposures
            or algo_count
            or normal_count
            or any(
                row.status in _COUNTED_ON_EXCHANGE and row.trade_plan_id != plan.trade_plan_id
                for row in counted
            )
        )

        # 3. The brackets must be fresh before anything is judged (the guard re-checks them).
        try:
            bracket_reading = await self._brackets.get(symbol=symbol)
        except Exception as exc:  # noqa: BLE001 - no brackets, no trade
            self._last_error_type = type(exc).__name__
            bracket_reading = None
        if bracket_reading is None:
            return PlacementRefusal(reason=REFUSAL_BRACKETS_UNAVAILABLE)

        # 4. The day: its state and its verdict, before the equity refresh (a day open refreshes
        #    the equity too, and that stamp must precede the final clock read).
        day_now = self._clock()
        verdict = await self._day_risk.evaluate(now_utc=day_now, exposure=exposure)
        opened = await self._day_risk.ensure_day(now_utc=day_now, exposure=exposure)
        day = opened if isinstance(opened, DayRiskState) else None

        # 5. WR-04: refresh the equity, THEN read the clock: that is the placement's only `now`.
        await self._equity.refresh()
        try:
            now_utc = self._clock()
        except Exception:  # noqa: BLE001 - no clock, no placement
            return PlacementRefusal(reason=REFUSAL_CLOCK_UNAVAILABLE)
        risk_rate = self._params["risk_rate"]
        equity_result = self._equity.resolve(risk_rate=risk_rate, now_utc=now_utc)

        # 6. The commission.
        rates_result = await _settled(self._cost_rates_for(symbol, now_utc))
        if rates_result.rates is None:
            return PlacementRefusal(reason=rates_result.reason_code)

        # 7. The pure builder (Phase 21): equity, day, reservations, exposures.
        built = build_live_risk_inputs(
            equity=equity_result,
            day=day,
            verdict=verdict,
            counted=counted,
            exchange_exposures=exposures,
            candidate_trade_plan_id=plan.trade_plan_id,
            parameter_set={key: self._params[key] for key in PORTFOLIO_PARAMETER_KEYS},
            now_utc=now_utc,
            max_equity_age=self._max_equity_age,
        )
        if built.inputs is None:
            return PlacementRefusal(reason=built.reason_code)

        # 8. The constraints, the per-plan snapshot and the manager's inputs.
        constraints = ConstraintSnapshot(
            symbol=symbol,
            price_tick_size=filters.price_tick_size,
            quantity_step_size=filters.quantity_step_size,
            min_quantity=filters.min_quantity,
            min_notional=filters.min_notional,
            metadata_observed_at_utc=captured_at,
        )
        snapshot = build_plan_constraint_snapshot(
            plan.trade_plan_id,
            constraints,
            ExchangeFilterExtras(
                market_lot_min_quantity=filters.market_lot_min_quantity,
                market_lot_max_quantity=filters.market_lot_max_quantity,
                market_lot_step_size=filters.market_lot_step_size,
                percent_price_multiplier_up=filters.percent_price_multiplier_up,
                percent_price_multiplier_down=filters.percent_price_multiplier_down,
                percent_price_multiplier_decimals=filters.percent_price_multiplier_decimals,
            ),
            filters.max_quantity,
            _WORKING_TYPE,
            captured_at_utc=now_utc,
        )
        risk_kwargs: dict[str, Any] = {
            "trade_plan": dataclasses.replace(plan, status=TradePlanStatus.APPROVED),
            "candidate_position_side": signal.direction,
            "account_state": built.inputs.account_state,
            "constraint_snapshot": constraints,
            "open_positions": list(built.inputs.open_positions),
            "daily_loss_quote": built.inputs.daily_loss_quote,
            "now_utc": now_utc,
            "ttl": self._ttl,
            "cost_rates": rates_result.rates,
            "min_stop_distance_rate": self._params["min_stop_distance_rate"],
            "max_cost_to_risk": self._params["max_cost_to_risk"],
            "minimum_risk_utilization_after_rounding": self._params[
                "minimum_risk_utilization_after_rounding"
            ],
            "parameter_set": built.inputs.parameter_set,
        }
        live_context = LivePlacementContext(
            signal=dataclasses.replace(signal, status=SignalStatus.APPROVED),
            plan_constraint_snapshot=snapshot,
            execution_limits=self._limits,
            protection_registry=self._protections,
            latest_closed_bar_close=context.latest_closed_bar_close,
            gtd_clock_margin=self._gtd_clock_margin,
            tp1_quantity_fraction=TP1_QUANTITY_FRACTION,
            clock=self._clock,
            margin_guard=self._margin_guard,
            alert_sink=self._alert_sink,
        )
        return PlacementInputs(
            now_utc=now_utc,
            expiry_utc=plan.expiry_utc,
            approval_strategy_version=signal.strategy_version,
            approval_parameter_set_id=signal.parameter_set_id,
            approval_parameter_set_hash=signal.parameter_set_hash,
            risk_kwargs=risk_kwargs,
            gate_kwargs={
                "open_algo_count": algo_count,
                "planned_leg_count": PLANNED_LEG_COUNT,
                # The builder just explained every exchange exposure by a PLACED or OPEN row.
                "positions_reconciled": True,
            },
            live_context=live_context,
        )


__all__ = [
    "COST_PARAMETER_KEYS",
    "PLANNED_LEG_COUNT",
    "PORTFOLIO_PARAMETER_KEYS",
    "REFUSAL_BRACKETS_UNAVAILABLE",
    "REFUSAL_CLOCK_UNAVAILABLE",
    "REFUSAL_EXCHANGE_STATE_UNAVAILABLE",
    "REFUSAL_PRODUCER_ERROR",
    "REFUSAL_RESERVATIONS_UNAVAILABLE",
    "REFUSAL_SIGNAL_CONTEXT_UNAVAILABLE",
    "REFUSAL_SYMBOL_NOT_TRADABLE",
    "REQUIRED_PARAMETER_KEYS",
    "CostRatesFor",
    "LiveRiskInputProducer",
    "PlanSignalContext",
    "PositionModeUnavailable",
    "PrePlacementReadings",
    "ProducerAdapter",
    "ReservationReader",
    "SignalContextLookup",
    "backfill_day_risk",
    "build_liquidation_watch",
    "confirm_inputs_from_readings",
    "make_cost_rates_for",
    "read_pre_placement_inputs",
]
