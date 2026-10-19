"""Reusable AST guards for the pure modules of Phase 18 (plan 18-03).

Each guard parses a source file (never imports it) and returns a plain list,
so any plan can assert an empty result or compare it against an allow-list:

- `module_imports(path)`: every imported dotted module name
- `forbidden_imports(path, prefixes)`: the imports matching a forbidden prefix
- `float_constructor_calls(path)`: line numbers of calls to the name `float`
- `wall_clock_calls(path)`: `(line, dotted name)` of wall-clock reads
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

# Dotted call names that read a clock. Matched against the full dotted name of
# the call or its suffix, so `datetime.now()` and `datetime.datetime.now()`
# both match `datetime.now`.
WALL_CLOCK_CALLS: tuple[str, ...] = (
    "datetime.now",
    "datetime.utcnow",
    "date.today",
    "time.time",
    "time.time_ns",
    "time.monotonic",
    "time.monotonic_ns",
    "time.perf_counter",
    "time.perf_counter_ns",
)


def _tree(path: str | Path) -> ast.Module:
    source = Path(path).read_text(encoding="utf-8")
    return ast.parse(source, filename=str(path))


def module_imports(path: str | Path) -> list[str]:
    """Every imported dotted module name, in source order.

    `import a.b` gives `a.b`; `from a.b import c` gives `a.b`; a relative
    import keeps its leading dots (`from . import x` gives `.`).
    """
    names: list[str] = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append("." * node.level + (node.module or ""))
    return names


def _matches_prefix(name: str, prefix: str) -> bool:
    if prefix.endswith("*"):
        return name.startswith(prefix[:-1])
    return name == prefix or name.startswith(prefix + ".")


def forbidden_imports(path: str | Path, prefixes: Iterable[str]) -> list[str]:
    """The imported module names that match any of `prefixes`.

    A prefix matches a module whose dotted name equals it or starts with it
    followed by a dot; a prefix ending in `*` matches any module name that
    starts with the text before the `*` (so `binance*` matches
    `binance_common` and `binance_sdk_derivatives_trading_usds_futures`).
    """
    wanted = tuple(prefixes)
    return [
        name
        for name in module_imports(path)
        if any(_matches_prefix(name, prefix) for prefix in wanted)
    ]


def float_constructor_calls(path: str | Path) -> list[int]:
    """Line numbers of calls to the name `float` (also `builtins.float`)."""
    lines: list[int] = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "float":
            lines.append(node.lineno)
        elif (
            isinstance(func, ast.Attribute)
            and func.attr == "float"
            and isinstance(func.value, ast.Name)
            and func.value.id == "builtins"
        ):
            lines.append(node.lineno)
    return sorted(lines)


def _dotted(node: ast.expr) -> str | None:
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _from_imported_clock_names(tree: ast.Module) -> dict[str, str]:
    """Local names bound by `from time import monotonic` and the like."""
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                if full in WALL_CLOCK_CALLS:
                    bound[alias.asname or alias.name] = full
    return bound


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    """Local name -> full dotted name for every import, `as` aliases included.

    `import time as t` gives `t -> time`; `from datetime import datetime as DT` gives
    `DT -> datetime.datetime`. A plain `import a.b` binds `a`.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _is_loop_time_call(node: ast.Call) -> str | None:
    """`loop.time()` and `asyncio.get_running_loop().time()` read the loop's monotonic clock."""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "time"):
        return None
    receiver = func.value
    if isinstance(receiver, ast.Call):
        inner = _dotted(receiver.func)
        if inner is not None and inner.split(".")[-1] in {"get_running_loop", "get_event_loop"}:
            return f"{inner}().time"
        return None
    dotted = _dotted(func)
    if dotted is not None and dotted.split(".")[-2:] == ["loop", "time"]:
        return dotted
    return None


def wall_clock_calls(path: str | Path) -> list[tuple[int, str]]:
    """`(line, dotted name)` of every call that reads a wall or monotonic clock.

    Import aliases are resolved (`import time as t; t.time()`, `from datetime import datetime
    as DT; DT.now()`), and the event loop's own clock (`loop.time()`,
    `asyncio.get_running_loop().time()`) counts as a clock read.
    """
    tree = _tree(path)
    bound = _from_imported_clock_names(tree)
    aliases = _import_aliases(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        loop_clock = _is_loop_time_call(node)
        if loop_clock is not None:
            found.append((node.lineno, loop_clock))
            continue
        dotted = _dotted(node.func)
        if dotted is None:
            continue
        if dotted in bound:
            found.append((node.lineno, bound[dotted]))
            continue
        written = next(
            (t for t in WALL_CLOCK_CALLS if dotted == t or dotted.endswith("." + t)), None
        )
        if written is not None:
            found.append((node.lineno, dotted))
            continue
        head, _, rest = dotted.partition(".")
        if head in aliases and aliases[head] != head:
            resolved = f"{aliases[head]}.{rest}" if rest else aliases[head]
            if any(resolved == t or resolved.endswith("." + t) for t in WALL_CLOCK_CALLS):
                found.append((node.lineno, resolved))
    return sorted(found)


__all__ = [
    "WALL_CLOCK_CALLS",
    "float_constructor_calls",
    "forbidden_imports",
    "module_imports",
    "wall_clock_calls",
]
