"""The live risk-input producer (plan 24-16; D-21, WR-04, D087).

Two layers. The unit layer builds the producer over REAL library objects (the live equity source,
the day-risk service, the bracket cache, the configuration guard, the margin guard) served by the
recorded-Demo SDK stand-in, with fakes only at the edges (the exchange reads, the reservation
store, the commission). The end-to-end layer puts the same producer under the Phase 24 live rig:
an authorized APPROVE then CONFIRM press reaches `ExecutionService`, the producer builds the
inputs from the account (not from fixtures), the real margin guard configures ISOLATED x5 on the
recorded-Demo symbol configuration, and the real manager places exactly one entry. Every number is
TEST_ONLY (tests/support/live_risk_rig.py); a green test proves the composition against the fakes,
not Binance behavior.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from src.domain.enums import SignalStatus, TradePlanStatus
from src.domain.trade_plan import TradePlan
from src.execution.binding import recompute_plan_hash
from src.execution.execution_limits import ExecutionLimitsNotConfigured
from src.execution.margin_guard import MarginGuard
from src.live.execution_service import (
    EVENT_PLACEMENT_OUTCOME,
    EVENT_PLACEMENT_REFUSED,
    PlacementInputs,
    PlacementRefusal,
)
from src.live.risk_inputs import (
    PLANNED_LEG_COUNT,
    REFUSAL_BRACKETS_UNAVAILABLE,
    REFUSAL_EXCHANGE_STATE_UNAVAILABLE,
    REFUSAL_RESERVATIONS_UNAVAILABLE,
    REFUSAL_SIGNAL_CONTEXT_UNAVAILABLE,
    REFUSAL_SYMBOL_NOT_TRADABLE,
    backfill_day_risk,
)
from src.risk.live_commission import AccountCommission, LiveCostRatesResult
from src.risk.reservations import CountedReservation, ReservationStatus

from tests.shadow_fakes import make_shadow_plan, make_shadow_signal
from tests.support.execution_limits import test_only_execution_limits as limits_with
from tests.support.live_rig import forbid_real_sleep, make_live_rig
from tests.support.live_risk_rig import (
    TEST_ONLY_PARAMS,
    TEST_ONLY_SYMBOL,
    UNIT_START,
    LateInputs,
    LateRegistry,
    MovingClock,
    Parts,
    ScriptedExchange,
    btc_filters,
    build_parts,
    position_row,
)
from tests.support.margin_guard_fakes import CompositeRest, StatefulConfigSdk

D = Decimal
UNCERTAIN = "UNCERTAIN_ACCOUNT_STATE"
RISK_KEYS = {
    "trade_plan",
    "candidate_position_side",
    "account_state",
    "constraint_snapshot",
    "open_positions",
    "daily_loss_quote",
    "now_utc",
    "ttl",
    "cost_rates",
    "min_stop_distance_rate",
    "max_cost_to_risk",
    "minimum_risk_utilization_after_rounding",
    "parameter_set",
}
GATE_KEYS = {"open_algo_count", "planned_leg_count", "positions_reconciled"}


def make_signal_and_plan() -> tuple[Any, TradePlan]:
    signal = make_shadow_signal()
    shadow = make_shadow_plan(signal)
    return signal, dataclasses.replace(shadow, plan_hash=recompute_plan_hash(shadow))


class EventClock(MovingClock):
    """A `MovingClock` that logs every read into a shared event list."""

    def __init__(self, events: list[str]) -> None:
        super().__init__(UNIT_START)
        self.events = events

    def __call__(self) -> datetime:
        self.events.append("clock")
        return super().__call__()


def unit_parts(
    *,
    clock: MovingClock | None = None,
    advance: timedelta = timedelta(0),
    **overrides: Any,
) -> tuple[Parts, Any, TradePlan]:
    the_clock = clock if clock is not None else MovingClock()
    signal, plan = make_signal_and_plan()
    rest = overrides.pop("rest", None) or CompositeRest(clock=the_clock, advance_per_call=advance)
    exchange = overrides.pop("exchange", None) or ScriptedExchange()
    parts = build_parts(clock=the_clock, exchange=exchange, signal=signal, rest=rest, **overrides)
    return parts, signal, plan


async def prime(parts: Parts) -> None:
    """Complete one backfill and open the day (what the scheduler did before the CONFIRM)."""
    now = parts.clock()
    await backfill_day_risk(parts.day_risk, now)
    verdict = await parts.day_risk.evaluate(now_utc=parts.clock(), exposure=False)
    assert verdict.state is not None


# --------------------------------------------------------------------------- #
# The tracer: complete inputs from fakes.
# --------------------------------------------------------------------------- #


async def test_for_plan_returns_complete_inputs_from_the_account() -> None:
    parts, signal, plan = unit_parts()
    await prime(parts)

    result = await parts.producer.for_plan(object(), plan, parts.clock())

    assert isinstance(result, PlacementInputs), result
    assert set(result.risk_kwargs) == RISK_KEYS
    assert set(result.gate_kwargs) == GATE_KEYS
    assert result.risk_kwargs["now_utc"] == result.now_utc
    assert result.gate_kwargs == {
        "open_algo_count": 0,
        "planned_leg_count": PLANNED_LEG_COUNT,
        "positions_reconciled": True,
    }
    state = result.risk_kwargs["account_state"]
    assert state.risk_rate == TEST_ONLY_PARAMS["risk_rate"]
    # The equity is the recorded-Demo account's (min of wallet and margin), not a fixture constant.
    assert state.equity == D("4999.09343961")
    assert result.risk_kwargs["candidate_position_side"] == "LONG"
    assert result.risk_kwargs["daily_loss_quote"] == D("0")
    assert result.risk_kwargs["open_positions"] == []
    assert result.risk_kwargs["trade_plan"].status is TradePlanStatus.APPROVED
    assert result.risk_kwargs["ttl"] == timedelta(seconds=3600)
    assert result.risk_kwargs["cost_rates"].fee_rate_entry == D("0.0005")
    # Thresholds are absolute quote amounts against the persisted day-start base.
    thresholds = result.risk_kwargs["parameter_set"]
    assert thresholds["cluster_cap"] == D("0.006") * D("4999.09343961")
    assert result.expiry_utc == plan.expiry_utc
    assert result.approval_strategy_version == signal.strategy_version
    assert result.approval_parameter_set_id == signal.parameter_set_id
    assert result.approval_parameter_set_hash == signal.parameter_set_hash


async def test_the_live_context_carries_the_real_guard_the_drift_margin_and_the_tp1_fraction() -> (
    None
):
    alerts = object()
    parts, signal, plan = unit_parts(alert_sink=None)
    await prime(parts)
    result = await parts.producer.for_plan(object(), plan, parts.clock())
    assert isinstance(result, PlacementInputs)
    context = result.live_context

    assert isinstance(context.margin_guard, MarginGuard)
    assert context.margin_guard is parts.producer.margin_guard
    assert context.gtd_clock_margin == timedelta(milliseconds=max(500, 1000))
    assert context.tp1_quantity_fraction == D("0.5")
    assert context.latest_closed_bar_close == D("50050")
    assert context.protection_registry is parts.registry
    assert context.signal.status is SignalStatus.APPROVED
    assert context.signal.symbol == TEST_ONLY_SYMBOL
    assert context.plan_constraint_snapshot.trade_plan_id == plan.trade_plan_id
    assert context.plan_constraint_snapshot.working_type == "MARK_PRICE"
    assert context.alert_sink is None
    assert context.execution_limits is parts.limits
    del alerts, signal


async def test_the_alert_sink_passed_in_reaches_the_live_context() -> None:
    class Sink:
        def alert(self, **kwargs: Any) -> None:  # the JournalFirstAlertSink call shape
            raise AssertionError("not called here")

    sink = Sink()
    parts, _, plan = unit_parts(alert_sink=sink)
    await prime(parts)
    result = await parts.producer.for_plan(object(), plan, parts.clock())
    assert isinstance(result, PlacementInputs)
    assert result.live_context.alert_sink is sink


async def test_the_clock_for_now_utc_is_read_after_the_equity_refresh_wr04() -> None:
    events: list[str] = []
    clock = EventClock(events)
    parts, _, plan = unit_parts(clock=clock, advance=timedelta(seconds=1))
    await prime(parts)
    original = parts.equity.refresh

    async def logged_refresh() -> None:
        events.append("refresh")
        await original()
        events.append("refreshed")

    parts.equity.refresh = logged_refresh  # type: ignore[method-assign]
    events.clear()

    result = await parts.producer.for_plan(object(), plan, clock.value)

    assert isinstance(result, PlacementInputs), result
    last_refresh = len(events) - 1 - events[::-1].index("refreshed")
    assert events[last_refresh + 1] == "clock", "the clock is read right after the refresh"
    # The reading was stamped at the start of the refresh, which moved the clock: a `now` read
    # before the refresh would be older than the stamp (a negative age, refused by design).
    assert result.now_utc > clock.value - timedelta(seconds=10)
    assert result.risk_kwargs["now_utc"] == result.now_utc
    assert clock.reads > 0


async def test_a_now_taken_before_the_refresh_would_have_been_refused() -> None:
    """The control of the order test: the builder refuses a negative equity age."""
    clock = MovingClock()
    parts, _, _ = unit_parts(clock=clock, advance=timedelta(seconds=1))
    before = clock.value
    clock.advance(timedelta(seconds=5))  # time passes between taking `now` and the refresh
    await parts.equity.refresh()
    result = parts.equity.resolve(risk_rate=D("0.005"), now_utc=before)
    assert result.is_no_trade


async def test_the_producer_needs_the_owner_equity_age_and_the_registry_values() -> None:
    signal, _ = make_signal_and_plan()
    with pytest.raises(ExecutionLimitsNotConfigured):
        build_parts(
            clock=MovingClock(),
            exchange=ScriptedExchange(),
            signal=signal,
            limits=limits_with(account_max_equity_age_ms=None),
        )
    broken = {k: v for k, v in TEST_ONLY_PARAMS.items() if k != "risk_rate"}
    with pytest.raises(ValueError, match="risk_rate"):
        build_parts(clock=MovingClock(), exchange=ScriptedExchange(), signal=signal, params=broken)


# --------------------------------------------------------------------------- #
# Every missing or stale input refuses (T-24-44, T-24-45).
# --------------------------------------------------------------------------- #


def _stale_equity(parts: Parts) -> None:
    original = parts.equity.refresh

    async def slow_refresh() -> None:
        await original()
        parts.clock.advance(timedelta(seconds=20))  # type: ignore[attr-defined]

    parts.equity.refresh = slow_refresh  # type: ignore[method-assign]


def _equity_refresh_fails(parts: Parts) -> None:
    parts.rest.fail["account_information_v3"] = RuntimeError("scripted")


def _loss_expired(parts: Parts) -> None:
    age_ms = parts.limits.account_max_daily_loss_age_ms
    assert age_ms is not None
    parts.clock.advance(timedelta(milliseconds=age_ms + 1000))  # type: ignore[attr-defined]


def _daily_stop(parts: Parts) -> None:
    parts.day_store.latch_stop(utc_day=parts.clock().date(), at_utc=parts.clock())


def _commission_missing(parts: Parts) -> None:
    parts.commission[TEST_ONLY_SYMBOL] = None


def _commission_stale(parts: Parts) -> None:
    parts.commission[TEST_ONLY_SYMBOL] = AccountCommission(
        symbol=TEST_ONLY_SYMBOL,
        maker_rate=D("0.0002"),
        taker_rate=D("0.0004"),
        observed_at_utc=parts.clock() - timedelta(hours=3),
    )


def _brackets_read_fails(parts: Parts) -> None:
    parts.rest.fail["notional_and_leverage_brackets"] = RuntimeError("scripted")


def _brackets_too_old(parts: Parts) -> None:
    # The read itself takes longer than margin.max_bracket_age_ms: it is stale on return.
    parts.rest._advance = timedelta(seconds=30)  # noqa: SLF001
    parts.rest._clock = parts.clock  # noqa: SLF001


def _unexplained_position(parts: Parts) -> None:
    parts.exchange.positions = [position_row(TEST_ONLY_SYMBOL, "0.5")]


def _positions_unreadable(parts: Parts) -> None:
    parts.exchange.fail.add("snapshot_positions")


def _algo_orders_unreadable(parts: Parts) -> None:
    parts.exchange.fail.add("snapshot_open_algo_orders")


def _exchange_info_fails(parts: Parts) -> None:
    parts.exchange.fail.add("exchange_info")


def _symbol_halted(parts: Parts) -> None:
    parts.exchange.filters = [btc_filters(status="BREAK")]


def _symbol_missing(parts: Parts) -> None:
    parts.exchange.filters = [btc_filters(symbol="ETHUSDT")]


def _reservations_unreadable(parts: Parts) -> None:
    parts.reservations.fail_counted = RuntimeError("scripted")


REFUSALS = [
    pytest.param(_equity_refresh_fails, UNCERTAIN, id="equity-refresh-failed"),
    pytest.param(_stale_equity, UNCERTAIN, id="equity-older-than-max-equity-age"),
    pytest.param(_loss_expired, UNCERTAIN, id="daily-loss-older-than-max-daily-loss-age"),
    pytest.param(_daily_stop, "DAILY_STOP_BLOCK", id="daily-stop-latched"),
    pytest.param(_commission_missing, UNCERTAIN, id="commission-unknown"),
    pytest.param(_commission_stale, UNCERTAIN, id="commission-older-than-ttl"),
    pytest.param(_brackets_read_fails, REFUSAL_BRACKETS_UNAVAILABLE, id="brackets-read-failed"),
    pytest.param(_brackets_too_old, REFUSAL_BRACKETS_UNAVAILABLE, id="brackets-older-than-bound"),
    pytest.param(_unexplained_position, UNCERTAIN, id="exchange-position-no-reservation"),
    pytest.param(
        _positions_unreadable, REFUSAL_EXCHANGE_STATE_UNAVAILABLE, id="positions-unreadable"
    ),
    pytest.param(
        _algo_orders_unreadable, REFUSAL_EXCHANGE_STATE_UNAVAILABLE, id="algo-orders-unreadable"
    ),
    pytest.param(
        _exchange_info_fails, REFUSAL_EXCHANGE_STATE_UNAVAILABLE, id="exchange-info-failed"
    ),
    pytest.param(_symbol_halted, REFUSAL_SYMBOL_NOT_TRADABLE, id="symbol-not-trading"),
    pytest.param(_symbol_missing, REFUSAL_EXCHANGE_STATE_UNAVAILABLE, id="symbol-not-listed"),
    pytest.param(
        _reservations_unreadable, REFUSAL_RESERVATIONS_UNAVAILABLE, id="reservations-unreadable"
    ),
]


@pytest.mark.parametrize(("break_it", "reason"), REFUSALS)
async def test_each_missing_or_stale_input_refuses_and_sends_nothing(
    break_it: Any, reason: str
) -> None:
    parts, _, plan = unit_parts()
    await prime(parts)
    sdk_calls_before = len(parts.rest.calls)
    break_it(parts)

    result = await parts.producer.for_plan(object(), plan, parts.clock())

    assert isinstance(result, PlacementRefusal), result
    assert result.reason == reason
    posts = [name for name in parts.rest.calls[sdk_calls_before:] if name.startswith("change_")]
    assert posts == [], "the producer never changes the account configuration"


def test_the_refusal_table_has_at_least_eight_cases() -> None:
    assert len(REFUSALS) >= 8


async def test_a_plan_without_a_signal_context_refuses() -> None:
    parts, _, plan = unit_parts()
    await prime(parts)
    other = dataclasses.replace(plan, signal_id="f" * 64)

    result = await parts.producer.for_plan(object(), other, parts.clock())

    assert result == PlacementRefusal(reason=REFUSAL_SIGNAL_CONTEXT_UNAVAILABLE)


async def test_an_unexpected_failure_is_a_refusal_with_only_the_class_name_kept() -> None:
    parts, _, plan = unit_parts()
    await prime(parts)

    def boom(symbol: str, now: datetime) -> LiveCostRatesResult:
        raise KeyError("a secret-looking exception text")

    parts.producer._cost_rates_for = boom  # type: ignore[method-assign, assignment]  # noqa: SLF001

    result = await parts.producer.for_plan(object(), plan, parts.clock())

    assert isinstance(result, PlacementRefusal)
    assert parts.producer.last_error_type == "KeyError"
    assert "secret" not in result.reason


async def test_open_algo_orders_count_toward_the_headroom_inputs() -> None:
    parts, _, plan = unit_parts()
    parts.exchange.algo = [object()] * 7
    await prime(parts)
    # exposure is now reported to the day service as present; the day is already open.
    result = await parts.producer.for_plan(object(), plan, parts.clock())
    assert isinstance(result, PlacementInputs), result
    assert result.gate_kwargs["open_algo_count"] == 7


async def test_other_reservations_become_open_positions_and_the_candidate_is_excluded() -> None:
    parts, _, plan = unit_parts()
    await prime(parts)
    parts.reservations.counted = [
        CountedReservation(
            trade_plan_id="other-plan",
            plan_hash="e" * 64,
            symbol="ETHUSDT",
            position_side="LONG",
            status=ReservationStatus.RESERVED,
            open_risk=D("10"),
        ),
        CountedReservation(
            trade_plan_id=plan.trade_plan_id,
            plan_hash=plan.plan_hash,
            symbol=TEST_ONLY_SYMBOL,
            position_side="LONG",
            status=ReservationStatus.RESERVED,
            open_risk=D("20"),
        ),
    ]

    result = await parts.producer.for_plan(object(), plan, parts.clock())

    assert isinstance(result, PlacementInputs), result
    (position,) = result.risk_kwargs["open_positions"]
    assert (position.symbol, position.open_risk) == ("ETHUSDT", D("10"))


# --------------------------------------------------------------------------- #
# D087: the backfill keeps the loss known; a stale loss still refuses.
# --------------------------------------------------------------------------- #


async def test_backfill_renews_the_known_loss_and_without_it_the_next_plan_refuses() -> None:
    parts, _, plan = unit_parts()
    await prime(parts)
    limit_ms = parts.limits.account_max_daily_loss_age_ms
    assert limit_ms is not None
    step = timedelta(milliseconds=limit_ms * 6 // 10)  # 60 % of the bound

    parts.clock.advance(step)  # type: ignore[attr-defined]
    assert await backfill_day_risk(parts.day_risk, parts.clock()) is None
    parts.clock.advance(step)  # type: ignore[attr-defined]
    renewed = await parts.producer.for_plan(object(), plan, parts.clock())
    assert isinstance(renewed, PlacementInputs), renewed

    # Two more steps with no backfill: 120 % of the bound since the last one.
    parts.clock.advance(step)  # type: ignore[attr-defined]
    parts.clock.advance(step)  # type: ignore[attr-defined]
    stale = await parts.producer.for_plan(object(), plan, parts.clock())
    assert stale == PlacementRefusal(reason=UNCERTAIN)


async def test_backfill_day_risk_reports_the_failure_class_and_never_raises() -> None:
    parts, _, _ = unit_parts()
    parts.day_reader.fail("user_trades_in_window", ConnectionError("scripted"))
    assert await backfill_day_risk(parts.day_risk, parts.clock()) == "ConnectionError"

    async def raising(*, now_utc: datetime) -> None:
        raise OSError("scripted")

    parts.day_risk.backfill = raising  # type: ignore[method-assign]
    assert await backfill_day_risk(parts.day_risk, parts.clock()) == "OSError"


# --------------------------------------------------------------------------- #
# End to end under the live rig: the producer feeds the real manager.
# --------------------------------------------------------------------------- #


async def make_producer_rig(**rig_overrides: Any) -> tuple[Any, Parts]:
    # The loss bound is raised for the rig only: the rig's presses take 30 virtual seconds.
    limits = rig_overrides.pop("limits", None) or limits_with(account_max_daily_loss_age_ms=120_000)
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


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


async def test_the_producer_feeds_the_live_rig_and_exactly_one_entry_is_placed() -> None:
    rig, parts = await make_producer_rig()

    await rig.approve_and_confirm()
    await rig.wiring.service.drain()

    (placement,) = rig.fake.calls_to("place_entry")
    quantity = placement["kwargs"]["quantity"]
    assert D("0") < quantity <= rig.plan.quantity_after_rounding
    (outcome,) = rig.journal.by_type(EVENT_PLACEMENT_OUTCOME)
    assert json.loads(outcome.payload_json) == {"is_no_trade": False, "reason_code": "OK"}
    assert rig.journal.by_type(EVENT_PLACEMENT_REFUSED) == []
    assert parts.producer.last_error_type is None
    # The real margin guard configured the symbol before the entry (recorded CROSSED x20 -> x5).
    assert parts.rest.config_sdk.margin_type == "ISOLATED"
    assert parts.rest.config_sdk.leverage == 5
    assert rig.fake.calls_to("place_algo_protective") == [], "no entry-time stop (D079)"


MANAGER_LEVEL_REFUSALS = [
    pytest.param("headroom", "EXCHANGE_CONSTRAINT", id="algo-orders-above-the-200-headroom"),
    pytest.param("not_changeable", "MARGIN_CONFIG_UNVERIFIED", id="symbol-config-not-verified"),
    pytest.param("margin", "INSUFFICIENT_MARGIN", id="margin-guard-refusal"),
]


@pytest.mark.parametrize(("case", "reason"), MANAGER_LEVEL_REFUSALS)
async def test_manager_level_refusals_place_nothing(case: str, reason: str) -> None:
    rig, parts = await make_producer_rig()
    if case == "headroom":
        parts.exchange.wrapped = None  # serve scripted reads: 199 open algo orders on the account
        parts.exchange.algo = [object()] * 199
    elif case == "not_changeable":
        sdk: StatefulConfigSdk = parts.rest.config_sdk
        sdk.no_change = {"change_margin_type"}  # the POST answers 200 but the state never moves
    else:
        parts.exchange.wrapped = rig.fake
        parts.rest.config_sdk.margin_type = "ISOLATED"
        parts.rest.config_sdk.leverage = 5
        parts.reservations.claims = []
    if case == "margin":
        from src.risk.margin_check import MarginClaim

        parts.reservations.claims = [
            MarginClaim(
                trade_plan_id="other-plan",
                status=ReservationStatus.RESERVED,
                required_margin=D("1000000"),
                placed_at_utc=None,
            )
        ]

    await rig.approve_and_confirm()
    await rig.wiring.service.drain()

    assert rig.fake.calls_to("place_entry") == []
    (outcome,) = rig.journal.by_type(EVENT_PLACEMENT_OUTCOME)
    body = json.loads(outcome.payload_json)
    assert body["is_no_trade"] is True
    assert body["reason_code"] == reason, body
