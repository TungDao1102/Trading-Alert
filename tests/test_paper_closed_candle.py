"""Phase 7 paper-loop closed-candle tests (plan 07-01, task 1).

Per D-01/D-02: the paper loop's closed-candle gate is the determinism
boundary between backtest replay and wall-clock observation. A WS kline
event with `x=False` (forming update) MUST NOT reach the engine. An
event with `x=True` but `close_time_utc > now_utc` (future-close) MUST
NOT reach the engine. Only `x=True AND close_time_utc <= now_utc`
events flow through the identical core + risk call chain.

The test loads the golden fixture pair (input.json + expected.json)
from `tests/fixtures/phase7/clean_run/`, feeds the sequence through
the loop entrypoint, and asserts the canonical-JSON hash of the
outcome dict equals the expected digest. A separate test pins the
forming-update silence contract.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.domain.canonical import sha256_hex

PHASE7_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"


def _load_input(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Test 1 — closed 1H event flows end-to-end through the engine.
# --------------------------------------------------------------------------- #


def test_clean_run_closed_candle_emits_canonical_outcome() -> None:
    """Beh. 1: one closed 1H event flows WS event → engine verdict.

    The closed event (x=True, close_time <= now_utc) flows through the
    identical compute_features → evaluate → plan → resolve_absolute_thresholds
    → size_position → quantize → check_portfolio → evaluate_risk chain.
    The canonical-JSON hash of the resulting outcome dict equals the
    expected digest pinned in tests/fixtures/phase7/clean_run/expected.json.
    """
    from src.paper.loop import run_paper_tick

    case_dir = PHASE7_FIXTURES_DIR / "clean_run"
    case_input = _load_input(case_dir)
    expected = _load_expected(case_dir)

    outcome = run_paper_tick(case_input)
    digest = sha256_hex(outcome)

    assert digest == expected["outcome_digest"], (
        f"outcome digest mismatch: got {digest!r}, "
        f"expected {expected['outcome_digest']!r}"
    )


# --------------------------------------------------------------------------- #
# Test 2 — forming updates (x=False) emit no Signal / no TradePlan.
# --------------------------------------------------------------------------- #


def test_forming_updates_emit_no_signal() -> None:
    """Beh. 2: every x=False event short-circuits to silence.

    The forming update in the clean_run fixture (x=False, close_time
    > now_utc) must NOT reach evaluate/plan/size/check_portfolio. The
    resulting outcome list contains zero Signal entries and zero
    TradePlan entries attributable to the forming bar.
    """
    from src.paper.loop import run_paper_tick

    case_dir = PHASE7_FIXTURES_DIR / "clean_run"
    case_input = _load_input(case_dir)

    # Drop the closed event so only the forming update remains; the
    # loop must emit no Signal from a single forming update.
    forming_only_input = {
        **case_input,
        "feed_events": [
            event
            for event in case_input["feed_events"]
            if not event["x"]
        ],
    }
    assert forming_only_input["feed_events"], "fixture must include a forming event"

    outcome = run_paper_tick(forming_only_input)
    signals = outcome.get("signals", [])
    trade_plans = outcome.get("trade_plans", [])
    assert signals == [], f"forming updates must not emit Signals, got {signals}"
    assert trade_plans == [], (
        f"forming updates must not emit TradePlans, got {trade_plans}"
    )


# --------------------------------------------------------------------------- #
# Test 3 — future-close event (x=True, close_time > now) emits nothing.
# --------------------------------------------------------------------------- #


def test_future_close_event_emits_no_signal() -> None:
    """Beh. 3: x=True with close_time > now_utc short-circuits to silence.

    The double-gate invariant: the closed-candle gate requires BOTH
    `x=True` AND `close_time_utc <= now_utc`. An event with `x=True`
    but `close_time_utc > now_utc` (a future-dated close marker) is
    structurally impossible at a real exchange, but the loop must
    defend against it explicitly — the gate is structural, not a
    log warning.
    """
    from src.paper.loop import run_paper_tick

    case_dir = PHASE7_FIXTURES_DIR / "clean_run"
    case_input = _load_input(case_dir)
    now_utc = datetime.fromisoformat(case_input["now_utc"])

    # Build a future-close event: x=True, close_time strictly > now_utc
    # by 1 hour. The loop's double gate rejects it.
    future_close = now_utc.replace(microsecond=0) + timedelta(hours=1)
    future_open = future_close - timedelta(hours=1)
    future_event = {
        "t": int(future_open.timestamp() * 1000),
        "T": int(future_close.timestamp() * 1000),
        "o": "100.00",
        "h": "100.05",
        "l": "99.95",
        "c": "100.00",
        "v": "1.0",
        "n": 10,
        "x": True,
        "q": "1.0",
    }
    future_only_input = {
        **case_input,
        "feed_events": [future_event],
    }

    outcome = run_paper_tick(future_only_input)
    signals = outcome.get("signals", [])
    trade_plans = outcome.get("trade_plans", [])
    assert signals == [], (
        f"future-close events must not emit Signals, got {signals}"
    )
    assert trade_plans == [], (
        f"future-close events must not emit TradePlans, got {trade_plans}"
    )


# --------------------------------------------------------------------------- #
# Test 4 — frozen-clock regression: a fixed now_utc yields identical digest.
# --------------------------------------------------------------------------- #


def test_clean_run_is_byte_deterministic_under_frozen_clock() -> None:
    """Beh. 4: running the clean_run fixture twice yields identical digest.

    Determinism contract: the paper loop is a pure function of the
    feed sequence + injected clock. Running it twice on identical
    inputs must hash identically.
    """
    from src.paper.loop import run_paper_tick

    case_dir = PHASE7_FIXTURES_DIR / "clean_run"
    case_input = _load_input(case_dir)

    outcome_a = run_paper_tick(case_input)
    outcome_b = run_paper_tick(case_input)
    assert sha256_hex(outcome_a) == sha256_hex(outcome_b)


def test_run_paper_tick_refuses_cost_model_that_disagrees_with_registry() -> None:
    """12-REVIEW WR-03: sizing costs must match the pinned registry set."""
    import pytest
    from src.backtest.binding import CostModelBindingMismatch
    from src.paper.loop import run_paper_tick

    case_input = _load_input(PHASE7_FIXTURES_DIR / "clean_run")
    case_input["cost_model"]["fee_rate_entry"] = "0.0001"
    with pytest.raises(CostModelBindingMismatch):
        run_paper_tick(case_input)
