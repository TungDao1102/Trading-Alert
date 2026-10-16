"""AST guard: the message-text fallbacks and adapter-level placement retries cannot return.

Plan 18-10 (D-10, D-11, 08-REVIEW IN-10, 09-REVIEW CR-09). Each rule is a function over source
text, run once on the real files (positive test) and once on a snippet that violates it
(negative control), so a guard that silently stopped matching would fail its control.

Rules:

1. `src/adapters/binance_usdm.py` defines none of the removed module-level names.
2. `src/adapters/binance_usdm.py` does not import `re`.
3. In `src/adapters/binance_usdm.py` and `src/execution/manager.py` no code reads exception
   message text for a decision: no attribute named `error_message`, and no `str(<name>)` for
   a typical exception variable name unless the call sits inside the arguments of a logger
   call (`log.info`, `log.warning`, `log.error`, `log.exception`, `log.debug`).
4. `place_entry` and `place_algo_protective` contain no loop (so no `await` in a loop) and
   no use of `tenacity`.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "src" / "adapters" / "binance_usdm.py"
MANAGER = REPO / "src" / "execution" / "manager.py"

# The removed names: the not-found regex constant, the not-found code set, the
# already-canceled message helper and the transient-reconcile helper.
REMOVED_NAMES: frozenset[str] = frozenset(
    {
        "_NOT_FOUND_MESSAGE",
        "_NOT_FOUND_CODES",
        "_is_already_canceled_message",
        "_is_transient_reconcile",
    }
)
EXCEPTION_NAMES: frozenset[str] = frozenset({"exc", "e", "err", "error", "exception"})
LOGGER_METHODS: frozenset[str] = frozenset({"info", "warning", "error", "exception", "debug"})
PLACEMENT_FUNCTIONS: frozenset[str] = frozenset({"place_entry", "place_algo_protective"})


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Rule 1: removed module-level names.
# --------------------------------------------------------------------------- #


def module_level_names(source: str) -> set[str]:
    """Every name bound at module level (functions, classes, assignments, imports)."""
    names: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
        elif isinstance(node, ast.AnnAssign | ast.AugAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
    return names


def removed_names_present(source: str) -> list[str]:
    return sorted(module_level_names(source) & REMOVED_NAMES)


def test_removed_names_stay_removed() -> None:
    assert removed_names_present(_read(ADAPTER)) == []


def test_removed_names_guard_reports_each_name() -> None:
    snippet = (
        "import re\n"
        "_NOT_FOUND_MESSAGE = re.compile('-2011')\n"
        "_NOT_FOUND_CODES: frozenset[int] = frozenset({-2013})\n"
        "def _is_already_canceled_message(message: str) -> bool:\n"
        "    return '-2011' in message\n"
        "def _is_transient_reconcile(exc: BaseException) -> bool:\n"
        "    return True\n"
    )
    assert removed_names_present(snippet) == sorted(REMOVED_NAMES)


# --------------------------------------------------------------------------- #
# Rule 2: no `re` import.
# --------------------------------------------------------------------------- #


def imports_re(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(
            alias.name == "re" or alias.name.startswith("re.") for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "re":
            return True
    return False


def test_adapter_does_not_import_re() -> None:
    assert imports_re(_read(ADAPTER)) is False


def test_re_import_guard_reports_both_forms() -> None:
    assert imports_re("import re\n") is True
    assert imports_re("from re import compile\n") is True
    assert imports_re("def f() -> None:\n    import re\n") is True
    assert imports_re("import reprlib\n") is False


# --------------------------------------------------------------------------- #
# Rule 3: no decision reads exception message text.
# --------------------------------------------------------------------------- #


def _is_logger_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in LOGGER_METHODS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "log"
    )


def message_text_reads(source: str) -> list[str]:
    """`error_message` attribute reads and `str(<exception name>)` outside logger calls."""
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "error_message":
            found.append(f"{node.lineno}: reads .error_message")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in EXCEPTION_NAMES
        ):
            ancestor = parents.get(node)
            inside_logger = False
            while ancestor is not None:
                if _is_logger_call(ancestor):
                    inside_logger = True
                    break
                ancestor = parents.get(ancestor)
            if not inside_logger:
                found.append(f"{node.lineno}: str({node.args[0].id}) outside a logger call")
    return sorted(found)


def test_adapter_reads_no_message_text_for_a_decision() -> None:
    assert message_text_reads(_read(ADAPTER)) == []


def test_manager_reads_no_message_text_for_a_decision() -> None:
    assert message_text_reads(_read(MANAGER)) == []


def test_message_text_guard_reports_each_form() -> None:
    snippet = (
        "def f(exc: BaseException, e: BaseException) -> bool:\n"
        "    if '-2011' in str(exc):\n"
        "        return True\n"
        "    return getattr(e, 'x', None) is None or e.error_message == 'gone'\n"
    )
    found = message_text_reads(snippet)
    assert any("str(exc)" in line for line in found)
    assert any(".error_message" in line for line in found)
    for name in sorted(EXCEPTION_NAMES):
        assert message_text_reads(f"text = str({name})\n") == [
            f"1: str({name}) outside a logger call"
        ]


def test_message_text_guard_allows_logger_arguments_only() -> None:
    allowed = (
        "def f(exc: BaseException) -> None:\n"
        "    log.warning('x', detail=str(exc))\n"
        "    log.info('x', data={'detail': str(exc)})\n"
    )
    assert message_text_reads(allowed) == []
    not_a_logger = (
        "def f(exc: BaseException) -> None:\n"
        "    journal.write('x', detail=str(exc))\n"
        "    other.info('x', detail=str(exc))\n"
    )
    assert len(message_text_reads(not_a_logger)) == 2


# --------------------------------------------------------------------------- #
# Rule 4: placement is single-attempt in the adapter.
# --------------------------------------------------------------------------- #

_LOOPS = (ast.For, ast.AsyncFor, ast.While, ast.ListComp, ast.SetComp, ast.DictComp)


def placement_retry_constructs(source: str) -> list[str]:
    """Loops, awaits inside loops and `tenacity` uses inside the placement functions."""
    found: list[str] = []
    seen: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name not in PLACEMENT_FUNCTIONS:
            continue
        seen.add(node.name)
        for inner in ast.walk(node):
            if isinstance(inner, _LOOPS):
                found.append(f"{node.name}:{inner.lineno}: loop {type(inner).__name__}")
                for awaited in ast.walk(inner):
                    if isinstance(awaited, ast.Await):
                        found.append(f"{node.name}:{awaited.lineno}: await inside a loop")
            if isinstance(inner, ast.Name) and inner.id == "tenacity":
                found.append(f"{node.name}:{inner.lineno}: uses tenacity")
            if isinstance(inner, ast.Attribute) and inner.attr in {
                "AsyncRetrying",
                "Retrying",
                "retry",
            }:
                found.append(f"{node.name}:{inner.lineno}: uses a retry helper")
    missing = sorted(PLACEMENT_FUNCTIONS - seen)
    found.extend(f"{name}: not defined" for name in missing)
    return sorted(found)


def test_placement_functions_have_no_retry_construct() -> None:
    assert placement_retry_constructs(_read(ADAPTER)) == []


def test_placement_guard_reports_loops_awaits_and_tenacity() -> None:
    snippet = (
        "import tenacity\n"
        "class A:\n"
        "    async def place_entry(self) -> None:\n"
        "        for _ in range(3):\n"
        "            await self.send()\n"
        "    async def place_algo_protective(self) -> None:\n"
        "        async for attempt in tenacity.AsyncRetrying():\n"
        "            with attempt:\n"
        "                await self.send()\n"
        "        while True:\n"
        "            break\n"
    )
    found = placement_retry_constructs(snippet)
    assert any("place_entry" in line and "loop For" in line for line in found)
    assert any("place_entry" in line and "await inside a loop" in line for line in found)
    assert any("place_algo_protective" in line and "loop AsyncFor" in line for line in found)
    assert any("place_algo_protective" in line and "uses tenacity" in line for line in found)
    assert any("place_algo_protective" in line and "loop While" in line for line in found)
    # A missing placement function is reported, so renaming one cannot hide a retry.
    assert placement_retry_constructs("x = 1\n") == [
        "place_algo_protective: not defined",
        "place_entry: not defined",
    ]
