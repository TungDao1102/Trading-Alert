"""The Demo probe runner on fakes (plan 18-17 Task 1): order, dry run, cases, cleanup, time.

Everything runs offline on `FakeProbePort` or `RecordingProbePort` and on virtual time
(`tests/support/virtual_time.py`); nothing sleeps in real time and nothing reaches Binance.
The limits are TEST_ONLY values written by `write_probe_limits`; the ratified Binance limits
file is read through the script's own default path.
"""

from __future__ import annotations

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
    assert port.names()[-3:] == ["open_orders", "open_algo_orders", "positions"] or (
        "cancel_all_open_orders" in port.names()
    )
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
MARKETABLE = Decimal("63000.00")
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
