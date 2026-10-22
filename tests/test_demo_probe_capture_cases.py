"""The ten owner opt-in evidence-capture cases of quick task 261021-sj0, on fakes.

Everything runs offline on `FakeProbePort` / `RecordingProbePort` and on virtual time
(`tests/support/virtual_time.py`); nothing sleeps in real time and nothing reaches Binance. The
limits are TEST_ONLY values written by `write_probe_limits`. The FAKE market is the one of
`tests/test_demo_probe_cases.py`: mark 60000.00, tick 0.10, step 0.001, quantity 0.002, notional
cap 150, far_price_fraction 0.80 (a far BUY rests at 48000.00, a far up-trigger sits at
72000.00, a marketable BUY is priced at 61500.00).
"""

from __future__ import annotations

import ast
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from scripts import demo_probe as dp
from scripts import user_data_smoke

from tests.probe_fakes import (
    FakeProbePort,
    error_observation,
    ok_observation,
    write_probe_limits,
)
from tests.support.ast_guards import float_constructor_calls
from tests.support.virtual_time import TEST_ONLY_VIRTUAL_START, VirtualTime

CASE_KEYS = {case_id: key for key, case_id in dp.OPTIONAL_CASES.items()}
ABSENT = {"code": -2013, "category": "ORDER_ABSENT"}


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def make_config(
    tmp_path: Path,
    *,
    case_ids: tuple[str, ...] = (),
    execute: bool = True,
    fixtures: bool = False,
    cap: str | None = None,
) -> dp.ProbeConfig:
    """A config enabling the keys of `case_ids`, running only them; `cap` lowers the notional."""
    optional = tuple(CASE_KEYS[case_id] for case_id in case_ids)
    limits = write_probe_limits(tmp_path, optional=optional)
    if cap is not None:
        text = limits.read_text(encoding="utf-8")
        assert 'max_notional_quote = "150"' in text
        limits.write_text(text.replace('"150"', f'"{cap}"'), encoding="utf-8")
    argv = [
        "--environment",
        "DEMO",
        "--probe-limits-file",
        str(limits),
        "--evidence-dir",
        str(tmp_path / "evidence"),
    ]
    if case_ids:
        argv += ["--only", ",".join(case_ids)]
    if fixtures:
        argv += ["--fixtures-dir", str(tmp_path / "fixtures")]
    if execute:
        argv.append("--execute")
    return dp.parse_config(argv)


class _Stream:
    """A stand-in for the user-data stream of an executed run (frames come from the fake)."""

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def scenario_rig(
    port: FakeProbePort, vt: VirtualTime | None = None, *, stream: bool = False
) -> dp.ProbeRig:
    """A rig whose sleep records the duration, runs the port wait hooks and moves time."""
    vt = vt if vt is not None else VirtualTime()

    async def sleep(seconds: int) -> None:
        vt.sleeps.append(seconds)
        port.run_wait_hooks()
        await vt.advance(seconds)

    return dp.ProbeRig(port=port, clock=vt.now, sleep=sleep, stream=_Stream() if stream else None)


async def run_cases(
    tmp_path: Path,
    port: FakeProbePort,
    *case_ids: str,
    vt: VirtualTime | None = None,
    fixtures: bool = False,
    stream: bool = False,
    cap: str | None = None,
) -> tuple[dict[str, Any], int]:
    config = make_config(tmp_path, case_ids=case_ids, fixtures=fixtures, cap=cap)
    recorder = dp.ProbeRecorder()
    rig = scenario_rig(port, vt, stream=stream)
    code = await dp.run_probe(config, rig, recorder)
    return recorder.document(config), code


def case(document: dict[str, Any], case_id: str) -> dict[str, Any]:
    matches = [item for item in document["cases"] if item["case_id"] == case_id]
    assert len(matches) == 1, case_id
    return matches[0]


def sent(port: FakeProbePort, operation: str) -> list[dict[str, Any]]:
    return [kwargs for name, kwargs in port.calls if name == operation]


# --------------------------------------------------------------------------- #
# The tracer: account_capture end to end (loader, registry, port, handler, fixtures).
# --------------------------------------------------------------------------- #

ACCOUNT = "account_read_only_capture"
ACCOUNT_ORDER = [
    "account_information",
    "account_balance_all",
    "account_config",
    "symbol_config",
    "leverage_brackets",
    "position_mode",
]


async def test_the_tracer_account_capture_records_the_six_reads_in_order(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, code = await run_cases(tmp_path, port, ACCOUNT)
    record = case(document, ACCOUNT)
    assert code == dp.EXIT_OK
    assert record["status"] == dp.OBSERVED
    assert [item["operation"] for item in record["observations"]] == ACCOUNT_ORDER
    mutating = {"new_limit_order", "new_market_order", "new_conditional_order", "cancel_order"}
    assert not mutating & {item["operation"] for item in record["observations"]}
    details = record["details"]
    for label in ACCOUNT_ORDER:
        assert details[f"{label}_field_count"].isdigit(), label
        assert details[f"{label}_fields"] != "", label
    assert "assets.*.walletBalance" in details["account_information_fields"]
    assert details["account_balance_all_fields"] == "*.asset,*.availableBalance,*.balance"
    # nothing but reads: the case sent no order before the cleanup
    first_cleanup = port.names().index("cancel_all_open_orders")
    case_part = port.names()[:first_cleanup]
    assert not [name for name in case_part if name.startswith(("new_", "cancel_"))]


async def test_the_tracer_writes_the_rest_fixtures_beside_the_frames_and_lists_them(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, ACCOUNT, fixtures=True, stream=True)
    record = case(document, ACCOUNT)
    directory = tmp_path / "fixtures"
    expected = [
        f"{ACCOUNT}-rest-{index:03d}-{operation}.json"
        for index, operation in enumerate(ACCOUNT_ORDER, start=1)
    ]
    assert record["rest_fixtures"] == expected
    assert sorted(path.name for path in directory.glob(f"{ACCOUNT}-rest-*.json")) == sorted(
        expected
    )
    provenance = (directory / "provenance.md").read_text(encoding="utf-8")
    for name in expected:
        assert f"`{name}`: {dp.FIXTURE_LABEL_EXECUTE}" in provenance
    first = json.loads((directory / expected[0]).read_text(encoding="utf-8"))
    assert first["case_id"] == ACCOUNT and first["index"] == 1
    assert first["label"] == dp.FIXTURE_LABEL_EXECUTE
    assert first["observation"]["operation"] == "account_information"
    assert first["observation"]["summary"]["totalWalletBalance"] == "5000.00000000"
    assert set(expected) <= set(document["fixtures"])


async def test_no_rest_fixture_is_written_without_a_fixtures_dir_or_for_another_case(
    tmp_path: Path,
) -> None:
    document, _ = await run_cases(tmp_path, FakeProbePort(), ACCOUNT)
    assert "rest_fixtures" not in case(document, ACCOUNT)
    assert not (tmp_path / "fixtures").exists()
    other = tmp_path / "other"
    other.mkdir()
    port = FakeProbePort()
    config = make_config(other, execute=True, fixtures=True)  # the required cases only
    recorder = dp.ProbeRecorder()
    await dp.run_probe(config, scenario_rig(port, stream=True), recorder)
    assert not list((other / "fixtures").glob("*-rest-*.json"))


async def test_a_dry_run_writes_no_rest_fixture(tmp_path: Path) -> None:
    config = make_config(tmp_path, case_ids=(ACCOUNT,), execute=False, fixtures=True)
    recorder = dp.ProbeRecorder()
    code = await dp.run_probe(config, dp.build_dry_run_rig(config), recorder)
    assert code == dp.EXIT_OK
    document = recorder.document(config)
    assert case(document, ACCOUNT)["status"] == dp.NOT_REHEARSED
    assert "rest_fixtures" not in case(document, ACCOUNT)
    assert not (tmp_path / "fixtures").exists() or not list((tmp_path / "fixtures").iterdir())


async def test_an_account_read_error_is_data_and_the_case_goes_on(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call(
        "account_config",
        0,
        error_observation("account_config", code=-2015, category="AUTH_OR_SIGNATURE"),
    )
    document, _ = await run_cases(tmp_path, port, ACCOUNT)
    record = case(document, ACCOUNT)
    assert record["status"] == dp.OBSERVED
    assert [item["operation"] for item in record["observations"]] == ACCOUNT_ORDER
    assert "account_config_fields" not in record["details"]
    assert "-2015" in record["details"]["account_config"]
    assert "leverage_brackets_fields" in record["details"]


async def test_a_truncated_flat_answer_is_flagged(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call(
        "account_information",
        0,
        ok_observation("account_information", {"a.0.b": "1", "truncated": "true"}),
    )
    document, _ = await run_cases(tmp_path, port, ACCOUNT)
    assert case(document, ACCOUNT)["details"]["account_information_truncated"] == "true"


async def test_the_capture_case_runs_in_hedge_mode_too(tmp_path: Path) -> None:
    """It sends no order, so the hedge-mode refusal of the order cases does not apply."""
    document, _ = await run_cases(tmp_path, FakeProbePort(dual_side=True), ACCOUNT)
    assert case(document, ACCOUNT)["status"] == dp.OBSERVED


# --------------------------------------------------------------------------- #
# algo_query_timing_after_new (P5, P11: the -2013 right after NEW).
# --------------------------------------------------------------------------- #

TIMING = "algo_query_timing_after_new"


def _absent(operation: str) -> Any:
    return error_observation(operation, **ABSENT)


async def test_timing_records_an_immediate_absent_and_a_waited_new_by_both_ids(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script_call("query_algo_order", 0, _absent("query_algo_order"))
    vt = VirtualTime()
    document, code = await run_cases(tmp_path, port, TIMING, vt=vt)
    record = case(document, TIMING)
    details = record["details"]
    assert code == dp.EXIT_OK and record["status"] == dp.OBSERVED
    # the reduce-only flat leg: -2013 at once, NEW after the one owner wait
    assert "-2013" in details["ro_query1_by_client_id"]
    assert details["ro_query1_by_client_id_elapsed_ms"] == "0"
    assert details["ro_query2_by_client_id"].startswith("accepted")
    assert details["ro_query2_by_client_id_elapsed_ms"] == str(30 * 1000)
    assert details["ro_query1_by_algo_id_elapsed_ms"] == "0"
    assert details["ro_query2_by_algo_id_elapsed_ms"] == str(30 * 1000)
    assert vt.sleeps == [30]  # exactly one wait: the carrier answered NEW at once
    assert details["ro_queries_before_all_ok"] == "2"
    assert details["carrier_queries_before_all_ok"] == "1"
    # the by-algo-id queries use the id of the placement answer
    placed = [obs for obs in record["observations"] if obs["operation"] == "new_conditional_order"]
    ids = [obs["summary"]["algo_id"] for obs in placed]
    assert len(ids) == 2 and ids[0] != ids[1]
    by_id = [int(kwargs["algo_id"]) for kwargs in sent(port, "query_algo_order_by_algo_id")]
    assert by_id[:2] == [int(ids[0])] * 2
    assert details["ro_algo_id"] == ids[0] and details["carrier_algo_id"] == ids[1]
    # listed, cancelled, re-queried both ways
    assert details["ro_listed_in_open_algo_orders"] == "true"
    assert details["ro_cancel"].startswith("accepted")
    assert "ro_after_cancel_by_client_id" in details and "ro_after_cancel_by_algo_id" in details
    assert "carrier_after_cancel_by_algo_id" in details
    assert len(sent(port, "cancel_algo_order")) >= 2


async def test_timing_with_an_answer_at_once_never_waits(tmp_path: Path) -> None:
    vt = VirtualTime()
    document, _ = await run_cases(tmp_path, FakeProbePort(), TIMING, vt=vt)
    details = case(document, TIMING)["details"]
    assert vt.sleeps == []
    assert details["ro_queries_before_all_ok"] == "1"
    assert "ro_query2_by_client_id" not in details


async def test_timing_without_an_algo_id_sends_no_query_by_id_and_is_not_an_error(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    for client_id_tag in ("ro", "carrier"):
        port.script(
            "new_conditional_order",
            ok_observation(
                "new_conditional_order", {"client_algo_id": client_id_tag, "algo_status": "NEW"}
            ),
        )
    document, code = await run_cases(tmp_path, port, TIMING)
    record = case(document, TIMING)
    assert record["status"] == dp.OBSERVED and code == dp.EXIT_OK
    assert sent(port, "query_algo_order_by_algo_id") == []
    assert record["details"]["ro_algo_id"].startswith("NOT_OBSERVED: the placement answer")
    assert record["details"]["carrier_algo_id"].startswith("NOT_OBSERVED")


async def test_timing_skips_a_variant_whose_placement_was_rejected(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "new_conditional_order",
        error_observation("new_conditional_order", code=-4509, category="REJECTED_DEFINITIVE"),
    )
    document, _ = await run_cases(tmp_path, port, TIMING)
    details = case(document, TIMING)["details"]
    assert details["ro_placement_accepted"] == "false"
    assert "ro_query1_by_client_id" not in details
    assert details["carrier_placement_accepted"] == "true"


async def test_timing_is_not_observed_in_hedge_mode_and_sends_nothing(tmp_path: Path) -> None:
    port = FakeProbePort(dual_side=True)
    document, _ = await run_cases(tmp_path, port, TIMING)
    record = case(document, TIMING)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == dp.REASON_HEDGE_MODE
    assert sent(port, "new_conditional_order") == []


async def test_timing_checks_both_legs_against_the_bound_before_the_first_send(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, TIMING, cap="1")
    record = case(document, TIMING)
    assert record["status"] == dp.ERROR and record["reason"].startswith("order bound")
    assert sent(port, "new_conditional_order") == []


def test_the_pure_helpers_read_ids_and_fields() -> None:
    answer = ok_observation("x", {"algo_id": "1000000007", "order_id": "42"})
    assert dp._algo_id_of(answer) == 1000000007
    assert dp._order_id_of(answer) == 42
    assert dp._algo_id_of(ok_observation("x", {"algo_id": "12a"})) is None
    assert dp._algo_id_of(ok_observation("x", {"algo_id": "-5"})) is None
    assert dp._algo_id_of(ok_observation("x", {"algo_id": "0"})) is None
    assert dp._algo_id_of(ok_observation("x", {})) is None
    assert dp._order_id_of(error_observation("x", code=-2013, category="ORDER_ABSENT")) is None
    assert dp._field_set({"assets.0.a": "1", "assets.1.a": "2", "b": "3", "c.10.d.2": "4"}) == (
        "assets.*.a,b,c.*.d.*"
    )
    assert dp._field_set({}) == ""


def test_the_only_new_mutating_operation_is_the_gtd_limit() -> None:
    assert "new_gtd_limit_order" in dp.MUTATING_OPERATIONS


# =========================================================================== #
# Task 2: the seven order-sending capture cases.
# =========================================================================== #

CLOSE_POSITION = "close_position_stop_with_position"
WOULD_TRIGGER = "stop_would_trigger_after_fill"
SAME_ID = "stop_query_absent_then_same_id"
MANUAL_CLOSE = "manual_close_with_open_legs"
COMMISSION = "commission_vs_realized_pnl"
BRACKET = "triggered_close_position_bracket"
TP1 = "tp1_quantity_from_fill"
ORDER_CASES = (
    CLOSE_POSITION,
    WOULD_TRIGGER,
    SAME_ID,
    MANUAL_CLOSE,
    COMMISSION,
    BRACKET,
    TP1,
)
FAR_BELOW = Decimal("48000.00")
FAR_ABOVE = Decimal("72000.00")
MARKETABLE = Decimal("61500.00")
APPROVED = Decimal("0.002")
ORDER_SENDS = ("new_limit_order", "new_market_order", "new_conditional_order")


def conditional_calls(port: FakeProbePort, tag: str) -> list[dict[str, Any]]:
    """The new_conditional_order requests whose client algo id carries the case tag."""
    return [c for c in sent(port, "new_conditional_order") if f"-{tag}-" in c["client_algo_id"]]


def algo_id_with(port: FakeProbePort, tag: str) -> str:
    (client_id,) = {c["client_algo_id"] for c in conditional_calls(port, tag)}
    return str(client_id)


def algo_raw(
    caid: str,
    status: str,
    *,
    ia: bool = False,
    ai: str = "",
    aq: str = "0",
    rm: str | None = None,
    event_time: int = 1,
) -> dict[str, Any]:
    o: dict[str, Any] = {"caid": caid, "X": status, "ia": ia, "ai": ai, "aq": aq}
    if rm is not None:
        o["rm"] = rm
    return {"e": "ALGO_UPDATE", "E": event_time, "T": event_time, "o": o}


def child_raw(order_id: int) -> dict[str, Any]:
    return {
        "e": "ORDER_TRADE_UPDATE",
        "E": 9,
        "T": 9,
        "o": {
            "c": "autoclid",
            "i": order_id,
            "X": "FILLED",
            "x": "TRADE",
            "ot": "MARKET",
            "z": "0.002",
            "ap": "60000.1",
            "n": "0.024",
            "N": "USDT",
            "rp": "0.5",
            "T": 2,
        },
    }


def fill_rows(*rows: dict[str, str]) -> Any:
    summary = {"count": str(len(rows))}
    for index, row in enumerate(rows):
        for key, value in row.items():
            summary[f"row_{index}_{key}"] = value
    return ok_observation("user_trades", summary)


# ----- _near_triggers (pure) ------------------------------------------------------- #


def test_near_triggers_sit_on_the_tick_grid_and_never_on_the_wrong_side() -> None:
    below, above = dp._near_triggers(Decimal("60000.0"), Decimal("0.1"), Decimal("0.999"))
    assert (below, above) == (Decimal("59940.0"), Decimal("60060.0"))
    # a fraction so close to 1 that the product lands on or beyond the mark: the tick rule wins
    below, above = dp._near_triggers(Decimal("60000.0"), Decimal("0.1"), Decimal("0.9999999"))
    assert below == Decimal("59999.9") and above == Decimal("60000.1")
    below, above = dp._near_triggers(Decimal("60000.05"), Decimal("0.1"), Decimal("0.99999999"))
    assert below < Decimal("60000.05") < above
    assert below % Decimal("0.1") == 0 and above % Decimal("0.1") == 0


@pytest.mark.parametrize("mark", ["83748.12", "0.5", "60000", "1234.5678"])
@pytest.mark.parametrize("fraction", ["0.9", "0.999", "0.999999", "0.99999999999"])
def test_near_triggers_hold_for_many_marks_and_fractions(mark: str, fraction: str) -> None:
    tick = Decimal("0.01")
    below, above = dp._near_triggers(Decimal(mark), tick, Decimal(fraction))
    assert below < Decimal(mark) < above
    assert below % tick == 0 and above % tick == 0


# ----- the common rules, parametrized over the seven cases -------------------------- #


@pytest.mark.parametrize("case_id", ORDER_CASES)
async def test_an_approved_quantity_above_the_notional_cap_sends_nothing(
    tmp_path: Path, case_id: str
) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, case_id, cap="1")
    record = case(document, case_id)
    assert record["status"] == dp.ERROR and record["reason"].startswith("order bound")
    for operation in ORDER_SENDS:
        assert sent(port, operation) == [], operation


@pytest.mark.parametrize("case_id", ORDER_CASES)
async def test_hedge_mode_is_not_observed_and_sends_nothing(tmp_path: Path, case_id: str) -> None:
    port = FakeProbePort(dual_side=True)
    document, _ = await run_cases(tmp_path, port, case_id)
    record = case(document, case_id)
    assert record["status"] == dp.NOT_OBSERVED and record["reason"] == dp.REASON_HEDGE_MODE
    for operation in ORDER_SENDS:
        assert sent(port, operation) == [], operation


@pytest.mark.parametrize("case_id", ORDER_CASES)
async def test_an_entry_that_does_not_fill_is_not_observed_with_the_entry_reason(
    tmp_path: Path, case_id: str
) -> None:
    port = FakeProbePort()
    port.fill_marketable = False
    document, _ = await run_cases(tmp_path, port, case_id)
    record = case(document, case_id)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == "the entry did not fill: status NEW"
    assert sent(port, "new_conditional_order") == []


@pytest.mark.parametrize("case_id", ORDER_CASES)
async def test_a_rejected_entry_is_not_observed_with_the_entry_reason(
    tmp_path: Path, case_id: str
) -> None:
    port = FakeProbePort()
    port.script(
        "new_limit_order",
        error_observation("new_limit_order", code=-4016, category="REJECTED_DEFINITIVE"),
    )
    document, _ = await run_cases(tmp_path, port, case_id)
    record = case(document, case_id)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"].startswith("entry rejected: ")
    assert sent(port, "new_conditional_order") == []


@pytest.mark.parametrize("case_id", ORDER_CASES)
async def test_every_order_case_ends_flat_through_the_runner_cleanup(
    tmp_path: Path, case_id: str
) -> None:
    port = FakeProbePort()
    document, code = await run_cases(tmp_path, port, case_id)
    assert document["cleanup"]["final"]["status"] == dp.CLEANUP_FLAT
    assert case(document, case_id)["cleanup"]["status"] == dp.CLEANUP_FLAT
    assert port.positions_rows == [] and port.open_algo_ids == [] and port.open_order_ids == []
    assert case(document, case_id)["status"] != dp.ERROR
    assert code == dp.EXIT_OK


# ----- P1 / A6: closePosition legs with an open position ----------------------------- #


async def test_close_position_legs_with_a_position(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, CLOSE_POSITION)
    record = case(document, CLOSE_POSITION)
    details = record["details"]
    assert record["status"] == dp.OBSERVED
    stop, take_profit = (
        conditional_calls(port, "cps")[0],
        conditional_calls(port, "cpt")[0],
    )
    assert (stop["order_type"], stop["side"], stop["trigger_price"]) == (
        "STOP_MARKET",
        "SELL",
        FAR_BELOW,
    )
    assert (take_profit["order_type"], take_profit["trigger_price"]) == (
        "TAKE_PROFIT_MARKET",
        FAR_ABOVE,
    )
    for call in (stop, take_profit):
        assert call["close_position"] is True and call["quantity"] is None
        assert call["reduce_only"] is None
    assert details["close_position_stop_accepted"] == "true"
    assert details["close_position_tp_accepted"] == "true"
    assert details["with_legs_open_algo_orders"] == "2"
    assert details["with_legs_position"] == "0.002"
    assert "stop_listed_algo_status" in details and "tp_listed_algo_status" in details
    assert len(sent(port, "cancel_algo_order")) == 2


async def test_a_scripted_minus_4509_is_recorded_verbatim_and_only_accepted_legs_are_cancelled(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script(
        "new_conditional_order",
        error_observation(
            "new_conditional_order",
            code=-4509,
            category="REJECTED_DEFINITIVE",
            message="FAKE position is required",
        ),
    )
    document, _ = await run_cases(tmp_path, port, CLOSE_POSITION)
    details = case(document, CLOSE_POSITION)["details"]
    assert details["close_position_stop_accepted"] == "false"
    assert details["close_position_tp_accepted"] == "true"
    assert "-4509" in details["close_position_stop"]
    assert len(sent(port, "cancel_algo_order")) == 1


# ----- P8 / B5: a stop on the wrong side after the fill -------------------------------- #


async def test_a_would_trigger_stop_is_sent_on_the_wrong_side_and_recorded(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script(
        "new_conditional_order",
        error_observation("new_conditional_order", code=-2021, category="REJECTED_DEFINITIVE"),
    )
    document, _ = await run_cases(tmp_path, port, WOULD_TRIGGER)
    record = case(document, WOULD_TRIGGER)
    (call,) = conditional_calls(port, "wts")
    assert call["order_type"] == "STOP_MARKET" and call["side"] == "SELL"
    assert call["trigger_price"] == FAR_ABOVE and call["close_position"] is True
    assert record["details"]["would_trigger_accepted"] == "false"
    assert "-2021" in record["details"]["would_trigger_stop"]
    assert record["status"] == dp.OBSERVED
    assert "after_position" not in record["details"]


async def test_an_accepted_would_trigger_stop_adds_a_note_and_the_state(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, WOULD_TRIGGER)
    record = case(document, WOULD_TRIGGER)
    assert record["details"]["would_trigger_accepted"] == "true"
    assert any("may trigger at once" in note for note in record["notes"])
    assert "would_trigger_status" in record["details"]
    assert record["details"]["after_position"] == "0.002"


# ----- B2 / B3 / Q5: the deliberate same-id re-placement -------------------------------- #


async def test_the_same_id_probe_sends_the_documented_sequence(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, SAME_ID)
    record = case(document, SAME_ID)
    details = record["details"]
    assert record["status"] == dp.OBSERVED
    first, again_close, again_reduce = conditional_calls(port, "sas")
    ids = {first["client_algo_id"], again_close["client_algo_id"], again_reduce["client_algo_id"]}
    assert len(ids) == 1  # one id, three placements: a deliberate probe, not a retry
    assert (first["close_position"], first["quantity"]) == (True, None)
    assert (again_close["close_position"], again_close["quantity"]) == (True, None)
    assert (again_reduce["reduce_only"], again_reduce["quantity"]) == (True, APPROVED)
    assert again_reduce["close_position"] is None
    for call in (first, again_close, again_reduce):
        assert call["trigger_price"] == FAR_BELOW and call["order_type"] == "STOP_MARKET"
    assert "-2013" in details["query_before_place"]
    assert details["query_right_after_place"].startswith("accepted")
    assert details["query_right_after_place_elapsed_ms"] == "0"
    assert "-4116" in details["same_id_replace_close_position"]
    assert "-4116" in details["same_id_replace_reduce_only"]
    assert details["legs_listed_with_id"] == "1" and details["legs_listed_total"] == "1"
    assert len(sent(port, "cancel_algo_order")) == 1
    assert "CANCELED" in details["query_after_cancel"]
    assert port.names().count("query_algo_order") == 3  # before, right after, after the cancel


class _TwoListedLegs(FakeProbePort):
    """A fake whose list shows the same client algo id twice once three placements were sent."""

    served = False

    async def open_algo_orders(self, *, symbol: str) -> Any:
        if self.served or self.count("new_conditional_order") < 3:
            return await super().open_algo_orders(symbol=symbol)
        self.served = True
        client_id = self.open_algo_ids[0]
        self.calls.append(("open_algo_orders", {"symbol": symbol}))
        return ok_observation(
            "open_algo_orders",
            {
                "count": "2",
                "row_0_client_algo_id": client_id,
                "row_1_client_algo_id": client_id,
            },
        )


async def test_the_same_id_probe_counts_the_legs_listed_with_the_id(tmp_path: Path) -> None:
    port = _TwoListedLegs()
    port.duplicate_algo_answer = ok_observation(
        "new_conditional_order", {"client_algo_id": "dup", "algo_status": "NEW"}
    )
    document, _ = await run_cases(tmp_path, port, SAME_ID)
    details = case(document, SAME_ID)["details"]
    assert details["same_id_replace_close_position"].startswith("accepted")
    assert details["legs_listed_with_id"] == "2" and details["legs_listed_total"] == "2"


# ----- P6 / A3 / G4-035 / P9: a manual close with two closePosition legs open ------------ #


def cancel_all_legs(port: FakeProbePort) -> Any:
    def hook() -> None:
        for client_id in list(port.open_algo_ids):
            port.system_cancel_algo(client_id)

    return hook


async def test_a_manual_close_sends_exactly_the_held_quantity_and_sees_the_system_cancels(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.on_wait.append(cancel_all_legs(port))
    vt = VirtualTime()
    document, _ = await run_cases(tmp_path, port, MANUAL_CLOSE, vt=vt)
    record = case(document, MANUAL_CLOSE)
    details = record["details"]
    assert record["status"] == dp.OBSERVED
    closes = sent(port, "new_market_order")
    assert closes[0]["quantity"] == APPROVED and closes[0]["side"] == "SELL"
    assert closes[0]["reduce_only"] is True and closes[0]["position_side"] == "BOTH"
    assert "-mcx-" in closes[0]["client_order_id"]
    assert details["manual_close_status"] == "FILLED"
    assert details["stop_auto_cancelled"] == "true" and details["tp_auto_cancelled"] == "true"
    assert sent(port, "cancel_algo_order") == []  # nothing left to cancel by hand
    assert vt.sleeps == [30]
    assert details["after_close_open_algo_orders"] == "0"
    assert details["stop_algo_update_sequence"].startswith("NOT_OBSERVED: no raw ALGO_UPDATE")
    assert "CANCELED" in details["stop_statuses_rest"]


async def test_a_manual_close_without_a_system_cancel_cancels_each_leg_by_hand(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, MANUAL_CLOSE)
    details = case(document, MANUAL_CLOSE)["details"]
    assert details["stop_auto_cancelled"] == "false" and details["tp_auto_cancelled"] == "false"
    assert len(sent(port, "cancel_algo_order")) == 2
    assert details["stop_cancel"].startswith("accepted")


async def test_a_manual_close_with_both_legs_rejected_names_the_codes(tmp_path: Path) -> None:
    port = FakeProbePort()
    for _ in range(2):
        port.script(
            "new_conditional_order",
            error_observation("new_conditional_order", code=-4509, category="REJECTED_DEFINITIVE"),
        )
    document, _ = await run_cases(tmp_path, port, MANUAL_CLOSE)
    record = case(document, MANUAL_CLOSE)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"].startswith(dp.REASON_CLOSE_LEGS_REJECTED)
    assert record["reason"].count("-4509") == 2
    assert "manual_close" not in record["details"]


async def test_a_manual_close_without_a_position_is_not_observed(tmp_path: Path) -> None:
    port = FakeProbePort()
    # positions call 0 is the run account read; call 1 is the case read before the close
    port.script_call("positions", 1, ok_observation("positions", {"count": "0"}))
    document, _ = await run_cases(tmp_path, port, MANUAL_CLOSE)
    record = case(document, MANUAL_CLOSE)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == dp.REASON_NO_POSITION_HELD
    assert "manual_close" not in record["details"]


# ----- G2-042 / A9: commission versus realized PnL --------------------------------------- #

ENTRY_TRADE = {
    "trade_id": "11",
    "side": "BUY",
    "price": "61500.0",
    "qty": "0.002",
    "quote_qty": "123.00000",
    "commission": "0.0246",
    "commission_asset": "USDT",
    "realized_pnl": "0",
    "maker": "false",
    "time_ms": "1000",
}
CLOSE_TRADE = {
    "trade_id": "12",
    "side": "SELL",
    "price": "61550.0",
    "qty": "0.002",
    "quote_qty": "123.10000",
    "commission": "0.0246",
    "commission_asset": "USDT",
    "realized_pnl": "0.05000000",
    "maker": "false",
    "time_ms": "2000",
}


class _WithOrderIds(FakeProbePort):
    """A fake whose entry and close answers carry an order id (the default ones do not)."""

    async def new_limit_order(self, **kwargs: Any) -> Any:
        answer = await super().new_limit_order(**kwargs)
        if not answer.ok:
            return answer
        return ok_observation(answer.operation, {**answer.summary, "order_id": "111"})

    async def new_market_order(self, **kwargs: Any) -> Any:
        answer = await super().new_market_order(**kwargs)
        if not answer.ok:
            return answer
        return ok_observation(answer.operation, {**answer.summary, "order_id": "222"})


def commission_port(*, close_trade: dict[str, str] | None = None) -> FakeProbePort:
    port = _WithOrderIds()
    port.script_call("user_trades", 0, fill_rows(close_trade or CLOSE_TRADE))
    port.script_call("user_trades", 1, fill_rows(ENTRY_TRADE))
    port.income_rows = [
        {
            "income_type": "COMMISSION",
            "income": "-0.0246",
            "asset": "USDT",
            "trade_id": "11",
            "tran_id": "5",
            "time_ms": "1001",
        },
        {
            "income_type": "REALIZED_PNL",
            "income": "0.05000000",
            "asset": "USDT",
            "trade_id": "12",
            "tran_id": "6",
            "time_ms": "2001",
        },
        {
            "income_type": "COMMISSION",
            "income": "-0.0246",
            "asset": "USDT",
            "trade_id": "12",
            "tran_id": "7",
            "time_ms": "2002",
        },
        {  # another trade of the day: never matched
            "income_type": "COMMISSION",
            "income": "-9",
            "asset": "USDT",
            "trade_id": "999",
            "tran_id": "8",
            "time_ms": "3000",
        },
    ]
    return port


async def test_commission_vs_realized_pnl_records_trades_income_and_derived_sums(
    tmp_path: Path,
) -> None:
    port = commission_port()
    document, _ = await run_cases(tmp_path, port, COMMISSION)
    record = case(document, COMMISSION)
    details = record["details"]
    assert record["status"] == dp.OBSERVED
    assert details["entry_order_id"] == "111" and details["close_order_id"] == "222"
    trade_queries = sent(port, "user_trades")
    assert [q["order_id"] for q in trade_queries] == [222, 111]
    assert (
        details["close_trade_1"]
        == "12|SELL|61550.0|0.002|123.10000|0.0246|USDT|0.05000000|false|2000"
    )
    assert details["entry_trade_1"] == "11|BUY|61500.0|0.002|123.00000|0.0246|USDT|0|false|1000"
    assert sent(port, "income_history")[0]["start_time_ms"] == 1000  # the smallest trade time
    assert details["income_1"] == "COMMISSION|-0.0246|USDT|11|5|1001"
    assert details["income_2"] == "REALIZED_PNL|0.05000000|USDT|12|6|2001"
    assert details["income_3"] == "COMMISSION|-0.0246|USDT|12|7|2002"
    assert "income_4" not in details
    assert Decimal(details["derived_sell_quote_minus_buy_quote"]) == Decimal("0.10000")
    assert Decimal(details["derived_sum_realized_pnl_trades"]) == Decimal("0.05")
    assert Decimal(details["derived_sum_commission_trades"]) == Decimal("0.0492")
    assert Decimal(details["derived_income_realized_pnl_sum"]) == Decimal("0.05")
    assert Decimal(details["derived_income_commission_sum"]) == Decimal("-0.0492")
    assert not [name for name in details if "verdict" in name or "includes" in name]


async def test_mixed_commission_assets_write_no_commission_sum(tmp_path: Path) -> None:
    port = commission_port(
        close_trade={**CLOSE_TRADE, "commission_asset": "BNB", "commission": "0.0001"}
    )
    document, _ = await run_cases(tmp_path, port, COMMISSION)
    details = case(document, COMMISSION)["details"]
    assert "derived_sum_commission_trades" not in details
    assert "derived_sum_realized_pnl_trades" in details


async def test_a_missing_order_id_queries_the_trades_without_it_and_records_the_fact(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()  # the fake answers carry no order_id
    port.trades = [dict(CLOSE_TRADE), dict(ENTRY_TRADE)]
    document, _ = await run_cases(tmp_path, port, COMMISSION)
    details = case(document, COMMISSION)["details"]
    assert details["entry_order_id"].startswith("NOT_OBSERVED")
    assert details["close_order_id"].startswith("NOT_OBSERVED")
    assert [q["order_id"] for q in sent(port, "user_trades")] == [None, None]
    assert "without" in details["close_trades_query_note"]
    assert "without" in details["entry_trades_query_note"]
    # both queries returned the same two trades: counted once in the derived sums
    assert Decimal(details["derived_sum_realized_pnl_trades"]) == Decimal("0.05")


async def test_the_trade_and_income_waits_are_one_owner_timeout_each(tmp_path: Path) -> None:
    port = commission_port()
    port.script_call("user_trades", 0, fill_rows())  # no close trade yet
    port.script_call("user_trades", 1, fill_rows(CLOSE_TRADE))  # after the wait
    port.script_call("user_trades", 2, fill_rows(ENTRY_TRADE))
    rows = list(port.income_rows)
    port.income_rows = []

    def income_appears() -> None:
        if port.count("income_history") >= 1:
            port.income_rows = rows
        else:
            port.on_wait.append(income_appears)  # the trade wait: not yet

    port.on_wait.append(income_appears)
    vt = VirtualTime()
    document, _ = await run_cases(tmp_path, port, COMMISSION, vt=vt)
    assert vt.sleeps == [30, 30]
    assert case(document, COMMISSION)["details"]["income_1"].startswith("COMMISSION")


# ----- P2 / P11 / A3: the triggered closePosition bracket -------------------------------- #


def trigger_stop(port: FakeProbePort, stop_id: str, tp_id: str) -> Any:
    """A stop leg that triggers (NEW twice, TRIGGERING, TRIGGERED, FINISHED), the TP cancelled."""

    def hook() -> None:
        port.emit_raw(algo_raw(stop_id, "NEW", ia=False, event_time=1))
        port.emit_raw(algo_raw(stop_id, "NEW", ia=False, event_time=2))
        port.emit_raw(algo_raw(stop_id, "TRIGGERING", ia=True, event_time=3))
        port.emit_raw(algo_raw(stop_id, "TRIGGERED", ia=True, ai="555", aq="0.002", event_time=4))
        port.emit_raw(algo_raw(stop_id, "FINISHED", ia=True, ai="555", aq="0.002", event_time=5))
        port.emit_raw(child_raw(555))
        port.trigger_algo(stop_id, child_order_id="555")
        port.system_cancel_algo(tp_id)

    return hook


async def run_bracket(
    tmp_path: Path, port: FakeProbePort, *, trigger: bool, vt: VirtualTime | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if trigger:

        def late_hook() -> None:
            stop_id = algo_id_with(port, "tbs")
            tp_id = algo_id_with(port, "tbt")
            trigger_stop(port, stop_id, tp_id)()

        port.on_wait.append(late_hook)
    document, _ = await run_cases(tmp_path, port, BRACKET, vt=vt)
    return document, case(document, BRACKET)


async def test_the_bracket_prices_both_legs_near_the_live_mark(tmp_path: Path) -> None:
    port = FakeProbePort()
    _, record = await run_bracket(tmp_path, port, trigger=True)
    stop, take_profit = conditional_calls(port, "tbs")[0], conditional_calls(port, "tbt")[0]
    assert (stop["order_type"], stop["trigger_price"]) == ("STOP_MARKET", Decimal("59940.00"))
    assert (take_profit["order_type"], take_profit["trigger_price"]) == (
        "TAKE_PROFIT_MARKET",
        Decimal("60060.00"),
    )
    for call in (stop, take_profit):
        assert (
            call["side"] == "SELL" and call["close_position"] is True and call["quantity"] is None
        )
    details = record["details"]
    assert Decimal(details["live_mark_price"]) == Decimal("60000")
    assert Decimal(details["stop_trigger_price"]) == Decimal("59940")
    assert Decimal(details["tp_trigger_price"]) == Decimal("60060")
    assert len(sent(port, "live_mark_price")) == 1


async def test_the_bracket_records_the_full_raw_algo_update_sequence(tmp_path: Path) -> None:
    port = FakeProbePort()
    vt = VirtualTime()
    _, record = await run_bracket(tmp_path, port, trigger=True, vt=vt)
    details = record["details"]
    assert record["status"] == dp.OBSERVED
    assert vt.sleeps == [30]  # one wait; the settle check passed at once
    assert details["triggered_leg"] == "stop"
    assert details["tp_auto_cancelled"] == "true"
    assert details["stop_algo_update_count"] == "5"
    assert details["stop_algo_update_sequence"] == (
        "NEW|false||0||1|1;NEW|false||0||2|2;TRIGGERING|true||0||3|3;"
        "TRIGGERED|true|555|0.002||4|4;FINISHED|true|555|0.002||5|5"
    )
    assert details["stop_repeated_statuses"] == "NEW x2"
    assert details["stop_statuses_beyond_new_canceled"] == "FINISHED,TRIGGERED,TRIGGERING"
    assert details["stop_ia_values"] == "false,true"
    assert details["stop_ai_values"] == "(empty),555"
    assert details["stop_aq_values"] == "0,0.002"
    assert details["stop_child_1"] == (
        "autoclid|FILLED|TRADE|MARKET|0.002|60000.1|0.024|USDT|0.5|2"
    )
    assert details["stop_ai"] == "555" and details["stop_aq"] == "0.002"
    assert [q["order_id"] for q in sent(port, "user_trades")] == [555]
    assert details["after_trigger_position"] == "0"
    assert details["tp_algo_update_sequence"].startswith("NOT_OBSERVED: no raw ALGO_UPDATE")


async def test_a_first_rest_minus_2013_does_not_end_the_bracket_wait(tmp_path: Path) -> None:
    port = FakeProbePort()
    for index in range(2):  # both legs answer -2013 on their first query
        port.script_call("query_algo_order", index, _absent("query_algo_order"))
    vt = VirtualTime()
    _, record = await run_bracket(tmp_path, port, trigger=True, vt=vt)
    assert vt.sleeps == [30]  # the wait went on for one owner case timeout
    assert record["status"] == dp.OBSERVED
    assert record["details"]["triggered_leg"] == "stop"
    assert "ABSENT" in record["details"]["stop_statuses_rest"]


async def test_without_a_trigger_the_bracket_is_not_observed_with_every_fact(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    for index in range(2):
        port.script_call("query_algo_order", index, _absent("query_algo_order"))
    vt = VirtualTime()
    _, record = await run_bracket(tmp_path, port, trigger=False, vt=vt)
    assert record["status"] == dp.NOT_OBSERVED and record["reason"] == dp.REASON_NOT_TRIGGERED
    assert vt.sleeps == [30]
    details = record["details"]
    assert details["stop_statuses_rest"].startswith("ABSENT")
    assert details["not_triggered_open_algo_orders"] == "2"
    assert details["stop_algo_update_sequence"].startswith("NOT_OBSERVED")
    assert "triggered_leg" not in details


async def test_the_bracket_with_both_legs_rejected_is_not_observed(tmp_path: Path) -> None:
    port = FakeProbePort()
    for _ in range(2):
        port.script(
            "new_conditional_order",
            error_observation("new_conditional_order", code=-4509, category="REJECTED_DEFINITIVE"),
        )
    _, record = await run_bracket(tmp_path, port, trigger=False)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"].startswith(dp.REASON_CLOSE_LEGS_REJECTED)


async def test_an_unreadable_live_mark_stops_the_bracket_before_any_leg(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script(
        "live_mark_price",
        error_observation("live_mark_price", code=None, category="UNKNOWN_EXCHANGE_ERROR"),
    )
    _, record = await run_bracket(tmp_path, port, trigger=False)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"].startswith("the live mark price is unreadable")
    assert sent(port, "new_conditional_order") == []


# ----- P10 / A7 / O-03: TP1 sized from the fill -------------------------------------------- #


def fake_lot_filters() -> Any:
    from src.domain.lot_filters import LotFilters

    from tests.probe_fakes import FAKE_SYMBOL_FILTERS as f

    return LotFilters(
        symbol="BTCUSDT",
        price_tick_size=Decimal(f["tick_size"]),
        lot_min_quantity=Decimal(f["min_quantity"]),
        lot_max_quantity=Decimal(f["max_quantity"]),
        lot_step_size=Decimal(f["step_size"]),
        market_lot_min_quantity=Decimal(f["market_lot_min_quantity"]),
        market_lot_max_quantity=Decimal(f["market_lot_max_quantity"]),
        market_lot_step_size=Decimal(f["market_lot_step_size"]),
        min_notional=Decimal(f["min_notional"]),
    )


def trigger_tp1(port: FakeProbePort) -> Any:
    def hook() -> None:
        tp_id = algo_id_with(port, "tp1")
        port.emit_raw(algo_raw(tp_id, "NEW", event_time=1))
        port.emit_raw(algo_raw(tp_id, "TRIGGERED", ia=True, ai="777", aq="0.001", event_time=2))
        port.emit_raw(child_raw(777))
        port.trigger_algo(tp_id, child_order_id="777")
        port.positions_rows = [("BOTH", Decimal("0.001"))]  # the remainder stays open

    return hook


async def test_tp1_is_the_production_quantization_of_the_held_quantity(tmp_path: Path) -> None:
    from src.backtest.semantics import TP1_QUANTITY_FRACTION
    from src.execution.lot_split import quantize_to_lot

    port = FakeProbePort()
    port.on_wait.append(trigger_tp1(port))
    document, _ = await run_cases(tmp_path, port, TP1)
    record = case(document, TP1)
    details = record["details"]
    expected = min(
        quantize_to_lot(
            quantity=APPROVED * TP1_QUANTITY_FRACTION, filters=fake_lot_filters(), market_exit=True
        ),
        APPROVED,
    )
    assert record["status"] == dp.OBSERVED
    assert Decimal(details["tp1_quantity"]) == expected == Decimal("0.001")
    assert Decimal(details["tp1_quantity_lot_size_only"]) == Decimal("0.001")
    assert Decimal(details["held_quantity"]) == APPROVED
    assert "TP1_QUANTITY_FRACTION" in details["tp1_fraction_source"]
    (call,) = conditional_calls(port, "tp1")
    assert call["order_type"] == "TAKE_PROFIT_MARKET" and call["side"] == "SELL"
    assert call["reduce_only"] is True and call["quantity"] == expected
    assert call["close_position"] is None and call["trigger_price"] == Decimal("60060.00")
    assert call["quantity"] <= APPROVED
    assert Decimal(details["tp1_aq"]) == Decimal("0.001")
    assert details["after_tp1_position"] == "0.001"
    assert Decimal(details["tp1_notional_at_trigger"]) == Decimal("0.001") * Decimal("60060.00")
    assert details["min_notional"] == "100"
    assert details["tp1_algo_update_sequence"].startswith("NEW|false||0||1|1;TRIGGERED|true|777")
    assert details["tp1_child_1"].startswith("autoclid|FILLED")


async def test_tp1_without_a_trigger_is_not_observed_with_the_facts(tmp_path: Path) -> None:
    port = FakeProbePort()
    vt = VirtualTime()
    document, _ = await run_cases(tmp_path, port, TP1, vt=vt)
    record = case(document, TP1)
    assert record["status"] == dp.NOT_OBSERVED and record["reason"] == dp.REASON_NOT_TRIGGERED
    assert vt.sleeps == [30]
    assert Decimal(record["details"]["tp1_quantity"]) == Decimal("0.001")


async def test_tp1_with_an_unreadable_lot_filter_is_not_observed_and_sends_no_leg(
    tmp_path: Path,
) -> None:
    from tests.probe_fakes import FAKE_SYMBOL_FILTERS

    broken = {k: v for k, v in FAKE_SYMBOL_FILTERS.items() if k != "market_lot_step_size"}
    port = FakeProbePort()
    # symbol_filters call 0 is the run market read; call 1 is the case read
    port.script_call(
        "symbol_filters",
        1,
        ok_observation("symbol_filters", {"symbol": "BTCUSDT", "found": "true", **broken}),
    )
    document, _ = await run_cases(tmp_path, port, TP1)
    record = case(document, TP1)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == dp.REASON_LOT_FILTERS_UNREADABLE
    assert sent(port, "new_conditional_order") == []


async def test_tp1_quantity_is_never_above_the_held_quantity() -> None:
    from src.backtest.semantics import TP1_QUANTITY_FRACTION
    from src.execution.lot_split import quantize_to_lot

    filters = fake_lot_filters()
    for held in ("0.001", "0.002", "0.003", "0.0049", "1"):
        quantity = Decimal(held)
        tp1 = min(
            quantize_to_lot(
                quantity=quantity * TP1_QUANTITY_FRACTION, filters=filters, market_exit=True
            ),
            quantity,
        )
        assert tp1 <= quantity


async def test_the_tp1_case_with_a_held_quantity_that_quantizes_to_zero(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call(
        "positions",
        1,
        ok_observation(
            "positions",
            {
                "count": "1",
                "row_0_symbol": "BTCUSDT",
                "row_0_position_side": "BOTH",
                "row_0_position_amt": "0.001",
            },
        ),
    )
    document, _ = await run_cases(tmp_path, port, TP1)
    record = case(document, TP1)
    assert record["status"] == dp.NOT_OBSERVED and record["reason"] == dp.REASON_TP1_ZERO
    assert sent(port, "new_conditional_order") == []


# =========================================================================== #
# Task 3: gtd_entry_expiry_status (A2, P4), the script docstring and the runbook.
# =========================================================================== #

GTD = "gtd_entry_expiry_status"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
GTD_LIFETIME = 660
GTD_WAIT = 720


def gtd_id(port: FakeProbePort) -> str:
    (call,) = sent(port, "new_gtd_limit_order")
    return str(call["client_order_id"])


def expire_when_waiting(port: FakeProbePort, *, reason: str | None = "FAKE_REASON") -> Any:
    def hook() -> None:
        client_id = gtd_id(port)
        raw = {
            "e": "ORDER_TRADE_UPDATE",
            "E": 5,
            "T": 5,
            "o": {"c": client_id, "X": "EXPIRED", "x": "EXPIRED", "T": 123},
        }
        port.expire_order(client_id, raw=raw, expire_reason=reason)

    return hook


async def test_the_gtd_case_sends_one_gtd_limit_with_a_whole_second_good_till_date(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.on_wait.append(expire_when_waiting(port))
    start = TEST_ONLY_VIRTUAL_START + timedelta(microseconds=987654)  # sub-second part dropped
    vt = VirtualTime(start)
    document, _ = await run_cases(tmp_path, port, GTD, vt=vt)
    record = case(document, GTD)
    (call,) = sent(port, "new_gtd_limit_order")
    expected = ((start - EPOCH) // timedelta(seconds=1) + GTD_LIFETIME) * 1000
    assert call["good_till_date_ms"] == expected and isinstance(call["good_till_date_ms"], int)
    assert call["good_till_date_ms"] % 1000 == 0
    assert (call["side"], call["price"], call["quantity"]) == ("BUY", FAR_BELOW, APPROVED)
    assert call["position_side"] == "BOTH" and "-gtd-" in call["client_order_id"]
    assert vt.sleeps == [GTD_WAIT]  # exactly one wait, the owner GTD wait
    details = record["details"]
    assert details["good_till_date_ms"] == str(expected)
    assert details["good_till_date_echoed"] == str(expected)
    assert details["placed_at_utc"] == start.isoformat()
    assert details["good_till_date_lifetime_seconds"] == str(GTD_LIFETIME)
    assert sent(port, "new_limit_order") == [] and sent(port, "new_market_order") == []


async def test_an_expired_entry_records_the_terminal_status_the_frames_and_the_time(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.on_wait.append(expire_when_waiting(port))
    document, _ = await run_cases(tmp_path, port, GTD)
    record = case(document, GTD)
    details = record["details"]
    assert record["status"] == dp.OBSERVED
    assert details["terminal_status"] == "EXPIRED"
    assert details["rest_statuses"] == "NEW,EXPIRED"
    assert details["frame_statuses"] == "EXPIRED/EXPIRED/FAKE_REASON"
    assert details["seconds_to_terminal"] == str(GTD_WAIT)
    assert details["raw_order_updates"] == "EXPIRED|EXPIRED|123"
    assert sent(port, "cancel_order") == []  # nothing left to cancel


async def test_an_entry_that_stays_open_is_cancelled_once_and_not_observed(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    vt = VirtualTime()
    document, _ = await run_cases(tmp_path, port, GTD, vt=vt)
    record = case(document, GTD)
    assert record["status"] == dp.NOT_OBSERVED
    assert record["reason"] == dp.REASON_GTD_NOT_TERMINAL
    assert "gtd_expiry_wait_seconds" in record["reason"]
    assert len(sent(port, "cancel_order")) == 1
    assert record["details"]["rest_statuses"] == "NEW,NEW"
    assert record["details"]["terminal_status"] == "none"
    assert vt.sleeps == [GTD_WAIT]
    assert port.open_order_ids == []


async def test_a_rejected_gtd_placement_is_observed_with_its_code_and_never_waits(
    tmp_path: Path,
) -> None:
    port = FakeProbePort()
    port.script(
        "new_gtd_limit_order",
        error_observation("new_gtd_limit_order", code=-4023, category="REJECTED_DEFINITIVE"),
    )
    vt = VirtualTime()
    document, _ = await run_cases(tmp_path, port, GTD, vt=vt)
    record = case(document, GTD)
    assert record["status"] == dp.OBSERVED
    assert "-4023" in record["details"]["gtd_limit"]
    assert vt.sleeps == []
    assert sent(port, "cancel_order") == []


async def test_an_absent_answer_is_recorded_but_is_not_terminal(tmp_path: Path) -> None:
    port = FakeProbePort()
    port.script_call("query_order", 0, error_observation("query_order", **ABSENT))
    port.on_wait.append(expire_when_waiting(port))
    vt = VirtualTime()
    document, _ = await run_cases(tmp_path, port, GTD, vt=vt)
    details = case(document, GTD)["details"]
    assert vt.sleeps == [GTD_WAIT]
    assert details["rest_statuses"] == "unreadable,EXPIRED"
    assert "-2013" in details["order_status_query"]


async def test_a_terminal_frame_alone_ends_the_wait(tmp_path: Path) -> None:
    port = FakeProbePort()

    def frame_only() -> None:
        port.emit_frame(
            {
                "event_type": "OrderUpdateEvent",
                "client_order_id": gtd_id(port),
                "order_status": "EXPIRED",
                "execution_type": "EXPIRED",
            }
        )

    port.on_wait.append(frame_only)
    document, _ = await run_cases(tmp_path, port, GTD)
    record = case(document, GTD)
    assert record["status"] == dp.OBSERVED
    assert record["details"]["terminal_status"] == "EXPIRED"
    assert record["details"]["rest_statuses"] == "NEW,NEW"


async def test_the_gtd_case_checks_the_bound_first_and_refuses_hedge_mode(tmp_path: Path) -> None:
    port = FakeProbePort()
    document, _ = await run_cases(tmp_path, port, GTD, cap="1")
    record = case(document, GTD)
    assert record["status"] == dp.ERROR and record["reason"].startswith("order bound")
    assert sent(port, "new_gtd_limit_order") == []
    hedge = FakeProbePort(dual_side=True)
    (tmp_path / "h").mkdir()
    document, _ = await run_cases(tmp_path / "h", hedge, GTD)
    assert case(document, GTD)["reason"] == dp.REASON_HEDGE_MODE
    assert sent(hedge, "new_gtd_limit_order") == []


async def test_the_gtd_case_in_a_dry_run_plans_the_far_buy_and_the_good_till_date(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, case_ids=(GTD,), execute=False)
    recorder = dp.ProbeRecorder()
    rig = dp.build_dry_run_rig(config)
    await dp.run_probe(config, rig, recorder)
    document = recorder.document(config)
    planned = [r for r in case(document, GTD)["planned_requests"] if r["mutating"]]
    assert [r["operation"] for r in planned[:1]] == ["new_gtd_limit_order"]
    kwargs = planned[0]["kwargs"]
    assert kwargs["price"] == "48000.00" and kwargs["quantity"] == "0.002"
    assert isinstance(kwargs["good_till_date_ms"], int)
    assert kwargs["good_till_date_ms"] % 1000 == 0
    assert case(document, GTD)["status"] == dp.NOT_REHEARSED


# ----- the dry run with every key, the Phase 18 list, the AST guards, the runbook ---------- #


def test_a_main_dry_run_with_all_ten_keys_exits_0_and_lists_the_ten_not_rehearsed(
    tmp_path: Path,
) -> None:
    limits = write_probe_limits(tmp_path, optional=tuple(CASE_KEYS[c] for c in dp.CAPTURE_CASES))
    code = dp.main(
        [
            "--environment",
            "DEMO",
            "--probe-limits-file",
            str(limits),
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ],
        environ={},
    )
    assert code == dp.EXIT_OK
    (path,) = (tmp_path / "evidence").glob("demo-probe-DRYRUN-*.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    by_id = {item["case_id"]: item for item in document["cases"]}
    assert [cid for cid in by_id if cid in dp.CAPTURE_CASES] == list(dp.CAPTURE_CASES)
    for cid in dp.CAPTURE_CASES:
        assert by_id[cid]["status"] == dp.NOT_REHEARSED and by_id[cid]["handler_registered"]
    assert document["mode"] == dp.MODE_DRY_RUN and document["proof_class"] == dp.PROOF_FAKE
    assert document["outcome"] == dp.OUTCOME_COMPLETE


async def test_every_capture_handler_runs_in_a_dry_run_without_an_error(tmp_path: Path) -> None:
    config = make_config(tmp_path, case_ids=dp.CAPTURE_CASES, execute=False)
    recorder = dp.ProbeRecorder()
    code = await dp.run_probe(config, dp.build_dry_run_rig(config), recorder)
    assert code == dp.EXIT_OK
    assert [cid for cid in dp.CAPTURE_CASES if cid not in recorder.results] == []
    assert {cid: r.reason for cid, r in recorder.results.items() if r.status == dp.ERROR} == {}


def test_without_a_new_key_the_case_list_is_the_phase18_list(tmp_path: Path) -> None:
    config = make_config(tmp_path, execute=False)
    assert config.case_ids == dp.REQUIRED_CASES
    optional = ("explicit_time_in_force", "stream_gap", "market_lot_size_out_of_range")
    limits = write_probe_limits(tmp_path, optional=optional, name="phase18.toml")
    full = dp.parse_config(
        [
            "--environment",
            "DEMO",
            "--probe-limits-file",
            str(limits),
            "--evidence-dir",
            str(tmp_path),
        ]
    )
    assert full.case_ids == (*dp.REQUIRED_CASES, *tuple(dp.OPTIONAL_CASES.values())[:3])
    assert not set(full.case_ids) & set(dp.CAPTURE_CASES)


def test_every_case_id_has_a_handler_and_the_gtd_wait_is_the_only_extra_timeout() -> None:
    assert set(dp.CASE_HANDLERS) == set(dp.CASE_ORDER)
    tree = ast.parse(Path(dp.__file__).read_text(encoding="utf-8"))
    gtd_waits = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and ast.unparse(call.func) == "wait_up_to"
        and ast.unparse(call.args[2]).endswith("gtd_expiry_wait_seconds")
    }
    assert gtd_waits == {"_gtd_entry_expiry_status"}


def test_the_script_has_no_float_constructor_and_documents_the_capture_cases() -> None:
    path = Path(dp.__file__)
    assert float_constructor_calls(path) == []
    doc = dp.__doc__ or ""
    for needle in ("261021-sj0", "CAPTURE_CASES", "--fixtures-dir", "--only", "acceptance.overall"):
        assert needle in doc, needle


RUNBOOK = Path(dp.__file__).resolve().parents[1] / ".planning" / "DEMO-EVIDENCE-PLAN.md"


def test_the_runbook_names_every_case_command_and_consumer() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    needed = [
        *dp.CAPTURE_CASES,
        *(CASE_KEYS[cid] for cid in dp.CAPTURE_CASES),
        "user_data_smoke",
        "18-UAT",
        "DEMO SMOKE BTCUSDT",
        "DEMO PROBE BTCUSDT",
        "19-probe-limits.toml",
        "G2-042",
        "G4-035",
        "A6",
        "A3",
        "A2",
        "A7",
        "A9",
        "P10",
        "ia",
        "--execute",
        "--only",
        "--fixtures-dir",
        "demo-probe-EVIDENCE-",
        "-rest-",
        "provenance.md",
        "demo-observed, not mainnet",
        "D055",
    ]
    assert [name for name in needed if name not in text] == []
    assert "<OWNER:" in text  # every owner number is a placeholder: the file is not parseable
    for forbidden in ("http://", "https://", "BINANCE_", "api_key", "secret ="):
        assert forbidden not in text, forbidden


def test_the_runbook_commands_use_the_real_flags() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    parser_flags = {
        option
        for parser in (dp._build_parser(), user_data_smoke._build_parser())
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--")
    }
    used = set(re.findall(r"(--[a-z][a-z-]+)", text))
    assert used <= parser_flags, used - parser_flags
    assert {"--execute", "--only", "--fixtures-dir", "--probe-limits-file"} <= used
    assert "--smoke-limits-file" in used
