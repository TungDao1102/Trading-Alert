"""SHADOW fill driver over the Phase 14 lifecycle (Phase 16, plan 16-19, D-14, L-02).

Task 1 (tracer): one confirmed plan is filled over recorded minutes through the public Phase 14
functions (`new_plan_state`, `advance`, `booking_for_event`, `build_trade_record`) and the trade
record equals the `simulate` trade for the same minutes byte for byte when the eligibility start
equals the signal close. An AST check proves the driver neither uses the private `_Engine` nor
re-defines a lifecycle step of its own.

Task 3 (below the tracer tests): the Q-B eligibility start (`confirm-plus-one`, decided by the
user), its audit fields, and the replay/restart properties of the threshold.

No network, no wall clock: every instant is an explicit argument.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.backtest.case import ParsedCase, parse_case_input
from src.backtest.constraints import select_constraints
from src.backtest.engine import simulate
from src.backtest.funding import FundingCoverageError
from src.backtest.series import ListMinuteSource, parse_minute_row
from src.core.types import Candle
from src.domain.enums import SignalStatus
from src.domain.signal import Signal
from src.paper import shadow_fill
from src.paper.loop import BarOutcome
from src.paper.shadow import ConfirmOutcome
from src.paper.shadow_fill import (
    STATUS_CONFIRM_BEFORE_SIGNAL_CLOSE,
    STATUS_CONFIRM_NOT_SUCCESSFUL,
    STATUS_ELIGIBLE,
    STATUS_NO_MINUTE_BEFORE_EXPIRY,
    STATUS_PLAN_EXPIRED,
    FillEligibility,
    FundingHistory,
    ShadowFillDriver,
    eligibility_start_for,
)

from tests.backtest_case_helpers import (
    DATA_END,
    SIGNAL_CLOSE,
    SYMBOL,
    at,
    fixed_risk_fn,
    flat_minutes,
    funding_row,
    minute_close,
    minute_row,
)
from tests.test_backtest_engine import tracer_case

SHADOW_FILL_PATH = Path(__file__).resolve().parent.parent / "src" / "paper" / "shadow_fill.py"
QUANTITY = "15.928"
REALIZED_RISK = "49.997992"


def _source(case: dict[str, Any]) -> ListMinuteSource:
    """The recorded minutes of a case as the `MinuteSource` the lifecycle reads."""
    trade = [parse_minute_row(r, kind="trade") for r in case["trade_bars_1m"]]
    mark = [parse_minute_row(r, kind="mark") for r in case["mark_bars_1m"]]
    return ListMinuteSource({SYMBOL: trade}, {SYMBOL: mark})


def _outcome(parsed: ParsedCase) -> BarOutcome:
    """The risk-passed bar outcome of the scripted plan, sized by the same stand-in as simulate."""
    scripted = parsed.scripted_plans[0] if parsed.scripted_plans else None
    assert scripted is not None
    verdict = fixed_risk_fn(QUANTITY, REALIZED_RISK)(trade_plan=scripted.plan)
    closed = Candle(
        symbol=SYMBOL,
        interval="1h",
        open_time_utc=SIGNAL_CLOSE - timedelta(hours=1) + timedelta(milliseconds=1),
        close_time_utc=SIGNAL_CLOSE,
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )
    signal = Signal(
        signal_id=scripted.plan.signal_id,
        strategy_id=parsed.strategy_id,
        strategy_version=parsed.strategy_version,
        parameter_set_id=parsed.parameter_set_id,
        parameter_set_hash="hash",
        symbol=SYMBOL,
        direction=scripted.direction,
        setup_type="SCRIPTED",
        source_timeframe="1h",
        source_candle_close_utc=SIGNAL_CLOSE,
        detected_at_utc=SIGNAL_CLOSE,
        status=SignalStatus.DETECTED,
        expires_at_utc=scripted.plan.expiry_utc,
    )
    return BarOutcome(
        closed_candle=closed,
        stage="risk_passed",
        reason_code="OK",
        signal=signal,
        trade_plan=scripted.plan,
        verdict=verdict,
        regime=scripted.regime,
    )


def _driver(parsed: ParsedCase, expected: dict[str, Any]) -> ShadowFillDriver:
    pit = select_constraints(parsed.constraints, symbol=SYMBOL, bar_close_utc=SIGNAL_CLOSE)
    return ShadowFillDriver(
        cost_model=parsed.cost_model,
        constraint_snapshot=pit.snapshot,
        strategy_version=expected["strategy_version"],
        parameter_set_hash=expected["parameter_set_hash"],
        constraints_extrapolated=pit.extrapolated,
    )


def _funding(parsed: ParsedCase) -> FundingHistory:
    return FundingHistory(
        rows=parsed.funding_rows,
        loaded_start_utc=parsed.data_start_utc,
        loaded_end_utc=parsed.data_end_utc,
    )


def _tracer() -> tuple[dict[str, Any], ParsedCase, dict[str, Any]]:
    case = tracer_case()
    expected = simulate(case, risk_fn=fixed_risk_fn(QUANTITY, REALIZED_RISK))
    return case, parse_case_input(case), expected


# --------------------------------------------------------------------------- #
# Task 1 - tracer
# --------------------------------------------------------------------------- #


def test_shadow_trade_record_equals_the_simulate_trade_when_start_is_the_signal_close() -> None:
    case, parsed, expected = _tracer()
    assert len(expected["trades"]) == 1
    driver = _driver(parsed, expected)

    opened = driver.open(_outcome(parsed), eligibility_start_utc=SIGNAL_CLOSE)
    assert opened.opened
    driver.advance_to(DATA_END, _source(case), funding=_funding(parsed))

    assert driver.is_closed
    assert driver.trade_record().to_dict() == expected["trades"][0]


def test_advancing_in_several_windows_gives_the_same_record_as_one_window() -> None:
    case, parsed, expected = _tracer()
    source = _source(case)
    driver = _driver(parsed, expected)
    driver.open(_outcome(parsed), eligibility_start_utc=SIGNAL_CLOSE)
    for hour, minute in ((10, 0), (10, 1), (10, 30), (10, 40), (11, 0)):
        driver.advance_to(
            datetime(2026, 1, 5, hour, minute, tzinfo=UTC), source, funding=_funding(parsed)
        )
    driver.advance_to(DATA_END, source, funding=_funding(parsed))

    assert driver.trade_record().to_dict() == expected["trades"][0]


def test_bookings_follow_the_lifecycle_events_in_time_order() -> None:
    case, parsed, expected = _tracer()
    driver = _driver(parsed, expected)
    driver.open(_outcome(parsed), eligibility_start_utc=SIGNAL_CLOSE)
    driver.advance_to(DATA_END, _source(case), funding=_funding(parsed))

    assert [b.kind for b in driver.bookings] == ["FILL", "EXIT"]
    times = [b.time_utc for b in driver.bookings]
    assert times == sorted(times)
    record = driver.trade_record()
    assert record.realized_pnl is not None
    assert sum((b.amount for b in driver.bookings), Decimal("0")) == record.realized_pnl


def test_a_position_open_without_funding_history_fails_closed() -> None:
    case, parsed, expected = _tracer()
    driver = _driver(parsed, expected)
    driver.open(_outcome(parsed), eligibility_start_utc=SIGNAL_CLOSE)
    with pytest.raises(FundingCoverageError):
        driver.advance_to(DATA_END, _source(case), funding=None)
    # Nothing moved: the failed window left the state at the signal close.
    assert driver.bookings == ()
    assert driver.advanced_to_utc == SIGNAL_CLOSE


def test_the_driver_calls_the_public_lifecycle_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    case, parsed, expected = _tracer()
    calls: dict[str, int] = {"new_plan_state": 0, "advance": 0, "booking_for_event": 0}

    def spy(name: str) -> Callable[..., Any]:
        original = getattr(shadow_fill, name)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls[name] += 1
            return original(*args, **kwargs)

        return wrapper

    for name in calls:
        monkeypatch.setattr(shadow_fill, name, spy(name))
    driver = _driver(parsed, expected)
    driver.open(_outcome(parsed), eligibility_start_utc=SIGNAL_CLOSE)
    driver.advance_to(DATA_END, _source(case), funding=_funding(parsed))
    driver.trade_record()

    assert calls["new_plan_state"] == 1
    assert calls["advance"] >= 1
    assert calls["booking_for_event"] == 2  # FILL and EXIT


def test_the_driver_neither_uses_the_private_engine_nor_defines_a_lifecycle_step() -> None:
    tree = ast.parse(SHADOW_FILL_PATH.read_text(encoding="utf-8"))
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    referenced |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            referenced |= {alias.name for alias in node.names}
    assert "_Engine" not in referenced
    assert "simulate" not in referenced and "simulate_detailed" not in referenced
    defined = {
        n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    forbidden = {
        "advance",
        "new_plan_state",
        "booking_for_event",
        "build_trade_record",
        "protective_levels_for_fill",
        "funding_events",
        "cancel_plan",
        "finalize_at_data_end",
    }
    assert defined.isdisjoint(forbidden), defined & forbidden


def test_an_outcome_that_did_not_pass_risk_is_refused() -> None:
    _case, parsed, expected = _tracer()
    passed = _outcome(parsed)
    rejected = BarOutcome(
        closed_candle=passed.closed_candle,
        stage="risk",
        reason_code="UTILIZATION_REJECT",
        signal=passed.signal,
        trade_plan=passed.trade_plan,
        verdict=passed.verdict,
    )
    driver = _driver(parsed, expected)
    with pytest.raises(ValueError, match="risk_passed"):
        driver.open(rejected, eligibility_start_utc=SIGNAL_CLOSE)


# --------------------------------------------------------------------------- #
# Task 3 - Q-B eligibility start (confirm-plus-one, decided by the user 2026-10-09)
# --------------------------------------------------------------------------- #

PLAN_EXPIRY = SIGNAL_CLOSE + timedelta(hours=4)


def _eligibility(confirmed_at: datetime | None, **overrides: Any) -> FillEligibility:
    arguments: dict[str, Any] = {
        "signal_close_utc": SIGNAL_CLOSE,
        "plan_expiry_utc": PLAN_EXPIRY,
        "confirm_outcome": ConfirmOutcome.CONFIRMED,
        "confirmed_at_utc": confirmed_at,
    }
    arguments.update(overrides)
    return eligibility_start_for(**arguments)


def test_the_start_is_the_confirm_floored_to_the_minute_plus_exactly_one_minute() -> None:
    confirmed = datetime(2026, 1, 5, 10, 5, 30, 250000, tzinfo=UTC)
    eligibility = _eligibility(confirmed)
    assert eligibility.is_eligible
    assert eligibility.status == STATUS_ELIGIBLE
    assert eligibility.eligibility_start_utc == at(10, 6)


def test_the_plus_one_is_applied_once_even_at_the_last_millisecond_of_the_minute() -> None:
    last_ms = datetime(2026, 1, 5, 10, 5, 59, 999000, tzinfo=UTC)
    assert _eligibility(last_ms).eligibility_start_utc == at(10, 6)


def test_a_confirm_exactly_on_a_minute_boundary_excludes_the_minute_opening_then() -> None:
    eligibility = _eligibility(at(10, 5))
    assert eligibility.eligibility_start_utc == at(10, 6)
    # The minute opening at 10:05 closes at 10:05:59.999, not after the start: never read.
    assert minute_close(at(10, 5)) <= at(10, 6)
    # The first minute that can be read opens at floor + 1 minute.
    assert minute_close(at(10, 6)) > at(10, 6)


@pytest.mark.parametrize(
    "outcome",
    [
        ConfirmOutcome.CANCELLED,
        ConfirmOutcome.EXPIRED_TTL,
        ConfirmOutcome.REJECTED_PLAN_EXPIRED,
        ConfirmOutcome.REJECTED_USER_MISMATCH,
        ConfirmOutcome.REJECTED_OTHER,
    ],
)
def test_a_confirm_that_did_not_succeed_starts_nothing(outcome: ConfirmOutcome) -> None:
    eligibility = _eligibility(at(10, 5), confirm_outcome=outcome)
    assert not eligibility.is_eligible
    assert eligibility.status == STATUS_CONFIRM_NOT_SUCCESSFUL
    assert eligibility.eligibility_start_utc is None


def test_a_successful_outcome_without_a_recorded_confirm_instant_starts_nothing() -> None:
    eligibility = _eligibility(None)
    assert not eligibility.is_eligible
    assert eligibility.status == STATUS_CONFIRM_NOT_SUCCESSFUL


def test_an_expired_plan_starts_nothing() -> None:
    at_expiry = _eligibility(PLAN_EXPIRY)
    after_expiry = _eligibility(PLAN_EXPIRY + timedelta(minutes=5))
    assert at_expiry.status == STATUS_PLAN_EXPIRED
    assert after_expiry.status == STATUS_PLAN_EXPIRED
    assert at_expiry.eligibility_start_utc is None and after_expiry.eligibility_start_utc is None


def test_a_confirm_in_the_last_minute_of_the_plan_leaves_no_minute_to_read() -> None:
    eligibility = _eligibility(PLAN_EXPIRY - timedelta(seconds=10))
    assert eligibility.status == STATUS_NO_MINUTE_BEFORE_EXPIRY
    assert not eligibility.is_eligible


def test_a_confirm_before_the_signal_close_is_refused() -> None:
    eligibility = _eligibility(SIGNAL_CLOSE - timedelta(seconds=1))
    assert eligibility.status == STATUS_CONFIRM_BEFORE_SIGNAL_CLOSE
    assert not eligibility.is_eligible


def test_naive_and_non_utc_instants_are_refused() -> None:
    with pytest.raises(ValueError, match="UTC"):
        _eligibility(datetime(2026, 1, 5, 10, 5))
    plus_seven = datetime(2026, 1, 5, 17, 5, tzinfo=timezone(timedelta(hours=7)))
    with pytest.raises(ValueError, match="UTC"):
        _eligibility(plus_seven)


def test_the_audit_record_carries_signal_close_approve_confirm_and_start() -> None:
    confirmed = datetime(2026, 1, 5, 10, 5, 30, tzinfo=UTC)
    approved = datetime(2026, 1, 5, 10, 5, 10, tzinfo=UTC)
    audit = _eligibility(confirmed, approved_at_utc=approved).to_audit_dict()
    assert audit == {
        "signal_close_utc": SIGNAL_CLOSE.isoformat(),
        "approved_at_utc": approved.isoformat(),
        "confirmed_at_utc": confirmed.isoformat(),
        "eligibility_start_utc": at(10, 6).isoformat(),
        "plan_expiry_utc": PLAN_EXPIRY.isoformat(),
        "status": STATUS_ELIGIBLE,
    }
    # An ineligible confirm still reports what it knows and a null start.
    refused = _eligibility(None, confirm_outcome=ConfirmOutcome.CANCELLED).to_audit_dict()
    assert refused["eligibility_start_utc"] is None
    assert refused["status"] == STATUS_CONFIRM_NOT_SUCCESSFUL


def test_the_threshold_depends_only_on_the_recorded_confirm_instant() -> None:
    """A restart rebuilds the threshold from the journaled ISO text and gets the same instant."""
    confirmed = datetime(2026, 1, 5, 10, 5, 30, 250000, tzinfo=UTC)
    first = _eligibility(confirmed)
    replayed = _eligibility(datetime.fromisoformat(confirmed.isoformat()))
    assert first == replayed
    assert first.eligibility_start_utc == replayed.eligibility_start_utc


def test_the_module_reads_no_clock() -> None:
    tree = ast.parse(SHADOW_FILL_PATH.read_text(encoding="utf-8"))
    clock_names = {"now", "utcnow", "today", "time", "monotonic", "perf_counter"}
    called = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert called.isdisjoint(clock_names), called & clock_names


# --- fills against the threshold -------------------------------------------------------------


def _trade_minutes(through: set[int], *, count: int = 30) -> list[dict[str, str]]:
    """Minutes 10:00.. of which only those at the given minute numbers trade through 100.00."""
    rows = []
    for index in range(count):
        if index in through:
            prices = ("100.20", "100.30", "99.80", "100.00")
        else:
            prices = ("100.60", "100.70", "100.40", "100.60")
        rows.append(minute_row(SYMBOL, at(10, index), *prices, kind="trade"))
    return rows


def _threshold_case(through: set[int]) -> dict[str, Any]:
    mark = [
        *flat_minutes(SYMBOL, at(10, 0), 40, "100.00", kind="mark"),
        minute_row(SYMBOL, at(10, 40), "98.50", "98.60", "97.90", "98.20", kind="mark"),
    ]
    return tracer_case(trade_minutes=_trade_minutes(through), mark_minutes=mark)


class _RecordingSource:
    """A MinuteSource that remembers which trade and mark minutes the lifecycle was shown."""

    def __init__(self, inner: ListMinuteSource) -> None:
        self._inner = inner
        self.trade_opens: list[datetime] = []
        self.mark_opens: list[datetime] = []

    def trade_minutes(
        self, symbol: str, start_exclusive: datetime, end_inclusive: datetime
    ) -> Sequence[Candle]:
        minutes = self._inner.trade_minutes(symbol, start_exclusive, end_inclusive)
        self.trade_opens.extend(m.open_time_utc for m in minutes)
        return minutes

    def mark_minutes(
        self, symbol: str, start_exclusive: datetime, end_inclusive: datetime
    ) -> Sequence[Candle]:
        minutes = self._inner.mark_minutes(symbol, start_exclusive, end_inclusive)
        self.mark_opens.extend(m.open_time_utc for m in minutes)
        return minutes


def _confirmed_driver(
    case: dict[str, Any], confirmed_at: datetime
) -> tuple[ShadowFillDriver, ParsedCase, dict[str, Any], FillEligibility]:
    parsed = parse_case_input(case)
    expected = simulate(case, risk_fn=fixed_risk_fn(QUANTITY, REALIZED_RISK))
    eligibility = _eligibility(confirmed_at)
    driver = _driver(parsed, expected)
    assert driver.open_confirmed(_outcome(parsed), eligibility).opened
    return driver, parsed, expected, eligibility


def test_no_fill_before_the_threshold_and_the_confirm_minute_is_never_used() -> None:
    # Minute 10:05 (the confirm minute) trades through the limit; 10:06-10:09 do not;
    # 10:10 does. A start at the confirm minute or the signal close would fill at 10:05.
    case = _threshold_case({5, 10})
    confirmed = datetime(2026, 1, 5, 10, 5, 30, tzinfo=UTC)
    driver, parsed, _expected, eligibility = _confirmed_driver(case, confirmed)
    source = _RecordingSource(_source(case))

    driver.advance_to(at(10, 9), source, funding=_funding(parsed))  # before the 10:10 fill
    assert driver.events == ()
    driver.advance_to(DATA_END, source, funding=_funding(parsed))

    fills = [e for e in driver.events if e.kind == "FILL"]
    assert len(fills) == 1
    assert fills[0].time_utc == minute_close(at(10, 10))
    assert eligibility.eligibility_start_utc == at(10, 6)
    assert min(source.trade_opens) == at(10, 6)
    # No minute that closes at or before the threshold was shown to the lifecycle at all.
    assert all(minute_close(opened) > at(10, 6) for opened in source.trade_opens)
    assert at(10, 5) not in source.trade_opens


def test_when_the_first_eligible_minute_trades_through_it_fills_exactly_there() -> None:
    case = _threshold_case({5, 6, 10})
    driver, parsed, _expected, _eligibility_ = _confirmed_driver(
        case, datetime(2026, 1, 5, 10, 5, 30, tzinfo=UTC)
    )
    source = _RecordingSource(_source(case))
    driver.advance_to(DATA_END, source, funding=_funding(parsed))

    fills = [e for e in driver.events if e.kind == "FILL"]
    assert [f.time_utc for f in fills] == [minute_close(at(10, 6))]
    assert source.trade_opens.count(at(10, 6)) == 1


def test_a_confirm_on_the_boundary_does_not_fill_on_the_minute_opening_then() -> None:
    case = _threshold_case({5, 10})
    driver, parsed, _expected, eligibility = _confirmed_driver(case, at(10, 5))
    driver.advance_to(DATA_END, _source(case), funding=_funding(parsed))

    assert eligibility.eligibility_start_utc == at(10, 6)
    fills = [e for e in driver.events if e.kind == "FILL"]
    assert [f.time_utc for f in fills] == [minute_close(at(10, 10))]


def test_the_first_eligible_minute_is_processed_once_across_windows_and_replays() -> None:
    case = _threshold_case({6})
    driver, parsed, _expected, _eligibility_ = _confirmed_driver(
        case, datetime(2026, 1, 5, 10, 5, 30, tzinfo=UTC)
    )
    source = _RecordingSource(_source(case))
    funding = _funding(parsed)
    for now in (at(10, 5), at(10, 6), at(10, 7), at(10, 7), at(10, 6), at(10, 8)):
        driver.advance_to(now, source, funding=funding)

    assert source.trade_opens.count(at(10, 6)) == 1
    assert len([e for e in driver.events if e.kind == "FILL"]) == 1
    assert len([b for b in driver.bookings if b.kind == "FILL"]) == 1


def test_restart_and_replay_give_the_same_threshold_and_no_duplicate_fill() -> None:
    case = _threshold_case({6})
    confirmed = datetime(2026, 1, 5, 10, 5, 30, tzinfo=UTC)
    driver, parsed, expected, first_eligibility = _confirmed_driver(case, confirmed)
    funding = _funding(parsed)
    driver.advance_to(at(10, 20), _source(case), funding=funding)

    # A restart: nothing survives but the journaled confirm instant; everything is rebuilt.
    restarted = _driver(parsed, expected)
    second_eligibility = _eligibility(datetime.fromisoformat(confirmed.isoformat()))
    assert restarted.open_confirmed(_outcome(parsed), second_eligibility).opened
    restarted.advance_to(at(10, 20), _source(case), funding=funding)

    assert second_eligibility.eligibility_start_utc == first_eligibility.eligibility_start_utc
    assert restarted.eligibility_start_utc == driver.eligibility_start_utc
    assert restarted.bookings == driver.bookings
    assert restarted.events == driver.events
    # Replaying the same window on either driver adds nothing.
    assert restarted.advance_to(at(10, 20), _source(case), funding=funding) == ()
    assert len([b for b in restarted.bookings if b.kind == "FILL"]) == 1


def test_an_ineligible_confirm_cannot_open_a_fill_simulation() -> None:
    case = _threshold_case({6})
    parsed = parse_case_input(case)
    expected = simulate(case, risk_fn=fixed_risk_fn(QUANTITY, REALIZED_RISK))
    refused = _eligibility(None, confirm_outcome=ConfirmOutcome.CANCELLED)
    driver = _driver(parsed, expected)
    with pytest.raises(ValueError, match="not eligible"):
        driver.open_confirmed(_outcome(parsed), refused)
    assert not driver.is_opened
    with pytest.raises(RuntimeError, match="no plan is open"):
        driver.advance_to(DATA_END, _source(case))


def test_funding_is_booked_with_the_engine_functions_on_the_open_position() -> None:
    """A non-zero funding instant inside the open stretch matches the simulate trade."""
    rows = [
        funding_row(SYMBOL, instant, rate)
        for instant, rate in (
            (datetime(2026, 1, 4, 16, 0, tzinfo=UTC), "0"),
            (at(0), "0"),
            (at(8), "0"),
            (at(10, 20), "0.0001"),
            (at(16), "0"),
            (datetime(2026, 1, 6, 0, 0, tzinfo=UTC), "0"),
        )
    ]
    case = tracer_case(funding=rows)
    expected = simulate(case, risk_fn=fixed_risk_fn(QUANTITY, REALIZED_RISK))
    parsed = parse_case_input(case)
    driver = _driver(parsed, expected)
    driver.open(_outcome(parsed), eligibility_start_utc=SIGNAL_CLOSE)
    driver.advance_to(at(10, 30), _source(case), funding=_funding(parsed))
    driver.advance_to(DATA_END, _source(case), funding=_funding(parsed))

    assert driver.funding_event_count == 1
    # LONG with a positive rate pays: -15.928 x 100 x 0.0001.
    assert driver.funding_amount == Decimal("-0.1592800")
    assert [b.kind for b in driver.bookings] == ["FILL", "FUNDING", "EXIT"]
    assert driver.trade_record().to_dict() == expected["trades"][0]
