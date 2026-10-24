"""Tests for the pure available-margin predicate (Phase 22, plan 22-04; D-13, criterion 3, F-966).

The check answers one question: does the exchange's free margin cover the new order plus every
other claim on margin? Oracles are literal Decimals; no expectation is computed by the code under
test. The -2019 shape below is a recorded Demo payload (demo-observed, not mainnet, D-19): 10 BTC
at 78570.9 at leverage 20 against an availableBalance of 4998.39137539.
"""

from __future__ import annotations

import ast
import inspect
from decimal import Decimal
from pathlib import Path

import pytest
from src.domain.enums import Direction, RejectionReason
from src.risk import margin_check
from src.risk.margin_check import (
    MarginVerdict,
    estimated_fees,
    estimated_open_loss,
    margin_verdict,
    required_initial_margin,
)

from tests.support.ast_guards import float_constructor_calls, forbidden_imports, wall_clock_calls

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE = REPO_ROOT / "src" / "risk" / "margin_check.py"

INSUFFICIENT = "INSUFFICIENT_MARGIN"
UNCERTAIN = "UNCERTAIN_ACCOUNT_STATE"
RATE = Decimal("0.0004")
DEMO_AVAILABLE = Decimal("4998.39137539")


def _verdict(**overrides: object) -> MarginVerdict:
    """The small passing plan: 0.01 at 80000, leverage 5, rates 0.0004 each, headroom 500 bps."""
    kwargs: dict[str, object] = {
        "available_balance": Decimal("1000"),
        "quantity": Decimal("0.01"),
        "limit_price": Decimal("80000"),
        "mark_price": Decimal("80000"),
        "side": Direction.LONG,
        "leverage": 5,
        "fee_rate_entry": RATE,
        "fee_rate_exit": RATE,
        "others_margin": Decimal("0"),
        "headroom_bps": 500,
    }
    kwargs.update(overrides)
    return margin_verdict(**kwargs)  # type: ignore[arg-type]


# --- required_initial_margin ------------------------------------------------------------------


def test_recorded_demo_shape_initial_margin() -> None:
    margin = required_initial_margin(quantity=Decimal("10"), price=Decimal("78570.9"), leverage=20)
    assert margin == Decimal("39285.45")


def test_initial_margin_small_plan() -> None:
    margin = required_initial_margin(quantity=Decimal("0.01"), price=Decimal("80000"), leverage=5)
    assert margin == Decimal("160")


@pytest.mark.parametrize("leverage", [True, 0, -3, Decimal("5"), 5.0, "5", None])
def test_initial_margin_rejects_bad_leverage(leverage: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        required_initial_margin(
            quantity=Decimal("1"),
            price=Decimal("100"),
            leverage=leverage,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "quantity, price",
    [
        (Decimal("0"), Decimal("100")),
        (Decimal("-1"), Decimal("100")),
        (Decimal("1"), Decimal("0")),
        (Decimal("1"), Decimal("NaN")),
        (Decimal("Infinity"), Decimal("100")),
        (1, Decimal("100")),
        (Decimal("1"), 100.0),
    ],
)
def test_initial_margin_rejects_bad_quantity_or_price(quantity: object, price: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        required_initial_margin(
            quantity=quantity,  # type: ignore[arg-type]
            price=price,  # type: ignore[arg-type]
            leverage=5,
        )


# --- estimated_fees ---------------------------------------------------------------------------


def test_estimated_fees_literal() -> None:
    fees = estimated_fees(
        quantity=Decimal("0.01"),
        price=Decimal("80000"),
        fee_rate_entry=Decimal("0.0004"),
        fee_rate_exit=Decimal("0.0004"),
    )
    assert fees == Decimal("0.64")


def test_estimated_fees_zero_rates_are_zero() -> None:
    fees = estimated_fees(
        quantity=Decimal("1"),
        price=Decimal("100"),
        fee_rate_entry=Decimal("0"),
        fee_rate_exit=Decimal("0"),
    )
    assert fees == Decimal("0")


@pytest.mark.parametrize(
    "entry, exit_",
    [(Decimal("-0.0001"), RATE), (RATE, Decimal("-0.0001")), (RATE, Decimal("NaN")), (RATE, 0)],
)
def test_estimated_fees_rejects_bad_rates(entry: object, exit_: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        estimated_fees(
            quantity=Decimal("1"),
            price=Decimal("100"),
            fee_rate_entry=entry,  # type: ignore[arg-type]
            fee_rate_exit=exit_,  # type: ignore[arg-type]
        )


# --- estimated_open_loss ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "side, limit, mark, expected",
    [
        (Direction.LONG, "101", "100", "2"),  # buy above the mark: marketable, loses at once
        (Direction.LONG, "99", "100", "0"),  # resting buy below the mark: no open loss
        (Direction.LONG, "100", "100", "0"),
        (Direction.SHORT, "99", "100", "2"),  # sell below the mark
        (Direction.SHORT, "101", "100", "0"),
        (Direction.SHORT, "100", "100", "0"),
    ],
)
def test_estimated_open_loss(side: Direction, limit: str, mark: str, expected: str) -> None:
    loss = estimated_open_loss(
        quantity=Decimal("2"),
        limit_price=Decimal(limit),
        mark_price=Decimal(mark),
        side=side,
    )
    assert loss == Decimal(expected)


def test_estimated_open_loss_rejects_unknown_side() -> None:
    with pytest.raises(ValueError):
        estimated_open_loss(
            quantity=Decimal("1"),
            limit_price=Decimal("100"),
            mark_price=Decimal("100"),
            side="BUY",
        )


# --- margin_verdict: the tracer ---------------------------------------------------------------


def test_recorded_demo_2019_shape_is_refused_insufficient_margin() -> None:
    verdict = margin_verdict(
        available_balance=DEMO_AVAILABLE,
        quantity=Decimal("10"),
        limit_price=Decimal("78570.9"),
        mark_price=Decimal("78570.9"),
        side=Direction.LONG,
        leverage=20,
        fee_rate_entry=RATE,
        fee_rate_exit=RATE,
        others_margin=Decimal("0"),
        headroom_bps=1,
    )
    assert verdict.ok is False
    assert verdict.reason_code == INSUFFICIENT
    assert verdict.required > verdict.available  # type: ignore[operator]
    assert verdict.available == DEMO_AVAILABLE
    # 39285.45 margin + 628.5672 fees = 39914.0172; headroom 1 bps = 3.99140172
    assert verdict.required == Decimal("39918.00860172")


def test_passing_plan_needs_margin_fees_and_headroom_equality_passes() -> None:
    # need 160 + 0.64 = 160.64; headroom 500 bps = 8.032; total 168.672.
    verdict = _verdict(available_balance=Decimal("168.672"))
    assert verdict.ok is True
    assert verdict.reason_code == "OK"
    assert verdict.required == Decimal("168.672")
    assert verdict.available == Decimal("168.672")


def test_one_unit_short_of_equality_fails() -> None:
    verdict = _verdict(available_balance=Decimal("168.671999"))
    assert verdict.ok is False
    assert verdict.reason_code == INSUFFICIENT
    assert verdict.required == Decimal("168.672")


def test_negative_free_margin_is_insufficient_not_an_error() -> None:
    verdict = _verdict(available_balance=Decimal("-5"))
    assert verdict.ok is False
    assert verdict.reason_code == INSUFFICIENT


def test_open_loss_of_a_marketable_limit_is_part_of_the_need() -> None:
    # Buy limit 80100 over a mark of 80000: open loss (80100-80000) x 0.01 = 1.
    # margin 801/5... the limit price is the margin price: 0.01 x 80100 / 5 = 160.2;
    # fees 801 x 0.0008 = 0.6408; need 160.2 + 0.6408 + 1 = 161.8408; headroom 0 bps is refused,
    # so use 1 bps: 0.01618408; total 161.85698408.
    verdict = _verdict(
        available_balance=Decimal("161.85698408"),
        limit_price=Decimal("80100"),
        mark_price=Decimal("80000"),
        headroom_bps=1,
    )
    assert verdict.ok is True
    assert verdict.required == Decimal("161.85698408")


def test_reason_codes_are_the_existing_rejection_reasons() -> None:
    assert INSUFFICIENT == RejectionReason.INSUFFICIENT_MARGIN.value
    assert UNCERTAIN == RejectionReason.UNCERTAIN_ACCOUNT_STATE.value


# --- headroom ---------------------------------------------------------------------------------


@pytest.mark.parametrize("headroom", [True, 0, -1, Decimal("5"), 5.0, "5", None])
def test_headroom_must_be_a_positive_int(headroom: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _verdict(headroom_bps=headroom)


# --- MarginVerdict ----------------------------------------------------------------------------


def test_verdict_ok_requires_reason_ok() -> None:
    with pytest.raises(ValueError):
        MarginVerdict(
            ok=True, reason_code=INSUFFICIENT, required=Decimal("1"), available=Decimal("2")
        )


def test_verdict_refusal_requires_a_rejection_reason() -> None:
    with pytest.raises(ValueError):
        MarginVerdict(ok=False, reason_code="OK", required=Decimal("2"), available=Decimal("1"))
    with pytest.raises(ValueError):
        MarginVerdict(ok=False, reason_code="NOPE", required=Decimal("2"), available=Decimal("1"))


def test_verdict_rejects_float_amounts() -> None:
    with pytest.raises(TypeError):
        MarginVerdict(ok=True, reason_code="OK", required=1.0, available=Decimal("2"))  # type: ignore[arg-type]


# --- purity and no-default signature ----------------------------------------------------------


def test_leverage_fee_rates_and_headroom_are_required_keywords() -> None:
    required = {
        required_initial_margin: ("leverage",),
        estimated_fees: ("fee_rate_entry", "fee_rate_exit"),
        margin_verdict: ("leverage", "fee_rate_entry", "fee_rate_exit", "headroom_bps"),
    }
    for func, names in required.items():
        params = inspect.signature(func).parameters
        for name in names:
            assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
            assert params[name].default is inspect.Parameter.empty


def test_module_reads_no_wall_clock() -> None:
    assert wall_clock_calls(MODULE) == []


def test_module_builds_no_float() -> None:
    assert float_constructor_calls(MODULE) == []
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)


def test_module_imports_only_stdlib_and_pure_layers() -> None:
    forbidden = (
        "src.adapters",
        "src.backtest",
        "src.execution",
        "src.persistence",
        "src.paper",
        "src.approval",
        "src.reconcile",
        "src.data",
        "src.db",
        "src.ops",
        "src.analytics",
        "src.research",
        "binance*",
        "polars",
        "pandas",
        "numpy",
        "pydantic",
        "sqlalchemy",
        "httpx",
        "requests",
        "aiohttp",
    )
    assert forbidden_imports(MODULE, forbidden) == []


def test_module_holds_no_quote_asset_literal() -> None:
    source = MODULE.read_text(encoding="utf-8")
    for name in ("USDT", "USDC", "BUSD", "FDUSD"):
        assert name not in source


def test_module_numeric_literals_are_only_zero_one_and_the_bps_denominator() -> None:
    allowed = {0, 1, 10000}
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            if isinstance(node.value, bool):
                continue
            assert node.value in allowed, node.value
    assert margin_check.BASIS_POINT_DENOMINATOR == 10000
