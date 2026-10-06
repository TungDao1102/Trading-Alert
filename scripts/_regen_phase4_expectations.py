"""Regenerate the Phase 4 regression snapshots of signals and plans (Phase 15, D-19).

Run: `uv run python scripts/_regen_phase4_expectations.py` from the repo root.

Why this exists: `tests/fixtures/phase4/expected_signals.json` and `expected_plans.json` are
regression snapshots (D-19, Phase 14 D-25) of the real planner output on three fixed windows.
Phase 15 corrected the strategy geometry, so the snapshots are recomputed from the corrected
code with the baseline-v6 sets (never hand-edited to match). `expected_plans.json` is consumed
by `tests/test_plan_hash_roundtrip_pg.py::test_planner_hashes_equal_the_pinned_phase4_fixture`,
which builds the same plans from the same windows and sets.

What this script writes: ONLY `expected_signals.json` and `expected_plans.json`.

What it never writes (T-15-19): `tests/fixtures/phase4/parameters.json` and
`expected_features.json`. The pin file is owned by the PA-01 gate
(`scripts/decision_alignment`), which verifies every registered parameter set hash; a
regeneration that rewrote it would silently drop the pins of every other set. The features
snapshot is not written either: the legacy feature values (ATR, EMAs, swing extremes) did not
change in Phase 15, and the legacy trend window it described is gone.

Windows (all deterministic, Decimal-only, no clock reads; the same builders the planner and
geometry tests use, `tests/geometry_builders.py`):
  - trend-pullback: `family_a_long_window` (confirmed pivot low 99.00, last bar touches the
    pivot zone, BULLISH 4h context).
  - breakout-retest LONG: `family_b_long_window` (anchored with-direction retest, BULLISH).
  - range-mr LONG: `range_mr_long_window` (wide triangle, pivot-NEUTRAL 4h context).

`candles.csv` is NOT rewritten. `created_at_utc` is `source_close + 1h` (inside the 4h expiry
window per CR-08). Output files are written with LF line endings so a regeneration on any
platform produces the same bytes (git normalizes the working tree on Windows). Outputs are
printed for hand-verification before committing.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.core.planner import plan  # noqa: E402 (sys.path above)
from src.core.strategy import evaluate  # noqa: E402 (sys.path above)
from src.core.types import AccountState, Candle, MarketSnapshot  # noqa: E402 (sys.path above)
from src.domain.registry import load_parameter_set  # noqa: E402 (sys.path above)
from tests import geometry_builders  # noqa: E402 (sys.path above)

PARAMETER_SET_ID = "baseline-v6"


def _evaluate_and_plan(
    strategy_id: str, setup: list[Candle], context: list[Candle]
) -> tuple[dict, dict]:
    ps = load_parameter_set(strategy_id, PARAMETER_SET_ID)
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
    return signal_entry, plan_entry


def _write_lf(path: Path, payload: object, *, sort_keys: bool) -> None:
    text = json.dumps(payload, indent=2, sort_keys=sort_keys) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main() -> None:
    fixtures_dir = _REPO_ROOT / "tests" / "fixtures" / "phase4"

    trend_setup, trend_context = geometry_builders.family_a_long_window()
    fam_b_setup, fam_b_context = geometry_builders.family_b_long_window()
    fam_c_setup, fam_c_context = geometry_builders.range_mr_long_window()

    signal_entries: list[dict] = []
    plan_entries: list[dict] = []
    for strategy_id, setup, context in (
        ("trend-pullback", trend_setup, trend_context),
        ("breakout-retest", fam_b_setup, fam_b_context),
        ("range-mr", fam_c_setup, fam_c_context),
    ):
        signal_entry, plan_entry = _evaluate_and_plan(strategy_id, setup, context)
        signal_entries.append(signal_entry)
        plan_entries.append(plan_entry)
        print(
            f"{strategy_id}: signal={signal_entry['signal_id'][:12]}... "
            f"plan={plan_entry['plan_hash'][:12]}..."
        )

    _write_lf(fixtures_dir / "expected_signals.json", {"signals": signal_entries}, sort_keys=True)
    _write_lf(fixtures_dir / "expected_plans.json", {"plans": plan_entries}, sort_keys=True)
    print("Wrote expected_signals.json, expected_plans.json")


if __name__ == "__main__":
    main()
