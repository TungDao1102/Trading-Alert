"""Decimal-only static guard, extended scope (Phase 3, plan 03-05).

Per D-12: no binary floating-point constructor call may exist on the
domain, mapper, or registry path. Lifts the AST walker verbatim from
the metadata suite (tests/test_metadata.py) and extends the scanned
file list to every src/domain module plus the mapper and registry
modules. Future phases extend by file list only.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Every module on the domain/mapper/registry path (D-12). Extend this
# list only — the walker stays project-agnostic.
SCANNED_FILES = (
    "src/domain/__init__.py",
    "src/domain/approval.py",
    "src/domain/canonical.py",
    "src/domain/enums.py",
    "src/domain/fill.py",
    "src/domain/ids.py",
    "src/domain/journal.py",
    "src/domain/order.py",
    "src/domain/position.py",
    "src/domain/registry.py",
    "src/domain/signal.py",
    "src/domain/trade_plan.py",
    "src/db/mappers.py",
    # Phase 4 plan 04-01 — pure core (D-10).
    "src/core/__init__.py",
    "src/core/types.py",
    "src/core/features.py",
    "src/core/strategy.py",
    "src/core/planner.py",
)


def _find_float_calls(src: str) -> list[tuple[int, str]]:
    """AST-walk source and return `(line_no, line_text)` for float shapes.

    Flags `float(...)` calls, float literals (`0.5`), `Decimal(<float
    literal>)` shapes (silent binary-noise constructors), and numpy
    floating-type uses (`np.float64`). TOML-sourced floats are the
    known exception: they never appear as literals on this path —
    `_normalize_params` converts them at the registry boundary.
    """
    found: dict[tuple[int, str], None] = {}
    lines = src.splitlines()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "float":
                found[(node.lineno, lines[node.lineno - 1].strip())] = None
            elif (
                isinstance(func, ast.Name)
                and func.id == "Decimal"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, float)
            ):
                found[(node.lineno, lines[node.lineno - 1].strip())] = None
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, float):
                found[(node.lineno, lines[node.lineno - 1].strip())] = None
        elif isinstance(node, ast.Attribute):
            if node.attr in {"float16", "float32", "float64", "floating"}:
                found[(node.lineno, lines[node.lineno - 1].strip())] = None
    return sorted(found)


def test_domain_mapper_registry_path_has_no_float_call() -> None:
    """Beh. 1: zero float shapes across the scanned list."""
    repo_root = Path(__file__).resolve().parent.parent
    offenders: dict[str, list[tuple[int, str]]] = {}
    for rel in SCANNED_FILES:
        path = repo_root / rel
        assert path.is_file(), f"guard file list stale — missing: {rel}"
        found = _find_float_calls(path.read_text(encoding="utf-8"))
        if found:
            offenders[rel] = found
    assert not offenders, (
        "Decimal-only invariant violated (D-12) — float shapes "
        f"found: {offenders}"
    )


def test_float_guard_catches_literals_and_decimal_float() -> None:
    """Beh. 2: the walker flags literals and Decimal(float) (WR-10)."""
    assert _find_float_calls("x = 0.5\n") != []
    assert _find_float_calls("from decimal import Decimal\nx = Decimal(0.5)\n") != []
    assert _find_float_calls('x = Decimal("0.5")\n') == []
    assert _find_float_calls("x = 1\n") == []
