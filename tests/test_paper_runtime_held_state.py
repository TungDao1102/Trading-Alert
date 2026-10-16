"""Plan 16-55 Task 3: a refused start holds, writes nothing and is visibly unhealthy.

The owner's decision 16-55 Q1 = A (decisions/16-DEC-RESTART-POLICY.md) with correction 1 of
16-DEC-FIXPLANS.md:

- every refused start, SKIPPED included, holds under `--hold-on-refusal` in a non-operational
  state: no record of any type, no loop, no WebSocket, Telegram or market-data client;
- the hold leaves an explicit held marker (`src/paper/held_marker.py`), so the healthcheck reports
  unhealthy even when the store holds a fresh bar of an earlier run;
- under `restart: unless-stopped` Docker restarts any exit that no `docker stop` or
  `compose stop` preceded, so a runtime-initiated exit 0 is restarted: no path of the service
  command may rely on exit 0 to stay down (Test 6, the exit-0 inventory).
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import src.paper.freeze as freeze
from src.paper import held_marker, runtime
from src.paper.runtime_config import ExitCode
from src.paper.runtime_state import (
    INSTANCE_LEASE_SCOPE,
    InMemoryRuntimeState,
    RuntimeRecord,
)
from src.paper.vocabulary import RuntimeEventType

from tests.test_paper_runtime_admission import _Rig
from tests.test_rationale import write_rationalized_set


class CountingState(InMemoryRuntimeState):
    def __init__(self) -> None:
        super().__init__()
        self.writes: list[RuntimeEventType] = []

    def record(self, record: RuntimeRecord) -> None:
        self.writes.append(record.event_type)
        super().record(record)


@pytest.fixture(autouse=True)
def _start_from_an_empty_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(freeze, "PAPER_START_ALLOWLIST", ())


@pytest.fixture
def no_clients(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fails the test when a WebSocket, market-data, Telegram or database client is built."""
    import sqlalchemy
    from src.adapters import binance_public, paper_ws

    built: list[str] = []

    def trip(label: str) -> Any:
        def _tripped(*_args: object, **_kwargs: object) -> None:
            built.append(label)
            raise AssertionError(f"{label} was constructed during a refused start")

        return _tripped

    monkeypatch.setattr(paper_ws.PaperWsAdapter, "__init__", trip("PaperWsAdapter"))
    monkeypatch.setattr(
        binance_public.BinancePublicMarketData, "__init__", trip("BinancePublicMarketData")
    )
    monkeypatch.setattr(sqlalchemy, "create_engine", trip("sqlalchemy.create_engine"))
    from telegram.ext import ApplicationBuilder

    monkeypatch.setattr(ApplicationBuilder, "build", trip("telegram Application"))
    return built


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Rig]:
    import src.domain.registry as domain_registry

    rig = _Rig(tmp_path, monkeypatch)
    rig.state = CountingState()
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", rig.root)
    write_rationalized_set(rig.root)
    yield rig


def _counting(rig: _Rig) -> CountingState:
    assert isinstance(rig.state, CountingState)
    return rig.state


# ---- the held marker itself -------------------------------------------------------------- #


def test_the_marker_names_the_container_pid_code_and_class_only(tmp_path: Path) -> None:
    path = held_marker.write_marker(tmp_path, code=5, refusal="NO_PINNED_EPOCH")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {"schema", "container", "pid", "code", "refusal"}
    assert payload["container"] == held_marker.container_name()
    assert payload["code"] == 5
    assert payload["refusal"] == "NO_PINNED_EPOCH"
    own = held_marker.read_own_marker(tmp_path)
    assert own is not None and own.code == 5 and own.refusal == "NO_PINNED_EPOCH"
    held_marker.remove_marker(tmp_path)
    assert held_marker.read_own_marker(tmp_path) is None
    held_marker.remove_marker(tmp_path)  # removing an absent marker is a no-op


def test_a_marker_of_another_container_is_not_this_containers_marker(tmp_path: Path) -> None:
    held_marker.write_marker(tmp_path, code=8, refusal="INSTANCE_LEASE_HELD", container="other-ct")
    assert held_marker.read_own_marker(tmp_path) is None
    assert held_marker.read_own_marker(tmp_path, container="other-ct") is not None


def test_an_unreadable_own_marker_still_counts_as_held(tmp_path: Path) -> None:
    held_marker.marker_path(tmp_path).write_text("{not json", encoding="utf-8")
    own = held_marker.read_own_marker(tmp_path)
    assert own is not None, "a damaged marker must never read as 'not held'"


def test_the_marker_module_is_stdlib_only() -> None:
    tree = ast.parse(Path(held_marker.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {
        "__future__",
        "json",
        "os",
        "re",
        "socket",
        "tempfile",
        "dataclasses",
        "pathlib",
        "typing",
        "collections",
    }, imported


# ---- Test 4: every refusal path holds with the marker and writes nothing ----------------- #


def _trade_key(rig: _Rig) -> dict[str, str]:
    rig.authorize()
    return {**rig.environ(), "BINANCE_API_KEY": "x"}


def _no_config(rig: _Rig) -> dict[str, str]:
    rig.authorize()
    env = rig.environ()
    del env["PAPER_RUNTIME_CONFIG"]
    return env


def _no_pin(rig: _Rig) -> dict[str, str]:
    rig.authorize()
    return rig.environ()


def _not_admitted(rig: _Rig) -> dict[str, str]:
    rig.authorize_other_set()
    return rig.environ()


def _epoch_mismatch(rig: _Rig) -> dict[str, str]:
    rig.authorize()
    assert rig.run("--pin-epoch") == 0
    pinned = rig.pinned()
    freeze.write_pinned_state(
        freeze.StreamEpoch(
            **{**pinned.__dict__, "opened_at_utc": pinned.opened_at_utc + timedelta(1)}
        ),
        rig.pinned_path,
    )
    _counting(rig).writes.clear()
    return rig.environ()


def _instance_held(rig: _Rig) -> dict[str, str]:
    rig.authorize()
    assert rig.run("--pin-epoch") == 0
    _counting(rig).writes.clear()
    lease = rig.state.acquire_instance_lease(INSTANCE_LEASE_SCOPE)
    assert lease is not None
    rig.other_lease = lease  # type: ignore[attr-defined]
    return rig.environ()


def _skipped(rig: _Rig) -> dict[str, str]:
    return rig.environ()  # the allowlist stays empty


REFUSALS = [
    pytest.param(_trade_key, ExitCode.TRADE_KEY_REFUSED, "TRADE_KEY_REFUSED", id="3-trade-key"),
    pytest.param(_no_config, ExitCode.CONFIG_NOT_RATIFIED, "CONFIG_NOT_RATIFIED", id="4-config"),
    pytest.param(_no_pin, ExitCode.NO_PINNED_EPOCH, "NO_PINNED_EPOCH", id="5-no-pin"),
    pytest.param(
        _not_admitted,
        ExitCode.ADMISSION_OR_EPOCH_MISMATCH,
        "ADMISSION_OR_EPOCH_MISMATCH",
        id="6-admission",
    ),
    pytest.param(
        _epoch_mismatch,
        ExitCode.ADMISSION_OR_EPOCH_MISMATCH,
        "ADMISSION_OR_EPOCH_MISMATCH",
        id="6-epoch",
    ),
    pytest.param(
        _instance_held, ExitCode.INSTANCE_LEASE_HELD, "INSTANCE_LEASE_HELD", id="8-instance"
    ),
    pytest.param(_skipped, ExitCode.OK, "SKIPPED", id="0-skipped"),
]


@pytest.mark.parametrize(("arrange", "code", "refusal"), REFUSALS)
def test_every_refusal_holds_with_its_marker_and_writes_nothing(
    rig: _Rig, no_clients: list[str], arrange: Any, code: ExitCode, refusal: str
) -> None:
    environ = arrange(rig)
    marker_dir = rig.pinned_path.parent
    seen: list[held_marker.HeldMarker | None] = []

    def wait_for_stop() -> None:
        seen.append(held_marker.read_own_marker(marker_dir))

    result = runtime.main(
        ["--hold-on-refusal", "--pinned-state", str(rig.pinned_path)],
        environ=environ,
        wait_for_stop=wait_for_stop,
        state=rig.state,
        registry_root=rig.root,
        clock=rig.clock,
        run_loop=lambda _c: pytest.fail("a refused start must not run the loop"),
    )

    assert result == int(code)
    assert len(seen) == 1, "wait_for_stop is called exactly once"
    assert seen[0] is not None, "the held marker exists while the process holds"
    assert seen[0].code == int(code) and seen[0].refusal == refusal
    assert held_marker.read_own_marker(marker_dir) is None, "the marker goes when the hold ends"
    assert _counting(rig).writes == [], "a held start writes no record of any type"
    assert no_clients == []


@pytest.mark.parametrize(("arrange", "code", "refusal"), REFUSALS)
def test_without_the_flag_every_refusal_returns_at_once_and_leaves_no_marker(
    rig: _Rig, no_clients: list[str], arrange: Any, code: ExitCode, refusal: str
) -> None:
    environ = arrange(rig)
    result = runtime.main(
        ["--pinned-state", str(rig.pinned_path)],
        environ=environ,
        wait_for_stop=lambda: pytest.fail("no hold without the flag"),
        state=rig.state,
        registry_root=rig.root,
        clock=rig.clock,
        run_loop=lambda _c: pytest.fail("a refused start must not run the loop"),
    )
    assert result == int(code)
    assert held_marker.read_own_marker(rig.pinned_path.parent) is None
    assert _counting(rig).writes == []


def test_a_hold_that_cannot_write_its_marker_exits_instead_of_holding_invisibly(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(*_args: object, **_kwargs: object) -> Path:
        raise OSError("read-only file system")

    monkeypatch.setattr(held_marker, "write_marker", fail)
    result = runtime.main(
        ["--hold-on-refusal", "--pinned-state", str(rig.pinned_path)],
        environ=_skipped(rig),
        wait_for_stop=lambda: pytest.fail("an invisible hold is never entered"),
        state=rig.state,
        registry_root=rig.root,
        clock=rig.clock,
    )
    assert result == ExitCode.FAIL_CLOSED_RUNTIME, "SKIPPED never exits 0 under the service flag"
    assert "held marker" in capsys.readouterr().err


# ---- Test 5: the healthcheck is unhealthy while held -------------------------------------- #

PROBE_NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _healthy_looking_store(rig: _Rig) -> None:
    """A pinned epoch with a RUNTIME_START and a fresh closed bar (an earlier run).

    The bar is ten seconds old, inside the test configuration's maximum bar age.
    """
    rig.authorize()
    assert rig.run("--pin-epoch") == 0
    epoch = rig.pinned()
    rig.state.record(
        RuntimeRecord(
            event_type=RuntimeEventType.RUNTIME_START,
            epoch_id=epoch.epoch_id,
            occurred_at_utc=PROBE_NOW - timedelta(minutes=30),
            payload={"strategy_id": epoch.strategy_id},
        )
    )
    rig.state.record(
        RuntimeRecord.bar_processed(
            epoch_id=epoch.epoch_id,
            symbol="BTCUSDT",
            interval="1h",
            close_time_utc=PROBE_NOW - timedelta(seconds=10),
            payload={"source": "LIVE_WS", "tick_time_utc": PROBE_NOW - timedelta(seconds=10)},
        )
    )


def _probe(rig: _Rig) -> int:
    return runtime.main(
        ["--healthcheck", "--pinned-state", str(rig.pinned_path)],
        environ=rig.environ(),
        state=rig.state,
        registry_root=rig.root,
        clock=lambda: PROBE_NOW,
    )


def test_a_held_container_is_unhealthy_even_with_a_fresh_bar_in_the_store(
    rig: _Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    _healthy_looking_store(rig)
    capsys.readouterr()
    assert _probe(rig) == 0, "control: without a marker the store reads healthy"
    assert capsys.readouterr().out.strip() == "healthy"

    held_marker.write_marker(rig.pinned_path.parent, code=8, refusal="INSTANCE_LEASE_HELD")
    assert _probe(rig) == 1
    out = capsys.readouterr().out
    assert out.startswith("unhealthy:")
    assert "held" in out and "INSTANCE_LEASE_HELD" in out
    assert held_marker.read_own_marker(rig.pinned_path.parent) is not None, (
        "the probe never removes the marker"
    )


def test_a_marker_of_another_container_does_not_change_this_probe(
    rig: _Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    _healthy_looking_store(rig)
    held_marker.write_marker(
        rig.pinned_path.parent, code=5, refusal="NO_PINNED_EPOCH", container="another-container"
    )
    capsys.readouterr()
    assert _probe(rig) == 0
    assert capsys.readouterr().out.strip() == "healthy"


def test_a_stale_marker_of_this_container_is_removed_by_the_next_start_before_runtime_start(
    rig: _Rig,
) -> None:
    rig.authorize()
    assert rig.run("--pin-epoch") == 0
    marker_dir = rig.pinned_path.parent
    held_marker.write_marker(marker_dir, code=5, refusal="NO_PINNED_EPOCH")  # a killed hold
    seen_at_start: list[bool] = []
    real_record = rig.state.record

    def record(record: RuntimeRecord) -> None:
        if record.event_type is RuntimeEventType.RUNTIME_START:
            seen_at_start.append(held_marker.read_own_marker(marker_dir) is not None)
        real_record(record)

    rig.state.record = record  # type: ignore[method-assign]
    assert rig.run() == 0
    assert seen_at_start == [False], "the marker is gone before RUNTIME_START is written"


# ---- Test 6: the exit-0 inventory of main (correction 1) ---------------------------------- #

# Every `return` of `main` returns one of these calls. Only the four marked True can yield 0.
RETURN_KINDS: dict[str, bool] = {
    "_healthcheck": True,  # the --healthcheck probe (docker exec, never the service process)
    "_skip": True,  # SKIPPED: 0 at the end of a hold, or at once without --hold-on-refusal
    "_pinned_and_exit": True,  # the one-shot --pin-epoch (never in the service command)
    "_stopped_on_request": True,  # after RUNTIME_STOP, following a requested stop
    "refuse": False,  # refusal codes 3 to 6 and 8
    "_usage_error": False,  # 2
    "_failed_closed": False,  # 7
}


def _main_returns() -> list[ast.Return]:
    source = textwrap.dedent(inspect.getsource(runtime.main))
    func = ast.parse(source).body[0]
    assert isinstance(func, ast.FunctionDef)
    found: list[ast.Return] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue  # a nested helper's return is not a return of main
            if isinstance(child, ast.Return):
                found.append(child)
            visit(child)

    visit(func)
    return found


def test_every_return_of_main_is_a_known_kind() -> None:
    """The exit-0 inventory: what may end the process with status 0.

    Under `restart: unless-stopped` Docker restarts every exit that no `docker stop` or
    `compose stop` preceded, a status 0 included. So no path of the service command
    (`--hold-on-refusal`, never `--pin-epoch`) may rely on exit 0 to stay down: 0 comes only from
    the probe, the one-shot pin, the end of a hold (a stop was requested) or the return after
    RUNTIME_STOP following a requested stop.
    """
    kinds: list[str] = []
    for node in _main_returns():
        value = node.value
        assert isinstance(value, ast.Call), ast.unparse(node)
        assert isinstance(value.func, ast.Name), ast.unparse(node)
        assert value.func.id in RETURN_KINDS, f"unknown exit path: {ast.unparse(node)}"
        if value.func.id == "refuse":
            first = value.args[0]
            assert isinstance(first, ast.Attribute) and first.attr != "OK", ast.unparse(node)
        kinds.append(value.func.id)
    assert set(kinds) == set(RETURN_KINDS), "every kind of the inventory is a real path"
    for name in ("_pinned_and_exit", "_stopped_on_request", "_skip"):
        assert kinds.count(name) == 1, name


def test_refusal_codes_are_never_zero() -> None:
    from src.paper.runtime_config import REFUSAL_CODES

    assert 0 not in REFUSAL_CODES


def test_the_service_command_exits_0_only_after_a_stop_request(rig: _Rig) -> None:
    """Behaviour of the four zero paths under the service flags (`--hold-on-refusal`)."""
    stops: list[int] = []

    def stop() -> None:
        stops.append(1)

    def service(**kwargs: Any) -> int:
        return runtime.main(
            ["--hold-on-refusal", "--pinned-state", str(rig.pinned_path)],
            environ=rig.environ(),
            wait_for_stop=stop,
            state=rig.state,
            registry_root=rig.root,
            clock=rig.clock,
            **kwargs,
        )

    # SKIPPED: 0 only after the hold ended on a stop request.
    assert service(run_loop=lambda _c: pytest.fail("no loop")) == 0
    assert stops == [1]
    # A run: 0 only after the loop returned on a requested stop and RUNTIME_STOP was written.
    rig.authorize()
    assert rig.run("--pin-epoch") == 0
    assert service(run_loop=lambda _c: None) == 0
    assert rig.types()[-1] is RuntimeEventType.RUNTIME_STOP

    # The loop failing closed is never 0 under the service flags.
    def failing(_c: Any) -> None:
        raise runtime.RuntimeFailClosed("x")

    assert service(run_loop=failing) == ExitCode.FAIL_CLOSED_RUNTIME
