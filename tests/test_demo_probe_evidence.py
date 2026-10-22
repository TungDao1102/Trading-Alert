"""The Demo probe evidence contract (plan 18-17): the dry-run file, the schema checker.

The dry run writes `demo-probe-DRYRUN-<UTC stamp>.json` under `tmp_path` with every network
entry point patched to fail; `check_probe_evidence` has a negative control per rule. Nothing
here reaches Binance; every value is FAKE or TEST_ONLY.
"""

from __future__ import annotations

import asyncio
import copy
import json
import socket
import time
from pathlib import Path
from typing import Any

import pytest
import requests
from scripts import demo_probe as dp
from src.adapters import binance_client

from tests.probe_fakes import (
    CASE_QUERY_OPERATIONS,
    MUTATING_OPERATIONS,
    FakeProbePort,
    write_probe_limits,
)
from tests.support.virtual_time import VirtualTime

_LOOPBACK = {"127.0.0.1", "::1"}


class _Reached(AssertionError):
    """Raised by every patched network, sleep or SDK entry point."""


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch real sleeps, name lookups, non-loopback connects, HTTP and the SDK factory to fail.

    `socket.socket` is replaced by a subclass that refuses non-loopback connects (the Windows
    event loop builds its self-pipe from a loopback socket pair, plan 18-16 deviation 1).
    """
    reached: list[str] = []
    real_socket = socket.socket

    class _LoopbackOnlySocket(real_socket):  # type: ignore[misc, valid-type]
        def connect(self, address: Any) -> None:
            if not (isinstance(address, tuple) and address[0] in _LOOPBACK):
                reached.append("socket.connect")
                raise _Reached("socket connect to a network host")
            super().connect(address)

    def _fail(name: str) -> Any:
        def _raise(*args: Any, **kwargs: Any) -> Any:
            reached.append(name)
            raise _Reached(name)

        return _raise

    async def _no_async_sleep(*args: Any, **kwargs: Any) -> None:
        reached.append("asyncio.sleep")
        raise _Reached("asyncio.sleep")

    monkeypatch.setattr(socket, "socket", _LoopbackOnlySocket)
    monkeypatch.setattr(socket, "getaddrinfo", _fail("getaddrinfo"))
    monkeypatch.setattr(socket, "create_connection", _fail("create_connection"))
    monkeypatch.setattr(requests.Session, "request", _fail("requests"))
    monkeypatch.setattr(binance_client, "build_sdk_client", _fail("build_sdk_client"))
    monkeypatch.setattr(time, "sleep", _fail("time.sleep"))
    monkeypatch.setattr(asyncio, "sleep", _no_async_sleep)
    return reached


def _dry_run(tmp_path: Path, *extra: str, optional: tuple[str, ...] = ()) -> tuple[int, Path]:
    limits = write_probe_limits(tmp_path, optional=optional)
    evidence = tmp_path / "evidence"
    code = dp.main(
        [
            "--environment",
            "DEMO",
            "--probe-limits-file",
            str(limits),
            "--evidence-dir",
            str(evidence),
            *extra,
        ],
        environ={},
    )
    return code, evidence


def _load_only(directory: Path) -> dict[str, Any]:
    files = sorted(directory.glob("demo-probe-*.json"))
    assert len(files) == 1, files
    document: dict[str, Any] = json.loads(files[0].read_text(encoding="utf-8"))
    return document


# --------------------------------------------------------------------------- #
# The dry-run evidence file.
# --------------------------------------------------------------------------- #


def test_the_dry_run_writes_a_valid_fake_evidence_file_offline(
    tmp_path: Path, offline: list[str]
) -> None:
    code, evidence = _dry_run(tmp_path, optional=("stream_gap",))
    assert code == dp.EXIT_OK
    assert offline == []
    files = sorted(evidence.glob("demo-probe-*.json"))
    assert [f.name for f in files] == ["demo-probe-DRYRUN-20261016T120000Z.json"]
    document = _load_only(evidence)
    assert dp.check_probe_evidence(document) == []
    assert document["schema"] == dp.EVIDENCE_SCHEMA
    assert document["mode"] == dp.MODE_DRY_RUN
    assert document["proof_class"] == dp.PROOF_FAKE
    assert "demo-observed, not mainnet" in document["label"]
    assert document["d055"]["status"].startswith("OPEN")
    assert document["environment"] == "DEMO"
    raw = files[0].read_bytes()
    assert b"\r\n" not in raw


def test_the_dry_run_records_planned_requests_only(tmp_path: Path, offline: list[str]) -> None:
    _, evidence = _dry_run(tmp_path)
    document = _load_only(evidence)
    planned = [request for item in document["cases"] for request in item["planned_requests"]]
    assert planned, "the read-only cases plan their requests"
    operations = {request["operation"] for request in planned}
    # the read-only cases (plan 18-17) plan these four; the cases that send orders (plan
    # 18-23) add order placements and per-id queries and cancels, nothing else
    assert {"query_order", "query_algo_order", "cancel_order", "cancel_algo_order"} <= operations
    assert operations <= MUTATING_OPERATIONS | CASE_QUERY_OPERATIONS
    assert document["live_port_calls"] == 0
    for item in document["cases"]:
        assert item["status"] == dp.NOT_REHEARSED
        assert item["observations"] == []


def test_the_dry_run_never_overwrites_an_earlier_file(tmp_path: Path, offline: list[str]) -> None:
    _dry_run(tmp_path)
    _dry_run(tmp_path)
    names = sorted(p.name for p in (tmp_path / "evidence").glob("demo-probe-*.json"))
    assert names == [
        "demo-probe-DRYRUN-20261016T120000Z-2.json",
        "demo-probe-DRYRUN-20261016T120000Z.json",
    ]


def test_a_dry_run_never_writes_into_the_recorded_demo_fixtures(
    tmp_path: Path, offline: list[str]
) -> None:
    code, evidence = _dry_run(tmp_path, "--fixtures-dir", str(dp.RECORDED_DEMO_FIXTURES_DIR))
    assert code == dp.EXIT_REFUSED
    assert not evidence.exists()


# --------------------------------------------------------------------------- #
# check_probe_evidence: a negative control per rule.
# --------------------------------------------------------------------------- #


@pytest.fixture
def valid(tmp_path: Path, offline: list[str]) -> dict[str, Any]:
    _, evidence = _dry_run(tmp_path)
    document = _load_only(evidence)
    assert dp.check_probe_evidence(document) == []
    return document


def _observed_case(document: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(document["cases"][0])
    item["status"] = dp.OBSERVED
    item["observations"] = [
        {
            "operation": "query_order",
            "ok": False,
            "summary": {},
            "error": {
                "http_class": "BAD_REQUEST",
                "code": -2013,
                "retry_after_seconds": None,
                "category": "ORDER_ABSENT",
                "message": "FAKE",
            },
        }
    ]
    item["reason"] = None
    return item


@pytest.mark.parametrize("key", dp.REQUIRED_TOP_LEVEL_KEYS)
def test_a_missing_top_level_key_is_a_problem(valid: dict[str, Any], key: str) -> None:
    document = copy.deepcopy(valid)
    del document[key]
    assert any(key in problem for problem in dp.check_probe_evidence(document))


def test_the_required_keys_are_the_plan_list() -> None:
    assert set(dp.REQUIRED_TOP_LEVEL_KEYS) == {
        "schema",
        "mode",
        "proof_class",
        "label",
        "environment",
        "symbol",
        "started_utc",
        "finished_utc",
        "account_before",
        "account_after",
        "cases",
        "cleanup",
        "d055",
        "outcome",
    }


def test_a_non_object_is_a_problem() -> None:
    assert dp.check_probe_evidence([]) == ["evidence is not an object"]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema", "demo-probe-evidence/schema-0"),
        ("proof_class", "REAL"),
        ("mode", "live"),
        ("label", "demo results"),
        ("label", "mainnet"),
    ],
)
def test_a_wrong_header_value_is_a_problem(valid: dict[str, Any], key: str, value: str) -> None:
    document = copy.deepcopy(valid)
    document[key] = value
    assert dp.check_probe_evidence(document) != []


def test_a_proof_class_that_does_not_match_the_mode_is_a_problem(valid: dict[str, Any]) -> None:
    document = copy.deepcopy(valid)
    document["proof_class"] = dp.PROOF_REAL_DEMO
    assert any("proof_class" in p for p in dp.check_probe_evidence(document))


def test_an_unknown_case_id_is_a_problem(valid: dict[str, Any]) -> None:
    document = copy.deepcopy(valid)
    document["cases"][0]["case_id"] = "invented_case"
    assert any("invented_case" in p for p in dp.check_probe_evidence(document))


def test_a_repeated_case_id_is_a_problem(valid: dict[str, Any]) -> None:
    document = copy.deepcopy(valid)
    document["cases"].append(copy.deepcopy(document["cases"][0]))
    assert any("more than once" in p for p in dp.check_probe_evidence(document))


def test_cases_out_of_case_order_are_a_problem(valid: dict[str, Any]) -> None:
    document = copy.deepcopy(valid)
    document["cases"].reverse()
    assert any("CASE_ORDER" in p for p in dp.check_probe_evidence(document))


@pytest.mark.parametrize("status", ["PASSED", "observed", "", None])
def test_a_case_status_outside_the_vocabulary_is_a_problem(
    valid: dict[str, Any], status: object
) -> None:
    document = copy.deepcopy(valid)
    document["cases"][0]["status"] = status
    assert any("status" in p for p in dp.check_probe_evidence(document))


def test_the_status_vocabulary_is_the_plan_list() -> None:
    assert dp.CASE_STATUSES == frozenset(
        {"OBSERVED", "NOT_OBSERVED", "NOT_REHEARSED", "SKIPPED_DRY_RUN", "ERROR"}
    )


@pytest.mark.parametrize("status", sorted(dp.CASE_STATUSES))
def test_every_listed_status_is_accepted(valid: dict[str, Any], status: str) -> None:
    document = copy.deepcopy(valid)
    document["mode"] = dp.MODE_EXECUTE
    document["proof_class"] = dp.PROOF_REAL_DEMO
    item = _observed_case(document)
    if status != dp.OBSERVED:
        item["status"] = status
        item["observations"] = []
        item["reason"] = "TEST_ONLY reason"
    document["cases"][0] = item
    assert dp.check_probe_evidence(document) == []
    # The status is what is checked: the same case with a status outside the list is refused.
    item["status"] = "NOT_A_STATUS"
    assert any("status" in p for p in dp.check_probe_evidence(document))


def test_an_observed_case_without_observations_is_a_problem(valid: dict[str, Any]) -> None:
    document = copy.deepcopy(valid)
    item = _observed_case(document)
    item["observations"] = []
    document["cases"][0] = item
    assert any("without observations" in p for p in dp.check_probe_evidence(document))


def test_an_observation_without_the_answer_facts_is_a_problem(valid: dict[str, Any]) -> None:
    document = copy.deepcopy(valid)
    item = _observed_case(document)
    del item["observations"][0]["error"]["code"]
    document["cases"][0] = item
    assert any("code" in p for p in dp.check_probe_evidence(document))


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_a_not_observed_case_without_a_reason_is_a_problem(
    valid: dict[str, Any], reason: object
) -> None:
    document = copy.deepcopy(valid)
    document["cases"][0]["status"] = dp.NOT_OBSERVED
    document["cases"][0]["reason"] = reason
    assert any("without a reason" in p for p in dp.check_probe_evidence(document))


@pytest.mark.parametrize("status", ["CLOSED: decided", "open", "", None, "D055 OPEN"])
def test_d055_must_stay_open(valid: dict[str, Any], status: object) -> None:
    document = copy.deepcopy(valid)
    document["d055"]["status"] = status
    assert any("d055" in p for p in dp.check_probe_evidence(document))


def test_d055_must_be_an_object(valid: dict[str, Any]) -> None:
    document = copy.deepcopy(valid)
    document["d055"] = "OPEN"
    assert any("d055" in p for p in dp.check_probe_evidence(document))


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-16T12:00:00",
        "2026-10-16T19:00:00+07:00",
        "yesterday",
        None,
        12,
    ],
)
@pytest.mark.parametrize("key", ["started_utc", "finished_utc"])
def test_a_time_that_is_not_aware_utc_iso_text_is_a_problem(
    valid: dict[str, Any], key: str, value: object
) -> None:
    document = copy.deepcopy(valid)
    document[key] = value
    assert any(key in p for p in dp.check_probe_evidence(document))


def test_a_finish_before_the_start_is_a_problem(valid: dict[str, Any]) -> None:
    document = copy.deepcopy(valid)
    document["started_utc"] = "2026-10-16T12:00:05+00:00"
    document["finished_utc"] = "2026-10-16T12:00:00+00:00"
    assert any("before" in p for p in dp.check_probe_evidence(document))


def test_the_dry_run_cases_cover_case_order(valid: dict[str, Any]) -> None:
    ids = [item["case_id"] for item in valid["cases"]]
    assert ids == list(dp.REQUIRED_CASES)


# --------------------------------------------------------------------------- #
# Executed runs on fakes (Task 2): frames, fixtures and the acceptance verdict.
# --------------------------------------------------------------------------- #


def _config(tmp_path: Path, *extra: str) -> dp.ProbeConfig:
    limits = write_probe_limits(tmp_path)
    return dp.parse_config(
        [
            "--environment",
            "DEMO",
            "--probe-limits-file",
            str(limits),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--execute",
            *extra,
        ]
    )


def _instant_rig(port: Any, *, real: bool = True, stream: Any = None) -> dp.ProbeRig:
    clock = VirtualTime()

    async def sleep(seconds: int) -> None:
        clock.sleeps.append(seconds)
        await clock.advance(seconds)

    return dp.ProbeRig(port=port, clock=clock.now, sleep=sleep, real=real, stream=stream)


async def _observed(context: dp.CaseContext) -> dp.CaseResult:
    probed = context.recorder.next_client_id("test")
    answer = await context.rig.port.query_order(
        symbol=context.config.symbol, client_order_id=probed
    )
    return dp.CaseResult(status=dp.OBSERVED, observations=(answer,))


async def _not_observed(context: dp.CaseContext) -> dp.CaseResult:
    return dp.CaseResult(status=dp.NOT_OBSERVED, reason="FAKE: a partial fill was not induced")


async def _executed_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    handlers = {
        case_id: (_not_observed if case_id == "partial_fill" else _observed)
        for case_id in dp.REQUIRED_CASES
    }
    monkeypatch.setattr(dp, "CASE_HANDLERS", handlers)
    config = _config(tmp_path)
    recorder = dp.ProbeRecorder()
    code = await dp.run_probe(config, _instant_rig(FakeProbePort()), recorder)
    assert code == dp.EXIT_OK
    return recorder.document(config)


async def test_an_executed_fake_run_passes_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = await _executed_document(tmp_path, monkeypatch)
    assert dp.check_probe_evidence(document) == []
    verdict = dp.probe_acceptance_verdict(document)
    assert verdict["overall"]["result"] == dp.VERDICT_PASS, verdict
    for case_id in dp.REQUIRED_CASES:
        assert verdict[case_id]["result"] == dp.VERDICT_PASS
    assert "NOT_OBSERVED" in verdict["partial_fill"]["reason"]


def test_the_dry_run_verdict_reports_every_case_not_rehearsed(valid: dict[str, Any]) -> None:
    verdict = dp.probe_acceptance_verdict(valid)
    assert verdict["overall"]["result"] == dp.VERDICT_FAIL
    for case_id in dp.REQUIRED_CASES:
        assert verdict[case_id]["result"] == dp.VERDICT_FAIL
        assert "NOT_REHEARSED" in verdict[case_id]["reason"]
    assert verdict["proof_class"]["result"] == dp.VERDICT_FAIL
    assert all(entry["proof_class"] == dp.PROOF_FAKE for entry in verdict.values())


def test_the_written_dry_run_carries_the_verdict(valid: dict[str, Any]) -> None:
    assert valid["acceptance"] == dp.probe_acceptance_verdict(
        {k: v for k, v in valid.items() if k != "acceptance"}
    )


def _break_observations(document: dict[str, Any]) -> str:
    document["cases"][0]["observations"] = []
    return str(document["cases"][0]["case_id"])


def _break_answer(document: dict[str, Any]) -> str:
    del document["cases"][0]["observations"][0]["error"]["category"]
    return str(document["cases"][0]["case_id"])


def _break_reason(document: dict[str, Any]) -> str:
    item = next(c for c in document["cases"] if c["case_id"] == "partial_fill")
    item["reason"] = ""
    return "partial_fill"


def _drop_case(document: dict[str, Any]) -> str:
    document["cases"] = [c for c in document["cases"] if c["case_id"] != "closeposition_stop_flat"]
    return "closeposition_stop_flat"


def _error_case(document: dict[str, Any]) -> str:
    document["cases"][1]["status"] = dp.ERROR
    document["cases"][1]["reason"] = "no handler registered"
    return str(document["cases"][1]["case_id"])


@pytest.mark.parametrize(
    "breaker", [_break_observations, _break_answer, _break_reason, _drop_case, _error_case]
)
async def test_a_case_rule_violation_fails_that_case_and_the_overall_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, breaker: Any
) -> None:
    document = await _executed_document(tmp_path, monkeypatch)
    case_id = breaker(document)
    verdict = dp.probe_acceptance_verdict(document)
    assert verdict[case_id]["result"] == dp.VERDICT_FAIL
    assert verdict["overall"]["result"] == dp.VERDICT_FAIL


async def test_an_enabled_optional_case_is_required_by_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = await _executed_document(tmp_path, monkeypatch)
    document["settings"]["optional_cases"]["stream_gap"] = True
    verdict = dp.probe_acceptance_verdict(document)
    assert verdict["stream_gap_during_case"]["result"] == dp.VERDICT_FAIL
    assert verdict["overall"]["result"] == dp.VERDICT_FAIL


async def test_an_enabled_capture_case_is_required_by_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quick task 261021-sj0: each of the ten new keys makes its case expected."""
    document = await _executed_document(tmp_path, monkeypatch)
    for key, case_id in dp.OPTIONAL_CASES.items():
        if case_id not in dp.CAPTURE_CASES:
            continue
        assert case_id not in dp.probe_acceptance_verdict(document)  # absent key: not expected
        document["settings"]["optional_cases"][key] = True
        verdict = dp.probe_acceptance_verdict(document)
        assert verdict[case_id]["result"] == dp.VERDICT_FAIL, case_id  # enabled but not run
        assert verdict["overall"]["result"] == dp.VERDICT_FAIL


def test_the_dry_run_settings_carry_the_new_owner_keys(tmp_path: Path, offline: list[str]) -> None:
    from tests.probe_fakes import (
        TEST_ONLY_GTD_EXPIRY_WAIT_SECONDS,
        TEST_ONLY_GTD_LIFETIME_SECONDS,
        TEST_ONLY_NEAR_TRIGGER_FRACTION,
    )

    code, evidence = _dry_run(tmp_path, optional=tuple(dp.OPTIONAL_CASES))
    assert code == dp.EXIT_OK and offline == []
    document = _load_only(evidence)
    assert dp.check_probe_evidence(document) == []
    settings = document["settings"]
    assert settings["near_trigger_fraction"] == TEST_ONLY_NEAR_TRIGGER_FRACTION
    assert settings["gtd_lifetime_seconds"] == TEST_ONLY_GTD_LIFETIME_SECONDS
    assert settings["gtd_expiry_wait_seconds"] == TEST_ONLY_GTD_EXPIRY_WAIT_SECONDS
    assert all(settings["optional_cases"][key] is True for key in dp.OPTIONAL_CASES)
    assert document["schema"] == "demo-probe-evidence/schema-1"  # the schema id is unchanged
    assert [item["case_id"] for item in document["cases"]] == list(dp.CASE_ORDER)
    for item in document["cases"]:
        assert item["status"] == dp.NOT_REHEARSED
    assert [
        fixture for item in document["cases"] for fixture in item.get("rest_fixtures", [])
    ] == []


def test_a_dry_run_without_the_new_keys_keeps_the_phase18_settings_and_cases(
    tmp_path: Path, offline: list[str]
) -> None:
    code, evidence = _dry_run(tmp_path)
    assert code == dp.EXIT_OK and offline == []
    document = _load_only(evidence)
    assert document["settings"]["near_trigger_fraction"] is None
    assert document["settings"]["gtd_lifetime_seconds"] is None
    assert document["settings"]["gtd_expiry_wait_seconds"] is None
    assert set(document["settings"]["optional_cases"]) == set(list(dp.OPTIONAL_CASES)[:3])
    assert document["case_order"] == list(dp.REQUIRED_CASES)


@pytest.mark.parametrize(
    ("path", "value", "rule"),
    [
        (("cleanup", "final", "status"), dp.CLEANUP_FAILED_STATUS, "cleanup"),
        (("cleanup", "final", "remaining", "open_orders"), 1, "cleanup"),
        (("cleanup", "final", "remaining", "open_algo_orders"), 2, "cleanup"),
        (
            ("cleanup", "final", "remaining", "positions"),
            [{"symbol": "BTCUSDT", "position_side": "BOTH", "position_amt": "0.002"}],
            "cleanup",
        ),
        (("account_before",), None, "account_state"),
        (("account_after",), {"status": "NOT_RUN"}, "account_state"),
        (("label",), "results", "label_and_d055"),
        (("d055", "status"), "CLOSED", "label_and_d055"),
        (("proof_class",), dp.PROOF_FAKE, "proof_class"),
        (("schema",), "other", "evidence"),
    ],
)
async def test_a_rule_violation_fails_its_rule_and_the_overall_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: tuple[str, ...],
    value: Any,
    rule: str,
) -> None:
    document = await _executed_document(tmp_path, monkeypatch)
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    verdict = dp.probe_acceptance_verdict(document)
    assert verdict[rule]["result"] == dp.VERDICT_FAIL, verdict[rule]
    assert verdict["overall"]["result"] == dp.VERDICT_FAIL


class _FakeStream:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.started = 0
        self.stopped = 0

    async def start(self) -> None:
        self.started += 1
        if self.fail:
            raise RuntimeError("FAKE: no LIVE")

    async def stop(self) -> None:
        self.stopped += 1


async def _emitting(context: dp.CaseContext) -> dp.CaseResult:
    port = context.rig.port
    assert isinstance(port, FakeProbePort)
    port.emit_frame(
        {"event_type": "OrderUpdateEvent", "execution_type": "NEW"},
        raw={"e": "ORDER_TRADE_UPDATE", "o": {"x": "NEW", "c": "dprobe-FAKE"}},
    )
    port.emit_state("LIVE")
    return await _observed(context)


async def test_each_case_records_its_frames_and_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dp,
        "CASE_HANDLERS",
        {"get_order_not_found": _emitting, "get_algo_order_not_found": _observed},
    )
    fixtures = tmp_path / "fixtures"
    config = _config(
        tmp_path,
        "--only",
        "get_order_not_found,get_algo_order_not_found",
        "--fixtures-dir",
        str(fixtures),
    )
    stream = _FakeStream()
    recorder = dp.ProbeRecorder()
    await dp.run_probe(config, _instant_rig(FakeProbePort(), stream=stream), recorder)
    document = recorder.document(config)
    first, second = document["cases"]
    assert first["frames"]["status"] == dp.OBSERVED
    assert first["frames"]["events"] == [
        {"event_type": "OrderUpdateEvent", "execution_type": "NEW"}
    ]
    assert first["frames"]["stream_states"] == ["LIVE"]
    fixture_name = "get_order_not_found-001-ORDER_TRADE_UPDATE.json"
    assert first["frames"]["fixtures"] == [fixture_name]
    assert second["frames"]["events"] == []
    written = json.loads((fixtures / fixture_name).read_text(encoding="utf-8"))
    assert written["o"]["x"] == "NEW"
    provenance = (fixtures / "provenance.md").read_text(encoding="utf-8")
    assert f"`{fixture_name}`: RECORDED_DEMO" in provenance
    assert stream.started == 1 and stream.stopped == 1
    assert document["stream"]["status"] == "STARTED"


async def test_a_stream_that_does_not_start_leaves_every_frame_field_not_observed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dp, "CASE_HANDLERS", {"get_order_not_found": _observed})
    config = _config(tmp_path, "--only", "get_order_not_found")
    stream = _FakeStream(fail=True)
    recorder = dp.ProbeRecorder()
    code = await dp.run_probe(config, _instant_rig(FakeProbePort(), stream=stream), recorder)
    document = recorder.document(config)
    (item,) = document["cases"]
    assert item["status"] == dp.OBSERVED
    assert item["frames"]["status"] == dp.NOT_OBSERVED
    assert "did not start" in item["frames"]["reason"]
    assert document["stream"]["status"] == "NOT_STARTED"
    assert code == dp.EXIT_OK
