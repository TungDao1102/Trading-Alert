"""Shared pinned-precision Decimal helpers (Phase 4 review fix WR-16).

Per D-10: every arithmetic op in the pure core runs inside a pinned
`localcontext(prec=28)` so identical inputs produce byte-identical
outputs regardless of the ambient context. These helpers were
previously copy-pasted in `features.py`, `strategy.py`, and
`planner.py`; the copies drifted (strategy's detector block used
prec-50/raw ops — review CR-04). Single source of truth: every future
precision change lands here once.

Construction guards (`_require_decimal` and friends) stay layer-local
in `types.py` — only the arithmetic precision is shared.
"""

from __future__ import annotations

from decimal import Decimal, localcontext

_PREC = 28


def _q(x: Decimal | int | str) -> Decimal:
    """Build a Decimal from a string/int (never from a float)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, str):
        return Decimal(x)
    raise TypeError(f"_q: unsupported type {type(x).__name__}")


def _div(a: Decimal, b: Decimal) -> Decimal:
    """Divide two Decimals under a pinned local context (D-10)."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return a / b


def _mul(a: Decimal, b: Decimal) -> Decimal:
    """Multiply two Decimals under a pinned local context."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return a * b


def _add(a: Decimal, b: Decimal) -> Decimal:
    """Add two Decimals under a pinned local context."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return a + b


def _sub(a: Decimal, b: Decimal) -> Decimal:
    """Subtract two Decimals under a pinned local context."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return a - b


__all__ = ["_PREC", "_q", "_div", "_mul", "_add", "_sub"]
