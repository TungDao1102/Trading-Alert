"""The liquidation watch policy, TP placement with real-data snapshots, the shared read (24-16).

* `build_liquidation_watch` returns the watch with the policy the owner chose (24-01 Q9, DECISIONS
  D085 O-4): a failed post-fill check CLOSES the position. A protection rig with that watch (the
  real `LiquidationWatch`, the real emergency closer, the Phase 19 stateful fake exchange) shows
  the coordinator's close path and one critical alert; a control with a far liquidation price
  closes nothing. The fake serves `liquidation_price=None`, so the tests wrap `snapshot_positions`
  to put a TEST_ONLY price on the rows; none is exchange data.
* The producer's constraint snapshot is the real-data one (exchangeInfo, no fixture). The manager
  completes the margin type, leverage and equity from the margin guard's verdict (gate 5g); with
  that, `snapshot_is_valid_for_live` holds and the coordinator places TP1 and TP2 (24-NOTES item 6)
  instead of TP_UNAVAILABLE.
* `read_pre_placement_inputs` reads each of the six gate 5e inputs once, and the CONFIRM recheck
  accepts the `ConfirmInputs` built from the same readings.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from src.adapters.binance_public import LastPriceReading, MarkPriceReading
from src.domain.enums import LiveInputsStatus
from src.execution.binding import recompute_plan_hash
from src.execution.confirm_recheck import (
    CONFIRM_INPUTS_UNAVAILABLE,
    PrefetchedConfirmInputs,
    make_confirm_recheck,
    prefetched_provider,
)
from src.execution.constraint_snapshot import snapshot_is_valid_for_live
from src.execution.execution_limits import ExecutionLimitsNotConfigured
from src.execution.liquidation_watch import (
    LIQUIDATION_TOO_CLOSE_AFTER_FILL,
    LiquidationFailurePolicy,
    LiquidationWatch,
    LiquidationWatchAction,
    LiquidationWatchInput,
)
from src.execution.order_ids import derive_algo_client_id
from src.execution.protection import BRANCH_B6_LIQUIDATION_TOO_CLOSE, ProtectionState
from src.live.risk_inputs import (
    PositionModeUnavailable,
    build_liquidation_watch,
    confirm_inputs_from_readings,
    read_pre_placement_inputs,
)
from src.risk.liquidation import Bracket

from tests.shadow_fakes import make_shadow_plan, make_shadow_signal
from tests.support.execution_limits import test_only_execution_limits as limits_with
from tests.support.live_rig import forbid_real_sleep
from tests.support.live_risk_rig import (
    TEST_ONLY_SYMBOL,
    MovingClock,
    ScriptedExchange,
    btc_filters,
    make_producer_rig,
    position_row,
)
from tests.support.margin_guard_stub import VERIFIED_MARGIN_TYPE, passing_verdict
from tests.support.phase22_fixtures import demo_brackets
from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, make_rig

D = Decimal


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


# --------------------------------------------------------------------------- #
# The liquidation watch: CLOSE_POSITION (Q9).
# --------------------------------------------------------------------------- #


class _Brackets:
    """A `BracketSource` serving the recorded Demo table (demo-observed, not mainnet)."""

    async def get(self, *, symbol: str) -> Any:
        brackets: list[Bracket] = demo_brackets()
        return SimpleNamespace(brackets=brackets)


class _FeeRates:
    async def entry_fee_rate(self, *, symbol: str) -> Decimal | None:
        return D("0.0004")


def _watch() -> LiquidationWatch:
    return build_liquidation_watch(
        brackets=_Brackets(), fee_rates=_FeeRates(), limits=limits_with()
    )


def _put_liquidation_price(fake: Any, value: Decimal | None) -> None:
    original = fake.snapshot_positions

    async def with_price(**kwargs: Any) -> Any:
        rows = await original(**kwargs)
        return [replace(row, liquidation_price=value) for row in rows]

    fake.snapshot_positions = with_price


async def _to_protected(rig: Any) -> None:
    rig.coordinator.fill_sink(rig.stream_fill(D("0.004")))
    await rig.coordinator.step()
    await rig.clock.advance(1)
    await rig.coordinator.step()
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None and protection.state is ProtectionState.PROTECTED


def test_the_built_watch_carries_the_owner_policy_close_position() -> None:
    watch = _watch()
    assert isinstance(watch, LiquidationWatch)
    assert watch.policy is LiquidationFailurePolicy.CLOSE_POSITION


def test_the_watch_needs_the_liquidation_buffer_limit() -> None:
    with pytest.raises(ExecutionLimitsNotConfigured):
        build_liquidation_watch(
            brackets=_Brackets(),
            fee_rates=_FeeRates(),
            limits=limits_with(margin_liquidation_buffer_bps=None),
        )


async def test_a_failed_check_judges_close_for_a_liquidation_price_at_the_stop() -> None:
    inputs = LiquidationWatchInput(
        symbol=TEST_ONLY_SYMBOL,
        side="LONG",
        stop_price=D("59000"),
        leverage=5,
        quantity=D("0.004"),
        entry_price=D("60000"),
        exchange_liquidation_price=D("59000"),
    )
    verdict = await _watch().check(inputs)
    assert verdict.action is LiquidationWatchAction.CLOSE
    assert verdict.reason == LIQUIDATION_TOO_CLOSE_AFTER_FILL


async def test_a_failed_post_fill_check_closes_through_the_coordinator_and_alerts() -> None:
    rig = await make_rig(liquidation_watch=_watch(), real_closer=True)
    _put_liquidation_price(rig.fake, rig.entry.sl_trigger_price)  # not beyond the stop: fails
    await _to_protected(rig)

    await rig.clock.advance(1)
    await rig.coordinator.step()

    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    transitions = rig.transitions()
    assert ("PROTECTED", "CLOSE_REQUIRED") in transitions
    assert len(rig.fake.calls_to("place_market_close")) == 1
    assert rig.fake.positions[rig.entry.symbol] == D("0")
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", BRANCH_B6_LIQUIDATION_TOO_CLOSE)
    ]
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]


async def test_a_passing_check_closes_nothing() -> None:
    rig = await make_rig(liquidation_watch=_watch(), real_closer=True)
    _put_liquidation_price(rig.fake, D("40000"))  # far beyond the stop of a LONG
    await _to_protected(rig)

    await rig.clock.advance(1)
    await rig.coordinator.step()

    assert rig.fake.calls_to("place_market_close") == []
    assert rig.alerts.alerts == []
    assert ("PROTECTED", "CLOSE_REQUIRED") not in rig.transitions()


# --------------------------------------------------------------------------- #
# TP placement with the producer's real-data snapshot (24-NOTES item 6).
# --------------------------------------------------------------------------- #


async def test_the_producer_snapshot_is_valid_for_live_once_the_guard_verdict_completes_it() -> (
    None
):
    rig, parts = await make_producer_rig()
    await rig.approve_and_confirm()
    inputs = await parts.producer.for_plan(rig.approve_row(), rig.plan, rig.clock.now())
    snapshot = inputs.live_context.plan_constraint_snapshot  # type: ignore[union-attr]

    # exchangeInfo gives every filter; the three account values come from the guard (gate 5g).
    assert snapshot.live_inputs_status is LiveInputsStatus.INCOMPLETE
    assert (snapshot.margin_type, snapshot.leverage, snapshot.equity_used) == (None, None, None)
    ttl = inputs.risk_kwargs["ttl"]  # type: ignore[union-attr]
    now = inputs.now_utc  # type: ignore[union-attr]
    verdict = passing_verdict()
    completed = dataclasses.replace(
        snapshot,
        margin_type=verdict.margin_type,
        leverage=verdict.leverage,
        equity_used=verdict.equity_used,
    )
    assert completed.margin_type == VERIFIED_MARGIN_TYPE
    assert snapshot_is_valid_for_live(completed, now_utc=now, ttl=ttl)
    assert not snapshot_is_valid_for_live(snapshot, now_utc=now, ttl=ttl)


async def test_a_snapshot_without_the_exchange_filters_never_becomes_valid() -> None:
    """The control: a missing market-lot filter keeps the snapshot INCOMPLETE after the guard."""
    rig, parts = await make_producer_rig()
    parts.exchange.filters = [btc_filters(market_lot_max_quantity=None)]
    await rig.approve_and_confirm()
    inputs = await parts.producer.for_plan(rig.approve_row(), rig.plan, rig.clock.now())
    snapshot = inputs.live_context.plan_constraint_snapshot  # type: ignore[union-attr]
    verdict = passing_verdict()
    completed = dataclasses.replace(
        snapshot,
        margin_type=verdict.margin_type,
        leverage=verdict.leverage,
        equity_used=verdict.equity_used,
    )
    assert not snapshot_is_valid_for_live(
        completed,
        now_utc=inputs.now_utc,  # type: ignore[union-attr]
        ttl=inputs.risk_kwargs["ttl"],  # type: ignore[union-attr]
    )


async def test_after_a_fill_and_a_terminal_entry_the_coordinator_places_tp1_and_tp2() -> None:
    rig, parts = await make_producer_rig()
    await rig.approve_and_confirm()
    await rig.wiring.service.drain()
    (placement,) = rig.fake.calls_to("place_entry")
    quantity: Decimal = placement["kwargs"]["quantity"]
    coordinator = rig.wiring.coordinator

    rig.fake.fill(rig.entry_id, quantity=quantity)
    assert rig.route(rig.trade_frame(str(quantity))).fills == 1
    await coordinator.step()
    await rig.clock.advance(1)
    await coordinator.step()
    protection = coordinator.protection_of(rig.plan.plan_hash)
    assert protection is not None and protection.state is ProtectionState.PROTECTED

    await coordinator.step()

    protection = coordinator.protection_of(rig.plan.plan_hash)
    assert protection is not None and protection.state is ProtectionState.COMPLETE
    placed = [c["kwargs"]["client_algo_id"] for c in rig.fake.calls_to("place_algo_protective")]
    assert placed == [
        derive_algo_client_id(plan_hash=rig.plan.plan_hash, role=role)
        for role in ("STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2")
    ]
    assert rig.alerts.alerts == [], "no TP_UNAVAILABLE alert"
    assert rig.safe_mode.in_safe_mode is False
    assert parts.producer.last_error_type is None


# --------------------------------------------------------------------------- #
# The shared pre-placement read.
# --------------------------------------------------------------------------- #

NOW = MovingClock().value


def _readings_exchange(clock: MovingClock) -> ScriptedExchange:
    exchange = ScriptedExchange()
    exchange.mark = MarkPriceReading(
        symbol=TEST_ONLY_SYMBOL, mark_price=D("50050"), exchange_time_utc=NOW - timedelta(seconds=1)
    )
    exchange.last = LastPriceReading(
        symbol=TEST_ONLY_SYMBOL, last_price=D("50050"), exchange_time_utc=NOW - timedelta(seconds=1)
    )
    return exchange


def _plan_and_signal() -> tuple[Any, Any]:
    signal = make_shadow_signal()
    shadow = make_shadow_plan(signal, expiry_utc=NOW + timedelta(hours=4))
    return signal, dataclasses.replace(shadow, plan_hash=recompute_plan_hash(shadow))


class _Registry:
    def __init__(self, blocks: bool = False) -> None:
        self.blocks = blocks

    def blocks_new_entries(self) -> bool:
        return self.blocks


async def test_each_gate_5e_input_is_read_once_and_stamped_after_the_reads() -> None:
    clock = MovingClock()
    reads: list[str] = []
    exchange = _readings_exchange(clock)

    def stamped() -> Any:
        reads.append("clock")
        return clock()

    readings = await read_pre_placement_inputs(exchange, TEST_ONLY_SYMBOL, stamped)  # type: ignore[arg-type]

    assert exchange.calls == [
        "get_mark_price",
        "get_last_price",
        "snapshot_open_normal_orders",
        "snapshot_open_algo_orders",
        "snapshot_positions",
        "get_position_mode",
    ]
    assert reads == ["clock"], "the clock is read once, after the last read"
    assert readings.position_mode == "ONE_WAY"
    assert readings.checked_at_utc == NOW
    assert readings.positions == [] and readings.algo_orders == [] and readings.normal_orders == []


async def test_a_failed_read_is_none_and_the_others_are_still_read() -> None:
    exchange = _readings_exchange(MovingClock())
    exchange.fail.update({"get_mark_price", "get_position_mode"})

    readings = await read_pre_placement_inputs(exchange, TEST_ONLY_SYMBOL, MovingClock())  # type: ignore[arg-type]

    assert readings.mark is None and readings.position_mode is None
    assert readings.last is not None and readings.positions == []
    with pytest.raises(PositionModeUnavailable):
        signal, plan = _plan_and_signal()
        confirm_inputs_from_readings(
            readings,
            signal=signal,
            plan=plan,
            execution_limits=limits_with(),
            latest_closed_bar_close=D("50050"),
            gtd_clock_margin=timedelta(seconds=1),
            protections=_Registry(),
        )


async def _recheck(exchange: ScriptedExchange, *, blocks: bool = False) -> str | None:
    signal, plan = _plan_and_signal()
    clock = MovingClock()
    readings = await read_pre_placement_inputs(exchange, TEST_ONLY_SYMBOL, clock)  # type: ignore[arg-type]
    holder = PrefetchedConfirmInputs()
    holder.put(
        plan.trade_plan_id,
        confirm_inputs_from_readings(
            readings,
            signal=signal,
            plan=plan,
            execution_limits=limits_with(),
            latest_closed_bar_close=D("50050"),
            gtd_clock_margin=timedelta(seconds=1),
            protections=_Registry(blocks),
        ),
    )
    recheck = make_confirm_recheck(prefetched_provider(holder))
    first = recheck(signal, plan, clock())
    assert recheck(signal, plan, clock()) == CONFIRM_INPUTS_UNAVAILABLE, "single use"
    return first


async def test_the_confirm_recheck_accepts_inputs_built_from_healthy_readings() -> None:
    assert await _recheck(_readings_exchange(MovingClock())) is None


async def test_the_confirm_recheck_refuses_a_hedge_account() -> None:
    exchange = _readings_exchange(MovingClock())
    exchange.dual_side = True
    assert await _recheck(exchange) == "HEDGE_MODE_UNSUPPORTED"


async def test_the_confirm_recheck_refuses_an_existing_position_or_an_unprotected_one() -> None:
    held = _readings_exchange(MovingClock())
    held.positions = [position_row(TEST_ONLY_SYMBOL, "0.01")]
    assert await _recheck(held) is not None
    assert await _recheck(_readings_exchange(MovingClock()), blocks=True) is not None


async def test_the_confirm_recheck_refuses_a_missing_price() -> None:
    exchange = _readings_exchange(MovingClock())
    exchange.fail.add("get_last_price")
    assert await _recheck(exchange) is not None
