"""Pure isolated liquidation guard (Phase 22, plan 22-07; D-08, D-09, D-10, criterion 2).

Oracles are the golden values of 22-RESEARCH 5.1, computed once with Decimal at precision 40 on the
recorded Demo bracket table (demo-observed, not mainnet). The table itself is loaded from the
generated fixture through `tests/support/phase22_fixtures.py`, never typed. Equality of these
numbers with the exchange's own isolated `liquidationPrice` is NOT claimed.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

import pytest
from src.risk.liquidation import (
    LIQUIDATION_OK,
    LIQUIDATION_TOO_CLOSE,
    Bracket,
    LiquidationVerdict,
    liquidation_beyond_stop,
    liquidation_price,
    liquidation_verdict,
)

from tests.support.phase22_fixtures import demo_brackets, load_leverage_brackets

DP12 = Decimal("1E-12")
ENTRY = Decimal("80000")

G1 = Decimal("64257.028112449799")
G2 = Decimal("95617.529880478088")


def _lp(side: str, quantity: str, leverage: int = 5) -> Decimal | None:
    return liquidation_price(
        side=side,
        entry_price=ENTRY,
        quantity=Decimal(quantity),
        leverage=leverage,
        brackets=demo_brackets(),
    )


def _q12(value: Decimal | None) -> Decimal:
    assert value is not None
    return value.quantize(DP12)


# --- the fixture loader -------------------------------------------------------------------------


def test_demo_brackets_come_from_the_generated_fixture() -> None:
    brackets = demo_brackets()
    raw = load_leverage_brackets()[0]["brackets"]
    assert len(brackets) == len(raw) == 10
    assert brackets[0].maint_margin_ratio == Decimal("0.004")
    assert brackets[0].initial_leverage == 125
    assert brackets[0].notional_floor == Decimal(0)
    assert brackets[1].cum == Decimal("50")
    assert all(isinstance(b.maint_margin_ratio, Decimal) for b in brackets)


# --- goldens G1 and G2 (the tracer) --------------------------------------------------------------


def test_g1_long_small_quantity() -> None:
    result = _lp("LONG", "0.01")
    assert isinstance(result, Decimal)
    assert _q12(result) == G1


def test_g2_short_small_quantity() -> None:
    result = _lp("SHORT", "0.01")
    assert isinstance(result, Decimal)
    assert _q12(result) == G2


# --- the strict buffer predicate -----------------------------------------------------------------


def _beyond(side: str, lp: str, stop: str) -> bool:
    return liquidation_beyond_stop(
        side=side,
        liquidation_price=Decimal(lp),
        stop_price=Decimal(stop),
        entry_price=ENTRY,
        buffer_bps=100,
    )


def test_long_boundary_is_strict() -> None:
    assert _beyond("LONG", "64200", "65000") is False
    assert _beyond("LONG", "64199.999999", "65000") is True
    assert _beyond("LONG", "65100", "65000") is False


def test_short_boundary_is_strict() -> None:
    assert _beyond("SHORT", "90800", "90000") is False
    assert _beyond("SHORT", "90800.000001", "90000") is True
    assert _beyond("SHORT", "89000", "90000") is False


# --- the verdict ---------------------------------------------------------------------------------


def _verdict(side: str = "LONG", stop: str = "66000", **overrides: Any) -> LiquidationVerdict:
    kwargs: dict[str, Any] = {
        "side": side,
        "entry_price": ENTRY,
        "quantity": Decimal("0.01"),
        "leverage": 5,
        "brackets": demo_brackets(),
        "stop_price": Decimal(stop),
        "buffer_bps": 100,
    }
    kwargs.update(overrides)
    return liquidation_verdict(**kwargs)


def test_verdict_ok_when_the_stop_is_inside_the_liquidation_with_buffer() -> None:
    verdict = _verdict("LONG", "66000")
    assert verdict.ok is True
    assert verdict.reason_code == LIQUIDATION_OK == "OK"
    assert _q12(verdict.liquidation_price) == G1


def test_verdict_too_close_when_the_stop_minus_buffer_is_below_the_liquidation() -> None:
    verdict = _verdict("LONG", "65000")
    assert verdict.ok is False
    assert verdict.reason_code == LIQUIDATION_TOO_CLOSE == "LIQUIDATION_TOO_CLOSE"
    assert _q12(verdict.liquidation_price) == G1


def test_short_verdict_ok_and_too_close() -> None:
    assert _verdict("SHORT", "94000").ok is True
    too_close = _verdict("SHORT", "95000")
    assert too_close.ok is False
    assert too_close.reason_code == LIQUIDATION_TOO_CLOSE


def test_the_verdict_decides_on_the_exact_value_not_on_a_rounded_decimal() -> None:
    # Exact G1 is 64257.02811244979919678...; the buffer is exactly 800 (80000 x 100 / 10000).
    # A context of six digits would round the informational Decimal to 64257.0, yet the decision
    # still sits on the 13th decimal place.
    with localcontext() as ctx:
        ctx.prec = 6
        above = _verdict("LONG", "65057.0281124498")
        below = _verdict("LONG", "65057.0281124497")
    assert above.ok is True
    assert below.ok is False
    assert below.reason_code == LIQUIDATION_TOO_CLOSE


@pytest.mark.parametrize(
    "overrides",
    [
        {"entry_price": 80000.0},
        {"entry_price": 80000},
        {"entry_price": True},
        {"quantity": 0.01},
        {"quantity": Decimal("0")},
        {"quantity": Decimal("-1")},
        {"entry_price": Decimal("0")},
        {"stop_price": Decimal("0")},
        {"stop_price": 66000.0},
        {"leverage": True},
        {"leverage": 5.0},
        {"leverage": Decimal(5)},
        {"leverage": 0},
        {"buffer_bps": True},
        {"buffer_bps": 100.0},
        {"buffer_bps": 0},
        {"side": "BUY"},
        {"side": None},
        {"entry_price": Decimal("NaN")},
        {"entry_price": Decimal("Infinity")},
    ],
)
def test_argument_errors_raise(overrides: dict[str, Any]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _verdict(**overrides)


def test_there_is_no_default_for_leverage_buffer_or_brackets() -> None:
    import inspect

    for func in (liquidation_price, liquidation_beyond_stop, liquidation_verdict):
        for name, param in inspect.signature(func).parameters.items():
            assert param.kind is inspect.Parameter.KEYWORD_ONLY, name
            assert param.default is inspect.Parameter.empty, name


# --- Bracket and verdict construction ------------------------------------------------------------


def _bracket(**overrides: Any) -> Bracket:
    kwargs: dict[str, Any] = {
        "bracket": 1,
        "initial_leverage": 10,
        "notional_floor": Decimal("0"),
        "notional_cap": Decimal("100"),
        "maint_margin_ratio": Decimal("0.01"),
        "cum": Decimal("0"),
    }
    kwargs.update(overrides)
    return Bracket(**kwargs)


@pytest.mark.parametrize(
    "overrides",
    [
        {"bracket": 0},
        {"bracket": True},
        {"initial_leverage": 0},
        {"initial_leverage": 1.5},
        {"notional_floor": Decimal("-1")},
        {"notional_floor": 0},
        {"notional_cap": Decimal("0")},
        {"notional_cap": Decimal("NaN")},
        {"maint_margin_ratio": Decimal("1")},
        {"maint_margin_ratio": Decimal("-0.1")},
        {"maint_margin_ratio": 0.01},
        {"cum": Decimal("-1")},
    ],
)
def test_bracket_rejects_invalid_fields(overrides: dict[str, Any]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _bracket(**overrides)


def test_liquidation_verdict_object_is_self_consistent() -> None:
    with pytest.raises(ValueError):
        LiquidationVerdict(True, "NOPE", Decimal("1"))
    with pytest.raises(ValueError):
        LiquidationVerdict(False, LIQUIDATION_OK, None)
    with pytest.raises(ValueError):
        LiquidationVerdict(True, LIQUIDATION_OK, None)
    with pytest.raises(TypeError):
        LiquidationVerdict(1, LIQUIDATION_OK, Decimal("1"))  # type: ignore[arg-type]
