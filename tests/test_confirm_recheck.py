"""CONFIRM-time re-run of the Phase 19 pre-placement checks (Phase 23, plan 23-05; D-11).

Hand oracles (LONG zone 99.50-100.60, stop 98.00, tick 0.10; same numbers as
tests/test_pre_placement.py): mark 100.00 passes; mark 98.00 is AT the stop (crossed) and refuses
as MARK_PRICE_CROSSED_STOP; a missing mark refuses as MARK_PRICE_UNAVAILABLE; a mark older than
`max_mark_price_age_ms` refuses as MARK_PRICE_UNAVAILABLE (the Phase 19 stale code).

The snapshot is pre-fetched by the composition and consumed by exactly one CONFIRM.
"""

from __future__ import annotations

import ast
import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import src.execution.confirm_recheck as cr
from src.domain.enums import SignalStatus, TradePlanStatus
from src.domain.signal import Signal
from src.execution.confirm_recheck import (
    CONFIRM_INPUTS_MISMATCH,
    CONFIRM_INPUTS_UNAVAILABLE,
    ConfirmInputs,
    PrefetchedConfirmInputs,
    make_confirm_recheck,
    prefetched_provider,
)
from src.execution.pre_placement import PrePlacementInputs

from tests.backtest_plan_helpers import make_trade_plan
from tests.support.ast_guards import wall_clock_calls

NOW = datetime(2026, 1, 5, 10, 0, 0, tzinfo=UTC)
EXPIRY = NOW + timedelta(hours=2)
SYMBOL = "BTCUSDT"
PLAN_ID = "tp-1"
MAX_AGE_MS = 5000
ONE_WAY = "ONE_WAY"
HEDGE = "HEDGE"


def D(text: str) -> Decimal:  # noqa: N802 - terse fixture helper
    return Decimal(text)


def _plan(side: str = "LONG") -> Any:
    stop = "98.00" if side == "LONG" else "102.00"
    return make_trade_plan(
        side,
        entry_min="99.50",
        entry_max="100.60",
        stop_loss=stop,
        signal_close_utc=NOW - timedelta(hours=1),
        expiry_hours=3,
        trade_plan_id=PLAN_ID,
    )


def _signal(direction: str = "LONG", symbol: str = SYMBOL) -> Signal:
    return Signal(
        signal_id="sig-1",
        strategy_id="trend-pullback",
        strategy_version="v1.0.0",
        parameter_set_id="baseline-v1",
        parameter_set_hash="c" * 64,
        symbol=symbol,
        direction=direction,
        setup_type="pullback",
        source_timeframe="1h",
        source_candle_close_utc=NOW - timedelta(hours=1),
        detected_at_utc=NOW - timedelta(hours=1),
        status=SignalStatus.DETECTED,
        expires_at_utc=EXPIRY,
    )


def _inputs(side: str = "LONG", **over: Any) -> PrePlacementInputs:
    stop = "98.00" if side == "LONG" else "102.00"
    base: dict[str, Any] = {
        "side": side,
        "plan_status": TradePlanStatus.APPROVED,
        "signal_invalidated": False,
        "trade_plan": _plan(side),
        "latest_closed_bar_close": D("100.00"),
        "expiry_utc": EXPIRY,
        "now_utc": NOW,
        "min_remaining_validity_seconds": 900,
        "gtd_clock_margin": timedelta(seconds=5),
        "position_symbols": frozenset({"ETHUSDT"}),
        "open_order_symbols": frozenset({"ETHUSDT"}),
        "any_unprotected": False,
        "symbol": SYMBOL,
        "mark_price": D("100.00"),
        "mark_time_utc": NOW - timedelta(milliseconds=1000),
        "mark_checked_at_utc": NOW,
        "max_mark_price_age_ms": MAX_AGE_MS,
        "last_price": D("100.00"),
        "last_time_utc": NOW - timedelta(milliseconds=1000),
        "last_checked_at_utc": NOW,
        "max_last_price_age_ms": 3000,
        "sl_trigger_price": D(stop),
        "entry_min_price": D("99.50"),
        "entry_max_price": D("100.60"),
    }
    base.update(over)
    return PrePlacementInputs(**base)


def _confirm(
    side: str = "LONG", mode: str = ONE_WAY, **over: Any
) -> ConfirmInputs:
    return ConfirmInputs(pre_placement=_inputs(side, **over), position_mode=mode)


def _run(
    snapshot: ConfirmInputs | None, *, side: str = "LONG", now: datetime = NOW
) -> tuple[str | None, PrefetchedConfirmInputs]:
    holder = PrefetchedConfirmInputs()
    if snapshot is not None:
        holder.put(PLAN_ID, snapshot)
    recheck = make_confirm_recheck(prefetched_provider(holder))
    return recheck(_signal(side), _plan(side), now), holder


# --- tracer: put -> recheck -> consumed ----------------------------------------------------


def test_valid_snapshot_passes_and_is_consumed() -> None:
    reason, holder = _run(_confirm())
    assert reason is None
    assert holder.take(PLAN_ID) is None


def test_mark_below_stop_refuses_as_crossed_stop() -> None:
    reason, holder = _run(_confirm(mark_price=D("98.00")))
    assert reason == "MARK_PRICE_CROSSED_STOP"
    assert holder.take(PLAN_ID) is None


def test_mark_missing_refuses_as_unavailable() -> None:
    reason, _ = _run(_confirm(mark_price=None))
    assert reason == "MARK_PRICE_UNAVAILABLE"


def test_stale_mark_refuses() -> None:
    stale = NOW - timedelta(milliseconds=MAX_AGE_MS + 1)
    reason, _ = _run(_confirm(mark_time_utc=stale))
    assert reason == "MARK_PRICE_UNAVAILABLE"


def test_last_price_crossed_stop_refuses() -> None:
    reason, _ = _run(_confirm(last_price=D("98.00")))
    assert reason == "LAST_PRICE_CROSSED_STOP"


def test_second_confirm_finds_no_snapshot() -> None:
    holder = PrefetchedConfirmInputs()
    holder.put(PLAN_ID, _confirm())
    recheck = make_confirm_recheck(prefetched_provider(holder))
    assert recheck(_signal(), _plan(), NOW) is None
    assert recheck(_signal(), _plan(), NOW) == CONFIRM_INPUTS_UNAVAILABLE


# --- identity ------------------------------------------------------------------------------


def test_no_snapshot_refuses_as_unavailable() -> None:
    reason, _ = _run(None)
    assert reason == CONFIRM_INPUTS_UNAVAILABLE == "CONFIRM_INPUTS_UNAVAILABLE"


def test_snapshot_for_another_plan_hash_refuses_as_mismatch() -> None:
    other = dataclasses.replace(_plan(), plan_hash="f" * 64)
    reason, _ = _run(_confirm(trade_plan=other))
    assert reason == CONFIRM_INPUTS_MISMATCH == "CONFIRM_INPUTS_MISMATCH"


def test_snapshot_for_another_symbol_refuses_as_mismatch() -> None:
    reason, _ = _run(_confirm(symbol="ETHUSDT"))
    assert reason == CONFIRM_INPUTS_MISMATCH


def test_snapshot_for_another_side_refuses_as_mismatch() -> None:
    # A SHORT snapshot presented for a LONG confirm.
    reason, _ = _run(_confirm("SHORT", trade_plan=_plan()), side="LONG")
    assert reason == CONFIRM_INPUTS_MISMATCH


def test_mismatched_snapshot_is_still_consumed() -> None:
    reason, holder = _run(_confirm(symbol="ETHUSDT"))
    assert reason == CONFIRM_INPUTS_MISMATCH
    assert holder.take(PLAN_ID) is None


# --- position mode -------------------------------------------------------------------------


def test_hedge_mode_refuses() -> None:
    reason, _ = _run(_confirm(mode=HEDGE))
    assert reason == "HEDGE_MODE_UNSUPPORTED"


def test_unknown_position_mode_raises() -> None:
    with pytest.raises(ValueError, match="unknown position mode"):
        _run(_confirm(mode="BOTH"))


def test_pre_placement_refusal_wins_over_hedge_mode() -> None:
    reason, _ = _run(_confirm(mode=HEDGE, mark_price=D("98.00")))
    assert reason == "MARK_PRICE_CROSSED_STOP"


# --- the validity check runs at the CONFIRM instant ----------------------------------------


def test_remaining_validity_is_evaluated_at_the_press_instant() -> None:
    # Snapshot fetched at NOW passes; pressed 1h50m later only 10 min remain (< 900 s) -> refuse.
    late = EXPIRY - timedelta(minutes=10)
    reason, _ = _run(_confirm(mark_time_utc=late, mark_checked_at_utc=late), now=late)
    assert reason == "VALIDITY_TOO_SHORT"
    # The same snapshot at its own fetch instant would have passed.
    ok, _ = _run(_confirm())
    assert ok is None


def test_price_age_is_measured_at_the_press_instant() -> None:
    # A snapshot whose mark was fresh when fetched is stale when pressed 10 s later.
    later = NOW + timedelta(seconds=10)
    reason, _ = _run(_confirm(), now=later)
    assert reason == "MARK_PRICE_UNAVAILABLE"


def test_press_instant_before_fetch_does_not_make_readings_fresher() -> None:
    # now earlier than mark_checked_at: the fetch instant is kept, never moved backwards.
    earlier = NOW - timedelta(seconds=1)
    reason, _ = _run(_confirm(), now=earlier)
    assert reason is None


# --- holder --------------------------------------------------------------------------------


def test_holder_take_is_single_use_and_put_replaces() -> None:
    holder = PrefetchedConfirmInputs()
    first = _confirm()
    second = _confirm(mark_price=D("99.90"))
    holder.put(PLAN_ID, first)
    holder.put(PLAN_ID, second)
    assert holder.take(PLAN_ID) is second
    assert holder.take(PLAN_ID) is None


def test_holder_keys_are_independent() -> None:
    holder = PrefetchedConfirmInputs()
    holder.put("a", _confirm())
    assert holder.take("b") is None
    assert holder.take("a") is not None


def test_confirm_inputs_is_frozen() -> None:
    snap = _confirm()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.position_mode = HEDGE  # type: ignore[misc]


# --- module hygiene ------------------------------------------------------------------------

_SRC = Path(cr.__file__)


def test_reuses_phase19_checks_not_reimplements() -> None:
    text = _SRC.read_text(encoding="utf-8")
    assert "evaluate_pre_placement" in text
    assert "check_position_mode" in text


def test_module_is_pure() -> None:
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    assert not wall_clock_calls(_SRC)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in imported:
        assert not name.startswith(
            ("src.execution.manager", "src.adapters", "src.persistence")
        ), name
