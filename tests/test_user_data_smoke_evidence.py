"""The smoke evidence schema, the acceptance verdict, the secret scan and the structural pins
of `scripts/user_data_smoke.py` (plan 18-16 Task 2).

The valid document comes from one real dry run (FAKE proof class); every rule of
`check_smoke_evidence` has a negative control and every acceptance letter a table of cases.
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
import types
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from scripts import user_data_smoke as uds
from src.adapters.binance_public import SymbolFilters
from src.ops import redaction

from tests.userdata_fakes import TEST_ONLY_LISTEN_KEY

SCRIPT_PATH = Path(uds.__file__)

TEST_ONLY_SMOKE_LIMITS = """
[order]
symbol = "BTCUSDT"
quantity = "0.002"
far_price_fraction = "0.96"

[waits]
event_wait_seconds = 30
cleanup_timeout_seconds = 60
"""


@pytest.fixture(autouse=True)
def _isolated_runtime_secrets() -> Iterator[None]:
    redaction.clear_runtime_secrets()
    yield
    redaction.clear_runtime_secrets()


def _dry_run(
    tmp_path: Path, prepare: Callable[[uds.SmokeRig], None] | None = None
) -> tuple[int, dict[str, Any]]:
    limits = tmp_path / "smoke-limits.toml"
    limits.write_text(TEST_ONLY_SMOKE_LIMITS, encoding="utf-8")
    evidence = tmp_path / "evidence"

    def factory(config: uds.SmokeConfig) -> uds.SmokeRig:
        rig = uds.build_dry_run_rig(config)
        if prepare is not None:
            prepare(rig)
        return rig

    argv = [
        "--environment",
        "DEMO",
        "--smoke-limits-file",
        str(limits),
        "--evidence-dir",
        str(evidence),
    ]
    code = uds.main(argv, environ={}, rig_factory=factory)
    (path,) = evidence.glob("user-data-smoke-*.json")
    return code, json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def valid_document(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    redaction.clear_runtime_secrets()
    code, document = _dry_run(tmp_path_factory.mktemp("valid"))
    redaction.clear_runtime_secrets()
    assert code == uds.EXIT_OK
    return document


@pytest.fixture
def doc(valid_document: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(valid_document)


def _set_step(document: dict[str, Any], name: str, status: str) -> None:
    for step in document["steps"]:
        if step["name"] == name:
            step["status"] = status
            return
    raise AssertionError(name)


# --------------------------------------------------------------------------- #
# check_smoke_evidence: the file written by a dry run passes; every rule has a negative control.
# --------------------------------------------------------------------------- #


def test_the_dry_run_file_passes_the_checker(valid_document: dict[str, Any]) -> None:
    assert uds.check_smoke_evidence(valid_document) == []


def test_not_an_object_is_refused() -> None:
    assert uds.check_smoke_evidence(["not", "an", "object"]) == ["evidence is not an object"]


@pytest.mark.parametrize("key", uds.REQUIRED_TOP_LEVEL_KEYS)
def test_every_required_key_is_checked(doc: dict[str, Any], key: str) -> None:
    del doc[key]
    assert f"missing key: {key}" in uds.check_smoke_evidence(doc)


@pytest.mark.parametrize(
    ("key", "value", "fragment"),
    [
        ("schema", "user-data-smoke-evidence/schema-2", "schema must be"),
        ("mode", "live", "mode must be one of"),
        ("proof_class", "REAL", "proof_class must be one of"),
        ("proof_class", "REAL_SMOKE", "proof_class does not match the mode"),
        ("sdk_route_delivery", "MAYBE", "sdk_route_delivery must be one of"),
        ("steps", {"not": "a list"}, "steps is not a list"),
        ("acceptance", {"a": {"result": "PASS"}}, "acceptance must carry the keys a to h"),
    ],
)
def test_each_rule_has_a_negative_control(
    doc: dict[str, Any], key: str, value: Any, fragment: str
) -> None:
    doc[key] = value
    problems = uds.check_smoke_evidence(doc)
    assert any(fragment in problem for problem in problems), problems


def test_an_executed_file_must_say_real_smoke(doc: dict[str, Any]) -> None:
    doc["mode"] = "execute"
    assert any("does not match" in p for p in uds.check_smoke_evidence(doc))
    doc["proof_class"] = "REAL_SMOKE"
    assert uds.check_smoke_evidence(doc) == []


def test_a_bad_step_status_is_refused(doc: dict[str, Any]) -> None:
    _set_step(doc, "keepalive", "MAYBE")
    assert any("step status" in p for p in uds.check_smoke_evidence(doc))


def test_a_missing_or_reordered_step_is_refused(doc: dict[str, Any]) -> None:
    doc["steps"] = doc["steps"][1:]
    assert any("every step once" in p for p in uds.check_smoke_evidence(doc))


def test_a_bad_acceptance_result_is_refused(doc: dict[str, Any]) -> None:
    doc["acceptance"]["c"]["result"] = "GOOD"
    assert any("acceptance result" in p for p in uds.check_smoke_evidence(doc))


@pytest.mark.parametrize(
    "planted",
    [TEST_ONLY_LISTEN_KEY, f"url ?listenKey={'Ab1' * 10}", f"/private/ws/{TEST_ONLY_LISTEN_KEY}"],
)
def test_a_listen_key_shaped_value_is_refused(doc: dict[str, Any], planted: str) -> None:
    doc["notes"].append(planted)
    assert any("listenKey-shaped" in p for p in uds.check_smoke_evidence(doc))


def test_a_listen_key_shaped_mapping_key_is_refused(doc: dict[str, Any]) -> None:
    doc["settings"][TEST_ONLY_LISTEN_KEY] = 1
    assert any("listenKey-shaped" in p for p in uds.check_smoke_evidence(doc))


def test_a_sha256_digest_is_not_mistaken_for_a_listen_key(doc: dict[str, Any]) -> None:
    assert len(doc["settings"]["limits_file_sha256"]) == 64
    doc["notes"].append("f" * 64)
    assert uds.check_smoke_evidence(doc) == []


# --------------------------------------------------------------------------- #
# smoke_acceptance_verdict: a table per letter.
# --------------------------------------------------------------------------- #


def _result(document: dict[str, Any], letter: str) -> str:
    return str(uds.smoke_acceptance_verdict(document)[letter]["result"])


def test_the_dry_run_verdict_is_pass_except_f_observed(valid_document: dict[str, Any]) -> None:
    verdict = uds.smoke_acceptance_verdict(valid_document)
    assert {k: v["result"] for k, v in verdict.items()} == {
        "a": "PASS",
        "b": "PASS",
        "c": "PASS",
        "d": "PASS",
        "e": "PASS",
        "f": "OBSERVED",
        "g": "PASS",
        "h": "PASS",
    }


def test_every_verdict_carries_the_proof_class(valid_document: dict[str, Any]) -> None:
    verdict = uds.smoke_acceptance_verdict(valid_document)
    assert {entry["proof_class"] for entry in verdict.values()} == {"FAKE"}


@pytest.mark.parametrize(
    ("status", "expected"), [("PASSED", "PASS"), ("FAILED", "FAIL"), ("NOT_RUN", "UNPROVEN")]
)
def test_verdict_a_follows_the_listen_key_start(
    doc: dict[str, Any], status: str, expected: str
) -> None:
    doc["listen_key"]["status"] = status
    assert _result(doc, "a") == expected


@pytest.mark.parametrize(
    ("status", "count", "expected"),
    [
        ("PASSED", 1, "PASS"),
        ("PASSED", 0, "FAIL"),
        ("FAILED", 1, "FAIL"),
        ("NOT_RUN", None, "UNPROVEN"),
    ],
)
def test_verdict_b_needs_the_subscription_and_a_private_connection(
    doc: dict[str, Any], status: str, count: int | None, expected: str
) -> None:
    doc["subscription"]["status"] = status
    doc["subscription"]["private_connection_count"] = count
    assert _result(doc, "b") == expected


def _drop_execution(document: dict[str, Any], execution: str) -> None:
    document["events"] = [
        e
        for e in document["events"]
        if not (e.get("is_smoke_order") and e.get("execution_type") == execution)
    ]


C_CASES: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
    "both-delivered": (lambda d: None, "PASS"),
    "silent-route": (
        lambda d: (
            _drop_execution(d, "NEW"),
            _drop_execution(d, "CANCELED"),
            d.update(sdk_route_delivery="FAIL"),
        ),
        "FAIL",
    ),
    "canceled-missing": (
        lambda d: (_drop_execution(d, "CANCELED"), d.update(sdk_route_delivery="FAIL")),
        "FAIL",
    ),
    "missing-but-route-pass": (lambda d: _drop_execution(d, "NEW"), "FAIL"),
    "delivered-but-route-fail": (lambda d: d.update(sdk_route_delivery="FAIL"), "FAIL"),
    "order-not-placed": (lambda d: _set_step(d, "order_place", "NOT_RUN"), "UNPROVEN"),
    "placement-failed": (lambda d: _set_step(d, "order_place", "FAILED"), "UNPROVEN"),
}


@pytest.mark.parametrize("case", list(C_CASES))
def test_verdict_c_is_typed_delivery_through_the_sdk_route(doc: dict[str, Any], case: str) -> None:
    mutate, expected = C_CASES[case]
    mutate(doc)
    assert _result(doc, "c") == expected


def test_verdict_c_names_the_missing_executions(doc: dict[str, Any]) -> None:
    _drop_execution(doc, "CANCELED")
    doc["sdk_route_delivery"] = "FAIL"
    reason = uds.smoke_acceptance_verdict(doc)["c"]["reason"]
    assert "CANCELED" in reason and "NEW" not in reason.split("missing:")[1]


@pytest.mark.parametrize(
    ("status", "expected"), [("PASSED", "PASS"), ("FAILED", "FAIL"), ("NOT_RUN", "UNPROVEN")]
)
def test_verdict_d_follows_the_keepalive_step(
    doc: dict[str, Any], status: str, expected: str
) -> None:
    _set_step(doc, "keepalive", status)
    assert _result(doc, "d") == expected


def _states(document: dict[str, Any], *names: str) -> None:
    document["forced_drop"]["state_sequence_after_drop"] = [
        {"state": name, "reason": "x", "at_utc": "2026-10-16T12:00:00+00:00"} for name in names
    ]


E_CASES: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
    "recovered": (lambda d: None, "PASS"),
    "no-syncing": (lambda d: _states(d, "UNKNOWN", "LIVE"), "FAIL"),
    "never-live": (lambda d: _states(d, "UNKNOWN", "SYNCING"), "FAIL"),
    "wrong-order": (lambda d: _states(d, "LIVE", "SYNCING", "UNKNOWN"), "FAIL"),
    "no-snapshot": (lambda d: d["forced_drop"].update(snapshot_count_after_drop=0), "FAIL"),
    "no-gap": (lambda d: d["forced_drop"].update(gap_ms=None), "FAIL"),
    "gap-not-int": (lambda d: d["forced_drop"].update(gap_ms="12"), "FAIL"),
    "not-run": (lambda d: d.update(forced_drop={"status": "NOT_RUN"}), "UNPROVEN"),
}


@pytest.mark.parametrize("case", list(E_CASES))
def test_verdict_e_is_unknown_syncing_live_with_a_snapshot_and_a_gap(
    doc: dict[str, Any], case: str
) -> None:
    mutate, expected = E_CASES[case]
    mutate(doc)
    assert _result(doc, "e") == expected


def test_verdict_f_is_observed_with_the_class_and_the_code(doc: dict[str, Any]) -> None:
    verdict = uds.smoke_acceptance_verdict(doc)["f"]
    assert verdict["result"] == "OBSERVED"
    assert "BAD_REQUEST" in verdict["reason"] and "-1125" in verdict["reason"]


@pytest.mark.parametrize(
    ("observation", "expected"),
    [
        ({"outcome": "NO_ERROR", "http_class": None, "code": None}, "OBSERVED"),
        ({"outcome": "ERROR", "http_class": "BAD_REQUEST", "code": -1125}, "OBSERVED"),
        ({"status": "FAILED", "outcome": "NOT_SENT"}, "UNPROVEN"),
        ({"status": "NOT_RUN"}, "UNPROVEN"),
    ],
)
def test_verdict_f_is_never_pass_or_fail(
    doc: dict[str, Any], observation: dict[str, Any], expected: str
) -> None:
    doc["delete_then_put"] = observation
    assert _result(doc, "f") == expected


G_CASES: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
    "clean": (lambda d: None, "PASS"),
    "listen-key-found": (lambda d: d["log_scan"]["findings"].update(listen_key=1), "FAIL"),
    "signature-found": (lambda d: d["log_scan"]["findings"].update(signature=2), "FAIL"),
    "step-failed": (lambda d: _set_step(d, "log_scan", "FAILED"), "FAIL"),
    "not-run": (
        lambda d: (_set_step(d, "log_scan", "NOT_RUN"), d.update(log_scan={"status": "NOT_RUN"})),
        "UNPROVEN",
    ),
}


@pytest.mark.parametrize("case", list(G_CASES))
def test_verdict_g_is_the_log_scan(doc: dict[str, Any], case: str) -> None:
    mutate, expected = G_CASES[case]
    mutate(doc)
    assert _result(doc, "g") == expected


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: None, "PASS"),
        (lambda d: d.update(schema="other"), "FAIL"),
        (lambda d: d.pop("events"), "FAIL"),
        (lambda d: d["notes"].append(TEST_ONLY_LISTEN_KEY), "FAIL"),
    ],
    ids=["valid", "schema", "missing-key", "listen-key"],
)
def test_verdict_h_is_the_checker(
    doc: dict[str, Any], mutate: Callable[[dict[str, Any]], None], expected: str
) -> None:
    mutate(doc)
    assert _result(doc, "h") == expected


# --------------------------------------------------------------------------- #
# The log scan (acceptance g) on a real dry run.
# --------------------------------------------------------------------------- #


def test_a_listen_key_printed_during_the_run_fails_the_log_scan(tmp_path: Path) -> None:
    def prepare(rig: uds.SmokeRig) -> None:
        rig.fakes.clients[0].on_user_data = lambda key: print(f"subscribing {key}")

    code, document = _dry_run(tmp_path, prepare)
    assert code == uds.EXIT_FAILED
    assert document["log_scan"]["findings"]["listen_key"] >= 1
    assert document["acceptance"]["g"]["result"] == "FAIL"
    assert TEST_ONLY_LISTEN_KEY not in json.dumps(document)


def test_scan_for_secrets_counts_each_kind_and_the_signature_shape() -> None:
    held = {"api_key": ("TestOnlyKeyValue0001",), "api_secret": ("TestOnlySecret0002",)}
    texts = [
        "x TestOnlyKeyValue0001 y TestOnlyKeyValue0001",
        f"?signature={'ab' * 32} TestOnlySecret0002",
        "nothing here",
    ]
    assert uds.scan_for_secrets(texts, held) == {
        "api_key": 2,
        "api_secret": 1,
        "listen_key": 0,
        "signature": 1,
    }


def test_the_log_scan_counts_never_carry_a_value(valid_document: dict[str, Any]) -> None:
    scan = valid_document["log_scan"]
    assert set(scan["findings"]) == {"api_key", "api_secret", "listen_key", "signature"}
    assert all(isinstance(v, int) for v in scan["findings"].values())


# --------------------------------------------------------------------------- #
# The far order.
# --------------------------------------------------------------------------- #


def _filters(**overrides: Any) -> SymbolFilters:
    values: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "contract_type": "PERPETUAL",
        "status": "TRADING",
        "onboard_time_utc": None,
        "price_tick_size": Decimal("0.10"),
        "quantity_step_size": Decimal("0.001"),
        "min_quantity": Decimal("0.001"),
        "max_quantity": Decimal("1000"),
        "min_notional": Decimal("100"),
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "margin_asset": "USDT",
        "notional_constraints_json": "{}",
        "order_capabilities_json": "[]",
        "position_mode_snapshot_json": "{}",
        "percent_price_multiplier_up": Decimal("1.05"),
        "percent_price_multiplier_down": Decimal("0.95"),
        "percent_price_multiplier_decimals": 4,
    }
    values.update(overrides)
    return SymbolFilters(**values)


MARK = Decimal("60000.05")


def test_the_far_price_is_floored_on_the_tick_grid() -> None:
    assert uds.far_order_price(MARK, Decimal("0.96"), Decimal("0.10")) == Decimal("57600.00")
    assert uds.far_order_price(Decimal("101.27"), Decimal("0.5"), Decimal("0.05")) == Decimal(
        "50.60"
    )


def test_a_valid_far_order_has_no_problem() -> None:
    order, problems = uds.plan_far_order(
        _filters(), mark=MARK, quantity=Decimal("0.002"), fraction=Decimal("0.96")
    )
    assert problems == []
    assert order.notional == order.price * Decimal("0.002")


@pytest.mark.parametrize(
    ("filters", "quantity", "fraction", "fragment"),
    [
        (_filters(), Decimal("0.002"), Decimal("0.90"), "PERCENT_PRICE band"),
        (
            _filters(percent_price_multiplier_down=None, percent_price_multiplier_up=None),
            Decimal("0.002"),
            Decimal("0.96"),
            "no PERCENT_PRICE band",
        ),
        (_filters(), Decimal("0.0005"), Decimal("0.96"), "below the minimum quantity"),
        (_filters(), Decimal("2000"), Decimal("0.96"), "above the maximum quantity"),
        (_filters(), Decimal("0.0025"), Decimal("0.96"), "not on the step grid"),
        (_filters(), Decimal("0.001"), Decimal("0.96"), "below the minimum notional"),
        (_filters(status="SETTLING"), Decimal("0.002"), Decimal("0.96"), "not TRADING"),
        (_filters(), Decimal("0.002"), Decimal("0.0000001"), "not positive"),
    ],
    ids=["band", "no-band", "min-qty", "max-qty", "step", "notional", "status", "zero-price"],
)
def test_every_far_order_refusal(
    filters: SymbolFilters, quantity: Decimal, fraction: Decimal, fragment: str
) -> None:
    _, problems = uds.plan_far_order(filters, mark=MARK, quantity=quantity, fraction=fraction)
    assert any(fragment in problem for problem in problems), problems


# --------------------------------------------------------------------------- #
# The forced transport drop (aiohttp attribute pin, as tests/test_paper_ws_smoke_evidence.py).
# --------------------------------------------------------------------------- #


class _Recorder:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


def test_drop_transport_closes_the_response_that_backs_the_websocket() -> None:
    response = _Recorder()
    connection = types.SimpleNamespace(
        websocket=types.SimpleNamespace(_response=response), close_initiated=False
    )
    uds._drop_transport(connection)
    assert response.closed == 1
    assert connection.close_initiated is False, "the SDK must still see an unsolicited close"


def test_aiohttp_still_keeps_the_response_on_the_websocket_object() -> None:
    # Contract: the transport drop reaches the TCP connection through this attribute path.
    source = inspect.getsource(aiohttp.ClientWebSocketResponse.__init__)
    assert "self._response = response" in source
    assert hasattr(aiohttp.ClientResponse, "close")


def test_the_script_never_calls_an_sdk_close_api_to_drop() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    drop = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_drop_transport"
    )
    called = {
        node.func.attr
        for node in ast.walk(drop)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called == {"close"}
    assert "close_connection" not in ast.unparse(drop)


# --------------------------------------------------------------------------- #
# One REST gate per run (user record 18-DEC-O-18-01.md and its amendment of 2026-10-16).
# --------------------------------------------------------------------------- #


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _calls(node: ast.AST, name: str) -> list[ast.Call]:
    found = []
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            func = call.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if called == name:
                found.append(call)
    return found


@pytest.mark.parametrize("builder", ["build_live_rig", "build_dry_run_rig"])
def test_each_rig_builder_constructs_exactly_one_rest_gate(builder: str) -> None:
    function = _function(builder)
    assert len(_calls(function, "RestRateLimitGate")) == 1
    gate_names = {
        target.id
        for node in ast.walk(function)
        if isinstance(node, ast.Assign) and _calls(node.value, "RestRateLimitGate")
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert gate_names == {"gate"}


@pytest.mark.parametrize(
    ("builder", "holders"),
    [
        ("build_live_rig", ("BinanceUsdmAdapter", "BinancePublicMarketData", "SdkListenKeyPort")),
        ("build_dry_run_rig", ("BinancePublicMarketData", "SdkListenKeyPort", "DryRunOrders")),
    ],
)
def test_every_rest_holder_of_a_rig_gets_the_one_gate(
    builder: str, holders: tuple[str, ...]
) -> None:
    function = _function(builder)
    for holder in holders:
        calls = _calls(function, holder)
        assert calls, holder
        for call in calls:
            gates = [kw.value for kw in call.keywords if kw.arg in {"rest_gate", "gate"}]
            assert len(gates) == 1 and isinstance(gates[0], ast.Name), holder
            assert gates[0].id == "gate", holder


def test_the_supervisor_and_the_rig_share_the_gate() -> None:
    stream_start = next(
        n
        for n in ast.walk(ast.parse(SCRIPT_PATH.read_text(encoding="utf-8")))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "stream_start"
    )
    (call,) = _calls(stream_start, "UserDataSupervisor")
    (gate,) = [kw.value for kw in call.keywords if kw.arg == "rest_gate"]
    assert ast.unparse(gate) == "self.rig.rest_gate"


def test_the_live_rig_runs_the_environment_guard_before_returning() -> None:
    function = _function("build_live_rig")
    source = ast.unparse(function)
    assert "binance_client.assert_environment(bundle)" in source
    assert "assert_stream_url(stream_config.stream_url, environment)" in source
    assert _calls(function, "GuardedTransport") and _calls(function, "GuardedOrders")
    assert _calls(function, "install_sdk_noise_guard")


def test_the_verdict_never_turns_fake_evidence_into_a_real_smoke(
    valid_document: dict[str, Any],
) -> None:
    verdict = uds.smoke_acceptance_verdict(valid_document)
    assert all(entry["proof_class"] != "REAL_SMOKE" for entry in verdict.values())
    assert valid_document["proof_class"] == "FAKE"


def test_started_at_is_an_aware_utc_time(valid_document: dict[str, Any]) -> None:
    started = datetime.fromisoformat(valid_document["started_at_utc"])
    assert started.tzinfo is not None and started.utcoffset() == UTC.utcoffset(None)
