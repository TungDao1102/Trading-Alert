"""Tests for the portfolio-cap reservation inputs (Phase 21, plan 21-06; D-15, D-16, D-17).

`reservation_verdict` judges a reservation request through the shared `check_portfolio` against
the counted reservation rows, never counting the candidate's own row twice. The thresholds are
ABSOLUTE quote amounts. Every expected value is a literal derived by hand in the comments.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from src.domain.enums import DailyState, RejectionReason
from src.risk import reservations as reservations_module
from src.risk.reservations import (
    CountedReservation,
    ReservationRequest,
    ReservationStatus,
    reservation_verdict,
)

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64

# Absolute thresholds: cluster cap 6, aggregate cap 10, at most 2 positions, warning 5, stop 10.
THRESHOLDS: dict[str, Any] = {
    "max_open_positions": 2,
    "max_aggregate_open_risk": Decimal("10"),
    "cluster_cap": Decimal("6"),
    "daily_loss_warning_threshold": Decimal("5"),
    "daily_loss_stop_threshold": Decimal("10"),
}


def _counted(
    plan_id: str,
    symbol: str,
    side: str,
    status: ReservationStatus,
    risk: str,
    plan_hash: str = HASH_A,
) -> CountedReservation:
    return CountedReservation(
        trade_plan_id=plan_id,
        plan_hash=plan_hash,
        symbol=symbol,
        position_side=side,
        status=status,
        open_risk=Decimal(risk),
    )


def _request(
    symbol: str,
    side: str,
    risk: str,
    plan_id: str = "plan-req",
    plan_hash: str = HASH_D,
    quantity: str = "1",
) -> ReservationRequest:
    return ReservationRequest(
        trade_plan_id=plan_id,
        plan_hash=plan_hash,
        symbol=symbol,
        position_side=side,
        quantity=Decimal(quantity),
        realized_risk=Decimal(risk),
    )


def _verdict(
    request: ReservationRequest,
    counted: tuple[CountedReservation, ...],
    *,
    daily_loss: Decimal | None = Decimal("0"),
    latched: bool = False,
) -> Any:
    return reservation_verdict(
        request=request,
        counted=counted,
        daily_loss_quote=daily_loss,
        stop_latched=latched,
        thresholds=THRESHOLDS,
        now_utc=NOW,
    )


A_RESERVED = _counted("plan-a", "BTCUSDT", "LONG", ReservationStatus.RESERVED, "5")


# --------------------------------------------------------------------------- #
# Task 1 - reservation_verdict over check_portfolio
# --------------------------------------------------------------------------- #


def test_cluster_cap_rejects_when_sum_exceeds_cap() -> None:
    # BTC LONG 5 + ETH LONG 2 = 7 > cluster cap 6.
    verdict = _verdict(_request("ETHUSDT", "LONG", "2"), (A_RESERVED,))
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.CLUSTER_CAP_REJECT.value
    assert verdict.sized is None


def test_aggregate_cap_passes_exactly_at_the_cap() -> None:
    # BNB is outside the cluster; aggregate 5 + 5 = 10 == cap 10 passes (strictly greater rejects).
    verdict = _verdict(_request("BNBUSDT", "LONG", "5"), (A_RESERVED,))
    assert verdict.is_no_trade is False
    assert verdict.reason_code == "OK"
    assert verdict.sized is not None
    # The reserved amount is the sized realized risk (Pitfall 9).
    assert verdict.sized.realized_risk == Decimal("5")
    assert verdict.sized.quantity == Decimal("1")


def test_aggregate_cap_rejects_one_cent_over() -> None:
    # 5 + 5.01 = 10.01 > 10.
    verdict = _verdict(_request("BNBUSDT", "LONG", "5.01"), (A_RESERVED,))
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.AGGREGATE_CAP_REJECT.value


def test_third_position_hits_the_position_count() -> None:
    counted = (
        _counted("plan-a", "BTCUSDT", "LONG", ReservationStatus.RESERVED, "1"),
        _counted("plan-b", "BNBUSDT", "SHORT", ReservationStatus.PLACED, "1", HASH_B),
    )
    # Both caps fit (SOL LONG 1: cluster 1+1=2 <= 6; aggregate 3 <= 10); two rows >= max 2.
    verdict = _verdict(_request("SOLUSDT", "LONG", "1"), counted)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.MAX_POSITIONS_REJECT.value


def test_own_reservation_is_excluded_so_an_exact_fit_still_passes() -> None:
    # At placement the request's own row is already counted. Judged against {A 5, own 5} it
    # would be 5 + 5 + 5 = 15 > 10; with the own row excluded it is 5 + 5 = 10 and passes.
    own = _counted("plan-req", "BNBUSDT", "LONG", ReservationStatus.RESERVED, "5", HASH_D)
    verdict = _verdict(_request("BNBUSDT", "LONG", "5"), (A_RESERVED, own))
    assert verdict.is_no_trade is False
    assert verdict.reason_code == "OK"


def test_own_reservation_excluded_from_the_position_count() -> None:
    # Two other rows would hit the count; own + one other must not (1 other < max 2).
    own = _counted("plan-req", "BNBUSDT", "LONG", ReservationStatus.RESERVED, "1", HASH_D)
    other = _counted("plan-a", "BTCUSDT", "LONG", ReservationStatus.RESERVED, "1")
    verdict = _verdict(_request("BNBUSDT", "LONG", "1"), (other, own))
    assert verdict.is_no_trade is False


def test_latched_day_refuses_with_daily_stop_even_when_everything_fits() -> None:
    verdict = _verdict(_request("BNBUSDT", "LONG", "1"), (), latched=True)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.DAILY_STOP_BLOCK.value
    assert verdict.daily_state is DailyState.DAILY_STOP
    assert verdict.sized is None


def test_unknown_daily_loss_refuses_with_uncertain_account_state() -> None:
    verdict = _verdict(_request("BNBUSDT", "LONG", "1"), (), daily_loss=None)
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.UNCERTAIN_ACCOUNT_STATE.value


def test_daily_loss_at_the_stop_threshold_refuses_through_check_portfolio() -> None:
    verdict = _verdict(_request("BNBUSDT", "LONG", "1"), (), daily_loss=Decimal("10"))
    assert verdict.is_no_trade is True
    assert verdict.reason_code == RejectionReason.DAILY_STOP_BLOCK.value


def test_empty_counted_with_loss_below_warning_passes_normal() -> None:
    verdict = _verdict(_request("BNBUSDT", "LONG", "1"), (), daily_loss=Decimal("4.99"))
    assert verdict.is_no_trade is False
    assert verdict.daily_state is DailyState.NORMAL


def test_counted_order_does_not_change_the_verdict() -> None:
    b = _counted("plan-b", "ETHUSDT", "LONG", ReservationStatus.PLACED, "1", HASH_B)
    request = _request("SOLUSDT", "LONG", "1")
    assert _verdict(request, (A_RESERVED, b)) == _verdict(request, (b, A_RESERVED))


@pytest.mark.parametrize(
    "overrides",
    [
        {"realized_risk": Decimal("0")},
        {"realized_risk": Decimal("-1")},
        {"quantity": Decimal("0")},
        {"quantity": Decimal("-1")},
        {"position_side": "BOTH"},
        {"position_side": "long"},
        {"plan_hash": "a" * 63},
        {"plan_hash": "A" * 64},
        {"plan_hash": "g" * 64},
        {"symbol": ""},
        {"trade_plan_id": ""},
    ],
)
def test_reservation_request_refuses_invalid_fields(overrides: dict[str, Any]) -> None:
    fields: dict[str, Any] = {
        "trade_plan_id": "plan-req",
        "plan_hash": HASH_D,
        "symbol": "BNBUSDT",
        "position_side": "LONG",
        "quantity": Decimal("1"),
        "realized_risk": Decimal("1"),
    }
    fields.update(overrides)
    with pytest.raises(ValueError):
        ReservationRequest(**fields)


@pytest.mark.parametrize("field", ["realized_risk", "quantity"])
def test_reservation_request_refuses_a_non_decimal_amount(field: str) -> None:
    fields: dict[str, Any] = {
        "trade_plan_id": "plan-req",
        "plan_hash": HASH_D,
        "symbol": "BNBUSDT",
        "position_side": "LONG",
        "quantity": Decimal("1"),
        "realized_risk": Decimal("1"),
    }
    fields[field] = 1
    with pytest.raises(TypeError):
        ReservationRequest(**fields)


def test_reservation_request_refuses_a_non_finite_amount() -> None:
    with pytest.raises(ValueError):
        _request("BNBUSDT", "LONG", "NaN")
    with pytest.raises(ValueError):
        _request("BNBUSDT", "LONG", "Infinity")


def test_module_is_pure_stdlib_domain_core_risk_only() -> None:
    path = Path(reservations_module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed_roots = {"src.domain", "src.core", "src.risk"}
    stdlib = set(__import__("sys").stdlib_module_names)
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names = ["src.risk"]
            elif node.module:
                names = [node.module]
        for name in names:
            root = name.split(".")[0]
            assert (
                root in stdlib
                or root == "__future__"
                or any(name == a or name.startswith(a + ".") for a in allowed_roots)
            ), f"disallowed import {name}"


def test_module_reads_no_clock_and_builds_no_float() -> None:
    path = Path(reservations_module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                assert func.id != "float", "float constructor"
            if isinstance(func, ast.Attribute):
                assert func.attr not in {"now", "utcnow", "today", "time", "monotonic"}, func.attr
