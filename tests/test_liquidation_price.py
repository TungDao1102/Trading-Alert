"""Pure isolated liquidation guard (Phase 22, plan 22-07; D-08, D-09, D-10, criterion 2).

Oracles are the golden values of 22-RESEARCH 5.1, computed once with Decimal at precision 40 on the
recorded Demo bracket table (demo-observed, not mainnet). The table itself is loaded from the
generated fixture through `tests/support/phase22_fixtures.py`, never typed. Equality of these
numbers with the exchange's own isolated `liquidationPrice` is NOT claimed.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from src.risk import liquidation
from src.risk.liquidation import (
    LEVERAGE_ABOVE_BRACKET,
    LIQUIDATION_INPUT_UNAVAILABLE,
    LIQUIDATION_OK,
    LIQUIDATION_TOO_CLOSE,
    NOTIONAL_ABOVE_MAX,
    Bracket,
    LiquidationVerdict,
    brackets_are_fresh,
    liquidation_beyond_stop,
    liquidation_price,
    liquidation_verdict,
)

from tests.support.ast_guards import float_constructor_calls, forbidden_imports, wall_clock_calls
from tests.support.phase22_fixtures import demo_brackets, load_leverage_brackets

MODULE = Path(liquidation.__file__)
DP12 = Decimal("1E-12")
ENTRY = Decimal("80000")

G3_ENTRY_TIER = Decimal("64254.606365159129")
G5_ENTRY_TIER = Decimal("64249.820531227566")
G4 = Decimal("95588.723051409619")
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


# --- tier consistency: G3, G4, G5 and the exact edge -------------------------------------------


def test_g3_long_uses_the_bracket_of_the_liquidation_notional_not_of_the_entry() -> None:
    result = _q12(_lp("LONG", "0.75"))
    assert result == G1
    assert result != G3_ENTRY_TIER  # Pitfall 1: the entry tier is closer to the entry by 2.42
    assert G1 - G3_ENTRY_TIER > Decimal("2.4")


def test_g5_long_uses_bracket_one() -> None:
    result = _q12(_lp("LONG", "0.7"))
    assert result == G1
    assert result != G5_ENTRY_TIER


def test_g4_short_uses_bracket_two() -> None:
    assert _q12(_lp("SHORT", "0.75")) == G4


def test_exact_edge_returns_the_common_value_and_is_stable() -> None:
    # 0.778125 x LP is exactly 50000: bracket 1 and bracket 2 coincide there.
    first = _lp("LONG", "0.778125")
    second = _lp("LONG", "0.7781250")
    assert first is not None
    assert _q12(first) == G1
    assert first == second


def test_continuity_of_the_demo_table_at_every_bracket_edge() -> None:
    # A property of the recorded Demo table, not a rule of the module.
    brackets = demo_brackets()
    assert len(brackets) == 10
    for lower, upper in zip(brackets, brackets[1:], strict=False):
        edge = Fraction(lower.notional_cap)
        assert edge == Fraction(upper.notional_floor)
        below = edge * Fraction(lower.maint_margin_ratio) - Fraction(lower.cum)
        above = edge * Fraction(upper.maint_margin_ratio) - Fraction(upper.cum)
        assert below == above


# --- fail closed: bracket list shape -----------------------------------------------------------


def _verdict_with(brackets: list[Bracket]) -> LiquidationVerdict:
    return _verdict("LONG", "66000", brackets=brackets)


def _rebuilt(source: Bracket, **overrides: Any) -> Bracket:
    fields: dict[str, Any] = {
        "bracket": source.bracket,
        "initial_leverage": source.initial_leverage,
        "notional_floor": source.notional_floor,
        "notional_cap": source.notional_cap,
        "maint_margin_ratio": source.maint_margin_ratio,
        "cum": source.cum,
    }
    fields.update(overrides)
    return Bracket(**fields)


def _shape_cases() -> dict[str, list[Bracket]]:
    full = demo_brackets()
    first, second = full[0], full[1]
    gap = _rebuilt(second, notional_floor=second.notional_floor + 1)
    overlap = _rebuilt(second, notional_floor=second.notional_floor - 1)
    not_zero = _rebuilt(first, notional_floor=Decimal(1))
    return {
        "empty": [],
        "gap": [first, gap, *full[2:]],
        "overlap": [first, overlap, *full[2:]],
        "first_floor_not_zero": [not_zero, *full[1:]],
        "unsorted": [second, first, *full[2:]],
        "duplicate_number": [first, first, *full[2:]],
    }


@pytest.mark.parametrize("case", sorted(_shape_cases()))
def test_malformed_bracket_lists_are_unavailable(case: str) -> None:
    brackets = _shape_cases()[case]
    verdict = _verdict_with(brackets)
    assert verdict.ok is False
    assert verdict.reason_code == LIQUIDATION_INPUT_UNAVAILABLE
    assert verdict.liquidation_price is None
    result = liquidation_price(
        side="LONG",
        entry_price=ENTRY,
        quantity=Decimal("0.01"),
        leverage=5,
        brackets=brackets,
    )
    assert result is None


def test_a_non_bracket_element_is_a_programming_error() -> None:
    with pytest.raises(TypeError):
        _verdict_with([object()])  # type: ignore[list-item]


# --- fail closed: notional and leverage --------------------------------------------------------


def test_entry_notional_above_the_top_cap_is_refused() -> None:
    # 80000 x 6250.0001 = 500000008 > 500000000
    verdict = _verdict("LONG", "66000", quantity=Decimal("6250.0001"))
    assert verdict.reason_code == NOTIONAL_ABOVE_MAX
    assert verdict.ok is False
    assert verdict.liquidation_price is None


def test_leverage_above_the_entry_bracket_is_refused() -> None:
    # entry notional 120000000 (80000 x 1500) lies on the edge of brackets 7 (4x) and 8 (3x).
    verdict = _verdict("LONG", "66000", quantity=Decimal("1500"))
    assert verdict.reason_code == LEVERAGE_ABOVE_BRACKET
    assert verdict.ok is False
    # and one tier up (bracket 8 alone, 3x) is refused as well
    assert _verdict("LONG", "66000", quantity=Decimal("1600")).reason_code == LEVERAGE_ABOVE_BRACKET


def test_leverage_equal_to_the_bracket_maximum_is_not_a_leverage_refusal() -> None:
    # bracket 6 allows 5x: 5x at a 60 million entry notional is not a leverage refusal.
    verdict = _verdict("LONG", "66000", quantity=Decimal("750"))
    assert verdict.reason_code != LEVERAGE_ABOVE_BRACKET


def test_no_self_consistent_tier_is_refused_with_the_notional_code() -> None:
    # A table that is not continuous at its edge: no tier contains its own Q x LP.
    brackets = [
        Bracket(1, 10, Decimal(0), Decimal(500), Decimal("0.5"), Decimal(0)),
        Bracket(2, 10, Decimal(500), Decimal(2000), Decimal("0.1"), Decimal(300)),
    ]
    verdict = liquidation_verdict(
        side="LONG",
        entry_price=Decimal("1000"),
        quantity=Decimal("1"),
        leverage=2,
        brackets=brackets,
        stop_price=Decimal("900"),
        buffer_bps=100,
    )
    assert verdict.reason_code == NOTIONAL_ABOVE_MAX


def test_a_non_positive_liquidation_price_is_unavailable() -> None:
    brackets = [Bracket(1, 10, Decimal(0), Decimal(1000000), Decimal("0.1"), Decimal(0))]
    verdict = liquidation_verdict(
        side="LONG",
        entry_price=Decimal("100"),
        quantity=Decimal("1"),
        leverage=1,
        brackets=brackets,
        stop_price=Decimal("90"),
        buffer_bps=100,
    )
    assert verdict.reason_code == LIQUIDATION_INPUT_UNAVAILABLE
    assert verdict.liquidation_price is None


def test_inverted_stop_geometry_is_unavailable() -> None:
    assert _verdict("LONG", "80000").reason_code == LIQUIDATION_INPUT_UNAVAILABLE
    assert _verdict("LONG", "81000").reason_code == LIQUIDATION_INPUT_UNAVAILABLE
    assert _verdict("SHORT", "80000").reason_code == LIQUIDATION_INPUT_UNAVAILABLE
    assert _verdict("SHORT", "79000").reason_code == LIQUIDATION_INPUT_UNAVAILABLE


# --- bracket age -------------------------------------------------------------------------------

T = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
MAX_AGE = timedelta(minutes=5)


def test_equal_age_passes_one_microsecond_more_is_stale() -> None:
    assert brackets_are_fresh(observed_at_utc=T, now_utc=T + MAX_AGE, max_age=MAX_AGE) is True
    stale_at = T + MAX_AGE + timedelta(microseconds=1)
    assert brackets_are_fresh(observed_at_utc=T, now_utc=stale_at, max_age=MAX_AGE) is False


def test_a_future_observation_is_stale() -> None:
    before = T - timedelta(microseconds=1)
    assert brackets_are_fresh(observed_at_utc=T, now_utc=before, max_age=MAX_AGE) is False
    assert brackets_are_fresh(observed_at_utc=T, now_utc=T, max_age=MAX_AGE) is True


NAIVE = datetime(2026, 10, 24, 12, 0, 0)  # noqa: DTZ001 - the naive value is the test input


@pytest.mark.parametrize(
    "overrides",
    [
        {"observed_at_utc": NAIVE},
        {"now_utc": NAIVE},
        {"now_utc": datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone(timedelta(hours=7)))},
        {"max_age": timedelta(0)},
        {"max_age": timedelta(seconds=-1)},
        {"max_age": 300},
        {"observed_at_utc": "2026-10-24"},
    ],
)
def test_freshness_argument_errors_raise(overrides: dict[str, Any]) -> None:
    kwargs: dict[str, Any] = {"observed_at_utc": T, "now_utc": T, "max_age": MAX_AGE}
    kwargs.update(overrides)
    with pytest.raises((TypeError, ValueError)):
        brackets_are_fresh(**kwargs)


# --- purity ------------------------------------------------------------------------------------


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
        "src.persistence",
        "src.execution",
        "src.ops",
        "src.paper",
        "src.backtest",
        "src.approval",
        "src.reconcile",
        "src.data",
        "src.db",
        "sqlalchemy",
        "binance*",
        "polars",
        "pandas",
        "numpy",
        "httpx",
    )
    assert forbidden_imports(MODULE, forbidden) == []


def test_module_holds_no_quote_asset_literal() -> None:
    source = MODULE.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value != "USDT"
    for name in ("USDT", "USDC", "BUSD", "FDUSD"):
        assert name not in source


def test_module_numeric_literals_are_only_zero_one_and_the_bps_denominator() -> None:
    allowed = {0, 1, 10000}
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            if isinstance(node.value, bool):
                continue
            assert node.value in allowed, node.value
    assert liquidation.BASIS_POINT_DENOMINATOR == 10000


def test_module_names_no_order_surface_method() -> None:
    order_surface = {"place_entry", "place_stop", "cancel_order", "change_initial_leverage"}
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in order_surface
