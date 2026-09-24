"""Full planner contract tests for Phase 4 plan 04-03.

Per D-08/D-09: every SETUP produces exactly one TradePlan filling the
frozen trade_plan shape with entry zone, SL, TP1 at minimum_rr, TP2
extension, invalidation, expiry, expected RR, and plan_hash. RR below
minimum_rr yields NO_TRADE with RR_TOO_LOW, never a downgraded plan.

plan_hash equals sha256_hex over the canonical JSON of signal_id plus
entry plus SL plus TPs plus invalidation plus expiry, recomputable by
hand. Quantization fields carry Decimal planner-side estimates with
quantization_decision DEFERRED_TO_RISK; planner never floors or rounds
against stepSize.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/core/planner.py` is updated to the full contract.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from src.core.features import compute_features
from src.core.planner import plan
from src.core.types import AccountState, Candle, PlanResult
from src.domain.canonical import sha256_hex
from src.domain.enums import RejectionReason, TradePlanStatus
from src.domain.ids import derive_child_id
from src.domain.registry import ParameterSet, load_parameter_set

# --------------------------------------------------------------------------- #
# Helpers — load phase4 candles and build Candle objects.
# --------------------------------------------------------------------------- #


def _build_candles_from_csv(rows: list[dict]) -> list[Candle]:
    """Convert CSV dict rows to Candle objects."""
    candles: list[Candle] = []
    for row in rows:
        open_time = datetime.fromisoformat(row["open_time_utc"].replace("Z", "+00:00"))
        interval = row["timeframe"]
        if interval == "1h":
            bar_duration = timedelta(hours=1)
        elif interval == "4h":
            bar_duration = timedelta(hours=4)
        elif interval == "1m":
            bar_duration = timedelta(minutes=1)
        else:
            raise ValueError(f"unknown interval: {interval}")
        close_time = open_time + bar_duration - timedelta(seconds=1)
        candles.append(
            Candle(
                symbol=row["symbol"],
                interval=interval,
                open_time_utc=open_time,
                close_time_utc=close_time,
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                volume=Decimal(row["volume"]),
            )
        )
    return candles


# --------------------------------------------------------------------------- #
# Fixtures — use phase4 candles which are known to produce a valid SETUP.
#
# Plan 04-02 added an intentional gap block to the shared candles.csv
# fixture (D-04 gap-policy boundary case). Feeding ALL 1H candles through
# evaluate()/plan() now hits GAP_IN_SOURCE → DATA_STALE instead of SETUP.
#
# Per D-04/D-08: the planner tests need a gap-free contiguous window.
# We subset the fixture to the first contiguous block (bars before the
# first gap) — this is the minimal correct fix that stays within 04-03
# scope and avoids mutating 04-02-owned files.
#
# Window choice: 1H bars 0..249 (250 bars, before the first gap at
# index 250). The corresponding 4H context is the bars with open_time
# <= the last 1H bar's close_time — enough for the EMA50(4H) regime
# gate (regime gate only requires EMA50 validity per 04-01 decision).
# --------------------------------------------------------------------------- #


def _first_gap_index(rows: list[dict], interval: str) -> int:
    """Return the index of the first gap, or len(rows) if contiguous."""
    from datetime import timedelta

    if interval == "1h":
        expected = timedelta(hours=1)
    elif interval == "4h":
        expected = timedelta(hours=4)
    else:
        raise ValueError(f"unknown interval: {interval}")

    for i in range(1, len(rows)):
        prev_open = datetime.fromisoformat(rows[i - 1]["open_time_utc"].replace("Z", "+00:00"))
        curr_open = datetime.fromisoformat(rows[i]["open_time_utc"].replace("Z", "+00:00"))
        if curr_open - prev_open > expected:
            return i
    return len(rows)


@pytest.fixture
def phase4_candles_csv() -> list[dict]:
    """Load the phase4 candles CSV."""
    path = Path("tests/fixtures/phase4/candles.csv")
    assert path.is_file(), f"missing: {path}"
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def setup_candles(phase4_candles_csv: list[dict]) -> list[Candle]:
    """1H setup candles — contiguous window before the first gap.

    Plan 04-02 added an intentional gap at index 250 of the 1H bars.
    We subset to bars 0..249 to keep a gap-free contiguous window.

    Review fix CR-06: the last fixture bar (a mid-range reversal bar)
    is no longer a valid Family-A setup — LONG requires a touch of the
    SUPPORT zone. The last bar is patched to touch support (its low is
    set to the trailing swing low; times/symbol/interval untouched so
    gap, forming-bar, and correspondence checks are unaffected).
    """
    rows_1h = [r for r in phase4_candles_csv if r["timeframe"] == "1h"]
    gap_idx = _first_gap_index(rows_1h, "1h")
    rows_1h = rows_1h[:gap_idx]
    return _with_support_touch_last_bar(_build_candles_from_csv(rows_1h))


def _with_support_touch_last_bar(candles: list[Candle]) -> list[Candle]:
    """Patch the last bar's low onto the trailing swing low (CR-06 setup)."""
    frame = compute_features(
        symbol="BTCUSDT",
        interval="1h",
        candles=candles,
        parameter_set=load_parameter_set("trend-pullback", "baseline-v1"),
    )
    assert frame.features_valid
    assert frame.swing_low.value is not None
    swing_low = frame.swing_low.value
    last = candles[-1]
    assert last.open >= swing_low and last.close >= swing_low
    patched = Candle(
        symbol=last.symbol,
        interval=last.interval,
        open_time_utc=last.open_time_utc,
        close_time_utc=last.close_time_utc,
        open=last.open,
        high=max(last.high, last.open, last.close),
        low=swing_low,
        close=last.close,
        volume=last.volume,
    )
    return [*candles[:-1], patched]


@pytest.fixture
def context_candles(phase4_candles_csv: list[dict]) -> list[Candle]:
    """4H context candles — first contiguous block (pre-gap truncation).

    Plan 04-02's feature gate requires ALL features valid on both streams
    (including EMA200, which needs 200 bars). Plan 04-04 appended family
    B/C windows with intentional gap blocks (D-04) after the tracer
    window, so the 4H stream is truncated to its first contiguous block
    (500 bars from 2026-09-09 — enough for EMA200(4H) warm-up), mirroring
    the setup_candles truncation above.
    """
    rows_4h = [r for r in phase4_candles_csv if r["timeframe"] == "4h"]
    gap_idx = _first_gap_index(rows_4h, "4h")
    rows_4h = rows_4h[:gap_idx]
    return _build_candles_from_csv(rows_4h)


@pytest.fixture
def parameter_set() -> ParameterSet:
    """Load trend-pullback/baseline-v1."""
    return load_parameter_set("trend-pullback", "baseline-v1")


@pytest.fixture
def account_state() -> AccountState:
    """Standard account state for tests."""
    return AccountState(
        equity=Decimal("10000.00"),
        risk_rate=Decimal("0.005"),
    )


def _get_signal_and_plan(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> PlanResult:
    """Run strategy → plan, return PlanResult."""
    from src.core.strategy import evaluate
    from src.core.types import MarketSnapshot

    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=setup_candles,
        context_candles=context_candles,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade, f"expected SETUP, got NO_TRADE: {result.reason_code}"
    assert result.signal is not None

    # CR-08: created_at must fall inside the signal's expiry window
    # (source_close + signal_expiry_hours), never after it.
    return plan(
        signal=result.signal,
        setup_candles=setup_candles,
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=result.signal.source_candle_close_utc + timedelta(hours=1),
    )


# --------------------------------------------------------------------------- #
# Test 1 — entry zone math: entry_max = zone_upper + entry_buffer_atr * ATR.
# --------------------------------------------------------------------------- #


def test_entry_zone_math_long(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 1: LONG entry zone is built off the SUPPORT zone (CR-06/WR-01)."""
    plan_result = _get_signal_and_plan(
        setup_candles, context_candles, parameter_set, account_state
    )
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None
    assert plan_result.trade_plan.signal_id  # signal exists

    frame = compute_features(
        symbol="BTCUSDT",
        interval="1h",
        candles=setup_candles,
        parameter_set=parameter_set,
    )
    assert frame.features_valid
    assert frame.swing_low.value is not None
    assert frame.atr_14.value is not None

    entry_buffer_atr = Decimal(str(parameter_set.params["entry_buffer_atr"]))
    sl_buffer_atr = Decimal(str(parameter_set.params["sl_buffer_atr"]))
    zone_tolerance_atr = Decimal(str(parameter_set.params["zone_tolerance_atr"]))
    atr = frame.atr_14.value
    swing_low = frame.swing_low.value

    # Per-side Family-A geometry: LONG entry = support zone ± buffer.
    half_width = zone_tolerance_atr * atr
    support_upper = swing_low + half_width
    support_lower = swing_low - half_width
    expected_entry_max = support_upper + entry_buffer_atr * atr
    expected_entry_min = support_lower - entry_buffer_atr * atr
    expected_stop = swing_low - sl_buffer_atr * atr

    tp = plan_result.trade_plan
    assert tp.entry_max_price == expected_entry_max
    assert tp.entry_min_price == expected_entry_min
    assert tp.stop_loss_price == expected_stop


# --------------------------------------------------------------------------- #
# Test 2 — RR gate: exact-equality pass, one-tick-above pass.
# --------------------------------------------------------------------------- #


def test_rr_gate_exact_equality_passes(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2a: TP1 RR exactly equal to minimum_rr is admitted."""
    plan_result = _get_signal_and_plan(
        setup_candles, context_candles, parameter_set, account_state
    )
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None
    assert plan_result.trade_plan.status == TradePlanStatus.READY


def test_rr_gate_one_tick_above_passes(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2b: RR one tick above minimum_rr is admitted."""
    plan_result = _get_signal_and_plan(
        setup_candles, context_candles, parameter_set, account_state
    )
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None


def test_rr_gate_below_returns_no_trade_with_rr_too_low(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2c: RR below minimum_rr returns NO_TRADE with RR_TOO_LOW."""
    from src.core.strategy import evaluate
    from src.core.types import MarketSnapshot

    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=setup_candles,
        context_candles=context_candles,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade
    signal = result.signal
    assert signal is not None

    # Perturb the last candle to widen the zone (deep wick).
    perturbed = list(setup_candles)
    last = perturbed[-1]
    perturbed[-1] = Candle(
        symbol=last.symbol,
        interval=last.interval,
        open_time_utc=last.open_time_utc,
        close_time_utc=last.close_time_utc,
        open=last.open,
        high=last.high,
        low=last.low - Decimal("500.00"),
        close=last.close,
        volume=last.volume,
    )

    plan_result = plan(
        signal=signal,
        setup_candles=perturbed,
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=signal.source_candle_close_utc + timedelta(hours=1),
    )
    assert isinstance(plan_result, PlanResult)
    if plan_result.is_no_trade:
        assert plan_result.reason_code == RejectionReason.RR_TOO_LOW.value
        assert plan_result.trade_plan is None


def test_rr_gate_fires_on_structure_tp_below_minimum(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2d (CR-03): TP1 is structure-derived, so the RR gate can fire.

    With minimum_rr raised above the structure-implied RR, the planner
    must return NO_TRADE with RR_TOO_LOW — the gate is a real
    acceptance threshold, not a tautology.
    """
    from src.core.strategy import evaluate
    from src.core.types import MarketSnapshot

    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=setup_candles,
        context_candles=context_candles,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade
    signal = result.signal
    assert signal is not None

    strict_params = ParameterSet(
        strategy_id=parameter_set.strategy_id,
        strategy_version=parameter_set.strategy_version,
        parameter_set_id=parameter_set.parameter_set_id,
        parameter_set_hash=parameter_set.parameter_set_hash,
        params={**parameter_set.params, "minimum_rr": Decimal("1000")},
    )
    plan_result = plan(
        signal=signal,
        setup_candles=setup_candles,
        parameter_set=strict_params,
        account_state=account_state,
        created_at_utc=signal.source_candle_close_utc + timedelta(hours=1),
    )
    assert isinstance(plan_result, PlanResult)
    assert plan_result.is_no_trade
    assert plan_result.reason_code == RejectionReason.RR_TOO_LOW.value
    assert plan_result.trade_plan is None


# --------------------------------------------------------------------------- #
# Test 2e — fail-closed envelope (CR-02/CR-08/WR-14): never raise, mismatch
# or stale input returns NO_TRADE with the mapped reason.
# --------------------------------------------------------------------------- #


def _valid_signal_and_params(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
):
    """Run evaluate and return (signal, created_at_inside_expiry)."""
    from src.core.strategy import evaluate
    from src.core.types import MarketSnapshot

    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=setup_candles,
        context_candles=context_candles,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade
    assert result.signal is not None
    created = result.signal.source_candle_close_utc + timedelta(hours=1)
    return result.signal, created


def test_plan_empty_candles_returns_no_trade(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2e-i (CR-02): empty setup stream returns DATA_STALE, never raises."""
    signal, created = _valid_signal_and_params(
        setup_candles, context_candles, parameter_set, account_state
    )
    plan_result = plan(
        signal=signal,
        setup_candles=[],
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=created,
    )
    assert plan_result.is_no_trade
    assert plan_result.reason_code == RejectionReason.DATA_STALE.value
    assert plan_result.trade_plan is None


def test_plan_expired_signal_returns_no_trade(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2e-ii (CR-08): created_at past expiry returns APPROVAL_EXPIRED."""
    signal, _ = _valid_signal_and_params(
        setup_candles, context_candles, parameter_set, account_state
    )
    plan_result = plan(
        signal=signal,
        setup_candles=setup_candles,
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=signal.source_candle_close_utc + timedelta(hours=99),
    )
    assert plan_result.is_no_trade
    assert plan_result.reason_code == RejectionReason.APPROVAL_EXPIRED.value
    assert plan_result.trade_plan is None


def test_plan_symbol_mismatch_returns_no_trade(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 2e-iii (WR-14): foreign-symbol candles return DATA_STALE."""
    from dataclasses import replace

    signal, created = _valid_signal_and_params(
        setup_candles, context_candles, parameter_set, account_state
    )
    other = [
        replace(c, symbol="ETHUSDT") for c in setup_candles
    ]
    plan_result = plan(
        signal=signal,
        setup_candles=other,
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=created,
    )
    assert plan_result.is_no_trade
    assert plan_result.reason_code == RejectionReason.DATA_STALE.value
    assert plan_result.trade_plan is None


# --------------------------------------------------------------------------- #
# Test 3 — plan_hash recomputation + trade_plan_id.
# --------------------------------------------------------------------------- #


def test_plan_hash_recomputable_from_payload(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 3a: plan_hash equals sha256_hex over the documented payload."""
    plan_result = _get_signal_and_plan(
        setup_candles, context_candles, parameter_set, account_state
    )
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None

    tp = plan_result.trade_plan
    expected_hash = sha256_hex(
        {
            "signal_id": tp.signal_id,
            "entry_min_price": tp.entry_min_price,
            "entry_max_price": tp.entry_max_price,
            "stop_loss_price": tp.stop_loss_price,
            "take_profit_json": tp.take_profit_json,
            "invalidation_rule_json": tp.invalidation_rule_json,
            "expiry_utc": tp.expiry_utc,
        }
    )
    assert tp.plan_hash == expected_hash


def test_trade_plan_id_derives_from_signal_id(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 3b: trade_plan_id = derive_child_id(signal_id, "trade_plan:v1")."""
    plan_result = _get_signal_and_plan(
        setup_candles, context_candles, parameter_set, account_state
    )
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None

    expected_id = derive_child_id(plan_result.trade_plan.signal_id, "trade_plan:v1")
    assert plan_result.trade_plan.trade_plan_id == expected_id


# --------------------------------------------------------------------------- #
# Test 4 — expiry, invalidation schema, deferred quantization.
# --------------------------------------------------------------------------- #


def test_expiry_equals_source_close_plus_signal_expiry_hours(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 4a: expiry_utc = source_candle_close_utc + signal_expiry_hours."""
    from src.core.strategy import evaluate
    from src.core.types import MarketSnapshot

    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=setup_candles,
        context_candles=context_candles,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account_state,
        strategy_version=parameter_set.strategy_version,
        parameter_set=parameter_set,
    )
    assert not result.is_no_trade
    signal = result.signal
    assert signal is not None

    plan_result = plan(
        signal=signal,
        setup_candles=setup_candles,
        parameter_set=parameter_set,
        account_state=account_state,
        created_at_utc=signal.source_candle_close_utc + timedelta(hours=1),
    )
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None

    signal_expiry_hours = int(parameter_set.params["signal_expiry_hours"])
    expected_expiry = signal.source_candle_close_utc + timedelta(
        hours=signal_expiry_hours
    )
    assert plan_result.trade_plan.expiry_utc == expected_expiry


def test_invalidation_json_schema(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 4b: invalidation JSON carries basis=CANDLE_CLOSE, level, break_distance."""
    plan_result = _get_signal_and_plan(
        setup_candles, context_candles, parameter_set, account_state
    )
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None

    invalidation = json.loads(plan_result.trade_plan.invalidation_rule_json)
    assert invalidation["basis"] == "CANDLE_CLOSE"
    assert "level" in invalidation
    assert invalidation["level"] == str(plan_result.trade_plan.stop_loss_price)
    assert "break_distance_atr" in invalidation


def test_deferred_quantization_equality(
    setup_candles: list[Candle],
    context_candles: list[Candle],
    parameter_set: ParameterSet,
    account_state: AccountState,
) -> None:
    """Beh. 4c: quantity_after_rounding == quantity_before_rounding, DEFERRED_TO_RISK."""
    plan_result = _get_signal_and_plan(
        setup_candles, context_candles, parameter_set, account_state
    )
    assert isinstance(plan_result, PlanResult)
    assert not plan_result.is_no_trade
    assert plan_result.trade_plan is not None

    tp = plan_result.trade_plan
    assert tp.quantization_decision == "DEFERRED_TO_RISK"
    assert tp.quantity_after_rounding == tp.quantity_before_rounding
    assert tp.suggested_quantity == tp.quantity_before_rounding
    assert isinstance(tp.suggested_quantity, Decimal)
    assert isinstance(tp.quantity_before_rounding, Decimal)
    assert isinstance(tp.quantity_after_rounding, Decimal)


# --------------------------------------------------------------------------- #
# Test 5 — no-float guard: src/core/planner.py has no float literals.
# --------------------------------------------------------------------------- #


def test_planner_has_no_float_literals() -> None:
    """Beh. 5: src/core/planner.py contains no float literals or float() calls.

    Per D-10: the pure core is Decimal-only. Float injection would fork
    plan_hash across processes.
    """
    import ast

    path = Path("src/core/planner.py")
    assert path.is_file(), f"missing: {path}"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            pytest.fail(f"planner.py contains float literal at line {node.lineno}")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "float":
                pytest.fail(f"planner.py contains float() call at line {node.lineno}")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "Decimal":
                if node.args and isinstance(node.args[0], ast.Call):
                    inner = node.args[0]
                    if isinstance(inner.func, ast.Name) and inner.func.id == "float":
                        pytest.fail(
                            f"planner.py contains Decimal(float) at line {node.lineno}"
                        )


# --------------------------------------------------------------------------- #
# Test 6 — PlanResult envelope: is_no_trade=True requires trade_plan=None.
# --------------------------------------------------------------------------- #


def test_plan_result_envelope_validation() -> None:
    """Beh. 6: PlanResult enforces is_no_trade/trade_plan consistency."""
    result = PlanResult(is_no_trade=True, trade_plan=None, reason_code="RR_TOO_LOW")
    assert result.is_no_trade
    assert result.trade_plan is None

    with pytest.raises(ValueError, match="is_no_trade=True requires trade_plan=None"):
        PlanResult(
            is_no_trade=True,
            trade_plan="not-none",  # type: ignore[arg-type]
            reason_code="RR_TOO_LOW",
        )

    with pytest.raises(ValueError, match="is_no_trade=False requires a TradePlan"):
        PlanResult(is_no_trade=False, trade_plan=None, reason_code="OK")
