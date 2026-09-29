"""AST purity guard for the pure analytics modules (Phase 10, plan 10-01, D-01, T-10-01/03).

Every `src/analytics/*.py` module (discovered by glob so later plans need no
list edits) except the explicit EDGE_MODULES must be free of: float shapes,
ambient wall-clock reads, module-level randomness, built-in `hash()`,
`timedelta.total_seconds()`, and third-party / adapter / DB / data imports.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.test_domain_no_float import _find_float_calls

REPO_ROOT = Path(__file__).resolve().parent.parent
ANALYTICS_DIR = REPO_ROOT / "src" / "analytics"
# The CLI edge (plan 12) may touch the filesystem/clock; nothing else may.
EDGE_MODULES = frozenset({"cli.py"})

FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "polars",
        "pandas",
        "numpy",
        "sqlalchemy",
        "pydantic",
        "fastapi",
        "uvicorn",
        "binance",
        "telegram",
        "httpx",
        "duckdb",
        "pyarrow",
    }
)
FORBIDDEN_INTERNAL_PREFIXES = ("src.adapters", "src.db", "src.data")
_CLOCK_ATTRS = frozenset({"now", "utcnow", "today"})
_TIME_MODULE_ATTRS = frozenset({"time", "time_ns", "monotonic", "perf_counter"})


def _under_forbidden_prefix(module: str) -> bool:
    return any(module == p or module.startswith(p + ".") for p in FORBIDDEN_INTERNAL_PREFIXES)


def _import_violations(node: ast.AST) -> list[str]:
    found: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in FORBIDDEN_IMPORT_ROOTS or _under_forbidden_prefix(alias.name):
                found.append(f"import {alias.name}")
    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        root = node.module.split(".")[0]
        if root in FORBIDDEN_IMPORT_ROOTS or _under_forbidden_prefix(node.module):
            found.append(f"from {node.module} import ...")
        elif node.module == "src":
            for alias in node.names:
                if _under_forbidden_prefix(f"src.{alias.name}"):
                    found.append(f"from src import {alias.name}")
        elif node.module == "random":
            for alias in node.names:
                if alias.name != "Random":
                    found.append(f"from random import {alias.name}")
    return found


def find_violations(source: str) -> list[tuple[int, str, str]]:
    """Return (line, rule, text) for every purity violation in `source`."""
    lines = source.splitlines()
    found: dict[tuple[int, str, str], None] = {}

    def add(lineno: int, rule: str) -> None:
        found[(lineno, rule, lines[lineno - 1].strip())] = None

    for lineno, _ in _find_float_calls(source):
        add(lineno, "float")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        for description in _import_violations(node):
            add(node.lineno, f"forbidden-import: {description}")
        if isinstance(node, ast.Attribute) and node.attr == "total_seconds":
            add(node.lineno, "total_seconds")
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "hash":
            add(node.lineno, "builtin-hash")
        elif isinstance(func, ast.Attribute):
            base = func.value
            if func.attr in _CLOCK_ATTRS:
                add(node.lineno, f"ambient-clock: .{func.attr}()")
            elif (
                isinstance(base, ast.Name)
                and base.id == "time"
                and func.attr in _TIME_MODULE_ATTRS
            ):
                add(node.lineno, f"ambient-clock: time.{func.attr}()")
            elif isinstance(base, ast.Name) and base.id == "random" and func.attr != "Random":
                add(node.lineno, f"module-level-random: random.{func.attr}()")
    return sorted(found)


def _pure_modules() -> list[Path]:
    return sorted(p for p in ANALYTICS_DIR.glob("*.py") if p.name not in EDGE_MODULES)


def test_guard_discovers_the_core_modules() -> None:
    names = {p.name for p in _pure_modules()}
    assert {"__init__.py", "types.py", "stats.py", "inputs.py", "excursion.py"} <= names


def test_pure_analytics_modules_have_no_violations() -> None:
    offenders: list[str] = []
    for path in _pure_modules():
        for lineno, rule, text in find_violations(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}: {rule}: {text}")
    assert not offenders, "analytics purity violated (D-01):\n" + "\n".join(offenders)


# --------------------------------------------------------------------------- #
# Self-tests: every rule fires on a synthetic offending snippet.
# --------------------------------------------------------------------------- #


def _rules(source: str) -> list[str]:
    return [rule for _, rule, _ in find_violations(source)]


def test_guard_flags_float_shapes() -> None:
    assert "float" in _rules("x = 0.5\n")
    assert "float" in _rules("x = float(1)\n")
    assert "float" in _rules("import numpy as np\nx = np.float64\n")


def _has_rule(source: str, prefix: str) -> bool:
    return any(rule.startswith(prefix) for rule in _rules(source))


def test_guard_flags_ambient_clock() -> None:
    for snippet in (
        "import datetime\nx = datetime.datetime.now()\n",
        "from datetime import datetime\nx = datetime.utcnow()\n",
        "from datetime import date\nx = date.today()\n",
        "import time\nx = time.time()\n",
    ):
        assert _has_rule(snippet, "ambient-clock"), snippet


def test_guard_flags_total_seconds() -> None:
    assert "total_seconds" in _rules("x = (a - b).total_seconds()\n")


def test_guard_flags_builtin_hash() -> None:
    assert "builtin-hash" in _rules("x = hash('a')\n")


def test_guard_flags_module_level_random_but_allows_seeded_instance() -> None:
    assert _has_rule("import random\nx = random.random()\n", "module-level-random")
    assert _has_rule("import random\nrandom.shuffle(xs)\n", "module-level-random")
    assert _has_rule("from random import choice\n", "forbidden-import")
    assert _rules("import random\nrng = random.Random(7)\n") == []


def test_guard_flags_forbidden_imports() -> None:
    for snippet in (
        "import polars\n",
        "import pandas as pd\n",
        "import numpy\n",
        "from sqlalchemy import text\n",
        "from pydantic import BaseModel\n",
        "import httpx\n",
        "import duckdb\n",
        "import pyarrow.parquet\n",
        "from src.adapters.telegram_notify import x\n",
        "from src.db.session import y\n",
        "from src.data import z\n",
        "from src import adapters\n",
    ):
        assert any(r.startswith("forbidden-import") for r in _rules(snippet)), snippet


def test_guard_allows_clean_pure_code() -> None:
    clean = (
        "from decimal import Decimal\n"
        "from src.backtest.report import _r_multiple\n"
        "from src.core._decimal import _div\n"
        "x = Decimal('0.5')\n"
        "y = (b - a) // timedelta(microseconds=1)\n"
    )
    assert _rules(clean) == []
