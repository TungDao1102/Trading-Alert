"""Plan 16-56 Task 4: the paper liveness stamp and the `--liveness` probe (16-DEC-HUNG-RUNTIME).

The separate paper heartbeat pings only while this probe passes: no held marker of this
container, and a loop-alive stamp and a last-frame time both within
`health.feed_silence_timeout_seconds` (correction 2: the 120 s feed-liveness and loop-alive
signal, never the 3900 s bar-age healthcheck). No database, network or Telegram client is opened.
"""

from __future__ import annotations

import ast
import tomllib
from datetime import timedelta
from pathlib import Path

import pytest
from src.paper import held_marker, liveness, runtime

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
    assert first.loop_alive_utc == NOW and first.last_frame_utc == NOW
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
