"""Helper script to compute byte-exact expected outputs for phase4 fixtures.

Run once during fixture creation; outputs are hand-verified then committed.
Not a test file — lives in scripts/ to keep it out of the pytest path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.core.features import compute_features
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import AccountState, Candle, MarketSnapshot
from src.domain.registry import load_parameter_set


def _build_1h_candles() -> list[Candle]:
    """Hand-built bullish 1H sequence with a clear pullback to a support zone.

    250 bars total: 190 bars of gentle uptrend (to warm up EMA200), then
    30 bars of continued uptrend, 20 bars of pullback, 1 swing-low bar,
    8 bars of slow recovery, and 1 reversal confirmation bar at index 249.
    """
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


def _build_4h_candles() -> list[Candle]:
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


def _csv_row(c: Candle) -> str:
    return (
        f"{c.symbol},{c.interval},"
        f"{c.open_time_utc.strftime('%Y-%m-%dT%H:%M:%SZ')},"
        f"{c.open},{c.high},{c.low},{c.close},{c.volume}"
    )


def main() -> None:
    fixtures_dir = Path("tests/fixtures/phase4")
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    candles_1h = _build_1h_candles()
    candles_4h = _build_4h_candles()

    csv_path = fixtures_dir / "candles.csv"
    with csv_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("symbol,timeframe,open_time_utc,open,high,low,close,volume\n")
        for c in candles_1h + candles_4h:
            f.write(_csv_row(c) + "\n")

    ps = load_parameter_set("trend-pullback", "baseline-v1")
    params_path = fixtures_dir / "parameters.json"
    params_path.write_text(
        json.dumps(
            {
                "strategy_id": ps.strategy_id,
                "strategy_version": ps.strategy_version,
                "parameter_set_id": ps.parameter_set_id,
                "parameter_set_hash": ps.parameter_set_hash,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = MarketSnapshot(
        symbol="BTCUSDT",
        setup_candles=candles_1h,
        context_candles=candles_4h,
        source_timeframe="1h",
    )
    account = AccountState(
        equity=Decimal("10000.00"),
        risk_rate=Decimal("0.005"),
    )

    setup_frame = compute_features(
        symbol="BTCUSDT",
        interval="1h",
        candles=candles_1h,
        parameter_set=ps,
    )
    context_frame = compute_features(
        symbol="BTCUSDT",
        interval="4h",
        candles=candles_4h,
        parameter_set=ps,
    )

    expected_features = {
        "setup_frame_valid": setup_frame.features_valid,
        "context_frame_valid": context_frame.features_valid,
        "setup_atr": str(setup_frame.atr_14.value) if setup_frame.atr_14.valid else None,
        "setup_swing_high": str(setup_frame.swing_high.value) if setup_frame.swing_high.valid else None,
        "setup_swing_low": str(setup_frame.swing_low.value) if setup_frame.swing_low.valid else None,
        "setup_zone_upper": str(setup_frame.zone_upper.value) if setup_frame.zone_upper.valid else None,
        "setup_zone_lower": str(setup_frame.zone_lower.value) if setup_frame.zone_lower.valid else None,
        "setup_ema_20": str(setup_frame.ema_20.value) if setup_frame.ema_20.valid else None,
        "setup_ema_50": str(setup_frame.ema_50.value) if setup_frame.ema_50.valid else None,
        "setup_ema_200": str(setup_frame.ema_200.value) if setup_frame.ema_200.valid else None,
        "context_ema_50": str(context_frame.ema_50.value) if context_frame.ema_50.valid else None,
    }

    features_path = fixtures_dir / "expected_features.json"
    features_path.write_text(
        json.dumps(expected_features, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = evaluate(
        snapshot=snapshot,
        account_state=account,
        strategy_version=ps.strategy_version,
        parameter_set=ps,
    )

    if result.is_no_trade:
        signals_payload = {"signals": [], "reason_code": result.reason_code}
        plans_payload = {"plans": []}
    else:
        signal = result.signal
        assert signal is not None
        signals_payload = {
            "signals": [
                {
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
            ]
        }
        tp = plan(
            signal=signal,
            setup_candles=candles_1h,
            parameter_set=ps,
            account_state=account,
            created_at_utc=datetime(2026, 9, 19, 23, 0, 0, tzinfo=UTC),
        )
        plans_payload = {
            "plans": [
                {
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
            ]
        }

    signals_path = fixtures_dir / "expected_signals.json"
    signals_path.write_text(
        json.dumps(signals_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    plans_path = fixtures_dir / "expected_plans.json"
    plans_path.write_text(
        json.dumps(plans_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("Wrote fixtures:")
    print(f"  {csv_path}")
    print(f"  {params_path}")
    print(f"  {features_path}")
    print(f"  {signals_path}")
    print(f"  {plans_path}")
    print(f"  is_no_trade: {result.is_no_trade}")
    print(f"  reason_code: {result.reason_code}")


if __name__ == "__main__":
    main()
