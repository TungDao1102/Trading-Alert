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

from tests.probe_fakes import write_probe_limits

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
    assert {request["operation"] for request in planned} == {
        "query_order",
        "query_algo_order",
        "cancel_order",
        "cancel_algo_order",
    }
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


def test_every_listed_status_is_accepted(valid: dict[str, Any]) -> None:
    assert dp.CASE_STATUSES == frozenset(
        {"OBSERVED", "NOT_OBSERVED", "NOT_REHEARSED", "SKIPPED_DRY_RUN", "ERROR"}
    )
    document = copy.deepcopy(valid)
    document["cases"][0] = _observed_case(document)
    document["mode"] = dp.MODE_EXECUTE
    document["proof_class"] = dp.PROOF_REAL_DEMO
    assert dp.check_probe_evidence(document) == []


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
