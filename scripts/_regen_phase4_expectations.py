"""Regenerate byte-exact phase4 expectation fixtures (Phase 04 review fix).

Run: `uv run python scripts/_regen_phase4_expectations.py` from the repo root.

Why this exists: the Phase 04 review fixes intentionally changed
byte-exact outputs (CR-01 registry promotion changed the B/C
parameter-set hashes; CR-03/CR-05/CR-06/WR-01 reworked planner geometry
and setup zones; CR-08 requires created_at inside the expiry window).
The expectation fixtures must be recomputed from the corrected code —
never hand-edited to match.

Windows (all deterministic, Decimal-only, no clock reads):
  - trend-pullback: the 250-bar 1H + 250-bar 4H builders from
    `_compute_phase4_fixtures.py`, with the last 1H bar patched to
    touch the trailing support zone (review CR-06: LONG requires a
    support touch; the unpatched reversal bar touches neither side).
  - breakout-retest: the LONG builders from
    `tests/test_core_strategy_breakout_retest.py`.
  - range-mr: the LONG builders from
    `tests/test_core_strategy_range_mr.py`.

`candles.csv` is NOT rewritten (market inputs are untouched by review
fixes). `created_at_utc` is `source_close + 1h` (inside the 4h expiry
window per CR-08). Outputs are printed for hand-verification before
committing.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "tests"))

from src.core.features import compute_features  # noqa: E402 (sys.path above)
from src.core.planner import plan  # noqa: E402 (sys.path above)
from src.core.strategy import evaluate  # noqa: E402 (sys.path above)
from src.core.types import AccountState, Candle, MarketSnapshot  # noqa: E402 (sys.path above)
from src.domain.registry import load_parameter_set  # noqa: E402 (sys.path above)

import test_core_strategy_breakout_retest as fam_b  # noqa: E402 (sys.path above)
import test_core_strategy_range_mr as fam_c  # noqa: E402 (sys.path above)


def _build_trend_1h() -> list[Candle]:
    rows = []
    base_price = Decimal("50000.00")
    for i in range(250):
        if i < 190:
            close = base_price + Decimal(str(i * 5 + 50))
        elif i < 220:
            close = base_price + Decimal(str(190 * 5 + 50 + (i - 189) * 100))
        elif i < 240:
            close = base_price + Decimal(str(190 * 5 + 50 + 30 * 100 - (i - 219) * 110))
        elif i == 240:
            close = Decimal("50900.00")
        elif i < 249:
            close = Decimal("50900.00") + Decimal(str((i - 240) * 80))
        else:
            close = Decimal("51620.00")
        open_p = close - Decimal("10.00")
        high = close + Decimal("50.00")
        low = close - Decimal("60.00")
        open_time = datetime(2026, 9, 8, 0, 0, 0, tzinfo=UTC) + timedelta(hours=i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=1) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("100.00"),
            )
        )
    return rows


def _build_trend_4h() -> list[Candle]:
    rows = []
    base_price = Decimal("50000.00")
    base = datetime(2026, 9, 9, 0, 0, 0, tzinfo=UTC)
    for i in range(250):
        close = base_price + Decimal(str(i * 50 + 30))
        open_p = close - Decimal("20.00")
        high = close + Decimal("40.00")
        low = close - Decimal("40.00")
        open_time = base + timedelta(hours=4 * i)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                interval="4h",
                open_time_utc=open_time,
                close_time_utc=open_time + timedelta(hours=4) - timedelta(seconds=1),
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=Decimal("500.00"),
            )
        )
    return rows


def _with_support_touch_last_bar(
    candles: list[Candle], strategy_id: str, parameter_set_id: str
) -> list[Candle]:
    """Patch the last bar's low onto the trailing swing low (CR-06 setup)."""
    ps = load_parameter_set(strategy_id, parameter_set_id)
    frame = compute_features(symbol="BTCUSDT", interval="1h", candles=candles, parameter_set=ps)
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


def _evaluate_and_plan(
    strategy_id: str, setup: list[Candle], context: list[Candle]
) -> tuple[dict, dict, dict]:
    ps = load_parameter_set(strategy_id, "baseline-v1")
    account = AccountState(equity=Decimal("10000.00"), risk_rate=Decimal("0.005"))
    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=setup,
        context_candles=context,
        source_timeframe="1h",
    )
    result = evaluate(
        snapshot=snapshot,
        account_state=account,
        strategy_version=ps.strategy_version,
        parameter_set=ps,
    )
    assert not result.is_no_trade, f"{strategy_id}: {result.reason_code}"
    signal = result.signal
    assert signal is not None
    created = signal.source_candle_close_utc + timedelta(hours=1)
    plan_result = plan(
        signal=signal,
        setup_candles=setup,
        parameter_set=ps,
        account_state=account,
        created_at_utc=created,
    )
    assert not plan_result.is_no_trade, f"{strategy_id}: {plan_result.reason_code}"
    tp = plan_result.trade_plan
    assert tp is not None
    param_entry = {
        "strategy_id": ps.strategy_id,
        "parameter_set_id": ps.parameter_set_id,
        "strategy_version": ps.strategy_version,
        "parameter_set_hash": ps.parameter_set_hash,
    }
    signal_entry = {
        "signal_id": signal.signal_id,
        "strategy_id": signal.strategy_id,
        "strategy_version": signal.strategy_version,
        "parameter_set_id": signal.parameter_set_id,
        "parameter_set_hash": signal.parameter_set_hash,
        "symbol": signal.symbol,
        "direction": signal.direction,
        "setup_type": signal.setup_type,
        "source_timeframe": signal.source_timeframe,
        "source_candle_close_utc": signal.source_candle_close_utc.isoformat(),
        "detected_at_utc": signal.detected_at_utc.isoformat(),
        "status": signal.status.value,
        "expires_at_utc": signal.expires_at_utc.isoformat(),
    }
    plan_entry = {
        "trade_plan_id": tp.trade_plan_id,
        "signal_id": tp.signal_id,
        "trade_plan_version": tp.trade_plan_version,
        "entry_model": tp.entry_model,
        "entry_min_price": str(tp.entry_min_price),
        "entry_max_price": str(tp.entry_max_price),
        "stop_loss_price": str(tp.stop_loss_price),
        "take_profit_json": tp.take_profit_json,
        "invalidation_rule_json": tp.invalidation_rule_json,
        "expiry_utc": tp.expiry_utc.isoformat(),
        "expected_rr_json": tp.expected_rr_json,
        "risk_rate": str(tp.risk_rate),
        "risk_budget": str(tp.risk_budget),
        "suggested_quantity": str(tp.suggested_quantity),
        "quantity_before_rounding": str(tp.quantity_before_rounding),
        "quantity_after_rounding": str(tp.quantity_after_rounding),
        "quantization_decision": tp.quantization_decision,
        "plan_hash": tp.plan_hash,
        "status": tp.status.value,
        "created_at_utc": tp.created_at_utc.isoformat(),
    }
    return param_entry, signal_entry, plan_entry


def main() -> None:
    fixtures_dir = Path("tests/fixtures/phase4")

    trend_setup = _with_support_touch_last_bar(_build_trend_1h(), "trend-pullback", "baseline-v1")
    trend_context = _build_trend_4h()
    fam_b_setup = fam_b._build_1h_candles_breakout_retest_long()
    fam_b_context = fam_b._build_4h_candles_bullish()
    fam_c_setup = fam_c._build_1h_candles_range_mr_long()
    fam_c_context = fam_c._build_4h_candles_neutral()

    param_entries: list[dict] = []
    signal_entries: list[dict] = []
    plan_entries: list[dict] = []
    for strategy_id, setup, context in (
        ("trend-pullback", trend_setup, trend_context),
        ("breakout-retest", fam_b_setup, fam_b_context),
        ("range-mr", fam_c_setup, fam_c_context),
    ):
        param_entry, signal_entry, plan_entry = _evaluate_and_plan(strategy_id, setup, context)
        param_entries.append(param_entry)
        signal_entries.append(signal_entry)
        plan_entries.append(plan_entry)
        print(
            f"{strategy_id}: signal={signal_entry['signal_id'][:12]}... "
            f"plan={plan_entry['plan_hash'][:12]}..."
        )

    (fixtures_dir / "parameters.json").write_text(
        json.dumps({"parameter_sets": param_entries}, indent=2) + "\n",
        encoding="utf-8",
    )

    ps_trend = load_parameter_set("trend-pullback", "baseline-v1")
    setup_frame = compute_features(
        symbol="BTCUSDT", interval="1h", candles=trend_setup, parameter_set=ps_trend
    )
    context_frame = compute_features(
        symbol="BTCUSDT", interval="4h", candles=trend_context, parameter_set=ps_trend
    )
    expected_features = {
        "setup_frame_valid": setup_frame.features_valid,
        "context_frame_valid": context_frame.features_valid,
        "setup_atr": str(setup_frame.atr_14.value) if setup_frame.atr_14.valid else None,
        "setup_swing_high": str(setup_frame.swing_high.value)
        if setup_frame.swing_high.valid
        else None,
        "setup_swing_low": str(setup_frame.swing_low.value)
        if setup_frame.swing_low.valid
        else None,
        "setup_zone_upper": str(setup_frame.zone_upper.value)
        if setup_frame.zone_upper.valid
        else None,
        "setup_zone_lower": str(setup_frame.zone_lower.value)
        if setup_frame.zone_lower.valid
        else None,
        "setup_ema_20": str(setup_frame.ema_20.value) if setup_frame.ema_20.valid else None,
        "setup_ema_50": str(setup_frame.ema_50.value) if setup_frame.ema_50.valid else None,
        "setup_ema_200": str(setup_frame.ema_200.value) if setup_frame.ema_200.valid else None,
        "context_ema_50": str(context_frame.ema_50.value) if context_frame.ema_50.valid else None,
    }
    (fixtures_dir / "expected_features.json").write_text(
        json.dumps(expected_features, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (fixtures_dir / "expected_signals.json").write_text(
        json.dumps({"signals": signal_entries}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (fixtures_dir / "expected_plans.json").write_text(
        json.dumps({"plans": plan_entries}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "Wrote parameters.json, expected_features.json, expected_signals.json, expected_plans.json"
    )


if __name__ == "__main__":
    main()
