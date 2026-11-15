"""The first Phase 22 owner opt-in case, on fakes and virtual time (plan 22-05, D-18).

`symbol_config_change_to_isolated` changes a FLAT symbol to ISOLATED and the owner's leverage and
records every answer. Everything runs offline on `FakeProbePort` / `RecordingProbePort` and on
virtual time; nothing reaches Binance and no agent runs the case: the owner does (AGENTS.md).
The FAKE symbol configuration is the account default Demo showed on 2026-10-04 (BTCUSDT x20
CROSSED, demo-observed, not mainnet). The FAKE answers prove the case logic only [DESIGN]; they
are not Demo evidence (D-19).
"""

from __future__ import annotations

import ast
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from scripts import demo_probe as dp
from src.ops.operator_evidence import load_demo_order_limits

from tests.probe_fakes import (
    TEST_ONLY_CONFIG_LEVERAGE,
    FakeProbePort,
    error_observation,
    ok_observation,
    write_probe_limits,
)
from tests.test_demo_probe_capture_cases import case, make_config, run_cases, sent
from tests.test_demo_probe_sj1_cases import case_part, sub

CONFIG = "symbol_config_change_to_isolated"
CONFIG_KEY = "symbol_config_change"
BALANCE = "available_balance_with_resting_order"
BALANCE_KEY = "available_balance_resting"
MARGIN_TYPE = "margin_type_change_with_resting_order"
LEVERAGE_MAX = "leverage_above_bracket_maximum"
MARGIN_TARGET = "margin_insufficient_at_target_leverage"
LIQUIDATION = "isolated_position_liquidation_price"
SJ3_IDS = (CONFIG, MARGIN_TYPE, LEVERAGE_MAX, MARGIN_TARGET, BALANCE, LIQUIDATION)
SJ3_KEYS = {
    CONFIG: CONFIG_KEY,
    MARGIN_TYPE: "margin_type_resting_order",
    LEVERAGE_MAX: "leverage_above_max",
    MARGIN_TARGET: "margin_insufficient_target",
    BALANCE: BALANCE_KEY,
    LIQUIDATION: "isolated_liquidation",
}
CONFIG_MUTATIONS = ("change_margin_type", "change_initial_leverage")
MUTATIONS = ("new_limit_order", "new_market_order", "cancel_order", *CONFIG_MUTATIONS)
CHANGE_OPERATIONS = ("change_margin_type", "change_initial_leverage")
SEQUENCE_OPERATIONS = ("symbol_config", *CHANGE_OPERATIONS)
ORDER_PREFIXES = ("new_", "cancel_")


def case_calls(port: FakeProbePort) -> list[str]:
    """The port calls before the runner's first cleanup (all of them if it never cleans up)."""
    names = port.names()
    if "cancel_all_open_orders" in names:
        return case_part(port)
    return names


def case_sequence(port: FakeProbePort) -> list[str]:
    """The configuration reads and changes of the case itself, in the order they were sent."""
    return [name for name in case_calls(port) if name in SEQUENCE_OPERATIONS]


def errors(document: dict[str, Any]) -> list[str]:
    return [item["case_id"] for item in document["cases"] if item["status"] == dp.ERROR]


# --------------------------------------------------------------------------- #
# Registry, loader wiring, dry run.
# --------------------------------------------------------------------------- #


def test_the_case_is_registered_with_its_own_key_and_handler() -> None:
    assert dp.SJ3_CASES == SJ3_IDS  # the plan's order, all after SJ2 and before the GTD case
    assert dp.OPTIONAL_CASES[CONFIG_KEY] == CONFIG
    assert dp.CASE_HANDLERS[CONFIG] is dp.case_symbol_config_change_to_isolated
    assert set(dp.CASE_HANDLERS) == set(dp.CASE_ORDER)
    order = list(dp.CASE_ORDER)
    assert order[-1] == "gtd_entry_expiry_status"  # the case that waits runs last
    assert order[-1 - len(dp.SJ3_CASES) : -1] == list(dp.SJ3_CASES)  # right before the GTD case
    assert order.index("income_history_read") + 1 == order.index(CONFIG)
    assert dp.FIXTURE_CASES == (
        *dp.CAPTURE_CASES,
        *dp.SJ1_CASES,
        *dp.SJ2_CASES,
        *dp.SJ3_CASES,
    )
    assert not set(dp.SJ3_CASES) & (set(dp.CAPTURE_CASES) | set(dp.SJ1_CASES) | set(dp.SJ2_CASES))


def test_both_configuration_changes_are_mutating_operations() -> None:
    assert set(CHANGE_OPERATIONS) <= dp.MUTATING_OPERATIONS
    assert "symbol_config" not in dp.MUTATING_OPERATIONS  # the read stays a read


async def test_a_dry_run_plans_both_changes_and_sends_nothing(tmp_path: Path) -> None:
    config = make_config(tmp_path, case_ids=tuple(dp.OPTIONAL_CASES.values()), execute=False)
    recorder = dp.ProbeRecorder()
    await dp.run_probe(config, dp.build_dry_run_rig(config), recorder)
    document = recorder.document(config)
    record = case(document, CONFIG)
    assert record["status"] == dp.NOT_REHEARSED
    assert not errors(document)
    planned = {item["operation"]: item for item in record["planned_requests"]}
    assert set(CHANGE_OPERATIONS) <= set(planned)
    assert all(planned[name]["mutating"] is True for name in CHANGE_OPERATIONS)
    assert planned["change_margin_type"]["kwargs"]["margin_type"] == "ISOLATED"
    assert planned["change_initial_leverage"]["kwargs"]["leverage"] == TEST_ONLY_CONFIG_LEVERAGE


# --------------------------------------------------------------------------- #
# The tracer: flag and owner key -> case -> port -> recorded answers.
# --------------------------------------------------------------------------- #


async def test_the_tracer_changes_a_flat_symbol_once_and_records_every_answer(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, code = await run_cases(tmp_path, port, CONFIG)
    record = case(document, CONFIG)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    assert case_sequence(port) == [
        "symbol_config",
        "change_margin_type",
        "change_initial_leverage",
        "symbol_config",
    ]
    assert sent(port, "change_margin_type") == [{"symbol": "BTCUSDT", "margin_type": "ISOLATED"}]
    assert sent(port, "change_initial_leverage") == [
        {"symbol": "BTCUSDT", "leverage": TEST_ONLY_CONFIG_LEVERAGE}
    ]
    details = record["details"]
    assert details["config_before_margin_type"] == "CROSSED"
    assert details["config_before_leverage"] == "20"
    assert details["previous_margin_type"] == "CROSSED"
    assert details["previous_leverage"] == "20"
    assert details["already_at_target"] == "false"
    assert details["requested_leverage"] == str(TEST_ONLY_CONFIG_LEVERAGE)
    assert details["margin_type_answer_accepted"] == "true"
    assert details["margin_type_answer_code"] == "200"
    assert details["leverage_answer_accepted"] == "true"
    assert details["leverage_answer_leverage"] == str(TEST_ONLY_CONFIG_LEVERAGE)
    assert details["leverage_answer_maxNotionalValue"] == "5000000"
    assert details["config_after_margin_type"] == "ISOLATED"
    assert details["config_after_leverage"] == str(TEST_ONLY_CONFIG_LEVERAGE)
    assert details["config_after_margin_type_equals_ISOLATED"] == "true"
    # no order, no cancel inside the case itself, and nothing is restored afterwards
    assert not [name for name in case_calls(port) if name.startswith(ORDER_PREFIXES)]
    assert port.config_margin_type == "ISOLATED"
    assert any("NOT restored" in note for note in record["notes"])


async def test_the_casing_the_exchange_wrote_is_recorded_as_read(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "symbol_config",
        ok_observation("symbol_config", {"0.marginType": "cross", "0.leverage": "20"}),
        ok_observation(
            "symbol_config",
            {"0.marginType": "isolated", "0.leverage": "5", "0.maxNotionalValue": "250000"},
        ),
    )
    document, _ = await run_cases(tmp_path, port, CONFIG)
    details = case(document, CONFIG)["details"]
    assert details["config_before_margin_type"] == "cross"
    assert details["config_after_margin_type"] == "isolated"
    assert details["config_after_max_notional_value"] == "250000"
    assert details["config_after_margin_type_equals_ISOLATED"] == "false"


async def test_a_symbol_already_at_the_target_still_gets_both_requests(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.config_margin_type = "ISOLATED"
    port.config_leverage = str(TEST_ONLY_CONFIG_LEVERAGE)
    document, _ = await run_cases(tmp_path, port, CONFIG)
    record = case(document, CONFIG)
    assert record["status"] == dp.OBSERVED
    assert record["details"]["already_at_target"] == "true"
    assert len(sent(port, "change_margin_type")) == 1
    assert len(sent(port, "change_initial_leverage")) == 1


async def test_an_exchange_error_is_the_evidence_and_the_case_stays_observed(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script(
        "change_margin_type",
        error_observation(
            "change_margin_type",
            code=-4046,
            category="REJECTED_DEFINITIVE",
            message="FAKE No need to change margin type.",
        ),
    )
    document, _ = await run_cases(tmp_path, port, CONFIG)
    record = case(document, CONFIG)
    assert record["status"] == dp.OBSERVED
    details = record["details"]
    assert details["margin_type_answer_accepted"] == "false"
    assert "-4046" in details["margin_type_answer_error_code"]
    assert details["margin_type_answer_error_class"] == "BAD_REQUEST"
    assert len(sent(port, "change_margin_type")) == 1  # never re-sent
    assert len(sent(port, "change_initial_leverage")) == 1  # the next request is still asked
    assert details["config_after_margin_type"] == "CROSSED"  # the fake kept the old value


# --------------------------------------------------------------------------- #
# What the case must NOT do.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("operation", "summary"),
    [
        ("open_orders", {"count": "1", "row_0_client_order_id": "foreign-order"}),
        ("open_algo_orders", {"count": "1", "row_0_client_algo_id": "foreign-algo"}),
        (
            "positions",
            {
                "count": "1",
                "row_0_symbol": "BTCUSDT",
                "row_0_position_side": "BOTH",
                "row_0_position_amt": "0.001",
            },
        ),
    ],
)
async def test_a_symbol_that_is_not_flat_is_never_changed(
    tmp_path: Path, operation: str, summary: dict[str, str]
) -> None:
    port = FakeProbePort()
    # call 0 is the run-start preflight (flat), call 1 the precheck of the case
    port.script_call(operation, 1, ok_observation(operation, summary))
    document, _ = await run_cases(tmp_path, port, CONFIG)
    record = case(document, CONFIG)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"].startswith(dp.REASON_NOT_FLAT_CASE.split("{")[0])
    assert [name for name in port.names() if name in CHANGE_OPERATIONS] == []
    assert case_sequence(port) == []  # not even the read of the configuration


async def test_an_unreadable_previous_configuration_changes_nothing(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "symbol_config",
        error_observation("symbol_config", code=-1000, category="UNKNOWN_EXCHANGE_ERROR"),
    )
    document, _ = await run_cases(tmp_path, port, CONFIG)
    record = case(document, CONFIG)
    assert record["status"] == dp.NOT_OBSERVED
    assert "previous configuration could not be read" in record["reason"]
    assert [name for name in port.names() if name in CHANGE_OPERATIONS] == []


async def test_a_hedge_mode_account_is_not_observed_and_nothing_is_changed(
    tmp_path: Path,
) -> None:
    port = FakeProbePort(dual_side=True)
    document, _ = await run_cases(tmp_path, port, CONFIG)
    record = case(document, CONFIG)
    assert record["status"] == dp.NOT_OBSERVED
    assert [name for name in port.names() if name in CHANGE_OPERATIONS] == []


async def test_a_rate_limit_answer_to_the_first_change_stops_the_case(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "change_margin_type",
        error_observation(
            "change_margin_type",
            code=-1003,
            category="RATE_LIMITED",
            http_class="TOO_MANY_429",
            retry_after_seconds=30,
            message="FAKE Too many requests.",
        ),
    )
    document, _ = await run_cases(tmp_path, port, CONFIG)
    assert case(document, CONFIG)["status"] != dp.OBSERVED
    assert len(sent(port, "change_margin_type")) == 1
    assert sent(port, "change_initial_leverage") == []


async def test_an_executed_run_with_fixtures_writes_the_change_answers(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, CONFIG, fixtures=True)
    assert case(document, CONFIG)["status"] == dp.OBSERVED
    names = sorted(path.name for path in (tmp_path / "fixtures").iterdir())
    assert any("change_margin_type" in name for name in names)
    assert any("change_initial_leverage" in name for name in names)


# --------------------------------------------------------------------------- #
# The owner key.
# --------------------------------------------------------------------------- #


def test_the_probe_limits_writer_gives_the_key_only_with_the_flag(tmp_path: Path) -> None:
    with_flag = write_probe_limits(sub(tmp_path, "a"), optional=(CONFIG_KEY,))
    without = write_probe_limits(sub(tmp_path, "b"), optional=())
    assert f"config_target_leverage = {TEST_ONLY_CONFIG_LEVERAGE}" in with_flag.read_text(
        encoding="utf-8"
    )
    assert "config_target_leverage" not in without.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Plan 22-09, the tracer: available_balance_with_resting_order (assumption A1).
# --------------------------------------------------------------------------- #

APPROVED = Decimal("0.002")
FAKE_ORDER_MARGIN = Decimal("4.8")  # a FAKE resting-order margin: the fake's own arithmetic


def far_resting_port() -> FakeProbePort:
    """A fake whose account answer moves by a made-up margin per resting order (not Demo)."""
    port = FakeProbePort()
    port.resting_order_margin = FAKE_ORDER_MARGIN
    return port


def test_the_balance_case_is_registered_with_its_own_key_and_handler() -> None:
    assert BALANCE in dp.SJ3_CASES
    assert dp.OPTIONAL_CASES[BALANCE_KEY] == BALANCE
    assert dp.CASE_HANDLERS[BALANCE] is dp.case_available_balance_with_resting_order
    assert BALANCE in dp.FIXTURE_CASES
    assert dp.CASE_ORDER[-1] == "gtd_entry_expiry_status"


async def test_the_balance_case_dry_run_plans_one_order_and_one_cancel(tmp_path: Path) -> None:
    config = make_config(tmp_path, case_ids=tuple(dp.OPTIONAL_CASES.values()), execute=False)
    recorder = dp.ProbeRecorder()
    await dp.run_probe(config, dp.build_dry_run_rig(config), recorder)
    document = recorder.document(config)
    record = case(document, BALANCE)
    assert record["status"] == dp.NOT_REHEARSED
    assert not errors(document)
    planned = [item["operation"] for item in record["planned_requests"]]
    assert planned.count("new_limit_order") == 1
    assert planned.count("cancel_order") == 1


async def test_the_tracer_records_the_exact_deltas_around_one_far_resting_order(
    tmp_path: Path,
) -> None:
    port = far_resting_port()
    document, code = await run_cases(tmp_path, port, BALANCE)
    record = case(document, BALANCE)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    # one placement, one cancel, the account read before and after the order (while it rests)
    orders = sent(port, "new_limit_order")
    assert len(orders) == 1 and len(sent(port, "cancel_order")) == 1
    assert orders[0]["side"] == "BUY" and orders[0]["quantity"] == APPROVED
    assert orders[0]["reduce_only"] is None  # a normal entry-shaped order, not reduce-only
    assert orders[0]["price"] * orders[0]["quantity"] <= Decimal("150")
    sequence = [
        name
        for name in case_calls(port)
        if name in ("symbol_config", "account_information", "new_limit_order", "cancel_order")
    ]
    assert sequence == [
        "symbol_config",
        "account_information",
        "new_limit_order",
        "account_information",
        "cancel_order",
    ]
    details = record["details"]
    assert details["config_margin_type"] == "CROSSED" and details["config_leverage"] == "20"
    assert details["available_balance_before"] == "5000.00000000"
    assert details["available_balance_after"] == "4995.20000000"
    assert details["available_balance_delta"] == "-4.80000000"
    assert details["total_open_order_initial_margin_before"] == "0.0"
    assert details["total_open_order_initial_margin_after"] == "4.8"
    assert details["open_order_margin_delta"] == "4.8"
    assert details["quote_asset_before"] == "USDT"
    assert details["quote_row_open_order_initial_margin_after"] == "4.8"
    assert details["quote_row_open_order_margin_delta"] == "4.8"
    assert Decimal(details["implied_notional"]) == APPROVED * orders[0]["price"]
    assert Decimal(details["implied_initial_margin"]) == FAKE_ORDER_MARGIN  # notional / 20
    assert details["available_decreased"] == "true"
    assert details["open_order_margin_increased"] == "true"
    assert details["order_accepted"] == "true" and details["cancel_accepted"] == "true"
    assert not any("verdict" in key or "tolerance" in key for key in details)
    assert any("no conclusion" in note for note in record["notes"])


async def test_an_account_that_does_not_move_is_recorded_as_no_change_not_as_a_verdict(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()  # the static account answer: nothing moves with a resting order
    document, _ = await run_cases(tmp_path, port, BALANCE)
    details = case(document, BALANCE)["details"]
    assert Decimal(details["available_balance_delta"]) == 0
    assert details["open_order_margin_delta"].startswith("NOT_OBSERVED")  # the fake has no figure
    assert details["available_decreased"] == "false"


async def test_a_missing_figure_is_not_observed_text_and_never_zero(tmp_path: Path) -> None:
    port = far_resting_port()
    thin = ok_observation("account_information", {"totalWalletBalance": "5000.00000000"})
    port.script("account_information", thin, thin)
    document, _ = await run_cases(tmp_path, port, BALANCE)
    record = case(document, BALANCE)
    assert record["status"] == dp.OBSERVED
    details = record["details"]
    assert details["available_balance_before"].startswith("NOT_OBSERVED")
    assert details["quote_row_open_order_initial_margin_after"].startswith("NOT_OBSERVED")
    assert details["available_balance_delta"].startswith("NOT_OBSERVED")
    assert details["open_order_margin_delta"].startswith("NOT_OBSERVED")
    assert details["available_decreased"] == "NOT_OBSERVED"
    assert details["open_order_margin_increased"] == "NOT_OBSERVED"


async def test_a_rejected_order_is_recorded_and_the_account_is_still_read_after(
    tmp_path: Path,
) -> None:
    port = far_resting_port()
    port.script(
        "new_limit_order",
        error_observation(
            "new_limit_order", code=-2019, category="REJECTED_DEFINITIVE", message="FAKE margin"
        ),
    )
    document, _ = await run_cases(tmp_path, port, BALANCE)
    record = case(document, BALANCE)
    assert record["status"] == dp.OBSERVED
    details = record["details"]
    assert details["order_accepted"] == "false"
    assert "-2019" in details["order_error_code"]
    assert port.count("account_information") == 2  # before and after, even with a rejection
    assert sent(port, "cancel_order") == []  # nothing was open: nothing to cancel
    assert len(sent(port, "new_limit_order")) == 1  # never re-sent


async def test_an_order_above_the_owner_notional_cap_is_refused_before_it_is_sent(
    tmp_path: Path,
) -> None:
    port = far_resting_port()
    document, _ = await run_cases(tmp_path, port, BALANCE, cap="1")
    record = case(document, BALANCE)
    assert record["status"] == dp.ERROR and "order bound" in record["reason"]
    assert sent(port, "new_limit_order") == []
    assert port.count("account_information") == 0


@pytest.mark.parametrize(
    ("operation", "summary"),
    [
        ("open_orders", {"count": "1", "row_0_client_order_id": "foreign-order"}),
        ("open_algo_orders", {"count": "1", "row_0_client_algo_id": "foreign-algo"}),
        (
            "positions",
            {
                "count": "1",
                "row_0_symbol": "BTCUSDT",
                "row_0_position_side": "BOTH",
                "row_0_position_amt": "0.001",
            },
        ),
    ],
)
async def test_the_balance_case_sends_nothing_on_a_symbol_that_is_not_flat(
    tmp_path: Path, operation: str, summary: dict[str, str]
) -> None:
    port = far_resting_port()
    port.script_call(operation, 1, ok_observation(operation, summary))
    document, _ = await run_cases(tmp_path, port, BALANCE)
    record = case(document, BALANCE)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"].startswith(dp.REASON_NOT_FLAT_CASE.split("{")[0])
    assert [name for name in case_calls(port) if name.startswith(ORDER_PREFIXES)] == []
    assert port.count("account_information") == 0


async def test_the_balance_case_on_a_hedge_account_is_not_observed(tmp_path: Path) -> None:
    port = FakeProbePort(dual_side=True)
    document, _ = await run_cases(tmp_path, port, BALANCE)
    assert case(document, BALANCE)["status"] == dp.NOT_OBSERVED
    assert sent(port, "new_limit_order") == []


def test_the_probe_limits_writer_needs_no_extra_owner_number_for_the_balance_key(
    tmp_path: Path,
) -> None:
    text = write_probe_limits(tmp_path, optional=(BALANCE_KEY,)).read_text(encoding="utf-8")
    assert f"{BALANCE_KEY} = true" in text
    assert "config_target_leverage" not in text and "insufficient_margin_quantity" not in text


# --------------------------------------------------------------------------- #
# Plan 22-09, task 2: the registry of all six cases and the dry run.
# --------------------------------------------------------------------------- #


def test_all_six_cases_have_their_own_key_handler_and_fixture_listing() -> None:
    assert list(SJ3_KEYS.values()) == [key for key in dp.OPTIONAL_CASES if key in SJ3_KEYS.values()]
    for case_id, key in SJ3_KEYS.items():
        assert dp.OPTIONAL_CASES[key] == case_id
        assert case_id in dp.CASE_HANDLERS and case_id in dp.FIXTURE_CASES
        assert dp.CASE_ORDER.count(case_id) == 1
    assert dp.CASE_ORDER[-1] == "gtd_entry_expiry_status"
    assert set(dp.CASE_HANDLERS) == set(dp.CASE_ORDER)


async def test_a_dry_run_ends_every_sj3_case_not_rehearsed_with_no_error(tmp_path: Path) -> None:
    config = make_config(tmp_path, case_ids=tuple(dp.OPTIONAL_CASES.values()), execute=False)
    recorder = dp.ProbeRecorder()
    await dp.run_probe(config, dp.build_dry_run_rig(config), recorder)
    document = recorder.document(config)
    assert not errors(document)
    for case_id in SJ3_IDS:
        record = case(document, case_id)
        assert record["status"] == dp.NOT_REHEARSED, case_id
        assert record["observations"] == [], case_id  # the canned answers are dropped


def test_the_probe_never_computes_a_liquidation_price_or_imports_the_risk_modules() -> None:
    source = Path(dp.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not [name for name in imported if name.startswith(("src.risk", "src.core"))]
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "liquidation_price" not in called  # the exchange's figure is recorded, never computed
    start = source.index("def _record_liquidation_inputs")
    handler = source[start : source.index("def _account_figure", start)]
    assert "float(" not in handler and "Decimal(" not in handler  # records text, computes nothing


# --------------------------------------------------------------------------- #
# margin_type_change_with_resting_order (D-04 evidence, key margin_type_resting_order).
# --------------------------------------------------------------------------- #


def margin_type_calls(port: FakeProbePort) -> list[str]:
    return [name for name in case_calls(port) if name in MUTATIONS or name == "symbol_config"]


async def test_a_refused_margin_type_change_is_the_evidence_and_is_sent_once(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script(
        "change_margin_type",
        error_observation(
            "change_margin_type",
            code=-4047,
            category="REJECTED_DEFINITIVE",
            message="FAKE Margin type cannot be changed if there exists open orders.",
        ),
    )
    document, _ = await run_cases(tmp_path, port, MARGIN_TYPE)
    record = case(document, MARGIN_TYPE)
    assert record["status"] == dp.OBSERVED
    assert margin_type_calls(port) == [
        "symbol_config",
        "new_limit_order",
        "change_margin_type",
        "cancel_order",
        "symbol_config",
    ]
    assert sent(port, "change_margin_type") == [{"symbol": "BTCUSDT", "margin_type": "ISOLATED"}]
    assert len(sent(port, "new_limit_order")) == 1 and len(sent(port, "cancel_order")) == 1
    details = record["details"]
    assert details["previous_margin_type"] == "CROSSED"
    assert details["requested_margin_type"] == "ISOLATED"
    assert details["order_accepted"] == "true" and details["cancel_accepted"] == "true"
    assert details["change_accepted"] == "false"
    assert "-4047" in details["change_error_code"]
    assert details["change_error_class"] == "BAD_REQUEST"
    assert "restore_accepted" not in details  # nothing was changed: nothing to undo
    assert details["config_before_margin_type"] == "CROSSED"
    assert details["config_after_margin_type"] == "CROSSED"
    assert port.config_margin_type == "CROSSED"
    assert sent(port, "change_initial_leverage") == []  # the leverage is never touched
    order = sent(port, "new_limit_order")[0]
    assert order["quantity"] == APPROVED and order["side"] == "BUY"


async def test_an_accepted_margin_type_change_is_reversed_once_and_recorded(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()  # the fake accepts a change by default: the "surprise" branch
    document, _ = await run_cases(tmp_path, port, MARGIN_TYPE)
    record = case(document, MARGIN_TYPE)
    assert record["status"] == dp.OBSERVED
    assert [call["margin_type"] for call in sent(port, "change_margin_type")] == [
        "ISOLATED",
        "CROSSED",
    ]
    details = record["details"]
    assert details["change_accepted"] == "true" and details["restore_accepted"] == "true"
    assert details["config_after_margin_type"] == "ISOLATED"  # as read before the undo
    assert details["config_restored_margin_type"] == "CROSSED"
    assert port.config_margin_type == "CROSSED"
    assert sent(port, "change_initial_leverage") == []


async def test_an_isolated_symbol_is_asked_for_the_opposite_type_whatever_the_casing(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script(
        "symbol_config",
        ok_observation("symbol_config", {"0.marginType": "isolated", "0.leverage": "5"}),
    )
    document, _ = await run_cases(tmp_path, port, MARGIN_TYPE)
    assert case(document, MARGIN_TYPE)["status"] == dp.OBSERVED
    requested = [call["margin_type"] for call in sent(port, "change_margin_type")]
    assert requested[0] == "CROSSED"  # the opposite of ISOLATED
    assert requested[1:] == ["ISOLATED"]  # the undo of the accepted change, the original type


async def test_a_margin_type_change_is_never_sent_without_a_resting_order(tmp_path: Path) -> None:
    rejected = FakeProbePort()
    rejected.script(
        "new_limit_order",
        error_observation("new_limit_order", code=-2019, category="REJECTED_DEFINITIVE"),
    )
    document, _ = await run_cases(tmp_path, rejected, MARGIN_TYPE)
    record = case(document, MARGIN_TYPE)
    assert record["status"] == dp.NOT_OBSERVED and "no margin-type change" in record["reason"]
    assert sent(rejected, "change_margin_type") == []
    filled = FakeProbePort()
    filled.script(
        "new_limit_order",
        ok_observation("new_limit_order", {"client_order_id": "x", "status": "FILLED"}),
    )
    other = sub(tmp_path, "filled")
    document2, _ = await run_cases(other, filled, MARGIN_TYPE)
    assert case(document2, MARGIN_TYPE)["status"] == dp.NOT_OBSERVED
    assert sent(filled, "change_margin_type") == []


async def test_an_unreadable_or_unknown_margin_type_sends_nothing(tmp_path: Path) -> None:
    unreadable = FakeProbePort()
    unreadable.script(
        "symbol_config",
        error_observation("symbol_config", code=-1000, category="UNKNOWN_EXCHANGE_ERROR"),
    )
    document, _ = await run_cases(tmp_path, unreadable, MARGIN_TYPE)
    assert case(document, MARGIN_TYPE)["status"] == dp.NOT_OBSERVED
    assert [n for n in case_calls(unreadable) if n in MUTATIONS] == []
    weird = FakeProbePort()
    weird.script("symbol_config", ok_observation("symbol_config", {"0.marginType": "PORTFOLIO"}))
    document2, _ = await run_cases(sub(tmp_path, "weird"), weird, MARGIN_TYPE)
    assert case(document2, MARGIN_TYPE)["status"] == dp.NOT_OBSERVED
    assert [n for n in case_calls(weird) if n in MUTATIONS] == []


NOT_FLAT_ANSWERS = [
    ("open_orders", {"count": "1", "row_0_client_order_id": "foreign-order"}),
    ("open_algo_orders", {"count": "1", "row_0_client_algo_id": "foreign-algo"}),
    (
        "positions",
        {
            "count": "1",
            "row_0_symbol": "BTCUSDT",
            "row_0_position_side": "BOTH",
            "row_0_position_amt": "0.001",
        },
    ),
]


@pytest.mark.parametrize("case_id", [MARGIN_TYPE, LEVERAGE_MAX, MARGIN_TARGET, LIQUIDATION])
@pytest.mark.parametrize(("operation", "summary"), NOT_FLAT_ANSWERS)
async def test_the_other_sj3_cases_send_nothing_on_a_symbol_that_is_not_flat(
    tmp_path: Path, case_id: str, operation: str, summary: dict[str, str]
) -> None:
    port = FakeProbePort()
    port.config_margin_type, port.config_leverage = "ISOLATED", str(TEST_ONLY_CONFIG_LEVERAGE)
    port.script_call(operation, 1, ok_observation(operation, summary))
    document, _ = await run_cases(tmp_path, port, case_id)
    record = case(document, case_id)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"].startswith(dp.REASON_NOT_FLAT_CASE.split("{")[0])
    assert [name for name in case_calls(port) if name in MUTATIONS] == []


@pytest.mark.parametrize("case_id", [MARGIN_TYPE, LEVERAGE_MAX, MARGIN_TARGET, LIQUIDATION])
async def test_the_other_sj3_cases_on_a_hedge_account_send_nothing(
    tmp_path: Path, case_id: str
) -> None:
    port = FakeProbePort(dual_side=True)
    document, _ = await run_cases(tmp_path, port, case_id)
    assert case(document, case_id)["status"] == dp.NOT_OBSERVED
    assert [name for name in port.names() if name in MUTATIONS[:2] + CONFIG_MUTATIONS] == []


async def test_the_margin_type_case_dry_run_plans_the_order_the_change_and_the_cancel(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, case_ids=(MARGIN_TYPE,), execute=False)
    recorder = dp.ProbeRecorder()
    await dp.run_probe(config, dp.build_dry_run_rig(config), recorder)
    planned = [
        item["operation"]
        for item in case(recorder.document(config), MARGIN_TYPE)["planned_requests"]
    ]
    assert planned[:3] == ["new_limit_order", "change_margin_type", "cancel_order"]


async def test_the_margin_type_case_refuses_an_order_above_the_notional_cap(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, MARGIN_TYPE, cap="1")
    record = case(document, MARGIN_TYPE)
    assert record["status"] == dp.ERROR and "order bound" in record["reason"]
    assert [name for name in case_calls(port) if name in MUTATIONS] == []


# --------------------------------------------------------------------------- #
# leverage_above_bracket_maximum (assumption A6, key leverage_above_max).
# --------------------------------------------------------------------------- #


async def test_a_refused_leverage_above_the_maximum_is_the_evidence_and_is_sent_once(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script(
        "change_initial_leverage",
        error_observation(
            "change_initial_leverage",
            code=-4028,
            category="REJECTED_DEFINITIVE",
            message="FAKE Leverage 126 is not valid",
        ),
    )
    document, _ = await run_cases(tmp_path, port, LEVERAGE_MAX)
    record = case(document, LEVERAGE_MAX)
    assert record["status"] == dp.OBSERVED
    assert sent(port, "change_initial_leverage") == [{"symbol": "BTCUSDT", "leverage": 126}]
    assert sent(port, "change_margin_type") == []
    assert sent(port, "new_limit_order") == [] and sent(port, "new_market_order") == []
    details = record["details"]
    assert details["bracket_one_initial_leverage"] == "125"  # read from the answer, not assumed
    assert details["previous_leverage"] == "20" and details["requested_leverage"] == "126"
    assert details["change_accepted"] == "false" and "-4028" in details["change_error_code"]
    assert "restore_accepted" not in details
    assert details["config_after_leverage"] == "20"
    assert port.config_leverage == "20"


async def test_an_accepted_leverage_above_the_maximum_is_reversed_once_and_recorded(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()  # the fake accepts any leverage: the "surprise" branch
    document, _ = await run_cases(tmp_path, port, LEVERAGE_MAX)
    record = case(document, LEVERAGE_MAX)
    assert record["status"] == dp.OBSERVED
    assert [call["leverage"] for call in sent(port, "change_initial_leverage")] == [126, 20]
    details = record["details"]
    assert details["change_accepted"] == "true" and details["restore_accepted"] == "true"
    assert details["config_after_change_leverage"] == "126"
    assert details["config_after_leverage"] == "20"
    assert port.config_leverage == "20"


async def test_the_maximum_is_the_initial_leverage_of_bracket_one_wherever_it_sits(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script(
        "leverage_brackets",
        ok_observation(
            "leverage_brackets",
            {
                "0.symbol": "BTCUSDT",
                "0.brackets.0.bracket": "2",
                "0.brackets.0.initialLeverage": "50",
                "0.brackets.1.bracket": "1",
                "0.brackets.1.initialLeverage": "75",
            },
        ),
    )
    await run_cases(tmp_path, port, LEVERAGE_MAX)
    assert sent(port, "change_initial_leverage")[0]["leverage"] == 76


@pytest.mark.parametrize(
    "summary",
    [
        {},
        {"0.brackets.0.bracket": "1"},
        {"0.brackets.0.bracket": "1", "0.brackets.0.initialLeverage": "abc"},
        {"0.brackets.0.bracket": "1", "0.brackets.0.initialLeverage": "12.5"},
        {"0.brackets.0.bracket": "2", "0.brackets.0.initialLeverage": "50"},
    ],
)
async def test_an_unreadable_maximum_sends_nothing(tmp_path: Path, summary: dict[str, str]) -> None:
    port = FakeProbePort()
    port.script("leverage_brackets", ok_observation("leverage_brackets", summary))
    document, _ = await run_cases(tmp_path, port, LEVERAGE_MAX)
    record = case(document, LEVERAGE_MAX)
    assert record["status"] == dp.NOT_OBSERVED and "maximum leverage" in record["reason"]
    assert sent(port, "change_initial_leverage") == []


async def test_an_unreadable_current_leverage_sends_nothing(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "symbol_config",
        error_observation("symbol_config", code=-1000, category="UNKNOWN_EXCHANGE_ERROR"),
    )
    document, _ = await run_cases(tmp_path, port, LEVERAGE_MAX)
    assert case(document, LEVERAGE_MAX)["status"] == dp.NOT_OBSERVED
    assert sent(port, "change_initial_leverage") == []


async def test_the_leverage_case_dry_run_plans_the_change_to_one_above_the_maximum(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, case_ids=(LEVERAGE_MAX,), execute=False)
    recorder = dp.ProbeRecorder()
    await dp.run_probe(config, dp.build_dry_run_rig(config), recorder)
    record = case(recorder.document(config), LEVERAGE_MAX)
    planned = [
        item
        for item in record["planned_requests"]
        if item["operation"] == "change_initial_leverage"
    ]
    # the first request is the case's own; the second is its undo (sent only if accepted)
    assert planned[0]["kwargs"]["leverage"] == 126 and planned[0]["mutating"] is True
    assert planned[1]["kwargs"]["leverage"] == 20


# --------------------------------------------------------------------------- #
# margin_insufficient_at_target_leverage (criterion 3 shape, key margin_insufficient_target).
# --------------------------------------------------------------------------- #

MARGIN_QUANTITY = Decimal("5")  # TEST_ONLY_MARGIN_QUANTITY


def isolated_port() -> FakeProbePort:
    port = FakeProbePort()
    port.config_margin_type = "ISOLATED"
    port.config_leverage = str(TEST_ONLY_CONFIG_LEVERAGE)
    return port


async def test_the_shortfall_order_is_the_owners_own_quantity_once_and_nothing_is_changed(
    tmp_path: Path,
) -> None:
    port = isolated_port()
    document, _ = await run_cases(tmp_path, port, MARGIN_TARGET)
    record = case(document, MARGIN_TARGET)
    assert record["status"] == dp.NOT_OBSERVED  # the fake accepts: the quantity did not exceed
    assert record["reason"] == dp.REASON_MARGIN_ACCEPTED
    orders = sent(port, "new_limit_order")
    assert len(orders) == 1 and orders[0]["quantity"] == MARGIN_QUANTITY
    assert orders[0]["side"] == "BUY" and orders[0]["reduce_only"] is None
    assert len(sent(port, "cancel_order")) == 1
    assert [name for name in port.names() if name in CONFIG_MUTATIONS] == []
    details = record["details"]
    assert details["target_config_target_leverage"] == str(TEST_ONLY_CONFIG_LEVERAGE)
    assert Decimal(details["target_leverage"]) == TEST_ONLY_CONFIG_LEVERAGE
    price = orders[0]["price"]
    assert Decimal(details["target_implied_notional"]) == MARGIN_QUANTITY * price
    assert Decimal(details["target_implied_initial_margin"]) == (
        MARGIN_QUANTITY * price / TEST_ONLY_CONFIG_LEVERAGE
    )
    assert details["target_available_balance_before"] == "5000.00000000"
    assert details["target_available_balance_after"] == "5000.00000000"
    assert details["target_order_accepted"] == "true"
    assert not any(key == "far_price" for key in details)  # its own prefix, not the neighbour's


async def test_a_refused_shortfall_order_is_the_evidence(tmp_path: Path) -> None:
    port = isolated_port()
    port.script(
        "new_limit_order",
        error_observation(
            "new_limit_order",
            code=-2019,
            category="REJECTED_DEFINITIVE",
            message="FAKE Margin is insufficient.",
        ),
    )
    document, _ = await run_cases(tmp_path, port, MARGIN_TARGET)
    record = case(document, MARGIN_TARGET)
    assert record["status"] == dp.OBSERVED
    assert "-2019" in record["details"]["target_order_error_code"]
    assert len(sent(port, "new_limit_order")) == 1 and sent(port, "cancel_order") == []


@pytest.mark.parametrize(
    ("margin_type", "leverage"),
    [("CROSSED", "5"), ("ISOLATED", "20"), ("CROSSED", "20")],
)
async def test_a_symbol_that_is_not_isolated_at_the_target_is_not_changed_here(
    tmp_path: Path, margin_type: str, leverage: str
) -> None:
    port = FakeProbePort()
    port.config_margin_type, port.config_leverage = margin_type, leverage
    document, _ = await run_cases(tmp_path, port, MARGIN_TARGET)
    record = case(document, MARGIN_TARGET)
    assert record["status"] == dp.NOT_OBSERVED
    assert "symbol_config_change_to_isolated first" in record["reason"]
    assert [name for name in port.names() if name in (*CONFIG_MUTATIONS, "new_limit_order")] == []
    assert record["details"]["target_config_margin_type"] == margin_type


async def test_the_lowercase_isolated_spelling_counts_as_isolated(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "symbol_config",
        ok_observation(
            "symbol_config",
            {"0.marginType": "isolated", "0.leverage": str(TEST_ONLY_CONFIG_LEVERAGE)},
        ),
    )
    document, _ = await run_cases(tmp_path, port, MARGIN_TARGET)
    assert len(sent(port, "new_limit_order")) == 1
    assert case(document, MARGIN_TARGET)["reason"] == dp.REASON_MARGIN_ACCEPTED


async def test_the_neighbour_case_keeps_its_details_and_its_own_key(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, "insufficient_margin_order")
    details = case(document, "insufficient_margin_order")["details"]
    assert "far_price" in details and "order_accepted" in details
    assert not any(key.startswith("target_") for key in details)


def test_the_shortfall_flow_refuses_a_quantity_when_neither_margin_key_is_on(
    tmp_path: Path,
) -> None:
    limits = load_demo_order_limits(
        write_probe_limits(tmp_path, optional=("available_balance_resting",)), kind="probe"
    )
    refusal = dp.margin_order_refusal(
        limits,
        quantity=MARGIN_QUANTITY,
        price=Decimal("48000"),
        ceiling_price=Decimal("48000"),
        step=Decimal("0.001"),
        flag="margin_insufficient_target",
    )
    assert refusal is not None and "margin_insufficient_target is not enabled" in refusal
    other = dp.margin_order_refusal(
        limits,
        quantity=MARGIN_QUANTITY,
        price=Decimal("48000"),
        ceiling_price=Decimal("48000"),
        step=Decimal("0.001"),
        flag="reduce_only_flat",
    )
    assert other is not None and "may send" in other


# --------------------------------------------------------------------------- #
# isolated_position_liquidation_price (assumption A3, key isolated_liquidation).
# --------------------------------------------------------------------------- #

FAKE_LIQUIDATION_ROW = {
    "entry_price": "60000.10",
    "mark_price": "60000.00",
    "liquidation_price": "48200.55",
    "break_even_price": "60030.00",
    "unrealized_profit": "-0.0002",
    "notional": "120.0002",
    "margin_asset": "USDT",
}
FAKE_ACCOUNT_POSITION = {
    "isolatedMargin": "24.00",
    "isolatedWallet": "24.01",
    "maintMargin": "0.48",
    "initialMargin": "24.00",
    "positionInitialMargin": "24.00",
}


def position_port() -> FakeProbePort:
    port = isolated_port()
    port.position_extras = dict(FAKE_LIQUIDATION_ROW)
    port.account_position_figures = dict(FAKE_ACCOUNT_POSITION)
    return port


async def test_the_inputs_of_the_formula_are_recorded_as_read_and_nothing_is_computed(
    tmp_path: Path,
) -> None:
    port = position_port()
    document, code = await run_cases(tmp_path, port, LIQUIDATION)
    record = case(document, LIQUIDATION)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    entries = sent(port, "new_limit_order")
    assert len(entries) == 1 and entries[0]["quantity"] == APPROVED  # ONE entry, the approved size
    assert entries[0]["price"] * entries[0]["quantity"] <= Decimal("150")
    assert [name for name in port.names() if name in CONFIG_MUTATIONS] == []
    reads = [
        name
        for name in case_calls(port)
        if name in ("positions", "leverage_brackets", "symbol_config", "account_information")
    ]
    assert reads[-4:] == ["positions", "leverage_brackets", "symbol_config", "account_information"]
    details = record["details"]
    assert details["position_liquidation_price"] == "48200.55"  # the exchange's text, untouched
    assert details["position_entry_price"] == "60000.10"
    assert details["position_position_amt"] == "0.002"
    assert details["position_mark_price"] == "60000.00"
    assert details["position_notional"] == "120.0002"
    assert details["position_margin_asset"] == "USDT"
    assert details["account_position_isolatedMargin"] == "24.00"
    assert details["account_position_isolatedWallet"] == "24.01"
    assert details["account_position_maintMargin"] == "0.48"
    assert details["bracket_0.brackets.0.initialLeverage"] == "125"
    assert details["config_at_position_margin_type"] == "ISOLATED"
    assert details["config_at_position_leverage"] == str(TEST_ONLY_CONFIG_LEVERAGE)
    assert details["quote_asset"] == "USDT"
    assert not any("verdict" in key or "difference" in key for key in details)
    assert any("nothing is computed" in note for note in record["notes"])


async def test_a_missing_account_figure_is_not_observed_text_and_the_case_stays_observed(
    tmp_path: Path,
) -> None:
    port = isolated_port()
    port.position_extras = dict(FAKE_LIQUIDATION_ROW)  # no positions.0.* in the account answer
    document, _ = await run_cases(tmp_path, port, LIQUIDATION)
    record = case(document, LIQUIDATION)
    assert record["status"] == dp.OBSERVED
    assert record["details"]["account_position_isolatedMargin"].startswith("NOT_OBSERVED")
    assert record["details"]["account_position_maintMargin"].startswith("NOT_OBSERVED")


async def test_an_answer_without_a_liquidation_price_is_not_observed_but_the_rest_is_kept(
    tmp_path: Path,
) -> None:
    port = isolated_port()
    port.position_extras = {"entry_price": "60000.10", "mark_price": "60000.00"}
    document, _ = await run_cases(tmp_path, port, LIQUIDATION)
    record = case(document, LIQUIDATION)
    assert record["status"] == dp.NOT_OBSERVED and "liquidationPrice" in record["reason"]
    assert record["details"]["position_liquidation_price"].startswith("NOT_OBSERVED")
    assert record["details"]["position_entry_price"] == "60000.10"


async def test_a_bracket_read_error_is_recorded_and_does_not_hide_the_price(
    tmp_path: Path,
) -> None:
    port = position_port()
    port.script(
        "leverage_brackets",
        error_observation("leverage_brackets", code=-1000, category="UNKNOWN_EXCHANGE_ERROR"),
    )
    document, _ = await run_cases(tmp_path, port, LIQUIDATION)
    record = case(document, LIQUIDATION)
    assert record["status"] == dp.OBSERVED
    assert record["details"]["brackets_accepted"] == "false"
    assert record["details"]["position_liquidation_price"] == "48200.55"


@pytest.mark.parametrize(("margin_type", "leverage"), [("CROSSED", "20"), ("ISOLATED", "20")])
async def test_a_symbol_not_isolated_at_the_target_opens_no_position(
    tmp_path: Path, margin_type: str, leverage: str
) -> None:
    port = FakeProbePort()
    port.config_margin_type, port.config_leverage = margin_type, leverage
    document, _ = await run_cases(tmp_path, port, LIQUIDATION)
    record = case(document, LIQUIDATION)
    assert record["status"] == dp.NOT_OBSERVED
    assert "symbol_config_change_to_isolated first" in record["reason"]
    assert [name for name in port.names() if name in MUTATIONS[:3] + CONFIG_MUTATIONS] == []


async def test_a_rejected_entry_ends_the_case_without_the_reads(tmp_path: Path) -> None:
    port = position_port()
    port.script(
        "new_limit_order",
        error_observation("new_limit_order", code=-2019, category="REJECTED_DEFINITIVE"),
    )
    document, _ = await run_cases(tmp_path, port, LIQUIDATION)
    record = case(document, LIQUIDATION)
    assert record["status"] == dp.NOT_OBSERVED and "entry rejected" in record["reason"]
    assert len(sent(port, "new_limit_order")) == 1  # never re-sent
    assert "leverage_brackets" not in case_calls(port)


async def test_the_liquidation_case_refuses_an_entry_above_the_notional_cap(
    tmp_path: Path,
) -> None:
    port = position_port()
    document, _ = await run_cases(tmp_path, port, LIQUIDATION, cap="1")
    record = case(document, LIQUIDATION)
    assert record["status"] == dp.ERROR and "order bound" in record["reason"]
    assert sent(port, "new_limit_order") == []


async def test_the_runner_cleanup_closes_the_position_the_liquidation_case_opened(
    tmp_path: Path,
) -> None:
    port = position_port()
    await run_cases(tmp_path, port, LIQUIDATION)
    closes = sent(port, "new_market_order")
    assert len(closes) == 1 and closes[0]["reduce_only"] is True and closes[0]["side"] == "SELL"
    assert closes[0]["quantity"] == APPROVED
    assert port.positions_rows == []


async def test_an_executed_run_with_fixtures_writes_the_new_cases_answers(tmp_path: Path) -> None:
    port = position_port()
    document, _ = await run_cases(tmp_path, port, LIQUIDATION, fixtures=True)
    assert case(document, LIQUIDATION)["status"] == dp.OBSERVED
    names = sorted(path.name for path in (tmp_path / "fixtures").iterdir())
    assert any("leverage_brackets" in name for name in names)
    assert any("account_information" in name for name in names)
    assert any("positions" in name for name in names)


# --------------------------------------------------------------------------- #
# Plan 22-09, task 3: the owner's runbook names every case, key and recorded detail.
# --------------------------------------------------------------------------- #

RUNBOOK = Path(dp.__file__).resolve().parents[1] / ".planning" / "DEMO-EVIDENCE-PLAN.md"


def runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def runbook_section(title: str) -> str:
    text = runbook()
    start = text.index(title)
    match = re.search(r"\n## ", text[start + len(title) :])
    return text[start : start + len(title) + match.start()] if match else text[start:]


def case_body(text: str, number: int, case_id: str) -> str:
    """The text of the numbered runbook section of one case, up to the next heading."""
    start = text.index(f"### {number}. {case_id}")
    ends = [text.find(marker, start + 1) for marker in ("\n### ", "\n## ")]
    return text[start : min(end for end in ends if end != -1)]


def test_the_runbook_names_every_sj3_case_key_and_the_leverage_rule() -> None:
    text = runbook()
    for case_id, key in SJ3_KEYS.items():
        assert f"`{case_id}`" in text and f"`{key}`" in text, case_id
    assert "config_target_leverage" in text and "not Demo-proven" in text
    assert "AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED" in text


def test_sections_24_to_29_are_one_per_case_in_order_with_the_same_parts() -> None:
    text = runbook()
    headings = re.findall(r"^### (2[4-9])\. (\w+) \(key `(\w+)`", text, flags=re.M)
    assert [(number, case_id, key) for number, case_id, key in headings] == [
        (str(24 + index), case_id, SJ3_KEYS[case_id]) for index, case_id in enumerate(SJ3_IDS)
    ]
    for number, case_id, _ in headings[1:]:  # section 24 was written by plan 22-05
        body = case_body(text, int(number), case_id)
        for part in ("- Read", "- Consumers:", "- If it stops:"):
            assert part in body, (case_id, part)
        assert "demo-observed" in body or "Demo-observed" in body or "Phase 22" in body


def test_the_step_0_rules_and_the_session_list_carry_the_phase_22_keys() -> None:
    step0 = runbook_section("## Step 0: your limits file")
    for key in SJ3_KEYS.values():
        assert f"{key} = <OWNER: true or false>" in step0, key
    assert "insufficient_margin` or `margin_insufficient_target` is true" in step0
    assert "`symbol_config_change`, `margin_insufficient_target` or `isolated_liquidation`" in step0
    session = runbook_section("## One session: all cases")
    positions = [session.index(f"`{case_id}`") for case_id in (*SJ3_IDS, "gtd_entry_expiry_status")]
    assert positions == sorted(positions)
    assert re.search(r"^29\. `gtd_entry_expiry_status`", session, flags=re.M)
    for case_id in SJ3_IDS[1:]:
        assert re.search(rf"^\d+\. `{case_id}`", session, flags=re.M), case_id


def test_the_consumers_table_and_the_evidence_map_name_the_phase_22_readers() -> None:
    consumers = runbook_section("## Consumers table")
    for case_id in SJ3_IDS:
        assert f"| {case_id} |" in consumers, case_id
    for reader in ("22-11", "22-13", "22-14", "O-1", "O-2", "A1", "A3", "A6"):
        assert reader in consumers, reader
    evidence_map = runbook_section("## Phase 22 evidence map")
    for case_id in SJ3_IDS:
        assert f"| {case_id} |" in evidence_map, case_id
    assert "NOT Demo-proven" in evidence_map and "criterion 1" in evidence_map
    assert "O-1 to O-4" in evidence_map and "demo-observed, not mainnet" in evidence_map
    for forbidden in ("http://", "https://", "BINANCE_"):
        assert forbidden not in runbook(), forbidden


async def test_the_runbook_read_lists_name_details_the_cases_really_record(
    tmp_path: Path,
) -> None:
    # The names the sections promise are run on the fakes: each must be a recorded detail.
    promised = {
        BALANCE: (far_resting_port, ("available_balance_delta", "open_order_margin_delta")),
        MARGIN_TYPE: (
            FakeProbePort,
            ("previous_margin_type", "change_accepted", "restore_accepted"),
        ),
        LEVERAGE_MAX: (
            FakeProbePort,
            ("bracket_one_initial_leverage", "requested_leverage", "restore_accepted"),
        ),
        MARGIN_TARGET: (isolated_port, ("target_implied_initial_margin", "target_order_accepted")),
        LIQUIDATION: (
            position_port,
            (
                "position_liquidation_price",
                "account_position_isolatedMargin",
                "config_at_position_leverage",
            ),
        ),
    }
    text = runbook()
    for case_id, (make_port, names) in promised.items():
        document, _ = await run_cases(sub(tmp_path, case_id), make_port(), case_id)
        details = case(document, case_id)["details"]
        body = case_body(text, 24 + SJ3_IDS.index(case_id), case_id)
        for name in names:
            assert name in body, (case_id, name)
            assert name in details, (case_id, name)
