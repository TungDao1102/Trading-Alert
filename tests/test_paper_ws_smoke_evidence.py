"""Evidence schema, redaction and dry-run tests for the public-data WS smoke (Phase 16, plan 16-17).

Everything here is offline. The smoke recorder is driven in `--dry-run` mode over the SDK-shaped
fakes of `tests/paper_ws_fakes.py` and a virtual clock, so no test waits and no socket is opened.
The `--live` mode exists for the blocking-human plan 16-21 only; nothing in this file runs it
against Binance.
"""

from __future__ import annotations

import copy
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import paper_ws_smoke as smoke
from src.ops.redaction import Redactor

from tests.paper_ws_fakes import fresh_sdk_stream_map

MEASUREMENT_KEYS = (
    "connection_count",
    "arrival_latency_ms_by_interval",
    "clock_skew_ms",
    "rest_minute_lag",
    "forced_disconnect",
    "sdk_reconnect",
    "archive_fetch",
)


@pytest.fixture(autouse=True)
def _isolated_sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The SDK stream map is process-global (research D7): isolate it per test."""
    return fresh_sdk_stream_map(monkeypatch)


def _run(
    tmp_path: Path,
    *extra: str,
    dry: smoke.DryRunConfig | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run the recorder in dry-run mode and return (exit code, parsed evidence)."""
    argv = [
        "--dry-run",
        "--out",
        str(tmp_path),
        "--symbol",
        "BTCUSDT",
        "--intervals",
        "1m,1h",
        "--duration-seconds",
        "150",
        *extra,
    ]
    code = smoke.main(argv, environ=environ if environ is not None else {}, dry_run_config=dry)
    files = sorted(tmp_path.glob("16-PAPER-WS-SMOKE-*.json"))
    assert len(files) == 1, f"expected exactly one evidence file, found {files}"
    return code, json.loads(files[0].read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Task 1 (tracer): dry-run smoke through adapter and supervisor.
# --------------------------------------------------------------------------- #


def test_dry_run_writes_one_schema_valid_evidence_file(tmp_path: Path) -> None:
    code, evidence = _run(tmp_path)

    assert code == 0
    assert smoke.check_evidence_schema(evidence) == []
    assert evidence["mode"] == "dry-run"
    assert evidence["proof_class"] == "FAKE"
    assert evidence["sdk_version"] == importlib.metadata.version(
        "binance-sdk-derivatives-trading-usds-futures"
    )
    assert evidence["binance_common_version"] == importlib.metadata.version("binance-common")
    assert evidence["started_at_utc"].endswith("Z")
    assert evidence["ws_subscribe"]["status"] == "OK"
    assert sorted(evidence["ws_subscribe"]["subscribed_streams"]) == [
        "btcusdt@kline_1h",
        "btcusdt@kline_1m",
    ]
    # Over 150 virtual seconds from 11:59:30Z: 1m closes at 12:00 and 12:01, 1h closes at 12:00.
    assert evidence["closed_events_by_interval"] == {"1h": 1, "1m": 2}
    assert evidence["open_events_dropped"] >= 1
    for key in MEASUREMENT_KEYS:
        assert evidence[key]["status"] in smoke.ALLOWED_STATUSES


def test_a_secret_in_a_recorded_error_is_scrubbed_before_the_write(tmp_path: Path) -> None:
    secret_url = "https://user:hunter2hunter2@example.invalid/stream"
    token = "123456789:" + "A" * 35
    dry = smoke.DryRunConfig(
        connect_error=ConnectionError(f"connect failed for {secret_url} token {token}")
    )

    code, evidence = _run(tmp_path, dry=dry)
    text = next(tmp_path.glob("16-PAPER-WS-SMOKE-*.json")).read_text(encoding="utf-8")

    assert code == 1, "a blocked subscribe is a failed smoke"
    assert evidence["ws_subscribe"]["status"] == "BLOCKED"
    assert "hunter2hunter2" not in text
    assert token not in text
    assert Redactor.from_environ({}).scrub(text) == text, "the written file passes the secret scan"
    assert smoke.check_evidence_schema(evidence) == []


def test_an_environment_secret_value_is_scrubbed_from_the_evidence(tmp_path: Path) -> None:
    dry = smoke.DryRunConfig(connect_error=ConnectionError("rejected key SUPERSECRETVALUE12345"))

    _code, _evidence = _run(tmp_path, dry=dry, environ={"EXAMPLE_API_KEY": "SUPERSECRETVALUE12345"})
    text = next(tmp_path.glob("16-PAPER-WS-SMOKE-*.json")).read_text(encoding="utf-8")

    assert "SUPERSECRETVALUE12345" not in text
    assert "[REDACTED]" in text


class _LeakyRedactor:
    """A redactor whose output changes on every call: the post-write scan must notice."""

    def __init__(self) -> None:
        self.calls = 0

    def scrub(self, text: str) -> str:
        self.calls += 1
        return text + (" " * self.calls)


def test_the_post_write_scan_removes_a_file_that_fails_it(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="post-write secret scan"):
        smoke.write_evidence({"a": 1}, tmp_path, "stem", _LeakyRedactor())  # type: ignore[arg-type]

    assert list(tmp_path.iterdir()) == [], "no evidence file, no temp file may remain"


def test_closed_events_count_only_bars_that_reached_the_supervisor_sink(tmp_path: Path) -> None:
    dry = smoke.DryRunConfig(duplicate_closed_events=True)

    _code, evidence = _run(tmp_path, dry=dry)

    # Every closed event is delivered twice; the supervisor drops the duplicate, so the count is
    # the number of distinct closes. Forming updates are counted as dropped, never as closed.
    assert evidence["closed_events_by_interval"] == {"1h": 1, "1m": 2}
    assert evidence["open_events_dropped"] >= 1


# --------------------------------------------------------------------------- #
# Task 1: schema completeness.
# --------------------------------------------------------------------------- #


def test_a_step_that_was_not_requested_is_not_run_never_absent(tmp_path: Path) -> None:
    _code, evidence = _run(tmp_path)

    assert evidence["forced_disconnect"]["status"] == "NOT_RUN"
    assert evidence["rest_minute_lag"]["status"] == "NOT_RUN"
    for key in MEASUREMENT_KEYS:
        assert key in evidence


@pytest.mark.parametrize("missing", MEASUREMENT_KEYS)
def test_the_schema_validator_rejects_a_missing_measurement_key(
    tmp_path: Path, missing: str
) -> None:
    _code, evidence = _run(tmp_path)
    broken = copy.deepcopy(evidence)
    del broken[missing]

    problems = smoke.check_evidence_schema(broken)

    assert problems, f"a file without {missing} must be rejected"
    assert any(missing in problem for problem in problems)


def test_the_schema_validator_rejects_an_unknown_status_and_a_missing_status(
    tmp_path: Path,
) -> None:
    _code, evidence = _run(tmp_path)
    wrong = copy.deepcopy(evidence)
    wrong["clock_skew_ms"]["status"] = "MAYBE"
    absent = copy.deepcopy(evidence)
    del absent["archive_fetch"]["status"]

    assert any("clock_skew_ms" in p for p in smoke.check_evidence_schema(wrong))
    assert any("archive_fetch" in p for p in smoke.check_evidence_schema(absent))


def test_the_schema_validator_accepts_every_combination_of_ok_and_not_run(
    tmp_path: Path,
) -> None:
    _code, evidence = _run(tmp_path)
    for status in ("OK", "NOT_RUN", "ERROR"):
        variant = copy.deepcopy(evidence)
        for key in MEASUREMENT_KEYS:
            variant[key]["status"] = status
        assert smoke.check_evidence_schema(variant) == []
