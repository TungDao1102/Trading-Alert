"""The five owner opt-in cases of quick task 261022-sj1, on fakes and virtual time.

`exchange_info_read_for_close`, `gtd_min_lifetime_boundary`, `partial_fill_attempt`,
`entry_cancel_fill_race` and `stream_loss_during_case` extend the capture framework of quick
task 261021-sj0. Everything runs offline on `FakeProbePort` / `RecordingProbePort` and on
virtual time; nothing sleeps in real time and nothing reaches Binance. The FAKE market is the
one of the sj0 tests: mark 60000.00, tick 0.10, step 0.001, quantity 0.002, notional cap 150,
far_price_fraction 0.80 (a far BUY rests at 48000.00, a marketable BUY is priced at 61500.00);
the FAKE book has its best ask at 60000.10 and its best bid at 59999.90.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from scripts import demo_probe as dp

from tests.probe_fakes import (
    TEST_ONLY_CASE_TIMEOUT_SECONDS,
    TEST_ONLY_RACE_REPEATS,
    FakeProbePort,
    error_observation,
    fake_symbol_filters,
    ok_observation,
)
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START, VirtualTime
from tests.test_demo_probe_capture_cases import (
    case,
    make_config,
    run_cases,
    sent,
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
START_MS = (TEST_ONLY_VIRTUAL_START - EPOCH) // timedelta(milliseconds=1)
GTD_MIN = "gtd_min_lifetime_boundary"
PARTIAL = "partial_fill_attempt"
RACE = "entry_cancel_fill_race"
GAP = "stream_loss_during_case"
INFO = "exchange_info_read_for_close"
NEW_CASES = (INFO, GTD_MIN, PARTIAL, RACE, GAP)
MUTATING_PREFIXES = ("new_", "cancel_")


def case_part(port: FakeProbePort) -> list[str]:
    """The port calls before the runner's first cleanup (what the case itself did)."""
    names = port.names()
    return names[: names.index("cancel_all_open_orders")]


def sub(tmp_path: Path, name: str) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    return directory


def nothing_sent(port: FakeProbePort) -> bool:
    return not [name for name in case_part(port) if name.startswith(MUTATING_PREFIXES)]


# --------------------------------------------------------------------------- #
# Registry, loader wiring, dry run.
# --------------------------------------------------------------------------- #


def test_the_five_cases_are_registered_with_their_own_keys_and_handlers() -> None:
    assert dp.SJ1_CASES == NEW_CASES
    keys = {case_id: key for key, case_id in dp.OPTIONAL_CASES.items()}
    assert [keys[case_id] for case_id in NEW_CASES] == [
        "exchange_info_read",
        "gtd_min_lifetime",
        "partial_fill_attempt",
        "cancel_fill_race",
        "stream_loss",
    ]
    assert set(dp.CASE_HANDLERS) == set(dp.CASE_ORDER)
    assert set(dp.SJ1_CASES) <= set(dp.CASE_ORDER)
    assert not set(dp.SJ1_CASES) & set(dp.CAPTURE_CASES)  # the sj0 ten keep their meaning
    assert dp.CASE_ORDER[-1] == "gtd_entry_expiry_status"  # the case that waits runs last
    assert dp.FIXTURE_CASES == (*dp.CAPTURE_CASES, *dp.SJ1_CASES)


async def test_a_dry_run_with_every_key_on_has_no_error_and_the_five_not_rehearsed(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, case_ids=tuple(dp.OPTIONAL_CASES.values()), execute=False)
    recorder = dp.ProbeRecorder()
    await dp.run_probe(config, dp.build_dry_run_rig(config), recorder)
    document = recorder.document(config)
    by_id = {item["case_id"]: item for item in document["cases"]}
    for case_id in NEW_CASES:
        assert by_id[case_id]["status"] == dp.NOT_REHEARSED, case_id
    assert not [cid for cid, item in by_id.items() if item["status"] == dp.ERROR]
    assert document["schema"] == "demo-probe-evidence/schema-1"
    assert document["settings"]["race_repeats"] == TEST_ONLY_RACE_REPEATS


async def test_the_executed_evidence_records_the_race_repeats_setting(tmp_path: Path) -> None:
    document, _ = await run_cases(tmp_path, FakeProbePort(), INFO)
    assert document["settings"]["race_repeats"] is None  # the key is only set with its case


async def test_a_disabled_new_case_cannot_be_named_by_only(tmp_path: Path) -> None:
    from tests.probe_fakes import write_probe_limits

    limits = write_probe_limits(tmp_path, optional=("exchange_info_read",))
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
                GTD_MIN,
            ]
        )


# --------------------------------------------------------------------------- #
# exchange_info_read_for_close (A10, Q3): a read-only public case.
# --------------------------------------------------------------------------- #


async def test_the_exchange_info_case_records_the_four_filters_and_sends_no_order(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, code = await run_cases(tmp_path, port, INFO)
    record = case(document, INFO)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    details = record["details"]
    assert details["filter_LOT_SIZE_min_qty"] == "0.001"
    assert details["filter_LOT_SIZE_max_qty"] == "1000"
    assert details["filter_LOT_SIZE_step_size"] == "0.001"
    assert details["filter_MARKET_LOT_SIZE_min_qty"] == "0.001"
    assert details["filter_MARKET_LOT_SIZE_max_qty"] == "120"
    assert details["filter_MARKET_LOT_SIZE_step_size"] == "0.001"
    assert details["filter_PRICE_FILTER_tick_size"] == "0.10"
    assert details["filter_MIN_NOTIONAL_notional"] == "100"
    assert details["symbol_status"] == "TRADING"
    assert "price_filter_min_price_max_price" in details  # stated as not exposed by the port
    assert nothing_sent(port)
    assert [obs["operation"] for obs in record["observations"]] == ["symbol_filters"]


async def test_the_exchange_info_case_records_how_long_the_read_took(tmp_path: Path) -> None:
    vt = VirtualTime()

    class _Slow(FakeProbePort):
        async def symbol_filters(self, *, symbol: str) -> Any:
            if self.count("symbol_filters") >= 1:  # not the run-start snapshot read
                await vt.advance(2)
            return await super().symbol_filters(symbol=symbol)

    document, _ = await run_cases(tmp_path, _Slow(), INFO, vt=vt)
    assert case(document, INFO)["details"]["read_elapsed_ms"] == "2000"


async def test_the_exchange_info_case_compares_with_the_run_start_snapshot(
    tmp_path: Path,
) -> None:
    same, _ = await run_cases(sub(tmp_path, "a"), FakeProbePort(), INFO)
    assert case(same, INFO)["details"]["matches_run_start_snapshot"] == "true"
    assert case(same, INFO)["details"]["snapshot_differences"] == "none"
    port = FakeProbePort()
    changed = dict(fake_symbol_filters("BTCUSDT").summary)
    changed["min_notional"] = "250"
    port.script_call("symbol_filters", 1, ok_observation("symbol_filters", changed))
    different, _ = await run_cases(sub(tmp_path, "b"), port, INFO)
    details = case(different, INFO)["details"]
    assert details["matches_run_start_snapshot"] == "false"
    assert details["snapshot_differences"] == "min_notional"
    assert details["filter_MIN_NOTIONAL_notional"] == "250"


async def test_an_unreadable_exchange_info_is_not_observed_with_the_code(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call(
        "symbol_filters",
        1,
        error_observation("symbol_filters", code=None, category="UNKNOWN_EXCHANGE_ERROR"),
    )
    document, _ = await run_cases(tmp_path, port, INFO)
    record = case(document, INFO)
    assert record["status"] == dp.NOT_OBSERVED
    assert "the exchangeInfo read failed" in record["reason"]


async def test_an_unlisted_symbol_is_not_observed(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call(
        "symbol_filters",
        1,
        ok_observation("symbol_filters", {"symbol": "BTCUSDT", "found": "false"}),
    )
    document, _ = await run_cases(tmp_path, port, INFO)
    record = case(document, INFO)
    assert record["status"] == dp.NOT_OBSERVED and "not listed" in record["reason"]


async def test_the_exchange_info_case_runs_in_hedge_mode_too(tmp_path: Path) -> None:
    document, _ = await run_cases(tmp_path, FakeProbePort(dual_side=True), INFO)
    assert case(document, INFO)["status"] == dp.OBSERVED


# --------------------------------------------------------------------------- #
# gtd_min_lifetime_boundary (A1): goodTillDate at server time + 599 s and + 601 s.
# --------------------------------------------------------------------------- #


async def test_the_boundary_case_sends_two_far_gtd_entries_at_599_and_601_seconds(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.server_time_ms = START_MS + 5_123  # the exchange clock runs 5.123 s ahead of the tool
    vt = VirtualTime()
    document, code = await run_cases(tmp_path, port, GTD_MIN, vt=vt)
    record = case(document, GTD_MIN)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    calls = sent(port, "new_gtd_limit_order")
    assert [call["good_till_date_ms"] for call in calls] == [
        port.server_time_ms + 599_000,
        port.server_time_ms + 601_000,
    ]
    for call in calls:
        assert call["price"] == Decimal("48000.00") and call["quantity"] == Decimal("0.002")
        assert call["side"] == "BUY" and call["position_side"] == "BOTH"
        assert "-gtd" in call["client_order_id"]
    assert calls[0]["client_order_id"] != calls[1]["client_order_id"]
    details = record["details"]
    for prefix, margin in (("plus_599s", 599), ("plus_601s", 601)):
        assert details[f"{prefix}_margin_seconds"] == str(margin)
        assert details[f"{prefix}_server_time_ms"] == str(port.server_time_ms)
        assert details[f"{prefix}_local_clock_before_utc"] == TEST_ONLY_VIRTUAL_START.isoformat()
        assert details[f"{prefix}_local_clock_after_utc"] == TEST_ONLY_VIRTUAL_START.isoformat()
        assert details[f"{prefix}_good_till_date_ms"] == str(port.server_time_ms + margin * 1000)
        assert details[f"{prefix}_good_till_date_minus_server_ms"] == str(margin * 1000)
        assert details[f"{prefix}_good_till_date_minus_local_ms"] == str(margin * 1000 + 5_123)
        assert details[f"{prefix}_local_minus_server_ms"] == "-5123"
        assert details[f"{prefix}_accepted"] == "true"
    assert vt.sleeps == []  # the case never waits for expiry (gtd_entry_expiry_status does)


async def test_each_boundary_point_uses_its_own_just_read_server_time(tmp_path: Path) -> None:
    port = FakeProbePort()
    first, second = START_MS + 1_000, START_MS + 1_400
    port.script("server_time", ok_observation("server_time", {"server_time_ms": str(first)}))
    port.script("server_time", ok_observation("server_time", {"server_time_ms": str(second)}))
    await run_cases(tmp_path, port, GTD_MIN)
    calls = sent(port, "new_gtd_limit_order")
    assert [call["good_till_date_ms"] for call in calls] == [first + 599_000, second + 601_000]
    # the server time is read right before each send
    names = case_part(port)
    assert names.index("server_time") < names.index("new_gtd_limit_order")
    reads = [i for i, name in enumerate(names) if name == "server_time"]
    sends = [i for i, name in enumerate(names) if name == "new_gtd_limit_order"]
    assert reads[0] < sends[0] < reads[1] < sends[1]


async def test_an_accepted_order_is_cancelled_at_once_and_a_rejected_one_is_not(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script_call(
        "new_gtd_limit_order",
        0,
        error_observation(
            "new_gtd_limit_order",
            code=-4023,
            category="REJECTED_DEFINITIVE",
            message="FAKE goodTillDate too soon",
        ),
    )
    document, _ = await run_cases(tmp_path, port, GTD_MIN)
    record = case(document, GTD_MIN)
    details = record["details"]
    assert record["status"] == dp.OBSERVED
    assert details["plus_599s_accepted"] == "false"
    assert details["plus_599s_error_code"] == "-4023"
    assert details["plus_599s_error_class"] == "BAD_REQUEST"
    assert details["plus_599s_error_category"] == "REJECTED_DEFINITIVE"
    assert details["plus_599s_error_message"] == "FAKE goodTillDate too soon"
    assert details["plus_601s_accepted"] == "true"
    cancels = sent(port, "cancel_order")
    placed = sent(port, "new_gtd_limit_order")
    assert [call["client_order_id"] for call in cancels] == [placed[1]["client_order_id"]]
    assert details["plus_601s_cancel_accepted"] == "true"
    assert "plus_599s_cancel_accepted" not in details
    assert port.open_order_ids == []


async def test_the_boundary_order_is_never_retried_after_an_ambiguous_answer(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script_call(
        "new_gtd_limit_order",
        0,
        error_observation(
            "new_gtd_limit_order",
            code=None,
            category="UNKNOWN_EXCHANGE_ERROR",
            http_class="NON_SDK",
        ),
    )
    document, _ = await run_cases(tmp_path, port, GTD_MIN)
    details = case(document, GTD_MIN)["details"]
    assert len(sent(port, "new_gtd_limit_order")) == 2  # one per point, none repeated
    assert details["plus_599s_accepted"] == "false"
    assert details["plus_599s_error_code"] == "none"


async def test_an_unreadable_server_time_sends_nothing_for_that_point(tmp_path: Path) -> None:
    port = FakeProbePort()
    bad = error_observation("server_time", code=None, category="UNKNOWN_EXCHANGE_ERROR")
    port.script_call("server_time", 0, bad)
    document, _ = await run_cases(tmp_path, port, GTD_MIN)
    record = case(document, GTD_MIN)
    assert record["status"] == dp.OBSERVED
    assert len(sent(port, "new_gtd_limit_order")) == 1
    assert record["details"]["plus_599s_skipped"].startswith("NOT_OBSERVED: the server time")
    both = FakeProbePort()
    both.script("server_time", bad, bad)
    document, _ = await run_cases(sub(tmp_path, "both"), both, GTD_MIN)
    record = case(document, GTD_MIN)
    assert record["status"] == dp.NOT_OBSERVED and "server time" in record["reason"]
    assert nothing_sent(both)


async def test_the_boundary_case_checks_the_bound_first_and_refuses_hedge_mode(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, GTD_MIN, cap="1")
    record = case(document, GTD_MIN)
    assert record["status"] == dp.ERROR and "order bound" in record["reason"]
    assert nothing_sent(port)
    hedge = FakeProbePort(dual_side=True)
    document, _ = await run_cases(sub(tmp_path, "h"), hedge, GTD_MIN)
    record = case(document, GTD_MIN)
    assert record["status"] == dp.NOT_OBSERVED and record["reason"] == dp.REASON_HEDGE_MODE
    assert nothing_sent(hedge) and "server_time" not in hedge.names()


# --------------------------------------------------------------------------- #
# partial_fill_attempt (P3, A5): one best-effort limit order that crosses the book.
# --------------------------------------------------------------------------- #


async def test_a_complete_fill_is_a_valid_answer_and_is_flattened(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, code = await run_cases(tmp_path, port, PARTIAL)
    record = case(document, PARTIAL)
    assert code == dp.EXIT_OK
    assert record["status"] == dp.NOT_OBSERVED and record["reason"] == "no partial fill produced"
    (order,) = sent(port, "new_limit_order")
    assert order["quantity"] == Decimal("0.002")  # the approved quantity, never more
    assert order["price"] == Decimal("61500.00") and order["side"] == "BUY"
    details = record["details"]
    assert details["approved_quantity"] == "0.002"
    assert Decimal(details["limit_price"]) == Decimal("61500")
    assert details["best_ask"] == "60000.10" and details["best_bid"] == "59999.90"
    assert details["ask_quantity_within_limit_price"] == "10"
    assert details["depth_expects_partial"] == "false"
    assert details["placement_status"] == "FILLED"
    assert details["orig_qty"] == "0.002" and details["executed_qty"] == "0.002"
    assert details["partial_fill_seen"] == "false"
    (close,) = sent(port, "new_market_order")  # flattened by the case itself
    assert close["reduce_only"] is True and close["side"] == "SELL"
    assert close["quantity"] == Decimal("0.002")
    assert port.positions_rows == []


async def test_a_partial_fill_is_observed_the_remainder_cancelled_and_the_position_flattened(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.partial_fill_quantity = Decimal("0.001")
    document, _ = await run_cases(tmp_path, port, PARTIAL)
    record = case(document, PARTIAL)
    assert record["status"] == dp.OBSERVED
    details = record["details"]
    assert details["placement_status"] == "PARTIALLY_FILLED"
    assert details["orig_qty"] == "0.002" and details["executed_qty"] == "0.001"
    assert details["partial_fill_seen"] == "true"
    assert details["partial_seen_in"] == "rest"
    assert len(sent(port, "new_limit_order")) == 1  # one order, never repeated
    assert len(sent(port, "cancel_order")) == 1  # the remainder, once
    (close,) = sent(port, "new_market_order")
    assert close["quantity"] == Decimal("0.001") and close["reduce_only"] is True
    assert port.positions_rows == [] and port.open_order_ids == []


async def test_a_partial_fill_seen_only_in_the_user_data_frames_counts(tmp_path: Path) -> None:
    class _FramePort(FakeProbePort):
        async def new_limit_order(self, **kwargs: Any) -> Any:
            answer = await super().new_limit_order(**kwargs)
            self.emit_frame(
                {
                    "event_type": "OrderUpdateEvent",
                    "client_order_id": kwargs["client_order_id"],
                    "order_status": "PARTIALLY_FILLED",
                    "execution_type": "TRADE",
                }
            )
            return answer

    document, _ = await run_cases(tmp_path, _FramePort(), PARTIAL)
    record = case(document, PARTIAL)
    assert record["status"] == dp.OBSERVED
    assert record["details"]["partial_seen_in"] == "frames"


async def test_a_rejected_limit_order_is_no_partial_fill_and_nothing_follows(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script(
        "new_limit_order",
        error_observation("new_limit_order", code=-4016, category="REJECTED_DEFINITIVE"),
    )
    document, _ = await run_cases(tmp_path, port, PARTIAL)
    record = case(document, PARTIAL)
    assert record["status"] == dp.NOT_OBSERVED and record["reason"] == "no partial fill produced"
    assert record["details"]["placement_accepted"] == "false"
    assert len(sent(port, "new_limit_order")) == 1
    assert sent(port, "cancel_order") == [] and sent(port, "new_market_order") == []


async def test_a_limit_that_cannot_reach_the_best_ask_sends_nothing(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, PARTIAL, cap="110")  # cap / quantity = 55000
    record = case(document, PARTIAL)
    assert record["status"] == dp.NOT_OBSERVED and record["reason"] == "no partial fill produced"
    assert Decimal(record["details"]["limit_price"]) == Decimal("55000")
    assert "best ask" in record["details"]["not_sent"]
    assert nothing_sent(port)


async def test_a_book_too_thin_for_the_quantity_is_recorded_as_expecting_a_partial_fill(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.book_asks = [(Decimal("60000.10"), Decimal("0.001"))]
    document, _ = await run_cases(tmp_path, port, PARTIAL)
    details = case(document, PARTIAL)["details"]
    assert details["ask_quantity_within_limit_price"] == "0.001"
    assert details["depth_expects_partial"] == "true"


async def test_an_unreadable_book_does_not_stop_the_attempt(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "order_book", error_observation("order_book", code=None, category="UNKNOWN_EXCHANGE_ERROR")
    )
    document, _ = await run_cases(tmp_path, port, PARTIAL)
    details = case(document, PARTIAL)["details"]
    assert details["order_book_read"].startswith("rejected")
    assert details["depth_expects_partial"] == "unknown"
    assert len(sent(port, "new_limit_order")) == 1


async def test_the_partial_case_refuses_hedge_mode_and_sends_one_order_at_most(
    tmp_path: Path,
) -> None:
    hedge = FakeProbePort(dual_side=True)
    document, _ = await run_cases(tmp_path, hedge, PARTIAL)
    record = case(document, PARTIAL)
    assert record["status"] == dp.NOT_OBSERVED and record["reason"] == dp.REASON_HEDGE_MODE
    assert nothing_sent(hedge)


# --------------------------------------------------------------------------- #
# entry_cancel_fill_race (P7): place at the touch, cancel at once, owner repeat count.
# --------------------------------------------------------------------------- #


async def test_each_repeat_places_at_the_best_ask_and_cancels_right_away(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, code = await run_cases(tmp_path, port, RACE)
    record = case(document, RACE)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    placed = sent(port, "new_limit_order")
    assert len(placed) == TEST_ONLY_RACE_REPEATS
    assert all(call["price"] == Decimal("60000.10") for call in placed)
    assert all(call["quantity"] == Decimal("0.002") for call in placed)
    assert len({call["client_order_id"] for call in placed}) == TEST_ONLY_RACE_REPEATS
    cancels = sent(port, "cancel_order")
    assert [c["client_order_id"] for c in cancels] == [p["client_order_id"] for p in placed]
    names = case_part(port)
    place_at = [i for i, n in enumerate(names) if n == "new_limit_order"]
    cancel_at = [i for i, n in enumerate(names) if n == "cancel_order"]
    for place, cancel in zip(place_at, cancel_at, strict=True):
        assert cancel == place + 1  # nothing between the placement answer and the cancel
    details = record["details"]
    assert details["race_repeats"] == str(TEST_ONLY_RACE_REPEATS)
    assert details["repeats_completed"] == str(TEST_ONLY_RACE_REPEATS)
    assert "does not reproduce a deterministic race" in details["note"]
    assert "best ask" in details["touch_price_side"]


async def test_a_marketable_touch_records_the_minus_2011_and_the_fill_and_flattens(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, RACE)
    details = case(document, RACE)["details"]
    assert details["r1_place_status"] == "FILLED"
    assert details["r1_cancel_code"] == "-2011"
    assert details["r1_final_status"] == "FILLED"
    assert details["r1_filled"] == "true"
    assert details["r1_outcome"] == "cancel rejected -2011; final FILLED"
    assert details["outcome_cancel_rejected"] == str(TEST_ONLY_RACE_REPEATS)
    assert details["outcome_canceled_in_time"] == "0"
    assert details["outcome_filled"] == str(TEST_ONLY_RACE_REPEATS)
    closes = sent(port, "new_market_order")  # every fill flattened at once, reduce-only
    assert len(closes) == TEST_ONLY_RACE_REPEATS
    assert all(c["reduce_only"] is True and c["quantity"] == Decimal("0.002") for c in closes)
    assert port.positions_rows == []


async def test_a_resting_touch_records_the_cancel_in_time(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.fill_marketable = False
    document, _ = await run_cases(tmp_path, port, RACE)
    details = case(document, RACE)["details"]
    assert details["r1_cancel_code"] == "accepted"
    assert details["r1_final_status"] == "CANCELED"
    assert details["r1_filled"] == "false"
    assert details["r1_outcome"] == "canceled in time; final CANCELED"
    assert details["outcome_canceled_in_time"] == str(TEST_ONLY_RACE_REPEATS)
    assert details["outcome_filled"] == "0"
    assert sent(port, "new_market_order") == []


async def test_a_rejected_placement_stops_the_repeats_and_is_not_retried(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call(
        "new_limit_order",
        1,
        error_observation("new_limit_order", code=-4016, category="REJECTED_DEFINITIVE"),
    )
    document, _ = await run_cases(tmp_path, port, RACE)
    record = case(document, RACE)
    assert record["status"] == dp.OBSERVED
    assert len(sent(port, "new_limit_order")) == 2  # repeat 2 was rejected; no repeat 3
    assert record["details"]["repeats_completed"] == "1"
    assert "placement rejected" in record["details"]["stopped"]
    assert len(sent(port, "cancel_order")) == 1


async def test_a_touch_outside_the_far_price_band_sends_nothing(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.book_asks = [(Decimal("80000.00"), Decimal("5"))]  # far above the 72000.00 band edge
    document, _ = await run_cases(tmp_path, port, RACE)
    record = case(document, RACE)
    assert record["status"] == dp.NOT_OBSERVED
    assert "far_price_fraction" in record["details"]["stopped"]
    assert nothing_sent(port)


async def test_an_unreadable_book_ends_the_race_case_without_an_order(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "order_book", error_observation("order_book", code=None, category="UNKNOWN_EXCHANGE_ERROR")
    )
    document, _ = await run_cases(tmp_path, port, RACE)
    record = case(document, RACE)
    assert record["status"] == dp.NOT_OBSERVED and "no place-and-cancel pair" in record["reason"]
    assert nothing_sent(port)


async def test_the_race_case_checks_the_bound_and_refuses_hedge_mode(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, RACE, cap="1")
    record = case(document, RACE)
    assert record["status"] == dp.ERROR and "order bound" in record["reason"]
    assert nothing_sent(port)
    hedge = FakeProbePort(dual_side=True)
    document, _ = await run_cases(sub(tmp_path, "h"), hedge, RACE)
    assert case(document, RACE)["reason"] == dp.REASON_HEDGE_MODE
    assert nothing_sent(hedge)


# --------------------------------------------------------------------------- #
# stream_loss_during_case (P5): the sj0 stream-gap mechanism around an entry + stop cycle.
# --------------------------------------------------------------------------- #


class GapPort(FakeProbePort):
    """`drop_stream_transport` puts the stream into RECONNECTING; a wait brings it back.

    `recover` False leaves it down; `deliver` False brings it back without the frames the
    exchange produced during the gap (the stream does not replay what it missed).
    """

    def __init__(self, *, recover: bool = True, deliver: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.stream_running = True
        self.recover = recover
        self.deliver = deliver

    async def drop_stream_transport(self) -> bool:
        dropped = await super().drop_stream_transport()
        if dropped:
            self.emit_state("RECONNECTING")
            if self.recover:
                self.on_wait.append(self._come_back)
        return dropped

    def _come_back(self) -> None:
        self.emit_state("LIVE")
        if not self.deliver:
            return
        entry = next((kw["client_order_id"] for n, kw in self.calls if n == "new_limit_order"), "")
        stop = next(
            (kw["client_algo_id"] for n, kw in self.calls if n == "new_conditional_order"), ""
        )
        if not entry or not stop:
            return  # the hook ran at an earlier wait (the entry's own): nothing to deliver yet
        self.emit_frame(
            {
                "event_type": "OrderUpdateEvent",
                "client_order_id": entry,
                "order_status": "FILLED",
                "execution_type": "TRADE",
            }
        )
        self.emit_frame(
            {"event_type": "AlgoUpdateEvent", "client_algo_id": stop, "algo_status": "NEW"}
        )


async def test_the_stream_is_dropped_first_then_one_entry_and_stop_cycle_runs(
    tmp_path: Path,
) -> None:
    port = GapPort()
    vt = VirtualTime()
    document, code = await run_cases(tmp_path, port, GAP, vt=vt, stream=True)
    record = case(document, GAP)
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    names = case_part(port)
    assert names.index("drop_stream_transport") < names.index("new_limit_order")
    (entry,) = sent(port, "new_limit_order")
    assert entry["price"] == Decimal("61500.00") and entry["quantity"] == Decimal("0.002")
    (stop,) = sent(port, "new_conditional_order")
    assert stop["order_type"] == "STOP_MARKET" and stop["side"] == "SELL"
    assert stop["close_position"] is True and stop["quantity"] is None
    assert stop["trigger_price"] == Decimal("48000.00")
    assert vt.sleeps == [TEST_ONLY_CASE_TIMEOUT_SECONDS]  # one wait for the stream to return
    assert len(sent(port, "cancel_algo_order")) == 1  # the stop is cancelled by the case
    details = record["details"]
    assert details["transport_dropped"] == "true"
    assert details["stream_states_at_entry_send"] == "RECONNECTING"
    assert details["rest_entry_status_during_gap"] == "FILLED"
    assert details["rest_stop_status_during_gap"] == "NEW"
    assert details["stream_recovered_live"] == "true"
    assert details["stream_states_after_drop"] == "RECONNECTING,LIVE"
    assert details["entry_fill_frame_delivered"] == "true"
    assert details["stop_frame_delivered"] == "true"
    assert details["frames_after_drop_entry"] == "FILLED/TRADE"
    assert details["frames_after_drop_stop"] == "NEW"
    assert details["comparison_entry"] == "rest=FILLED; stream_after_drop=FILLED/TRADE"
    assert details["comparison_stop"] == "rest=NEW; stream_after_drop=NEW"
    assert "end_position" in details and "end_open_algo_orders" in details


async def test_frames_the_stream_did_not_deliver_after_the_gap_are_recorded_as_missing(
    tmp_path: Path,
) -> None:
    port = GapPort(deliver=False)
    document, _ = await run_cases(tmp_path, port, GAP, stream=True)
    record = case(document, GAP)
    assert record["status"] == dp.OBSERVED
    details = record["details"]
    assert details["entry_fill_frame_delivered"] == "false"
    assert details["stop_frame_delivered"] == "false"
    assert details["frames_after_drop_entry"] == "none"
    assert details["comparison_entry"] == "rest=FILLED; stream_after_drop=none"


async def test_a_stream_that_does_not_come_back_is_not_observed_and_the_stop_is_cancelled(
    tmp_path: Path,
) -> None:
    port = GapPort(recover=False)
    document, _ = await run_cases(tmp_path, port, GAP, stream=True)
    record = case(document, GAP)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == dp.REASON_STREAM_NOT_RECOVERED
    assert record["details"]["stream_recovered_live"] == "false"
    assert len(sent(port, "cancel_algo_order")) == 1


async def test_without_a_running_stream_nothing_is_sent_and_nothing_is_dropped(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, GAP, stream=False)
    record = case(document, GAP)
    assert record["status"] == dp.NOT_OBSERVED and record["reason"] == dp.REASON_NO_STREAM
    assert nothing_sent(port) and "drop_stream_transport" not in port.names()


async def test_a_drop_the_port_cannot_make_sends_no_order(tmp_path: Path) -> None:
    port = FakeProbePort()  # stream_running is False: the drop answers False
    document, _ = await run_cases(tmp_path, port, GAP, stream=True)
    record = case(document, GAP)
    assert record["status"] == dp.NOT_OBSERVED and record["reason"] == dp.REASON_NO_STREAM
    assert record["details"]["transport_dropped"] == "false"
    assert nothing_sent(port)


async def test_an_entry_that_does_not_fill_is_cancelled_and_no_stop_is_sent(
    tmp_path: Path,
) -> None:
    port = GapPort()
    port.fill_marketable = False
    document, _ = await run_cases(tmp_path, port, GAP, stream=True)
    record = case(document, GAP)
    assert record["status"] == dp.NOT_OBSERVED and "did not fill" in record["reason"]
    assert sent(port, "new_conditional_order") == []
    assert len(sent(port, "cancel_order")) == 1
    assert port.open_order_ids == []


async def test_the_stream_loss_case_refuses_hedge_mode_and_checks_the_bound(
    tmp_path: Path,
) -> None:
    hedge = GapPort(dual_side=True)
    document, _ = await run_cases(tmp_path, hedge, GAP, stream=True)
    assert case(document, GAP)["reason"] == dp.REASON_HEDGE_MODE
    assert nothing_sent(hedge) and "drop_stream_transport" not in hedge.names()
    port = GapPort()
    document, _ = await run_cases(sub(tmp_path, "b"), port, GAP, stream=True, cap="1")
    record = case(document, GAP)
    assert record["status"] == dp.ERROR and "order bound" in record["reason"]
    assert nothing_sent(port)


# --------------------------------------------------------------------------- #
# Common rules.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("case_id", NEW_CASES)
async def test_a_new_case_leaves_nothing_open_after_the_runner_cleanup(
    tmp_path: Path, case_id: str
) -> None:
    port = GapPort() if case_id == GAP else FakeProbePort()
    document, _ = await run_cases(tmp_path, port, case_id, stream=case_id == GAP)
    assert document["cleanup"]["final"]["status"] == dp.CLEANUP_FLAT
    assert port.open_order_ids == [] and port.open_algo_ids == []
    assert port.positions_rows == []


@pytest.mark.parametrize("case_id", [INFO, GTD_MIN, PARTIAL, RACE])
async def test_the_short_cases_never_sleep(tmp_path: Path, case_id: str) -> None:
    vt = VirtualTime()
    await run_cases(tmp_path, FakeProbePort(), case_id, vt=vt)
    assert vt.sleeps == []


async def test_the_new_cases_write_scrubbed_rest_fixtures_in_an_executed_run(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, INFO, fixtures=True, stream=True)
    record = case(document, INFO)
    assert record["rest_fixtures"] == [f"{INFO}-rest-001-symbol_filters.json"]
    path = tmp_path / "fixtures" / record["rest_fixtures"][0]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["case_id"] == INFO and saved["label"] == dp.FIXTURE_LABEL_EXECUTE
    assert saved["observation"]["summary"]["min_notional"] == "100"


def test_the_port_and_the_guarded_port_know_the_two_new_reads() -> None:
    assert "server_time" not in dp.MUTATING_OPERATIONS
    assert "order_book" not in dp.MUTATING_OPERATIONS
    for name in ("server_time", "order_book"):
        assert hasattr(dp.GuardedProbePort, name)
        assert name in dp.ProbePort.__dict__


def test_the_script_docstring_and_the_new_handlers_have_no_float_and_no_new_fault_injector() -> (
    None
):
    source = Path(dp.__file__).read_text(encoding="utf-8")
    assert "261022-sj1" in source.split('"""')[1]
    tree = ast.parse(source)
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }
    assert {
        "_exchange_info_read_for_close",
        "_gtd_min_lifetime_boundary",
        "_partial_fill_attempt",
        "_entry_cancel_fill_race",
        "_stream_loss_during_case",
    } <= names
    # the gap uses the existing mechanism only: the port's drop, no socket or network import
    gap = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_stream_loss_during_case"
    )
    called = {
        call.func.attr
        for call in ast.walk(gap)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    }
    assert "drop_stream_transport" in called
    assert not {"connect", "close", "send", "recv", "socket"} & called
    # nothing but the 599 and 601 second points of the boundary case are spelled as numbers
    assert dp.GTD_BOUNDARY_MARGINS_SECONDS == (599, 601)
