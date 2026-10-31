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
   `src/adapters/binance_errors.py` is scanned too (plan 24-03): DECISIONS D083 item 2 allows
   exactly ONE read there, the `error_message` of a 418 in `_ban_until_epoch_ms`; any other read
   in that file, and any other form (`args`, `msg`, `str(exc)`, f-strings) in that function,
   still fails.
4. `place_entry` and `place_algo_protective` contain no loop (so no `await` in a loop) and
   no use of `tenacity`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "src" / "adapters" / "binance_usdm.py"
MANAGER = REPO / "src" / "execution" / "manager.py"
ERRORS = REPO / "src" / "adapters" / "binance_errors.py"

# D083 item 2 (plan 24-03): the one function allowed to read exception message text, and the one
# attribute it may read. Nothing else is allowed, there or elsewhere.
D083_FUNCTION = "_ban_until_epoch_ms"
D083_ALLOWED: dict[str, frozenset[str]] = {D083_FUNCTION: frozenset({"error_message"})}

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
PLACEMENT_FUNCTIONS: frozenset[str] = frozenset(
    {"place_entry", "place_algo_protective", "place_market_close"}
)


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


def _exception_names(tree: ast.AST) -> set[str]:
    """The typical exception variable names plus every name the code binds to an exception.

    A name is an exception name when an `except ... as name` clause binds it or when a
    function parameter is annotated with a type that contains `Exception` or `Error`
    (review WR-07: the fixed list alone missed `except ValueError as caught`).
    """
    names = set(EXCEPTION_NAMES)
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            for argument in arguments:
                if argument.annotation is None:
                    continue
                text = ast.unparse(argument.annotation)
                if "Exception" in text or "Error" in text:
                    names.add(argument.arg)
    return names


def message_text_reads(source: str, allowed: dict[str, frozenset[str]] | None = None) -> list[str]:
    """Reads of an exception's message text outside logger calls.

    Flagged: any `error_message` attribute; `str(x)`, `repr(x)` and `format(x)` of an exception
    name; `x.args` and `x.msg`; `getattr(x, "error_message" | "args" | "msg")`; and an f-string
    that interpolates an exception name.

    `allowed` maps a function name to the `error_message` form it may read (`.error_message` or
    `getattr(x, "error_message")`), and only that one (D083 item 2). Default: nothing is allowed.
    """
    allowed = allowed or {}
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    names = _exception_names(tree)

    def error_message_allowed(node: ast.AST) -> bool:
        ancestor = parents.get(node)
        while ancestor is not None:
            if isinstance(ancestor, ast.FunctionDef | ast.AsyncFunctionDef):
                return "error_message" in allowed.get(ancestor.name, frozenset())
            ancestor = parents.get(ancestor)
        return False

    def inside_logger(node: ast.AST) -> bool:
        ancestor = parents.get(node)
        while ancestor is not None:
            if _is_logger_call(ancestor):
                return True
            ancestor = parents.get(ancestor)
        return False

    found: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "error_message"
            and not error_message_allowed(node)
        ):
            found.append(f"{node.lineno}: reads .error_message")
        if (
            isinstance(node, ast.Attribute)
            and node.attr in {"args", "msg"}
            and isinstance(node.value, ast.Name)
            and node.value.id in names
            and not inside_logger(node)
        ):
            found.append(f"{node.lineno}: {node.value.id}.{node.attr} outside a logger call")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"str", "repr", "format"}
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in names
            and not inside_logger(node)
        ):
            found.append(f"{node.lineno}: {node.func.id}({node.args[0].id}) outside a logger call")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in names
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in {"error_message", "args", "msg"}
            and not inside_logger(node)
            and not (node.args[1].value == "error_message" and error_message_allowed(node))
        ):
            found.append(f"{node.lineno}: getattr({node.args[0].id}, {node.args[1].value!r})")
        if (
            isinstance(node, ast.FormattedValue)
            and isinstance(node.value, ast.Name)
            and node.value.id in names
            and not inside_logger(node)
        ):
            found.append(f"{node.lineno}: f-string interpolates {node.value.id}")
    return sorted(found)


def test_adapter_reads_no_message_text_for_a_decision() -> None:
    assert message_text_reads(_read(ADAPTER)) == []


def test_manager_reads_no_message_text_for_a_decision() -> None:
    assert message_text_reads(_read(MANAGER)) == []


def test_errors_module_reads_message_text_only_in_the_d083_function() -> None:
    source = _read(ERRORS)
    assert message_text_reads(source, D083_ALLOWED) == []
    # Without the allow-list the D083 read is seen, so the guard really scans this file.
    unallowed = message_text_reads(source)
    assert len(unallowed) == 1
    assert "getattr(exc, 'error_message')" in unallowed[0]
    # The allow-listed function exists exactly once (a rename cannot silently drop the fence).
    definitions = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == D083_FUNCTION
    ]
    assert len(definitions) == 1


def test_d083_allow_list_is_one_function_and_one_attribute() -> None:
    assert D083_ALLOWED == {D083_FUNCTION: frozenset({"error_message"})}


def test_d083_function_exists_only_in_the_errors_module() -> None:
    for path in (ADAPTER, MANAGER):
        assert D083_FUNCTION not in _read(path)


def test_d083_allow_list_negative_control_another_function_reading_msg_or_error_message() -> None:
    snippet = (
        "def _ban_until_epoch_ms(exc: BaseException) -> int | None:\n"
        "    return getattr(exc, 'error_message', None)\n"
        "def _retry_after_seconds(exc: BaseException) -> int | None:\n"
        "    if exc.msg:\n"
        "        return 1\n"
        "    return getattr(exc, 'error_message', None)\n"
        "def _other(exc: BaseException) -> str:\n"
        "    return exc.error_message\n"
    )
    assert message_text_reads(snippet, D083_ALLOWED) == [
        "4: exc.msg outside a logger call",
        "6: getattr(exc, 'error_message')",
        "8: reads .error_message",
    ]


def test_d083_allow_list_negative_control_the_d083_function_reading_args_or_other_forms() -> None:
    snippet = (
        "def _ban_until_epoch_ms(exc: BaseException) -> int | None:\n"
        "    text = exc.args[1]\n"
        "    text = getattr(exc, 'args', None)\n"
        "    text = getattr(exc, 'msg', None)\n"
        "    text = exc.msg\n"
        "    text = str(exc)\n"
        "    text = f'{exc}'\n"
        "    return 1\n"
    )
    assert message_text_reads(snippet, D083_ALLOWED) == [
        "2: exc.args outside a logger call",
        "3: getattr(exc, 'args')",
        "4: getattr(exc, 'msg')",
        "5: exc.msg outside a logger call",
        "6: str(exc) outside a logger call",
        "7: f-string interpolates exc",
    ]


def test_d083_allow_list_does_not_leak_to_a_nested_or_renamed_function() -> None:
    renamed = (
        "def _ban_until_epoch_ms_v2(exc: BaseException) -> int | None:\n"
        "    return getattr(exc, 'error_message', None)\n"
    )
    assert message_text_reads(renamed, D083_ALLOWED) == ["2: getattr(exc, 'error_message')"]


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


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        ("text = repr(exc)\n", "1: repr(exc) outside a logger call"),
        ("text = format(err)\n", "1: format(err) outside a logger call"),
        ("text = exc.args[0]\n", "1: exc.args outside a logger call"),
        ("text = exc.msg\n", "1: exc.msg outside a logger call"),
        ("text = getattr(exc, 'error_message')\n", "1: getattr(exc, 'error_message')"),
        ("text = f'bad {exc}'\n", "1: f-string interpolates exc"),
        (
            "try:\n    pass\nexcept ValueError as caught:\n    text = str(caught)\n",
            "4: str(caught) outside a logger call",
        ),
        (
            "def f(failure: BaseException) -> str:\n    return str(failure)\n",
            "2: str(failure) outside a logger call",
        ),
    ],
)
def test_message_text_guard_reports_the_bypass_forms(snippet: str, expected: str) -> None:
    assert message_text_reads(snippet) == [expected]


def test_message_text_guard_allows_a_logger_f_string_and_unrelated_names() -> None:
    allowed = (
        "def f(exc: BaseException, value: int) -> None:\n"
        "    log.warning('x', detail=f'{exc}', raw=repr(exc))\n"
        "    text = str(value)\n"
        "    text = repr(value)\n"
    )
    assert message_text_reads(allowed) == []


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
        "place_market_close: not defined",
    ]
