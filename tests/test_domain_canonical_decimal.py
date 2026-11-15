"""Canonical decimal text and storage-scale quantization (Phase 17, plan 17-05, D-12).

`canonical_decimal_text` is the D047 helper moved from `src/backtest/costs.py`
(behavior unchanged). `quantize_for_storage` rounds a Decimal to the
NUMERIC(38,18) scale with ROUND_HALF_EVEN so a plan value written to
PostgreSQL reads back identically (F-410).
"""

from __future__ import annotations

from decimal import Decimal, localcontext

import pytest
from src.domain.canonical import (
    STORAGE_DECIMAL_PLACES,
    canonical_decimal_text,
    quantize_for_storage,
)

# --------------------------------------------------------------------------- #
# canonical_decimal_text
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spelling", ["1", "1.0", "1.00", "1.000000000000000000"])
def test_equivalent_spellings_render_one_text(spelling: str) -> None:
    assert canonical_decimal_text(Decimal(spelling)) == "1"


def test_trailing_zeros_stripped_fraction_kept() -> None:
    assert canonical_decimal_text(Decimal("0.00020")) == "0.0002"


def test_integer_never_uses_exponent_form() -> None:
    assert canonical_decimal_text(Decimal("100")) == "100"
    assert canonical_decimal_text(Decimal("1E+2")) == "100"
    assert canonical_decimal_text(Decimal("50000.000000000000000000")) == "50000"


@pytest.mark.parametrize("zero", ["0", "0.0", "-0", "-0.000", "0E-18"])
def test_zero_in_any_spelling_is_zero(zero: str) -> None:
    assert canonical_decimal_text(Decimal(zero)) == "0"


def test_negative_value_keeps_sign() -> None:
    assert canonical_decimal_text(Decimal("-1.50")) == "-1.5"


@pytest.mark.parametrize("bad", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_non_finite_raises_value_error(bad: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_decimal_text(Decimal(bad))


def test_text_is_independent_of_ambient_context_precision() -> None:
    value = Decimal("123456789012345678901234567890.123456789012345678")
    with localcontext() as ctx:
        ctx.prec = 5
        low = canonical_decimal_text(value)
    with localcontext() as ctx:
        ctx.prec = 80
        high = canonical_decimal_text(value)
    assert low == high == "123456789012345678901234567890.123456789012345678"


# --------------------------------------------------------------------------- #
# quantize_for_storage
# --------------------------------------------------------------------------- #


def test_storage_scale_constant() -> None:
    assert STORAGE_DECIMAL_PLACES == 18


def test_quantize_real_planner_value() -> None:
    q = quantize_for_storage(Decimal("50976.11812218609640044949190"))
    assert q == Decimal("50976.118122186096400449")
    assert q.as_tuple().exponent == -18


def test_quantize_pads_to_scale_18() -> None:
    q = quantize_for_storage(Decimal("50000"))
    assert str(q) == "50000.000000000000000000"


def test_half_even_tie_with_even_18th_digit_stays() -> None:
    # 18th digit is 2 (even), 19th digit is 5 with nothing after: tie -> stays.
    assert quantize_for_storage(Decimal("1.0000000000000000025")) == Decimal("1.000000000000000002")


def test_half_even_tie_with_odd_18th_digit_rounds_up() -> None:
    # 18th digit is 3 (odd), tie -> rounds up to 4.
    assert quantize_for_storage(Decimal("1.0000000000000000035")) == Decimal("1.000000000000000004")


def test_above_tie_rounds_up_below_tie_rounds_down() -> None:
    assert quantize_for_storage(Decimal("1.00000000000000000251")) == Decimal(
        "1.000000000000000003"
    )
    assert quantize_for_storage(Decimal("1.00000000000000000249")) == Decimal(
        "1.000000000000000002"
    )


def test_large_integer_part_does_not_overflow_context() -> None:
    value = Decimal("123456789012345678901.1234567890123456785")  # 21 integer digits
    q = quantize_for_storage(value)
    assert q == Decimal("123456789012345678901.123456789012345678")


def test_quantize_ignores_ambient_context_precision() -> None:
    with localcontext() as ctx:
        ctx.prec = 5
        q = quantize_for_storage(Decimal("50976.11812218609640044949190"))
    assert q == Decimal("50976.118122186096400449")


def test_quantize_is_idempotent() -> None:
    once = quantize_for_storage(Decimal("0.123456789012345678901234"))
    assert quantize_for_storage(once) == once
    assert quantize_for_storage(once).as_tuple() == once.as_tuple()


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_quantize_non_finite_raises_value_error(bad: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        quantize_for_storage(Decimal(bad))


def test_quantize_result_exceeding_working_precision_raises_value_error() -> None:
    # 45 integer digits + 18 fractional digits exceed the 60-digit working
    # precision: fail closed with ValueError, never a wrong value.
    with pytest.raises(ValueError):
        quantize_for_storage(Decimal("1" + "0" * 44))


# --------------------------------------------------------------------------- #
# IN-05 (plan 24-15): the finite-exponent invariant is an explicit raise, not an assert, so
# it still holds under `python -O`.
# --------------------------------------------------------------------------- #


class _BrokenExponent(Decimal):
    """A finite non-zero Decimal whose digit tuple reports a non-int exponent."""

    def as_tuple(self) -> tuple[int, tuple[int, ...], str]:  # type: ignore[override]
        return (0, (1,), "n")


def test_a_non_integer_exponent_raises_runtime_error_naming_the_invariant() -> None:
    with pytest.raises(RuntimeError, match="finite Decimal exponent"):
        canonical_decimal_text(_BrokenExponent("1"))


def test_canonical_module_has_no_runtime_assert() -> None:
    import ast
    from pathlib import Path

    import src.domain.canonical as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    assert [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Assert)] == []
