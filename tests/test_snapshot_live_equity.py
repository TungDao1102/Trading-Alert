"""D-18 snapshot test (Phase 21, plan 21-04; G4-039, 21-NOTES).

`attach_protectives_to_fill` places take-profit orders only when `snapshot_is_valid_for_live`
holds for the plan's constraint snapshot. This file shows that a COMPLETE snapshot built from a
resolved live equity passes that gate once Phase 22 supplies margin type and leverage, and that
it does not while any live input is unknown. Phase 21 itself sets neither margin type nor
leverage (D-19): an AST scan of `src` proves it.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import LiveInputsStatus
from src.execution.constraint_snapshot import (
    ExchangeFilterExtras,
    PlanConstraintSnapshot,
    build_plan_constraint_snapshot,
    snapshot_is_valid_for_live,
)
from src.risk.live_equity import AccountEquityReading, LiveEquityResult, resolve_live_equity
from src.risk.types import ConstraintSnapshot

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"

# TEST DATA: stands in for the Phase 22 margin type input (D035 is Phase 22). The Demo account
# is x20 CROSSED by account default and the system never sets it. Never a production default.
STUB_MARGIN_TYPE = "ISOLATED"
# TEST DATA: stands in for the Phase 22 leverage input (D035 is Phase 22). Never a production
# default; no module under src may pass it (see the AST scan below).
STUB_LEVERAGE = 5

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
OBSERVED = NOW - timedelta(seconds=30)
TTL = timedelta(seconds=3600)
MAX_AGE = timedelta(seconds=60)
RISK_RATE = Decimal("0.005")
DEMO_EQUITY = Decimal("4999.09343961")


def _constraints() -> ConstraintSnapshot:
    return ConstraintSnapshot(
        symbol="BTCUSDT",
        price_tick_size=Decimal("0.10"),
        quantity_step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("50"),
        metadata_observed_at_utc=OBSERVED,
    )


def _extras() -> ExchangeFilterExtras:
    return ExchangeFilterExtras(
        market_lot_min_quantity=Decimal("0.001"),
        market_lot_max_quantity=Decimal("120"),
        market_lot_step_size=Decimal("0.001"),
        percent_price_multiplier_up=Decimal("1.0500"),
        percent_price_multiplier_down=Decimal("0.9500"),
        percent_price_multiplier_decimals=4,
    )


def _reading(**overrides: Any) -> AccountEquityReading:
    kwargs: dict[str, Any] = {
        "total_margin_balance": DEMO_EQUITY,
        "total_wallet_balance": DEMO_EQUITY,
        "total_unrealized_profit": Decimal("0.00000000"),
        "quote_asset_margin_balance": DEMO_EQUITY,
        "balance_endpoint_wallet": DEMO_EQUITY,
        "multi_assets_margin": False,
        "available_balance": DEMO_EQUITY,
        "total_open_order_initial_margin": Decimal("0.00000000"),
        "quote_asset_available_balance": DEMO_EQUITY,
        "dual_side_position": False,
        "observed_at_utc": NOW - timedelta(seconds=10),
    }
    kwargs.update(overrides)
    return AccountEquityReading(**kwargs)


def _resolve(reading: AccountEquityReading) -> LiveEquityResult:
    return resolve_live_equity(reading=reading, risk_rate=RISK_RATE, now_utc=NOW, max_age=MAX_AGE)


def _snapshot(
    result: LiveEquityResult,
    *,
    margin_type: str | None = STUB_MARGIN_TYPE,
    leverage: int | None = STUB_LEVERAGE,
) -> PlanConstraintSnapshot:
    return build_plan_constraint_snapshot(
        "plan-1",
        _constraints(),
        _extras(),
        Decimal("1000"),
        "MARK_PRICE",
        margin_type=margin_type,
        leverage=leverage,
        equity_used=result.equity_for_snapshot,
        captured_at_utc=NOW,
    )


def test_live_equity_with_stubbed_phase22_inputs_is_valid_for_live() -> None:
    result = _resolve(_reading())
    assert result.reason_code == "OK"
    snapshot = _snapshot(result)
    assert snapshot.live_inputs_status is LiveInputsStatus.COMPLETE
    assert snapshot_is_valid_for_live(snapshot, now_utc=NOW, ttl=TTL) is True
    assert snapshot.equity_used == Decimal("4999.09343961")


def test_no_trade_equity_leaves_snapshot_incomplete() -> None:
    stale = _reading(observed_at_utc=NOW - MAX_AGE - timedelta(milliseconds=1))
    result = _resolve(stale)
    assert result.is_no_trade is True
    snapshot = _snapshot(result)
    assert snapshot.equity_used is None
    assert snapshot.live_inputs_status is LiveInputsStatus.INCOMPLETE
    assert snapshot_is_valid_for_live(snapshot, now_utc=NOW, ttl=TTL) is False


def test_live_equity_without_margin_type_and_leverage_is_not_valid_for_live() -> None:
    # What Phase 21 really has (D-19): equity yes, margin type and leverage not yet.
    result = _resolve(_reading())
    snapshot = _snapshot(result, margin_type=None, leverage=None)
    assert snapshot.equity_used == Decimal("4999.09343961")
    assert snapshot.live_inputs_status is LiveInputsStatus.INCOMPLETE
    assert snapshot_is_valid_for_live(snapshot, now_utc=NOW, ttl=TTL) is False


def test_live_equity_without_margin_type_alone_is_not_valid_for_live() -> None:
    snapshot = _snapshot(_resolve(_reading()), margin_type=None)
    assert snapshot_is_valid_for_live(snapshot, now_utc=NOW, ttl=TTL) is False


def test_live_equity_without_leverage_alone_is_not_valid_for_live() -> None:
    snapshot = _snapshot(_resolve(_reading()), leverage=None)
    assert snapshot_is_valid_for_live(snapshot, now_utc=NOW, ttl=TTL) is False


def test_unknown_sentinel_margin_type_cannot_reach_a_snapshot() -> None:
    # Unknown is None, never the UNKNOWN text: the snapshot refuses the sentinel outright.
    with pytest.raises(ValueError):
        _snapshot(_resolve(_reading()), margin_type="UNKNOWN")


def test_no_module_under_src_sets_margin_type_or_leverage() -> None:
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name != "build_plan_constraint_snapshot":
                continue
            for keyword in node.keywords:
                if keyword.arg in ("margin_type", "leverage"):
                    offenders.append(f"{path.relative_to(SRC_ROOT)}:{node.lineno}:{keyword.arg}")
    assert offenders == []
