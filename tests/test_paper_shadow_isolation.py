"""Plan 16-38: SHADOW isolation proof, SC6 (D-13 layers 1-3, D040, L-12, T-16-87, T-16-88).

SC6: in SHADOW the process loads no trade-capable API key and never constructs an order adapter,
and no code path from a SHADOW confirm reaches `execute_approved_plan` or any order endpoint.
Three independent layers prove it for the composed paper runtime and for the REV-03 rehearsal:

1. Structure (this section): the transitive `src` import closure of every SHADOW entrypoint has no
   module under `src.execution` and not the order adapter module `src.adapters.binance_usdm`,
   and no node of that closure names an order-surface method. Only the order module is banned,
   not the adapter package: market data lives in `src/adapters/binance_public.py` (plan 16-03).
2. Environment: both entrypoints refuse a `BINANCE_*` variable before building anything.
3. Behaviour: a full APPROVE then CONFIRM calls no spied order method.

Every layer has a negative control that proves the scan or the spy can fail.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The SHADOW entrypoints: the composed runtime, the SHADOW coordinator, the rehearsal path and
# the rehearsal operator script.
ENTRYPOINTS = (
    "src.paper.runtime",
    "src.paper.shadow_runtime",
    "src.paper.rehearsal",
    "scripts.shadow_rehearsal",
)
LOCAL_ROOTS = frozenset({"src", "scripts", "tests"})

BANNED_MODULE_PREFIX = "src.execution"
BANNED_ADAPTER_MODULE = "src.adapters.binance_usdm"

# The dependency-free helpers of `src.execution` that the backtest deliberately shares with the
# order path ("called, never re-derived", src/backtest/entry.py): the package barrel (re-exports
# `order_ids` only), the order id derivation, the pure limit/protective sizing arithmetic and the
# enablement value types. None of them imports an adapter, the manager or any I/O; the scan
# below still covers their source, so a helper that grew an order import would pull the manager
# into the closure and fail. Every OTHER module under `src.execution` (manager, fill_monitor,
# intent_recovery, intent_store, ...) is banned from the SHADOW closure. Adding a name here is a
# deliberate, reviewed act (T-16-88).
PURE_EXECUTION_HELPERS = frozenset(
    {
        "src.execution",
        "src.execution.order_ids",
        "src.execution.placement",
        "src.execution.enablement",
    }
)

# Order surface of src/adapters/binance_usdm.py (read 2026-10-08) and the execution entry
# `execute_approved_plan` (src/execution/manager.py).
ORDER_SURFACE = frozenset(
    {
        "place_entry",
        "place_algo_protective",
        "cancel_normal_order",
        "cancel_algo_order",
        "query_order_by_client",
        "query_algo_order_by_client",
        "snapshot_open_normal_orders",
        "snapshot_open_algo_orders",
        "snapshot_positions",
        "get_position_mode",
        "user_commission_rate",
        "execute_approved_plan",
    }
)


def _is_banned_module(name: str) -> bool:
    """An order-capable module: the adapter module or a `src.execution` module not allowlisted.

    A dotted name below an allowlisted module is a symbol (`src.execution.placement.quantize`),
    not a module, and is allowed with it.
    """
    if name == BANNED_ADAPTER_MODULE:
        return True
    if not (name == BANNED_MODULE_PREFIX or name.startswith(BANNED_MODULE_PREFIX + ".")):
        return False
    if name in PURE_EXECUTION_HELPERS:
        return False
    # A symbol below an allowlisted submodule (`src.execution.placement.quantize_price`); the
    # package itself is allowlisted by name only, so `src.execution.manager` stays banned.
    return not any(
        name.startswith(helper + ".")
        for helper in PURE_EXECUTION_HELPERS
        if helper != BANNED_MODULE_PREFIX
    )


def _module_file(name: str, root: Path) -> Path | None:
    """The source file of a local module under `root`, or None (third party or absent)."""
    parts = name.split(".")
    if parts[0] not in LOCAL_ROOTS:
        return None
    base = root.joinpath(*parts)
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None


def _parents(name: str) -> list[str]:
    parts = name.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _runtime_nodes(tree: ast.AST) -> Iterator[ast.AST]:
    """Every node that can execute: the body of `if TYPE_CHECKING:` is never run, so skipped.

    Lazy imports inside functions are kept (they run when the function is called).
    """
    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            stack.extend(node.orelse)
            continue
        stack.extend(ast.iter_child_nodes(node))


def _imported_names(path: Path, module: str) -> set[str]:
    """Every module name this file imports at run time (lazy imports included)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    is_package = path.name == "__init__.py"
    package = module if is_package else ".".join(module.split(".")[:-1])
    found: set[str] = set()
    for node in _runtime_nodes(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - (node.level - 1)]
                base = ".".join([*anchor, *([node.module] if node.module else [])])
            if base:
                found.add(base)
                # `from pkg import mod` may import a submodule: record the candidate too.
                found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def _closure(entry_modules: tuple[str, ...], root: Path = REPO_ROOT) -> set[str]:
    """The transitive set of local module names reachable by imports from the entrypoints.

    Pure `ast` scan: no scanned module is imported. A name that is imported but does not resolve
    to a file under `root` is still recorded (so a banned import cannot hide behind a missing
    file) but is not expanded.
    """
    seen: set[str] = set()
    queue = list(entry_modules)
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        # Importing a module also runs the `__init__` of every parent package.
        queue.extend(parent for parent in _parents(name) if parent not in seen)
        path = _module_file(name, root)
        if path is None:
            continue
        queue.extend(
            imported
            for imported in _imported_names(path, name)
            if imported.split(".")[0] in LOCAL_ROOTS and imported not in seen
        )
    return {name for name in seen if name.split(".")[0] in LOCAL_ROOTS}


def _scan_module(name: str, root: Path) -> list[str]:
    """Order-surface names used inside one module: attribute, name, import alias or string."""
    path = _module_file(name, root)
    if path is None:
        return []
    out: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        used: str | None = None
        if isinstance(node, ast.Attribute):
            used = node.attr
        elif isinstance(node, ast.Name):
            used = node.id
        elif isinstance(node, ast.alias):
            used = node.name.split(".")[-1]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            used = node.value  # getattr(adapter, "place_entry")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            used = node.name
        if used in ORDER_SURFACE:
            out.append(f"{name}: order-surface name {used!r} (line {getattr(node, 'lineno', 0)})")
    return out


def _violations(modules: set[str], root: Path = REPO_ROOT) -> list[str]:
    """Sorted violations of layer 1 over a closure: banned modules and order-surface names."""
    found: list[str] = []
    for name in sorted(modules):
        if _is_banned_module(name):
            found.append(f"{name}: banned module in the closure")
        found.extend(_scan_module(name, root))
    return sorted(found)


# --------------------------------------------------------------------------- #
# Task 1 (tracer): layer 1, the import closure of every SHADOW entrypoint.
# --------------------------------------------------------------------------- #


def test_the_closure_of_every_shadow_entrypoint_has_no_order_module() -> None:
    closure = _closure(ENTRYPOINTS)
    # The scan reaches the code it is meant to guard (a closure that stopped early would pass).
    for expected in (*ENTRYPOINTS, "src.paper.loop", "src.adapters.binance_public"):
        assert expected in closure, expected
    banned = sorted(name for name in closure if _is_banned_module(name))
    assert banned == []


def test_no_module_of_the_closure_names_an_order_surface_method() -> None:
    assert _violations(_closure(ENTRYPOINTS)) == []


def _seed(root: Path, files: dict[str, str]) -> None:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def test_negative_control_the_scan_reports_a_seeded_import_and_a_seeded_call(
    tmp_path: Path,
) -> None:
    _seed(
        tmp_path,
        {
            "src/__init__.py": "",
            "src/paper/__init__.py": "",
            "src/paper/runtime.py": (
                "from src.paper import helper\n"
                "def main():\n"
                "    import src.execution.manager as manager\n"
                "    return manager\n"
            ),
            "src/paper/helper.py": (
                "async def go(adapter):\n    return await adapter.place_entry(object())\n"
            ),
            "src/execution/__init__.py": "",
            "src/execution/manager.py": "async def execute_approved_plan(): ...\n",
        },
    )
    closure = _closure(("src.paper.runtime",), tmp_path)
    assert {"src.paper.helper", "src.execution.manager"} <= closure
    violations = _violations(closure, tmp_path)
    assert "src.execution.manager: banned module in the closure" in violations
    assert any("src.paper.helper: order-surface name 'place_entry'" in v for v in violations)
    assert any("order-surface name 'execute_approved_plan'" in v for v in violations)
    assert violations == sorted(violations)


def test_negative_control_only_the_pure_execution_helpers_are_allowed() -> None:
    for allowed in (*PURE_EXECUTION_HELPERS, "src.execution.placement.quantize_price"):
        assert not _is_banned_module(allowed), allowed
    for banned in (
        "src.execution.manager",
        "src.execution.manager.execute_approved_plan",
        "src.execution.fill_monitor",
        "src.execution.intent_recovery",
        "src.execution.intent_store",
        "src.execution.constraint_snapshot",
        "src.execution.placementx",
        "src.adapters.binance_usdm",
    ):
        assert _is_banned_module(banned), banned
    assert not _is_banned_module("src.adapters.binance_public")


def test_negative_control_the_order_adapter_module_is_banned_even_through_a_from_import(
    tmp_path: Path,
) -> None:
    _seed(
        tmp_path,
        {
            "src/__init__.py": "",
            "src/adapters/__init__.py": "",
            "src/adapters/binance_usdm.py": "class BinanceUsdmAdapter: ...\n",
            "src/adapters/binance_public.py": "class BinancePublicMarketData: ...\n",
            "src/paper/__init__.py": "",
            "src/paper/runtime.py": "from src.adapters import binance_usdm\n",
        },
    )
    closure = _closure(("src.paper.runtime",), tmp_path)
    assert "src.adapters.binance_usdm" in closure
    assert "src.adapters.binance_usdm: banned module in the closure" in _violations(
        closure, tmp_path
    )


def test_type_checking_imports_are_skipped_but_every_runtime_import_is_followed(
    tmp_path: Path,
) -> None:
    _seed(
        tmp_path,
        {
            "src/__init__.py": "",
            "src/execution/__init__.py": "",
            "src/execution/manager.py": "",
            "src/paper/__init__.py": "",
            "src/paper/typed.py": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    from src.execution import manager\n"
            ),
            "src/paper/lazy.py": "def f():\n    from src.execution import manager\n",
            "src/paper/branch.py": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    pass\n"
                "else:\n"
                "    import src.execution.manager\n"
            ),
        },
    )
    assert "src.execution.manager" not in _closure(("src.paper.typed",), tmp_path)
    assert "src.execution.manager" in _closure(("src.paper.lazy",), tmp_path)
    assert "src.execution.manager" in _closure(("src.paper.branch",), tmp_path)


def test_an_allowed_tree_reports_no_violation_and_market_data_is_not_banned(
    tmp_path: Path,
) -> None:
    _seed(
        tmp_path,
        {
            "src/__init__.py": "",
            "src/adapters/__init__.py": "",
            "src/adapters/binance_public.py": "class BinancePublicMarketData: ...\n",
            "src/paper/__init__.py": "",
            "src/paper/runtime.py": (
                "from src.adapters.binance_public import BinancePublicMarketData\n"
            ),
        },
    )
    closure = _closure(("src.paper.runtime",), tmp_path)
    assert "src.adapters.binance_public" in closure
    assert _violations(closure, tmp_path) == []
