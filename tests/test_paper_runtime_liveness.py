"""Plan 16-56 Task 4: the paper liveness stamp and the `--liveness` probe (16-DEC-HUNG-RUNTIME).

The separate paper heartbeat pings only while this probe passes: no held marker of this
container, and a loop-alive stamp and a last-frame time both within
`health.feed_silence_timeout_seconds` (correction 2: the 120 s feed-liveness and loop-alive
signal, never the 3900 s bar-age healthcheck). No database, network or Telegram client is opened.
"""

from __future__ import annotations

import ast
import json
import tomllib
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from src.paper import held_marker, liveness, runtime
from src.paper.runtime_config import ExitCode

from tests.test_paper_runtime_admission import CONFIG_TEXT
from tests.test_paper_runtime_loop import NOW, FixedClock, Live, live, wait_until
from tests.test_paper_runtime_watchdog import BOUND, HALF, Watch, _frame, _watched

__all__ = ["live"]  # the imported fixture

REPO_ROOT = Path(__file__).resolve().parent.parent
LIMIT = timedelta(seconds=int(tomllib.loads(CONFIG_TEXT)["health"]["feed_silence_timeout_seconds"]))


@pytest.fixture(autouse=True)
def _isolated_sdk_stream_map(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.paper_ws_fakes import fresh_sdk_stream_map

    fresh_sdk_stream_map(monkeypatch)


# ---- Test 1: the stamp ----------------------------------------------------------------------- #


def test_the_watchdog_stamps_loop_alive_and_last_frame_times_of_this_container(
    live: Live,
) -> None:
    watch = Watch()
    clock = FixedClock()
    directory = live.rig.pinned_path.parent
    seen: list[liveness.LivenessStamp | None] = []

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        await wait_until(lambda: liveness.liveness_path(directory).exists())
        seen.append(liveness.read_liveness(directory))  # the stamp at the watchdog's start
        _frame(h, "ETHUSDT", "1h")  # a message at feed time 1000
        clock.advance(timedelta(seconds=HALF))
        await watch.tick()
        seen.append(liveness.read_liveness(directory))
        clock.advance(timedelta(seconds=HALF))
        await watch.tick()  # no message during this wake
        seen.append(liveness.read_liveness(directory))

    assert live.start(script, clock=clock, **_watched(watch)) == 0

    first, second, third = seen
    assert first is not None and second is not None and third is not None
    assert first.container == held_marker.container_name()
    assert first.loop_alive_utc == NOW
    assert first.last_frame_utc is None, "no frame had arrived at the watchdog's start (16-65)"
    assert second.loop_alive_utc == NOW + timedelta(seconds=HALF)
    assert second.last_frame_utc == NOW, "the last message came at the watchdog's start"
    assert third.loop_alive_utc == NOW + timedelta(seconds=2 * HALF)
    assert third.last_frame_utc == NOW
    path = liveness.liveness_path(directory)
    assert path.parent == directory and path.name.startswith("liveness-")


def test_a_hung_event_loop_stops_refreshing_the_stamp() -> None:
    """The stamp is written only by the watchdog task on the event loop, never on the SDK thread."""
    supervisor = (REPO_ROOT / "src" / "paper" / "supervisor.py").read_text(encoding="utf-8")
    assert "liveness" not in supervisor, "the SDK-thread handler must not write the stamp"
    tree = ast.parse((REPO_ROOT / "src" / "paper" / "runtime.py").read_text(encoding="utf-8"))
    writers = {
        func.name
        for func in ast.walk(tree)
        if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef)
        for node in ast.walk(func)
        if isinstance(node, ast.Attribute) and node.attr == "write_liveness"
    }
    assert writers == {"_stamp_liveness"}
    callers = {
        func.name
        for func in ast.walk(tree)
        if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef)
        for node in ast.walk(func)
        if isinstance(node, ast.Attribute) and node.attr == "_stamp_liveness"
    }
    assert callers == {"_watch_feed"}


# ---- Test 2: the probe ----------------------------------------------------------------------- #


class Probe:
    def __init__(self, tmp_path: Path) -> None:
        self.directory = tmp_path / "logs" / "paper"
        self.pinned = self.directory / "pinned_epoch.json"
        self.config = tmp_path / "paper-runtime-test.toml"
        self.config.write_text(CONFIG_TEXT, encoding="utf-8")

    def environ(self, **extra: str) -> dict[str, str]:
        return {"PAPER_RUNTIME_CONFIG": str(self.config), **extra}

    def stamp(self, *, loop_age: timedelta, frame_age: timedelta) -> None:
        liveness.write_liveness(
            self.directory, loop_alive_utc=NOW - loop_age, last_frame_utc=NOW - frame_age
        )

    def run(self, environ: dict[str, str] | None = None) -> int:
        return runtime.main(
            ["--liveness", "--pinned-state", str(self.pinned)],
            environ=self.environ() if environ is None else environ,
            clock=FixedClock(NOW),
        )


@pytest.fixture
def probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Probe:
    def no_database(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the liveness probe must not open the database")

    monkeypatch.setattr(runtime, "_state_from_env", no_database)
    monkeypatch.setattr(runtime, "_shadow_from_env", no_database)
    monkeypatch.setattr(runtime, "_resolve_public", no_database)
    return Probe(tmp_path)


def test_live_when_both_stamps_are_within_the_bound(
    probe: Probe, capsys: pytest.CaptureFixture[str]
) -> None:
    probe.stamp(loop_age=LIMIT, frame_age=LIMIT)
    assert probe.run() == 0
    assert capsys.readouterr().out.strip() == "live"


@pytest.mark.parametrize(
    ("loop_age", "frame_age", "reason"),
    [
        (LIMIT + timedelta(seconds=1), timedelta(0), "event loop"),
        (timedelta(0), LIMIT + timedelta(seconds=1), "feed is silent"),
    ],
    ids=["hung-loop", "silent-feed"],
)
def test_a_stale_stamp_is_not_live(
    probe: Probe,
    capsys: pytest.CaptureFixture[str],
    loop_age: timedelta,
    frame_age: timedelta,
    reason: str,
) -> None:
    probe.stamp(loop_age=loop_age, frame_age=frame_age)
    assert probe.run() == 1
    out = capsys.readouterr().out
    assert out.startswith("not live: ") and reason in out and len(out.splitlines()) == 1


def test_a_held_refusal_is_not_live_even_with_a_fresh_stamp(
    probe: Probe, capsys: pytest.CaptureFixture[str]
) -> None:
    probe.stamp(loop_age=timedelta(0), frame_age=timedelta(0))
    held_marker.write_marker(probe.directory, code=6, refusal="ADMISSION_OR_EPOCH_MISMATCH")
    assert probe.run() == 1
    assert "held" in capsys.readouterr().out


def test_a_missing_or_unreadable_stamp_is_not_live(
    probe: Probe, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe.run() == 1
    assert "no liveness file" in capsys.readouterr().out
    probe.directory.mkdir(parents=True, exist_ok=True)
    liveness.liveness_path(probe.directory).write_text("{not json", encoding="utf-8")
    assert probe.run() == 1
    assert "unreadable" in capsys.readouterr().out


def test_another_containers_stamp_does_not_count(probe: Probe) -> None:
    liveness.write_liveness(
        probe.directory,
        loop_alive_utc=NOW,
        last_frame_utc=NOW,
        container="some-other-container",
    )
    assert probe.run() == 1


@pytest.mark.parametrize("config", ["absent", "missing-file", "missing-key"])
def test_an_unreadable_configuration_is_not_live(
    probe: Probe, capsys: pytest.CaptureFixture[str], config: str
) -> None:
    probe.stamp(loop_age=timedelta(0), frame_age=timedelta(0))
    if config == "absent":
        environ: dict[str, str] = {}
    elif config == "missing-file":
        environ = probe.environ(PAPER_RUNTIME_CONFIG=str(probe.config) + ".gone")
    else:
        probe.config.write_text(
            CONFIG_TEXT.replace("feed_silence_timeout_seconds", "# removed"), encoding="utf-8"
        )
        environ = probe.environ()
    assert probe.run(environ) == 1
    assert capsys.readouterr().out.startswith("not live: ")


def test_the_probe_prints_no_environment_value(
    probe: Probe, capsys: pytest.CaptureFixture[str]
) -> None:
    probe.stamp(loop_age=timedelta(0), frame_age=timedelta(0))
    environ = probe.environ(
        TELEGRAM_BOT_TOKEN="tg-secret-token-value",
        DATABASE_URL="postgresql://user:db-secret-password@host/db",
    )
    assert probe.run(environ) == 0
    out = capsys.readouterr()
    for value in ("tg-secret-token-value", "db-secret-password"):
        assert value not in out.out + out.err


def test_the_probe_is_handled_before_any_start_step(probe: Probe) -> None:
    """Like --healthcheck: no lease, no pin, no record, no client (the seams above would raise)."""
    probe.stamp(loop_age=timedelta(0), frame_age=timedelta(0))
    environ = probe.environ(BINANCE_API_KEY="")  # a refusal would happen at the start gate
    assert probe.run(environ) == 0
    assert not probe.pinned.exists()


def test_the_bound_is_read_from_the_configuration() -> None:
    assert LIMIT == timedelta(seconds=BOUND)
    source = (REPO_ROOT / "src" / "paper" / "runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    probe_fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_liveness"
    )
    assert "health.feed_silence_timeout_seconds" in ast.unparse(probe_fn)


def test_the_liveness_module_imports_only_the_stdlib_and_the_held_marker() -> None:
    tree = ast.parse((REPO_ROOT / "src" / "paper" / "liveness.py").read_text(encoding="utf-8"))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported <= {
        "__future__",
        "json",
        "os",
        "tempfile",
        "dataclasses",
        "datetime",
        "pathlib",
        "src.paper",
    }


# ---- Plan 16-65: a stamp belongs to this process and never claims a frame before one arrived - #
# Review of c654524..6f73e5b (MAJOR): the watchdog stamped last_frame = now at its start and no
# exit removed the stamp, so a runtime crashing and restarting within seconds under
# `restart: unless-stopped` kept the probe green. decisions/16-DEC-LIVENESS-FIRST-FRAME.md.


def _probe(rig: Any) -> int:
    """The `--liveness` probe of this container against the rig's directory, at NOW."""
    return runtime.main(
        ["--liveness", "--pinned-state", str(rig.pinned_path)],
        environ=rig.environ(),
        clock=FixedClock(NOW),
    )


def _healthy_looking_stamp(directory: Path) -> Path:
    """What a previous process of this container left behind: fresh times and a frame."""
    return liveness.write_liveness(directory, loop_alive_utc=NOW, last_frame_utc=NOW)


def test_a_stamp_of_a_previous_process_is_removed_before_any_start_step(live: Live) -> None:
    """(a) at the start: the stamp is gone before the loop begins."""
    directory = live.rig.pinned_path.parent
    path = _healthy_looking_stamp(directory)
    seen: list[bool] = []

    def loop(_context: object) -> None:
        seen.append(path.exists())

    assert live.rig.run(run_loop=loop) == 0
    assert seen == [False], "the previous process's stamp must be gone when the loop starts"
    assert not path.exists()


def test_a_held_refusal_holds_with_no_stamp_of_a_previous_process(live: Live) -> None:
    directory = live.rig.pinned_path.parent
    path = _healthy_looking_stamp(directory)
    seen: list[bool] = []
    code = runtime.main(
        ["--hold-on-refusal", "--pinned-state", str(live.rig.pinned_path)],
        environ={**live.rig.environ(), "PAPER_PARAMETER_SET_ID": ""},
        wait_for_stop=lambda: seen.append(path.exists()),
        state=live.rig.state,
        registry_root=live.rig.root,
        clock=FixedClock(),
        run_loop=lambda _context: None,
    )
    assert code == int(ExitCode.CONFIG_NOT_RATIFIED)
    assert seen == [False]


def test_the_stamp_is_removed_on_a_fail_closed_exit(live: Live) -> None:
    """(a) at the exit: whatever this process stamped is gone after exit 7."""
    directory = live.rig.pinned_path.parent

    def loop(_context: object) -> None:
        _healthy_looking_stamp(directory)  # as the watchdog would, then the loop fails
        raise runtime.RuntimeFailClosed("the loop failed (test)")

    assert live.rig.run(run_loop=loop) == int(ExitCode.FAIL_CLOSED_RUNTIME)
    assert not liveness.liveness_path(directory).exists()


def test_the_stamp_is_removed_on_a_clean_stop(live: Live) -> None:
    directory = live.rig.pinned_path.parent

    def loop(_context: object) -> None:
        _healthy_looking_stamp(directory)

    assert live.rig.run(run_loop=loop) == 0
    assert not liveness.liveness_path(directory).exists()


def test_the_one_shot_pin_and_the_probes_never_remove_the_stamp(live: Live) -> None:
    directory = live.rig.pinned_path.parent
    path = _healthy_looking_stamp(directory)
    assert _probe(live.rig) == 0
    assert path.exists()
    live.rig.run("--healthcheck")
    assert path.exists()
    assert live.rig.run("--pin-epoch") != 0  # refused: a pinned state exists
    assert path.exists()


def test_a_restart_loop_of_short_lived_runtimes_never_passes_the_probe(live: Live) -> None:
    """(b) the review's scenario: start, watchdog stamps, fail closed before a frame, restart.

    Before plan 16-65 every run stamped last_frame = now at the watchdog's start and left the
    stamp behind at exit 7, so the probe passed during and after every short-lived run and the
    paper heartbeat never alerted. Each run here reaches the watchdog's start stamp, probes, and
    fails closed; the probe must fail during the run and after its exit, for both runs.
    """
    directory = live.rig.pinned_path.parent
    probes: list[tuple[str, int]] = []
    codes: list[int] = []
    left_behind: list[bool] = []

    def short_lived(label: str) -> Callable[[Live], Awaitable[None]]:
        async def script(h: Live) -> None:
            await wait_until(lambda: len(h.client.handles) == 4)
            await wait_until(lambda: liveness.liveness_path(directory).exists())
            probes.append((f"{label} running", _probe(h.rig)))
            raise RuntimeError("a deterministic failure right after the start")

        return script

    for label in ("first", "second"):
        run = Live(live.rig)
        watch = Watch()
        code = run.start(short_lived(label), **_watched(watch))
        codes.append(code)
        left_behind.append(liveness.liveness_path(directory).exists())
        probes.append((f"{label} exited", _probe(live.rig)))

    assert probes == [
        ("first running", 1),
        ("first exited", 1),
        ("second running", 1),
        ("second exited", 1),
    ]
    assert codes == [int(ExitCode.FAIL_CLOSED_RUNTIME)] * 2
    assert left_behind == [False, False], "a stamp must not outlive its process"


def test_the_probe_passes_after_a_real_frame(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    """(c) a message on the connection, then a watchdog wake: live."""
    watch = Watch()
    codes: list[int] = []

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        _frame(h, "BTCUSDT", "1h")
        await watch.tick()
        codes.append(_probe(h.rig))

    assert live.start(script, **_watched(watch)) == 0
    assert codes == [0]
    assert "live" in capsys.readouterr().out.splitlines()


def test_the_probe_fails_before_the_first_frame(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    """(d) at the watchdog's start and after a wake with no message: not live.

    The silence bound itself is still measured from the watch start (the watchdog tests in
    tests/test_paper_runtime_watchdog.py are unchanged).
    """
    watch = Watch()
    directory = live.rig.pinned_path.parent
    codes: list[int] = []
    stamps: list[liveness.LivenessStamp | None] = []

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        await wait_until(lambda: liveness.liveness_path(directory).exists())
        codes.append(_probe(h.rig))
        await watch.tick()
        stamps.append(liveness.read_liveness(directory))
        codes.append(_probe(h.rig))

    assert live.start(script, **_watched(watch)) == 0
    assert codes == [1, 1]
    (stamp,) = stamps
    assert stamp is not None and stamp.last_frame_utc is None
    out = capsys.readouterr().out
    assert out.count("not live: no market message since this process started") == 2


def test_a_stamp_of_the_old_schema_is_refused(
    probe: Probe, capsys: pytest.CaptureFixture[str]
) -> None:
    probe.directory.mkdir(parents=True, exist_ok=True)
    liveness.liveness_path(probe.directory).write_text(
        json.dumps(
            {
                "schema": "paper-liveness/1",
                "container": held_marker.container_name(),
                "loop_alive_utc": NOW.isoformat(),
                "last_frame_utc": NOW.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    assert probe.run() == 1
    out = capsys.readouterr().out
    assert "unreadable" in out and liveness.LIVENESS_SCHEMA in out


def test_remove_liveness_removes_only_this_containers_stamp(tmp_path: Path) -> None:
    mine = liveness.write_liveness(tmp_path, loop_alive_utc=NOW, last_frame_utc=None)
    other = liveness.write_liveness(
        tmp_path, loop_alive_utc=NOW, last_frame_utc=NOW, container="some-other-container"
    )
    liveness.remove_liveness(tmp_path)
    assert not mine.exists() and other.exists()
    liveness.remove_liveness(tmp_path)  # absent: no error
