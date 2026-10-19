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
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

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


# --------------------------------------------------------------------------- #
# Task 2: layer 2, a BINANCE_ variable refuses both entrypoints before anything is built.
# --------------------------------------------------------------------------- #

SECRET_VALUE = "isolation-secret-value-must-never-be-printed"
TRADE_NAMES = (
    "BINANCE_LIVE_API_KEY",
    "BINANCE_LIVE_API_SECRET",
    "BINANCE_DEMO_API_KEY",
    "BINANCE_DEMO_API_SECRET",
    "BINANCE_FOO",
)
EVIDENCE_NAME = "unused-evidence.json"


@pytest.fixture
def constructions(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record (and fail) the construction of every real adapter, bot or database engine."""
    import sqlalchemy
    import src.adapters.binance_public as binance_public
    import src.adapters.binance_usdm as binance_usdm
    import src.adapters.paper_ws as paper_ws
    import src.adapters.telegram_callbacks as telegram_callbacks
    import src.persistence.engine as persistence_engine
    from telegram.ext import ApplicationBuilder

    built: list[str] = []

    def recorder(label: str) -> Callable[..., Any]:
        def record(*args: Any, **kwargs: Any) -> Any:
            built.append(label)
            raise AssertionError(f"{label} was constructed")

        return record

    for owner, attribute, label in (
        (paper_ws.PaperWsAdapter, "__init__", "PaperWsAdapter"),
        (binance_public.BinancePublicMarketData, "__init__", "BinancePublicMarketData"),
        (binance_usdm.BinanceUsdmAdapter, "__init__", "BinanceUsdmAdapter"),
        (telegram_callbacks, "build_application", "build_application"),
        (ApplicationBuilder, "build", "telegram ApplicationBuilder.build"),
        (persistence_engine, "make_sync_engine", "make_sync_engine"),
        (persistence_engine, "create_engine", "persistence create_engine"),
        (sqlalchemy, "create_engine", "sqlalchemy.create_engine"),
    ):
        monkeypatch.setattr(owner, attribute, recorder(label))
    return built


def _runtime_entry(environ: dict[str, str]) -> int:
    from src.paper import runtime

    return runtime.main([], environ=environ)


def _rehearsal_entry(environ: dict[str, str]) -> int:
    """The live mode, because only the live mode could reach a bot, the network or a database."""
    import scripts.shadow_rehearsal as shadow_rehearsal

    return shadow_rehearsal.main(
        ["--live-telegram", "--i-am-the-operator", "--out", EVIDENCE_NAME],
        environ=environ,
    )


ENTRIES = {"runtime": _runtime_entry, "rehearsal": _rehearsal_entry}


@pytest.mark.parametrize("entry", sorted(ENTRIES))
@pytest.mark.parametrize("value", [SECRET_VALUE, ""], ids=["non-empty", "empty"])
@pytest.mark.parametrize("name", TRADE_NAMES)
def test_a_binance_variable_refuses_with_code_3_and_builds_nothing(
    entry: str,
    value: str,
    name: str,
    constructions: list[str],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)  # the evidence path is relative: nothing may land in the repo
    environ = {
        "PAPER_STRATEGY_ID": "trend-pullback",
        "PAPER_PARAMETER_SET_ID": "baseline-v3",
        "TELEGRAM_BOT_TOKEN": "123456:fake-token",
        "TELEGRAM_AUTHORIZED_CHAT_ID": "42",
        "DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:1/none",
        name: value,
    }

    code = ENTRIES[entry](environ)

    captured = capsys.readouterr()
    assert code == 3
    assert constructions == []
    assert name in captured.err
    assert SECRET_VALUE not in captured.out + captured.err + caplog.text
    assert not (tmp_path / EVIDENCE_NAME).exists()


@pytest.mark.parametrize("entry", sorted(ENTRIES))
def test_the_refusal_lists_names_only_and_every_present_name(
    entry: str,
    constructions: list[str],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    environ = {name: f"{SECRET_VALUE}-{index}" for index, name in enumerate(TRADE_NAMES)}

    code = ENTRIES[entry](environ)

    output = capsys.readouterr().err
    assert code == 3
    for name in TRADE_NAMES:
        assert name in output
    assert SECRET_VALUE not in output + caplog.text
    assert constructions == []


def test_negative_control_the_construction_spies_would_catch_an_adapter(
    constructions: list[str],
) -> None:
    import src.adapters.binance_public as binance_public
    import src.adapters.binance_usdm as binance_usdm
    import src.adapters.paper_ws as paper_ws

    for cls in (
        binance_public.BinancePublicMarketData,
        binance_usdm.BinanceUsdmAdapter,
        paper_ws.PaperWsAdapter,
    ):
        with pytest.raises(AssertionError, match="was constructed"):
            cls()
    assert constructions == ["BinancePublicMarketData", "BinanceUsdmAdapter", "PaperWsAdapter"]


def test_negative_control_without_a_trade_variable_the_entry_gets_past_the_refusal(
    constructions: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal above is caused by the variable: the same environment minus it is not refused."""
    code = _runtime_entry({"PAPER_STRATEGY_ID": "trend-pullback"})

    assert code != 3
    assert "trade-capable" not in capsys.readouterr().err


def test_the_dry_run_rehearsal_is_fakes_only_and_constructs_no_real_adapter(
    constructions: list[str], tmp_path: Path
) -> None:
    """The dry run builds fakes only (it refuses BINANCE_ names too since 16-53, see the
    rehearsal test file; here the environment is clean)."""
    import scripts.shadow_rehearsal as shadow_rehearsal

    out = tmp_path / "dry.json"

    code = shadow_rehearsal.main(["--dry-run", "--out", str(out)], environ={})

    assert code == 0
    assert out.is_file()
    assert constructions == []


# --------------------------------------------------------------------------- #
# Task 3: layer 3, behaviour spies over a full APPROVE then CONFIRM.
# --------------------------------------------------------------------------- #

ADAPTER_ORDER_METHODS = tuple(sorted(ORDER_SURFACE - {"execute_approved_plan"}))


@pytest.fixture
def order_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Spies on every order-surface method of the order adapter and on `execute_approved_plan`.

    The adapter methods are replaced on the CLASS, so any instance, however built, is spied. The
    execution entry is replaced in every loaded module that holds a reference to it. A spy
    records the call and raises, so a reached order path also fails the test loudly.
    """
    import sys

    import src.adapters.binance_usdm as binance_usdm
    import src.execution.manager as manager

    called: list[str] = []

    def spy(label: str) -> Callable[..., Any]:
        def record(*args: Any, **kwargs: Any) -> Any:
            called.append(label)
            raise AssertionError(f"order surface reached: {label}")

        return record

    for method in ADAPTER_ORDER_METHODS:
        assert hasattr(binance_usdm.BinanceUsdmAdapter, method), method  # the list is not stale
        monkeypatch.setattr(binance_usdm.BinanceUsdmAdapter, method, spy(f"adapter.{method}"))
    original = manager.execute_approved_plan
    for module in list(sys.modules.values()):
        if getattr(module, "execute_approved_plan", None) is original:
            monkeypatch.setattr(module, "execute_approved_plan", spy("execute_approved_plan"))
    return called


async def test_a_full_shadow_approve_then_confirm_in_the_runtime_wiring_reaches_no_order_surface(
    order_calls: list[str],
) -> None:
    from src.paper.shadow_confirm import EVENT_SHADOW_CONFIRMED
    from src.paper.shadow_ledger import EVENT_SHADOW_POSITION_OPENED
    from src.paper.shadow_runtime import ShadowCoordinator

    from tests.test_paper_shadow_runtime import FIRST_MINUTE, LAG_SECONDS, Rig

    rig = Rig()
    assert isinstance(rig.coordinator, ShadowCoordinator)

    await rig.approve_and_confirm()
    rig.now = FIRST_MINUTE + timedelta(minutes=2, seconds=LAG_SECONDS + 1)
    await rig.coordinator.poll_once()

    # The flow really ran to the simulated position: the isolation result is not vacuous.
    assert len(rig.bot.sent) >= 2
    assert len(rig.bot.edited) == 1
    assert len(rig.journal(EVENT_SHADOW_CONFIRMED)) == 1
    assert len(rig.journal(EVENT_SHADOW_POSITION_OPENED)) == 1
    assert rig.coordinator.open_positions()[0].filled is True
    assert order_calls == []


async def test_the_rehearsal_path_in_dry_run_reaches_no_order_surface(
    order_calls: list[str], tmp_path: Path
) -> None:
    import scripts.shadow_rehearsal as shadow_rehearsal

    result = await shadow_rehearsal.run_dry_rehearsal(tmp_path / "rehearsal.json")

    assert result.complete is True
    assert result.evidence["position_opened"] is True
    assert result.evidence["confirmed_within_ttl"] is True
    assert order_calls == []


async def test_negative_control_a_deliberate_call_is_recorded_by_the_spies(
    order_calls: list[str],
) -> None:
    import src.adapters.binance_usdm as binance_usdm
    import src.execution.manager as manager

    adapter = object.__new__(binance_usdm.BinanceUsdmAdapter)  # no SDK client is built
    for method in ADAPTER_ORDER_METHODS:
        with pytest.raises(AssertionError, match="order surface reached"):
            getattr(adapter, method)()
    with pytest.raises(AssertionError, match="order surface reached"):
        cast(Any, manager).execute_approved_plan()

    assert order_calls == [
        *(f"adapter.{m}" for m in ADAPTER_ORDER_METHODS),
        "execute_approved_plan",
    ]


def test_negative_control_the_spy_list_covers_every_public_order_method_of_the_adapter() -> None:
    """A new public async method on the adapter must be classified: market data or spied."""
    import inspect

    import src.adapters.binance_usdm as binance_usdm

    market_data = {
        "klines",
        "mark_klines",
        "open_interest",
        "open_interest_statistics",
        "funding_rate",
        "server_time",
        "exchange_info",
        "get_mark_price",
    }
    public_async = {
        name
        for name, member in inspect.getmembers(binance_usdm.BinanceUsdmAdapter)
        if not name.startswith("_") and inspect.iscoroutinefunction(member)
    }
    assert public_async - market_data == set(ADAPTER_ORDER_METHODS)
