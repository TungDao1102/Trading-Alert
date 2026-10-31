"""AST guards for `src/live/` (plan 24-04): Q5, wall clock and import direction.

Every `src/live/**/*.py` is found by glob, so a module a later plan adds is covered from its first
commit. Each rule is a function over a source text or a path and has at least one seeded negative
control, so a rule that stops detecting its violation fails here and not silently.

  * Q5 / D080: no call of `place_entry`, `place_algo_protective` or `place_market_close` under
    `src/live/` (placement goes through the manager); `execute_approved_plan` has exactly one
    reference in the whole package, a call in `src/live/execution_service.py`, outside any loop,
    except-handler or tenacity-decorated function; no `tenacity` import; no loop or retry helper
    in the functions of the bridge. The adapter-level guards stay in
    tests/test_binance_usdm_source_guard.py and tests/test_execution_manager.py.
  * Wall clock: a `src/live` module reads no clock (inject one); the explicit edge allow-list below
    names the only modules that may, with the reason.
  * Direction: `src/live` imports neither `src.paper.runtime`, `tests` nor `scripts`, and the
    layers below it import nothing from `src.live`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.support.ast_guards import forbidden_imports, wall_clock_calls
from tests.test_binance_usdm_source_guard import placement_retry_constructs

ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = ROOT / "src" / "live"
SERVICE = "src/live/execution_service.py"

# Plan 24-32 asserts the size of this table: an entry is a reviewed exception, not a convenience.
# Applied only when the file exists.
WALL_CLOCK_EDGE_ALLOW_LIST: dict[str, str] = {
    "src/live/runtime.py": "CLI edge reads the process clock",
}

FORBIDDEN_PLACEMENT_CALLS = frozenset(
    {"place_entry", "place_algo_protective", "place_market_close"}
)
MANAGER_ENTRY = "execute_approved_plan"
# The functions of the bridge: none may loop or retry.
BRIDGE_FUNCTIONS = frozenset({"on_confirmed", "_schedule", "_place"})
LIVE_FORBIDDEN_IMPORTS = ("src.paper.runtime", "tests", "scripts")
LOWER_LAYERS = (
    "core",
    "risk",
    "domain",
    "execution",
    "adapters",
    "reconcile",
    "ops",
    "persistence",
    "approval",
    "paper",
)
_LOOPS = (
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)
_RETRY_NAMES = frozenset({"tenacity", "retry", "retrying", "Retrying", "AsyncRetrying"})


def live_files(root: Path = LIVE_DIR) -> list[Path]:
    return sorted(root.rglob("*.py"))


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _name_of(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


# --------------------------------------------------------------------------- #
# Q5: no placement call under src/live; one manager call, never repeated.
# --------------------------------------------------------------------------- #


def placement_calls(source: str) -> list[str]:
    """`line: name` of every call of a raw placement method (by name or attribute)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            name = _name_of(node.func)
            if name in FORBIDDEN_PLACEMENT_CALLS:
                found.append(f"{node.lineno}: {name}")
    return sorted(found)


def tenacity_imports(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(
                f"{node.lineno}: import {a.name}"
                for a in node.names
                if a.name.split(".")[0] == "tenacity"
            )
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "tenacity":
            found.append(f"{node.lineno}: from {node.module} import ...")
    return sorted(found)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _decorator_is_retry(decorator: ast.expr, tenacity_names: set[str]) -> bool:
    for inner in ast.walk(decorator):
        if isinstance(inner, ast.Name) and (inner.id in _RETRY_NAMES or inner.id in tenacity_names):
            return True
        if isinstance(inner, ast.Attribute) and inner.attr in _RETRY_NAMES:
            return True
    return False


def manager_references(source: str) -> list[tuple[int, list[str]]]:
    """Every reference to `execute_approved_plan` as `(line, problems)`.

    A reference is a Name or Attribute with that identifier outside an import. A call that sits
    inside a loop, an except handler or a retry-decorated function reports that as a problem; a
    reference that is not the callee of a Call (a `partial(...)` argument) is a problem too.
    """
    tree = ast.parse(source)
    parents = _parents(tree)
    tenacity_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "tenacity"
        for alias in node.names
    }
    found: list[tuple[int, list[str]]] = []
    for node in ast.walk(tree):
        is_name = isinstance(node, ast.Name) and node.id == MANAGER_ENTRY
        is_attr = isinstance(node, ast.Attribute) and node.attr == MANAGER_ENTRY
        if not (is_name or is_attr):
            continue
        problems: list[str] = []
        parent = parents.get(node)
        if not (isinstance(parent, ast.Call) and parent.func is node):
            problems.append("referenced without being called")
        current: ast.AST | None = parent
        while current is not None:
            if isinstance(current, _LOOPS):
                problems.append("inside a loop")
            elif isinstance(current, ast.ExceptHandler):
                problems.append("inside an except handler")
            elif isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef) and any(
                _decorator_is_retry(d, tenacity_names) for d in current.decorator_list
            ):
                problems.append(f"inside {current.name}, a retry-decorated function")
            current = parents.get(current)
        found.append((node.lineno, problems))
    return sorted(found)


def bridge_loop_constructs(source: str, names: frozenset[str] = BRIDGE_FUNCTIONS) -> list[str]:
    """Loops, comprehensions and retry helpers inside the named functions of the bridge."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in names):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, _LOOPS):
                found.append(f"{node.name}:{inner.lineno}: {type(inner).__name__}")
            elif isinstance(inner, ast.Name) and inner.id in _RETRY_NAMES:
                found.append(f"{node.name}:{inner.lineno}: retry helper {inner.id}")
            elif isinstance(inner, ast.Attribute) and inner.attr in _RETRY_NAMES:
                found.append(f"{node.name}:{inner.lineno}: retry helper {inner.attr}")
    return sorted(found)


@pytest.mark.parametrize("path", live_files(), ids=relative)
def test_q5_no_raw_placement_call_and_no_tenacity_under_src_live(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    assert placement_calls(source) == [], f"{relative(path)} calls a raw placement method"
    assert tenacity_imports(source) == [], f"{relative(path)} imports tenacity"
    # The adapter-level guard, applied to the live package too: a function named like a
    # placement function under src/live would be flagged for any loop or retry helper in it.
    found = [
        line for line in placement_retry_constructs(source) if not line.endswith(": not defined")
    ]
    assert found == [], f"{relative(path)}: {found}"


def test_q5_execute_approved_plan_has_one_call_site_in_the_service() -> None:
    sites: list[tuple[str, int, list[str]]] = []
    for path in live_files():
        sites.extend(
            (relative(path), line, problems)
            for line, problems in manager_references(path.read_text(encoding="utf-8"))
        )
    assert [(file, problems) for file, _line, problems in sites] == [(SERVICE, [])], sites


def test_q5_the_bridge_functions_hold_no_loop_or_retry() -> None:
    source = (ROOT / SERVICE).read_text(encoding="utf-8")
    assert {"on_confirmed", "_schedule", "_place"} <= {
        n.name
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }, "a bridge function was renamed: update BRIDGE_FUNCTIONS"
    assert bridge_loop_constructs(source) == []


# --------------------------------------------------------------------------- #
# Wall clock and direction.
# --------------------------------------------------------------------------- #


def wall_clock_violations(
    files: list[Path], allow: dict[str, str], *, root: Path = ROOT
) -> list[str]:
    """`file:line name` for every clock read outside the edge allow-list."""
    found: list[str] = []
    for path in files:
        rel = path.resolve().relative_to(root).as_posix()
        if rel in allow:
            continue
        found.extend(f"{rel}:{line} {name}" for line, name in wall_clock_calls(path))
    return found


def test_src_live_modules_read_no_wall_clock_outside_the_edge_allow_list() -> None:
    assert wall_clock_violations(live_files(), WALL_CLOCK_EDGE_ALLOW_LIST) == []


def test_the_edge_allow_list_names_only_live_modules_with_a_reason() -> None:
    for rel, reason in WALL_CLOCK_EDGE_ALLOW_LIST.items():
        assert rel.startswith("src/live/") and rel.endswith(".py")
        assert reason.strip() != ""


@pytest.mark.parametrize("path", live_files(), ids=relative)
def test_src_live_imports_neither_the_paper_runtime_tests_nor_scripts(path: Path) -> None:
    assert forbidden_imports(path, LIVE_FORBIDDEN_IMPORTS) == []


def lower_layer_files(root: Path = ROOT) -> list[Path]:
    return sorted(p for layer in LOWER_LAYERS for p in (root / "src" / layer).rglob("*.py"))


def imports_of_src_live(files: list[Path]) -> list[str]:
    return [f"{p.name}: {name}" for p in files for name in forbidden_imports(p, ["src.live"])]


def test_the_layers_below_src_live_import_nothing_from_it() -> None:
    files = lower_layer_files()
    assert len(files) > 100, "the layer glob found too few files"
    assert imports_of_src_live(files) == []


# --------------------------------------------------------------------------- #
# Negative controls: every rule fails on a seeded snippet.
# --------------------------------------------------------------------------- #


def test_negative_control_a_raw_placement_call_is_found() -> None:
    snippet = (
        "async def f(adapter):\n"
        "    await adapter.place_entry(symbol='X')\n"
        "    await adapter.client.place_algo_protective()\n"
        "    place_market_close()\n"
        "    adapter.place_entry_ok()\n"
    )
    assert placement_calls(snippet) == [
        "2: place_entry",
        "3: place_algo_protective",
        "4: place_market_close",
    ]


def test_negative_control_a_tenacity_import_is_found() -> None:
    assert tenacity_imports("import tenacity\nfrom tenacity import retry\nimport os\n") == [
        "1: import tenacity",
        "2: from tenacity import ...",
    ]
    assert tenacity_imports("import tenacity.asyncio as t\n") == ["1: import tenacity.asyncio"]
    assert tenacity_imports("import os\nfrom asyncio import sleep\n") == []


def test_negative_control_the_manager_call_in_a_loop_is_found() -> None:
    for header in ("for _ in range(2):", "while True:", "async for _ in stream():"):
        snippet = f"async def f():\n    {header}\n        await execute_approved_plan(a=1)\n"
        ((_, problems),) = manager_references(snippet)
        assert problems == ["inside a loop"], header
    comprehension = "async def f():\n    return [await execute_approved_plan() for _ in x]\n"
    ((_, problems),) = manager_references(comprehension)
    assert problems == ["inside a loop"]


def test_negative_control_the_manager_call_in_an_except_handler_is_found() -> None:
    snippet = (
        "async def f():\n"
        "    try:\n"
        "        await execute_approved_plan()\n"
        "    except Exception:\n"
        "        await execute_approved_plan()\n"
    )
    assert [problems for _, problems in manager_references(snippet)] == [
        [],
        ["inside an except handler"],
    ]


def test_negative_control_the_manager_call_under_a_retry_decorator_is_found() -> None:
    snippet = (
        "from tenacity import retry as again\n"
        "@again(stop=3)\n"
        "async def f():\n"
        "    await execute_approved_plan()\n"
    )
    ((_, problems),) = manager_references(snippet)
    assert problems == ["inside f, a retry-decorated function"]
    dotted = "@tenacity.retry\nasync def g():\n    await execute_approved_plan()\n"
    ((_, problems),) = manager_references(dotted)
    assert problems == ["inside g, a retry-decorated function"]


def test_negative_control_a_second_or_indirect_reference_to_the_manager_is_found() -> None:
    two = "async def f():\n    await execute_approved_plan()\n    await execute_approved_plan()\n"
    assert len(manager_references(two)) == 2
    indirect = "g = partial(execute_approved_plan, a=1)\n"
    ((_, problems),) = manager_references(indirect)
    assert problems == ["referenced without being called"]
    attribute = "async def f(m):\n    await m.execute_approved_plan()\n"
    assert len(manager_references(attribute)) == 1
    imported_only = "from src.execution.manager import execute_approved_plan\n"
    assert manager_references(imported_only) == []


def test_negative_control_a_loop_or_retry_helper_in_the_bridge_is_found() -> None:
    snippet = (
        "class S:\n"
        "    def on_confirmed(self, a):\n"
        "        for _ in range(2):\n"
        "            self._schedule(a)\n"
        "    async def _place(self):\n"
        "        async for attempt in tenacity.AsyncRetrying():\n"
        "            pass\n"
        "        x = [y for y in z]\n"
        "    def other(self):\n"
        "        while True:\n"
        "            pass\n"
    )
    found = bridge_loop_constructs(snippet)
    assert found == [
        "_place:6: AsyncFor",
        "_place:6: retry helper AsyncRetrying",
        "_place:6: retry helper tenacity",
        "_place:8: ListComp",
        "on_confirmed:3: For",
    ]


def test_negative_control_a_wall_clock_read_is_found_unless_allow_listed(tmp_path: Path) -> None:
    (tmp_path / "src" / "live").mkdir(parents=True)
    clocked = tmp_path / "src" / "live" / "clocked.py"
    clocked.write_text(
        "import time\nfrom datetime import UTC, datetime\n"
        "def f():\n    return time.monotonic(), datetime.now(UTC)\n",
        encoding="utf-8",
    )
    edge = tmp_path / "src" / "live" / "runtime.py"
    edge.write_text("import time\ndef f():\n    return time.time()\n", encoding="utf-8")
    found = wall_clock_violations([clocked, edge], WALL_CLOCK_EDGE_ALLOW_LIST, root=tmp_path)
    assert sorted(found) == [
        "src/live/clocked.py:4 datetime.now",
        "src/live/clocked.py:4 time.monotonic",
    ]
    assert wall_clock_violations([edge], WALL_CLOCK_EDGE_ALLOW_LIST, root=tmp_path) == []
    # The allow-list is by exact path: the same code under another name is not excused.
    renamed = tmp_path / "src" / "live" / "runtime_v2.py"
    renamed.write_text(edge.read_text(encoding="utf-8"), encoding="utf-8")
    assert wall_clock_violations([renamed], WALL_CLOCK_EDGE_ALLOW_LIST, root=tmp_path) == [
        "src/live/runtime_v2.py:3 time.time"
    ]


def test_negative_control_forbidden_live_imports_are_found(tmp_path: Path) -> None:
    seeded = tmp_path / "seeded.py"
    seeded.write_text(
        "import src.paper.runtime\n"
        "from tests.support import live_rig\n"
        "import scripts.demo_rehearsal\n"
        "from src.paper import liveness\n"
        "import src.paper.runtime_helpers_not_forbidden\n",
        encoding="utf-8",
    )
    assert forbidden_imports(seeded, LIVE_FORBIDDEN_IMPORTS) == [
        "src.paper.runtime",
        "tests.support",
        "scripts.demo_rehearsal",
    ]


def test_negative_control_a_lower_layer_importing_src_live_is_found(tmp_path: Path) -> None:
    seeded = tmp_path / "seeded.py"
    seeded.write_text("from src.live.wiring import LiveWiring\nimport src.live\n", encoding="utf-8")
    clean = tmp_path / "clean.py"
    clean.write_text(
        "from src.liveness_not_live import x\nimport src.paper.liveness\n", encoding="utf-8"
    )
    assert imports_of_src_live([seeded, clean]) == [
        "seeded.py: src.live.wiring",
        "seeded.py: src.live",
    ]
