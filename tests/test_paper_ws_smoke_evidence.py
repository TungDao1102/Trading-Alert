"""Evidence schema, redaction and dry-run tests for the public-data WS smoke (Phase 16, plan 16-17).

Everything here is offline. The smoke recorder is driven in `--dry-run` mode over the SDK-shaped
fakes of `tests/paper_ws_fakes.py` and a virtual clock, so no test waits and no socket is opened.
The `--live` mode exists for the blocking-human plan 16-21 only; nothing in this file runs it
against Binance.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import importlib.metadata
import inspect
import json
import types
from datetime import timedelta
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from binance_common import constants as sdk_constants
from binance_common import websocket as sdk_websocket
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


# --------------------------------------------------------------------------- #
# Task 2: live-mode guards, forced disconnect (unsolicited path), SDK rotation, archive fetch.
# --------------------------------------------------------------------------- #

SCRIPT_PATH = Path(smoke.__file__)
SRC_ROOT = Path(smoke.__file__).resolve().parents[1] / "src"
SDK_ROTATION_NAME = "AUTO_RECONNECT_INTERVAL_SECONDS"


def _run_rig(
    *extra: str,
    dry: smoke.DryRunConfig | None = None,
    base: tuple[str, ...] = ("--intervals", "1m,1h", "--duration-seconds", "150"),
    out: Path | None = None,
) -> tuple[smoke.SmokeRig, dict[str, Any], int]:
    """Build the dry-run rig explicitly so a test can look at the fakes after the run."""
    config = smoke.parse_config(
        ["--dry-run", "--out", str(out if out is not None else Path(".")), *base, *extra]
    )
    rig = smoke.build_dry_run_rig(config, dry or smoke.DryRunConfig())
    try:
        evidence, code = asyncio.run(smoke.run_smoke(config, rig))
    finally:
        rig.cleanup()
    return rig, evidence, code


def test_live_refuses_when_any_binance_variable_is_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = smoke.main(
        ["--live", "--i-am-on-the-connected-machine", "--out", str(tmp_path)],
        environ={"BINANCE_API_KEY": "VALUE-THAT-MUST-NEVER-BE-PRINTED-123"},
    )

    captured = capsys.readouterr()
    assert code == 3
    assert "trade-capable variable present: BINANCE_API_KEY" in captured.err
    assert "VALUE-THAT-MUST-NEVER-BE-PRINTED-123" not in captured.err + captured.out
    assert list(tmp_path.iterdir()) == [], "refused before anything was written"


def test_live_needs_the_explicit_operator_flag(tmp_path: Path) -> None:
    code = smoke.main(["--live", "--out", str(tmp_path)], environ={})

    assert code == 2
    assert list(tmp_path.iterdir()) == []


def test_forced_disconnect_goes_through_the_unsolicited_path_and_is_proven(
    tmp_path: Path,
) -> None:
    rig, evidence, code = _run_rig("--force-disconnect-after-seconds", "20", out=tmp_path)

    forced = evidence["forced_disconnect"]
    assert code == 0
    assert smoke.check_evidence_schema(evidence) == []
    assert forced["status"] == "OK"
    assert forced["method"] == "transport-drop"
    assert forced["path_exercised"] == "unsolicited"
    assert forced["close_api_calls"] == 0
    assert sorted(forced["stale_stream_entries_before_rebuild"]) == [
        "btcusdt@kline_1h",
        "btcusdt@kline_1m",
    ]
    assert forced["disconnected_at_utc"] == "2026-10-09T11:59:50.000Z"
    assert forced["resumed_at_utc"] is not None
    assert forced["closed_events_after_resume"] >= 1
    assert isinstance(forced["gap_records"], list)
    assert forced["outage_statement"] == "no bar closed during the outage"
    assert smoke.check_forced_disconnect(evidence).ok
    clients = rig.fakes.clients  # type: ignore[union-attr]
    assert len(clients) == 2, "one rebuild produced one replacement client"
    # The only close of the dead client is the adapter's own release inside rebuild; the script
    # itself never called the user-initiated close during the step (close_api_calls == 0).
    assert clients[0].close_calls == 1


def test_closed_events_resume_on_the_replacement_client_after_the_drop(tmp_path: Path) -> None:
    _rig, evidence, _code = _run_rig("--force-disconnect-after-seconds", "20", out=tmp_path)

    # 1m closes at 12:00 and 12:01 and 1h at 12:00 all arrive after the 11:59:50 drop.
    assert evidence["forced_disconnect"]["closed_events_after_resume"] == 3
    assert evidence["closed_events_by_interval"] == {"1h": 1, "1m": 2}


def test_the_archive_fetch_records_url_status_rows_and_sha256(tmp_path: Path) -> None:
    _rig, evidence, code = _run_rig(out=tmp_path)

    fetch = evidence["archive_fetch"]
    assert code == 0
    assert fetch["status"] == "OK"
    assert fetch["url"].startswith(
        "https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1h/BTCUSDT-1h-"
    )
    assert fetch["url"].endswith(".zip")
    assert fetch["http_status"] == 200
    assert fetch["rows"] == 24
    assert len(fetch["sha256"]) == 64
    assert fetch["error"] is None


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("not_found", "ArchiveNotFound"), ("network_error", "ArchiveError")],
)
def test_an_archive_fetch_error_is_recorded_not_raised(
    tmp_path: Path, mode: str, expected: str
) -> None:
    _rig, evidence, code = _run_rig(out=tmp_path, dry=smoke.DryRunConfig(archive_mode=mode))

    fetch = evidence["archive_fetch"]
    assert fetch["status"] == "ERROR"
    assert expected in fetch["error"]
    assert fetch["rows"] is None
    assert code == 1
    assert smoke.check_evidence_schema(evidence) == []


def test_no_archive_fetch_flag_leaves_the_step_not_run(tmp_path: Path) -> None:
    _rig, evidence, _code = _run_rig("--no-archive-fetch", out=tmp_path)

    assert evidence["archive_fetch"]["status"] == "NOT_RUN"


def _imported_modules_and_names(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return modules, names


def test_the_script_imports_no_execution_module_and_never_names_the_order_adapter() -> None:
    modules, names = _imported_modules_and_names(SCRIPT_PATH)

    assert not [m for m in modules if m == "src.execution" or m.startswith("src.execution.")]
    assert "BinanceUsdmAdapter" not in names
    assert "src.adapters.binance_usdm" not in modules


# -- negative control: the wrong close path must be caught --------------------------------- #


async def test_the_user_initiated_close_path_is_not_accepted_as_proof(tmp_path: Path) -> None:
    config = smoke.parse_config(
        ["--dry-run", "--out", str(tmp_path), "--intervals", "1m,1h", "--duration-seconds", "150"]
    )
    rig = smoke.build_dry_run_rig(config, smoke.DryRunConfig())
    run = smoke.SmokeRun(config, rig)
    try:
        assert await run.start()

        async def user_initiated_close() -> None:
            # The fake's close_connection mirrors the SDK's _close_one: it forgets the streams.
            await rig.fakes.clients[-1].close_connection()  # type: ignore[union-attr]

        step = await run.forced_disconnect(drop=user_initiated_close)
    finally:
        await run.stop()
        rig.cleanup()

    assert step["path_exercised"] == "solicited-or-unknown"
    assert step["stale_stream_entries_before_rebuild"] == []
    assert step["close_api_calls"] == 1
    result = smoke.check_forced_disconnect(run.evidence)
    assert not result.ok
    assert result.reason == "unsolicited path not proven"


def test_check_forced_disconnect_rejects_each_missing_proof(tmp_path: Path) -> None:
    _rig, evidence, _code = _run_rig("--force-disconnect-after-seconds", "20", out=tmp_path)
    assert smoke.check_forced_disconnect(evidence).ok

    def mutated(**changes: Any) -> dict[str, Any]:
        broken = copy.deepcopy(evidence)
        broken["forced_disconnect"].update(changes)
        return broken

    no_stale = mutated(stale_stream_entries_before_rebuild=[])
    assert smoke.check_forced_disconnect(no_stale).reason == "unsolicited path not proven"
    close_api = mutated(close_api_calls=1)
    assert smoke.check_forced_disconnect(close_api).reason == "unsolicited path not proven"
    nothing_after = mutated(closed_events_after_resume=0)
    assert "no closed event" in smoke.check_forced_disconnect(nothing_after).reason
    no_outage = mutated(gap_records=[], outage_statement=None)
    assert "outage" in smoke.check_forced_disconnect(no_outage).reason
    assert not smoke.check_forced_disconnect({"forced_disconnect": {"status": "NOT_RUN"}}).ok
    assert not smoke.check_forced_disconnect({}).ok


# -- live transport drop, pinned against the installed packages without opening a socket --- #


class _Recorder:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class _AsyncRecorder:
    def __init__(self) -> None:
        self.closed = 0

    async def close(self) -> bool:
        self.closed += 1
        return True


def _stub_connection(response: Any = None, websocket: Any = None) -> types.SimpleNamespace:
    sock = websocket if websocket is not None else types.SimpleNamespace()
    if response is not None:
        sock._response = response
    return types.SimpleNamespace(websocket=sock, close_initiated=False)


def test_drop_transport_closes_the_response_that_backs_the_websocket() -> None:
    response = _Recorder()
    connection = _stub_connection(response=response)

    smoke._drop_transport(connection)

    assert response.closed == 1
    assert connection.close_initiated is False, "the SDK must still see an unsolicited close"


async def test_drop_connections_transport_drop_touches_every_connection() -> None:
    responses = [_Recorder(), _Recorder(), _Recorder()]
    connections = [_stub_connection(response=r) for r in responses]

    await smoke.drop_connections(connections, "transport-drop")

    assert [r.closed for r in responses] == [1, 1, 1]


async def test_drop_connections_ws_close_awaits_close_on_the_aiohttp_websocket() -> None:
    sockets = [_AsyncRecorder(), _AsyncRecorder()]
    connections = [_stub_connection(websocket=s) for s in sockets]

    await smoke.drop_connections(connections, "ws-close")

    assert [s.closed for s in sockets] == [1, 1]
    assert all(c.close_initiated is False for c in connections)


async def test_drop_connections_refuses_an_empty_list_and_an_unknown_method() -> None:
    with pytest.raises(RuntimeError, match="no SDK connection"):
        await smoke.drop_connections([], "transport-drop")
    with pytest.raises(ValueError, match="unsupported disconnect method"):
        await smoke.drop_connections([_stub_connection(response=_Recorder())], "close-api")


def test_aiohttp_still_keeps_the_response_on_the_websocket_object() -> None:
    # Contract: the transport drop reaches the TCP connection through this attribute path.
    source = inspect.getsource(aiohttp.ClientWebSocketResponse.__init__)
    assert "self._response = response" in source
    assert hasattr(aiohttp.ClientResponse, "close")


def test_disconnect_method_accepts_only_the_two_unsolicited_paths(tmp_path: Path) -> None:
    for method in ("transport-drop", "ws-close"):
        config = smoke.parse_config(
            ["--dry-run", "--out", str(tmp_path), "--disconnect-method", method]
        )
        assert config.disconnect_method == method
    refused = smoke.main(
        ["--dry-run", "--out", str(tmp_path), "--disconnect-method", "close-api"], environ={}
    )
    assert refused == 2


def test_the_script_never_references_a_close_api_or_sets_close_initiated() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"close_connection", "_close_one"}, (
                f"script references {node.attr} at line {node.lineno}"
            )
            if node.attr == "close_initiated":
                assert not isinstance(node.ctx, ast.Store), "script sets close_initiated"
        if isinstance(node, ast.Name):
            assert node.id not in {"close_connection", "_close_one"}


# -- SDK rotation override and guard (research D2) ------------------------------------------ #


def test_the_sdk_rotation_constant_exists_and_defaults_to_23_hours() -> None:
    module_value = sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS
    assert module_value == sdk_constants.AUTO_RECONNECT_INTERVAL_SECONDS
    assert sdk_constants.AUTO_RECONNECT_INTERVAL_SECONDS == 82800


def test_nothing_under_src_assigns_the_sdk_rotation_constant() -> None:
    offenders: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            stored_attribute = (
                isinstance(node, ast.Attribute)
                and node.attr == SDK_ROTATION_NAME
                and isinstance(node.ctx, ast.Store)
            )
            stored_name = (
                isinstance(node, ast.Name)
                and node.id == SDK_ROTATION_NAME
                and isinstance(node.ctx, ast.Store)
            )
            as_string = isinstance(node, ast.Constant) and node.value == SDK_ROTATION_NAME
            if stored_attribute or stored_name or as_string:
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == []


def test_a_rotation_interval_below_the_floor_is_refused(tmp_path: Path) -> None:
    refused = smoke.main(
        ["--dry-run", "--out", str(tmp_path), "--sdk-reconnect-interval-seconds", "299"],
        environ={},
    )
    assert refused == 2
    assert list(tmp_path.iterdir()) == []
    config = smoke.parse_config(
        ["--dry-run", "--out", str(tmp_path), "--sdk-reconnect-interval-seconds", "300"]
    )
    assert config.sdk_reconnect_interval_seconds == 300


def _spying_rig_factory(seen: list[int]) -> Any:
    """A live-mode rig factory over the fakes that records the SDK constant at connect time."""

    def factory(config: smoke.SmokeConfig) -> smoke.SmokeRig:
        rig = smoke.build_dry_run_rig(config, smoke.DryRunConfig())
        original = rig.adapter.connect

        async def spy() -> None:
            seen.append(sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS)
            await original()

        rig.adapter.connect = spy  # type: ignore[method-assign]
        return rig

    return factory


def test_live_sets_the_sdk_timer_for_the_run_only_and_restores_it(tmp_path: Path) -> None:
    seen: list[int] = []
    before = sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS

    code = smoke.main(
        [
            "--live",
            "--i-am-on-the-connected-machine",
            "--out",
            str(tmp_path),
            "--duration-seconds",
            "700",
            "--sdk-reconnect-interval-seconds",
            "600",
            "--no-archive-fetch",
        ],
        environ={},
        rig_factory=_spying_rig_factory(seen),
    )

    evidence = json.loads(next(tmp_path.glob("16-PAPER-WS-SMOKE-*.json")).read_text("utf-8"))
    assert code == 0
    assert seen == [600], "the SDK read the shortened timer when it opened its connections"
    assert sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS == before, "restored in a finally block"
    assert evidence["mode"] == "live"
    assert evidence["proof_class"] == "FAKE", "a fake rig is never REAL_SMOKE, even in live mode"
    assert evidence["sdk_reconnect"]["mode"] == "override"


def test_live_restores_the_sdk_timer_when_the_run_fails(tmp_path: Path) -> None:
    before = sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS

    def factory(config: smoke.SmokeConfig) -> smoke.SmokeRig:
        raise RuntimeError("rig construction failed")

    with pytest.raises(RuntimeError, match="rig construction failed"):
        smoke.main(
            [
                "--live",
                "--i-am-on-the-connected-machine",
                "--out",
                str(tmp_path),
                "--sdk-reconnect-interval-seconds",
                "600",
            ],
            environ={},
            rig_factory=factory,
        )

    assert sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS == before


def test_dry_run_leaves_the_sdk_attribute_untouched_and_shortens_only_the_fake(
    tmp_path: Path,
) -> None:
    before = sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS

    _rig, evidence, _code = _run_rig(
        "--sdk-reconnect-interval-seconds",
        "600",
        base=("--intervals", "1h", "--duration-seconds", "700"),
        out=tmp_path,
    )

    assert sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS == before
    reconnect = evidence["sdk_reconnect"]
    assert reconnect["mode"] == "override"
    assert reconnect["interval_seconds_effective"] == 600
    assert reconnect["reconnect_events"] == 1
    assert reconnect["real"] is False


# -- faked-clock test of the 23 h path (research D2) --------------------------------------- #


def _rotation_run(duration: int, tmp_path: Path) -> tuple[smoke.SmokeRig, dict[str, Any]]:
    rig, evidence, _code = _run_rig(
        base=("--intervals", "1h", "--duration-seconds", str(duration), "--no-archive-fetch"),
        out=tmp_path,
    )
    return rig, evidence


def test_no_reconnect_fires_one_second_before_the_sdk_rotation_interval(tmp_path: Path) -> None:
    _rig, evidence = _rotation_run(82799, tmp_path)

    reconnect = evidence["sdk_reconnect"]
    assert reconnect["interval_seconds_effective"] == 82800
    assert reconnect["mode"] == "default"
    assert reconnect["reconnect_events"] == 0
    assert reconnect["status"] == "NOT_RUN"


def test_exactly_one_reconnect_fires_at_the_sdk_rotation_interval_and_is_verified(
    tmp_path: Path,
) -> None:
    rig, evidence = _rotation_run(82800, tmp_path)

    reconnect = evidence["sdk_reconnect"]
    reconnect_at = smoke.DryRunConfig().start_utc + timedelta(seconds=82800)
    assert reconnect["status"] == "OK"
    assert reconnect["reconnect_events"] == 1
    assert reconnect["interval_seconds_effective"] == 82800
    assert reconnect["real"] is False
    calls = rig.fakes.public.klines_calls  # type: ignore[union-attr]
    assert [call for call in calls if call[2] < reconnect_at] == []
    assert len([call for call in calls if call[2] >= reconnect_at]) >= 1, (
        "the supervisor verified the seam with a REST backfill from the last close"
    )
    assert evidence["forced_disconnect"]["status"] == "NOT_RUN"


def test_closed_events_after_the_rotation_are_counted(tmp_path: Path) -> None:
    _rig, evidence = _rotation_run(82800 + 3700, tmp_path)

    reconnect = evidence["sdk_reconnect"]
    assert reconnect["reconnect_events"] == 1
    assert reconnect["closed_events_after_reconnect"] >= 1
    assert isinstance(reconnect["backfill_bars"], list)
    assert isinstance(reconnect["gap_records"], list)
    assert smoke.check_evidence_schema(evidence) == []


def test_an_override_interval_fires_at_the_override(tmp_path: Path) -> None:
    short = ("--intervals", "1h", "--no-archive-fetch")
    _rig, evidence, _code = _run_rig(
        "--sdk-reconnect-interval-seconds",
        "600",
        base=(*short, "--duration-seconds", "599"),
        out=tmp_path,
    )
    assert evidence["sdk_reconnect"]["reconnect_events"] == 0

    _rig, evidence, _code = _run_rig(
        "--sdk-reconnect-interval-seconds",
        "600",
        base=(*short, "--duration-seconds", "600"),
        out=tmp_path,
    )
    assert evidence["sdk_reconnect"]["reconnect_events"] == 1
    assert evidence["sdk_reconnect"]["mode"] == "override"
