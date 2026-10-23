"""The eight owner opt-in cases of quick task 261023-sj2, on fakes and virtual time.

`reduce_only_market_on_flat` (A4), `reduce_only_market_larger_than_position` (A8),
`non_reduce_only_below_min_notional` (-4164), `insufficient_margin_order` (-2019),
`stop_rejected_after_acceptance` (P5), `trigger_cancel_race` (P7), `timestamp_outside_recv_window`
(-1021) and `income_history_read` extend the capture framework of quick tasks 261021-sj0 and
261022-sj1. Everything runs offline on `FakeProbePort` / `RecordingProbePort` and on virtual
time; nothing sleeps in real time and nothing reaches Binance. The FAKE market is the one of the
sj0 tests: mark 60000.00, tick 0.10, step 0.001, quantity 0.002, notional cap 150,
far_price_fraction 0.80 (a far BUY rests at 48000.00, a marketable BUY is priced at 61500.00),
near_trigger_fraction 0.999 (a near stop sits at 59940.00), recvWindow 5000 (the ratified file).
"""

from __future__ import annotations

import ast
import inspect
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from scripts import demo_probe as dp

from tests.probe_fakes import (
    TEST_ONLY_CASE_TIMEOUT_SECONDS,
    TEST_ONLY_MARGIN_QUANTITY,
    TEST_ONLY_RACE_REPEATS,
    FakeProbePort,
    error_observation,
    fake_symbol_filters,
    ok_observation,
)
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START, VirtualTime
from tests.test_demo_probe_capture_cases import case, make_config, run_cases, sent
from tests.test_demo_probe_sj1_cases import nothing_sent, sub

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
START_MS = (TEST_ONLY_VIRTUAL_START - EPOCH) // timedelta(milliseconds=1)
FLAT = "reduce_only_market_on_flat"
OVERSIZE = "reduce_only_market_larger_than_position"
MIN_NOTIONAL = "non_reduce_only_below_min_notional"
MARGIN = "insufficient_margin_order"
STOP_REJECT = "stop_rejected_after_acceptance"
TRIGGER_RACE = "trigger_cancel_race"
RECV = "timestamp_outside_recv_window"
INCOME = "income_history_read"
NEW_CASES = (FLAT, OVERSIZE, MIN_NOTIONAL, MARGIN, STOP_REJECT, TRIGGER_RACE, RECV, INCOME)
APPROVED = Decimal("0.002")
CAP = Decimal("150")
NEAR_STOP = Decimal("59940.00")
ORDER_CASES = (FLAT, OVERSIZE, MIN_NOTIONAL, MARGIN, STOP_REJECT, TRIGGER_RACE)
READ_ONLY_CASES = (RECV, INCOME)

REDUCE_ONLY_REJECTED = error_observation(
    "new_market_order",
    code=-2022,
    category="REJECTED_DEFINITIVE",
    message="FAKE ReduceOnly Order is rejected.",
)
MARGIN_REJECTED = error_observation(
    "new_limit_order",
    code=-2019,
    category="REJECTED_DEFINITIVE",
    message="FAKE Margin is insufficient.",
)
MIN_NOTIONAL_REJECTED = error_observation(
    "new_limit_order",
    code=-4164,
    category="REJECTED_DEFINITIVE",
    message="FAKE Order's notional must be no smaller than 100.",
)


def assert_orders_within_caps(
    port: FakeProbePort, *, except_quantity: Decimal | None = None
) -> None:
    """No order the case sent is above the approved quantity or the notional cap."""
    for name, kwargs in port.calls:
        if name not in ("new_limit_order", "new_market_order", "new_conditional_order"):
            continue
        quantity = kwargs.get("quantity")
        if quantity is None:
            continue  # a closePosition leg has no quantity
        if except_quantity is not None and quantity == except_quantity:
            continue
        assert quantity <= APPROVED, (name, kwargs)
        price = kwargs.get("price") or kwargs.get("trigger_price")
        if price is not None:
            assert quantity * price <= CAP, (name, kwargs)


def errors(document: dict[str, Any]) -> list[str]:
    return [item["case_id"] for item in document["cases"] if item["status"] == dp.ERROR]


# --------------------------------------------------------------------------- #
# Registry, loader wiring, dry run.
# --------------------------------------------------------------------------- #


def test_the_eight_cases_are_registered_with_their_own_keys_and_handlers() -> None:
    assert dp.SJ2_CASES == NEW_CASES
    keys = {case_id: key for key, case_id in dp.OPTIONAL_CASES.items()}
    assert [keys[case_id] for case_id in NEW_CASES] == [
        "reduce_only_flat",
        "reduce_only_oversize",
        "min_notional_entry",
        "insufficient_margin",
        "stop_reject_after_accept",
        "trigger_cancel_race",
        "recv_window_error",
        "income_history",
    ]
    assert set(dp.CASE_HANDLERS) == set(dp.CASE_ORDER)
    order = list(dp.CASE_ORDER)
    assert order[-1] == "gtd_entry_expiry_status"  # the case that waits runs last
    assert order[-9:-1] == list(NEW_CASES)  # contiguous, right before the GTD case
    assert order.index("stream_loss_during_case") < order.index(FLAT)
    assert dp.FIXTURE_CASES == (*dp.CAPTURE_CASES, *dp.SJ1_CASES, *dp.SJ2_CASES)
    assert not set(dp.SJ2_CASES) & (set(dp.CAPTURE_CASES) | set(dp.SJ1_CASES))


async def test_a_dry_run_with_every_key_on_has_no_error_and_the_eight_not_rehearsed(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, case_ids=tuple(dp.OPTIONAL_CASES.values()), execute=False)
    recorder = dp.ProbeRecorder()
    await dp.run_probe(config, dp.build_dry_run_rig(config), recorder)
    document = recorder.document(config)
    by_id = {item["case_id"]: item for item in document["cases"]}
    for case_id in NEW_CASES:
        assert by_id[case_id]["status"] == dp.NOT_REHEARSED, case_id
    assert not errors(document)
    assert document["schema"] == "demo-probe-evidence/schema-1"
    # the dry run plans requests, and none of them is above the cap except the margin case
    for case_id, item in by_id.items():
        for planned in item["planned_requests"]:
            quantity = planned["kwargs"].get("quantity")
            if quantity is None or case_id == MARGIN:
                continue
            assert Decimal(str(quantity)) <= Decimal("0.2"), (case_id, planned)


async def test_a_disabled_new_case_cannot_be_named_by_only(tmp_path: Path) -> None:
    from tests.probe_fakes import write_probe_limits

    limits = write_probe_limits(tmp_path, optional=("reduce_only_flat",))
    with pytest.raises(dp.UsageError):
        dp.parse_config(
            [
                "--environment",
                "DEMO",
                "--probe-limits-file",
                str(limits),
                "--evidence-dir",
                str(tmp_path / "e"),
                "--only",
                OVERSIZE,
            ]
        )


@pytest.mark.parametrize("case_id", ORDER_CASES)
async def test_every_order_case_refuses_hedge_mode_with_nothing_sent(
    tmp_path: Path, case_id: str
) -> None:
    port = FakeProbePort(dual_side=True)
    document, _ = await run_cases(tmp_path, port, case_id)
    record = case(document, case_id)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == dp.REASON_HEDGE_MODE
    assert nothing_sent(port)


@pytest.mark.parametrize("case_id", READ_ONLY_CASES)
async def test_the_read_only_cases_send_no_order_at_all(tmp_path: Path, case_id: str) -> None:
    port = FakeProbePort()
    port.income_rows = [{"income_type": "COMMISSION", "income": "-0.1", "asset": "USDT"}]
    await run_cases(tmp_path, port, case_id)
    assert nothing_sent(port)


async def test_an_executed_run_writes_the_rest_fixtures_of_the_new_cases(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.income_rows = [{"income_type": "COMMISSION", "income": "-0.1", "asset": "USDT"}]
    document, _ = await run_cases(tmp_path, port, INCOME, fixtures=True)
    names = case(document, INCOME)["rest_fixtures"]
    assert names and all(name.startswith(f"{INCOME}-rest-") for name in names)
    assert (tmp_path / "fixtures" / names[0]).is_file()


# --------------------------------------------------------------------------- #
# reduce_only_market_on_flat (A4).
# --------------------------------------------------------------------------- #


async def test_a_reduce_only_market_on_a_flat_account_records_the_exact_rejection(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script_call("new_market_order", 0, REDUCE_ONLY_REJECTED)
    document, code = await run_cases(tmp_path, port, FLAT)
    record = case(document, FLAT)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    (order,) = sent(port, "new_market_order")[:1]
    assert order["reduce_only"] is True and order["quantity"] == APPROVED
    assert order["side"] == "SELL" and order["position_side"] == "BOTH"
    details = record["details"]
    assert details["order_accepted"] == "false"
    assert details["order_error_code"] == "-2022"
    assert details["order_error_class"] == "BAD_REQUEST"
    assert details["order_error_category"] == "REJECTED_DEFINITIVE"
    assert details["order_error_message"] == "FAKE ReduceOnly Order is rejected."
    assert details["flipped"] == "false"
    assert details["position_after"] == "0"
    assert len(sent(port, "new_market_order")) == 1  # the rejected one; nothing to flatten
    assert_orders_within_caps(port)


async def test_the_flat_precheck_stops_the_case_when_a_position_exists(tmp_path: Path) -> None:
    port = FakeProbePort()
    row = {"symbol": "BTCUSDT", "position_side": "BOTH", "position_amt": "0.001"}
    # call 0 is the run-start account read, call 1 the precheck of the case
    port.script_call(
        "positions",
        1,
        ok_observation("positions", {"count": "1", **{f"row_0_{k}": v for k, v in row.items()}}),
    )
    document, _ = await run_cases(tmp_path, port, FLAT)
    record = case(document, FLAT)
    assert record["status"] == dp.NOT_OBSERVED
    assert "not flat" in record["reason"]
    assert nothing_sent(port)


async def test_the_flat_precheck_stops_the_case_when_an_order_is_open(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call(
        "open_orders",
        1,
        ok_observation("open_orders", {"count": "1", "row_0_client_order_id": "x"}),
    )
    document, _ = await run_cases(tmp_path, port, FLAT)
    assert case(document, FLAT)["status"] == dp.NOT_OBSERVED
    assert nothing_sent(port)


class _FlippingPort(FakeProbePort):
    """A reduce-only market on a flat account is (FAKE) accepted and opens a short."""

    async def new_market_order(self, **kwargs: Any) -> Any:
        if self.count("new_market_order") == 0:
            self.calls.append(("new_market_order", dict(kwargs)))
            self.positions_rows = [("BOTH", -Decimal(kwargs["quantity"]))]
            return ok_observation(
                "new_market_order",
                {"client_order_id": kwargs["client_order_id"], "status": "FILLED"},
            )
        return await super().new_market_order(**kwargs)


async def test_an_accepted_reduce_only_that_opened_a_position_is_flattened_and_flagged(
    tmp_path: Path,
) -> None:
    port = _FlippingPort()
    document, _ = await run_cases(tmp_path, port, FLAT)
    record = case(document, FLAT)
    assert record["status"] == dp.OBSERVED
    details = record["details"]
    assert details["order_accepted"] == "true"
    assert details["flipped"] == "true"
    assert details["position_after"] == "-0.002"
    first, second = sent(port, "new_market_order")[:2]
    assert (second["side"], second["reduce_only"], second["quantity"]) == ("BUY", True, APPROVED)
    assert port.positions_rows == []
    assert record["cleanup"]["status"] == dp.CLEANUP_FLAT
    assert_orders_within_caps(port)


async def test_an_accepted_reduce_only_without_a_position_change_is_not_flipped(
    tmp_path: Path,
) -> None:
    class _NoOp(FakeProbePort):
        pass

    port = _NoOp()  # the FAKE default accepts and changes nothing on a flat account
    document, _ = await run_cases(tmp_path, port, FLAT)
    details = case(document, FLAT)["details"]
    assert details["order_accepted"] == "true" and details["flipped"] == "false"


async def test_the_flat_case_never_exceeds_the_notional_cap(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, FLAT, cap="1")
    record = case(document, FLAT)
    assert record["status"] == dp.ERROR and "order bound" in record["reason"]
    assert nothing_sent(port)


async def test_a_failing_flat_case_still_runs_the_cleanup(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call("new_market_order", 0, RuntimeError("boom"))
    document, code = await run_cases(tmp_path, port, FLAT)
    record = case(document, FLAT)
    assert record["status"] == dp.ERROR
    assert record["cleanup"]["status"] == dp.CLEANUP_FLAT
    assert code == dp.EXIT_FAILED


# --------------------------------------------------------------------------- #
# reduce_only_market_larger_than_position (A8).
# --------------------------------------------------------------------------- #


async def test_an_oversize_reduce_only_is_sized_half_then_full_and_a_clip_is_recorded(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, code = await run_cases(tmp_path, port, OVERSIZE)
    record = case(document, OVERSIZE)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    (entry,) = sent(port, "new_limit_order")
    assert entry["quantity"] == Decimal("0.001") and entry["reduce_only"] is None
    assert entry["price"] == Decimal("61500.00")
    market = sent(port, "new_market_order")[0]
    assert market["quantity"] == APPROVED and market["reduce_only"] is True
    assert market["side"] == "SELL"
    details = record["details"]
    assert details["half_quantity"] == "0.001"
    assert details["held_before"] == "0.001"
    assert details["oversize_quantity"] == "0.002"
    assert details["order_accepted"] == "true"
    assert details["position_after"] == "0"
    assert details["outcome"] == "clipped_to_position"
    assert_orders_within_caps(port)


async def test_a_rejected_oversize_reduce_only_records_the_code_and_flattens_the_rest(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script_call("new_market_order", 0, REDUCE_ONLY_REJECTED)
    document, _ = await run_cases(tmp_path, port, OVERSIZE)
    record = case(document, OVERSIZE)
    assert record["status"] == dp.OBSERVED
    details = record["details"]
    assert details["order_accepted"] == "false"
    assert details["order_error_code"] == "-2022"
    assert details["outcome"] == "rejected"
    assert details["position_after"] == "0.001"
    flatten = sent(port, "new_market_order")[1]
    assert (flatten["side"], flatten["quantity"], flatten["reduce_only"]) == (
        "SELL",
        Decimal("0.001"),
        True,
    )
    assert port.positions_rows == []


class _OversizeFlipPort(FakeProbePort):
    async def new_market_order(self, **kwargs: Any) -> Any:
        if self.count("new_market_order") == 0:
            self.calls.append(("new_market_order", dict(kwargs)))
            held = sum((amount for _, amount in self.positions_rows), Decimal(0))
            self.positions_rows = [("BOTH", held - Decimal(kwargs["quantity"]))]
            return ok_observation(
                "new_market_order",
                {
                    "client_order_id": kwargs["client_order_id"],
                    "status": "FILLED",
                    "executed_qty": "0.002",
                },
            )
        return await super().new_market_order(**kwargs)


async def test_a_flip_by_the_oversize_reduce_only_is_recorded_and_flattened(
    tmp_path: Path,
) -> None:
    port = _OversizeFlipPort()
    document, _ = await run_cases(tmp_path, port, OVERSIZE)
    record = case(document, OVERSIZE)
    details = record["details"]
    assert record["status"] == dp.OBSERVED
    assert details["outcome"] == "flipped"
    assert details["position_after"] == "-0.001"
    assert details["order_executed_qty"] == "0.002"
    flatten = sent(port, "new_market_order")[1]
    assert (flatten["side"], flatten["quantity"]) == ("BUY", Decimal("0.001"))
    assert port.positions_rows == []


async def test_a_half_quantity_below_the_minimum_is_not_observed_with_the_reason(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(
        tmp_path, port, OVERSIZE, replace=(('quantity = "0.002"', 'quantity = "0.001"'),)
    )
    record = case(document, OVERSIZE)
    assert record["status"] == dp.NOT_OBSERVED
    assert "half" in record["reason"] and "minimum quantity" in record["reason"]
    assert nothing_sent(port)


async def test_an_oversize_entry_that_is_rejected_or_does_not_fill_is_not_observed(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script_call("new_limit_order", 0, MIN_NOTIONAL_REJECTED)
    document, _ = await run_cases(sub(tmp_path, "a"), port, OVERSIZE)
    record = case(document, OVERSIZE)
    assert record["status"] == dp.NOT_OBSERVED and "entry rejected" in record["reason"]
    assert "-4164" in record["reason"]
    unfilled = FakeProbePort()
    unfilled.fill_marketable = False
    other = sub(tmp_path, "b")
    document2, _ = await run_cases(other, unfilled, OVERSIZE)
    record2 = case(document2, OVERSIZE)
    assert record2["status"] == dp.NOT_OBSERVED and "did not fill" in record2["reason"]
    assert sent(unfilled, "new_market_order") == []  # nothing held, so nothing was reduced


async def test_the_oversize_case_never_exceeds_the_cap_and_checks_before_the_entry(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, OVERSIZE, cap="100")  # 0.002 x 61500 = 123
    record = case(document, OVERSIZE)
    assert record["status"] == dp.ERROR and "order bound" in record["reason"]
    assert nothing_sent(port)  # refused before the half entry too


# --------------------------------------------------------------------------- #
# non_reduce_only_below_min_notional (-4164).
# --------------------------------------------------------------------------- #


async def test_the_below_min_notional_order_is_computed_from_the_filters_and_the_code_recorded(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script_call("new_limit_order", 0, MIN_NOTIONAL_REJECTED)
    document, code = await run_cases(tmp_path, port, MIN_NOTIONAL)
    record = case(document, MIN_NOTIONAL)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    (order,) = sent(port, "new_limit_order")
    assert order["side"] == "BUY" and order["reduce_only"] is None
    assert order["price"] == Decimal("48000.00") and order["quantity"] == Decimal("0.002")
    assert order["quantity"] * order["price"] < Decimal("100")
    details = record["details"]
    assert details["min_notional_used"] == "100"
    assert Decimal(details["computed_notional"]) == Decimal("96")
    assert details["order_accepted"] == "false"
    assert details["order_error_code"] == "-4164"
    assert details["order_error_message"].startswith("FAKE Order's notional")
    assert sent(port, "cancel_order") == []  # a rejected order is not cancelled
    assert_orders_within_caps(port)


async def test_an_accepted_below_min_notional_order_is_cancelled_at_once(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, MIN_NOTIONAL)
    record = case(document, MIN_NOTIONAL)
    assert record["status"] == dp.OBSERVED
    assert record["details"]["order_accepted"] == "true"
    (placed,) = sent(port, "new_limit_order")
    (cancel,) = sent(port, "cancel_order")
    assert cancel["client_order_id"] == placed["client_order_id"]
    assert port.open_order_ids == []


def _filters(**changes: str) -> Any:
    summary = dict(fake_symbol_filters("BTCUSDT").summary)
    summary.update(changes)
    return ok_observation("symbol_filters", summary)


async def test_the_quantity_is_floored_to_the_step_and_never_above_the_approved_one(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script_call("symbol_filters", 1, _filters(min_notional="1000000"))
    document, _ = await run_cases(tmp_path, port, MIN_NOTIONAL)
    (order,) = sent(port, "new_limit_order")
    assert order["quantity"] == APPROVED  # the computed bound is huge, the approved cap wins
    port2 = FakeProbePort()
    port2.script_call("symbol_filters", 1, _filters(min_notional="50"))
    other = sub(tmp_path, "small")
    await run_cases(other, port2, MIN_NOTIONAL)
    (small,) = sent(port2, "new_limit_order")
    assert small["quantity"] == Decimal("0.001")  # 50 / 48000 = 0.00104 -> floor step 0.001
    assert small["quantity"] * small["price"] < Decimal("50")


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"min_notional": ""}, "MIN_NOTIONAL"),
        ({"min_quantity": "0.005"}, "minimum quantity"),
        ({"min_notional": "10"}, "minimum quantity"),  # 10 / 48000 = 0.0002 -> below one step
    ],
)
async def test_unusable_filters_are_not_observed_with_the_reason(
    tmp_path: Path, changes: dict[str, str], reason: str
) -> None:
    port = FakeProbePort()
    summary = dict(fake_symbol_filters("BTCUSDT").summary)
    for key, value in changes.items():
        if value == "":
            summary.pop(key)
        else:
            summary[key] = value
    port.script_call("symbol_filters", 1, ok_observation("symbol_filters", summary))
    document, _ = await run_cases(tmp_path, port, MIN_NOTIONAL)
    record = case(document, MIN_NOTIONAL)
    assert record["status"] == dp.NOT_OBSERVED and reason in record["reason"]
    assert nothing_sent(port)


async def test_the_below_min_notional_case_obeys_the_cap(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, MIN_NOTIONAL, cap="50")  # 96 > 50
    record = case(document, MIN_NOTIONAL)
    assert record["status"] == dp.NOT_OBSERVED and "cap" in record["reason"]
    assert nothing_sent(port)


# --------------------------------------------------------------------------- #
# insufficient_margin_order (-2019): the one case with its own owner quantity.
# --------------------------------------------------------------------------- #

MARGIN_QTY = Decimal(TEST_ONLY_MARGIN_QUANTITY)


async def test_the_margin_order_sends_the_owner_quantity_far_below_the_mark_and_records_the_code(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script_call("new_limit_order", 0, MARGIN_REJECTED)
    document, code = await run_cases(tmp_path, port, MARGIN)
    record = case(document, MARGIN)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    (order,) = sent(port, "new_limit_order")
    assert order["quantity"] == MARGIN_QTY and order["side"] == "BUY"
    assert order["price"] == Decimal("48000.00") and order["price"] < port.mark
    assert order["reduce_only"] is None and order["time_in_force"] == "GTC"
    assert order["symbol"] == "BTCUSDT" and order["position_side"] == "BOTH"
    assert order["quantity"] * order["price"] > CAP  # the cap of the other cases is not applied
    details = record["details"]
    assert details["order_accepted"] == "false"
    assert details["order_error_code"] == "-2019"
    assert details["order_error_class"] == "BAD_REQUEST"
    assert details["order_error_category"] == "REJECTED_DEFINITIVE"
    assert details["order_error_message"] == "FAKE Margin is insufficient."
    assert details["available_balance_before"] == "5000.00000000"
    assert details["leverage"] == "20"
    assert Decimal(details["implied_notional"]) == Decimal("240000")
    assert Decimal(details["implied_initial_margin"]) == Decimal("12000")
    assert details["implied_margin_exceeds_available"] == "true"
    assert sent(port, "cancel_order") == []
    assert record["cleanup"]["status"] == dp.CLEANUP_FLAT


async def test_an_accepted_margin_order_is_cancelled_with_the_margin_before_and_after(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, MARGIN)
    record = case(document, MARGIN)
    assert record["status"] == dp.NOT_OBSERVED
    assert "-2019" in record["reason"] and "accepted" in record["reason"]
    details = record["details"]
    assert details["order_accepted"] == "true"
    assert "available_balance_before" in details and "available_balance_after" in details
    (placed,) = sent(port, "new_limit_order")
    (cancel,) = sent(port, "cancel_order")
    assert cancel["client_order_id"] == placed["client_order_id"]
    assert port.open_order_ids == []


class _FillingMarginPort(FakeProbePort):
    """FAKE: the margin order fills (it should not) and leaves a long position."""

    async def new_limit_order(self, **kwargs: Any) -> Any:
        answer = await super().new_limit_order(**kwargs)
        self.positions_rows = [("BOTH", Decimal(kwargs["quantity"]))]
        return answer


async def test_a_margin_order_that_somehow_fills_is_flattened_by_the_cleanup(
    tmp_path: Path,
) -> None:
    port = _FillingMarginPort()
    document, _ = await run_cases(tmp_path, port, MARGIN)
    record = case(document, MARGIN)
    assert record["details"]["position_after"] == "5"
    assert port.positions_rows == []
    assert record["cleanup"]["status"] == dp.CLEANUP_FLAT
    flatten = sent(port, "new_market_order")[-1]
    assert (flatten["side"], flatten["quantity"], flatten["reduce_only"]) == (
        "SELL",
        MARGIN_QTY,
        True,
    )


async def test_the_margin_case_needs_a_flat_account_first(tmp_path: Path) -> None:
    port = FakeProbePort()
    row = {"symbol": "BTCUSDT", "position_side": "BOTH", "position_amt": "0.001"}
    port.script_call(
        "positions",
        1,
        ok_observation("positions", {"count": "1", **{f"row_0_{k}": v for k, v in row.items()}}),
    )
    document, _ = await run_cases(tmp_path, port, MARGIN)
    record = case(document, MARGIN)
    assert record["status"] == dp.NOT_OBSERVED and "not flat" in record["reason"]
    assert nothing_sent(port)


@pytest.mark.parametrize(
    ("margin_quantity", "reason"),
    [
        ("5.0005", "step"),
        ("0.0005", "minimum quantity"),
        ("2000", "maximum quantity"),
    ],
)
async def test_a_margin_quantity_the_exchange_would_reject_for_another_reason_is_not_sent(
    tmp_path: Path, margin_quantity: str, reason: str
) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(
        tmp_path,
        port,
        MARGIN,
        replace=(
            (
                f'insufficient_margin_quantity = "{TEST_ONLY_MARGIN_QUANTITY}"',
                f'insufficient_margin_quantity = "{margin_quantity}"',
            ),
        ),
    )
    record = case(document, MARGIN)
    assert record["status"] == dp.NOT_OBSERVED and reason in record["reason"]
    assert nothing_sent(port)


async def test_the_margin_case_ignores_the_notional_cap_and_nothing_else_does(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script_call("new_limit_order", 0, MARGIN_REJECTED)
    document, _ = await run_cases(tmp_path, port, MARGIN, cap="1")
    assert case(document, MARGIN)["status"] == dp.OBSERVED  # cap 1 does not matter here
    for case_id in (FLAT, OVERSIZE, MIN_NOTIONAL, STOP_REJECT, TRIGGER_RACE):
        other_port = FakeProbePort()
        folder = sub(tmp_path, f"cap-{case_id}")
        other, _ = await run_cases(folder, other_port, case_id, cap="1")
        record = case(other, case_id)
        assert record["status"] in (dp.ERROR, dp.NOT_OBSERVED), case_id
        assert nothing_sent(other_port), case_id
        assert_orders_within_caps(other_port)


def test_the_shared_bound_still_refuses_the_margin_quantity_and_any_notional_above_the_cap(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, case_ids=(MARGIN,), execute=False)
    limits = config.order_limits
    assert limits.insufficient_margin_quantity == MARGIN_QTY
    refusal = dp.order_bound_refusal(limits, quantity=MARGIN_QTY, price=Decimal("48000"))
    assert refusal is not None and "approved quantity" in refusal
    cap_refusal = dp.order_bound_refusal(limits, quantity=APPROVED, price=Decimal("80000"))
    assert cap_refusal is not None and "cap" in cap_refusal


def test_only_the_margin_handler_uses_the_uncapped_path() -> None:
    source = Path(dp.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    callers: dict[str, set[str]] = {}
    for function in [
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
    ]:
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                callers.setdefault(node.func.attr, set()).add(function.name)
    assert callers["margin_limit"] == {"_insufficient_margin_order"}
    handler = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_insufficient_margin_order"
    )
    names = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
    }
    assert not names & {
        "check_bounds",
        "limit",
        "order_bound_refusal",
        "market_close",
        "gtd_limit",
        "conditional",
    }
    assert "cap" in inspect.getsource(dp._WriteCase.margin_limit).lower()


# --------------------------------------------------------------------------- #
# stop_rejected_after_acceptance (P5 remainder, ALGO_UPDATE.o.rm).
# --------------------------------------------------------------------------- #


def _reject_frame(
    port: FakeProbePort, status: str = "REJECTED", rm: str = "FAKE reduce only"
) -> None:
    leg = port.open_algo_ids[-1]
    port.emit_frame(
        {"event_type": "AlgoUpdateEvent", "client_algo_id": leg, "algo_status": status},
        raw={
            "e": "ALGO_UPDATE",
            "E": 1,
            "T": 2,
            "o": {"caid": leg, "X": status, "rm": rm, "ia": "", "ai": "", "aq": "0"},
        },
    )


async def test_an_oversize_stop_is_placed_against_a_half_position_and_the_frames_are_watched(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.on_wait.append(lambda: _reject_frame(port))
    document, code = await run_cases(tmp_path, port, STOP_REJECT, stream=True)
    record = case(document, STOP_REJECT)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    (entry,) = sent(port, "new_limit_order")
    assert entry["quantity"] == Decimal("0.001")
    (stop,) = sent(port, "new_conditional_order")
    assert stop["quantity"] == APPROVED and stop["reduce_only"] is True
    assert stop["close_position"] is None and stop["side"] == "SELL"
    assert stop["order_type"] == "STOP_MARKET" and stop["trigger_price"] == NEAR_STOP
    details = record["details"]
    assert details["placement_accepted"] == "true"
    assert details["stop_statuses_frames"] == "REJECTED"
    assert details["stop_rm"] == "FAKE reduce only"
    assert "REJECTED|" in details["stop_algo_update_sequence"]
    assert record["cleanup"]["status"] == dp.CLEANUP_FLAT
    assert_orders_within_caps(port)


async def test_a_rejected_stop_placement_is_the_answer(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call(
        "new_conditional_order",
        0,
        error_observation(
            "new_conditional_order",
            code=-2022,
            category="REJECTED_DEFINITIVE",
            message="FAKE ReduceOnly Order is rejected.",
        ),
    )
    vt = VirtualTime()
    document, _ = await run_cases(tmp_path, port, STOP_REJECT, vt=vt)
    record = case(document, STOP_REJECT)
    assert record["status"] == dp.OBSERVED
    assert record["details"]["placement_accepted"] == "false"
    assert record["details"]["stop_leg_error_code"] == "-2022"
    assert sent(port, "cancel_algo_order") == []
    assert TEST_ONLY_CASE_TIMEOUT_SECONDS not in vt.sleeps  # a rejection is never waited on


async def test_an_accepted_stop_that_shows_nothing_is_not_observed_and_cancelled(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    vt = VirtualTime()
    document, _ = await run_cases(tmp_path, port, STOP_REJECT, vt=vt)
    record = case(document, STOP_REJECT)
    assert record["status"] == dp.NOT_OBSERVED
    assert "no ALGO_UPDATE" in record["reason"] or "beyond" in record["reason"]
    assert record["details"]["placement_accepted"] == "true"
    assert len(sent(port, "cancel_algo_order")) >= 1
    assert TEST_ONLY_CASE_TIMEOUT_SECONDS in vt.sleeps


async def test_a_half_quantity_below_the_minimum_stops_the_stop_case(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(
        tmp_path, port, STOP_REJECT, replace=(('quantity = "0.002"', 'quantity = "0.001"'),)
    )
    record = case(document, STOP_REJECT)
    assert record["status"] == dp.NOT_OBSERVED and "minimum quantity" in record["reason"]
    assert nothing_sent(port)


async def test_the_stop_case_obeys_the_cap_before_any_order(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, STOP_REJECT, cap="100")
    assert case(document, STOP_REJECT)["status"] == dp.ERROR
    assert nothing_sent(port)


# --------------------------------------------------------------------------- #
# trigger_cancel_race (P7 trigger part): best effort, not a deterministic race.
# --------------------------------------------------------------------------- #


async def test_the_trigger_race_places_and_cancels_a_close_position_stop_per_repeat(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, code = await run_cases(tmp_path, port, TRIGGER_RACE)
    record = case(document, TRIGGER_RACE)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    stops = sent(port, "new_conditional_order")
    assert len(stops) == TEST_ONLY_RACE_REPEATS
    for stop in stops:
        assert stop["close_position"] is True and stop["quantity"] is None
        assert stop["order_type"] == "STOP_MARKET" and stop["side"] == "SELL"
        assert stop["trigger_price"] == NEAR_STOP
    assert len(sent(port, "cancel_algo_order")) == TEST_ONLY_RACE_REPEATS
    assert len(sent(port, "new_limit_order")) == 1  # the position stayed open: one entry
    details = record["details"]
    assert "not a deterministic race" in details["note"]
    assert details["repeats_completed"] == str(TEST_ONLY_RACE_REPEATS)
    for number in range(1, TEST_ONLY_RACE_REPEATS + 1):
        assert details[f"r{number}_placement_accepted"] == "true"
        assert details[f"r{number}_cancel_code"] == "accepted"
        assert details[f"r{number}_final_algo_status"] == "CANCELED"
        assert details[f"r{number}_triggered"] == "false"
        assert details[f"r{number}_position_closed"] == "false"
    assert details["outcome_triggered"] == "0"
    assert record["cleanup"]["status"] == dp.CLEANUP_FLAT
    assert_orders_within_caps(port)


class _TriggeringPort(FakeProbePort):
    """FAKE: the first stop triggers while its cancel is in flight (cancel -2011, flat)."""

    async def cancel_algo_order(self, *, client_algo_id: str) -> Any:
        if self.count("cancel_algo_order") == 0:
            self.calls.append(("cancel_algo_order", {"client_algo_id": client_algo_id}))
            self.trigger_algo(client_algo_id)
            return error_observation("cancel_algo_order", code=-2011, category="ORDER_ABSENT")
        return await super().cancel_algo_order(client_algo_id=client_algo_id)


async def test_a_stop_that_triggers_during_the_cancel_is_recorded_and_the_position_reopened(
    tmp_path: Path,
) -> None:
    port = _TriggeringPort()
    document, _ = await run_cases(tmp_path, port, TRIGGER_RACE)
    record = case(document, TRIGGER_RACE)
    details = record["details"]
    assert record["status"] == dp.OBSERVED
    assert details["r1_cancel_code"] == "-2011"
    assert details["r1_final_algo_status"] == "FINISHED"
    assert details["r1_triggered"] == "true"
    assert details["r1_position_closed"] == "true"
    assert details["r2_triggered"] == "false"
    assert details["outcome_triggered"] == "1"
    assert len(sent(port, "new_limit_order")) == 2  # reopened once for repeat 2
    assert_orders_within_caps(port)


async def test_rejected_stop_placements_are_counted_and_no_repeat_completes(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    for index in range(TEST_ONLY_RACE_REPEATS):
        port.script_call(
            "new_conditional_order",
            index,
            error_observation("new_conditional_order", code=-2021, category="REJECTED_DEFINITIVE"),
        )
    document, _ = await run_cases(tmp_path, port, TRIGGER_RACE)
    record = case(document, TRIGGER_RACE)
    assert record["status"] == dp.NOT_OBSERVED and "no stop" in record["reason"]
    assert record["details"]["r1_placement_accepted"] == "false"
    assert record["details"]["r1_placement_error_code"] == "-2021"
    assert sent(port, "cancel_algo_order") == []


async def test_an_entry_that_does_not_fill_stops_the_trigger_race(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.fill_marketable = False
    document, _ = await run_cases(tmp_path, port, TRIGGER_RACE)
    record = case(document, TRIGGER_RACE)
    assert record["status"] == dp.NOT_OBSERVED
    assert sent(port, "new_conditional_order") == []


async def test_the_trigger_race_obeys_the_cap_before_any_order(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, TRIGGER_RACE, cap="100")
    assert case(document, TRIGGER_RACE)["status"] == dp.ERROR
    assert nothing_sent(port)


# --------------------------------------------------------------------------- #
# timestamp_outside_recv_window (-1021).
# --------------------------------------------------------------------------- #


async def test_the_stale_read_uses_twice_the_window_behind_the_exchange_time(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.server_time_ms = START_MS + 3_000  # the exchange runs 3 s ahead of the tool
    document, code = await run_cases(tmp_path, port, RECV)
    record = case(document, RECV)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    (call,) = sent(port, "stale_timestamp_read")
    assert call["recv_window_ms"] == 5000
    # behind the local clock by 2 x window + (local - server) = 10000 - 3000
    assert call["timestamp_behind_ms"] == 7_000
    details = record["details"]
    assert details["recv_window_ms"] == "5000"
    assert details["server_time_ms"] == str(port.server_time_ms)
    assert details["local_clock_before_utc"] == TEST_ONLY_VIRTUAL_START.isoformat()
    assert details["local_clock_after_utc"] == TEST_ONLY_VIRTUAL_START.isoformat()
    assert details["local_minus_server_ms"] == "-3000"
    assert details["timestamp_behind_server_ms_target"] == "10000"
    assert details["accepted"] == "false"
    assert details["error_code"] == "-1021"
    assert details["error_class"] == "BAD_REQUEST"
    assert details["error_category"] == "CLOCK_SKEW"
    assert details["error_message"].startswith("FAKE Timestamp")
    assert "timestamp_sent_ms" in details and details["clock_calls"] == "1"
    assert nothing_sent(port)


async def test_an_accepted_stale_read_is_still_an_answer(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call(
        "stale_timestamp_read",
        0,
        ok_observation(
            "stale_timestamp_read", {"count": "0", "clock_calls": "1", "timestamp_sent_ms": "1"}
        ),
    )
    document, _ = await run_cases(tmp_path, port, RECV)
    record = case(document, RECV)
    assert record["status"] == dp.OBSERVED and record["details"]["accepted"] == "true"


async def test_a_stale_clock_the_sdk_did_not_honour_is_not_observed(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call(
        "stale_timestamp_read",
        0,
        ok_observation("stale_timestamp_read", {"count": "0", "clock_calls": "0"}),
    )
    document, _ = await run_cases(tmp_path, port, RECV)
    record = case(document, RECV)
    assert record["status"] == dp.NOT_OBSERVED and "stale clock" in record["reason"]


async def test_an_unreadable_server_time_sends_no_stale_read(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call(
        "server_time",
        0,
        error_observation("server_time", code=None, category="UNKNOWN_EXCHANGE_ERROR"),
    )
    document, _ = await run_cases(tmp_path, port, RECV)
    record = case(document, RECV)
    assert record["status"] == dp.NOT_OBSERVED and "server time" in record["reason"]
    assert sent(port, "stale_timestamp_read") == []


async def test_a_clock_far_ahead_of_the_tool_makes_the_offset_unusable(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.server_time_ms = START_MS + 20_000  # the offset (-20 s) swallows the 10 s target
    document, _ = await run_cases(tmp_path, port, RECV)
    record = case(document, RECV)
    assert record["status"] == dp.NOT_OBSERVED and "offset" in record["reason"]
    assert sent(port, "stale_timestamp_read") == []


async def test_the_stale_read_runs_in_hedge_mode_too(tmp_path: Path) -> None:
    port = FakeProbePort(dual_side=True)
    port.server_time_ms = START_MS
    document, _ = await run_cases(tmp_path, port, RECV)
    assert case(document, RECV)["status"] == dp.OBSERVED


# --------------------------------------------------------------------------- #
# income_history_read.
# --------------------------------------------------------------------------- #

INCOME_ROWS = [
    {
        "symbol": "BTCUSDT",
        "income_type": "COMMISSION",
        "income": "-0.05",
        "asset": "USDT",
        "time_ms": str(START_MS + 1000),
        "trade_id": "11",
        "info": "11",
    },
    {
        "symbol": "BTCUSDT",
        "income_type": "COMMISSION",
        "income": "-0.07",
        "asset": "USDT",
        "time_ms": str(START_MS + 2000),
        "trade_id": "12",
    },
    {
        "symbol": "BTCUSDT",
        "income_type": "REALIZED_PNL",
        "income": "0.30",
        "asset": "USDT",
        "time_ms": str(START_MS + 3000),
        "trade_id": "12",
    },
    {
        "symbol": "BTCUSDT",
        "income_type": "FUNDING_FEE",
        "income": "0.01",
        "asset": "USDT",
        "time_ms": str(START_MS + 4000),
    },
]


async def test_the_income_history_records_the_row_types_the_fields_and_the_window(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.income_rows = list(INCOME_ROWS)
    port.server_time_ms = START_MS + 2_000  # the exchange runs 2 s ahead
    document, code = await run_cases(tmp_path, port, INCOME)
    record = case(document, INCOME)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    (call,) = sent(port, "income_history")
    # the window starts at the run start on the EXCHANGE clock: local - (local - server)
    assert call["start_time_ms"] == START_MS + 2_000
    details = record["details"]
    assert details["row_count"] == "4"
    assert details["row_types"] == "COMMISSION,FUNDING_FEE,REALIZED_PNL"
    assert details["row_count_COMMISSION"] == "2"
    assert details["row_count_REALIZED_PNL"] == "1"
    assert details["row_count_FUNDING_FEE"] == "1"
    assert "income_type" in details["row_fields"] and "trade_id" in details["row_fields"]
    assert Decimal(details["derived_sum_COMMISSION_USDT"]) == Decimal("-0.12")
    assert Decimal(details["derived_sum_REALIZED_PNL_USDT"]) == Decimal("0.30")
    assert details["first_row_time_ms"] == str(START_MS + 1000)
    assert details["last_row_time_ms"] == str(START_MS + 4000)
    assert details["window_start_ms"] == str(START_MS + 2_000)
    assert details["local_minus_server_ms"] == "-2000"
    assert nothing_sent(port)


async def test_an_empty_income_window_is_not_observed_with_the_reason(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, INCOME)
    record = case(document, INCOME)
    assert record["status"] == dp.NOT_OBSERVED and "no income row" in record["reason"]
    assert record["details"]["row_count"] == "0"


async def test_a_failed_income_read_is_not_observed_with_the_code(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call(
        "income_history",
        0,
        error_observation("income_history", code=-1021, category="CLOCK_SKEW"),
    )
    document, _ = await run_cases(tmp_path, port, INCOME)
    record = case(document, INCOME)
    assert record["status"] == dp.NOT_OBSERVED and "-1021" in record["reason"]


async def test_the_income_window_falls_back_to_the_local_start_without_a_server_time(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.income_rows = list(INCOME_ROWS)
    port.script_call(
        "server_time",
        0,
        error_observation("server_time", code=None, category="UNKNOWN_EXCHANGE_ERROR"),
    )
    document, _ = await run_cases(tmp_path, port, INCOME)
    record = case(document, INCOME)
    assert record["status"] == dp.OBSERVED
    (call,) = sent(port, "income_history")
    assert call["start_time_ms"] == START_MS
    assert "server time unreadable" in record["details"]["window_note"]


# --------------------------------------------------------------------------- #
# The session: every new case together, run order, cleanup.
# --------------------------------------------------------------------------- #


async def test_all_eight_cases_in_one_run_end_flat_and_stay_within_the_caps(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.server_time_ms = START_MS
    port.income_rows = list(INCOME_ROWS)
    port.script("new_limit_order")  # nothing scripted: the FAKE defaults answer
    document, code = await run_cases(tmp_path, port, *NEW_CASES)
    assert [item["case_id"] for item in document["cases"]] == list(NEW_CASES)
    assert not errors(document)
    assert code == dp.EXIT_OK
    assert document["cleanup"]["final"]["status"] == dp.CLEANUP_FLAT
    assert port.positions_rows == [] and port.open_order_ids == [] and port.open_algo_ids == []
    assert_orders_within_caps(port, except_quantity=MARGIN_QTY)
    margin_orders = [
        k for n, k in port.calls if n == "new_limit_order" and k["quantity"] == MARGIN_QTY
    ]
    assert len(margin_orders) == 1


# --------------------------------------------------------------------------- #
# The runbook.
# --------------------------------------------------------------------------- #

RUNBOOK = Path(__file__).resolve().parents[1] / ".planning" / "DEMO-EVIDENCE-PLAN.md"


def _runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _section(text: str, title: str) -> str:
    start = text.index(title)
    match = re.search(r"\n## ", text[start + len(title) :])
    return text[start : start + len(title) + match.start()] if match else text[start:]


def test_the_runbook_lists_every_case_id_in_run_order_in_the_session_section() -> None:
    session = _section(_runbook(), "## One session: all cases")
    positions = [session.index(f"`{case_id}`") for case_id in dp.CASE_ORDER[-9:]]
    assert positions == sorted(positions)
    assert session.count("<OWNER") >= 10


def test_the_runbook_template_carries_every_new_key_and_only_owner_placeholders() -> None:
    session = _section(_runbook(), "## One session: all cases")
    template = re.search(r"```toml\n(.*?)```", session, re.S)
    assert template is not None
    text = template.group(1)
    for key in (
        "reduce_only_flat",
        "reduce_only_oversize",
        "min_notional_entry",
        "insufficient_margin",
        "stop_reject_after_accept",
        "trigger_cancel_race",
        "recv_window_error",
        "income_history",
        "insufficient_margin_quantity",
    ):
        assert re.search(rf"^{key} = ", text, re.M), key
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            value = value.strip()
            if value in ("true", "false"):
                continue
            assert value.startswith('"<OWNER') or value.startswith("<OWNER"), line


def test_the_runbook_has_the_new_case_sections_and_the_not_covered_list() -> None:
    text = _runbook()
    for number, case_id in zip(range(16, 24), NEW_CASES, strict=True):
        assert re.search(rf"^### {number}\. .*{case_id}", text, re.M), (number, case_id)
    covered = _section(text, "## Not covered here")
    assert "-2019" not in covered or "now covered" in covered
    assert "Hedge" in covered and "418" in covered and "429" in covered
    consumers = _section(text, "## Consumers")
    for item in ("A4", "A8", "-4164", "-1021", "-2019", "income"):
        assert item in consumers, item
    assert "if it stops" in text.lower()


def test_the_script_docstring_names_the_task_and_the_cap_exception() -> None:
    doc = Path(dp.__file__).read_text(encoding="utf-8").split('"""')[1]
    assert "261023-sj2" in doc and "margin_order_refusal" in doc
