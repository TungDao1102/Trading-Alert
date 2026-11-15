"""TEST_ONLY parts for the live risk-input producer tests (plan 24-16).

Every number here is a made-up value that only makes a consistent BTCUSDT LONG shadow plan pass the
real gates; none is a Binance fact, a chosen threshold or a project value. No production module
imports this file (tests/test_no_unratified_defaults.py enforces it).

`build_parts(clock, exchange, ...)` assembles the producer over REAL library objects (the live
equity source, the day-risk service, the bracket cache, the symbol configuration guard, the margin
guard) served by the recorded-Demo answers of `CompositeRest`, with fakes only at the edges: the
SDK stand-in, the exchange reads (`ScriptedExchange`), the reservation store and the commission.
`LateInputs` lets the live rig (which needs its `inputs` at construction) be built before the
producer, which needs the rig's clock, fake exchange and protection coordinator.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from src.adapters.binance_public import SymbolFilters
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_usdm import BinanceUsdmAdapter
from src.domain.approval import Approval
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.execution.account_equity import LiveEquitySource
from src.execution.bracket_cache import BracketCache
from src.execution.day_risk_service import LiveDayRiskService
from src.execution.execution_limits import ExecutionLimits
from src.execution.margin_guard import MarginGuardPort
from src.execution.symbol_config_guard import SymbolConfigGuard
from src.live.execution_service import PlacementInputs, PlacementInputsSource, PlacementRefusal
from src.live.risk_inputs import (
    CostRatesFor,
    LiveRiskInputProducer,
    PlanSignalContext,
    backfill_day_risk,
    make_cost_rates_for,
)
from src.risk.daily_loss import FundingPolicy
from src.risk.live_commission import AccountCommission
from src.risk.margin_check import MarginClaim
from src.risk.reservations import CountedReservation

from tests.support.day_risk_fakes import (
    TEST_ONLY_PARAMETER_SET,
    InMemoryDayRiskStore,
    ScriptedDayRiskReader,
)
from tests.support.execution_limits import test_only_execution_limits
from tests.support.limits import test_only_signed_call_policy
from tests.support.live_rig import make_live_rig
from tests.support.margin_guard_fakes import (
    START as UNIT_START,
)
from tests.support.margin_guard_fakes import (
    CompositeRest,
    MovingClock,
)

D = Decimal
DEFAULT_BAR_CLOSE = D("50050")  # TEST_ONLY latest closed bar close
TEST_ONLY_SYMBOL = "BTCUSDT"
TEST_ONLY_QUOTE = "USDT"
TEST_ONLY_TARGET_LEVERAGE = 5  # the D085 composition value, handed to the real configuration guard

# TEST_ONLY registry values: the equity-fraction thresholds of the day-risk fakes plus the rest.
TEST_ONLY_PARAMS: dict[str, Any] = {
    **TEST_ONLY_PARAMETER_SET,
    "risk_rate": D("0.005"),
    "constraint_snapshot_ttl_seconds": 3600,
    "min_stop_distance_rate": D("0.003"),
    "max_cost_to_risk": D("0.15"),
    "minimum_risk_utilization_after_rounding": D("0.60"),
    "fee_rate_entry": D("0.0005"),
    "expected_slippage": D("0.0001"),
    "fee_rate_exit": D("0.0005"),
    "exit_slippage_rate": D("0.0003"),
    "commission_rate_ttl_seconds": 3600,
}


def drift_limits_for_tests(ahead_ms: int = 500, behind_ms: int = 1000) -> Any:
    """The two ratified drift limits (the values of the 2026-10 drift file; TEST_ONLY here)."""
    return SimpleNamespace(ahead_limit_ms=ahead_ms, behind_limit_ms=behind_ms)


def btc_filters(**overrides: Any) -> SymbolFilters:
    """TEST_ONLY BTCUSDT exchangeInfo row; an override replaces a field."""
    values: dict[str, Any] = {
        "symbol": TEST_ONLY_SYMBOL,
        "contract_type": "PERPETUAL",
        "status": "TRADING",
        "onboard_time_utc": None,
        "price_tick_size": D("0.01"),
        "quantity_step_size": D("0.001"),
        "min_quantity": D("0.001"),
        "max_quantity": D("1000"),
        "min_notional": D("100"),
        "base_asset": "BTC",
        "quote_asset": TEST_ONLY_QUOTE,
        "margin_asset": TEST_ONLY_QUOTE,
        "notional_constraints_json": "{}",
        "order_capabilities_json": "{}",
        "position_mode_snapshot_json": "{}",
        "market_lot_min_quantity": D("0.001"),
        "market_lot_max_quantity": D("120"),
        "market_lot_step_size": D("0.001"),
        "percent_price_multiplier_up": D("1.05"),
        "percent_price_multiplier_down": D("0.95"),
        "percent_price_multiplier_decimals": 4,
    }
    values.update(overrides)
    return SymbolFilters(**values)


def position_row(symbol: str, amount: str) -> Any:
    """A position reading row (the fields the producer reads)."""
    return SimpleNamespace(symbol=symbol, position_amt=D(amount))


class ScriptedExchange:
    """The exchange reads of the producer, scripted; every call is recorded by name.

    `fail` lists method names that raise; `wrapped` (the live rig's fake exchange) serves the order
    and price reads when given, so a real placement can follow. exchangeInfo is always served here.
    """

    def __init__(self, *, wrapped: Any = None, filters: Sequence[SymbolFilters] | None = None):
        self.wrapped = wrapped
        self.filters: list[SymbolFilters] = [btc_filters()] if filters is None else list(filters)
        self.positions: list[Any] = []
        self.normal: list[Any] = []
        self.algo: list[Any] = []
        self.dual_side: Any = False
        self.mark: Any = None
        self.last: Any = None
        self.fail: set[str] = set()
        self.calls: list[str] = []
        self.now: Callable[[], datetime] | None = None

    def count(self, name: str) -> int:
        return self.calls.count(name)

    def _enter(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail:
            raise RuntimeError(f"scripted failure of {name}")

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or self.__dict__.get("wrapped") is None:
            raise AttributeError(name)
        return getattr(self.wrapped, name)

    async def exchange_info(self, symbols: Sequence[str] | None = None) -> list[SymbolFilters]:
        self._enter("exchange_info")
        return list(self.filters)

    async def get_mark_price(self, *, symbol: str) -> Any:
        self._enter("get_mark_price")
        if self.wrapped is not None:
            return await self.wrapped.get_mark_price(symbol=symbol)
        return self.mark

    async def get_last_price(self, *, symbol: str) -> Any:
        self._enter("get_last_price")
        if self.wrapped is not None:
            return await self.wrapped.get_last_price(symbol=symbol)
        return self.last

    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> Any:
        self._enter("snapshot_open_normal_orders")
        if self.wrapped is not None:
            return await self.wrapped.snapshot_open_normal_orders(symbol=symbol)
        return list(self.normal)

    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> Any:
        self._enter("snapshot_open_algo_orders")
        if self.wrapped is not None:
            return await self.wrapped.snapshot_open_algo_orders(symbol=symbol)
        return list(self.algo)

    async def snapshot_positions(self, *, symbol: str | None = None) -> Any:
        self._enter("snapshot_positions")
        if self.wrapped is not None:
            return await self.wrapped.snapshot_positions(symbol=symbol)
        return list(self.positions)

    async def get_position_mode(self) -> Any:
        self._enter("get_position_mode")
        if self.wrapped is not None:
            return await self.wrapped.get_position_mode()
        return SimpleNamespace(dual_side_position=self.dual_side)


class FakeReservations:
    """The reservation store surface of the producer and the margin guard."""

    def __init__(
        self,
        counted: Sequence[CountedReservation] = (),
        claims: Sequence[MarginClaim] = (),
    ) -> None:
        self.counted = list(counted)
        self.claims = list(claims)
        self.fail_counted: BaseException | None = None
        self.calls: list[str] = []

    def list_counted(self) -> tuple[CountedReservation, ...]:
        self.calls.append("list_counted")
        if self.fail_counted is not None:
            raise self.fail_counted
        return tuple(self.counted)

    def list_margin_claims(self) -> tuple[MarginClaim, ...]:
        self.calls.append("list_margin_claims")
        return tuple(self.claims)


class LateInputs:
    """A `PlacementInputsSource` whose target is set after the rig that needs it is built."""

    def __init__(self) -> None:
        self.target: PlacementInputsSource | None = None

    async def for_plan(
        self, approval: Approval, plan: TradePlan, confirmed_at_utc: datetime
    ) -> PlacementInputs | PlacementRefusal:
        if self.target is None:
            return PlacementRefusal(reason="WIRING_NOT_BUILT")
        return await self.target.for_plan(approval, plan, confirmed_at_utc)


class LateRegistry:
    """A protection registry whose target (the coordinator) is set after the rig is built."""

    def __init__(self) -> None:
        self.target: Any = None

    def blocks_new_entries(self) -> bool:
        return bool(self.target.blocks_new_entries()) if self.target is not None else True

    def register_resting_entry(self, entry: Any) -> None:
        self.target.register_resting_entry(entry)

    def protection_of(self, plan_hash: str) -> Any:
        return self.target.protection_of(plan_hash)


def static_context(
    signal: Signal, bar_close: Decimal | None = DEFAULT_BAR_CLOSE
) -> Callable[[TradePlan], PlanSignalContext | None]:
    """A signal-context lookup that knows exactly one signal."""

    def lookup(plan: TradePlan) -> PlanSignalContext | None:
        return PlanSignalContext(signal=signal, latest_closed_bar_close=bar_close)

    return lookup


@dataclass
class Parts:
    """The producer and every real object under it (see `build_parts`)."""

    producer: LiveRiskInputProducer
    clock: Callable[[], datetime]
    exchange: ScriptedExchange
    rest: CompositeRest
    equity: LiveEquitySource
    brackets: BracketCache
    config_guard: SymbolConfigGuard
    day_risk: LiveDayRiskService
    day_store: InMemoryDayRiskStore
    day_reader: ScriptedDayRiskReader
    reservations: FakeReservations
    registry: LateRegistry
    limits: ExecutionLimits
    commission: dict[str, AccountCommission | None] = field(default_factory=dict)


def build_parts(
    *,
    clock: Callable[[], datetime],
    exchange: ScriptedExchange,
    signal: Signal,
    limits: ExecutionLimits | None = None,
    rest: CompositeRest | None = None,
    reservations: FakeReservations | None = None,
    params: dict[str, Any] | None = None,
    cost_rates_for: CostRatesFor | None = None,
    margin_guard: MarginGuardPort | None = None,
    bar_close: Decimal | None = DEFAULT_BAR_CLOSE,
    alert_sink: Any = None,
    registry: LateRegistry | None = None,
) -> Parts:
    """The producer over real library objects and the recorded-Demo SDK stand-in."""
    the_limits = limits if limits is not None else test_only_execution_limits()
    the_params = dict(TEST_ONLY_PARAMS if params is None else params)
    the_rest = rest if rest is not None else CompositeRest(clock=None)
    gate = RestRateLimitGate(
        policy=test_only_signed_call_policy().rate_limit, clock=lambda: UNIT_START
    )
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=the_rest),  # type: ignore[arg-type]
        rest_gate=gate,
        signed_call_policy=test_only_signed_call_policy(),
    )
    equity = LiveEquitySource(
        adapter=adapter, clock=clock, limits=the_limits, quote_asset=TEST_ONLY_QUOTE
    )
    brackets = BracketCache(adapter=adapter, clock=clock, limits=the_limits)
    config_guard = SymbolConfigGuard(adapter=adapter, target_leverage=TEST_ONLY_TARGET_LEVERAGE)
    day_store = InMemoryDayRiskStore()
    day_reader = ScriptedDayRiskReader()
    day_risk = LiveDayRiskService(
        reader=day_reader,
        store=day_store,
        equity=equity,
        clock=clock,
        symbols={TEST_ONLY_SYMBOL},
        quote_asset=TEST_ONLY_QUOTE,
        funding_policy=FundingPolicy.TRADES_WITH_UNVERIFIED_FUNDING,
        parameter_set=TEST_ONLY_PARAMETER_SET,
        limits=the_limits,
    )
    the_reservations = reservations if reservations is not None else FakeReservations()
    the_registry = registry if registry is not None else LateRegistry()
    commission: dict[str, AccountCommission | None] = {}

    def commission_for(symbol: str) -> AccountCommission | None:
        if symbol in commission:
            return commission[symbol]
        now = clock()
        return AccountCommission(
            symbol=symbol,
            maker_rate=D("0.0002"),
            taker_rate=D("0.0004"),
            observed_at_utc=now - timedelta(seconds=60),
        )

    producer = LiveRiskInputProducer(
        adapter=exchange,  # type: ignore[arg-type]
        equity=equity,
        day_risk=day_risk,
        config_guard=config_guard,
        brackets=brackets,
        reservations=the_reservations,  # type: ignore[arg-type]
        protections=the_registry,  # type: ignore[arg-type]
        cost_rates_for=(
            cost_rates_for
            if cost_rates_for is not None
            else make_cost_rates_for(commission_for=commission_for, parameter_set=the_params)
        ),
        parameter_set=the_params,
        execution_limits=the_limits,
        drift_limits=drift_limits_for_tests(),
        alert_sink=alert_sink,
        clock=clock,
        signal_context_for=static_context(signal, bar_close),
        margin_guard=margin_guard,
        snapshot_recorder=lambda snapshot: None,  # plan 24-37 (F3): required, TEST_ONLY no-op
    )
    return Parts(
        producer=producer,
        clock=clock,
        exchange=exchange,
        rest=the_rest,
        equity=equity,
        brackets=brackets,
        config_guard=config_guard,
        day_risk=day_risk,
        day_store=day_store,
        day_reader=day_reader,
        reservations=the_reservations,
        registry=the_registry,
        limits=the_limits,
        commission=commission,
    )


async def prime(parts: Parts) -> None:
    """Complete one backfill and open the day (what the scheduler did before the CONFIRM)."""
    now = parts.clock()
    await backfill_day_risk(parts.day_risk, now)
    verdict = await parts.day_risk.evaluate(now_utc=parts.clock(), exposure=False)
    assert verdict.state is not None


async def make_producer_rig(**rig_overrides: Any) -> tuple[Any, Parts]:
    # The loss bound is raised for the rig only: the rig's presses take 30 virtual seconds.
    limits = rig_overrides.pop("limits", None) or test_only_execution_limits(
        account_max_daily_loss_age_ms=120_000
    )
    late = LateInputs()
    rig = await make_live_rig(inputs=late, limits=limits, **rig_overrides)
    registry = LateRegistry()
    registry.target = rig.wiring.coordinator
    exchange = ScriptedExchange(wrapped=rig.fake)
    parts = build_parts(
        clock=rig.clock,
        exchange=exchange,
        signal=rig.signal,
        limits=limits,
        registry=registry,
        alert_sink=None,
        rest=CompositeRest(clock=None),
    )
    late.target = parts.producer
    await prime(parts)
    return rig, parts


__all__ = [
    "TEST_ONLY_PARAMS",
    "TEST_ONLY_QUOTE",
    "TEST_ONLY_SYMBOL",
    "UNIT_START",
    "FakeReservations",
    "LateInputs",
    "LateRegistry",
    "MovingClock",
    "Parts",
    "ScriptedExchange",
    "btc_filters",
    "build_parts",
    "make_producer_rig",
    "prime",
    "position_row",
    "static_context",
    "drift_limits_for_tests",
]
