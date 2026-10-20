"""No unratified number for the O-18-01 safety thresholds anywhere in src or scripts (18-07).

The 27 canonical keys of `CANONICAL_KEYS` and the three `RateLimitPolicy` field names (also
the keyword names of `rate_limit_decision`) may only ever be READ from a loaded limits object.
This scan parses every `.py` file under `src/` and `scripts/` with `ast` (never imports it)
and fails on any assignment, annotated assignment, keyword argument, parameter default,
dataclass field default or dict entry that gives one of those names an int, float or bool
constant. It also fails when production code imports the TEST_ONLY values of
`tests/support/limits.py`. The README of `config/binance/` is checked against the key list.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from src.adapters.binance_limits import CANONICAL_KEYS, NULLABLE_KEYS, PROVENANCE_LABELS
from src.execution.execution_limits import EXECUTION_LIMIT_KEYS

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (ROOT / "src", ROOT / "scripts")
README = ROOT / "config" / "binance" / "README.md"

RATE_LIMIT_FIELD_NAMES = frozenset(
    {
        "no_retry_after_wait_418_seconds",
        "no_retry_after_wait_429_seconds",
        "retry_after_cap_seconds",
    }
)
# Phase 19 adds the execution-limit keys of D-07/D-13 (plan 19-01) and the owner's 19-REVIEW
# keys `entry_unknown_grace_ms` (WR-05) and `emergency_close_poll_timeout_ms` (WR-03), then
# `max_last_price_age_ms` (quick task 261020-l4p, the last-price check): seven keys.
EXECUTION_LIMIT_NAMES = frozenset(key for keys in EXECUTION_LIMIT_KEYS.values() for key in keys)
GUARDED_NAMES = (
    frozenset(key for keys in CANONICAL_KEYS.values() for key in keys)
    | RATE_LIMIT_FIELD_NAMES
    | EXECUTION_LIMIT_NAMES
)

# The dataclasses that carry the loaded limits: no number may be given to them positionally.
LIMIT_CLASS_NAMES = frozenset(
    {
        "BinanceLimits",
        "StreamLimits",
        "RateLimitPolicy",
        "SignedCallPolicy",
        "DriftLimits",
        "ClientLimits",
        "ExecutionLimits",
    }
)

# (path relative to the repository root, name) -> the reason the numeric constant is allowed.
# Every entry needs a one-line reason. The list is empty: the scan found no such constant.
ALLOW_LIST: dict[tuple[str, str], str] = {}


# --------------------------------------------------------------------------- #
# The scanner.
# --------------------------------------------------------------------------- #


def _is_numeric_constant(node: ast.expr | None) -> bool:
    """An int, float, complex or bool literal, optionally behind a unary plus or minus."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        node = node.operand
    return isinstance(node, ast.Constant) and isinstance(node.value, int | float | complex)


def _target_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        value = node.slice.value
        return value if isinstance(value, str) else None
    return None


def _assigned_pairs(target: ast.expr, value: ast.expr) -> Iterator[tuple[str | None, ast.expr]]:
    if isinstance(target, ast.Tuple | ast.List) and isinstance(value, ast.Tuple | ast.List):
        for sub_target, sub_value in zip(target.elts, value.elts, strict=False):
            yield from _assigned_pairs(sub_target, sub_value)
        return
    yield _target_name(target), value


def _field_default(value: ast.expr | None) -> ast.expr | None:
    """The `default=` of a `field(...)` / `dataclasses.field(...)` call, if any."""
    if not isinstance(value, ast.Call):
        return None
    func = value.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name != "field":
        return None
    for keyword in value.keywords:
        if keyword.arg == "default":
            return keyword.value
    return None


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else None


def _parameter_defaults(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
) -> Iterator[tuple[str, ast.expr]]:
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    for arg, default in zip(
        positional[len(positional) - len(args.defaults) :], args.defaults, strict=True
    ):
        yield arg.arg, default
    for arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        if kw_default is not None:
            yield arg.arg, kw_default


def find_numeric_defaults(source: str, filename: str = "<source>") -> list[tuple[int, str, str]]:
    """`(line, name, kind)` for every guarded name given a numeric constant in `source`."""
    found: list[tuple[int, str, str]] = []

    def hit(line: int, name: str | None, kind: str, value: ast.expr | None) -> None:
        # Compared in lower case: a module constant such as `KEEPALIVE_INTERVAL_SECONDS = 1800`
        # is the same name spelled the constant way (review WR-04).
        if name is not None and name.lower() in GUARDED_NAMES and _is_numeric_constant(value):
            found.append((line, name, kind))

    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name, value in _assigned_pairs(target, node.value):
                    hit(node.lineno, name, "assignment", value)
        elif isinstance(node, ast.AnnAssign):
            name = _target_name(node.target)
            hit(node.lineno, name, "annotated assignment", node.value)
            hit(node.lineno, name, "dataclass field default", _field_default(node.value))
        elif isinstance(node, ast.NamedExpr):
            hit(node.lineno, _target_name(node.target), "assignment expression", node.value)
        elif isinstance(node, ast.keyword):
            hit(getattr(node, "lineno", 0), node.arg, "keyword argument", node.value)
        elif isinstance(node, ast.Call) and _call_name(node) in LIMIT_CLASS_NAMES:
            # A positional number given to a limits dataclass names no field at all.
            for argument in node.args:
                if _is_numeric_constant(argument):
                    found.append((node.lineno, str(_call_name(node)), "positional argument"))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            for name, default in _parameter_defaults(node):
                hit(node.lineno, name, "parameter default", default)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    hit(node.lineno, key.value, "dict entry", value)
    return sorted(found)


TEST_ONLY_MODULES = ("limits", "execution_limits")


def imports_test_only_limits(source: str, filename: str = "<source>") -> list[int]:
    """Line numbers of imports of `tests.support.limits` or `tests.support.execution_limits`."""
    prefixes = tuple(f"tests.support.{name}" for name in TEST_ONLY_MODULES)
    lines: list[int] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Import):
            if any(alias.name.startswith(prefixes) for alias in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.startswith(prefixes) or (
                node.module == "tests.support"
                and any(alias.name in TEST_ONLY_MODULES for alias in node.names)
            ):
                lines.append(node.lineno)
    return lines


def _production_files() -> list[Path]:
    return sorted(path for root in SCAN_ROOTS for path in root.rglob("*.py"))


# --------------------------------------------------------------------------- #
# The repository scan.
# --------------------------------------------------------------------------- #


def test_the_scan_covers_src_and_scripts() -> None:
    files = _production_files()
    relative = {path.relative_to(ROOT).as_posix() for path in files}
    assert "src/adapters/binance_limits.py" in relative
    assert "src/adapters/binance_clock.py" in relative
    assert any(name.startswith("scripts/") for name in relative)
    # 30 ratified Binance-limit names + 7 execution-limit names (the fifth,
    # entry_unknown_grace_ms, is the owner's 19-REVIEW WR-05 key; the sixth,
    # emergency_close_poll_timeout_ms, the owner's WR-03 key; the seventh,
    # max_last_price_age_ms, the last-price check of quick task 261020-l4p).
    assert len(GUARDED_NAMES) == 37
    assert EXECUTION_LIMIT_NAMES <= GUARDED_NAMES


def test_no_canonical_key_gets_a_numeric_constant_in_src_or_scripts() -> None:
    offences: list[str] = []
    for path in _production_files():
        relative = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        for line, name, kind in find_numeric_defaults(source, relative):
            if (relative, name) in ALLOW_LIST:
                continue
            offences.append(f"{relative}:{line} {kind} gives {name} a numeric constant")
    assert offences == []


def test_every_allow_list_entry_has_a_reason() -> None:
    for key, reason in ALLOW_LIST.items():
        assert isinstance(reason, str) and reason.strip(), key


def test_no_production_file_imports_the_test_only_limits() -> None:
    offences = [
        f"{path.relative_to(ROOT).as_posix()}:{line}"
        for path in _production_files()
        for line in imports_test_only_limits(path.read_text(encoding="utf-8"), str(path))
    ]
    assert offences == []


# --------------------------------------------------------------------------- #
# The scanner itself: every forbidden form is found, every read is allowed.
# --------------------------------------------------------------------------- #

_FORBIDDEN_FORMS = {
    "assignment": "recv_window_ms = 5\n",
    "negative assignment": "ahead_limit_ms = -5\n",
    "float assignment": "keepalive_interval_seconds = 2.5\n",
    "bool assignment": "include_measurement_uncertainty = True\n",
    "attribute assignment": "self.event_queue_max = 64\n",
    "tuple assignment": "a, sdk_retries = 1, 2\n",
    "annotated assignment": "rest_timeout_ms: int = 7\n",
    "dataclass field default": (
        "from dataclasses import field\n"
        "class C:\n"
        "    snapshot_max_attempts: int = field(default=3)\n"
    ),
    "keyword argument": "build(retry_after_cap_seconds=9)\n",
    "rate-limit keyword": "rate_limit_decision(c, None, no_retry_after_wait_429_seconds=4)\n",
    "positional parameter default": "def f(behind_limit_ms=8):\n    pass\n",
    "keyword-only parameter default": (
        "async def f(*, no_retry_after_wait_418_seconds: int = 6):\n    pass\n"
    ),
    "lambda default": "g = lambda sdk_backoff_ms=1: sdk_backoff_ms\n",
    "dict entry": 'cfg = {"reconnect_max_attempts": 7}\n',
    "subscript assignment": 'cfg["max_liveness_age_seconds"] = 30\n',
    "assignment expression": "if (snapshot_deadline_seconds := 20):\n    pass\n",
    "upper-case constant": "KEEPALIVE_INTERVAL_SECONDS = 1800\n",
    "upper-case annotated constant": "RECV_WINDOW_MS: int = 5000\n",
    "class attribute": "class C:\n    RECV_WINDOW_MS = 5\n",
    "execution limit assignment": "max_unprotected_ms = 5000\n",
    "execution limit keyword": "build(entry_terminal_timeout_ms=9000)\n",
    "execution limit parameter default": "def f(max_mark_price_age_ms=800):\n    pass\n",
    "execution limit upper-case constant": "MIN_REMAINING_VALIDITY_SECONDS = 600\n",
    "positional execution limits argument": "ExecutionLimits(1, 2, 3, 4)\n",
    "positional limits argument": "StreamLimits(1800, 3)\n",
    "positional limits argument through a module": "limits_mod.RateLimitPolicy(10, 20, 30)\n",
}


@pytest.mark.parametrize("form", sorted(_FORBIDDEN_FORMS))
def test_the_scanner_finds_every_forbidden_form(form: str) -> None:
    assert find_numeric_defaults(_FORBIDDEN_FORMS[form]) != [], form


_ALLOWED_FORMS = {
    "attribute read": "x = limits.stream.keepalive_interval_seconds\n",
    "keyword from a loaded value": "f(recv_window_ms=policy.recv_window_ms)\n",
    "annotation without a value": "class C:\n    recv_window_ms: int\n",
    "none for a nullable": "max_liveness_age_seconds = None\n",
    "string literal": 'event_queue_max = "event_queue_max"\n',
    "unguarded name": "timeout_ms = 5\n",
    "required parameter": "def f(*, retry_after_cap_seconds: int) -> None:\n    pass\n",
    "upper-case unguarded name": "TIMEOUT_MS = 5\n",
    "limits object built from loaded values": "StreamLimits(**loaded)\n",
    "execution limit unset": "max_unprotected_ms = None\n",
    "execution limits built from loaded values": "ExecutionLimits(**loaded)\n",
    "field without a default": (
        "from dataclasses import field\nclass C:\n    sdk_retries: int = field(repr=False)\n"
    ),
}


@pytest.mark.parametrize("form", sorted(_ALLOWED_FORMS))
def test_the_scanner_allows_reads_and_required_fields(form: str) -> None:
    assert find_numeric_defaults(_ALLOWED_FORMS[form]) == [], form


@pytest.mark.parametrize(
    "source",
    [
        "import tests.support.limits\n",
        "from tests.support.limits import test_only_binance_limits\n",
        "from tests.support import limits\n",
        "from tests.support import ast_guards, limits as tl\n",
        "import tests.support.execution_limits\n",
        "from tests.support.execution_limits import test_only_execution_limits\n",
        "from tests.support import execution_limits\n",
    ],
)
def test_the_import_scan_finds_every_import_form(source: str) -> None:
    assert imports_test_only_limits(source) != []


def test_the_import_scan_ignores_other_support_modules() -> None:
    assert imports_test_only_limits("from tests.support import ast_guards\n") == []


# --------------------------------------------------------------------------- #
# config/binance/README.md: the required keys, no values.
# --------------------------------------------------------------------------- #

_KEY_LINE = re.compile(r"^- `([a-z_]+)\.([a-z0-9_]+)` - \S")


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def _readme_keys() -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for line in _readme_text().splitlines():
        match = _KEY_LINE.match(line)
        if match:
            keys.append((match.group(1), match.group(2)))
    return keys


def test_the_readme_key_set_equals_the_canonical_keys() -> None:
    keys = _readme_keys()
    assert len(keys) == len(set(keys)) == 27
    expected = {(section, key) for section, names in CANONICAL_KEYS.items() for key in names}
    assert set(keys) == expected


def test_the_readme_key_lines_carry_a_meaning_and_a_unit() -> None:
    for line in _readme_text().splitlines():
        if _KEY_LINE.match(line):
            assert re.search(r"\([^()]+\)\.?$", line), line


def test_the_readme_carries_no_value_for_any_key() -> None:
    text = _readme_text()
    for name in GUARDED_NAMES:
        assert not re.search(rf"\b{name}\b`?\s*[=:]\s*[-+]?\d", text), name


def test_the_readme_states_the_rules() -> None:
    text = _readme_text()
    assert "binance-limits-v1.toml" in text
    assert "18-DEC-O-18-01.md" in text
    assert "18-09" in text
    assert "load_binance_limits" in text
    assert "no default" in text
    assert "PLACEHOLDER" in text
    assert "rate_limit_no_retry_after_wait_seconds" in text  # named as retired, without a value
    for label in PROVENANCE_LABELS:
        assert label in text, label
    for dotted in NULLABLE_KEYS:
        line = next(line for line in text.splitlines() if line.startswith(f"- `{dotted}`"))
        assert "none" in line, dotted
