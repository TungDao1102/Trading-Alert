"""Plan 16-26 Task 2: the market inputs of the live tick (D-35, Q-G folded into O-07, D-17).

The exchange constraints come from the public `exchangeInfo` with the ratified refresh cadence and
time-to-live (a stale snapshot is the existing STALE_CONSTRAINTS verdict, never a fallback), the
account inputs come from the ratified configuration, open positions and the daily loss come
through a required port that src does not implement (plan 16-31), and the start measures the host
clock against Binance server time once.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
import src.domain.registry as domain_registry
from src.adapters.binance_public import SymbolFilters
from src.backtest.costs import cost_rates_from_model, guard_rates_from_params
from src.backtest.ledger import roll_to
from src.backtest.records import BOOKING_EXIT, Booking
from src.core.types import AccountState, Candle
from src.paper import market_inputs
from src.paper.freeze import load_parameter_set_at_root
from src.paper.runtime_config import AccountConfig, ExitCode
from src.paper.shadow_ledger import ShadowLedger
from src.paper.shadow_runtime import bind_risk_inputs
from src.paper.vocabulary import RuntimeEventType
from src.risk.gating import evaluate_risk
from src.risk.portfolio import resolve_absolute_thresholds
from src.risk.types import ConstraintSnapshot

from tests.test_paper_runtime_admission import _Rig
from tests.test_paper_runtime_loop import (
    HOUR,
    NOW,
    FakePublic,
    FakeRiskInputs,
    FixedClock,
    Live,
    filters,
    wait_until,
)
from tests.test_rationale import SET_ID, STRATEGY_ID, write_rationalized_set
from tests.test_risk_portfolio import _mk_trade_plan

REPO_ROOT = Path(__file__).resolve().parent.parent
PAPER_SRC = REPO_ROOT / "src" / "paper"

TTL_SECONDS = 16  # the CONFIG_TEXT constraint_snapshot_ttl_seconds of the admission rig
REFRESH_SECONDS = 17  # its exchange_info_refresh_seconds
ACCOUNT = AccountConfig(initial_equity=Decimal("1000"), risk_rate=Decimal("0.005"))


class SteppingClock:
    """An injected clock that moves only when the test says so."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class ChangingPublic(FakePublic):
    """A public adapter whose exchangeInfo tick size changes per call (so refreshes differ)."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next = False

    async def exchange_info(self, symbols: Sequence[str] | None = None) -> list[SymbolFilters]:
        self.exchange_info_calls += 1
        if self.fail_next:
            raise ConnectionError("exchangeInfo unreachable")
        rows = [filters("BTCUSDT"), filters("ETHUSDT")]
        return rows


class RecordingRisk:
    """Test-only RiskInputsProvider that remembers the instants it was asked about."""

    def __init__(
        self,
        params: dict[str, Any],
        *,
        equity: Decimal = ACCOUNT.initial_equity,
        threshold_equity: Decimal | None = None,
    ) -> None:
        self.asked: list[datetime] = []
        self.params = params
        self.equity = equity
        self.threshold_equity = equity if threshold_equity is None else threshold_equity

    def equity_and_thresholds(self, at_utc: datetime) -> tuple[Decimal, dict[str, Any]]:
        self.asked.append(at_utc)
        return self.equity, resolve_absolute_thresholds(
            parameter_set=self.params, equity=self.threshold_equity
        )

    def open_positions(self, at_utc: datetime) -> Sequence[Any]:
        self.asked.append(at_utc)
        return ()

    def daily_loss_quote(self, at_utc: datetime) -> Decimal | None:
        self.asked.append(at_utc)
        return Decimal("0")


@pytest.fixture
def parameter_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    root = tmp_path / "registry"
    write_rationalized_set(root)
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", root)
    return load_parameter_set_at_root(STRATEGY_ID, SET_ID, root)


def candle(symbol: str, close: datetime) -> Candle:
    return Candle(
        symbol=symbol,
        interval="1h",
        open_time_utc=close + timedelta(milliseconds=1) - HOUR,
        close_time_utc=close,
        open=Decimal("50000"),
        high=Decimal("50100"),
        low=Decimal("49900"),
        close=Decimal("50000"),
        volume=Decimal("10"),
    )


def build_context(parameter_set: Any, provider: Any, close: datetime, risk: Any = None) -> Any:
    factory = market_inputs.make_context_factory(
        parameter_set=parameter_set,
        constraints=provider,
        risk_inputs=risk if risk is not None else RecordingRisk(parameter_set.params),
        account=ACCOUNT,
        ttl_seconds=TTL_SECONDS,
    )
    return factory(candle("BTCUSDT", close))


def verdict_of(context: Any, close: datetime) -> Any:
    """Run the context through the real shared risk pipeline for a plan sized at the close."""
    min_stop, max_cost = guard_rates_from_params(context.parameter_set.params)
    return evaluate_risk(
        trade_plan=_mk_trade_plan(risk_rate="0.005", risk_budget="5"),
        candidate_position_side="LONG",
        account_state=context.account_state,
        constraint_snapshot=context.constraint_snapshot,
        open_positions=context.open_positions,
        daily_loss_quote=context.daily_loss_quote,
        now_utc=close,
        ttl=context.ttl,
        cost_rates=cost_rates_from_model(context.cost_model),
        min_stop_distance_rate=min_stop,
        max_cost_to_risk=max_cost,
        minimum_risk_utilization_after_rounding=Decimal(
            str(context.parameter_set.params["minimum_risk_utilization_after_rounding"])
        ),
        parameter_set=context.absolute_thresholds,
    )


# ---------------------------------------------------------------------------------------------- #
# Test 1: constraint snapshots, cadence, ttl, staleness.
# ---------------------------------------------------------------------------------------------- #


async def test_the_provider_builds_one_snapshot_per_configured_symbol_from_exchange_info() -> None:
    clock = SteppingClock()
    public = ChangingPublic()
    provider = market_inputs.ConstraintProvider(
        public=public, symbols=("BTCUSDT", "ETHUSDT"), clock=clock
    )

    await provider.refresh()

    for symbol in ("BTCUSDT", "ETHUSDT"):
        snapshot = provider.snapshot_for(symbol, NOW)
        row = filters(symbol)
        assert snapshot.symbol == symbol
        assert snapshot.price_tick_size == row.price_tick_size
        assert snapshot.quantity_step_size == row.quantity_step_size
        assert snapshot.min_quantity == row.min_quantity
        assert snapshot.min_notional == row.min_notional
        assert snapshot.metadata_observed_at_utc == NOW


async def test_a_symbol_the_exchange_does_not_list_fails_the_refresh() -> None:
    provider = market_inputs.ConstraintProvider(
        public=FakePublic(), symbols=("BTCUSDT", "DOGEUSDT"), clock=SteppingClock()
    )
    with pytest.raises(market_inputs.ConstraintsUnavailable, match="DOGEUSDT"):
        await provider.refresh()


async def test_the_refresh_loop_uses_the_configured_period() -> None:
    public = ChangingPublic()
    provider = market_inputs.ConstraintProvider(
        public=public, symbols=("BTCUSDT",), clock=SteppingClock()
    )
    sleeps: list[timedelta] = []

    async def sleep(delay: timedelta) -> None:
        sleeps.append(delay)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await market_inputs.refresh_forever(
            provider, every=timedelta(seconds=REFRESH_SECONDS), sleep=sleep
        )

    assert sleeps == [timedelta(seconds=REFRESH_SECONDS)] * 3
    assert public.exchange_info_calls == 2, "one refresh after each completed sleep"


async def test_a_failed_refresh_keeps_the_old_snapshot_and_it_goes_stale(
    parameter_set: Any,
) -> None:
    clock = SteppingClock()
    public = ChangingPublic()
    provider = market_inputs.ConstraintProvider(public=public, symbols=("BTCUSDT",), clock=clock)
    await provider.refresh()
    public.fail_next = True
    clock.now = NOW + timedelta(seconds=REFRESH_SECONDS)
    with pytest.raises(ConnectionError):
        await provider.refresh()

    just_inside = NOW + timedelta(seconds=TTL_SECONDS)
    just_outside = NOW + timedelta(seconds=TTL_SECONDS + 1)
    fresh = build_context(parameter_set, provider, just_inside)
    stale = build_context(parameter_set, provider, just_outside)

    assert fresh.ttl == timedelta(seconds=TTL_SECONDS) == stale.ttl
    assert stale.constraint_snapshot.metadata_observed_at_utc == NOW, "no fallback snapshot"
    assert verdict_of(fresh, just_inside).reason_code == "OK"
    stale_verdict = verdict_of(stale, just_outside)
    assert stale_verdict.is_no_trade is True
    assert stale_verdict.reason_code == "STALE_CONSTRAINTS"


async def test_a_bar_is_judged_with_the_snapshot_observed_at_or_before_its_close(
    parameter_set: Any,
) -> None:
    clock = SteppingClock()
    provider = market_inputs.ConstraintProvider(
        public=ChangingPublic(), symbols=("BTCUSDT",), clock=clock
    )
    await provider.refresh()  # observed at NOW
    clock.now = NOW + timedelta(seconds=10)
    await provider.refresh()  # observed 10 s later

    between = build_context(parameter_set, provider, NOW + timedelta(seconds=5))
    assert between.constraint_snapshot.metadata_observed_at_utc == NOW

    before_any = build_context(parameter_set, provider, NOW - timedelta(seconds=5))
    assert before_any.constraint_snapshot.metadata_observed_at_utc == NOW, "earliest, never later"
    assert verdict_of(before_any, NOW - timedelta(seconds=5)).reason_code == "STALE_CONSTRAINTS"


async def test_without_any_snapshot_the_provider_refuses_instead_of_inventing_one() -> None:
    provider = market_inputs.ConstraintProvider(
        public=FakePublic(), symbols=("BTCUSDT",), clock=SteppingClock()
    )
    with pytest.raises(market_inputs.ConstraintsUnavailable):
        provider.snapshot_for("BTCUSDT", NOW)


# ---------------------------------------------------------------------------------------------- #
# Test 2: the BarContext factory and the required risk-inputs port.
# ---------------------------------------------------------------------------------------------- #


async def test_the_context_takes_equity_and_thresholds_from_the_port_and_the_rate_from_config(
    parameter_set: Any,
) -> None:
    provider = market_inputs.ConstraintProvider(
        public=ChangingPublic(), symbols=("BTCUSDT",), clock=SteppingClock()
    )
    await provider.refresh()
    risk = RecordingRisk(
        parameter_set.params, equity=Decimal("987.65"), threshold_equity=Decimal("990")
    )
    close = NOW + timedelta(seconds=1)

    context = build_context(parameter_set, provider, close, risk)

    assert context.symbol == "BTCUSDT"
    assert context.strategy_version == parameter_set.strategy_version
    assert context.parameter_set is parameter_set
    assert ACCOUNT.initial_equity == Decimal("1000"), "the configured start differs on purpose"
    assert context.account_state.equity == Decimal("987.65"), "the port's equity, not the config's"
    assert context.account_state.risk_rate == ACCOUNT.risk_rate
    assert context.open_positions == ()
    assert context.daily_loss_quote == Decimal("0")
    assert risk.asked == [close] * 3, "the port is asked three times, each at the bar close"
    assert context.absolute_thresholds["cluster_cap"] == (
        Decimal(parameter_set.params["cluster_cap"]) * Decimal("990")
    )


# ---------------------------------------------------------------------------------------------- #
# The equity base (16-DEC-EQUITY-BASE, 16-43 cap reject): the bar pipeline and the ledger agree.
# ---------------------------------------------------------------------------------------------- #

LEDGER_START = datetime(2026, 11, 1, tzinfo=UTC)
LEDGER_START_EQUITY = Decimal("600")
INCIDENT_LOSSES = ("-1.835028", "-1.865155", "-1.843585", "-1.850293")  # the four 16-43 losses
AFTER_LOSSES_EQUITY = Decimal("592.605939")  # 600 - 7.394061
BAR_CLOSE = datetime(2026, 11, 3, 5, 59, 59, 999000, tzinfo=UTC)
INTRADAY_LOSS = Decimal("-1.85")


def incident_parameter_set() -> Any:
    """The parameter set of the 16-43 trial (cluster cap 0.005 of the equity)."""
    return domain_registry.load_parameter_set("trend-pullback", "research-run-1-a01")


def exit_booking(at: datetime, amount: str, plan_id: str) -> Booking:
    return Booking(
        time_utc=at,
        symbol="BTCUSDT",
        trade_plan_id=plan_id,
        amount=Decimal(amount),
        kind=BOOKING_EXIT,
    )


def incident_ledger(params: dict[str, Any], *, intraday: bool = False) -> ShadowLedger:
    """A SHADOW ledger started at 600 that booked the four losses of 2026-11-01."""
    ledger = ShadowLedger(
        initial_equity=LEDGER_START_EQUITY, parameter_set_params=params, started_at_utc=LEDGER_START
    )
    for index, amount in enumerate(INCIDENT_LOSSES):
        ledger.apply(
            exit_booking(LEDGER_START + timedelta(hours=10 + index), amount, f"loss-{index}")
        )
    if intraday:
        ledger.apply(
            exit_booking(datetime(2026, 11, 3, 2, tzinfo=UTC), str(INTRADAY_LOSS), "loss-today")
        )
    return ledger


class FixedConstraints:
    """Point-in-time constraints with a fine quantity step (the sized risk fills the budget)."""

    def __init__(self, observed_at: datetime) -> None:
        self.snapshot = ConstraintSnapshot(
            symbol="BTCUSDT",
            price_tick_size=Decimal("0.1"),
            quantity_step_size=Decimal("0.000001"),
            min_quantity=Decimal("0.000001"),
            min_notional=Decimal("5"),
            metadata_observed_at_utc=observed_at,
        )

    def snapshot_for(self, symbol: str, at_utc: datetime) -> ConstraintSnapshot:
        return self.snapshot


def ledger_context(ledger: ShadowLedger, parameter_set: Any) -> Any:
    factory = market_inputs.make_context_factory(
        parameter_set=parameter_set,
        constraints=cast(Any, FixedConstraints(BAR_CLOSE - timedelta(minutes=1))),
        risk_inputs=bind_risk_inputs(ledger),
        account=AccountConfig(initial_equity=LEDGER_START_EQUITY, risk_rate=Decimal("0.005")),
        ttl_seconds=3600,
    )
    return factory(candle("BTCUSDT", BAR_CLOSE))


def test_a_standard_candidate_passes_the_pipeline_and_the_ledger_after_realized_losses() -> None:
    parameter_set = incident_parameter_set()
    ledger = incident_ledger(parameter_set.params)
    assert ledger.equity == AFTER_LOSSES_EQUITY
    admit_at = BAR_CLOSE + timedelta(seconds=40)

    context = ledger_context(ledger, parameter_set)
    verdict = verdict_of(context, BAR_CLOSE)

    assert verdict.reason_code == "OK"
    assert verdict.sized is not None and verdict.sized.quantity is not None
    reason = ledger.admit(
        symbol="BTCUSDT",
        direction="LONG",
        sized_realized_risk=verdict.sized.realized_risk,
        planned_quantity=verdict.sized.quantity,
        now_utc=admit_at,
    )
    assert reason is None, "the pipeline and the ledger judge the same equity"

    # The old arithmetic (account state and thresholds on the 600 start) is what failed at 16-43.
    stale = dataclasses.replace(
        context,
        account_state=AccountState(equity=LEDGER_START_EQUITY, risk_rate=Decimal("0.005")),
        absolute_thresholds=resolve_absolute_thresholds(
            parameter_set=parameter_set.params, equity=LEDGER_START_EQUITY
        ),
    )
    stale_verdict = verdict_of(stale, BAR_CLOSE)
    assert stale_verdict.reason_code == "OK", "sized on 600 the pipeline still lets it through"
    assert stale_verdict.sized is not None and stale_verdict.sized.quantity is not None
    assert (
        ledger.admit(
            symbol="BTCUSDT",
            direction="LONG",
            sized_realized_risk=stale_verdict.sized.realized_risk,
            planned_quantity=stale_verdict.sized.quantity,
            now_utc=admit_at,
        )
        == "CLUSTER_CAP_REJECT"
    )


def test_the_sizing_equity_and_the_thresholds_are_the_engine_view_at_the_close() -> None:
    parameter_set = incident_parameter_set()
    ledger = incident_ledger(parameter_set.params)

    context = ledger_context(ledger, parameter_set)

    reference = roll_to(ledger.ledger, BAR_CLOSE)
    assert context.account_state.equity == ledger.equity == AFTER_LOSSES_EQUITY
    assert context.account_state.risk_rate == Decimal("0.005")
    assert context.absolute_thresholds == reference.thresholds
    assert context.absolute_thresholds["cluster_cap"] == (
        Decimal(str(parameter_set.params["cluster_cap"])) * AFTER_LOSSES_EQUITY
    )

    # Intraday: sizing follows the CURRENT equity, the thresholds stay on the day-start equity.
    intraday = incident_ledger(parameter_set.params, intraday=True)
    context = ledger_context(intraday, parameter_set)

    expected = roll_to(intraday.ledger, BAR_CLOSE)
    assert expected.equity == AFTER_LOSSES_EQUITY + INTRADAY_LOSS
    assert context.account_state.equity == expected.equity
    assert context.absolute_thresholds == expected.thresholds
    assert expected.equity_at_day_start == AFTER_LOSSES_EQUITY
    assert context.absolute_thresholds["cluster_cap"] == (
        Decimal(str(parameter_set.params["cluster_cap"])) * AFTER_LOSSES_EQUITY
    )
    assert context.daily_loss_quote == -INTRADAY_LOSS
    verdict = verdict_of(context, BAR_CLOSE)
    assert verdict.reason_code == "OK"
    assert verdict.sized is not None and verdict.sized.quantity is not None
    assert (
        intraday.admit(
            symbol="BTCUSDT",
            direction="LONG",
            sized_realized_risk=verdict.sized.realized_risk,
            planned_quantity=verdict.sized.quantity,
            now_utc=BAR_CLOSE + timedelta(seconds=40),
        )
        is None
    )


def test_omitting_the_risk_inputs_port_is_a_type_error(parameter_set: Any) -> None:
    provider = market_inputs.ConstraintProvider(
        public=FakePublic(), symbols=("BTCUSDT",), clock=SteppingClock()
    )
    factory: Callable[..., Any] = market_inputs.make_context_factory
    with pytest.raises(TypeError):
        factory(
            parameter_set=parameter_set,
            constraints=provider,
            account=ACCOUNT,
            ttl_seconds=TTL_SECONDS,
        )


def test_src_has_no_default_implementation_of_the_risk_inputs_port() -> None:
    offenders: list[str] = []
    for path in sorted(PAPER_SRC.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ClassDef) or node.name == "RiskInputsProvider":
                continue
            methods = {n.name for n in node.body if isinstance(n, ast.FunctionDef)}
            if {"open_positions", "daily_loss_quote"} <= methods:
                offenders.append(f"{path.name}:{node.name}")
    assert offenders == []


# ---------------------------------------------------------------------------------------------- #
# Test 3: the clock-skew measurement at start.
# ---------------------------------------------------------------------------------------------- #


async def test_clock_skew_is_host_minus_server_in_whole_milliseconds() -> None:
    clock = SteppingClock()
    public = FakePublic(server_time=NOW - timedelta(milliseconds=1500))
    assert await market_inputs.measure_clock_skew(public, clock) == 1500
    public.server = NOW + timedelta(milliseconds=250)
    assert await market_inputs.measure_clock_skew(public, clock) == -250


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Live]:
    from tests.paper_ws_fakes import fresh_sdk_stream_map

    fresh_sdk_stream_map(monkeypatch)
    rig = _Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", rig.root)
    write_rationalized_set(rig.root)
    rig.authorize()
    assert rig.run("--pin-epoch") == 0
    yield Live(rig)


class SkewPublic(ChangingPublic):
    def __init__(self) -> None:
        super().__init__()
        self.server = NOW - timedelta(milliseconds=1500)
        self.server_time_calls = 0

    async def server_time(self) -> datetime:
        self.server_time_calls += 1
        return self.server


def market_wiring(live: Live, **overrides: Any) -> dict[str, Any]:
    """The wiring of a production-shaped run: only the context factory is NOT overridden."""
    settings: dict[str, Any] = {"context_factory": None, "risk_inputs": FakeRiskInputs()}
    settings.update(overrides)
    return settings


def test_runtime_start_records_the_measured_skew_and_reads_server_time_once(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    public = SkewPublic()
    live.public = public

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)

    assert live.start(script, **market_wiring(live)) == 0

    starts = live.records(RuntimeEventType.RUNTIME_START)
    # The pin exits without RUNTIME_START (16-DEC-PIN-COMMAND): the run's start is the only one.
    assert [dict(s.payload).get("clock_skew_ms") for s in starts] == [1500]
    assert public.server_time_calls == 1
    assert "clock_skew_ms" in capsys.readouterr().out


def test_a_production_shaped_run_refreshes_exchange_info_at_the_configured_period(
    live: Live,
) -> None:
    public = ChangingPublic()
    live.public = public
    sleeps: list[timedelta] = []

    async def sleep(delay: timedelta) -> None:
        sleeps.append(delay)
        if len(sleeps) > 2:
            await asyncio.Event().wait()
        await asyncio.sleep(0)

    async def script(h: Live) -> None:
        await wait_until(lambda: public.exchange_info_calls >= 3)

    assert live.start(script, sleep=sleep, **market_wiring(live)) == 0
    assert sleeps[:2] == [timedelta(seconds=REFRESH_SECONDS)] * 2


def test_the_first_exchange_info_refresh_failing_fails_closed(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    public = ChangingPublic()
    public.fail_next = True
    live.public = public

    async def script(h: Live) -> None:
        await asyncio.Event().wait()

    assert live.start(script, **market_wiring(live)) == ExitCode.FAIL_CLOSED_RUNTIME
    assert "exchangeInfo" in capsys.readouterr().err
    assert live.records(RuntimeEventType.PAPER_BAR_PROCESSED) == []


def test_a_run_without_a_bound_risk_inputs_port_is_refused_before_it_starts(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    async def script(h: Live) -> None:
        await asyncio.Event().wait()

    code = live.start(script, **market_wiring(live, risk_inputs=None))

    assert code == ExitCode.CONFIG_NOT_RATIFIED
    assert "risk inputs" in capsys.readouterr().err
    assert live.records(RuntimeEventType.RUNTIME_START) == [], "the refused run never started"


def test_a_closed_bar_through_the_real_market_inputs_is_recorded(live: Live) -> None:
    clock = FixedClock()

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        h.emit("BTCUSDT", "1h", open_time=NOW - timedelta(hours=2))
        await wait_until(lambda: len(h.records(RuntimeEventType.PAPER_BAR_PROCESSED)) == 1)

    assert live.start(script, clock=clock, **market_wiring(live)) == 0


# ---------------------------------------------------------------------------------------------- #
# Test 4: time is read only through the injected clock.
# ---------------------------------------------------------------------------------------------- #

CLOCK_READ_ATTRS = {("datetime", "now"), ("time", "time"), ("datetime", "utcnow")}
MONOTONIC_ATTRS = {"monotonic", "monotonic_ns", "perf_counter", "perf_counter_ns"}


def _enclosing_function_of_calls(tree: ast.Module) -> list[tuple[str, str]]:
    """(enclosing function name, 'owner.attr') for every attribute call in the module."""
    found: list[tuple[str, str]] = []

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = function
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
            ):
                found.append((function, f"{child.func.value.id}.{child.func.attr}"))
            visit(child, name)

    visit(tree, "<module>")
    return found


@pytest.mark.parametrize("module", ["runtime.py", "market_inputs.py"])
def test_time_is_read_only_through_the_one_clock_and_the_one_monotonic_function(
    module: str,
) -> None:
    tree = ast.parse((PAPER_SRC / module).read_text(encoding="utf-8"))
    calls = _enclosing_function_of_calls(tree)
    clock_reads = [(fn, call) for fn, call in calls if tuple(call.split(".")) in CLOCK_READ_ATTRS]
    monotonic_reads = [(fn, call) for fn, call in calls if call.split(".")[1] in MONOTONIC_ATTRS]
    assert all(fn == "_utc_now" for fn, _ in clock_reads), clock_reads
    assert all(fn == "_monotonic_ms" for fn, _ in monotonic_reads), monotonic_reads
    if module == "market_inputs.py":
        assert clock_reads == [] and monotonic_reads == []


# ---- plan 16-56 Task 2: one malformed unrelated contract (B1-WR-12) -------------------------- #


class _RecordingPublic(FakePublic):
    def __init__(self) -> None:
        super().__init__()
        self.requested: list[Any] = []

    async def exchange_info(self, symbols: Any = None) -> list[SymbolFilters]:
        self.requested.append(symbols)
        return [filters("BTCUSDT"), filters("ETHUSDT")]


async def test_the_refresh_asks_exchange_info_for_its_configured_symbols() -> None:
    public = _RecordingPublic()
    provider = market_inputs.ConstraintProvider(
        public=public, symbols=("BTCUSDT", "ETHUSDT"), clock=FixedClock()
    )
    await provider.refresh()
    assert public.requested == [("BTCUSDT", "ETHUSDT")]


def _sdk_public(records: list[Any]) -> Any:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
        ExchangeInformationResponse,
    )
    from src.adapters.binance_public import BinancePublicMarketData

    class _Response:
        def data(self) -> Any:
            return ExchangeInformationResponse(symbols=records)

    class _Rest:
        def exchange_information(self, **_kwargs: Any) -> Any:
            return _Response()

    sdk = type("Sdk", (), {"rest_api": _Rest()})()
    return BinancePublicMarketData(sdk_client=sdk)


def _record(symbol: str, *, malformed: bool = False) -> Any:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
        ExchangeInformationResponseSymbolsInner,
        ExchangeInformationResponseSymbolsInnerFiltersInner,
    )

    price = ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="PRICE_FILTER", tick_size="0.10"
    )
    lot = ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="LOT_SIZE", step_size="0.001", min_qty="0.001", max_qty="1000"
    )
    notional = ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="MIN_NOTIONAL", notional="5"
    )
    return ExchangeInformationResponseSymbolsInner(
        symbol=symbol,
        contract_type="PERPETUAL",
        status="TRADING",
        base_asset=symbol[:-4],
        quote_asset="USDT",
        margin_asset="USDT",
        filters=[price, notional] if malformed else [price, lot, notional],
    )


FIVE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


async def test_one_malformed_unrelated_contract_no_longer_stops_the_refresh() -> None:
    records = [_record(s) for s in FIVE_SYMBOLS] + [_record("ODDUSDT", malformed=True)]
    provider = market_inputs.ConstraintProvider(
        public=_sdk_public(records), symbols=FIVE_SYMBOLS, clock=FixedClock()
    )
    await provider.refresh()
    for symbol in FIVE_SYMBOLS:
        assert provider.snapshot_for(symbol, NOW).symbol == symbol


async def test_a_malformed_configured_symbol_still_fails_the_whole_refresh() -> None:
    records = [_record(s) for s in FIVE_SYMBOLS[1:]] + [_record("BTCUSDT", malformed=True)]
    provider = market_inputs.ConstraintProvider(
        public=_sdk_public(records), symbols=FIVE_SYMBOLS, clock=FixedClock()
    )
    with pytest.raises(ValueError, match="BTCUSDT"):
        await provider.refresh()
    with pytest.raises(market_inputs.ConstraintsUnavailable):
        provider.snapshot_for("ETHUSDT", NOW)
