"""The user-data smoke dry run (plan 18-16): the identical pipeline over the SDK-shaped fakes.

The real `UserDataAdapter`, `SdkListenKeyPort`, `SdkUserDataTransport`, `UserDataSupervisor` and
`BinancePublicMarketData` run over the fakes of `tests/userdata_fakes.py` and the script's fake
order port, on virtual time. Every test patches `asyncio.sleep`, `socket.socket` and
`requests.Session.request` to fail, so nothing sleeps in real time and nothing reaches a
network. The smoke limits written here are TEST_ONLY values, never an owner-approved size.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from scripts import user_data_smoke as uds
from src.adapters.binance_limits import load_binance_limits
from src.domain.exchange_errors import ExchangeErrorCategory
from src.ops import redaction

from tests.support.net_guard import forbid_network_and_sleep
from tests.userdata_fakes import TEST_ONLY_LISTEN_KEY

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
def no_network_no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail on any real sleep, HTTP request, name lookup or non-loopback socket connect."""
    return forbid_network_and_sleep(monkeypatch)


@pytest.fixture(autouse=True)
def _isolated_runtime_secrets() -> Iterator[None]:
    redaction.clear_runtime_secrets()
    yield
    redaction.clear_runtime_secrets()


@pytest.fixture
def smoke_limits(tmp_path: Path) -> Path:
    path = tmp_path / "smoke-limits.toml"
    path.write_text(TEST_ONLY_SMOKE_LIMITS, encoding="utf-8")
    return path


def _argv(smoke_limits: Path, evidence: Path, *extra: str) -> list[str]:
    return [
        "--environment",
        "DEMO",
        "--smoke-limits-file",
        str(smoke_limits),
        "--evidence-dir",
        str(evidence),
        *extra,
    ]


def _only_evidence(directory: Path) -> tuple[Path, dict[str, Any]]:
    files = sorted(directory.glob("user-data-smoke-*.json"))
    assert len(files) == 1, files
    return files[0], json.loads(files[0].read_text(encoding="utf-8"))


def _config(smoke_limits: Path, evidence: Path, *extra: str) -> uds.SmokeConfig:
    return uds.parse_config(_argv(smoke_limits, evidence, *extra))


def _steps(document: dict[str, Any]) -> dict[str, str]:
    return {step["name"]: step["status"] for step in document["steps"]}


def _run_with(
    smoke_limits: Path, evidence: Path, scenario: uds.DryRunScenario | None = None
) -> tuple[int, uds.SmokeRig, dict[str, Any]]:
    """main() with a captured dry rig so the test can read the fakes afterwards."""
    built: list[uds.SmokeRig] = []

    def factory(config: uds.SmokeConfig) -> uds.SmokeRig:
        rig = uds.build_dry_run_rig(config, scenario)
        built.append(rig)
        return rig

    code = uds.main(_argv(smoke_limits, evidence), environ={}, rig_factory=factory)
    _, document = _only_evidence(evidence)
    return code, built[0], document


# --------------------------------------------------------------------------- #
# Tracer: start, one far order placed and cancelled, typed NEW and CANCELED, FAKE evidence.
# --------------------------------------------------------------------------- #


def test_tracer_dry_run_writes_a_scrubbed_fake_evidence_file_with_both_typed_events(
    tmp_path: Path, smoke_limits: Path, no_network_no_sleep: list[str]
) -> None:
    evidence = tmp_path / "evidence"
    code = uds.main(_argv(smoke_limits, evidence), environ={})

    path, document = _only_evidence(evidence)
    assert code == uds.EXIT_OK
    assert no_network_no_sleep == []
    assert path.name.startswith("user-data-smoke-DRYRUN-")
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    assert document["schema"] == uds.EVIDENCE_SCHEMA == "user-data-smoke-evidence/schema-1"
    assert document["mode"] == "dry-run"
    assert document["proof_class"] == "FAKE"
    assert document["sdk_route_delivery"] == "PASS"
    ours = [event for event in document["events"] if event.get("is_smoke_order")]
    assert [event["execution_type"] for event in ours] == ["NEW", "CANCELED"]
    assert all(event["event_type"] == "ORDER_TRADE_UPDATE" for event in ours)
    assert document["order"]["client_order_id"] == ours[0]["client_order_id"]
    assert TEST_ONLY_LISTEN_KEY not in raw.decode("ascii")
    assert uds.SINGLETON_NOTE in document["notes"]


def test_the_dry_run_state_sequence_reaches_live_and_ends_stopped(
    tmp_path: Path, smoke_limits: Path
) -> None:
    code, rig, document = _run_with(smoke_limits, tmp_path)
    states = [entry["state"] for entry in document["state_sequence"]]
    assert code == uds.EXIT_OK
    assert states[:3] == ["CONNECTING", "SYNCING", "LIVE"]
    assert states[-1] == "STOPPED"
    assert set(_steps(document).values()) == {"PASSED"}


def test_the_far_order_is_one_buy_limit_on_the_tick_grid_inside_the_band(
    tmp_path: Path, smoke_limits: Path
) -> None:
    _, rig, document = _run_with(smoke_limits, tmp_path)
    order = document["order"]
    mark = uds.Decimal(uds.DRY_RUN_FAKE_MARK)
    tick = uds.Decimal(uds.DRY_RUN_FAKE_FILTERS["tick_size"])
    price = uds.Decimal(order["price"])
    assert price == uds.far_order_price(mark, uds.Decimal("0.96"), tick)
    assert price % tick == 0
    assert (order["side"], order["type"], order["time_in_force"]) == ("BUY", "LIMIT", "GTC")
    calls = rig.fakes.orders.calls
    assert calls.count("place_entry") == 1
    assert calls.count("cancel_normal_order") == 1


def test_the_environment_guard_runs_before_the_stages_and_the_calls(
    tmp_path: Path, smoke_limits: Path
) -> None:
    _, rig, _ = _run_with(smoke_limits, tmp_path)
    # every port call, every transport connect and every stage passes the guard
    order_calls = len(rig.fakes.orders.calls)
    assert len(rig.fakes.guard_calls) > order_calls


def test_dry_run_restores_the_process_wide_patches(tmp_path: Path, smoke_limits: Path) -> None:
    from binance_common import websocket as sdk_websocket

    stream_map = sdk_websocket.global_stream_connections
    to_thread = asyncio.to_thread
    _run_with(smoke_limits, tmp_path)
    assert sdk_websocket.global_stream_connections is stream_map
    assert asyncio.to_thread is to_thread


def test_the_ratified_limits_file_is_the_default_and_recorded_by_hash(
    tmp_path: Path, smoke_limits: Path
) -> None:
    _, _, document = _run_with(smoke_limits, tmp_path)
    assert document["settings"]["limits_file"] == "binance-limits-v1.toml"
    assert document["settings"]["limits_file_sha256"] == uds.sha256_lf(uds.DEFAULT_LIMITS_FILE)
    assert document["settings"]["smoke_limits_file_sha256"] == uds.sha256_lf(smoke_limits)


# --------------------------------------------------------------------------- #
# Scenarios.
# --------------------------------------------------------------------------- #


def test_a_silent_sdk_route_is_fail_and_the_run_still_cleans_up_and_exits_1(
    tmp_path: Path, smoke_limits: Path
) -> None:
    code, rig, document = _run_with(smoke_limits, tmp_path, uds.DryRunScenario(route_silent=True))
    steps = _steps(document)
    assert code == uds.EXIT_FAILED
    assert document["sdk_route_delivery"] == "FAIL"
    assert document["acceptance"]["c"]["result"] == "FAIL"
    assert steps["order_new_event"] == "FAILED"
    assert steps["order_canceled_event"] == "FAILED"
    assert steps["order_cancel"] == "PASSED"
    assert steps["account_after"] == "PASSED"
    assert document["end_state"] == "FLAT"
    assert steps["stop_and_delete_then_put"] == "PASSED"
    assert rig.fakes.orders.calls.count("place_entry") == 1


def test_a_drift_out_of_limits_aborts_with_exit_3_before_any_order(
    tmp_path: Path, smoke_limits: Path
) -> None:
    ahead = load_binance_limits(uds.DEFAULT_LIMITS_FILE).drift.ahead_limit_ms
    code, rig, document = _run_with(
        smoke_limits, tmp_path, uds.DryRunScenario(server_offset_ms=-(ahead + 1_000))
    )
    assert code == uds.EXIT_ABORTED
    assert document["outcome"] == "ABORTED_NO_ORDER"
    assert document["drift"]["within_limits"] is False
    assert _steps(document)["preflight"] == "FAILED"
    assert rig.fakes.orders.calls == []
    assert rig.fakes.clients == [] or all(not c.subscribe_frames for c in rig.fakes.clients)
    assert document["sdk_route_delivery"] == "NOT_RUN"


def test_preflight_refused_by_paused_gate(tmp_path: Path, smoke_limits: Path) -> None:
    built: list[uds.SmokeRig] = []

    def factory(config: uds.SmokeConfig) -> uds.SmokeRig:
        rig = uds.build_dry_run_rig(config)
        rig.rest_gate.record(ExchangeErrorCategory.RATE_LIMITED, None)
        built.append(rig)
        return rig

    code = uds.main(_argv(smoke_limits, tmp_path), environ={}, rig_factory=factory)
    _, document = _only_evidence(tmp_path)
    rig = built[0]
    assert code == uds.EXIT_ABORTED
    assert document["drift"]["measurement_failed"] is True
    assert document["drift"]["failure_type"] == "RateLimitPauseActive"
    assert rig.fakes.public_rest.calls["check_server_time"] == 0
    assert rig.fakes.orders.calls == []


def test_a_non_flat_end_state_is_manual_cleanup_required(
    tmp_path: Path, smoke_limits: Path
) -> None:
    code, _, document = _run_with(
        smoke_limits, tmp_path, uds.DryRunScenario(end_state_not_flat=True)
    )
    assert code == uds.EXIT_FAILED
    assert document["end_state"] == "MANUAL_CLEANUP_REQUIRED"
    assert _steps(document)["account_after"] == "FAILED"
    assert document["account_after"]["positions"]
    assert document["outcome"] == "FAILED"


def test_the_delete_then_put_observation_records_the_fake_class_and_code(
    tmp_path: Path, smoke_limits: Path
) -> None:
    code, rig, document = _run_with(
        smoke_limits, tmp_path, uds.DryRunScenario(put_after_delete_code=-1125)
    )
    observation = document["delete_then_put"]
    assert code == uds.EXIT_OK
    assert observation["outcome"] == "ERROR"
    assert observation["http_class"] == "BAD_REQUEST"
    assert observation["code"] == -1125
    assert observation["category"] == "INVALID_LISTEN_KEY"
    assert observation["delete_ok"] is True
    assert document["acceptance"]["f"]["result"] == "OBSERVED"
    calls = rig.fakes.rest_userdata.calls
    assert calls["close_user_data_stream"] == 1
    # one keepalive from the keepalive step, one PUT after the DELETE, and one from the
    # rebuild after the forced drop (the rebuild proves the stored key first; review CR-02)
    assert calls["keepalive_user_data_stream"] == 3


def test_the_forced_drop_goes_unknown_snapshot_live_with_a_measured_gap(
    tmp_path: Path, smoke_limits: Path
) -> None:
    _, rig, document = _run_with(smoke_limits, tmp_path)
    drop = document["forced_drop"]
    sequence = [entry["state"] for entry in drop["state_sequence_after_drop"]]
    assert sequence[:3] == ["UNKNOWN", "SYNCING", "LIVE"]
    assert drop["snapshot_count_after_drop"] >= 1
    assert isinstance(drop["gap_ms"], int)
    # the drop rebuilt the WebSocket client
    assert len(rig.fakes.clients) == 2
    assert document["acceptance"]["e"]["result"] == "PASS"


def test_the_dry_run_evidence_passes_the_checker_and_the_verdict(
    tmp_path: Path, smoke_limits: Path
) -> None:
    _, _, document = _run_with(smoke_limits, tmp_path)
    assert uds.check_smoke_evidence(document) == []
    verdict = uds.smoke_acceptance_verdict(document)
    assert {letter: verdict[letter]["result"] for letter in "abcdefgh"} == {
        "a": "PASS",
        "b": "PASS",
        "c": "PASS",
        "d": "PASS",
        "e": "PASS",
        "f": "OBSERVED",
        "g": "PASS",
        "h": "PASS",
    }
    assert all(entry["proof_class"] == "FAKE" for entry in verdict.values())
    assert document["acceptance"] == verdict


def test_an_account_not_flat_before_the_smoke_aborts_before_any_order(
    tmp_path: Path, smoke_limits: Path
) -> None:
    built: list[uds.SmokeRig] = []

    def factory(config: uds.SmokeConfig) -> uds.SmokeRig:
        rig = uds.build_dry_run_rig(config, uds.DryRunScenario(end_state_not_flat=True))
        rig.fakes.orders._placed = True  # a position exists before the smoke
        built.append(rig)
        return rig

    code = uds.main(_argv(smoke_limits, tmp_path), environ={}, rig_factory=factory)
    _, document = _only_evidence(tmp_path)
    assert code == uds.EXIT_ABORTED
    assert _steps(document)["account_before"] == "FAILED"
    assert "place_entry" not in built[0].fakes.orders.calls


# --------------------------------------------------------------------------- #
# Raw-frame capture.
# --------------------------------------------------------------------------- #


def test_fixtures_dir_writes_every_raw_payload_scrubbed_with_provenance(
    tmp_path: Path, smoke_limits: Path
) -> None:
    fixtures = tmp_path / "fixtures"
    code = uds.main(
        _argv(smoke_limits, tmp_path / "evidence", "--fixtures-dir", str(fixtures)), environ={}
    )
    assert code == uds.EXIT_OK
    names = sorted(p.name for p in fixtures.glob("*.json"))
    assert names == [
        "dry-run-001-ORDER_TRADE_UPDATE.json",
        "dry-run-002-ORDER_TRADE_UPDATE.json",
    ]
    payload = json.loads((fixtures / names[0]).read_text(encoding="utf-8"))
    assert payload["e"] == "ORDER_TRADE_UPDATE"
    assert payload["o"]["x"] == "NEW"
    provenance = (fixtures / "provenance.md").read_text(encoding="utf-8")
    assert all(f"`{name}`: FAKE_DRYRUN" in provenance for name in names)
    assert "RECORDED_DEMO" not in provenance
    _, document = _only_evidence(tmp_path / "evidence")
    assert document["fixtures"]["files"] == names


@pytest.mark.parametrize("spelling", ["root", "smoke", "dotdot", "relative", "symlink"])
def test_the_dry_run_refuses_the_recorded_demo_fixtures_directory(
    tmp_path: Path,
    smoke_limits: Path,
    monkeypatch: pytest.MonkeyPatch,
    spelling: str,
) -> None:
    # A stand-in directory: if the guard ever regresses, the dry run must not write into the
    # committed Demo evidence that `test_userdata_recorded_frames.py` pins (review WR-07).
    recorded = tmp_path / "recorded_demo"
    (recorded / "smoke").mkdir(parents=True)
    (recorded / "probe").mkdir()
    monkeypatch.setattr(uds, "RECORDED_DEMO_FIXTURES_DIR", recorded)
    if spelling == "root":
        target = str(recorded)
    elif spelling == "smoke":
        target = str(recorded / "smoke")
    elif spelling == "dotdot":
        target = str(recorded / "smoke" / ".." / "probe")
    elif spelling == "relative":
        monkeypatch.chdir(tmp_path)
        target = str(Path("recorded_demo") / "smoke")
    else:
        link = tmp_path / "link_to_recorded"
        try:
            link.symlink_to(recorded, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are not available on this platform")
        target = str(link)

    code = uds.main(
        _argv(smoke_limits, tmp_path / "evidence", "--fixtures-dir", target), environ={}
    )

    assert code == uds.EXIT_REFUSED
    # Nothing was written: only the two stand-in sub-directories exist.
    assert sorted(path.name for path in recorded.rglob("*")) == ["probe", "smoke"]


def test_the_real_recorded_demo_fixtures_directory_is_a_guarded_path() -> None:
    assert uds.RECORDED_DEMO_FIXTURES_DIR.name == "recorded_demo"
    assert uds.RECORDED_DEMO_FIXTURES_DIR.parts[-4:-1] == ("tests", "fixtures", "phase18")


def test_without_fixtures_dir_no_frame_is_written(tmp_path: Path, smoke_limits: Path) -> None:
    _, _, document = _run_with(smoke_limits, tmp_path)
    assert document["fixtures"]["status"] == "NOT_RUN"
    assert list(tmp_path.rglob("dry-run-*.json")) == []
    assert not list(tmp_path.rglob("provenance.md"))
