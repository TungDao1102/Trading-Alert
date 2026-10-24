"""The first Phase 22 owner opt-in case, on fakes and virtual time (plan 22-05, D-18).

`symbol_config_change_to_isolated` changes a FLAT symbol to ISOLATED and the owner's leverage and
records every answer. Everything runs offline on `FakeProbePort` / `RecordingProbePort` and on
virtual time; nothing reaches Binance and no agent runs the case: the owner does (AGENTS.md).
The FAKE symbol configuration is the account default Demo showed on 2026-10-04 (BTCUSDT x20
CROSSED, demo-observed, not mainnet). The FAKE answers prove the case logic only [DESIGN]; they
are not Demo evidence (D-19).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from scripts import demo_probe as dp

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
    assert dp.SJ3_CASES == (CONFIG,)
    assert dp.OPTIONAL_CASES[CONFIG_KEY] == CONFIG
    assert dp.CASE_HANDLERS[CONFIG] is dp.case_symbol_config_change_to_isolated
    assert set(dp.CASE_HANDLERS) == set(dp.CASE_ORDER)
    order = list(dp.CASE_ORDER)
    assert order[-1] == "gtd_entry_expiry_status"  # the case that waits runs last
    assert order[-2] == CONFIG  # right before the GTD case, after the SJ2 group
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
