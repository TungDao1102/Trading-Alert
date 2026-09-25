"""Tests for the portfolio gates + DAILY_STOP + fail-closed input validation (Phase 5, plan 05-02).

Per D-03 + D-04 + RISK_MANAGEMENT §§4-5/8/12:
- `check_portfolio` evaluates cluster cap, aggregate cap, position count, and
  daily state in fixed order (first failure wins).
- Daily state machine NORMAL → WARNING → DAILY_STOP with thresholds from registry.
- Fail-closed on uncertain inputs: `daily_loss_quote=None`,
  `positions_reconciled=False`, stale constraint snapshot, missing stepSize
  metadata.

TDD discipline: RED → GREEN. This file is the RED phase — it MUST fail
until `src/risk/portfolio.py` is implemented.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.core.types import AccountState
from src.domain.canonical import sha256_hex
from src.domain.enums import DailyState, TradePlanStatus
from src.domain.trade_plan import TradePlan
from src.risk.portfolio import PortfolioVerdict, check_portfolio
from src.risk.quantization import quantize
from src.risk.sizing import size_position
from src.risk.types import (
    ConstraintSnapshot,
    OpenPosition,
    SizedResult,
)

PHASE5_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase5"

# V1 conservative cluster rule (D-03 + RESEARCH A3): directionally-aligned
# BTC/ETH/SOL/XRP positions count as one cluster. The candidate's symbol
# is supplied by the caller (the trade plan's symbol).
CLUSTER_SYMBOLS: frozenset[str] = frozenset(
    {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"}
)

# Registry parameters (research baselines per RISK_MANAGEMENT §§4-5/8).
# Values are ABSOLUTE quote amounts in USDT for an equity of 10000:
# - max_aggregate_open_risk = 0.01 × 10000 = 100 USDT (1.0% of equity)
# - cluster_cap = 0.005 × 10000 = 50 USDT (single-trade risk_rate)
# - daily_loss_warning_threshold = 0.005 × 10000 = 50 USDT (50% of stop)
# - daily_loss_stop_threshold = 0.01 × 10000 = 100 USDT (1.0% of equity)
# The caller (evaluate_risk or Phase-7+ caller) is responsible for
# converting registry rates to absolute amounts before calling.
PARAMETERS: dict[str, Any] = {
    "max_open_positions": 2,
    "max_aggregate_open_risk": Decimal("100"),
    "cluster_cap": Decimal("50"),
    "daily_loss_warning_threshold": Decimal("50"),
    "daily_loss_stop_threshold": Decimal("100"),
    "risk_rate": Decimal("0.005"),
    "minimum_risk_utilization_after_rounding": Decimal("0.6"),
}

TTL_SECONDS = 3600
FROZEN_NOW = datetime(2026, 9, 19, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Helpers — build TradePlan, AccountState, ConstraintSnapshot, OpenPosition,
# and a fully-sized SizedResult for portfolio-gate tests.
# --------------------------------------------------------------------------- #


def _mk_trade_plan(
    *,
    symbol: str = "BTCUSDT",
    entry_min: str = "49900.00",
    entry_max: str = "50100.00",
    stop_loss: str = "49000.00",
    risk_rate: str = "0.005",
    risk_budget: str = "50.00000",
    suggested_quantity: str = "0.04995004995004995004995004995",
) -> TradePlan:
    """Build a frozen TradePlan with DEFERRED_TO_RISK estimate fields."""
    return TradePlan(
        trade_plan_id="1" * 64,
        signal_id="2" * 64,
        trade_plan_version="v1",
        entry_model="LIMIT_ZONE",
        entry_min_price=Decimal(entry_min),
        entry_max_price=Decimal(entry_max),
        stop_loss_price=Decimal(stop_loss),
        take_profit_json='{"tp1":"52000.00","tp1_role":"TAKE_PROFIT_1"}',
        invalidation_rule_json='{"basis":"CANDLE_CLOSE","level":"49000.00","break_distance_atr":"20.00"}',
        expiry_utc=datetime(2026, 9, 19, 4, tzinfo=UTC),
        expected_rr_json='{"tp1_rr":"2.0"}',
        risk_rate=Decimal(risk_rate),
        risk_budget=Decimal(risk_budget),
        suggested_quantity=Decimal(suggested_quantity),
        quantity_before_rounding=Decimal(suggested_quantity),
        quantity_after_rounding=Decimal(suggested_quantity),
        quantization_decision="DEFERRED_TO_RISK",
        plan_hash="3" * 64,
        status=TradePlanStatus.READY,
        created_at_utc=datetime(2026, 9, 19, tzinfo=UTC),
    )


def _mk_account_state(equity: str = "10000.00", risk_rate: str = "0.005") -> AccountState:
    return AccountState(equity=Decimal(equity), risk_rate=Decimal(risk_rate))


def _mk_constraints(
    *,
    symbol: str = "BTCUSDT",
    step: str = "0.001",
    min_qty: str = "0.001",
    min_notional: str = "50",
    metadata_observed_at_utc: datetime | None = None,
) -> ConstraintSnapshot:
    return ConstraintSnapshot(
        symbol=symbol,
        price_tick_size=Decimal("0.10"),
        quantity_step_size=Decimal(step),
        min_quantity=Decimal(min_qty),
        min_notional=Decimal(min_notional),
        metadata_observed_at_utc=metadata_observed_at_utc or FROZEN_NOW,
    )


def _mk_open_position(
    symbol: str,
    position_side: str,
    open_risk: str,
    daily_pnl_contribution: str = "0",
) -> OpenPosition:
    return OpenPosition(
        symbol=symbol,
        position_side=position_side,
        open_risk=Decimal(open_risk),
        daily_pnl_contribution=Decimal(daily_pnl_contribution),
    )


def _size_and_quantize(
    *,
    equity: str = "10000.00",
    risk_rate: str = "0.005",
    stop_loss: str = "49000.00",
    entry_min: str = "49900.00",
    entry_max: str = "50100.00",
    costs: str = "1.0",
    symbol: str = "BTCUSDT",
    metadata_observed_at_utc: datetime | None = None,
) -> SizedResult:
    """Run size_position + quantize and return the final SizedResult."""
    plan = _mk_trade_plan(
        symbol=symbol,
        entry_min=entry_min,
        entry_max=entry_max,
        stop_loss=stop_loss,
        risk_rate=risk_rate,
        risk_budget=str(Decimal(equity) * Decimal(risk_rate)),
    )
    account = _mk_account_state(equity=equity, risk_rate=risk_rate)
    constraints = _mk_constraints(
        symbol=symbol, metadata_observed_at_utc=metadata_observed_at_utc
    )
    entry_ref = (Decimal(entry_min) + Decimal(entry_max)) / Decimal("2")
    sized = size_position(
        trade_plan=plan,
        account_state=account,
        entry_ref=entry_ref,
        modeled_costs_per_unit=Decimal(costs),
    )
    if sized.is_no_trade:
        return sized
    allowed_risk = Decimal(equity) * Decimal(risk_rate)
    sl_distance = abs(entry_ref - Decimal(stop_loss))
    risk_per_unit = sl_distance + Decimal(costs)
    return quantize(
        sized=sized,
        constraint_snapshot=constraints,
        allowed_risk=allowed_risk,
        risk_per_unit=risk_per_unit,
        minimum_risk_utilization_after_rounding=Decimal("0.6"),
        reference_price=entry_ref,
    )


# --------------------------------------------------------------------------- #
# Test 1 — cluster cap exact pass (open_risk + candidate_risk == cluster_cap).
# --------------------------------------------------------------------------- #


def test_cluster_cap_exact_pass() -> None:
    """Beh. 1a: open_risk + candidate_risk == cluster_cap → PASS (boundary).

    Per D-03 + 05-01 checkpoint lock: candidate risk ADDED to open-risk
    sums; equality is the inclusive boundary (== cap is PASS, > cap is
    REJECT).
    """
    # equity=10000, cluster_cap=0.005 → cluster_cap_quote = 50 USDT.
    # ETHUSDT LONG open_risk = 30, BTCUSDT candidate risk = 20 → 30+20=50.
    sized = _size_and_quantize(
        equity="10000.00",
        risk_rate="0.002",  # allowed_risk = 20
        stop_loss="49990.00",
        entry_min="49995.00",
        entry_max="50005.00",
        costs="0.0",
    )
    assert sized.is_no_trade is False
    assert sized.realized_risk == Decimal("20")

    open_positions = [_mk_open_position("ETHUSDT", "LONG", "30.00")]
    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=open_positions,
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
    )
    assert verdict.is_no_trade is False
    assert verdict.reason_code == "OK"
    assert verdict.daily_state == DailyState.NORMAL


# --------------------------------------------------------------------------- #
# Test 2 — cluster cap one ULP over → CLUSTER_CAP_REJECT.
# --------------------------------------------------------------------------- #


def test_cluster_cap_one_ulp_over_rejects() -> None:
    """Beh. 1b: open_risk + candidate_risk > cluster_cap → CLUSTER_CAP_REJECT.

    Per D-03: first failing gate determines the reason code.
    """
    # equity=10000, cluster_cap_quote = 50 USDT.
    # ETHUSDT LONG open_risk = 21, BTCUSDT candidate risk = 30 → 21+30=51 > 50.
    sized = _size_and_quantize(
        equity="10000.00",
        risk_rate="0.003",  # allowed_risk = 30
        stop_loss="49990.00",
        entry_min="49995.00",
        entry_max="50005.00",
        costs="0.0",
    )
    assert sized.is_no_trade is False
    assert sized.realized_risk == Decimal("30")

    open_positions = [_mk_open_position("ETHUSDT", "LONG", "21.00")]
    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=open_positions,
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
    )
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "CLUSTER_CAP_REJECT"
    assert verdict.daily_state == DailyState.NORMAL


# --------------------------------------------------------------------------- #
# Test 3 — aggregate cap exact pass.
# --------------------------------------------------------------------------- #


def test_aggregate_cap_exact_pass() -> None:
    """Beh. 1c: open_risk + candidate_risk == max_aggregate_open_risk → PASS."""
    # equity=10000, max_aggregate_open_risk=0.01 → cap_quote = 100 USDT.
    # BNBUSDT (NOT in cluster) open_risk = 70, BTCUSDT candidate risk = 30 → 100.
    sized = _size_and_quantize(
        equity="10000.00",
        risk_rate="0.003",  # allowed_risk = 30
        stop_loss="49990.00",
        entry_min="49995.00",
        entry_max="50005.00",
        costs="0.0",
    )
    assert sized.is_no_trade is False
    assert sized.realized_risk == Decimal("30")

    open_positions = [_mk_open_position("BNBUSDT", "LONG", "70.00")]
    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=open_positions,
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
    )
    assert verdict.is_no_trade is False
    assert verdict.reason_code == "OK"


# --------------------------------------------------------------------------- #
# Test 4 — aggregate cap one ULP over → AGGREGATE_CAP_REJECT.
# --------------------------------------------------------------------------- #


def test_aggregate_cap_one_ulp_over_rejects() -> None:
    """Beh. 1d: open_risk + candidate_risk > max_aggregate_open_risk → REJECT."""
    # BNBUSDT open_risk = 71, BTCUSDT candidate risk = 30 → 71+30=101 > 100.
    sized = _size_and_quantize(
        equity="10000.00",
        risk_rate="0.003",
        stop_loss="49990.00",
        entry_min="49995.00",
        entry_max="50005.00",
        costs="0.0",
    )
    assert sized.is_no_trade is False
    assert sized.realized_risk == Decimal("30")

    open_positions = [_mk_open_position("BNBUSDT", "LONG", "71.00")]
    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=open_positions,
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
    )
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "AGGREGATE_CAP_REJECT"


# --------------------------------------------------------------------------- #
# Test 5 — first-failure-wins: cluster OK, aggregate FAIL → AGGREGATE_CAP_REJECT.
# --------------------------------------------------------------------------- #


def test_first_failure_wins_aggregate_over_cluster() -> None:
    """Beh. 1e: cluster passes, aggregate fails → AGGREGATE_CAP_REJECT.

    Per D-03: gate order is fixed (cluster → aggregate → count → daily);
    first failing gate determines the reason code.
    """
    # ETHUSDT LONG open_risk = 30 (cluster member, same direction).
    # BNBUSDT LONG open_risk = 71 (NOT in cluster).
    # Cluster sum: 30 + 30 = 60 > 50 → CLUSTER_CAP_REJECT would fire first.
    # To test first-failure-wins for aggregate, we need cluster to PASS
    # but aggregate to FAIL. Use a non-cluster candidate symbol.
    # Candidate: SOLUSDT (cluster member) with risk = 10.
    # Cluster sum: 30 + 10 = 40 < 50 → cluster PASS.
    # Aggregate sum: 30 + 71 + 10 = 111 > 100 → aggregate FAIL.
    sized = _size_and_quantize(
        equity="10000.00",
        risk_rate="0.001",  # allowed_risk = 10
        stop_loss="49990.00",
        entry_min="49995.00",
        entry_max="50005.00",
        costs="0.0",
        symbol="SOLUSDT",
    )
    assert sized.is_no_trade is False
    assert sized.realized_risk == Decimal("10")

    open_positions = [
        _mk_open_position("ETHUSDT", "LONG", "30.00"),
        _mk_open_position("BNBUSDT", "LONG", "71.00"),
    ]
    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="SOLUSDT",
        candidate_position_side="LONG",
        open_positions=open_positions,
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
    )
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "AGGREGATE_CAP_REJECT"


# --------------------------------------------------------------------------- #
# Test 6 — position count at max → MAX_POSITIONS_REJECT.
# --------------------------------------------------------------------------- #


def test_max_positions_at_limit_rejects() -> None:
    """Beh. 1f: len(open_positions) >= max_open_positions → MAX_POSITIONS_REJECT.

    Per D-03: count OPEN positions only (candidate is not yet a position).
    """
    # 2 existing open positions (== max_open_positions = 2).
    # Candidate risk = 5 (small, so cluster/aggregate pass).
    sized = _size_and_quantize(
        equity="10000.00",
        risk_rate="0.0005",  # allowed_risk = 5
        stop_loss="49990.00",
        entry_min="49995.00",
        entry_max="50005.00",
        costs="0.0",
    )
    assert sized.is_no_trade is False
    assert sized.realized_risk == Decimal("5")

    open_positions = [
        _mk_open_position("ETHUSDT", "LONG", "10.00"),
        _mk_open_position("SOLUSDT", "LONG", "10.00"),
    ]
    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=open_positions,
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
    )
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "MAX_POSITIONS_REJECT"


# --------------------------------------------------------------------------- #
# Test 7 — DAILY_STOP at stop threshold → DAILY_STOP_BLOCK.
# --------------------------------------------------------------------------- #


def test_daily_stop_at_threshold_blocks() -> None:
    """Beh. 1g: daily_loss_quote == stop_threshold → DAILY_STOP_BLOCK.

    Per D-03: DAILY_STOP blocks new entries; existing protectives stay
    active (enforced downstream — risk only emits the block + reason).
    """
    # equity=10000, daily_loss_stop_threshold=0.01 → stop_quote = 100 USDT.
    sized = _size_and_quantize(
        equity="10000.00",
        risk_rate="0.005",
        stop_loss="49000.00",
        entry_min="49900.00",
        entry_max="50100.00",
        costs="1.0",
    )
    assert sized.is_no_trade is False

    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=[],
        daily_loss_quote=Decimal("100.00"),  # == stop_threshold * equity
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
    )
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "DAILY_STOP_BLOCK"
    assert verdict.daily_state == DailyState.DAILY_STOP


# --------------------------------------------------------------------------- #
# Test 8 — WARNING at warning threshold → PASS with daily_state=WARNING.
# --------------------------------------------------------------------------- #


def test_warning_at_threshold_passes_with_state() -> None:
    """Beh. 1h: daily_loss_quote == warning_threshold → PASS, daily_state=WARNING.

    Per D-03: WARNING does not block new entries; the daily state is
    reported in the verdict for downstream consumers.
    """
    # equity=10000, daily_loss_warning_threshold=0.005 → warning_quote = 50 USDT.
    sized = _size_and_quantize(
        equity="10000.00",
        risk_rate="0.005",
        stop_loss="49000.00",
        entry_min="49900.00",
        entry_max="50100.00",
        costs="1.0",
    )
    assert sized.is_no_trade is False

    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=[],
        daily_loss_quote=Decimal("50.00"),  # == warning_threshold * equity
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
    )
    assert verdict.is_no_trade is False
    assert verdict.reason_code == "OK"
    assert verdict.daily_state == DailyState.WARNING


# --------------------------------------------------------------------------- #
# Test 9 — NORMAL below warning → PASS with daily_state=NORMAL.
# --------------------------------------------------------------------------- #


def test_normal_below_warning_passes() -> None:
    """Beh. 1i: daily_loss_quote < warning_threshold → PASS, daily_state=NORMAL."""
    sized = _size_and_quantize()
    assert sized.is_no_trade is False

    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=[],
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
    )
    assert verdict.is_no_trade is False
    assert verdict.reason_code == "OK"
    assert verdict.daily_state == DailyState.NORMAL


# --------------------------------------------------------------------------- #
# Test 10 — TTL exact pass (now_utc - observed_at == ttl).
# --------------------------------------------------------------------------- #


def test_ttl_exact_pass() -> None:
    """Beh. 1j: now_utc - observed_at == ttl → PASS (boundary)."""
    observed_at = FROZEN_NOW - timedelta(seconds=TTL_SECONDS)
    sized = _size_and_quantize(metadata_observed_at_utc=observed_at)
    assert sized.is_no_trade is False

    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=[],
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
        constraint_observed_at_utc=observed_at,
    )
    assert verdict.is_no_trade is False
    assert verdict.reason_code == "OK"


# --------------------------------------------------------------------------- #
# Test 11 — TTL one second over → STALE_CONSTRAINTS.
# --------------------------------------------------------------------------- #


def test_ttl_one_second_over_rejects() -> None:
    """Beh. 1k: now_utc - observed_at > ttl → STALE_CONSTRAINTS (fail closed)."""
    observed_at = FROZEN_NOW - timedelta(seconds=TTL_SECONDS + 1)
    sized = _size_and_quantize(metadata_observed_at_utc=observed_at)
    assert sized.is_no_trade is False

    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=[],
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
        constraint_observed_at_utc=observed_at,
    )
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "STALE_CONSTRAINTS"


# --------------------------------------------------------------------------- #
# Test 12 — daily_loss_quote None → UNCERTAIN_ACCOUNT_STATE.
# --------------------------------------------------------------------------- #


def test_daily_loss_quote_none_rejects() -> None:
    """Beh. 1l: daily_loss_quote is None → UNCERTAIN_ACCOUNT_STATE (fail closed)."""
    sized = _size_and_quantize()
    assert sized.is_no_trade is False

    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=[],
        daily_loss_quote=None,
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
    )
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "UNCERTAIN_ACCOUNT_STATE"


# --------------------------------------------------------------------------- #
# Test 13 — positions_reconciled False → UNCERTAIN_ACCOUNT_STATE.
# --------------------------------------------------------------------------- #


def test_positions_unreconciled_rejects() -> None:
    """Beh. 1m: positions_reconciled=False → UNCERTAIN_ACCOUNT_STATE (fail closed)."""
    sized = _size_and_quantize()
    assert sized.is_no_trade is False

    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=[],
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=False,
    )
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "UNCERTAIN_ACCOUNT_STATE"


# --------------------------------------------------------------------------- #
# Test 14 — order independence: shuffled insertion orders yield identical verdicts.
# --------------------------------------------------------------------------- #


def test_open_positions_order_independence() -> None:
    """Beh. 1n: shuffled insertion orders yield identical PortfolioVerdict.

    Per Pitfall 4: positions are sorted by (symbol, position_side) before
    any aggregation so set/dict iteration order cannot leak into the
    verdict.
    """
    sized = _size_and_quantize(
        equity="10000.00",
        risk_rate="0.003",  # allowed_risk = 30
        stop_loss="49990.00",
        entry_min="49995.00",
        entry_max="50005.00",
        costs="0.0",
    )
    assert sized.is_no_trade is False

    # Two open positions with different insertion orders.
    pos_a = _mk_open_position("ETHUSDT", "LONG", "21.00")
    pos_b = _mk_open_position("BNBUSDT", "LONG", "71.00")
    pos_c = _mk_open_position("SOLUSDT", "LONG", "5.00")

    order_1 = [pos_a, pos_b, pos_c]
    order_2 = [pos_c, pos_a, pos_b]
    order_3 = [pos_b, pos_c, pos_a]

    verdicts = []
    for positions in (order_1, order_2, order_3):
        v = check_portfolio(
            sized=sized,
            candidate_symbol="BTCUSDT",
            candidate_position_side="LONG",
            open_positions=positions,
            daily_loss_quote=Decimal("0"),
            parameter_set=PARAMETERS,
            now_utc=FROZEN_NOW,
            ttl=timedelta(seconds=TTL_SECONDS),
            positions_reconciled=True,
        )
        verdicts.append(v)

    # All three verdicts must be byte-identical.
    for v in verdicts[1:]:
        assert v.is_no_trade == verdicts[0].is_no_trade
        assert v.reason_code == verdicts[0].reason_code
        assert v.daily_state == verdicts[0].daily_state


# --------------------------------------------------------------------------- #
# Test 15 — candidate-risk-added semantic: open_risk + candidate_risk == cap → PASS.
# --------------------------------------------------------------------------- #


def test_candidate_risk_added_to_open_risk_sums() -> None:
    """Beh. 1o: candidate risk is ADDED to open-risk sums (Pitfall 6 lock).

    Per 05-01 checkpoint: candidate risk is included in cluster and
    aggregate sums. Equality at the cap is PASS (boundary).
    """
    # ETHUSDT LONG open_risk = 30, BTCUSDT candidate risk = 20 → 30+20=50 = cap.
    sized = _size_and_quantize(
        equity="10000.00",
        risk_rate="0.002",  # allowed_risk = 20
        stop_loss="49990.00",
        entry_min="49995.00",
        entry_max="50005.00",
        costs="0.0",
    )
    assert sized.is_no_trade is False
    assert sized.realized_risk == Decimal("20")

    open_positions = [_mk_open_position("ETHUSDT", "LONG", "30.00")]
    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=open_positions,
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
    )
    assert verdict.is_no_trade is False
    assert verdict.reason_code == "OK"


# --------------------------------------------------------------------------- #
# Test 16 — sized.is_no_trade short-circuits to PortfolioVerdict with same reason.
# --------------------------------------------------------------------------- #


def test_sized_no_trade_short_circuits() -> None:
    """Beh. 1p: if sized.is_no_trade=True, check_portfolio preserves the reason.

    Per D-02: sizing/quantization rejects short-circuit before portfolio
    gates run. The portfolio verdict carries the upstream reason code.
    """
    # Force a sizing reject: zero SL distance.
    sized = _size_and_quantize(
        equity="10000.00",
        risk_rate="0.005",
        stop_loss="50000.00",  # == entry_ref → sl_distance = 0
        entry_min="49900.00",
        entry_max="50100.00",
        costs="1.0",
    )
    assert sized.is_no_trade is True
    assert sized.reason_code == "EXCHANGE_CONSTRAINT"

    verdict = check_portfolio(
        sized=sized,
        candidate_symbol="BTCUSDT",
        candidate_position_side="LONG",
        open_positions=[],
        daily_loss_quote=Decimal("0"),
        parameter_set=PARAMETERS,
        now_utc=FROZEN_NOW,
        ttl=timedelta(seconds=TTL_SECONDS),
        positions_reconciled=True,
    )
    assert verdict.is_no_trade is True
    assert verdict.reason_code == "EXCHANGE_CONSTRAINT"


# --------------------------------------------------------------------------- #
# Test 17 — OpenPosition construction guards.
# --------------------------------------------------------------------------- #


def test_open_position_construction_guards() -> None:
    """Beh. 1q: OpenPosition rejects empty symbol and non-Decimal fields."""
    with pytest.raises(ValueError, match="symbol must be a non-empty string"):
        OpenPosition(
            symbol="",
            position_side="LONG",
            open_risk=Decimal("10"),
            daily_pnl_contribution=Decimal("0"),
        )
    with pytest.raises(TypeError, match="open_risk must be Decimal"):
        OpenPosition(
            symbol="BTCUSDT",
            position_side="LONG",
            open_risk=10.0,  # type: ignore[arg-type]
            daily_pnl_contribution=Decimal("0"),
        )


# --------------------------------------------------------------------------- #
# Test 18 — PortfolioVerdict envelope guards.
# --------------------------------------------------------------------------- #


def test_portfolio_verdict_envelope_guards() -> None:
    """Beh. 1r: PortfolioVerdict envelope validates is_no_trade/sized pairing."""
    sized = _size_and_quantize()
    assert sized.is_no_trade is False

    # is_no_trade=True requires sized=None.
    with pytest.raises(ValueError, match="is_no_trade=True requires sized=None"):
        PortfolioVerdict(
            is_no_trade=True,
            sized=sized,
            reason_code="OK",
            daily_state=DailyState.NORMAL,
        )
    # is_no_trade=False requires sized to be set.
    with pytest.raises(ValueError, match="is_no_trade=False requires sized"):
        PortfolioVerdict(
            is_no_trade=False,
            sized=None,
            reason_code="OK",
            daily_state=DailyState.NORMAL,
        )


# --------------------------------------------------------------------------- #
# Test 19 — parity: each portfolio case runs through evaluate_risk twice with
# canonical-JSON-identical outputs.
# --------------------------------------------------------------------------- #


def _load_input(case_dir: Path) -> dict:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _build_trade_plan(tp_dict: dict) -> TradePlan:
    return TradePlan(
        trade_plan_id=tp_dict["trade_plan_id"],
        signal_id=tp_dict["signal_id"],
        trade_plan_version=tp_dict["trade_plan_version"],
        entry_model=tp_dict["entry_model"],
        entry_min_price=Decimal(tp_dict["entry_min_price"]),
        entry_max_price=Decimal(tp_dict["entry_max_price"]),
        stop_loss_price=Decimal(tp_dict["stop_loss_price"]),
        take_profit_json=tp_dict["take_profit_json"],
        invalidation_rule_json=tp_dict["invalidation_rule_json"],
        expiry_utc=datetime.fromisoformat(tp_dict["expiry_utc"]),
        expected_rr_json=tp_dict["expected_rr_json"],
        risk_rate=Decimal(tp_dict["risk_rate"]),
        risk_budget=Decimal(tp_dict["risk_budget"]),
        suggested_quantity=Decimal(tp_dict["suggested_quantity"]),
        quantity_before_rounding=Decimal(tp_dict["quantity_before_rounding"]),
        quantity_after_rounding=Decimal(tp_dict["quantity_after_rounding"]),
        quantization_decision=tp_dict["quantization_decision"],
        plan_hash=tp_dict["plan_hash"],
        status=TradePlanStatus(tp_dict["status"]),
        created_at_utc=datetime.fromisoformat(tp_dict["created_at_utc"]),
    )


def _build_account_state(as_dict: dict) -> AccountState:
    return AccountState(
        equity=Decimal(as_dict["equity"]),
        risk_rate=Decimal(as_dict["risk_rate"]),
    )


def _build_constraints(cs_dict: dict) -> ConstraintSnapshot:
    return ConstraintSnapshot(
        symbol=cs_dict["symbol"],
        price_tick_size=Decimal(cs_dict["price_tick_size"]),
        quantity_step_size=Decimal(cs_dict["quantity_step_size"]),
        min_quantity=Decimal(cs_dict["min_quantity"]),
        min_notional=Decimal(cs_dict["min_notional"]),
        metadata_observed_at_utc=datetime.fromisoformat(cs_dict["metadata_observed_at_utc"]),
    )


def _build_open_positions(op_list: list[dict]) -> list[OpenPosition]:
    return [
        OpenPosition(
            symbol=p["symbol"],
            position_side=p["position_side"],
            open_risk=Decimal(p["open_risk"]),
            daily_pnl_contribution=Decimal(p["daily_pnl_contribution"]),
        )
        for p in op_list
    ]


def _run_evaluate_risk(case_input: dict) -> PortfolioVerdict:
    """Run the full evaluate_risk pipeline on a phase5 case input."""
    from src.risk.gating import evaluate_risk

    trade_plan = _build_trade_plan(case_input["trade_plan"])
    account = _build_account_state(case_input["account_state"])
    constraints = _build_constraints(case_input["constraint_snapshot"])
    open_positions = _build_open_positions(case_input["open_positions"])
    daily_loss_raw = case_input["daily_loss_quote"]
    daily_loss_quote = (
        None if daily_loss_raw is None else Decimal(daily_loss_raw)
    )
    now_utc = datetime.fromisoformat(case_input["now_utc"])
    ttl = timedelta(seconds=int(case_input["ttl_seconds"]))
    modeled_costs = Decimal(str(case_input["modeled_costs_per_unit"]))

    return evaluate_risk(
        trade_plan=trade_plan,
        account_state=account,
        constraint_snapshot=constraints,
        open_positions=open_positions,
        daily_loss_quote=daily_loss_quote,
        now_utc=now_utc,
        ttl=ttl,
        modeled_costs_per_unit=modeled_costs,
        minimum_risk_utilization_after_rounding=Decimal("0.6"),
        parameter_set=PARAMETERS,
    )


def _to_parity_dict(verdict: PortfolioVerdict) -> dict:
    """Project PortfolioVerdict to a parity-fixture-shaped dict."""
    sized = verdict.sized
    return {
        "is_no_trade": verdict.is_no_trade,
        "quantity": None if sized is None or sized.quantity is None else str(sized.quantity),
        "quantity_before_rounding": (
            None if sized is None else str(sized.quantity_before_rounding)
        ),
        "quantity_after_rounding": (
            None if sized is None else str(sized.quantity_after_rounding)
        ),
        "quantization_decision": (
            None if sized is None else sized.quantization_decision
        ),
        "realized_risk": None if sized is None else str(sized.realized_risk),
        "reason_code": verdict.reason_code,
        "daily_state": verdict.daily_state.value,
    }


_PHASE5_PORTFOLIO_CASES = (
    "cluster_cap_reject",
    "aggregate_cap_reject",
    "max_positions_reject",
    "daily_stop_block",
    "stale_constraints",
    "uncertain_account_state",
)


@pytest.mark.parametrize("case_name", _PHASE5_PORTFOLIO_CASES)
def test_portfolio_case_byte_identical_across_runs(case_name: str) -> None:
    """Beh. 1s: each portfolio case runs through evaluate_risk twice with
    canonical-JSON-identical outputs (parity guarantee).
    """
    case_dir = PHASE5_FIXTURES_DIR / case_name
    case_input = _load_input(case_dir)

    a = _run_evaluate_risk(case_input)
    b = _run_evaluate_risk(case_input)

    a_dict = _to_parity_dict(a)
    b_dict = _to_parity_dict(b)
    assert sha256_hex(a_dict) == sha256_hex(b_dict), (
        f"parity mismatch in {case_name}: a={a_dict}, b={b_dict}"
    )
    assert a.reason_code == b.reason_code
    assert a.daily_state == b.daily_state
    assert a.is_no_trade == b.is_no_trade
