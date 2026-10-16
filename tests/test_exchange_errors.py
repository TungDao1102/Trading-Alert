"""Exchange error taxonomy: classification by (class, code, call kind) only (plan 18-05).

The code table is documentation text read per docs/SOURCES.md section "Facts
read for Phase 18" (WebFetch summaries, not verified live); -4509 is
Demo-observed only. Nothing here reads exception message text (D-10).
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from binance_common.configuration import ConfigurationRestAPI
from binance_common.utils import send_request
from src.adapters.binance_errors import error_facts_from_exception
from src.domain.exchange_errors import (
    CallKind,
    ErrorFacts,
    ExchangeErrorCategory,
    HttpClass,
    classify,
)

from tests.support.ast_guards import (
    float_constructor_calls,
    forbidden_imports,
    module_imports,
    wall_clock_calls,
)

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "src" / "domain" / "exchange_errors.py"
NORMALIZER = ROOT / "src" / "adapters" / "binance_errors.py"


class _Response:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json"}
        self.text = json.dumps(body)

    def json(self) -> Any:
        return json.loads(self.text)


class _Session:
    def __init__(self, response: _Response) -> None:
        self._response = response

    def request(self, **_: Any) -> _Response:
        return self._response


def _sdk_error(status: int, body: dict[str, Any]) -> BaseException:
    """An exception raised by the installed `send_request` for a stubbed answer."""
    config = ConfigurationRestAPI(
        api_key="TEST_ONLY_KEY",
        api_secret="TEST_ONLY_SECRET",
        base_path="https://example.invalid",
        retries=0,
        timeout=1000,
    )
    with pytest.raises(Exception) as info:
        send_request(
            _Session(_Response(status, body)),  # type: ignore[arg-type]
            config,
            method="GET",
            path="/fapi/v1/order",
            payload={"symbol": "BTCUSDT"},
            is_signed=False,
        )
    return info.value


# --------------------------------------------------------------------------- #
# Task 1 tracer
# --------------------------------------------------------------------------- #


def test_sdk_2013_on_query_is_order_absent() -> None:
    exc = _sdk_error(400, {"code": -2013, "msg": "Order does not exist."})
    facts = error_facts_from_exception(exc)
    assert facts == ErrorFacts(HttpClass.BAD_REQUEST, -2013, None)
    assert classify(facts, CallKind.QUERY) is ExchangeErrorCategory.ORDER_ABSENT


def test_sdk_2013_on_placement_is_unknown_exchange_error() -> None:
    exc = _sdk_error(400, {"code": -2013, "msg": "Order does not exist."})
    facts = error_facts_from_exception(exc)
    assert classify(facts, CallKind.PLACEMENT) is ExchangeErrorCategory.UNKNOWN_EXCHANGE_ERROR


def test_runtime_error_with_code_text_is_never_read() -> None:
    facts = error_facts_from_exception(RuntimeError("-2013 NO_SUCH_ORDER"))
    assert facts == ErrorFacts(HttpClass.NON_SDK, None, None)
    for kind in CallKind:
        assert classify(facts, kind) is ExchangeErrorCategory.UNKNOWN_EXCHANGE_ERROR


def test_taxonomy_is_pure_stdlib_no_float_no_clock() -> None:
    imports = module_imports(TAXONOMY)
    non_stdlib = [
        name
        for name in imports
        if name.split(".")[0] not in sys.stdlib_module_names and name != "__future__"
    ]
    assert non_stdlib == []
    assert forbidden_imports(TAXONOMY, ("binance*", "requests", "aiohttp", "src", "tests")) == []
    assert float_constructor_calls(TAXONOMY) == []
    assert wall_clock_calls(TAXONOMY) == []


def test_normalizer_never_reads_message_text() -> None:
    """`str(exc)`, `exc.args`, `error_message` and `repr` never appear in the normalizer."""
    tree = ast.parse(NORMALIZER.read_text(encoding="utf-8"))
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"args", "error_message", "msg"}:
            offenders.append((node.lineno, node.attr))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"str", "repr", "format"}
        ):
            offenders.append((node.lineno, node.func.id))
        if isinstance(node, ast.JoinedStr):
            offenders.append((node.lineno, "f-string"))
        if isinstance(node, ast.Constant) and node.value in {"error_message", "args", "msg"}:
            offenders.append((node.lineno, f"constant {node.value!r}"))
    assert offenders == []
