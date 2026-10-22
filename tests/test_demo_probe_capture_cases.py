"""The ten owner opt-in evidence-capture cases of quick task 261021-sj0, on fakes.

Everything runs offline on `FakeProbePort` / `RecordingProbePort` and on virtual time
(`tests/support/virtual_time.py`); nothing sleeps in real time and nothing reaches Binance. The
limits are TEST_ONLY values written by `write_probe_limits`. The FAKE market is the one of
`tests/test_demo_probe_cases.py`: mark 60000.00, tick 0.10, step 0.001, quantity 0.002, notional
cap 150, far_price_fraction 0.80 (a far BUY rests at 48000.00, a far up-trigger sits at
72000.00, a marketable BUY is priced at 61500.00).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts import demo_probe as dp

from tests.probe_fakes import (
    FakeProbePort,
    error_observation,
    ok_observation,
    write_probe_limits,
)
from tests.support.virtual_time import VirtualTime

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
