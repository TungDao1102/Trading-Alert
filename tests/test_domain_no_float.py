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
    "src/domain/rationale.py",
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
    "src/core/pivots.py",
    # Phase 5 plan 05-01 — pure risk engine (D-05).
    "src/risk/__init__.py",
    "src/risk/types.py",
    "src/risk/sizing.py",
    "src/risk/quantization.py",
    "src/risk/gating.py",
    # Phase 5 plan 05-02 — portfolio gates (D-03/D-04).
    "src/risk/portfolio.py",
    # Phase 14 plan 14-01 — the single R-denominator function (D-20).
    "src/risk/realized_risk.py",
    # Phase 21 (D-04): pure live account modules.
    "src/risk/live_equity.py",
    "src/risk/daily_loss.py",
    "src/risk/reservations.py",
    # Phase 22 (D-08): pure live margin modules.
    "src/risk/margin_check.py",
    "src/risk/liquidation.py",
    # Phase 23 plan 23-02 (D-13): the money block built once from the risk pipeline output.
    "src/risk/money_at_stake.py",
    # Phase 6 plan 06-03 — pure backtest package (D-05).
    "src/backtest/__init__.py",
    "src/backtest/simulator.py",
    "src/backtest/costs.py",
    "src/backtest/experiment.py",
    "src/backtest/report.py",
    # Phase 7.1 plan 07.1-01 — registry↔cost binding helper (D-05 purity).
    "src/backtest/binding.py",
    # Phase 7 plan 07-01: the paper WS adapter; src/paper/*.py and src/research/*.py are
    # scanned by glob (SCANNED_GLOBS below, Phase 16 plan 16-10).
    "src/adapters/paper_ws.py",
    # Phase 10 - pure analytics core (D-01/D-05 purity). The CLI edge (cli.py) and the two
    # analytics adapters are float/clock-guarded by tests/test_analytics_edge_guards.py, which
    # also fails if a pure module is missing from this list.
    "src/analytics/__init__.py",
    "src/analytics/approval_delay.py",
    "src/analytics/clock.py",
    "src/analytics/core_metrics.py",
    "src/analytics/excursion.py",
    "src/analytics/family.py",
    "src/analytics/gates.py",
    "src/analytics/inputs.py",
    "src/analytics/killgate.py",
    "src/analytics/killgate_guard.py",
    "src/analytics/latency.py",
    "src/analytics/lifecycle.py",
    "src/analytics/live_outcomes.py",
    "src/analytics/no_trade.py",
    "src/analytics/provenance.py",
    "src/analytics/render.py",
    "src/analytics/render_common.py",
    "src/analytics/render_killgate.py",
    "src/analytics/render_metrics.py",
    "src/analytics/render_sidecar.py",
    "src/analytics/report.py",
    "src/analytics/slices.py",
    "src/analytics/stats.py",
    "src/analytics/types.py",
    "src/analytics/universe.py",
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


# Phase 14 plan 14-01: packages scanned by glob, so a module added by a later plan can
# never be silently skipped by the explicit list above (registration trap, D-26).
SCANNED_GLOBS = ("src/backtest/*.py", "src/paper/*.py", "src/research/*.py")

# Modules matched by a glob above that are NOT float-scanned, each with a one-line reason.
# Adding an entry needs a reason; weakening the scan instead is not allowed (Phase 16,
# plan 16-10). Every other src/paper and src/research module passes the full scan.
FLOAT_SCAN_EXCLUDED: dict[str, str] = {
    "src/paper/shadow.py": (
        "tenacity retry-wait arithmetic in seconds (float is the tenacity wait type; "
        "no price, quantity or risk value is computed with it)"
    ),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _glob_scanned_files() -> list[str]:
    """Return every file matched by `SCANNED_GLOBS` as sorted repo-relative posix paths."""
    root = _repo_root()
    matched: set[str] = set()
    for pattern in SCANNED_GLOBS:
        matched.update(
            rel
            for rel in (p.relative_to(root).as_posix() for p in root.glob(pattern))
            if rel not in FLOAT_SCAN_EXCLUDED
        )
    return sorted(matched)


def _all_scanned_files() -> list[str]:
    """The explicit list first (kept in order), then any glob match not already listed."""
    extra = [rel for rel in _glob_scanned_files() if rel not in SCANNED_FILES]
    return [*SCANNED_FILES, *extra]


def test_domain_mapper_registry_path_has_no_float_call() -> None:
    """Beh. 1: zero float shapes across the scanned list and the scanned globs."""
    repo_root = _repo_root()
    offenders: dict[str, list[tuple[int, str]]] = {}
    for rel in _all_scanned_files():
        path = repo_root / rel
        assert path.is_file(), f"guard file list stale — missing: {rel}"
        found = _find_float_calls(path.read_text(encoding="utf-8"))
        if found:
            offenders[rel] = found
    assert not offenders, (
        f"Decimal-only invariant violated (D-12) — float shapes found: {offenders}"
    )


def test_every_backtest_module_is_scanned_by_the_float_guard() -> None:
    """Every src/backtest/*.py file, including ones later plans add, is float-scanned."""
    backtest_files = sorted(
        p.relative_to(_repo_root()).as_posix() for p in (_repo_root() / "src/backtest").glob("*.py")
    )
    assert {
        "src/backtest/semantics.py",
        "src/backtest/series.py",
        "src/backtest/entry.py",
        "src/backtest/exits.py",
        "src/backtest/lifecycle.py",
        "src/backtest/records.py",
        "src/backtest/validator.py",
    } <= set(backtest_files)
    scanned = set(_all_scanned_files())
    missing = [rel for rel in backtest_files if rel not in scanned]
    assert not missing, f"src/backtest modules not covered by the float guard: {missing}"


def test_float_guard_catches_literals_and_decimal_float() -> None:
    """Beh. 2: the walker flags literals and Decimal(float) (WR-10)."""
    assert _find_float_calls("x = 0.5\n") != []
    assert _find_float_calls("from decimal import Decimal\nx = Decimal(0.5)\n") != []
    assert _find_float_calls('x = Decimal("0.5")\n') == []
    assert _find_float_calls("x = 1\n") == []


def test_every_paper_and_research_module_is_scanned_by_the_float_guard() -> None:
    """Every src/paper and src/research module, including ones later plans add, is scanned.

    The paper and research packages are scanned by glob (Phase 16, plan 16-10), so a module
    a later Phase 16 plan adds is covered without anyone remembering to list it. A module
    is skipped only through `FLOAT_SCAN_EXCLUDED`, each entry with a one-line reason.
    """
    root = _repo_root()
    modules = sorted(
        p.relative_to(root).as_posix()
        for pattern in ("src/paper/*.py", "src/research/*.py")
        for p in root.glob(pattern)
    )
    assert {"src/paper/bars.py", "src/paper/loop.py", "src/paper/surface.py"} <= set(modules)
    scanned = set(_all_scanned_files())
    missing = [rel for rel in modules if rel not in scanned and rel not in FLOAT_SCAN_EXCLUDED]
    assert not missing, f"paper/research modules not covered by the float guard: {missing}"
    assert "src/adapters/paper_ws.py" in scanned


def test_float_scan_exclusions_are_justified_and_exist() -> None:
    """An exclusion needs a non-empty reason and must name a real file (no stale entries)."""
    root = _repo_root()
    for rel, reason in FLOAT_SCAN_EXCLUDED.items():
        assert reason.strip(), f"{rel}: an exclusion needs a one-line reason"
        assert (root / rel).is_file(), f"{rel}: excluded file does not exist"
        assert rel not in SCANNED_FILES
