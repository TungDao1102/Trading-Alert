"""The Demo probe runner on fakes (plan 18-17 Task 1): order, dry run, cases, cleanup, time.

Everything runs offline on `FakeProbePort` or `RecordingProbePort` and on virtual time
(`tests/support/virtual_time.py`); nothing sleeps in real time and nothing reaches Binance.
The limits are TEST_ONLY values written by `write_probe_limits`; the ratified Binance limits
file is read through the script's own default path.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from scripts import demo_probe as dp
from src.adapters.binance_probe import ProbeBanned
from src.adapters.binance_ratelimit_gate import IP_BAN_418

from tests.probe_fakes import (
    TEST_ONLY_CASE_TIMEOUT_SECONDS,
    TEST_ONLY_CLEANUP_TIMEOUT_SECONDS,
    FakeProbePort,
    RecordingProbePort,
    error_observation,
    fake_symbol_filters,
    ok_observation,
    write_probe_limits,
)
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START, VirtualTime

EXPECTED_ORDER = (
    "get_order_not_found",
    "get_algo_order_not_found",
    "cancel_order_not_found",
    "cancel_algo_order_not_found",
    "duplicate_client_algo_id",
    "id_reuse_after_canceled_normal",
    "id_reuse_after_canceled_algo",
    "id_reuse_after_filled",
    "preplaced_stop_reduce_only_flat",
    "closeposition_stop_flat",
    "entry_never_fills_protective_orphan",
    "full_fill_protective_quantity",
    "partial_fill",
    "rejected_protective_variants",
    "below_min_notional_reduce_only_leg",
    "triggered_market_exit_lifecycle",
    "explicit_time_in_force_variant",
    "stream_gap_during_case",
    "market_lot_size_out_of_range",
)
READ_ONLY = EXPECTED_ORDER[:4]
ALL_OPTIONAL = ("explicit_time_in_force", "stream_gap", "market_lot_size_out_of_range")


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def make_config(
    tmp_path: Path,
    *,
    execute: bool = False,
    optional: tuple[str, ...] = (),
    only: tuple[str, ...] | None = None,
) -> dp.ProbeConfig:
    limits = write_probe_limits(tmp_path, optional=optional)
    argv = [
        "--environment",
        "DEMO",
        "--probe-limits-file",
        str(limits),
        "--evidence-dir",
        str(tmp_path / "evidence"),
    ]
    if only is not None:
        argv += ["--only", ",".join(only)]
    if execute:
        argv.append("--execute")
    return dp.parse_config(argv)


def instant_sleep(vt: VirtualTime) -> Callable[[int], Awaitable[None]]:
    """A virtual sleep that moves virtual time by itself (records the duration, never waits)."""

    async def sleep(seconds: int) -> None:
        vt.sleeps.append(seconds)
        await vt.advance(seconds)

    return sleep


def make_rig(port: Any, vt: VirtualTime | None = None) -> dp.ProbeRig:
    vt = vt if vt is not None else VirtualTime()
    return dp.ProbeRig(port=port, clock=vt.now, sleep=instant_sleep(vt))


async def run(config: dp.ProbeConfig, rig: dp.ProbeRig) -> tuple[dict[str, Any], int]:
    recorder = dp.ProbeRecorder()
    code = await dp.run_probe(config, rig, recorder)
    return recorder.document(config), code


def case(document: dict[str, Any], case_id: str) -> dict[str, Any]:
    matches = [item for item in document["cases"] if item["case_id"] == case_id]
    assert len(matches) == 1, case_id
    return matches[0]


def restrict_handlers(monkeypatch: pytest.MonkeyPatch, keep: tuple[str, ...]) -> None:
    """Replace the registry by the read-only handlers named in `keep` (stays valid after 18-23)."""
    smaller = {cid: dp.CASE_HANDLERS[cid] for cid in keep}
    monkeypatch.setattr(dp, "CASE_HANDLERS", smaller)


# --------------------------------------------------------------------------- #
# Order and dry-run semantics.
# --------------------------------------------------------------------------- #


def test_case_order_is_the_d16_order_of_risk() -> None:
    assert dp.CASE_ORDER == EXPECTED_ORDER
    assert dp.REQUIRED_CASES == EXPECTED_ORDER[:16]
    assert tuple(dp.OPTIONAL_CASES) == ALL_OPTIONAL
    assert tuple(dp.OPTIONAL_CASES.values()) == EXPECTED_ORDER[16:]
    assert dp.READ_ONLY_CASES == READ_ONLY


def test_this_plan_registers_the_four_read_only_handlers() -> None:
    for case_id in READ_ONLY:
        assert case_id in dp.CASE_HANDLERS
    assert set(dp.CASE_HANDLERS) <= set(dp.CASE_ORDER)


@pytest.mark.parametrize(
    ("optional", "expected"),
    [
        ((), EXPECTED_ORDER[:16]),
        (ALL_OPTIONAL, EXPECTED_ORDER),
        (("stream_gap",), (*EXPECTED_ORDER[:16], "stream_gap_during_case")),
    ],
)
async def test_the_dry_run_enumerates_case_order_each_not_rehearsed(
    tmp_path: Path, optional: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    config = make_config(tmp_path, optional=optional)
    document, code = await run(config, dp.build_dry_run_rig(config))
    assert code == dp.EXIT_OK
    assert [item["case_id"] for item in document["cases"]] == list(expected)
    for item in document["cases"]:
        assert item["status"] == dp.NOT_REHEARSED
        assert item["reason"] == dp.REASON_DRY_RUN
        assert item["observations"] == []


async def test_the_dry_run_invokes_every_registered_handler_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path, optional=ALL_OPTIONAL)
    invoked: list[str] = []
    wrapped: dict[str, dp.CaseHandler] = {}
    for case_id, handler in dp.CASE_HANDLERS.items():

        def make(cid: str, inner: dp.CaseHandler) -> dp.CaseHandler:
            async def counting(context: dp.CaseContext) -> dp.CaseResult:
                invoked.append(cid)
                return await inner(context)

            return counting

        wrapped[case_id] = make(case_id, handler)
    monkeypatch.setattr(dp, "CASE_HANDLERS", wrapped)
    rig = dp.build_dry_run_rig(config)
    document, _ = await run(config, rig)
    assert sorted(invoked) == sorted(wrapped) and len(invoked) == len(set(invoked))
    for item in document["cases"]:
        registered = item["case_id"] in wrapped
        assert item["handler_registered"] is registered
        if not registered:
            assert item["planned_requests"] == []
    planned = {cid: case(document, cid)["planned_requests"] for cid in READ_ONLY}
    assert [r["operation"] for r in planned["get_order_not_found"]] == ["query_order"]
    assert [r["operation"] for r in planned["get_algo_order_not_found"]] == ["query_algo_order"]
    assert [r["operation"] for r in planned["cancel_order_not_found"]] == ["cancel_order"]
    assert [r["operation"] for r in planned["cancel_algo_order_not_found"]] == ["cancel_algo_order"]
    assert planned["cancel_order_not_found"][0]["mutating"] is True
    assert planned["get_order_not_found"][0]["kwargs"]["symbol"] == config.symbol
    port = rig.port
    assert isinstance(port, RecordingProbePort)


async def test_an_unregistered_id_in_a_dry_run_is_not_invoked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restrict_handlers(monkeypatch, ("get_order_not_found",))
    config = make_config(tmp_path)
    document, _ = await run(config, dp.build_dry_run_rig(config))
    flagged = [item["case_id"] for item in document["cases"] if not item["handler_registered"]]
    assert flagged == list(EXPECTED_ORDER[1:16])
    assert case(document, "get_algo_order_not_found")["status"] == dp.NOT_REHEARSED


async def test_only_runs_the_named_cases_in_case_order(tmp_path: Path) -> None:
    config = make_config(tmp_path, only=("cancel_order_not_found", "get_order_not_found"))
    document, _ = await run(config, dp.build_dry_run_rig(config))
    assert [item["case_id"] for item in document["cases"]] == [
        "get_order_not_found",
        "cancel_order_not_found",
    ]


@pytest.mark.parametrize("only", [("no_such_case",), ("stream_gap_during_case",), ("",)])
def test_only_refuses_unknown_and_disabled_ids(tmp_path: Path, only: tuple[str, ...]) -> None:
    with pytest.raises(dp.UsageError):
        make_config(tmp_path, only=only)


# --------------------------------------------------------------------------- #
# The read-only cases (execute mode over FakeProbePort).
# --------------------------------------------------------------------------- #

_READ_ONLY_OPERATION = {
    "get_order_not_found": "query_order",
    "get_algo_order_not_found": "query_algo_order",
    "cancel_order_not_found": "cancel_order",
    "cancel_algo_order_not_found": "cancel_algo_order",
}


@pytest.mark.parametrize("case_id", READ_ONLY)
async def test_a_not_found_answer_is_recorded_as_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_id: str
) -> None:
    restrict_handlers(monkeypatch, READ_ONLY)
    config = make_config(tmp_path, execute=True, only=(case_id,))
    port = FakeProbePort()
    operation = _READ_ONLY_OPERATION[case_id]
    port.script(
        operation,
        error_observation(
            operation, code=-2013, category="ORDER_ABSENT", message="Order does not exist."
        ),
    )
    document, code = await run(config, make_rig(port))
    record = case(document, case_id)
    assert record["status"] == dp.OBSERVED
    error = record["observations"][0]["error"]
    assert error["code"] == -2013
    assert error["category"] == "ORDER_ABSENT"
    assert error["http_class"] == "BAD_REQUEST"
    assert error["message"] == "Order does not exist."
    assert record["notes"] == []
    assert code == dp.EXIT_OK
    sent = [kwargs for name, kwargs in port.calls if name == operation]
    assert len(sent) == 1
    probed = next(iter(v for k, v in sent[0].items() if k.startswith("client")))
    assert record["details"]["probed_client_id"] == probed
    assert dp.CLIENT_ID_RE.fullmatch(probed)


@pytest.mark.parametrize("case_id", READ_ONLY)
async def test_an_unexpected_success_is_observed_with_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_id: str
) -> None:
    restrict_handlers(monkeypatch, READ_ONLY)
    config = make_config(tmp_path, execute=True, only=(case_id,))
    port = FakeProbePort()
    operation = _READ_ONLY_OPERATION[case_id]
    port.script(operation, ok_observation(operation, {"status": "NEW"}))
    document, _ = await run(config, make_rig(port))
    record = case(document, case_id)
    assert record["status"] == dp.OBSERVED
    assert record["observations"][0]["ok"] is True
    assert record["notes"] == [dp.NOTE_UNEXPECTED_EXISTS]


async def test_the_probed_ids_differ_per_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restrict_handlers(monkeypatch, READ_ONLY)
    config = make_config(tmp_path, execute=True, only=READ_ONLY)
    document, _ = await run(config, make_rig(FakeProbePort()))
    ids = [case(document, cid)["details"]["probed_client_id"] for cid in READ_ONLY]
    assert len(set(ids)) == 4


async def test_an_unregistered_id_in_an_execute_run_is_an_error_and_the_run_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(dp.CASE_HANDLERS, "get_algo_order_not_found")
    config = make_config(tmp_path, execute=True, only=READ_ONLY)
    port = FakeProbePort()
    document, code = await run(config, make_rig(port))
    record = case(document, "get_algo_order_not_found")
    assert record["status"] == dp.ERROR
    assert record["reason"] == dp.REASON_NO_HANDLER
    assert record["handler_registered"] is False
    assert case(document, "cancel_order_not_found")["status"] == dp.OBSERVED
    assert document["cleanup"]["final"]["status"] == dp.CLEANUP_FLAT
    # The run still ends with the account re-read (a guard against the `or` that passed always).
    assert port.names()[-4:] == ["open_orders", "open_algo_orders", "positions", "account_balance"]
    assert document["cleanup"]["final"]["remaining"] == {
        "open_orders": 0,
        "open_algo_orders": 0,
        "positions": [],
        "readable": True,
    }
    assert document["outcome"] == dp.OUTCOME_FAILED
    assert code == dp.EXIT_FAILED


async def test_a_handler_that_raises_is_recorded_as_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(context: dp.CaseContext) -> dp.CaseResult:
        raise KeyError("FAKE bug")

    restrict_handlers(monkeypatch, READ_ONLY)
    monkeypatch.setitem(dp.CASE_HANDLERS, "get_order_not_found", broken)
    config = make_config(tmp_path, execute=True, only=READ_ONLY)
    document, code = await run(config, make_rig(FakeProbePort()))
    record = case(document, "get_order_not_found")
    assert record["status"] == dp.ERROR
    assert "KeyError" in record["reason"]
    assert case(document, "get_algo_order_not_found")["status"] == dp.OBSERVED
    assert code == dp.EXIT_FAILED


# --------------------------------------------------------------------------- #
# Ban and rate limit: the run stops every further call.
# --------------------------------------------------------------------------- #


async def test_a_probe_ban_aborts_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    restrict_handlers(monkeypatch, READ_ONLY)
    config = make_config(tmp_path, execute=True)
    port = FakeProbePort()
    port.script("query_algo_order", ProbeBanned(IP_BAN_418, 120))
    document, code = await run(config, make_rig(port))
    assert document["outcome"] == dp.OUTCOME_ABORTED_BAN
    assert code == dp.EXIT_FAILED
    assert case(document, "get_order_not_found")["status"] == dp.OBSERVED
    for case_id in EXPECTED_ORDER[1:16]:
        record = case(document, case_id)
        assert record["status"] == dp.NOT_OBSERVED
        assert record["reason"] == dp.REASON_BAN
    calls_after_ban = port.names()[port.names().index("query_algo_order") + 1 :]
    assert calls_after_ban == []
    assert document["cleanup"]["final"]["status"] == dp.CLEANUP_NOT_VERIFIED
    assert document["ban"]["reason"] == IP_BAN_418


@pytest.mark.parametrize(
    ("category", "http_class", "code"),
    [("RATE_LIMITED", "TOO_MANY_429", -1003), ("IP_BANNED", "BANNED_418", -1003)],
)
async def test_a_rate_limit_answer_stops_every_further_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, category: str, http_class: str, code: int
) -> None:
    restrict_handlers(monkeypatch, READ_ONLY)
    config = make_config(tmp_path, execute=True)
    port = FakeProbePort()
    port.script(
        "query_order",
        error_observation("query_order", code=code, category=category, http_class=http_class),
    )
    document, exit_code = await run(config, make_rig(port))
    record = case(document, "get_order_not_found")
    assert record["status"] == dp.OBSERVED
    assert record["observations"][0]["error"]["category"] == category
    assert port.names()[-1] == "query_order"
    assert document["outcome"] == dp.OUTCOME_ABORTED_BAN
    assert exit_code == dp.EXIT_FAILED
    assert case(document, "get_algo_order_not_found")["reason"] == dp.REASON_BAN


async def test_a_ban_while_reading_the_account_before_aborts_with_nothing_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restrict_handlers(monkeypatch, READ_ONLY)
    config = make_config(tmp_path, execute=True)
    port = FakeProbePort()
    port.script("open_orders", ProbeBanned(IP_BAN_418, None))
    document, code = await run(config, make_rig(port))
    assert document["outcome"] == dp.OUTCOME_ABORTED_BAN
    assert code == dp.EXIT_FAILED
    assert not any(name.startswith(("cancel", "new_", "query")) for name in port.names())


# --------------------------------------------------------------------------- #
# Account before: the symbol must be flat, else nothing is sent.
# --------------------------------------------------------------------------- #


async def test_a_symbol_not_flat_before_the_probe_aborts_before_any_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restrict_handlers(monkeypatch, READ_ONLY)
    config = make_config(tmp_path, execute=True)
    port = FakeProbePort()
    port.open_order_ids.append("someone-elses-order")
    document, code = await run(config, make_rig(port))
    assert code == dp.EXIT_ABORTED
    assert document["outcome"] == dp.OUTCOME_ABORTED_NO_ORDER
    assert not any(name.startswith(("cancel", "new_", "query")) for name in port.names())
    assert port.open_order_ids == ["someone-elses-order"]
    assert all(item["status"] == dp.NOT_OBSERVED for item in document["cases"])


async def test_account_state_is_recorded_before_and_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restrict_handlers(monkeypatch, READ_ONLY)
    config = make_config(tmp_path, execute=True, only=READ_ONLY)
    document, _ = await run(config, make_rig(FakeProbePort()))
    for key in ("account_before", "account_after"):
        state = document[key]
        assert state["flat"] is True
        for part in ("position_mode", "open_orders", "open_algo_orders", "positions", "balance"):
            assert state[part]["ok"] is True, (key, part)
        assert state["dual_side_position"] is False


# --------------------------------------------------------------------------- #
# The cleanup framework.
# --------------------------------------------------------------------------- #


def _ids() -> Callable[[], str]:
    counter = iter(range(1, 1000))
    return lambda: f"dprobe-flat-test-{next(counter)}"


async def test_cleanup_cancels_everything_and_reads_flat_without_waiting() -> None:
    vt = VirtualTime()
    port = FakeProbePort()
    port.open_order_ids.append("a")
    port.open_algo_ids.append("b")
    result = await dp.cleanup_symbol(
        make_rig(port, vt),
        symbol="BTCUSDT",
        dual_side=False,
        timeout_seconds=60,
        next_client_id=_ids(),
    )
    assert result["status"] == dp.CLEANUP_FLAT
    assert port.names()[:3] == [
        "cancel_all_open_orders",
        "cancel_all_algo_open_orders",
        "positions",
    ]
    assert "new_market_order" not in port.names()
    assert vt.sleeps == []
    assert result["remaining"] == {
        "open_orders": 0,
        "open_algo_orders": 0,
        "positions": [],
        "readable": True,
    }


@pytest.mark.parametrize(
    ("dual_side", "row_side", "amount", "close_side", "position_side", "reduce_only"),
    [
        (False, "BOTH", Decimal("0.002"), "SELL", "BOTH", True),
        (False, "BOTH", Decimal("-0.003"), "BUY", "BOTH", True),
        (True, "LONG", Decimal("0.002"), "SELL", "LONG", None),
        (True, "SHORT", Decimal("-0.004"), "BUY", "SHORT", None),
    ],
)
async def test_cleanup_flattens_a_residual_position_with_one_reduce_only_market_order(
    dual_side: bool,
    row_side: str,
    amount: Decimal,
    close_side: str,
    position_side: str,
    reduce_only: bool | None,
) -> None:
    port = FakeProbePort(dual_side=dual_side)
    port.positions_rows.append((row_side, amount))
    result = await dp.cleanup_symbol(
        make_rig(port),
        symbol="BTCUSDT",
        dual_side=dual_side,
        timeout_seconds=60,
        next_client_id=_ids(),
    )
    markets = [kwargs for name, kwargs in port.calls if name == "new_market_order"]
    assert len(markets) == 1
    sent = markets[0]
    assert sent["side"] == close_side
    assert sent["quantity"] == abs(amount)
    assert isinstance(sent["quantity"], Decimal)
    assert sent["position_side"] == position_side
    assert sent["reduce_only"] is reduce_only
    assert sent["symbol"] == "BTCUSDT"
    assert result["status"] == dp.CLEANUP_FLAT


async def test_cleanup_sends_no_close_when_the_position_mode_is_unknown() -> None:
    port = FakeProbePort()
    port.positions_rows.append(("BOTH", Decimal("0.002")))
    result = await dp.cleanup_symbol(
        make_rig(port), symbol="BTCUSDT", dual_side=None, timeout_seconds=60, next_client_id=_ids()
    )
    assert "new_market_order" not in port.names()
    assert result["status"] == dp.CLEANUP_FAILED_STATUS


async def test_a_non_flat_re_read_is_repeated_once_after_the_cleanup_timeout() -> None:
    vt = VirtualTime()
    port = FakeProbePort()
    still_open = ok_observation(
        "positions",
        {"count": "1", "row_0_position_side": "BOTH", "row_0_position_amt": "0.002"},
    )
    # call 0: the cleanup read (flat, so no close); call 1: the re-read shows a position;
    # call 2: the one re-read after the wait is flat.
    port.script_call("positions", 1, still_open)
    result = await dp.cleanup_symbol(
        make_rig(port, vt),
        symbol="BTCUSDT",
        dual_side=False,
        timeout_seconds=45,
        next_client_id=_ids(),
    )
    assert vt.sleeps == [45]
    assert port.count("positions") == 3
    assert result["status"] == dp.CLEANUP_FLAT
    assert result["waited_seconds"] == 45


async def test_cleanup_failed_reports_the_exact_remaining_state() -> None:
    vt = VirtualTime()
    port = FakeProbePort()
    port.positions_rows.append(("BOTH", Decimal("0.002")))
    port.flatten_takes_effect = False
    result = await dp.cleanup_symbol(
        make_rig(port, vt),
        symbol="BTCUSDT",
        dual_side=False,
        timeout_seconds=60,
        next_client_id=_ids(),
    )
    assert result["status"] == dp.CLEANUP_FAILED_STATUS
    assert vt.sleeps == [60]
    assert result["remaining"]["positions"] == [
        {"symbol": "BTCUSDT", "position_side": "BOTH", "position_amt": "0.002"}
    ]


async def test_a_run_whose_final_cleanup_fails_ends_cleanup_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def leaves_a_position(context: dp.CaseContext) -> dp.CaseResult:
        port = context.rig.port
        assert isinstance(port, FakeProbePort)
        port.positions_rows.append(("BOTH", Decimal("0.002")))
        return dp.CaseResult(status=dp.NOT_OBSERVED, reason="FAKE: a fill the test injected")

    restrict_handlers(monkeypatch, ("get_order_not_found",))
    monkeypatch.setitem(dp.CASE_HANDLERS, "get_order_not_found", leaves_a_position)
    config = make_config(tmp_path, execute=True, only=("get_order_not_found",))
    port = FakeProbePort()
    port.flatten_takes_effect = False
    vt = VirtualTime()
    document, code = await run(config, make_rig(port, vt))
    assert document["outcome"] == dp.OUTCOME_CLEANUP_FAILED
    assert code == dp.EXIT_FAILED
    per_case = case(document, "get_order_not_found")["cleanup"]
    assert per_case["status"] == dp.CLEANUP_FAILED_STATUS
    assert document["cleanup"]["final"]["status"] == dp.CLEANUP_FAILED_STATUS
    assert document["cleanup"]["final"]["remaining"]["positions"][0]["position_amt"] == "0.002"
    assert vt.sleeps == [TEST_ONLY_CLEANUP_TIMEOUT_SECONDS, TEST_ONLY_CLEANUP_TIMEOUT_SECONDS]
    assert "CLEANUP_FAILED" in capsys.readouterr().err


async def test_cleanup_runs_after_every_case_and_at_the_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restrict_handlers(monkeypatch, READ_ONLY)
    config = make_config(tmp_path, execute=True, only=READ_ONLY)
    port = FakeProbePort()
    document, _ = await run(config, make_rig(port))
    assert port.count("cancel_all_open_orders") == len(READ_ONLY) + 1
    assert port.count("cancel_all_algo_open_orders") == len(READ_ONLY) + 1
    for case_id in READ_ONLY:
        assert case(document, case_id)["cleanup"]["status"] == dp.CLEANUP_FLAT
    assert document["cleanup"]["final"]["status"] == dp.CLEANUP_FLAT


# --------------------------------------------------------------------------- #
# Time: wait_up_to and the injected clock.
# --------------------------------------------------------------------------- #


async def test_wait_up_to_returns_at_once_without_sleeping() -> None:
    vt = VirtualTime()
    rig = dp.ProbeRig(port=FakeProbePort(), clock=vt.now, sleep=vt.sleep)
    calls: list[int] = []

    async def predicate() -> bool:
        calls.append(1)
        return True

    assert await dp.wait_up_to(rig, predicate, 30) is True
    assert vt.sleeps == [] and calls == [1]


async def test_wait_up_to_sleeps_once_and_sees_the_change() -> None:
    import asyncio  # noqa: PLC0415 - only this test schedules a task

    vt = VirtualTime()
    rig = dp.ProbeRig(port=FakeProbePort(), clock=vt.now, sleep=vt.sleep)
    state = {"done": False}

    async def predicate() -> bool:
        return state["done"]

    task = asyncio.ensure_future(dp.wait_up_to(rig, predicate, 30))
    await vt.settle()
    state["done"] = True
    await vt.advance(30)
    assert await task is True
    assert vt.sleeps == [30]


async def test_wait_up_to_returns_false_after_exactly_one_sleep() -> None:
    import asyncio  # noqa: PLC0415

    vt = VirtualTime()
    rig = dp.ProbeRig(port=FakeProbePort(), clock=vt.now, sleep=vt.sleep)
    calls: list[int] = []

    async def predicate() -> bool:
        calls.append(1)
        return False

    task = asyncio.ensure_future(dp.wait_up_to(rig, predicate, 7))
    await vt.advance(7)
    assert await task is False
    assert vt.sleeps == [7] and calls == [1, 1]
    assert vt.now() == TEST_ONLY_VIRTUAL_START + timedelta(seconds=7)


@pytest.mark.parametrize("timeout", [0, -1, True, "30"])
async def test_wait_up_to_refuses_a_timeout_that_is_not_a_positive_int(timeout: Any) -> None:
    vt = VirtualTime()
    rig = dp.ProbeRig(port=FakeProbePort(), clock=vt.now, sleep=vt.sleep)

    async def predicate() -> bool:
        return False

    with pytest.raises((TypeError, ValueError)):
        await dp.wait_up_to(rig, predicate, timeout)


class TickClock:
    """Returns a new aware UTC instant (one second later) on every call and records it."""

    def __init__(self) -> None:
        self.start = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
        self.given: list[datetime] = []

    def __call__(self) -> datetime:
        moment = self.start + timedelta(seconds=len(self.given))
        self.given.append(moment)
        return moment


async def test_every_evidence_time_comes_from_the_injected_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restrict_handlers(monkeypatch, READ_ONLY)
    config = make_config(tmp_path, execute=True, only=READ_ONLY)
    clock = TickClock()
    vt = VirtualTime()
    rig = dp.ProbeRig(port=FakeProbePort(), clock=clock, sleep=instant_sleep(vt))
    document, _ = await run(config, rig)
    given = [moment.isoformat() for moment in clock.given]
    assert document["started_utc"] == given[0]
    assert document["finished_utc"] == given[-1]
    for item in document["cases"]:
        assert item["started_utc"] in given and item["finished_utc"] in given
        assert item["started_utc"] <= item["finished_utc"]
    assert dp.evidence_stem(config, document) == "demo-probe-EVIDENCE-20261016T090000Z"


async def test_a_naive_clock_is_refused_before_any_port_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    restrict_handlers(monkeypatch, READ_ONLY)
    config = make_config(tmp_path, execute=True)
    port = FakeProbePort()
    rig = dp.ProbeRig(
        port=port, clock=lambda: datetime(2026, 10, 16, 9, 0), sleep=instant_sleep(VirtualTime())
    )
    with pytest.raises(ValueError, match="aware UTC"):
        await dp.run_probe(config, rig, dp.ProbeRecorder())
    assert port.calls == []


# =========================================================================== #
# Plan 18-23: the cases that send orders, on scripted FakeProbePort scenarios.
# =========================================================================== #
#
# The FAKE market (tests/probe_fakes.py): mark 60000.00, tick 0.10, step 0.001, min quantity
# 0.001, min notional 100, PERCENT_PRICE up 1.0500. TEST_ONLY limits: quantity 0.002, notional
# cap 150, far_price_fraction 0.80. So a far BUY rests at 48000.00, a far up-trigger sits at
# 72000.00 (notional 144) and a marketable BUY is priced at the PERCENT_PRICE bound 63000.00.

FAR_BELOW = Decimal("48000.00")
FAR_ABOVE = Decimal("72000.00")
MARKETABLE = Decimal("61500.00")  # halfway between the mark 60000 and the band edge 63000
JUST_BELOW = Decimal("59999.90")
APPROVED = Decimal("0.002")
ORDER_SENDS = ("new_limit_order", "new_market_order", "new_conditional_order")


def scenario_rig(port: FakeProbePort, vt: VirtualTime | None = None) -> dp.ProbeRig:
    """A rig whose sleep records the duration, runs the port's wait hooks and moves time."""
    vt = vt if vt is not None else VirtualTime()

    async def sleep(seconds: int) -> None:
        vt.sleeps.append(seconds)
        port.run_wait_hooks()
        await vt.advance(seconds)

    return dp.ProbeRig(port=port, clock=vt.now, sleep=sleep)


async def run_cases(
    tmp_path: Path,
    port: FakeProbePort,
    *case_ids: str,
    optional: tuple[str, ...] = (),
    vt: VirtualTime | None = None,
) -> tuple[dict[str, Any], int, dp.ProbeRecorder]:
    config = make_config(tmp_path, execute=True, optional=optional, only=case_ids)
    recorder = dp.ProbeRecorder()
    code = await dp.run_probe(config, scenario_rig(port, vt), recorder)
    return recorder.document(config), code, recorder


def sent(port: FakeProbePort, operation: str) -> list[dict[str, Any]]:
    return [kwargs for name, kwargs in port.calls if name == operation]


def case_calls(port: FakeProbePort, nth: int = 0) -> list[str]:
    """The operations the nth case of the run sent, between the market read and its cleanup."""
    names = port.names()
    start = names.index("symbol_filters") + 1  # the run's market read precedes every case
    for _ in range(nth):
        start = names.index("cancel_all_open_orders", start) + 1
        start = names.index("open_orders", start)  # skip the cleanup's re-read
        start = names.index("positions", start) + 1
    end = names.index("cancel_all_open_orders", start)
    return names[start:end]


# --------------------------------------------------------------------------- #
# The shared order bound (threat T-18-55).
# --------------------------------------------------------------------------- #


def _limits(tmp_path: Path, *, market_lot: bool = False) -> Any:
    optional = ("market_lot_size_out_of_range",) if market_lot else ()
    return make_config(tmp_path, optional=optional).order_limits


def test_the_order_bound_accepts_the_approved_quantity_within_the_cap(tmp_path: Path) -> None:
    limits = _limits(tmp_path)
    assert dp.order_bound_refusal(limits, quantity=APPROVED, price=Decimal("75000")) is None
    assert dp.order_bound_refusal(limits, quantity=Decimal("0.001"), price=FAR_ABOVE) is None
    assert dp.order_bound_refusal(limits, quantity=None, price=FAR_ABOVE) is None


def test_the_order_bound_refuses_a_quantity_above_the_approved_one(tmp_path: Path) -> None:
    refusal = dp.order_bound_refusal(_limits(tmp_path), quantity=Decimal("0.003"), price=FAR_BELOW)
    assert refusal is not None and "above the approved quantity" in refusal


def test_the_order_bound_refuses_a_notional_above_the_cap(tmp_path: Path) -> None:
    refusal = dp.order_bound_refusal(_limits(tmp_path), quantity=APPROVED, price=Decimal("75000.1"))
    assert refusal is not None and "above the approved cap" in refusal


@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-0.001")])
def test_the_order_bound_refuses_a_quantity_that_is_not_positive(
    tmp_path: Path, quantity: Decimal
) -> None:
    assert dp.order_bound_refusal(_limits(tmp_path), quantity=quantity, price=FAR_BELOW)


def test_the_order_bound_refuses_a_price_that_is_not_positive(tmp_path: Path) -> None:
    assert dp.order_bound_refusal(_limits(tmp_path), quantity=APPROVED, price=Decimal("0"))


def test_the_order_bound_refuses_a_quantity_off_the_step_grid(tmp_path: Path) -> None:
    refusal = dp.order_bound_refusal(
        _limits(tmp_path), quantity=Decimal("0.0015"), price=FAR_BELOW, step=Decimal("0.001")
    )
    assert refusal is not None and "step" in refusal


def test_the_market_lot_exception_is_exactly_the_owner_approved_quantity(tmp_path: Path) -> None:
    limits = _limits(tmp_path, market_lot=True)
    approved = limits.market_lot_probe_quantity
    assert approved == Decimal("200")
    # the notional cap is not applied to the owner-approved market-lot quantity
    assert (
        dp.order_bound_refusal(limits, quantity=approved, price=FAR_ABOVE, market_lot_probe=True)
        is None
    )
    assert dp.order_bound_refusal(
        limits, quantity=Decimal("199"), price=FAR_ABOVE, market_lot_probe=True
    )
    not_approved = _limits(tmp_path)
    assert not_approved.market_lot_probe_quantity is None
    assert dp.order_bound_refusal(
        not_approved, quantity=approved, price=FAR_ABOVE, market_lot_probe=True
    )


# --------------------------------------------------------------------------- #
# Task 1: the carrier cases.
# --------------------------------------------------------------------------- #


async def test_duplicate_client_algo_id_records_both_answers_and_cancels_the_carrier(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.duplicate_algo_answer = error_observation(
        "new_conditional_order",
        code=-4116,
        category="DUPLICATE_CLIENT_ID",
        message="FAKE duplicated clientAlgoId.",
    )
    document, code, _ = await run_cases(tmp_path, port, "duplicate_client_algo_id")
    record = case(document, "duplicate_client_algo_id")
    assert record["status"] == dp.OBSERVED, record
    placed = sent(port, "new_conditional_order")
    assert len(placed) == 2
    first, second = placed
    assert first == second
    assert dp.CLIENT_ID_RE.fullmatch(first["client_algo_id"])
    assert first["order_type"] == "STOP" and first["side"] == "BUY"
    assert first["trigger_price"] == FAR_ABOVE and first["price"] == FAR_ABOVE
    assert first["quantity"] == APPROVED and isinstance(first["quantity"], Decimal)
    assert first["reduce_only"] is None and first["close_position"] is None
    assert first["working_type"] == "MARK_PRICE" and first["position_side"] == "BOTH"
    duplicate = next(item for item in record["observations"] if not item["ok"])
    assert duplicate["error"] == {
        "http_class": "BAD_REQUEST",
        "code": -4116,
        "retry_after_seconds": None,
        "category": "DUPLICATE_CLIENT_ID",
        "message": "FAKE duplicated clientAlgoId.",
    }
    assert record["details"]["duplicate_accepted"] == "false"
    assert [kw["client_algo_id"] for kw in sent(port, "cancel_algo_order")] == [
        first["client_algo_id"]
    ]
    assert record["cleanup"]["status"] == dp.CLEANUP_FLAT
    assert code == dp.EXIT_OK


async def test_duplicate_client_algo_id_with_a_rejected_carrier_is_not_observed(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script(
        "new_conditional_order",
        error_observation("new_conditional_order", code=-2027, category="REJECTED_DEFINITIVE"),
    )
    document, code, _ = await run_cases(tmp_path, port, "duplicate_client_algo_id")
    record = case(document, "duplicate_client_algo_id")
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "carrier rejected: BAD_REQUEST -2027"
    assert len(sent(port, "new_conditional_order")) == 1
    assert record["observations"][0]["error"]["code"] == -2027
    assert sent(port, "cancel_algo_order") == []
    assert code == dp.EXIT_OK


@pytest.mark.parametrize("reuse_accepted", [True, False])
async def test_id_reuse_after_canceled_normal(tmp_path: Path, reuse_accepted: bool) -> None:
    port = FakeProbePort()
    if not reuse_accepted:
        port.script_call(
            "new_limit_order",
            1,
            error_observation("new_limit_order", code=-4116, category="DUPLICATE_CLIENT_ID"),
        )
    document, _, _ = await run_cases(tmp_path, port, "id_reuse_after_canceled_normal")
    record = case(document, "id_reuse_after_canceled_normal")
    assert record["status"] == dp.OBSERVED
    first, again = sent(port, "new_limit_order")
    assert first == again
    assert first["price"] == FAR_BELOW and first["side"] == "BUY"
    assert first["quantity"] == APPROVED and first["time_in_force"] == "GTC"
    assert first["reduce_only"] is None
    assert record["details"]["reuse_accepted"] == ("true" if reuse_accepted else "false")
    assert len(sent(port, "cancel_order")) == (2 if reuse_accepted else 1)
    assert case_calls(port)[:3] == ["mark_price", "symbol_filters", "new_limit_order"]


async def test_id_reuse_after_canceled_normal_stops_when_the_cancel_fails(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "cancel_order", error_observation("cancel_order", code=-2011, category="ORDER_ABSENT")
    )
    document, _, _ = await run_cases(tmp_path, port, "id_reuse_after_canceled_normal")
    record = case(document, "id_reuse_after_canceled_normal")
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "the first order was not canceled: BAD_REQUEST -2011"
    assert len(sent(port, "new_limit_order")) == 1


@pytest.mark.parametrize("reuse_accepted", [True, False])
async def test_id_reuse_after_canceled_algo(tmp_path: Path, reuse_accepted: bool) -> None:
    port = FakeProbePort()
    if not reuse_accepted:
        port.script_call(
            "new_conditional_order",
            1,
            error_observation("new_conditional_order", code=-4116, category="DUPLICATE_CLIENT_ID"),
        )
    document, _, _ = await run_cases(tmp_path, port, "id_reuse_after_canceled_algo")
    record = case(document, "id_reuse_after_canceled_algo")
    assert record["status"] == dp.OBSERVED
    first, again = sent(port, "new_conditional_order")
    assert first == again
    assert first["order_type"] == "STOP" and first["trigger_price"] == FAR_ABOVE
    assert record["details"]["reuse_accepted"] == ("true" if reuse_accepted else "false")
    assert len(sent(port, "cancel_algo_order")) == (2 if reuse_accepted else 1)


async def test_id_reuse_after_canceled_algo_with_a_rejected_carrier(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "new_conditional_order",
        error_observation("new_conditional_order", code=-1111, category="REJECTED_DEFINITIVE"),
    )
    document, _, _ = await run_cases(tmp_path, port, "id_reuse_after_canceled_algo")
    record = case(document, "id_reuse_after_canceled_algo")
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "carrier rejected: BAD_REQUEST -1111"
    assert sent(port, "cancel_algo_order") == []


async def test_id_reuse_after_filled_places_the_same_id_as_a_far_limit(tmp_path: Path) -> None:
    port = FakeProbePort()
    vt = VirtualTime()
    document, code, _ = await run_cases(tmp_path, port, "id_reuse_after_filled", vt=vt)
    record = case(document, "id_reuse_after_filled")
    assert record["status"] == dp.OBSERVED, record
    entry, again = sent(port, "new_limit_order")
    assert entry["price"] == MARKETABLE and entry["quantity"] == APPROVED
    assert again["price"] == FAR_BELOW and again["quantity"] == APPROVED
    assert entry["client_order_id"] == again["client_order_id"]
    assert record["details"]["entry_statuses"].endswith("FILLED")
    assert record["details"]["reuse_accepted"] == "true"
    # the filled entry left a position: the per-case cleanup flattens it
    assert len(sent(port, "new_market_order")) == 1
    assert record["cleanup"]["status"] == dp.CLEANUP_FLAT
    assert vt.sleeps == []  # the fill was visible at the first check: no wait
    assert code == dp.EXIT_OK


async def test_id_reuse_after_filled_is_not_observed_when_the_entry_does_not_fill(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.fill_marketable = False
    vt = VirtualTime()
    document, _, _ = await run_cases(tmp_path, port, "id_reuse_after_filled", vt=vt)
    record = case(document, "id_reuse_after_filled")
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "the entry did not fill: status NEW"
    assert len(sent(port, "new_limit_order")) == 1
    assert vt.sleeps == [TEST_ONLY_CASE_TIMEOUT_SECONDS]  # one wait of the owner's timeout


# --------------------------------------------------------------------------- #
# Task 1: the common rules (bound, hedge mode, script error, client ids).
# --------------------------------------------------------------------------- #


def _mark(close: str) -> Any:
    return ok_observation(
        "mark_price", {"symbol": "BTCUSDT", "interval": "1m", "count": "1", "close": close}
    )


async def test_a_notional_cap_breach_refuses_the_case_and_sends_nothing(tmp_path: Path) -> None:
    port = FakeProbePort()
    # call 0 is the run's market read; the case reads the mark again (call 1): it has risen,
    # so the far up-trigger notional is 0.002 * 96000.00 = 192, above the cap of 150
    port.script_call("mark_price", 1, _mark("80000.00"))
    document, code, _ = await run_cases(tmp_path, port, "duplicate_client_algo_id")
    record = case(document, "duplicate_client_algo_id")
    assert record["status"] == dp.ERROR
    assert "above the approved cap" in record["reason"]
    assert not any(name in ORDER_SENDS for name in case_calls(port))
    assert record["cleanup"]["status"] == dp.CLEANUP_FLAT
    assert code == dp.EXIT_FAILED


async def test_hedge_mode_makes_a_reduce_only_case_not_observed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Task 1 proves the rule on the wrapper with a stand-in reduce-only body; Task 2 and
    # Task 3 prove it on every registered reduce-only case.
    async def body(case: Any) -> dp.CaseResult:
        raise AssertionError("a reduce-only body must not run in hedge mode")

    async def handler(context: dp.CaseContext) -> dp.CaseResult:
        return await dp.run_write_case(
            context, body, case_id="preplaced_stop_reduce_only_flat", reduce_only=True
        )

    monkeypatch.setitem(dp.CASE_HANDLERS, "preplaced_stop_reduce_only_flat", handler)
    port = FakeProbePort(dual_side=True)
    document, _, _ = await run_cases(tmp_path, port, "preplaced_stop_reduce_only_flat")
    record = case(document, "preplaced_stop_reduce_only_flat")
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "hedge mode: reduceOnly cannot be sent"
    assert not any(name in ORDER_SENDS for name in port.names())


async def test_hedge_mode_uses_the_long_position_side_for_a_carrier(tmp_path: Path) -> None:
    port = FakeProbePort(dual_side=True)
    document, _, _ = await run_cases(tmp_path, port, "duplicate_client_algo_id")
    assert case(document, "duplicate_client_algo_id")["status"] == dp.OBSERVED
    assert {kw["position_side"] for kw in sent(port, "new_conditional_order")} == {"LONG"}


async def test_a_script_error_is_error_and_the_run_continues_to_cleanup(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script("new_conditional_order", RuntimeError("FAKE script bug"))
    document, code, recorder = await run_cases(
        tmp_path, port, "duplicate_client_algo_id", "id_reuse_after_canceled_normal"
    )
    record = case(document, "duplicate_client_algo_id")
    assert record["status"] == dp.ERROR
    assert record["reason"] == "script error: RuntimeError"
    assert record["cleanup"]["status"] == dp.CLEANUP_FLAT
    assert case(document, "id_reuse_after_canceled_normal")["status"] == dp.OBSERVED
    assert recorder.failures == []  # the handler returned ERROR itself: it never raised
    assert code == dp.EXIT_FAILED


async def test_every_client_id_is_unique_but_the_intended_reuse(tmp_path: Path) -> None:
    port = FakeProbePort()
    await run_cases(
        tmp_path,
        port,
        "duplicate_client_algo_id",
        "id_reuse_after_canceled_normal",
        "id_reuse_after_canceled_algo",
        "id_reuse_after_filled",
    )
    placed = [
        kw.get("client_order_id") or kw.get("client_algo_id")
        for name, kw in port.calls
        if name in ("new_limit_order", "new_conditional_order")
    ]
    assert all(dp.CLIENT_ID_RE.fullmatch(str(value)) for value in placed)
    # each case places exactly one id twice (the reuse under test); no id crosses cases
    assert sorted(placed.count(value) for value in set(placed)) == [2, 2, 2, 2]


# --------------------------------------------------------------------------- #
# Task 2: the D055 cases.
# --------------------------------------------------------------------------- #

PREPLACED = "preplaced_stop_reduce_only_flat"
ORPHAN = "entry_never_fills_protective_orphan"
FULL_FILL = "full_fill_protective_quantity"
REDUCE_ONLY_REJECT = error_observation(
    "new_conditional_order",
    code=-2022,
    category="REJECTED_DEFINITIVE",
    message="FAKE ReduceOnly Order is rejected.",
)


def _assert_preplaced_leg(kwargs: dict[str, Any]) -> None:
    assert kwargs["order_type"] == "STOP_MARKET" and kwargs["side"] == "SELL"
    assert kwargs["trigger_price"] == FAR_BELOW and kwargs["working_type"] == "MARK_PRICE"
    assert kwargs["quantity"] == APPROVED and kwargs["reduce_only"] is True
    assert kwargs["close_position"] is None and kwargs["position_side"] == "BOTH"


async def test_preplaced_leg_accepted_records_its_status_and_reconciles(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, code, _ = await run_cases(tmp_path, port, PREPLACED)
    record = case(document, PREPLACED)
    assert record["status"] == dp.OBSERVED
    (leg,) = sent(port, "new_conditional_order")
    _assert_preplaced_leg(leg)
    assert record["details"]["leg_accepted"] == "true"
    assert record["details"]["leg_status"] == "accepted status=NEW"
    assert [kw["client_algo_id"] for kw in sent(port, "query_algo_order")] == [
        leg["client_algo_id"]
    ]
    assert record["details"]["reconciliation_expected"] == (
        "open_orders=0 open_algo_orders=1 position=0"
    )
    assert record["details"]["reconciliation_matches"] == "true"
    assert code == dp.EXIT_OK


async def test_preplaced_leg_rejected_records_the_exact_answer(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script("new_conditional_order", REDUCE_ONLY_REJECT)
    document, _, _ = await run_cases(tmp_path, port, PREPLACED)
    record = case(document, PREPLACED)
    assert record["status"] == dp.OBSERVED
    assert record["details"]["leg_accepted"] == "false"
    assert record["observations"][0]["error"]["code"] == -2022
    assert record["observations"][0]["error"]["message"] == "FAKE ReduceOnly Order is rejected."
    assert sent(port, "query_algo_order") == []
    assert record["details"]["reconciliation_expected"] == (
        "open_orders=0 open_algo_orders=0 position=0"
    )
    assert record["details"]["reconciliation_matches"] == "true"


async def test_a_reconciliation_that_does_not_match_is_recorded(tmp_path: Path) -> None:
    port = FakeProbePort()
    # the leg is accepted but the open algo snapshot of the case (call 1) shows none
    port.script_call("open_algo_orders", 1, ok_observation("open_algo_orders", {"count": "0"}))
    document, _, _ = await run_cases(tmp_path, port, PREPLACED)
    details = case(document, PREPLACED)["details"]
    assert details["reconciliation_observed"] == "open_orders=0 open_algo_orders=0 position=0"
    assert details["reconciliation_matches"] == "false"


@pytest.mark.parametrize("accepted", [True, False])
async def test_closeposition_stop_flat_records_the_answer(tmp_path: Path, accepted: bool) -> None:
    port = FakeProbePort()
    if not accepted:
        port.script(
            "new_conditional_order",
            error_observation(
                "new_conditional_order",
                code=-4509,
                category="REJECTED_DEFINITIVE",
                message="FAKE Time in Force (TIF) GTE can only be used with open positions.",
            ),
        )
    document, _, _ = await run_cases(tmp_path, port, "closeposition_stop_flat")
    record = case(document, "closeposition_stop_flat")
    assert record["status"] == dp.OBSERVED
    (leg,) = sent(port, "new_conditional_order")
    assert leg["order_type"] == "STOP_MARKET" and leg["side"] == "SELL"
    assert leg["close_position"] is True and leg["quantity"] is None
    assert leg["reduce_only"] is None and leg["trigger_price"] == FAR_BELOW
    assert record["details"]["close_position_accepted"] == ("true" if accepted else "false")
    if not accepted:
        assert record["observations"][0]["error"]["code"] == -4509
        assert sent(port, "query_algo_order") == []


async def test_orphan_case_with_the_leg_left_open_cancels_it_and_reconciles(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    vt = VirtualTime()
    document, code, _ = await run_cases(tmp_path, port, PREPLACED, ORPHAN, vt=vt)
    record = case(document, ORPHAN)
    assert record["status"] == dp.OBSERVED, record
    entry = sent(port, "new_limit_order")[-1]
    leg = sent(port, "new_conditional_order")[-1]
    assert entry["price"] == FAR_BELOW and entry["side"] == "BUY"
    _assert_preplaced_leg(leg)
    calls = case_calls(port, nth=1)
    assert calls.index("new_limit_order") < calls.index("new_conditional_order")
    assert calls.index("new_conditional_order") < calls.index("cancel_order")
    assert vt.sleeps == [TEST_ONLY_CASE_TIMEOUT_SECONDS]  # one wait for a system cancel
    details = record["details"]
    assert details["leg_status_after_entry_cancel"] == "NEW"
    assert details["orphaned"] == "true"
    assert details["leg_cancel_clean"] == "true"
    assert [kw["client_algo_id"] for kw in sent(port, "cancel_algo_order")] == [
        leg["client_algo_id"]
    ]
    assert details["reconciliation_expected"] == "open_orders=0 open_algo_orders=0 position=0"
    assert details["reconciliation_matches"] == "true"
    assert code == dp.EXIT_OK


async def test_orphan_case_with_a_system_cancel_is_not_orphaned(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.on_wait.append(lambda: port.system_cancel_algo(port.open_algo_ids[-1]))
    document, _, _ = await run_cases(tmp_path, port, PREPLACED, ORPHAN)
    details = case(document, ORPHAN)["details"]
    assert details["leg_status_after_entry_cancel"] == "CANCELED"
    assert details["orphaned"] == "false"
    assert "leg_cancel_clean" not in details
    assert sent(port, "cancel_algo_order") == []


@pytest.mark.parametrize("dependent", [ORPHAN, FULL_FILL])
async def test_a_dependent_case_of_a_rejected_leg_sends_nothing(
    tmp_path: Path, dependent: str
) -> None:
    port = FakeProbePort()
    port.script("new_conditional_order", REDUCE_ONLY_REJECT)
    document, _, _ = await run_cases(tmp_path, port, PREPLACED, dependent)
    record = case(document, dependent)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "pre-placed leg not accepted"
    assert not any(name in ORDER_SENDS for name in case_calls(port, nth=1))


@pytest.mark.parametrize("dependent", [ORPHAN, FULL_FILL])
async def test_a_dependent_case_without_its_premise_case_is_not_observed(
    tmp_path: Path, dependent: str
) -> None:
    port = FakeProbePort()
    document, _, _ = await run_cases(tmp_path, port, dependent)
    record = case(document, dependent)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "premise case not run"
    assert not any(name in ORDER_SENDS for name in port.names())


@pytest.mark.parametrize("dependent", [ORPHAN, FULL_FILL])
async def test_a_dependent_case_whose_own_leg_is_rejected_stops(
    tmp_path: Path, dependent: str
) -> None:
    port = FakeProbePort()
    port.script_call("new_conditional_order", 1, REDUCE_ONLY_REJECT)
    document, _, _ = await run_cases(tmp_path, port, PREPLACED, dependent)
    record = case(document, dependent)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "pre-placed leg not accepted in this case: BAD_REQUEST -2022"
    # no entry is sent after the rejected leg of the full-fill case
    if dependent == FULL_FILL:
        assert sent(port, "new_limit_order") == []


async def test_full_fill_compares_the_position_with_the_protective_quantity(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, code, _ = await run_cases(tmp_path, port, PREPLACED, FULL_FILL)
    record = case(document, FULL_FILL)
    assert record["status"] == dp.OBSERVED, record
    calls = case_calls(port, nth=1)
    assert calls.index("new_conditional_order") < calls.index("new_limit_order")
    leg = sent(port, "new_conditional_order")[-1]
    entry = sent(port, "new_limit_order")[-1]
    _assert_preplaced_leg(leg)
    assert entry["price"] == MARKETABLE and entry["quantity"] == APPROVED
    details = record["details"]
    assert details["position_amount"] == "0.002"
    assert details["leg_quantity"] == "0.002"
    assert details["leg_status_after_fill"] == "NEW"
    assert details["protective_quantity_equals_position"] == "true"
    assert details["reconciliation_expected"] == ("open_orders=0 open_algo_orders=1 position=0.002")
    assert details["reconciliation_matches"] == "true"
    assert record["cleanup"]["status"] == dp.CLEANUP_FLAT
    assert code == dp.EXIT_OK


async def test_full_fill_without_a_fill_is_not_observed(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.fill_marketable = False
    document, _, _ = await run_cases(tmp_path, port, PREPLACED, FULL_FILL)
    record = case(document, FULL_FILL)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "the entry did not fill: status NEW"


async def test_partial_fill_is_derived_from_a_partially_filled_entry(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.partial_fill_quantity = Decimal("0.001")
    document, _, _ = await run_cases(tmp_path, port, "id_reuse_after_filled", "partial_fill")
    record = case(document, "partial_fill")
    assert record["status"] == dp.OBSERVED
    assert record["observations"]
    assert all(
        item["summary"].get("status") == "PARTIALLY_FILLED" for item in record["observations"]
    )
    assert record["details"]["derived_from"] == "id_reuse_after_filled"
    # derived: the case itself sends nothing
    assert not any(name in ORDER_SENDS for name in case_calls(port, nth=1))


async def test_partial_fill_is_seen_in_a_stream_frame_too(tmp_path: Path) -> None:
    port = FakeProbePort()
    recorder = dp.ProbeRecorder()
    recorder.results["id_reuse_after_filled"] = dp.CaseResult(
        status=dp.OBSERVED,
        observations=(ok_observation("new_limit_order", {"status": "NEW"}),),
    )
    recorder.records["id_reuse_after_filled"] = {
        "frames": {
            "events": [{"event_type": "OrderUpdateEvent", "order_status": "PARTIALLY_FILLED"}]
        }
    }
    config = make_config(tmp_path, execute=True)
    context = dp.CaseContext(rig=scenario_rig(port), config=config, recorder=recorder)
    result = await dp.CASE_HANDLERS["partial_fill"](context)
    assert result.status == dp.OBSERVED
    assert result.details["seen_in"] == "frames"


async def test_partial_fill_absent_is_not_observed(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _, _ = await run_cases(tmp_path, port, "id_reuse_after_filled", "partial_fill")
    record = case(document, "partial_fill")
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "every marketable entry filled completely at the approved size"


async def test_partial_fill_with_no_filled_entry_is_not_observed(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.fill_marketable = False
    document, _, _ = await run_cases(tmp_path, port, "id_reuse_after_filled", "partial_fill")
    record = case(document, "partial_fill")
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "no marketable entry of this run filled"


async def test_partial_fill_without_an_entry_case_is_not_observed(tmp_path: Path) -> None:
    document, _, _ = await run_cases(tmp_path, FakeProbePort(), "partial_fill")
    record = case(document, "partial_fill")
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "premise case not run"


async def test_rejected_protective_variants_records_each_answer_once(tmp_path: Path) -> None:
    port = FakeProbePort()
    answers = [
        error_observation("new_conditional_order", code=-4509, category="REJECTED_DEFINITIVE"),
        error_observation("new_conditional_order", code=-1106, category="REJECTED_DEFINITIVE"),
        error_observation("new_conditional_order", code=-2021, category="REJECTED_DEFINITIVE"),
    ]
    port.script("new_conditional_order", *answers)
    document, _, _ = await run_cases(tmp_path, port, "rejected_protective_variants")
    record = case(document, "rejected_protective_variants")
    assert record["status"] == dp.OBSERVED
    a, b, c = sent(port, "new_conditional_order")  # exactly three: none retried
    assert a["order_type"] == "TAKE_PROFIT_MARKET" and a["close_position"] is True
    assert a["quantity"] is None and a["reduce_only"] is None and a["trigger_price"] == FAR_ABOVE
    assert b["order_type"] == "STOP_MARKET" and b["close_position"] is True
    assert b["reduce_only"] is True and b["quantity"] is None and b["trigger_price"] == FAR_BELOW
    assert c["order_type"] == "STOP_MARKET" and c["side"] == "SELL"
    assert c["trigger_price"] == FAR_ABOVE and c["quantity"] == APPROVED
    assert c["reduce_only"] is None and c["close_position"] is None
    assert [item["error"]["code"] for item in record["observations"]] == [-4509, -1106, -2021]
    details = record["details"]
    assert details["variant_a_close_position_flat"].startswith("rejected BAD_REQUEST -4509")
    assert details["variant_b_reduce_only_with_close_position"].startswith("rejected")
    assert details["variant_c_wrong_side_trigger"].startswith("rejected BAD_REQUEST -2021")


async def test_rejected_protective_variants_in_hedge_mode_skip_the_reduce_only_variant(
    tmp_path: Path,
) -> None:
    port = FakeProbePort(dual_side=True)
    document, _, _ = await run_cases(tmp_path, port, "rejected_protective_variants")
    record = case(document, "rejected_protective_variants")
    assert record["status"] == dp.OBSERVED
    a, c = sent(port, "new_conditional_order")
    assert a["position_side"] == "LONG" and c["position_side"] == "SHORT"
    assert record["details"]["variant_b_reduce_only_with_close_position"] == (
        "NOT_OBSERVED: hedge mode: reduceOnly cannot be sent"
    )


@pytest.mark.parametrize("case_id", [PREPLACED, ORPHAN, FULL_FILL])
async def test_the_reduce_only_d055_cases_are_not_observed_in_hedge_mode(
    tmp_path: Path, case_id: str
) -> None:
    port = FakeProbePort(dual_side=True)
    document, _, _ = await run_cases(tmp_path, port, case_id)
    record = case(document, case_id)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "hedge mode: reduceOnly cannot be sent"
    assert not any(name in ORDER_SENDS for name in port.names())


async def test_closeposition_stop_flat_runs_in_hedge_mode_with_the_long_side(
    tmp_path: Path,
) -> None:
    port = FakeProbePort(dual_side=True)
    document, _, _ = await run_cases(tmp_path, port, "closeposition_stop_flat")
    assert case(document, "closeposition_stop_flat")["status"] == dp.OBSERVED
    (leg,) = sent(port, "new_conditional_order")
    assert leg["position_side"] == "LONG"


# --------------------------------------------------------------------------- #
# Task 3: the G2-029 additions.
# --------------------------------------------------------------------------- #

BELOW_MIN = "below_min_notional_reduce_only_leg"
TRIGGERED = "triggered_market_exit_lifecycle"


def _filters(**changes: str) -> Any:
    summary = dict(fake_symbol_filters("BTCUSDT").summary)
    summary.update(changes)
    return ok_observation("symbol_filters", summary)


async def test_below_min_notional_impossible_is_not_observed_and_sends_nothing(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    # 0.001 * 48000.00 = 48 is not below a minimum notional of 40
    port.script_call("symbol_filters", 1, _filters(min_notional="40"))
    document, _, _ = await run_cases(tmp_path, port, BELOW_MIN)
    record = case(document, BELOW_MIN)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == (
        "the smallest valid quantity 0.001 at trigger 48000.00 has notional 48.00000, "
        "not below the minimum notional 40"
    )
    assert not any(name in ORDER_SENDS for name in port.names())


@pytest.mark.parametrize("accepted", [True, False])
async def test_below_min_notional_leg_records_accept_or_the_exact_reject(
    tmp_path: Path, accepted: bool
) -> None:
    port = FakeProbePort()
    if not accepted:
        port.script(
            "new_conditional_order",
            error_observation(
                "new_conditional_order",
                code=-4164,
                category="REJECTED_DEFINITIVE",
                message="FAKE Order's notional must be no smaller than 100",
            ),
        )
    document, code, _ = await run_cases(tmp_path, port, BELOW_MIN)
    record = case(document, BELOW_MIN)
    assert record["status"] == dp.OBSERVED, record
    (entry,) = sent(port, "new_limit_order")
    assert entry["price"] == MARKETABLE and entry["quantity"] == APPROVED
    (leg,) = sent(port, "new_conditional_order")
    assert leg["quantity"] == Decimal("0.001") and leg["reduce_only"] is True
    assert leg["trigger_price"] == FAR_BELOW and leg["order_type"] == "STOP_MARKET"
    details = record["details"]
    assert details["smallest_quantity"] == "0.001"
    assert details["leg_notional"] == "48.00000"
    assert details["leg_accepted"] == ("true" if accepted else "false")
    if not accepted:
        error = next(item["error"] for item in record["observations"] if not item["ok"])
        assert error["code"] == -4164
    assert record["cleanup"]["status"] == dp.CLEANUP_FLAT
    assert code == dp.EXIT_OK


async def test_below_min_notional_without_a_position_is_not_observed(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.fill_marketable = False
    document, _, _ = await run_cases(tmp_path, port, BELOW_MIN)
    record = case(document, BELOW_MIN)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "no open position: the entry did not fill: status NEW"
    assert sent(port, "new_conditional_order") == []


async def test_a_quantity_above_the_approved_one_refuses_the_case_and_sends_nothing(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    # the smallest valid quantity (0.005) is above the approved 0.002; its notional at the
    # far trigger (240) is below the minimum notional (1000), so the case would send it
    port.script_call("symbol_filters", 1, _filters(min_quantity="0.005", min_notional="1000"))
    document, _, _ = await run_cases(tmp_path, port, BELOW_MIN)
    record = case(document, BELOW_MIN)
    assert record["status"] == dp.ERROR
    assert "above the approved quantity" in record["reason"]
    assert not any(name in ORDER_SENDS for name in port.names())


def _trigger_latest(port: FakeProbePort) -> None:
    port.on_wait.append(lambda: port.trigger_algo(port.open_algo_ids[-1]))


async def test_the_triggered_exit_lifecycle_is_observed_with_the_child_identity(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    _trigger_latest(port)
    vt = VirtualTime()
    document, code, _ = await run_cases(tmp_path, port, TRIGGERED, vt=vt)
    record = case(document, TRIGGERED)
    assert record["status"] == dp.OBSERVED, record
    (entry,) = sent(port, "new_limit_order")
    assert entry["price"] == MARKETABLE
    (leg,) = sent(port, "new_conditional_order")
    assert leg["order_type"] == "STOP_MARKET" and leg["side"] == "SELL"
    assert leg["reduce_only"] is True and leg["quantity"] == APPROVED
    assert leg["trigger_price"] == JUST_BELOW and leg["working_type"] == "MARK_PRICE"
    assert vt.sleeps == [TEST_ONLY_CASE_TIMEOUT_SECONDS]  # one wait_up_to of the case timeout
    details = record["details"]
    assert details["algo_statuses_frames"] == "TRIGGERING,TRIGGERED,FINISHED"
    assert details["algo_statuses_rest"] == "NEW,FINISHED"
    assert details["child_ai"] == "FAKE-CHILD-1"
    assert details["child_aq"] == "0.002"
    assert details["child_c"] == "FAKE-CHILD-C"
    assert details["child_i"] == "FAKE-CHILD-1"
    assert details["filter_market_lot_max_quantity"] == "120"
    assert details["filter_max_quantity"] == "1000"
    assert details["market_lot_size_question"] == (
        "NOT_OBSERVED at the approved size: the optional case market_lot_size_out_of_range "
        "is not enabled"
    )
    assert code == dp.EXIT_OK


async def test_the_triggered_exit_not_reached_within_the_case_timeout_is_not_observed(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    vt = VirtualTime()
    document, _, _ = await run_cases(tmp_path, port, TRIGGERED, vt=vt)
    record = case(document, TRIGGERED)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "the trigger was not reached within case_timeout_seconds"
    assert vt.sleeps == [TEST_ONLY_CASE_TIMEOUT_SECONDS]
    assert record["details"]["child_ai"].startswith("NOT_OBSERVED")
    assert record["observations"]  # the answers are kept with the reason


async def test_a_rejected_exit_leg_is_not_observed_with_the_answer(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "new_conditional_order",
        error_observation("new_conditional_order", code=-2021, category="REJECTED_DEFINITIVE"),
    )
    vt = VirtualTime()
    document, _, _ = await run_cases(tmp_path, port, TRIGGERED, vt=vt)
    record = case(document, TRIGGERED)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "the exit leg was not accepted: BAD_REQUEST -2021"
    assert vt.sleeps == []


async def test_the_triggered_exit_names_the_optional_market_lot_case_when_enabled(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    _trigger_latest(port)
    document, _, _ = await run_cases(
        tmp_path,
        port,
        TRIGGERED,
        "market_lot_size_out_of_range",
        optional=("market_lot_size_out_of_range",),
    )
    assert case(document, TRIGGERED)["details"]["market_lot_size_question"] == (
        "NOT_OBSERVED at the approved size; the optional case market_lot_size_out_of_range "
        "of this run answers it"
    )


@pytest.mark.parametrize("case_id", [BELOW_MIN, TRIGGERED])
async def test_the_g2_029_cases_are_not_observed_in_hedge_mode(
    tmp_path: Path, case_id: str
) -> None:
    port = FakeProbePort(dual_side=True)
    document, _, _ = await run_cases(tmp_path, port, case_id)
    record = case(document, case_id)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "hedge mode: reduceOnly cannot be sent"


# --------------------------------------------------------------------------- #
# Task 3: the optional cases.
# --------------------------------------------------------------------------- #


async def test_the_explicit_time_in_force_variant_sends_one_leg_per_documented_value(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script_call(
        "new_conditional_order",
        4,
        error_observation("new_conditional_order", code=-1106, category="REJECTED_DEFINITIVE"),
    )
    document, _, _ = await run_cases(
        tmp_path, port, "explicit_time_in_force_variant", optional=("explicit_time_in_force",)
    )
    record = case(document, "explicit_time_in_force_variant")
    assert record["status"] == dp.OBSERVED
    legs = sent(port, "new_conditional_order")
    assert [kw["time_in_force"] for kw in legs] == ["GTC", "IOC", "FOK", "GTX", "GTD", "RPI"]
    for kw in legs:
        _assert_preplaced_leg(kw)
    assert len({kw["client_algo_id"] for kw in legs}) == 6
    assert record["details"]["leg_GTD"].startswith("rejected BAD_REQUEST -1106")
    assert len(record["observations"]) == 6  # one answer each, none retried


@pytest.mark.parametrize(
    ("key", "case_id"),
    [
        ("explicit_time_in_force", "explicit_time_in_force_variant"),
        ("stream_gap", "stream_gap_during_case"),
        ("market_lot_size_out_of_range", "market_lot_size_out_of_range"),
    ],
)
def test_an_optional_case_runs_only_when_enabled(tmp_path: Path, key: str, case_id: str) -> None:
    assert case_id not in make_config(tmp_path, execute=True).case_ids
    assert case_id in make_config(tmp_path, execute=True, optional=(key,)).case_ids


async def test_the_stream_gap_case_without_a_stream_is_not_observed(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _, _ = await run_cases(
        tmp_path, port, "stream_gap_during_case", optional=("stream_gap",)
    )
    record = case(document, "stream_gap_during_case")
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "no stream running"
    assert "drop_stream_transport" in port.names()
    (order,) = sent(port, "new_limit_order")
    assert order["price"] == FAR_BELOW


async def test_the_stream_gap_case_records_the_recovery_and_reconciles(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.drop_results.append(True)
    for state in ("UNKNOWN", "CONNECTING", "SYNCING", "LIVE"):
        port.on_wait.append(lambda state=state: port.emit_state(state))
    vt = VirtualTime()
    document, code, _ = await run_cases(
        tmp_path, port, "stream_gap_during_case", optional=("stream_gap",), vt=vt
    )
    record = case(document, "stream_gap_during_case")
    assert record["status"] == dp.OBSERVED, record
    assert vt.sleeps == [TEST_ONLY_CASE_TIMEOUT_SECONDS]
    details = record["details"]
    assert details["transport_dropped"] == "true"
    assert details["stream_states_after_drop"] == "UNKNOWN,CONNECTING,SYNCING,LIVE"
    assert details["stream_recovered_live"] == "true"
    assert details["reconciliation_expected"] == "open_orders=1 open_algo_orders=0 position=0"
    assert details["reconciliation_matches"] == "true"
    assert len(sent(port, "cancel_order")) == 1
    assert code == dp.EXIT_OK


async def test_the_market_lot_case_places_the_owner_approved_quantity(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "new_conditional_order",
        error_observation(
            "new_conditional_order",
            code=-4005,
            category="REJECTED_DEFINITIVE",
            message="FAKE Quantity greater than max quantity.",
        ),
    )
    document, _, _ = await run_cases(
        tmp_path,
        port,
        "market_lot_size_out_of_range",
        optional=("market_lot_size_out_of_range",),
    )
    record = case(document, "market_lot_size_out_of_range")
    # the placement answer is the finding: OBSERVED with the exact answer
    assert record["status"] == dp.OBSERVED
    (leg,) = sent(port, "new_conditional_order")
    assert leg["quantity"] == Decimal("200")  # notional ~12 million: the cap is not applied
    assert leg["reduce_only"] is True and leg["trigger_price"] == JUST_BELOW
    error = next(item["error"] for item in record["observations"] if not item["ok"])
    assert error["code"] == -4005
    assert record["details"]["market_lot_probe_quantity"] == "200"


async def test_the_market_lot_case_accepted_follows_the_lifecycle(tmp_path: Path) -> None:
    port = FakeProbePort()
    _trigger_latest(port)
    document, _, _ = await run_cases(
        tmp_path,
        port,
        "market_lot_size_out_of_range",
        optional=("market_lot_size_out_of_range",),
    )
    record = case(document, "market_lot_size_out_of_range")
    assert record["status"] == dp.OBSERVED
    assert record["details"]["algo_statuses_frames"] == "TRIGGERING,TRIGGERED,FINISHED"


# --------------------------------------------------------------------------- #
# Task 3: ban and rate limit in a write case.
# --------------------------------------------------------------------------- #

REUSE_ALGO = "id_reuse_after_canceled_algo"


@pytest.mark.parametrize("port_banned", [False, True])
async def test_a_ban_in_a_write_case_aborts_the_run_with_one_cleanup_attempt(
    tmp_path: Path, port_banned: bool
) -> None:
    port = FakeProbePort()
    port.banned = port_banned
    port.script("cancel_algo_order", ProbeBanned(IP_BAN_418, 600))
    document, code, _ = await run_cases(tmp_path, port, REUSE_ALGO, "id_reuse_after_filled")
    assert document["outcome"] == dp.OUTCOME_ABORTED_BAN
    assert code == dp.EXIT_FAILED
    assert case(document, REUSE_ALGO)["reason"] == dp.REASON_BAN
    later = case(document, "id_reuse_after_filled")
    assert later["status"] == dp.NOT_OBSERVED and later["reason"] == dp.REASON_BAN
    ban = document["ban"]
    assert ban["reason"] == IP_BAN_418 and ban["during"] == REUSE_ALGO
    carrier = sent(port, "new_conditional_order")[0]["client_algo_id"]
    assert ban["known_state"]["algo_orders_not_known_closed"] == carrier
    assert ban["case_observations"][0]["ok"] is True  # the carrier's answer is kept
    after_ban = port.names()[port.names().index("cancel_algo_order") + 1 :]
    if port_banned:
        assert after_ban == []
        assert ban["cleanup_after_ban"]["status"] == dp.CLEANUP_NOT_VERIFIED
        assert "adapter reports a ban" in ban["cleanup_after_ban"]["reason"]
    else:
        assert after_ban[:2] == ["cancel_all_open_orders", "cancel_all_algo_open_orders"]
        assert after_ban.count("cancel_all_open_orders") == 1  # attempted once
        assert ban["cleanup_after_ban"]["status"] == dp.CLEANUP_FLAT
    assert document["cleanup"]["final"]["status"] == dp.CLEANUP_NOT_VERIFIED


async def test_a_ban_refusing_the_cleanup_after_a_ban_is_recorded(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script("cancel_algo_order", ProbeBanned(IP_BAN_418, 600))
    port.script("cancel_all_open_orders", ProbeBanned(IP_BAN_418, 599))
    document, _, _ = await run_cases(tmp_path, port, REUSE_ALGO)
    cleanup = document["ban"]["cleanup_after_ban"]
    assert cleanup["status"] == dp.CLEANUP_NOT_VERIFIED
    assert cleanup["reason"] == f"refused: {IP_BAN_418}"


async def test_a_rate_limit_answer_in_a_write_case_stops_the_case_and_the_run(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script(
        "new_conditional_order",
        error_observation(
            "new_conditional_order",
            code=-1003,
            category="RATE_LIMITED",
            http_class="TOO_MANY_429",
            retry_after_seconds=None,
        ),
    )
    document, code, _ = await run_cases(tmp_path, port, "duplicate_client_algo_id", REUSE_ALGO)
    record = case(document, "duplicate_client_algo_id")
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"].startswith("a rate-limit answer")
    assert record["observations"][0]["error"]["category"] == "RATE_LIMITED"
    assert port.names()[-1] == "new_conditional_order"  # nothing after the answer
    assert document["outcome"] == dp.OUTCOME_ABORTED_BAN
    assert case(document, REUSE_ALGO)["reason"] == dp.REASON_BAN
    assert code == dp.EXIT_FAILED


# --------------------------------------------------------------------------- #
# Task 3: completeness of the registry, the dry run and handler purity.
# --------------------------------------------------------------------------- #


def test_every_case_id_has_a_registered_handler() -> None:
    assert set(dp.CASE_HANDLERS) == set(dp.REQUIRED_CASES) | set(dp.OPTIONAL_CASES.values())
    assert set(dp.CASE_HANDLERS) == set(dp.CASE_ORDER)
    for case_id in dp.OPTIONAL_CASES.values():
        assert case_id in dp.CASE_HANDLERS


async def test_the_dry_run_with_every_optional_case_rehearses_every_handler_without_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path, optional=ALL_OPTIONAL)
    invoked: list[str] = []
    wrapped: dict[str, dp.CaseHandler] = {}
    for case_id, handler in dp.CASE_HANDLERS.items():

        def make(cid: str, inner: dp.CaseHandler) -> dp.CaseHandler:
            async def counting(context: dp.CaseContext) -> dp.CaseResult:
                invoked.append(cid)
                return await inner(context)

            return counting

        wrapped[case_id] = make(case_id, handler)
    monkeypatch.setattr(dp, "CASE_HANDLERS", wrapped)
    recorder = dp.ProbeRecorder()
    code = await dp.run_probe(config, dp.build_dry_run_rig(config), recorder)
    document = recorder.document(config)
    assert code == dp.EXIT_OK and document["outcome"] == dp.OUTCOME_COMPLETE
    assert invoked == list(dp.CASE_ORDER)  # every handler once, in CASE_ORDER
    assert [item["case_id"] for item in document["cases"]] == list(dp.CASE_ORDER)
    for item in document["cases"]:
        assert item["status"] == dp.NOT_REHEARSED
        assert item["handler_registered"] is True
    assert not [cid for cid, result in recorder.results.items() if result.status == dp.ERROR], {
        cid: result.reason for cid, result in recorder.results.items()
    }
    planned = {item["case_id"]: item["planned_requests"] for item in document["cases"]}
    assert [r["operation"] for r in planned["duplicate_client_algo_id"]] == [
        "new_conditional_order",
        "new_conditional_order",
        "cancel_algo_order",
    ]
    assert any(r["operation"] == "new_limit_order" for r in planned["id_reuse_after_filled"])
    assert planned["partial_fill"] == []  # derived: nothing is sent
    for requests in planned.values():
        for request in requests:
            if request["operation"].startswith("new_"):
                assert request["mutating"] is True


def _function_nodes(tree: ast.Module) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_no_handler_sleeps_and_every_case_wait_is_the_owners_case_timeout() -> None:
    tree = ast.parse(Path(dp.__file__).read_text(encoding="utf-8"))
    functions = _function_nodes(tree)
    sleep_callers: set[str] = set()
    waits: list[tuple[str, str, str]] = []
    for name, node in functions.items():
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            text = ast.unparse(call.func)
            if text == "sleep" or text.endswith(".sleep"):
                sleep_callers.add(name)
            if text == "wait_up_to":
                assert len(call.args) == 3, ast.unparse(call)
                waits.append((name, ast.unparse(call.args[0]), ast.unparse(call.args[2])))
    # the only sleep call of the script is the rig's sleep inside wait_up_to
    assert sleep_callers == {"wait_up_to"}
    assert waits, "the write cases wait through wait_up_to"
    for name, rig, timeout in waits:
        assert rig.endswith("rig"), (name, rig)
        if name == "cleanup_symbol":
            assert timeout == "timeout_seconds"
        else:
            assert timeout.endswith("case_timeout_seconds"), (name, timeout)
    for handler in dp.CASE_HANDLERS.values():
        source = inspect.getsource(handler)
        assert "asyncio.sleep" not in source and "time.sleep" not in source


async def test_a_case_wait_sleeps_exactly_the_owners_case_timeout(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.fill_marketable = False
    vt = VirtualTime()
    await run_cases(tmp_path, port, "id_reuse_after_filled", vt=vt)
    config = make_config(tmp_path, execute=True)
    assert vt.sleeps == [config.order_limits.case_timeout_seconds]


class _UnusedModeReader:
    async def get_position_mode(self) -> Any:
        raise AssertionError("not read in this test")


def _ban_flag_adapter(flag: object) -> object:
    class _Adapter:
        pass

    adapter = _Adapter()
    if flag is not None:
        adapter.banned = flag  # type: ignore[attr-defined]
    return adapter


@pytest.mark.parametrize(
    ("flag", "expected"), [(False, False), (True, True), (None, True), ("no", True)]
)
def test_the_guarded_port_reports_the_adapter_ban_flag_failing_closed(
    flag: object, expected: bool
) -> None:
    port = dp.GuardedProbePort(
        _ban_flag_adapter(flag),
        position_mode_reader=_UnusedModeReader(),
        frames=dp.FrameLog(),
        guard=lambda: None,
        mode=dp.MODE_EXECUTE,
    )
    assert port.banned is expected


def _market(mark: str, up: str | None = "1.0500") -> dp._Market:
    return dp._Market(
        mark=Decimal(mark),
        tick=Decimal("0.1"),
        step=Decimal("0.0001"),
        min_quantity=Decimal("0.0001"),
        min_notional=Decimal("50"),
        multiplier_up=None if up is None else Decimal(up),
        filters={},
    )


def test_the_marketable_buy_stays_inside_the_percent_price_band_when_the_mark_is_stale() -> None:
    """Live finding 2026-10-16 (id_reuse_after_filled, -4016): the mark came from the last
    one-minute close, which can sit above the exchange's own mark. A BUY at the band edge of
    that mark was above the exchange cap. The price must cross the book yet leave room for a
    mark that is lower by a share of the band."""
    market = _market("82247.1")
    price = market.marketable_buy()
    edge = market.mark * Decimal("1.0500")
    assert market.mark < price < edge
    # the exchange cap of the live run was 86305.10, the band edge of its own mark 82195.33
    assert price <= Decimal("86305.10")


def test_the_marketable_buy_still_refuses_an_unreadable_band() -> None:
    with pytest.raises(dp._StopCase):
        _market("82247.1", up=None).marketable_buy()


# --------------------------------------------------------------------------- #
# The fakes keep the `ProbePort` signatures (review WR-02).
# --------------------------------------------------------------------------- #


def _port_methods() -> list[str]:
    return sorted(
        name
        for name, member in vars(dp.ProbePort).items()
        if inspect.isfunction(member) and not name.startswith("_")
    )


def _shape(function: Callable[..., Any]) -> list[tuple[str, Any, bool]]:
    """(name, kind, has_default) of every parameter except `self`, in order."""
    return [
        (parameter.name, parameter.kind, parameter.default is not inspect.Parameter.empty)
        for parameter in inspect.signature(function).parameters.values()
        if parameter.name != "self"
    ]


@pytest.mark.parametrize("fake", [FakeProbePort, RecordingProbePort], ids=lambda c: c.__name__)
def test_the_probe_port_fakes_have_the_protocol_signatures(fake: type) -> None:
    methods = _port_methods()
    assert "new_limit_order" in methods and "new_conditional_order" in methods
    for name in methods:
        assert hasattr(fake, name), name
        assert _shape(getattr(fake, name)) == _shape(getattr(dp.ProbePort, name)), name


def test_the_probe_adapter_keeps_the_protocol_signatures_it_implements() -> None:
    from src.adapters.binance_probe import BinanceProbeAdapter

    shared = [name for name in _port_methods() if hasattr(BinanceProbeAdapter, name)]
    assert {"new_limit_order", "new_market_order", "new_conditional_order"} <= set(shared)
    for name in shared:
        assert _shape(getattr(BinanceProbeAdapter, name)) == _shape(getattr(dp.ProbePort, name)), (
            name
        )


async def test_a_fake_order_for_another_symbol_is_refused() -> None:
    port = FakeProbePort()
    with pytest.raises(AssertionError):
        await port.new_limit_order(
            symbol="ETHUSDT",
            side="BUY",
            quantity=Decimal("0.001"),
            price=Decimal("1"),
            client_order_id="c-1",
            position_side="BOTH",
            time_in_force="GTC",
            reduce_only=None,
        )


async def test_a_wrong_side_or_partial_reduce_only_order_does_not_flatten_the_fake() -> None:
    port = FakeProbePort()
    port.positions_rows.append(("BOTH", Decimal("0.010")))
    await port.new_market_order(
        symbol="BTCUSDT",
        side="BUY",  # the wrong side for a long
        quantity=Decimal("0.010"),
        client_order_id="c-1",
        position_side="BOTH",
        reduce_only=True,
    )
    assert port.positions_rows == [("BOTH", Decimal("0.010"))]
    await port.new_market_order(
        symbol="BTCUSDT",
        side="SELL",
        quantity=Decimal("0.004"),  # smaller than the position
        client_order_id="c-2",
        position_side="BOTH",
        reduce_only=True,
    )
    assert port.positions_rows == [("BOTH", Decimal("0.006"))]
