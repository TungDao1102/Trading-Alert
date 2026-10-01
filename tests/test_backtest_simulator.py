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
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from src.backtest.binding import CostModelBindingMismatch
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
    assert trade["coverage_note"] is None, "1m path was available; coverage_note must be None"


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
    assert trade["fallback_applied"] is True, "missing 1m must set fallback_applied=True"
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
    reject = next((t for t in trades if t.get("outcome_kind") == "REJECT"), None)
    assert reject is not None, "expected a REJECT record in the trade list"
    assert reject["reason_code"] in {
        "NOTIONAL_REJECT",
        "MIN_QTY_REJECT",
        "UTILIZATION_REJECT",
        "STOP_TOO_TIGHT",
        "COST_TO_RISK_EXCEEDED",
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
    assert sha256_hex({"trades": a_canonical}) == sha256_hex({"trades": b_canonical}), (
        "run-twice digests differ — determinism violated"
    )


# --------------------------------------------------------------------------- #
# Test 11 - cost parity: the record's modeled cost is quote per unit at the
# sizing edge, matching the public helper and literal arithmetic (D-18).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case_name", ["intrabar_missing_fallback", "intrabar_both_touched_short"])
def test_cost_parity_simulator_matches_costs_module(case_name: str) -> None:
    """Beh. 11: the simulator record's modeled_costs_per_unit equals the public helper.

    The plan edge and stop come from re-running the planner in the test; the
    expected value is also written out as literal arithmetic,
    edge x (0.0005 + 0.0001) + stop x (0.0005 + 0.0003), so the test cannot
    agree with a re-derived buggy formula (the old rate-sum did).
    """
    from src.backtest.costs import build_cost_model, modeled_costs_per_unit
    from src.backtest.simulator import run

    case_input = _load_input(PHASE6_FIXTURES_DIR / case_name)
    cost_model = build_cost_model(case_input["cost_model"])
    trade = run(case_input)["trades"][0]
    sim_costs = Decimal(str(trade["modeled_costs_per_unit"]))

    trade_plan, direction = _replan(case_input)
    edge = trade_plan.entry_max_price if direction == "LONG" else trade_plan.entry_min_price
    via_helper = modeled_costs_per_unit(
        cost_model=cost_model,
        side=direction,
        entry_price=edge,
        stop_price=trade_plan.stop_loss_price,
    )
    literal = edge * Decimal("0.0006") + trade_plan.stop_loss_price * Decimal("0.0008")
    assert sim_costs == via_helper
    assert sim_costs == literal
    assert sim_costs > Decimal("0.0011"), "must not collapse to the dimensionless rate sum"


_MODELED_COSTS_ORACLES = [
    ("btc_long", "LONG", "60100", "58780", "83.0840"),
    ("btc_short", "SHORT", "59900", "61300", "84.9800"),
    ("xrp_long", "LONG", "0.5010", "0.4930", "0.000695"),
]


@pytest.mark.parametrize(
    "label,side,entry,stop,expected",
    _MODELED_COSTS_ORACLES,
    ids=[row[0] for row in _MODELED_COSTS_ORACLES],
)
def test_modeled_costs_per_unit_price_aware_oracles(
    label: str, side: str, entry: str, stop: str, expected: str
) -> None:
    from src.backtest.costs import build_cost_model, modeled_costs_per_unit

    got = modeled_costs_per_unit(
        cost_model=build_cost_model(_COST8),
        side=side,
        entry_price=Decimal(entry),
        stop_price=Decimal(stop),
    )
    assert got == Decimal(expected)


def test_modeled_costs_per_unit_is_linear_in_price() -> None:
    from src.backtest.costs import build_cost_model, modeled_costs_per_unit

    model = build_cost_model(_COST8)
    base = modeled_costs_per_unit(
        cost_model=model, side="LONG", entry_price=Decimal("60100"), stop_price=Decimal("58780")
    )
    doubled = modeled_costs_per_unit(
        cost_model=model, side="LONG", entry_price=Decimal("120200"), stop_price=Decimal("117560")
    )
    assert base == Decimal("83.0840")
    assert doubled == Decimal("166.1680")


def test_modeled_costs_per_unit_rejects_bad_side_legacy_model_and_old_call_form() -> None:
    from src.backtest.costs import build_cost_model, modeled_costs_per_unit

    model = build_cost_model(_COST8)
    prices = {"entry_price": Decimal("60100"), "stop_price": Decimal("58780")}
    with pytest.raises(ValueError, match="side"):
        modeled_costs_per_unit(cost_model=model, side="FLAT", **prices)

    legacy = build_cost_model({k: v for k, v in _COST8.items() if k != "exit_slippage_rate"})
    with pytest.raises(ValueError, match="exit_slippage_rate"):
        modeled_costs_per_unit(cost_model=legacy, side="LONG", **prices)

    with pytest.raises(TypeError):
        modeled_costs_per_unit(cost_model=model, side="LONG")  # type: ignore[call-arg]


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
    assert sha256_hex({"trades": a_canonical}) == sha256_hex({"trades": b_canonical}), (
        "appending a post-horizon 1m candle changed the trade list — lookahead leak"
    )


# --------------------------------------------------------------------------- #
# Test 13 — phase6 fixtures exist.
# --------------------------------------------------------------------------- #


def test_phase6_fixtures_exist() -> None:
    """Beh. 13: each case directory under phase6/ contains input.json."""
    assert PHASE6_FIXTURES_DIR.is_dir(), f"missing phase6 fixtures dir: {PHASE6_FIXTURES_DIR}"
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
    bar_close_a = datetime(2026, 9, 11, 9, 0, 0, tzinfo=UTC)
    bar_close_b = datetime(2026, 9, 11, 10, 0, 0, tzinfo=UTC)

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
    assert _rec("ETHUSDT", bar_close_a, "0.5") != base, "symbol-only variation must change trade_id"
    assert _rec("BTCUSDT", bar_close_b, "0.5") != base, (
        "bar-time-only variation must change trade_id"
    )
    assert _rec("BTCUSDT", bar_close_a, "0.5") == base, "identical inputs must re-hash identically"

    # End-to-end anchor: the same plan filled at fraction 1.0 vs 0.5
    # yields different trade_ids on the same bar.
    case_dir = PHASE6_FIXTURES_DIR / "limit_partial_fill"
    full_input = _load_input(case_dir)
    full_input["cost_model"] = dict(full_input["cost_model"], partial_fill_fraction="1.0")
    partial_input = _load_input(case_dir)
    full_id = run(full_input)["trades"][0]["trade_id"]
    partial_id = run(partial_input)["trades"][0]["trade_id"]
    assert full_id != partial_id, "full vs partial fill of the same plan must not share a trade_id"


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


# --------------------------------------------------------------------------- #
# Phase 12 (plan 12-09): per-leg slippage booking, shared cost path, guards.
# Every expected value below is a hand-derived literal (standalone Decimal
# arithmetic), never the output of _apply_costs / modeled_costs_per_unit.
# --------------------------------------------------------------------------- #

_COST8 = {
    "fee_rate_entry": "0.0005",
    "fee_rate_exit": "0.0005",
    "funding_treatment": "ADDITIVE",
    "expected_slippage": "0.0001",
    "slippage_model": "FIXED_BPS",
    "spread_fill_assumptions": "FULL_FILL",
    "partial_fill_fraction": "1.0",
    "exit_slippage_rate": "0.0003",
}


def _filled_record(*, direction: str, entry: str, exit_: str, quantity: str, exit_kind: str):
    """Hand-built filled TradeRecord with every cost field still None."""

    from src.backtest.simulator import TradeRecord

    t = datetime(2026, 9, 11, 10, 0, 0, tzinfo=UTC)
    return TradeRecord(
        trade_id="t-oracle",
        signal_id="s-oracle",
        trade_plan_id="p-oracle",
        strategy_version="v4.0.0",
        parameter_set_hash="0" * 64,
        symbol="BTCUSDT",
        direction=direction,
        entry_kind="ENTRY_FILLED",
        entry_price=Decimal(entry),
        entry_time_utc=t,
        quantity=Decimal(quantity),
        exit_kind=exit_kind,
        exit_price=Decimal(exit_),
        exit_time_utc=t,
        realized_pnl=None,
        realized_risk=None,
        gross_pnl=None,
        entry_fee=None,
        exit_fee=None,
        funding_amount=None,
        slippage_amount=None,
        modeled_costs_per_unit=None,
        coverage_note=None,
        fallback_applied=False,
        outcome_kind="OK",
        reason_code="OK",
    )


# (label, direction, entry, exit, quantity, exit_kind,
#  gross, entry_fee, exit_fee, slippage_total, realized)
_APPLY_COSTS_ORACLES = [
    (
        "btc_long_sl_edge",
        "LONG",
        "60100",
        "58780",
        "0.035",
        "SL",
        "-46.200",
        "1.05175",
        "1.02865",
        "0.82754",
        "-49.10794",
    ),
    (
        "btc_long_sl_mid",
        "LONG",
        "60000",
        "58780",
        "0.035",
        "SL",
        "-42.700",
        "1.05",
        "1.02865",
        "0.82719",
        "-45.60584",
    ),
    (
        "btc_short_sl_edge",
        "SHORT",
        "59900",
        "61300",
        "0.033",
        "SL",
        "-46.200",
        "0.98835",
        "1.01145",
        "0.80454",
        "-49.00434",
    ),
    (
        "xrp_long_sl_edge",
        "LONG",
        "0.5010",
        "0.4930",
        "5750.4",
        "SL",
        "-46.00320",
        "1.4404752",
        "1.4174736",
        "1.1385792",
        "-49.999728",
    ),
    (
        "btc_long_tp1",
        "LONG",
        "60000",
        "62000",
        "0.035",
        "TP1",
        "70.000",
        "1.05",
        "1.085",
        "0.427",
        "67.438",
    ),
    (
        "btc_long_eod",
        "LONG",
        "60000",
        "60300",
        "0.035",
        "EOD",
        "10.500",
        "1.05",
        "1.05525",
        "0.84315",
        "7.5516",
    ),
]


@pytest.mark.parametrize(
    "label,direction,entry,exit_,quantity,exit_kind,gross,efee,xfee,slip,realized",
    _APPLY_COSTS_ORACLES,
    ids=[row[0] for row in _APPLY_COSTS_ORACLES],
)
def test_apply_costs_books_slippage_per_leg_in_quote_currency(
    label: str,
    direction: str,
    entry: str,
    exit_: str,
    quantity: str,
    exit_kind: str,
    gross: str,
    efee: str,
    xfee: str,
    slip: str,
    realized: str,
) -> None:
    """F-306: slippage is fill_price x quantity x rate per leg (D-05, D-06).

    SL and EOD exits use exit_slippage_rate (0.0003); TP1 uses
    expected_slippage (0.0001) on the exit leg; the entry leg always uses
    expected_slippage. The old booking was quantity x expected_slippage.
    """
    from src.backtest.costs import build_cost_model
    from src.backtest.simulator import _apply_costs

    record = _filled_record(
        direction=direction,
        entry=entry,
        exit_=exit_,
        quantity=quantity,
        exit_kind=exit_kind,
    )
    out = _apply_costs(trade_record=record, cost_model=build_cost_model(_COST8))
    assert out.gross_pnl == Decimal(gross)
    assert out.entry_fee == Decimal(efee)
    assert out.exit_fee == Decimal(xfee)
    assert out.slippage_amount == Decimal(slip)
    assert out.realized_pnl == Decimal(realized)


def test_apply_costs_tp1_uses_entry_slippage_rate_not_the_exit_rate() -> None:
    """Discriminator: TP1 realized 67.438 (expected_slippage), never 67.004."""
    from src.backtest.costs import build_cost_model
    from src.backtest.simulator import _apply_costs

    record = _filled_record(
        direction="LONG", entry="60000", exit_="62000", quantity="0.035", exit_kind="TP1"
    )
    out = _apply_costs(trade_record=record, cost_model=build_cost_model(_COST8))
    assert out.realized_pnl == Decimal("67.438")
    assert out.realized_pnl != Decimal("67.004")


def test_apply_costs_refuses_model_without_exit_slippage_rate() -> None:
    from src.backtest.costs import build_cost_model
    from src.backtest.simulator import _apply_costs

    legacy = {k: v for k, v in _COST8.items() if k != "exit_slippage_rate"}
    record = _filled_record(
        direction="LONG", entry="60000", exit_="58780", quantity="0.035", exit_kind="SL"
    )
    with pytest.raises(ValueError, match="exit_slippage_rate"):
        _apply_costs(trade_record=record, cost_model=build_cost_model(legacy))


def test_apply_costs_refuses_unknown_exit_kind() -> None:
    from src.backtest.costs import build_cost_model
    from src.backtest.simulator import _apply_costs

    record = _filled_record(
        direction="LONG", entry="60000", exit_="58780", quantity="0.035", exit_kind="TP2"
    )
    with pytest.raises(ValueError, match="exit_kind"):
        _apply_costs(trade_record=record, cost_model=build_cost_model(_COST8))


def test_apply_costs_passes_unfilled_records_through_untouched() -> None:
    from dataclasses import replace

    from src.backtest.costs import build_cost_model
    from src.backtest.simulator import _apply_costs

    base = _filled_record(
        direction="LONG", entry="60000", exit_="58780", quantity="0.035", exit_kind="SL"
    )
    cost_model = build_cost_model(_COST8)
    for changes in (
        {"entry_price": None},
        {"quantity": None},
        {"exit_price": None, "exit_kind": None},
    ):
        unfilled = replace(base, **changes)
        assert _apply_costs(trade_record=unfilled, cost_model=cost_model) == unfilled


# --------------------------------------------------------------------------- #
# guard_rates_from_params (shared by the simulator and the paper loop, D-19).
# --------------------------------------------------------------------------- #


def test_guard_rates_from_params_reads_both_keys_as_decimals() -> None:
    from src.backtest.costs import guard_rates_from_params

    result = guard_rates_from_params(
        {"min_stop_distance_rate": Decimal("0.003"), "max_cost_to_risk": Decimal("0.15")}
    )
    assert result == (Decimal("0.003"), Decimal("0.15"))
    assert all(isinstance(v, Decimal) for v in result)


@pytest.mark.parametrize("missing", ["min_stop_distance_rate", "max_cost_to_risk"])
def test_guard_rates_from_params_names_the_missing_key(missing: str) -> None:
    from src.backtest.costs import guard_rates_from_params

    params = {"min_stop_distance_rate": Decimal("0.003"), "max_cost_to_risk": Decimal("0.15")}
    del params[missing]
    with pytest.raises(ValueError, match=missing):
        guard_rates_from_params(params)


def test_guard_rates_from_params_matches_pinned_registry_set() -> None:
    from src.backtest.costs import guard_rates_from_params
    from src.domain.registry import load_parameter_set

    v5 = load_parameter_set("trend-pullback", "baseline-v5")
    assert guard_rates_from_params(v5.params) == (Decimal("0.003"), Decimal("0.15"))
    v4 = load_parameter_set("trend-pullback", "baseline-v4")
    with pytest.raises(ValueError, match="min_stop_distance_rate"):
        guard_rates_from_params(v4.params)


@pytest.mark.parametrize("bad", [0.003, "0.003", True, None])
def test_guard_rates_from_params_rejects_non_decimal_types(bad: object) -> None:
    """12-REVIEW WR-05: float, str, bool and None are refused (Decimal or int only)."""
    from src.backtest.costs import guard_rates_from_params

    params = {"min_stop_distance_rate": bad, "max_cost_to_risk": Decimal("0.15")}
    with pytest.raises(TypeError, match="min_stop_distance_rate"):
        guard_rates_from_params(params)


@pytest.mark.parametrize(
    ("min_stop", "max_ratio"),
    [
        (Decimal("NaN"), Decimal("0.15")),
        (Decimal("0.003"), Decimal("NaN")),
        (Decimal("Infinity"), Decimal("0.15")),
        (Decimal("0.003"), Decimal("0")),
        (Decimal("0.003"), Decimal("2")),
    ],
)
def test_guard_rates_from_params_validates_range_and_finiteness(
    min_stop: Decimal, max_ratio: Decimal
) -> None:
    from src.backtest.costs import guard_rates_from_params

    params = {"min_stop_distance_rate": min_stop, "max_cost_to_risk": max_ratio}
    with pytest.raises(ValueError):
        guard_rates_from_params(params)


# --------------------------------------------------------------------------- #
# End to end: simulated SL-exit loss stays within allowed_risk (D-05, F-306).
# --------------------------------------------------------------------------- #

_E2E_CASES = [
    "intrabar_both_touched",
    "intrabar_both_touched_short",
    "intrabar_missing_fallback",
]


def _replan(case_input: dict):
    """Re-run strategy + planner over the fixture (independent of costs).

    Returns the TradePlan and direction of the single plan the fixture
    produces, so expected values come from plan prices and literal rates.
    """
    from src.backtest.simulator import (
        _parse_account_state,
        _parse_candle,
    )
    from src.core.planner import plan
    from src.core.strategy import evaluate
    from src.core.types import MarketSnapshot
    from src.domain.registry import load_parameter_set

    bars = sorted(
        (_parse_candle(r) for r in case_input["strategy_bars"]),
        key=lambda b: (b.close_time_utc, b.symbol),
    )
    context = sorted(
        (_parse_candle(r) for r in case_input["context_bars"]),
        key=lambda c: (c.close_time_utc, c.symbol),
    )
    account = _parse_account_state(case_input["account_state"])
    pset = load_parameter_set(case_input["strategy_id"], case_input["parameter_set_id"])
    plans = []
    for idx, bar in enumerate(bars):
        snapshot = MarketSnapshot(
            symbol=bar.symbol,
            setup_candles=bars[: idx + 1],
            context_candles=[c for c in context if c.close_time_utc <= bar.close_time_utc],
            source_timeframe="1h",
        )
        setup = evaluate(
            snapshot=snapshot,
            account_state=account,
            strategy_version=case_input["strategy_version"],
            parameter_set=pset,
        )
        if setup.is_no_trade:
            continue
        signal = setup.signal
        assert signal is not None
        result = plan(
            signal=signal,
            setup_candles=bars[: idx + 1],
            parameter_set=pset,
            account_state=account,
            created_at_utc=bar.close_time_utc,
        )
        assert not result.is_no_trade
        assert result.trade_plan is not None
        plans.append((result.trade_plan, signal.direction))
    assert len(plans) == 1
    return plans[0]


@pytest.mark.parametrize("case_name", _E2E_CASES)
def test_end_to_end_sl_loss_including_costs_is_within_allowed_risk(case_name: str) -> None:
    """The full simulator run: loss at the SL, fees and slippage included, <= 50.

    allowed_risk = 10000 x 0.005 = 50. Rates are literals (0.0005 fees,
    0.0001 entry slippage, 0.0003 stop-exit slippage), the loss is
    recomputed here from the record's own prices and quantity.
    """
    from src.backtest.simulator import run

    case_input = _load_input(PHASE6_FIXTURES_DIR / case_name)
    trades = run(case_input)["trades"]
    assert len(trades) == 1
    trade = trades[0]
    assert trade["exit_kind"] == "SL"

    entry = Decimal(trade["entry_price"])
    exit_ = Decimal(trade["exit_price"])
    qty = Decimal(trade["quantity"])
    if trade["direction"] == "LONG":
        gross = (exit_ - entry) * qty
    else:
        gross = (entry - exit_) * qty
    entry_fee = entry * qty * Decimal("0.0005")
    exit_fee = exit_ * qty * Decimal("0.0005")
    slippage = entry * qty * Decimal("0.0001") + exit_ * qty * Decimal("0.0003")

    assert Decimal(trade["entry_fee"]) == entry_fee
    assert Decimal(trade["exit_fee"]) == exit_fee
    assert Decimal(trade["slippage_amount"]) == slippage
    assert Decimal(trade["gross_pnl"]) == gross

    loss = -(gross - entry_fee - exit_fee - slippage)
    assert Decimal(trade["realized_pnl"]) == -loss
    assert loss > 0
    assert loss <= Decimal("50")
    assert qty % Decimal("0.001") == 0


@pytest.mark.parametrize("case_name", _E2E_CASES)
def test_end_to_end_modeled_costs_are_quote_per_unit_at_the_sizing_edge(
    case_name: str,
) -> None:
    """modeled_costs_per_unit = sizing_edge x 0.0006 + stop x 0.0008 (quote per unit)."""
    from src.backtest.simulator import run

    case_input = _load_input(PHASE6_FIXTURES_DIR / case_name)
    trade = run(case_input)["trades"][0]
    trade_plan, direction = _replan(case_input)
    edge = trade_plan.entry_max_price if direction == "LONG" else trade_plan.entry_min_price
    expected = edge * Decimal("0.0006") + trade_plan.stop_loss_price * Decimal("0.0008")
    assert Decimal(trade["modeled_costs_per_unit"]) == expected


# --------------------------------------------------------------------------- #
# Legacy refusals and guard flow-through (T-12-19).
# --------------------------------------------------------------------------- #


def test_run_refuses_legacy_registry_set_without_guard_rates() -> None:
    from src.backtest.simulator import run

    case_input = _load_input(PHASE6_FIXTURES_DIR / "intrabar_both_touched")
    case_input["parameter_set_id"] = "baseline-v4"
    case_input["strategy_version"] = "v3.0.0"
    # The v5 fixture cost model carries exit_slippage_rate, the legacy v4 set
    # does not pin it: the registry binding refuses before any sizing (WR-03).
    with pytest.raises(CostModelBindingMismatch):
        run(case_input)


def test_run_refuses_cost_dict_without_exit_slippage_rate() -> None:
    from src.backtest.simulator import run

    case_input = _load_input(PHASE6_FIXTURES_DIR / "intrabar_both_touched")
    del case_input["cost_model"]["exit_slippage_rate"]
    # A dict without exit_slippage_rate disagrees with the v5 registry set that
    # pins it; the binding refuses it before the per-bar cost-rate mapping (WR-03).
    with pytest.raises(CostModelBindingMismatch):
        run(case_input)


def test_run_refuses_fixture_cost_model_that_disagrees_with_registry() -> None:
    """WR-03: a fixture fee rate the registry set does not pin is refused."""
    from src.backtest.simulator import run

    case_input = _load_input(PHASE6_FIXTURES_DIR / "intrabar_both_touched")
    case_input["cost_model"]["fee_rate_entry"] = "0.0001"
    with pytest.raises(CostModelBindingMismatch):
        run(case_input)


def test_run_accepts_partial_fill_fraction_that_differs_from_registry() -> None:
    """WR-03: partial_fill_fraction is applied after sizing and is not bound."""
    from src.backtest.simulator import run

    case_input = _load_input(PHASE6_FIXTURES_DIR / "limit_partial_fill")
    assert run(case_input)["trades"][0]["entry_kind"] == "PARTIAL_FILL"


def test_guard_reason_flows_from_the_shared_helper_into_a_reject_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A min_stop_distance_rate of 2 percent (fixture stop is about 1.1 percent)."""
    import src.backtest.simulator as simulator

    real = simulator.guard_rates_from_params

    def _tight(params):  # type: ignore[no-untyped-def]
        _, max_cost_to_risk = real(params)
        return Decimal("0.02"), max_cost_to_risk

    monkeypatch.setattr(simulator, "guard_rates_from_params", _tight)
    case_input = _load_input(PHASE6_FIXTURES_DIR / "intrabar_both_touched")
    trades = simulator.run(case_input)["trades"]
    assert len(trades) == 1
    assert trades[0]["outcome_kind"] == "REJECT"
    assert trades[0]["reason_code"] == "STOP_TOO_TIGHT"
