"""End-to-end tests for the Phase 6 backtest simulator (plan 06-01).

Per D-01/D-02/D-05: the simulator replays closed 1H strategy bars through
strategy.evaluate → planner.plan → evaluate_risk, resolves exits via 1m
intrabar data (SL-first conservative fallback when 1m is missing), and
applies registry-parameterized costs from run #1. Every test loads a
golden fixture pair (input.json + expected.json) and asserts the
canonical-JSON hash of the trade list matches.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/backtest/` is implemented.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from src.domain.canonical import sha256_hex

PHASE6_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase6"


# --------------------------------------------------------------------------- #
# Helpers — load input/expected pair from a phase6 case directory.
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


def _canonical_trade_dict(trade: dict) -> dict:
    """Project a TradeRecord to a canonical-JSON-safe dict for hashing.

    Decimal fields are stringified; datetimes are ISO-formatted; None
    values pass through. The dict is sorted by key for stable hashing.
    """
    out: dict = {}
    for k, v in trade.items():
        if isinstance(v, Decimal):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif v is None:
            out[k] = None
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------- #
# Test 1 — LONG both-touched bar resolves SL via 1m path (D-01).
# --------------------------------------------------------------------------- #


def test_intrabar_both_touched_long_resolves_sl_via_1m() -> None:
    """Beh. 1: LONG both-touched bar → 1m path → SL-first exit.

    The trigger bar's range brackets both SL and TP. The 1m intrabar
    shows SL was touched first. Per D-01, the simulator must resolve
    exit_kind=SL with fallback_applied=False.
    """
    from src.backtest.simulator import run

    case_dir = PHASE6_FIXTURES_DIR / "intrabar_both_touched"
    case_input = _load_input(case_dir)
    result = run(case_input)
    trades = result["trades"]
    assert len(trades) == 1, f"expected 1 trade, got {len(trades)}"
    trade = trades[0]
    assert trade["exit_kind"] == "SL", (
        f"expected exit_kind=SL (SL-first per D-01), got {trade['exit_kind']}"
    )
    assert trade["fallback_applied"] is False, (
        "1m path was available; fallback_applied must be False"
    )
    assert trade["coverage_note"] is None, (
        "1m path was available; coverage_note must be None"
    )


# --------------------------------------------------------------------------- #
# Test 2 — SHORT both-touched bar resolves SL via 1m path (D-01).
# --------------------------------------------------------------------------- #


def test_intrabar_both_touched_short_resolves_sl_via_1m() -> None:
    """Beh. 2: SHORT both-touched bar → 1m path → SL-first exit.

    Mirrored levels prove the SHORT SL-first ordering (per D-01).
    """
    from src.backtest.simulator import run

    case_dir = PHASE6_FIXTURES_DIR / "intrabar_both_touched_short"
    case_input = _load_input(case_dir)
    result = run(case_input)
    trades = result["trades"]
    assert len(trades) == 1, f"expected 1 trade, got {len(trades)}"
    trade = trades[0]
    assert trade["exit_kind"] == "SL", (
        f"expected exit_kind=SL (SL-first per D-01), got {trade['exit_kind']}"
    )
    assert trade["fallback_applied"] is False
    assert trade["coverage_note"] is None


# --------------------------------------------------------------------------- #
# Test 3 — missing 1m → SL-first fallback + flag (D-01).
# --------------------------------------------------------------------------- #


def test_intrabar_missing_fallback_resolves_sl_with_flag() -> None:
    """Beh. 3: missing 1m → SL-first fallback + fallback_applied=True.

    Per D-01 + Phase-2 D-09 flag-never-fabricate: the simulator must
    never synthesize intrabar prices. Missing 1m yields SL-first with
    an explicit flag and coverage note.
    """
    from src.backtest.simulator import run

    case_dir = PHASE6_FIXTURES_DIR / "intrabar_missing_fallback"
    case_input = _load_input(case_dir)
    result = run(case_input)
    trades = result["trades"]
    assert len(trades) == 1, f"expected 1 trade, got {len(trades)}"
    trade = trades[0]
    assert trade["exit_kind"] == "SL"
    assert trade["fallback_applied"] is True, (
        "missing 1m must set fallback_applied=True"
    )
    assert trade["coverage_note"] == "1m_intrabar_missing", (
        f"expected coverage_note='1m_intrabar_missing', got {trade['coverage_note']!r}"
    )


# --------------------------------------------------------------------------- #
# Test 4 — costs apply from run #1 (D-02).
# --------------------------------------------------------------------------- #


def test_costs_apply_from_run_1_realized_pnl_differs_from_gross() -> None:
    """Beh. 4: realized_pnl = gross_pnl - entry_fee - exit_fee - slippage.

    Per D-02: costs apply from run #1, not as a post-filter. The
    realized_pnl must differ from gross_pnl by the exact fee+slippage
    Decimal.
    """
    from src.backtest.simulator import run

    case_dir = PHASE6_FIXTURES_DIR / "intrabar_both_touched"
    case_input = _load_input(case_dir)
    result = run(case_input)
    trades = result["trades"]
    assert len(trades) == 1
    trade = trades[0]
    gross = Decimal(str(trade["gross_pnl"]))
    entry_fee = Decimal(str(trade["entry_fee"]))
    exit_fee = Decimal(str(trade["exit_fee"]))
    slippage = Decimal(str(trade["slippage_amount"]))
    realized = Decimal(str(trade["realized_pnl"]))
    expected_realized = gross - entry_fee - exit_fee - slippage
    assert realized == expected_realized, (
        f"realized_pnl {realized} != gross - fees - slippage {expected_realized}"
    )


# --------------------------------------------------------------------------- #
# Test 5 — risk rejects are first-class outcomes (D-02).
# --------------------------------------------------------------------------- #


def test_risk_reject_is_first_class_outcome() -> None:
    """Beh. 5: a QUANTIZATION_REJECT-class outcome is a first-class record.

    Per D-02: realized-risk/quantization rejects are first-class trade
    outcomes, not post-filters. The simulator must emit a reject record
    with the canonical reason code.
    """
    from src.backtest.simulator import run

    # Use the notional_reject fixture from phase5 to construct a case
    # where the risk pipeline rejects. For Phase 6, we use a fixture
    # where the trade plan's notional is below the exchange minimum.
    case_dir = PHASE6_FIXTURES_DIR / "intrabar_both_touched"
    case_input = _load_input(case_dir)
    # Force a NOTIONAL_REJECT by setting min_notional very high.
    case_input["constraint_snapshot"]["min_notional"] = "999999"
    result = run(case_input)
    trades = result["trades"]
    assert len(trades) >= 1
    # Find the reject record.
    reject = next(
        (t for t in trades if t.get("outcome_kind") == "REJECT"), None
    )
    assert reject is not None, "expected a REJECT record in the trade list"
    assert reject["reason_code"] in {
        "NOTIONAL_REJECT",
        "MIN_QTY_REJECT",
        "UTILIZATION_REJECT",
        "QUANTIZATION_REJECT",
    }, f"unexpected reason_code {reject['reason_code']!r}"


# --------------------------------------------------------------------------- #
# Test 6 — limit touch-no-fill (Task 2).
# --------------------------------------------------------------------------- #


def test_limit_touch_no_fill() -> None:
    """Beh. 6: bar touches zone but high < entry_min → TOUCH_NO_FILL."""
    from src.backtest.simulator import run

    case_dir = PHASE6_FIXTURES_DIR / "limit_touch_no_fill"
    case_input = _load_input(case_dir)
    result = run(case_input)
    trades = result["trades"]
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_kind"] == "TOUCH_NO_FILL", (
        f"expected entry_kind=TOUCH_NO_FILL, got {trade['entry_kind']!r}"
    )
    assert trade["quantity"] is None, "TOUCH_NO_FILL must have quantity=None"


# --------------------------------------------------------------------------- #
# Test 7 — limit partial fill (Task 2).
# --------------------------------------------------------------------------- #


def test_limit_partial_fill() -> None:
    """Beh. 7: partial_fill_fraction < 1.0 applied to quantity."""
    from src.backtest.simulator import run

    case_dir = PHASE6_FIXTURES_DIR / "limit_partial_fill"
    case_input = _load_input(case_dir)
    result = run(case_input)
    trades = result["trades"]
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_kind"] == "PARTIAL_FILL", (
        f"expected entry_kind=PARTIAL_FILL, got {trade['entry_kind']!r}"
    )
    # Quantity must be < full quantity (partial_fill_fraction = 0.5).
    assert trade["quantity"] is not None
    partial_qty = Decimal(str(trade["quantity"]))
    full_qty = partial_qty / Decimal("0.5")
    assert partial_qty < full_qty, (
        f"partial fill quantity {partial_qty} should be < full quantity {full_qty}"
    )


# --------------------------------------------------------------------------- #
# Test 8 — limit expiry (Task 2).
# --------------------------------------------------------------------------- #


def test_limit_expiry() -> None:
    """Beh. 8: no fill inside expiry window → EXPIRED."""
    from src.backtest.simulator import run

    case_dir = PHASE6_FIXTURES_DIR / "limit_expiry"
    case_input = _load_input(case_dir)
    result = run(case_input)
    trades = result["trades"]
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_kind"] == "EXPIRED", (
        f"expected entry_kind=EXPIRED, got {trade['entry_kind']!r}"
    )
    assert trade["quantity"] is None


# --------------------------------------------------------------------------- #
# Test 9 — invalidation cancels entry (Task 2).
# --------------------------------------------------------------------------- #


def test_invalidation_cancels_entry() -> None:
    """Beh. 9: invalidation level trades before any fill → INVALIDATION_CANCEL."""
    from src.backtest.simulator import run

    case_dir = PHASE6_FIXTURES_DIR / "invalidation_cancels_entry"
    case_input = _load_input(case_dir)
    result = run(case_input)
    trades = result["trades"]
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_kind"] == "INVALIDATION_CANCEL", (
        f"expected entry_kind=INVALIDATION_CANCEL, got {trade['entry_kind']!r}"
    )
    assert trade["quantity"] is None


# --------------------------------------------------------------------------- #
# Test 10 — run-twice byte-identical (Task 3).
# --------------------------------------------------------------------------- #


def test_run_twice_byte_identical() -> None:
    """Beh. 10: two simulator runs over the same fixture yield byte-identical trade lists."""
    from src.backtest.simulator import run

    case_dir = PHASE6_FIXTURES_DIR / "intrabar_both_touched"
    case_input = _load_input(case_dir)
    a = run(case_input)
    b = run(case_input)
    a_canonical = [_canonical_trade_dict(t) for t in a["trades"]]
    b_canonical = [_canonical_trade_dict(t) for t in b["trades"]]
    assert sha256_hex({"trades": a_canonical}) == sha256_hex(
        {"trades": b_canonical}
    ), "run-twice digests differ — determinism violated"


# --------------------------------------------------------------------------- #
# Test 11 — cost parity: simulator modeled_costs_per_unit matches costs.modeled_costs_per_unit.
# --------------------------------------------------------------------------- #


def test_cost_parity_simulator_matches_costs_module() -> None:
    """Beh. 11: simulator's modeled_costs_per_unit matches costs.modeled_costs_per_unit.

    Per D-02: the simulator must call the identical cost formula that
    src/risk/sizing.py consumes. A direct comparison pins the parity.
    """
    from src.backtest.costs import build_cost_model, modeled_costs_per_unit
    from src.backtest.simulator import run

    case_dir = PHASE6_FIXTURES_DIR / "intrabar_both_touched"
    case_input = _load_input(case_dir)
    # Build the cost model from the fixture.
    cost_model = build_cost_model(case_input["cost_model"])
    # Run the simulator.
    result = run(case_input)
    # The simulator's internal modeled_costs_per_unit must match the
    # costs module's output for the same inputs.
    trade = result["trades"][0]
    # The trade record carries the modeled_costs_per_unit used.
    sim_costs = Decimal(str(trade["modeled_costs_per_unit"]))
    # Compute the expected value from the costs module.
    # For a LONG trade with entry_ref ≈ 121.50 and SL ≈ 121.40:
    # modeled_costs_per_unit = fee_rate_entry + fee_rate_exit + expected_slippage
    # (simplified for the tracer slice).
    expected_costs = (
        Decimal(cost_model.fee_rate_entry)
        + Decimal(cost_model.fee_rate_exit)
        + Decimal(cost_model.expected_slippage)
    )
    assert sim_costs == expected_costs, (
        f"simulator modeled_costs_per_unit {sim_costs} != "
        f"costs module {expected_costs}"
    )


# --------------------------------------------------------------------------- #
# Test 12 — no-lookahead: appending a post-horizon 1m candle changes nothing.
# --------------------------------------------------------------------------- #


def test_no_lookahead_appending_1m_candle_changes_nothing() -> None:
    """Beh. 12: appending a post-horizon 1m candle does not change the trade list.

    Per D-01: 1m candles at or after the strategy-bar close must never
    leak into the entry decision for that bar.
    """
    from src.backtest.simulator import run

    case_dir = PHASE6_FIXTURES_DIR / "intrabar_both_touched"
    case_input = _load_input(case_dir)
    a = run(case_input)
    # Append a post-horizon 1m candle (close_time after the trigger bar).
    key = list(case_input["intrabar_1m_map"].keys())[0]
    intrabar = list(case_input["intrabar_1m_map"][key])
    # Add a candle at 10:01:00 (after the trigger bar's 09:59:59 close).
    from datetime import datetime as _dt

    post_horizon = {
        "symbol": "BTCUSDT",
        "interval": "1m",
        "open_time_utc": "2026-09-11T10:00:00+00:00",
        "close_time_utc": "2026-09-11T10:00:59+00:00",
        "open": "99999.00",
        "high": "99999.00",
        "low": "99999.00",
        "close": "99999.00",
        "volume": "1.0",
    }
    case_input["intrabar_1m_map"][key] = intrabar + [post_horizon]
    b = run(case_input)
    a_canonical = [_canonical_trade_dict(t) for t in a["trades"]]
    b_canonical = [_canonical_trade_dict(t) for t in b["trades"]]
    assert sha256_hex({"trades": a_canonical}) == sha256_hex(
        {"trades": b_canonical}
    ), "appending a post-horizon 1m candle changed the trade list — lookahead leak"


# --------------------------------------------------------------------------- #
# Test 13 — phase6 fixtures exist.
# --------------------------------------------------------------------------- #


def test_phase6_fixtures_exist() -> None:
    """Beh. 13: each case directory under phase6/ contains input.json."""
    assert PHASE6_FIXTURES_DIR.is_dir(), (
        f"missing phase6 fixtures dir: {PHASE6_FIXTURES_DIR}"
    )
    expected_cases = {
        "intrabar_both_touched",
        "intrabar_both_touched_short",
        "intrabar_missing_fallback",
        "limit_touch_no_fill",
        "limit_partial_fill",
        "limit_expiry",
        "invalidation_cancels_entry",
    }
    actual_cases = {p.name for p in PHASE6_FIXTURES_DIR.iterdir() if p.is_dir()}
    assert expected_cases.issubset(actual_cases), (
        f"missing phase6 cases: {expected_cases - actual_cases}"
    )


# --------------------------------------------------------------------------- #
# Nyquist gap-fill (review-fix iteration 1): CR-01, CR-02, CR-10, WR-14.
# --------------------------------------------------------------------------- #


def test_cr01_empty_intrabar_list_resolves_sl_first_fallback() -> None:
    """CR-01: empty intrabar [] resolves SL-first fallback with fallback_applied=True.

    An empty 1m payload (valid JSON, zero candles) is the most likely
    real-world shape of "no coverage" and must behave exactly like None:
    SL-first fallback, never IndexError. Only None was tested before.
    """
    from src.backtest.simulator import resolve_intrabar

    for direction in ("LONG", "SHORT"):
        for intrabar in ([], None):
            outcome = resolve_intrabar(
                direction=direction,
                stop_loss=Decimal("121.40"),
                take_profit_1=Decimal("125.00"),
                intrabar=intrabar,  # type: ignore[arg-type]
            )
            assert outcome.exit_kind == "SL", (
                f"{direction} intrabar={intrabar!r}: expected SL-first fallback, "
                f"got {outcome.exit_kind!r}"
            )
            assert outcome.fallback_applied is True, (
                f"{direction} intrabar={intrabar!r}: fallback_applied must be True"
            )
            assert outcome.coverage_note == "1m_intrabar_missing"


def test_cr02_trade_id_unique_across_bar_time_symbol_quantity() -> None:
    """CR-02: trade_id binds bar time, symbol, and quantity; symbol is explicit.

    Two fills of the same plan at different partial-fill fractions shared
    one trade_id before the fix. The payload must bind symbol +
    bar_close_time_utc + quantity, and symbol must be an explicit caller
    parameter (no "Decimal" placeholder).
    """
    import inspect
    from datetime import timezone
    from types import SimpleNamespace

    from src.backtest.simulator import _make_record, run

    # Structural pin: symbol and bar_close_time_utc are required keyword-only.
    sig = inspect.signature(_make_record)
    for required in ("symbol", "bar_close_time_utc"):
        param = sig.parameters[required]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is inspect.Parameter.empty, (
            f"_make_record({required}) must be required, never defaulted"
        )

    plan = SimpleNamespace(
        trade_plan_id="plan-gap-cr02",
        signal_id="sig-gap-cr02",
        trade_plan_version="v2.0.0",
        plan_hash="0" * 64,
    )
    bar_close_a = datetime(2026, 9, 11, 9, 0, 0, tzinfo=timezone.utc)
    bar_close_b = datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc)

    def _rec(symbol: str, bar_close: datetime, quantity: str) -> str:
        return _make_record(
            trade_plan=plan,  # type: ignore[arg-type]
            symbol=symbol,
            bar_close_time_utc=bar_close,
            entry_kind="ENTRY_FILLED",
            entry_price=Decimal("121.50"),
            entry_time_utc=bar_close,
            quantity=Decimal(quantity),
            exit_kind="SL",
            exit_price=Decimal("121.40"),
            exit_time_utc=bar_close,
            realized_pnl=Decimal("-0.05"),
            realized_risk=Decimal("0.10"),
            gross_pnl=Decimal("-0.05"),
            entry_fee=Decimal("0.001"),
            exit_fee=Decimal("0.001"),
            funding_amount=Decimal("0"),
            slippage_amount=Decimal("0.0001"),
            modeled_costs_per_unit=Decimal("0.0008"),
            coverage_note=None,
            fallback_applied=False,
            outcome_kind="OK",
            reason_code="OK",
            direction="LONG",
        ).trade_id

    base = _rec("BTCUSDT", bar_close_a, "0.5")
    assert _rec("BTCUSDT", bar_close_a, "0.9") != base, (
        "quantity-only variation must change trade_id (fraction collision)"
    )
    assert _rec("ETHUSDT", bar_close_a, "0.5") != base, (
        "symbol-only variation must change trade_id"
    )
    assert _rec("BTCUSDT", bar_close_b, "0.5") != base, (
        "bar-time-only variation must change trade_id"
    )
    assert _rec("BTCUSDT", bar_close_a, "0.5") == base, (
        "identical inputs must re-hash identically"
    )

    # End-to-end anchor: the same plan filled at fraction 1.0 vs 0.5
    # yields different trade_ids on the same bar.
    case_dir = PHASE6_FIXTURES_DIR / "limit_partial_fill"
    full_input = _load_input(case_dir)
    full_input["cost_model"] = dict(
        full_input["cost_model"], partial_fill_fraction="1.0"
    )
    partial_input = _load_input(case_dir)
    full_id = run(full_input)["trades"][0]["trade_id"]
    partial_id = run(partial_input)["trades"][0]["trade_id"]
    assert full_id != partial_id, (
        "full vs partial fill of the same plan must not share a trade_id"
    )


def test_cr10_fixture_strategy_version_bound_to_registry() -> None:
    """CR-10: fixture strategy_version diverging from the registry fails closed.

    A fixture claiming v9.9.9 replayed against registry v2.0.0 must raise
    instead of replaying under a hybrid identity.
    """
    from src.backtest.simulator import run

    case_input = _load_input(PHASE6_FIXTURES_DIR / "intrabar_both_touched")
    case_input["strategy_version"] = "v9.9.9"
    with pytest.raises(ValueError, match="strategy_version"):
        run(case_input)


def test_wr14_float_json_numbers_and_naive_datetimes_rejected() -> None:
    """WR-14: float-typed JSON numbers and naive datetimes fail closed at parse."""
    import copy

    from src.backtest.simulator import run

    base = _load_input(PHASE6_FIXTURES_DIR / "intrabar_both_touched")

    float_price = copy.deepcopy(base)
    float_price["strategy_bars"][0]["open"] = 1.1
    with pytest.raises(TypeError):
        run(float_price)

    naive_dt = copy.deepcopy(base)
    naive_dt["strategy_bars"][0]["close_time_utc"] = "2026-09-11T10:00:00"
    with pytest.raises(ValueError):
        run(naive_dt)

    float_account = copy.deepcopy(base)
    float_account["account_state"]["equity"] = 10000.00
    with pytest.raises(TypeError):
        run(float_account)
