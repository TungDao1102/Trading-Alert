"""Public-data WebSocket smoke recorder for the paper runtime (Phase 16, plan 16-17, D-10, G3-026).

Run from the repository root::

    uv run python -m scripts.paper_ws_smoke --dry-run --out <dir>

What it is. A single-file operator and CI tool that composes the project's `PaperWsAdapter` and
`PaperSupervisor` on PUBLIC market data only and writes one redacted evidence file. `--dry-run`
(the CI mode) drives the same pipeline over the SDK-shaped fakes of `tests/paper_ws_fakes.py` on a
virtual clock, so it never touches the network and never waits. The evidence of a dry run carries
`proof_class` "FAKE": fake-level evidence never closes PAPER-01 (SC9). `--live` exists for the
blocking-human plan 16-21 only and must never be run by an automated task.

Safety posture. The script constructs no order adapter, imports nothing from `src.execution` and
holds no credential. `--live` refuses to start when any environment variable name starts with
BINANCE_ (exit 3, the name only is printed) and needs the explicit operator flag
`--i-am-on-the-connected-machine`. Evidence is scrubbed through `src.ops.redaction` before it is
written and re-scanned after the write; a file that fails the scan is deleted.

Forced disconnect. The step never uses the SDK's own close API (the user-initiated path forgets
the stream names and so cannot show the dead-subscription defect, research D3 and P4). It drops
the transport beneath the SDK connection, and the evidence proves the path through the stale
stream names that `PaperWsAdapter.rebuild` found in the SDK global stream map.

Measurements are observations for the O-07 table (plan 16-27), not thresholds. No value measured
here is compared with a limit.

Exit codes::

    0  the run completed and every requested step is OK or NOT_RUN
    1  the run completed but the subscribe was blocked or a step reported ERROR (evidence written)
    2  refused before any network call (usage, missing operator flag)
    3  refused: a trade-capable (BINANCE_*) environment variable is present
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import heapq
import importlib.metadata
import io
import itertools
import json
import os
import re
import statistics
import sys
import zipfile
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn, Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
from binance_common import websocket as sdk_websocket  # noqa: E402
from binance_common.websocket import StreamConnectionsMap  # noqa: E402
from src.adapters.binance_public import BinancePublicMarketData, Kline, MarkKline  # noqa: E402
from src.adapters.paper_ws import ALLOWED_INTERVALS, LIFECYCLE_EVENTS, PaperWsAdapter  # noqa: E402
from src.adapters.paper_ws import Kline as WsKline  # noqa: E402
from src.data.archive import (  # noqa: E402
    ArchiveError,
    archive_zip_url,
    fetch_archive_klines,
    make_archive_client,
)
from src.ops.redaction import Redactor, configure_logging  # noqa: E402
from src.paper.supervisor import PaperSupervisor  # noqa: E402
from src.paper.vocabulary import (  # noqa: E402
    INTERVAL_MS,
    GapRecord,
    RuntimeEventType,
    TaggedBar,
)

# --------------------------------------------------------------------------- #
# Constants.
# --------------------------------------------------------------------------- #

EVIDENCE_SCHEMA = "paper-ws-smoke-evidence/schema-1"
DEFAULT_EVIDENCE_DIR = (
    REPO_ROOT / ".planning" / "phases" / "16-paper-runtime-composition" / "evidence"
)
OBSERVATIONS_NOTE = "measurements are observations for the O-07 table (plan 16-27), not thresholds"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2
EXIT_TRADE_CAPABLE = 3

ALLOWED_STATUSES: frozenset[str] = frozenset({"OK", "NOT_RUN", "ERROR"})
SUBSCRIBE_STATUSES: frozenset[str] = frozenset({"OK", "BLOCKED", "NOT_RUN"})
MODES: frozenset[str] = frozenset({"dry-run", "live"})
PROOF_CLASSES: frozenset[str] = frozenset({"FAKE", "REAL_SMOKE"})
DISCONNECT_METHODS: tuple[str, ...] = ("transport-drop", "ws-close")

# Tool guard against a reconnect storm while the new-connection rate limit is UNVERIFIED
# (research G3(c)). It is a guard on this tool, not a trading threshold.
SDK_RECONNECT_FLOOR_SECONDS = 300

# The SDK opens one socket per url path (research D5): market, public, private.
EXPECTED_SDK_PATHS = 3
LAG_SETTING_LABEL = "measurement setting, not a threshold"
WEIGHT_NOT_EXPOSED_REASON = "not exposed by the SDK response"

PATH_UNSOLICITED = "unsolicited"
PATH_UNPROVEN = "solicited-or-unknown"
OUTAGE_STATEMENT = "no bar closed during the outage"

# Every measurement object the evidence must carry, requested or not (schema completeness).
MEASUREMENT_KEYS: tuple[str, ...] = (
    "connection_count",
    "arrival_latency_ms_by_interval",
    "clock_skew_ms",
    "rest_minute_lag",
    "forced_disconnect",
    "sdk_reconnect",
    "archive_fetch",
)
REQUIRED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "schema",
    "mode",
    "proof_class",
    "sdk_version",
    "binance_common_version",
    "started_at_utc",
    "finished_at_utc",
    "symbol",
    "intervals",
    "settings",
    "ws_subscribe",
    "closed_events_by_interval",
    "open_events_dropped",
    "observations_note",
    *MEASUREMENT_KEYS,
)

SDK_DISTRIBUTION = "binance-sdk-derivatives-trading-usds-futures"
SDK_COMMON_DISTRIBUTION = "binance-common"

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")
_DAY_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MS = timedelta(milliseconds=1)


class UsageError(Exception):
    """A command-line mistake; refused before any step runs."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


# --------------------------------------------------------------------------- #
# Small helpers.
# --------------------------------------------------------------------------- #


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _to_ms(moment: datetime) -> int:
    return (moment - _EPOCH) // _ONE_MS


def _from_ms(milliseconds: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=milliseconds)


def _describe(exc: BaseException) -> str:
    """Type name and message; the whole evidence file is scrubbed on write."""
    return f"{type(exc).__name__}: {exc}"


def _not_run(**extra: Any) -> dict[str, Any]:
    return {"status": "NOT_RUN", **extra}


def effective_sdk_interval(config: SmokeConfig) -> int:
    """The SDK rotation interval in force: the override, else the installed SDK's own value."""
    if config.sdk_reconnect_interval_seconds is not None:
        return config.sdk_reconnect_interval_seconds
    return int(sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS)


# --------------------------------------------------------------------------- #
# Configuration.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SmokeConfig:
    """Everything a run needs, parsed once from the command line."""

    mode: str
    out_dir: Path
    symbol: str
    intervals: tuple[str, ...]
    duration_seconds: int
    operator_flag: bool = False
    force_disconnect_after_seconds: int | None = None
    disconnect_method: str = "transport-drop"
    sdk_reconnect_interval_seconds: int | None = None
    recovery_wait_seconds: int = 120
    archive_fetch: bool = True
    archive_day: str | None = None
    rest_lag_probe_minutes: int = 0
    rest_lag_poll_interval_ms: int | None = None
    rest_lag_max_wait_seconds: int | None = None

    def settings(self) -> dict[str, Any]:
        return {
            "duration_seconds": self.duration_seconds,
            "force_disconnect_after_seconds": self.force_disconnect_after_seconds,
            "disconnect_method": self.disconnect_method,
            "sdk_reconnect_interval_seconds": self.sdk_reconnect_interval_seconds,
            "recovery_wait_seconds": self.recovery_wait_seconds,
            "archive_fetch": self.archive_fetch,
            "archive_day": self.archive_day,
            "rest_lag_probe_minutes": self.rest_lag_probe_minutes,
            "rest_lag_poll_interval_ms": self.rest_lag_poll_interval_ms,
            "rest_lag_max_wait_seconds": self.rest_lag_max_wait_seconds,
        }


@dataclass(frozen=True)
class DryRunConfig:
    """Knobs of the dry-run fakes (never reachable from the command line).

    `host_behind_server_ms`: Binance server time equals the host clock plus this value.
    `arrival_latency_ms`: how long after a bar's close the fake feed delivers the closed event
    (on the server clock). `connect_error`: makes the fake `create_connection` raise.
    `archive_mode`: "ok", "not_found" (HTTP 404) or "network_error" for the fake archive host.
    `rest_trade_lag_ms` / `rest_mark_lag_ms`: how long after a minute close the fake REST
    serves the just-closed 1m trade / mark bar (server clock).
    """

    start_utc: datetime = datetime(2026, 10, 9, 11, 59, 30, tzinfo=UTC)
    host_behind_server_ms: int = 0
    arrival_latency_ms: int = 150
    url_paths: tuple[str, ...] = ("market", "public", "private")
    duplicate_closed_events: bool = False
    connect_error: Exception | None = None
    archive_mode: str = "ok"
    rest_trade_lag_ms: int = 0
    rest_mark_lag_ms: int = 0


# --------------------------------------------------------------------------- #
# Clocks: one injected clock for every sleep and timestamp of the script.
# --------------------------------------------------------------------------- #


class SmokeClock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...

    async def sleep_until(self, moment: datetime) -> None: ...

    async def wait_event(self, event: asyncio.Event, timeout_seconds: float) -> bool: ...


class RealClock:
    """Wall clock and real sleeps (the `--live` clock)."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(seconds, 0.0))

    async def sleep_until(self, moment: datetime) -> None:
        await self.sleep((moment - self.now()).total_seconds())

    async def wait_event(self, event: asyncio.Event, timeout_seconds: float) -> bool:
        try:
            await asyncio.wait_for(event.wait(), timeout_seconds)
        except TimeoutError:
            return False
        return True


class VirtualClock:
    """Virtual time for `--dry-run`: sleeping advances time instead of waiting.

    Scheduled actions (the fake feed) and sleepers share one timer heap. A single pump task pops
    the timers in time order, runs the action or wakes the sleeper, and then yields several times
    and awaits the optional `settle` hook (the supervisor's `wait_idle`) so every woken coroutine
    and any triggered recovery finishes before time moves on. One pump (not one per sleeper) is
    what keeps concurrent sleepers, such as the main loop and the REST lag probe, ordered.
    """

    SETTLE_YIELDS = 12

    def __init__(self, start: datetime) -> None:
        self._now = start
        self._timers: list[tuple[datetime, int, Callable[[], None] | None, Any]] = []
        self._sequence = itertools.count()
        self._waiters: list[asyncio.Future[None]] = []
        self._pump_task: asyncio.Task[None] | None = None
        self.settle: Callable[[], Awaitable[None]] | None = None

    def now(self) -> datetime:
        return self._now

    def schedule(self, at: datetime, action: Callable[[], None]) -> None:
        heapq.heappush(self._timers, (at, next(self._sequence), action, None))

    async def _settle(self) -> None:
        for _ in range(self.SETTLE_YIELDS):
            await asyncio.sleep(0)
        if self.settle is not None:
            await self.settle()

    def _has_waiters(self) -> bool:
        self._waiters = [waiter for waiter in self._waiters if not waiter.done()]
        return bool(self._waiters)

    async def _pump(self) -> None:
        try:
            while self._has_waiters():
                at, _seq, action, future = heapq.heappop(self._timers)
                self._now = max(self._now, at)
                if action is not None:
                    action()
                elif future is not None and not future.done():
                    future.set_result(None)
                await self._settle()
        except Exception as exc:
            # A failing scheduled action must not leave sleepers hanging forever.
            for waiter in self._waiters:
                if not waiter.done():
                    waiter.set_exception(exc)

    async def sleep(self, seconds: float) -> None:
        await self.sleep_until(self._now + timedelta(seconds=seconds))

    async def sleep_until(self, moment: datetime) -> None:
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        heapq.heappush(self._timers, (max(moment, self._now), next(self._sequence), None, waiter))
        if self._pump_task is None or self._pump_task.done():
            self._pump_task = asyncio.get_running_loop().create_task(self._pump())
        await waiter

    async def wait_event(self, event: asyncio.Event, timeout_seconds: float) -> bool:
        for _ in range(self.SETTLE_YIELDS):
            if event.is_set():
                return True
            await asyncio.sleep(0)
        if not event.is_set():
            await self.sleep(timeout_seconds)
        return event.is_set()


# --------------------------------------------------------------------------- #
# Evidence: schema, validators, atomic scrubbed writer.
# --------------------------------------------------------------------------- #


def new_evidence(
    *,
    mode: str,
    proof_class: str,
    symbol: str,
    intervals: Sequence[str],
    started_at: datetime,
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    """An evidence object in which every measurement is NOT_RUN until its step runs."""
    return {
        "schema": EVIDENCE_SCHEMA,
        "mode": mode,
        "proof_class": proof_class,
        "sdk_version": importlib.metadata.version(SDK_DISTRIBUTION),
        "binance_common_version": importlib.metadata.version(SDK_COMMON_DISTRIBUTION),
        "started_at_utc": _iso(started_at),
        "finished_at_utc": None,
        "symbol": symbol,
        "intervals": list(intervals),
        "settings": dict(settings),
        "ws_subscribe": {"status": "NOT_RUN", "reason": None, "subscribed_streams": []},
        "closed_events_by_interval": {},
        "open_events_dropped": 0,
        "observations_note": OBSERVATIONS_NOTE,
        **{key: _not_run() for key in MEASUREMENT_KEYS},
    }


def check_evidence_schema(evidence: object) -> list[str]:
    """Problems that make an evidence object invalid; an empty list means valid.

    Reused by the later tasks of plan 16-17 and by plan 16-21 on the committed live file. A file
    in which any measurement object or its `status` is missing is rejected: a step that was not
    requested is NOT_RUN, never absent.
    """
    if not isinstance(evidence, Mapping):
        return ["evidence is not an object"]
    problems: list[str] = []
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in evidence:
            problems.append(f"missing key: {key}")
    if evidence.get("mode") not in MODES:
        problems.append(f"mode must be one of {sorted(MODES)}")
    if evidence.get("proof_class") not in PROOF_CLASSES:
        problems.append(f"proof_class must be one of {sorted(PROOF_CLASSES)}")
    subscribe = evidence.get("ws_subscribe")
    if not isinstance(subscribe, Mapping) or subscribe.get("status") not in SUBSCRIBE_STATUSES:
        problems.append(f"ws_subscribe.status must be one of {sorted(SUBSCRIBE_STATUSES)}")
    for key in MEASUREMENT_KEYS:
        value = evidence.get(key)
        if value is None:
            continue  # already reported as a missing key
        if not isinstance(value, Mapping):
            problems.append(f"{key} is not an object")
        elif value.get("status") not in ALLOWED_STATUSES:
            problems.append(f"{key}.status must be one of {sorted(ALLOWED_STATUSES)}")
    return problems


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    reason: str


def check_forced_disconnect(evidence: object) -> CheckResult:
    """Did the forced disconnect prove the unsolicited path and a recovery? (plan 16-21 reuses it)

    Requires `path_exercised` "unsolicited" (derived from stale stream names found by the
    rebuild), at least one stale entry, zero close-API calls, at least one closed event after
    the resume, and either a gap record or the explicit "no bar closed during the outage"
    statement. A disconnect that went through the SDK's own close API fails with the reason
    "unsolicited path not proven".
    """
    if not isinstance(evidence, Mapping):
        return CheckResult(False, "evidence is not an object")
    forced = evidence.get("forced_disconnect")
    if not isinstance(forced, Mapping):
        return CheckResult(False, "forced_disconnect missing")
    if forced.get("status") == "NOT_RUN":
        return CheckResult(False, "forced disconnect not run")
    stale = forced.get("stale_stream_entries_before_rebuild")
    if (
        forced.get("path_exercised") != PATH_UNSOLICITED
        or not stale
        or forced.get("close_api_calls") != 0
    ):
        return CheckResult(False, "unsolicited path not proven")
    if int(forced.get("closed_events_after_resume") or 0) < 1:
        return CheckResult(False, "no closed event after the resume")
    if not forced.get("gap_records") and forced.get("outage_statement") != OUTAGE_STATEMENT:
        return CheckResult(
            False, "the outage shows neither a gap record nor the no-bar-closed statement"
        )
    return CheckResult(True, "unsolicited path proven")


def write_evidence(
    evidence: Mapping[str, Any], directory: Path, stem: str, redactor: Redactor
) -> Path:
    """Scrub, write to a temp file, `os.replace` into a fresh name, then re-scan the result.

    LF line endings only. A file that fails the post-write scan is deleted and the call raises.
    """
    text = json.dumps(evidence, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    text = redactor.scrub(text)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stem}.json"
    counter = 2
    while target.exists():
        target = directory / f"{stem}-{counter}.json"
        counter += 1
    temp = directory / f".{target.name}.tmp"
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temp, target)
    written = target.read_bytes().decode("utf-8")
    if redactor.scrub(written) != written:
        target.unlink()
        raise RuntimeError("evidence failed the post-write secret scan and was removed")
    return target


# --------------------------------------------------------------------------- #
# Observation collectors and the observed WS adapter.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BarObservation:
    interval: str
    close_time_utc: datetime
    received_at_utc: datetime


@dataclass(frozen=True)
class GapObservation:
    record: GapRecord
    received_at_utc: datetime


@dataclass
class Collectors:
    """What the sinks of the supervisor saw, stamped with the injected clock."""

    clock: SmokeClock
    closed: list[BarObservation] = field(default_factory=list)
    backfill: list[BarObservation] = field(default_factory=list)
    gaps: list[GapObservation] = field(default_factory=list)
    connection_events: list[tuple[str, datetime]] = field(default_factory=list)
    sdk_events: list[tuple[str, datetime]] = field(default_factory=list)
    open_events_dropped: int = 0

    def on_closed_bar(self, bar: TaggedBar) -> None:
        self.closed.append(BarObservation(bar.interval, bar.close_time_utc, self.clock.now()))

    def on_backfill(self, bar: TaggedBar) -> None:
        self.backfill.append(BarObservation(bar.interval, bar.close_time_utc, self.clock.now()))

    def on_gap(self, record: GapRecord) -> None:
        self.gaps.append(GapObservation(record, self.clock.now()))

    def on_connection_event(self, event: RuntimeEventType, at: datetime) -> None:
        self.connection_events.append((str(event), at))


class ObservedWsAdapter:
    """Delegating wrapper around `PaperWsAdapter` that the supervisor drives.

    It counts forming (open) updates on their way to the supervisor, which ignores them by
    design, and keeps every `RebuildReport` the adapter produced, so the forced-disconnect step
    can read the report of the first rebuild after the drop even if later rebuilds overwrite
    `last_rebuild`. It satisfies the supervisor's `WsAdapterLike`.
    """

    def __init__(self, inner: PaperWsAdapter, collectors: Collectors) -> None:
        self._inner = inner
        self._collectors = collectors
        self.rebuild_reports: list[Any] = []

    async def connect(self) -> None:
        await self._inner.connect()

    def on_connection(self, event: str, callback: Callable[..., None]) -> None:
        self._inner.on_connection(event, callback)

    async def subscribe(
        self,
        *,
        symbol: str,
        interval: str,
        on_kline: Callable[[WsKline], None],
        stream_id: str | None = None,
    ) -> Any:
        def _observed(kline: WsKline) -> None:
            if not kline.is_closed:
                self._collectors.open_events_dropped += 1
            on_kline(kline)

        return await self._inner.subscribe(
            symbol=symbol, interval=interval, on_kline=_observed, stream_id=stream_id
        )

    async def unsubscribe(self, handle: Any) -> None:
        await self._inner.unsubscribe(handle)

    async def close(self) -> None:
        await self._inner.close()

    async def rebuild(self) -> None:
        await self._inner.rebuild()
        if self._inner.last_rebuild is not None:
            self.rebuild_reports.append(self._inner.last_rebuild)


# --------------------------------------------------------------------------- #
# Unsolicited transport drop (live). Never the SDK's own close API.
# --------------------------------------------------------------------------- #


def _drop_transport(connection: Any) -> None:
    """End the TCP connection beneath an SDK connection without a WebSocket close handshake.

    Closes the aiohttp response that backs the connection's websocket, like a network failure.
    The SDK's receive loop then ends and takes its unsolicited-close branch: `close` is emitted,
    the connection is discarded and its stream names stay in the global map (research D3).
    `tests/test_paper_ws_smoke_evidence.py` pins the aiohttp attribute path this relies on.
    """
    connection.websocket._response.close()


async def drop_connections(connections: Sequence[Any], method: str) -> None:
    """Drop every SDK connection through one of the two unsolicited paths.

    `transport-drop`: `_drop_transport`. `ws-close`: an awaited `close()` on the aiohttp
    websocket object itself, still unsolicited from the SDK's view because the SDK's
    `close_initiated` flag stays unset.
    """
    if method not in DISCONNECT_METHODS:
        raise ValueError(f"unsupported disconnect method {method!r}; use {DISCONNECT_METHODS}")
    if not connections:
        raise RuntimeError("no SDK connection to drop")
    for connection in connections:
        if method == "transport-drop":
            _drop_transport(connection)
        else:
            await connection.websocket.close()


@contextlib.contextmanager
def sdk_reconnect_override(config: SmokeConfig) -> Iterator[None]:
    """Shorten the SDK's rotation timer for this process only, and restore it in a finally.

    Applied only in `--live` mode with the option given. The SDK reads the module attribute when
    it opens a connection, so it must be in force before the adapter connects. Nothing under
    `src/` ever assigns it; the natural 23 h rotation is observed in the trial soak.
    """
    seconds = config.sdk_reconnect_interval_seconds
    if config.mode != "live" or seconds is None:
        yield
        return
    original = sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS
    sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS = seconds
    try:
        yield
    finally:
        sdk_websocket.AUTO_RECONNECT_INTERVAL_SECONDS = original


# --------------------------------------------------------------------------- #
# Archive recording client (http status and sha256 of the zip payload).
# --------------------------------------------------------------------------- #


class _RecordingResponse:
    def __init__(self, owner: _RecordingArchiveClient, response: Any, is_zip: bool) -> None:
        self._owner = owner
        self._response = response
        self._is_zip = is_zip

    @property
    def status_code(self) -> int:
        return int(self._response.status_code)

    @property
    def headers(self) -> Any:
        return self._response.headers

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        digest = hashlib.sha256()
        async for chunk in self._response.aiter_bytes():
            digest.update(chunk)
            yield chunk
        if self._is_zip:
            self._owner.zip_sha256 = digest.hexdigest()


class _RecordingStream:
    def __init__(self, owner: _RecordingArchiveClient, manager: Any, is_zip: bool) -> None:
        self._owner = owner
        self._manager = manager
        self._is_zip = is_zip

    async def __aenter__(self) -> _RecordingResponse:
        response = await self._manager.__aenter__()
        if self._is_zip:
            self._owner.zip_status = int(response.status_code)
            self._owner.zip_sha256 = None
        return _RecordingResponse(self._owner, response, self._is_zip)

    async def __aexit__(self, *exc_info: Any) -> Any:
        return await self._manager.__aexit__(*exc_info)


class _RecordingArchiveClient:
    """Wraps the archive HTTP client so the evidence can state the zip's status and sha256."""

    def __init__(self, inner: httpx.AsyncClient) -> None:
        self._inner = inner
        self.zip_status: int | None = None
        self.zip_sha256: str | None = None

    def stream(self, method: str, url: str, params: Any = None) -> _RecordingStream:
        return _RecordingStream(
            self, self._inner.stream(method, url, params=params), url.endswith(".zip")
        )


# --------------------------------------------------------------------------- #
# The rig: everything environment-specific (fakes versus real SDK) behind one object.
# --------------------------------------------------------------------------- #


class PublicDataLike(Protocol):
    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]: ...

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]: ...

    async def server_time(self) -> datetime: ...


@dataclass
class DryRunHandles:
    """The dry-run internals a test may inspect after a run."""

    clients: list[Any]
    public: _DryRunPublic
    clock: VirtualClock


@dataclass
class SmokeRig:
    """The environment of one run. `real` is True only for the built-in live rig."""

    real: bool
    clock: SmokeClock
    adapter: PaperWsAdapter
    public: PublicDataLike
    drop: Callable[[str], Awaitable[None]]
    close_api_calls: Callable[[], int]
    close_api_call_source: str
    archive_client: Callable[[], httpx.AsyncClient]
    bind_supervisor: Callable[[PaperSupervisor], None] = lambda _supervisor: None
    cleanup: Callable[[], None] = lambda: None
    fakes: DryRunHandles | None = None


class _DryRunPublic:
    """Fake public REST adapter: serves bars derived from the injected clock."""

    def __init__(self, clock: VirtualClock, dry: DryRunConfig) -> None:
        self._clock = clock
        self._dry = dry
        self.klines_calls: list[tuple[str, int | None, datetime]] = []

    def _server_now(self) -> datetime:
        return self._clock.now() + timedelta(milliseconds=self._dry.host_behind_server_ms)

    def _slots(
        self,
        interval: str,
        start_ms: int | None,
        end_ms: int | None,
        limit: int,
        lag_ms: int,
    ) -> list[int]:
        step = INTERVAL_MS[interval]
        now_ms = _to_ms(self._server_now())
        first = -(-start_ms // step) * step if start_ms is not None else (now_ms // step - 5) * step
        opens: list[int] = []
        open_ms = first
        while open_ms <= now_ms and len(opens) < limit:
            closes_at = open_ms + step
            # A closed bar is served `lag_ms` after its close; the forming bar is always served.
            visible = closes_at > now_ms or closes_at + lag_ms <= now_ms
            if visible and (end_ms is None or open_ms <= end_ms):
                opens.append(open_ms)
            open_ms += step
        return opens

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        self.klines_calls.append((interval, start_ms, self._clock.now()))
        step = INTERVAL_MS[interval]
        return [
            Kline(
                symbol=symbol,
                interval=interval,
                open_time_utc=_from_ms(open_ms),
                close_time_utc=_from_ms(open_ms + step - 1),
                open=Decimal("100.00"),
                high=Decimal("100.10"),
                low=Decimal("99.95"),
                close=Decimal("100.05"),
                volume=Decimal("1.0"),
                quote_volume=Decimal("0"),
                trade_count=0,
            )
            for open_ms in self._slots(
                interval, start_ms, end_ms, limit, self._dry.rest_trade_lag_ms
            )
        ]

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]:
        step = INTERVAL_MS[interval]
        return [
            MarkKline(
                symbol=symbol,
                interval=interval,
                open_time_utc=_from_ms(open_ms),
                close_time_utc=_from_ms(open_ms + step - 1),
                open=Decimal("100.00"),
                high=Decimal("100.10"),
                low=Decimal("99.95"),
                close=Decimal("100.05"),
                price_tick_count=0,
            )
            for open_ms in self._slots(
                interval, start_ms, end_ms, limit, self._dry.rest_mark_lag_ms
            )
        ]

    async def server_time(self) -> datetime:
        return self._server_now()


def _load_fakes() -> Any:
    """Import the SDK-shaped fakes lazily: only `--dry-run` loads test code, `--live` never."""
    from tests import paper_ws_fakes  # noqa: PLC0415

    return paper_ws_fakes


def _archive_zip_bytes(symbol: str, stamp: str) -> bytes:
    """A one-member daily 1h archive zip (24 rows) in the data.binance.vision layout."""
    day_start = datetime.fromisoformat(stamp).replace(tzinfo=UTC)
    lines = [
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
        "taker_buy_volume,taker_buy_quote_volume,ignore"
    ]
    for hour in range(24):
        open_ms = _to_ms(day_start) + hour * 3_600_000
        lines.append(
            f"{open_ms},100.0,101.0,99.0,100.5,10.0,{open_ms + 3_599_999},1000.0,5,5.0,500.0,0"
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{symbol}-1h-{stamp}.csv", "\n".join(lines) + "\n")
    return buffer.getvalue()


def _fake_archive_client(symbol: str, mode: str) -> httpx.AsyncClient:
    """An httpx client over a mock transport that plays the data.binance.vision host."""

    def handler(request: httpx.Request) -> httpx.Response:
        if mode == "network_error":
            raise httpx.ConnectError("simulated network failure", request=request)
        if mode == "not_found":
            return httpx.Response(404)
        url = str(request.url)
        stamp_match = re.search(r"-1h-(\d{4}-\d{2}-\d{2})\.zip", url)
        if stamp_match is None:
            return httpx.Response(404)
        blob = _archive_zip_bytes(symbol, stamp_match.group(1))
        if url.endswith(".CHECKSUM"):
            zip_name = url.rsplit("/", 1)[1].removesuffix(".CHECKSUM")
            return httpx.Response(200, text=f"{hashlib.sha256(blob).hexdigest()}  {zip_name}\n")
        return httpx.Response(200, content=blob)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


def build_dry_run_rig(config: SmokeConfig, dry: DryRunConfig) -> SmokeRig:
    """A rig over the SDK-shaped fakes, a virtual clock and a scripted public feed."""
    fakes = _load_fakes()
    clock = VirtualClock(dry.start_utc)
    saved_map = sdk_websocket.global_stream_connections
    sdk_websocket.global_stream_connections = StreamConnectionsMap()
    clients: list[Any] = []
    rotation_seconds = effective_sdk_interval(config)

    class _ScriptedClient(fakes.FakeSdkWsClient):  # type: ignore[misc]
        URL_PATHS = dry.url_paths

        def __init__(self) -> None:
            super().__init__()
            self.dead = False
            clients.append(self)
            clock.schedule(clock.now() + timedelta(seconds=rotation_seconds), self._rotate)

        async def create_connection(self) -> None:
            if dry.connect_error is not None:
                raise dry.connect_error
            await super().create_connection()

        def simulate_unsolicited_close(self) -> None:
            self.dead = True
            super().simulate_unsolicited_close()

        def _rotate(self) -> None:
            """The SDK's in-place rotation: a `reconnect` event on the live client."""
            if self.dead or clients[-1] is not self or not self.connections:
                return
            for callback in list(self.connection_callbacks["reconnect"]):
                callback()

    def _factory(_configuration: Any) -> Any:
        return _ScriptedClient()

    adapter = PaperWsAdapter(ws_client=_ScriptedClient(), client_factory=_factory)
    public = _DryRunPublic(clock, dry)

    def _emit(interval: str, open_ms: int, closed: bool) -> None:
        client = clients[-1]
        if client.dead or not client.connections:
            return
        stream = f"{config.symbol.lower()}@kline_{interval}"
        handle = next((h for h in reversed(client.handles) if h._stream == stream), None)
        if handle is None:
            return
        model = fakes.make_kline_model(
            symbol=config.symbol,
            interval=interval,
            open_time_ms=open_ms,
            close_time_ms=open_ms + INTERVAL_MS[interval] - 1,
            is_closed=closed,
        )
        handle._emit(model)
        if closed and dry.duplicate_closed_events:
            handle._emit(model)

    start_ms = _to_ms(dry.start_utc)
    skew = dry.host_behind_server_ms
    horizon_ms = start_ms + config.duration_seconds * 1000
    for interval in config.intervals:
        step = INTERVAL_MS[interval]
        boundary = ((start_ms + skew) // step + 1) * step
        while True:
            closed_host_ms = boundary + dry.arrival_latency_ms - skew
            if closed_host_ms > horizon_ms:
                break
            open_ms = boundary - step
            forming_host_ms = boundary - step // 2 - skew
            if start_ms <= forming_host_ms <= horizon_ms:
                clock.schedule(
                    _from_ms(forming_host_ms),
                    lambda i=interval, o=open_ms: _emit(i, o, False),  # type: ignore[misc]
                )
            clock.schedule(
                _from_ms(closed_host_ms),
                lambda i=interval, o=open_ms: _emit(i, o, True),  # type: ignore[misc]
            )
            boundary += step

    async def _drop(_method: str) -> None:
        clients[-1].simulate_unsolicited_close()

    def _bind(supervisor: PaperSupervisor) -> None:
        clock.settle = supervisor.wait_idle

    def _cleanup() -> None:
        sdk_websocket.global_stream_connections = saved_map

    return SmokeRig(
        real=False,
        clock=clock,
        adapter=adapter,
        public=public,
        drop=_drop,
        close_api_calls=lambda: int(clients[-1].close_calls),
        close_api_call_source="fake-client-counter",
        archive_client=lambda: _fake_archive_client(config.symbol, dry.archive_mode),
        bind_supervisor=_bind,
        cleanup=_cleanup,
        fakes=DryRunHandles(clients=clients, public=public, clock=clock),
    )


def build_live_rig(config: SmokeConfig) -> SmokeRig:
    """The real rig: the default SDK stream client, a credential-free REST adapter, real time.

    Nothing here reads credentials or constructs an order adapter. Plan 16-21 runs it.
    """
    adapter = PaperWsAdapter()

    async def _drop(method: str) -> None:
        await drop_connections(adapter.sdk_connections(), method)

    return SmokeRig(
        real=True,
        clock=RealClock(),
        adapter=adapter,
        public=BinancePublicMarketData(),
        drop=_drop,
        # The script never calls a close API (an AST test enforces it), so its own count is 0.
        close_api_calls=lambda: 0,
        close_api_call_source="script-ast-guard",
        archive_client=make_archive_client,
    )


# --------------------------------------------------------------------------- #
# Measurements. Every number is an observation; none is compared with a limit.
# --------------------------------------------------------------------------- #


def summarize_arrival(observations: Sequence[BarObservation]) -> dict[str, Any]:
    """Per interval: count, min and max of (receipt time minus the bar's close time) in ms.

    `future_close_events` counts closed events whose close time is later than their receipt time
    on the injected clock (the skew case in which the runtime tick would drop a valid bar); they
    stay in the closed counts.
    """
    latencies: dict[str, list[int]] = {}
    future_close_events = 0
    for observation in observations:
        latency_ms = (observation.received_at_utc - observation.close_time_utc) // _ONE_MS
        latencies.setdefault(observation.interval, []).append(latency_ms)
        if observation.close_time_utc > observation.received_at_utc:
            future_close_events += 1
    return {
        "status": "OK" if latencies else "NOT_RUN",
        "definition": "receipt time on the injected clock minus the bar close time, milliseconds",
        "by_interval": {
            interval: {"count": len(values), "min": min(values), "max": max(values)}
            for interval, values in sorted(latencies.items())
        },
        "future_close_events": future_close_events,
    }


@dataclass(frozen=True)
class SkewReading:
    """One clock-skew reading: the server time that was read and the skew (or an error string)."""

    server_time: datetime | None
    value: int | str


async def measure_clock_skew(public: PublicDataLike, clock: SmokeClock) -> SkewReading:
    """Binance server time minus the injected clock, milliseconds (includes request latency)."""
    try:
        server = await public.server_time()
    except Exception as exc:
        return SkewReading(None, _describe(exc))
    return SkewReading(server, _to_ms(server) - _to_ms(clock.now()))


def describe_connection_count(
    after_connect: int | None, after_rebuild: int | None
) -> dict[str, Any]:
    """The SDK socket count after connect and after the forced-disconnect rebuild (D5, A2)."""
    if after_connect is None:
        return _not_run(expected_sdk_paths=EXPECTED_SDK_PATHS)
    return {
        "status": "OK",
        "after_connect": after_connect,
        "after_rebuild": after_rebuild,
        "expected_sdk_paths": EXPECTED_SDK_PATHS,
        "private_established": after_connect >= EXPECTED_SDK_PATHS,
    }


async def run_rest_lag_probe(
    *,
    public: PublicDataLike,
    clock: SmokeClock,
    symbol: str,
    minutes: int,
    poll_interval_ms: int,
    max_wait_seconds: int,
) -> list[dict[str, Any]]:
    """For each of `minutes` consecutive UTC minute closes, poll the public 1m trade and mark
    klines until the just-closed bar appears or the maximum wait ends.

    Lag is measured on the injected (host) clock from the minute boundary to the first poll that
    saw the bar; it uses only the credential-free public adapter and awaits REST calls only, so it
    never blocks the WebSocket receive loop.
    """
    results: list[dict[str, Any]] = []
    boundary = _from_ms((_to_ms(clock.now()) // 60_000 + 1) * 60_000)
    for _ in range(minutes):
        await clock.sleep_until(boundary)
        open_dt = boundary - timedelta(minutes=1)
        open_ms = _to_ms(open_dt)
        deadline = boundary + timedelta(seconds=max_wait_seconds)
        trade_seen: int | None = None
        mark_seen: int | None = None
        polls = 0
        while True:
            polls += 1
            if trade_seen is None:
                trade_rows = await public.klines(symbol, "1m", start_ms=open_ms, limit=2)
                if any(row.open_time_utc == open_dt for row in trade_rows):
                    trade_seen = _to_ms(clock.now()) - _to_ms(boundary)
            if mark_seen is None:
                mark_rows = await public.mark_klines(symbol, "1m", start_ms=open_ms, limit=2)
                if any(row.open_time_utc == open_dt for row in mark_rows):
                    mark_seen = _to_ms(clock.now()) - _to_ms(boundary)
            if trade_seen is not None and mark_seen is not None:
                break
            if clock.now() >= deadline:
                break
            await clock.sleep(poll_interval_ms / 1000)
        results.append(
            {
                "boundary_utc": _iso(boundary),
                "trade_first_seen_after_close_ms": trade_seen,
                "mark_first_seen_after_close_ms": mark_seen,
                "polls": polls,
            }
        )
        boundary += timedelta(minutes=1)
    return results


def summarize_rest_lag(minutes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Maxima and (low) medians of the per-minute lags; `not_seen_count` counts every
    (minute, series) pair whose bar never appeared within the maximum wait."""
    trade = [
        m["trade_first_seen_after_close_ms"]
        for m in minutes
        if m["trade_first_seen_after_close_ms"] is not None
    ]
    mark = [
        m["mark_first_seen_after_close_ms"]
        for m in minutes
        if m["mark_first_seen_after_close_ms"] is not None
    ]
    return {
        "trade_max_ms": max(trade) if trade else None,
        "trade_median_ms": statistics.median_low(trade) if trade else None,
        "mark_max_ms": max(mark) if mark else None,
        "mark_median_ms": statistics.median_low(mark) if mark else None,
        "not_seen_count": 2 * len(minutes) - len(trade) - len(mark),
    }


def _weight_used_1m(public: PublicDataLike) -> tuple[int | None, str | None]:
    """The SDK's rate-limit weight header, only when the adapter exposes it (introspected)."""
    exposed = getattr(public, "last_weight_used_1m", None)
    if isinstance(exposed, int):
        return exposed, None
    return None, WEIGHT_NOT_EXPOSED_REASON


# --------------------------------------------------------------------------- #
# One smoke run.
# --------------------------------------------------------------------------- #


def _bar_dicts(observations: Sequence[BarObservation]) -> list[dict[str, str]]:
    return [
        {"interval": o.interval, "close_time_utc": _iso(o.close_time_utc)} for o in observations
    ]


def _gap_dicts(observations: Sequence[GapObservation]) -> list[dict[str, str]]:
    return [
        {
            "symbol": g.record.symbol,
            "interval": g.record.interval,
            "expected_close_utc": _iso(g.record.expected_close_utc),
            "reason": str(g.record.reason),
            "detected_at_utc": _iso(g.record.detected_at_utc),
        }
        for g in observations
    ]


class SmokeRun:
    """The state and steps of one smoke run; `run_smoke` composes them in order."""

    def __init__(self, config: SmokeConfig, rig: SmokeRig) -> None:
        self.config = config
        self.rig = rig
        self.clock = rig.clock
        proof_class = "REAL_SMOKE" if (config.mode == "live" and rig.real) else "FAKE"
        self.evidence = new_evidence(
            mode=config.mode,
            proof_class=proof_class,
            symbol=config.symbol,
            intervals=config.intervals,
            started_at=self.clock.now(),
            settings=config.settings(),
        )
        self.collectors = Collectors(self.clock)
        self.observed = ObservedWsAdapter(rig.adapter, self.collectors)
        self.supervisor = PaperSupervisor(
            ws_adapter=self.observed,
            rest_adapter=rig.public,
            symbols=(config.symbol,),
            intervals=config.intervals,
            on_closed_bar=self.collectors.on_closed_bar,
            on_backfill=self.collectors.on_backfill,
            on_gap=self.collectors.on_gap,
            on_connection_event=self.collectors.on_connection_event,
            clock=self.clock.now,
        )
        rig.bind_supervisor(self.supervisor)
        self._started = False
        self._drop_seen: asyncio.Event | None = None
        self._disconnected_at: datetime | None = None
        self._resumed_at: datetime | None = None
        self._skew_start: int | str | None = None
        self._skew_end: int | str | None = None
        self._after_connect: int | None = None
        self._after_rebuild: int | None = None
        self._probe_task: asyncio.Task[None] | None = None
        for event in LIFECYCLE_EVENTS:
            self.observed.on_connection(event, self._make_observer(event))

    def _make_observer(self, event: str) -> Callable[..., None]:
        def _observer(*_args: Any, **_kwargs: Any) -> None:
            self.collectors.sdk_events.append((event, self.clock.now()))
            if event in ("close", "error") and self._drop_seen is not None:
                self._drop_seen.set()

        return _observer

    # -- lifecycle ------------------------------------------------------------------------- #

    async def start(self) -> bool:
        """Seed the cursors, connect and subscribe. False when the subscribe is blocked."""
        reading = await measure_clock_skew(self.rig.public, self.clock)
        self._skew_start = reading.value
        server_now = reading.server_time if reading.server_time is not None else self.clock.now()
        now_ms = _to_ms(server_now)
        for interval in self.config.intervals:
            step = INTERVAL_MS[interval]
            # The runtime seeds its cursor from restored state (P8); the smoke seeds the last
            # close before the exchange's now so a later verification has a base to start from.
            self.supervisor.record_close(
                self.config.symbol, interval, _from_ms(now_ms // step * step - 1)
            )
        try:
            await self.supervisor.start()
        except Exception as exc:
            self.evidence["ws_subscribe"] = {
                "status": "BLOCKED",
                "reason": _describe(exc),
                "subscribed_streams": [],
            }
            return False
        self._started = True
        self._after_connect = self.rig.adapter.diagnostics().connection_count
        self.evidence["ws_subscribe"] = {
            "status": "OK",
            "reason": None,
            "subscribed_streams": [
                f"{self.config.symbol.lower()}@kline_{interval}"
                for interval in self.config.intervals
            ],
        }
        return True

    async def stop(self) -> None:
        if self._probe_task is not None and not self._probe_task.done():
            self._probe_task.cancel()
            await asyncio.gather(self._probe_task, return_exceptions=True)
        if self._started:
            await self.supervisor.stop()
            self._started = False

    async def _settle(self) -> None:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await self.supervisor.wait_idle()

    # -- steps ----------------------------------------------------------------------------- #

    async def archive_fetch(self) -> None:
        """One data.binance.vision fetch (G3-026): url, http status, rows, sha256 of the zip."""
        if not self.config.archive_fetch:
            return
        stamp = self.config.archive_day or (self.clock.now() - timedelta(days=2)).date().isoformat()
        url = archive_zip_url(self.config.symbol, "1h", "daily", stamp)
        result: dict[str, Any] = {
            "status": "ERROR",
            "url": url,
            "stamp": stamp,
            "http_status": None,
            "rows": None,
            "sha256": None,
            "attempts": 0,
            "error": None,
            "fetched_at_utc": None,
        }
        attempts = 2 if self.config.mode == "live" else 1
        client = self.rig.archive_client()
        try:
            for attempt in range(1, attempts + 1):
                recorder = _RecordingArchiveClient(client)
                result["attempts"] = attempt
                try:
                    rows = await fetch_archive_klines(
                        recorder,  # type: ignore[arg-type]
                        self.config.symbol,
                        "1h",
                        "daily",
                        stamp,
                    )
                except Exception as exc:
                    result["error"] = _describe(exc)
                    result["http_status"] = recorder.zip_status
                    # Only a transport failure (the base class) is worth the single retry.
                    if type(exc) is ArchiveError and attempt < attempts:
                        await self.clock.sleep(1.0)
                        continue
                else:
                    result.update(
                        status="OK",
                        http_status=recorder.zip_status,
                        rows=len(rows),
                        sha256=recorder.zip_sha256,
                        error=None,
                    )
                break
        finally:
            await client.aclose()
        result["fetched_at_utc"] = _iso(self.clock.now())
        self.evidence["archive_fetch"] = result

    async def forced_disconnect(
        self, *, drop: Callable[[], Awaitable[None]] | None = None
    ) -> dict[str, Any]:
        """Drop the connections through an unsolicited path and record how the runtime recovered.

        `path_exercised` is "unsolicited" only when the first rebuild after the drop found stale
        stream names in the SDK global map (the SDK keeps them on an unsolicited close and
        forgets them on a user-initiated one) and no close API was called during the drop.
        """
        method = self.config.disconnect_method
        action = drop if drop is not None else (lambda: self.rig.drop(method))
        self._drop_seen = asyncio.Event()
        reports_before = len(self.observed.rebuild_reports)
        calls_before = self.rig.close_api_calls()
        self._disconnected_at = self.clock.now()
        result: dict[str, Any] = {
            "status": "ERROR",
            "method": method,
            "path_exercised": PATH_UNPROVEN,
            "close_api_calls": None,
            "close_api_call_source": self.rig.close_api_call_source,
            "stale_stream_entries_before_rebuild": [],
            "rebuild_count": 0,
            "disconnected_at_utc": _iso(self._disconnected_at),
            "resumed_at_utc": None,
            "closed_events_after_resume": 0,
            "backfill_bars": [],
            "gap_records": [],
            "outage_statement": None,
            "connection_events": [],
            "real": self.rig.real,
            "error": None,
        }
        self.evidence["forced_disconnect"] = result
        try:
            await action()
            result["close_api_calls"] = self.rig.close_api_calls() - calls_before
            seen = await self.clock.wait_event(self._drop_seen, self.config.recovery_wait_seconds)
            await self._settle()
        except Exception as exc:
            result["error"] = _describe(exc)
            return result
        finally:
            self._drop_seen = None
        reports = self.observed.rebuild_reports[reports_before:]
        result["rebuild_count"] = len(reports)
        if not reports:
            result["error"] = (
                "close event seen but no rebuild completed"
                if seen
                else "no close event and no rebuild within the recovery wait"
            )
            return result
        self._after_rebuild = self.rig.adapter.diagnostics().connection_count
        stale = list(reports[0].stale_stream_names_found)
        result["stale_stream_entries_before_rebuild"] = stale
        if stale and result["close_api_calls"] == 0:
            result["path_exercised"] = PATH_UNSOLICITED
        self._resumed_at = self.clock.now()
        result["resumed_at_utc"] = _iso(self._resumed_at)
        result["status"] = "OK"
        return result

    async def _probe(self) -> None:
        """The REST 1m lag probe as one task: REST calls only, finished before the drop."""
        config = self.config
        assert config.rest_lag_poll_interval_ms is not None
        assert config.rest_lag_max_wait_seconds is not None
        weight, weight_reason = _weight_used_1m(self.rig.public)
        result: dict[str, Any] = {
            "status": "ERROR",
            "minutes": [],
            "summary": None,
            "settings": {
                "poll_interval_ms": config.rest_lag_poll_interval_ms,
                "max_wait_seconds": config.rest_lag_max_wait_seconds,
                "label": LAG_SETTING_LABEL,
            },
            "measured_against": "host clock; read together with clock_skew_ms",
            "weight_used_1m": weight,
            "weight_used_1m_reason": weight_reason,
            "error": "probe did not finish",
        }
        self.evidence["rest_minute_lag"] = result
        try:
            minutes = await run_rest_lag_probe(
                public=self.rig.public,
                clock=self.clock,
                symbol=config.symbol,
                minutes=config.rest_lag_probe_minutes,
                poll_interval_ms=config.rest_lag_poll_interval_ms,
                max_wait_seconds=config.rest_lag_max_wait_seconds,
            )
        except Exception as exc:
            result["error"] = _describe(exc)
            return
        result["minutes"] = minutes
        result["summary"] = summarize_rest_lag(minutes)
        result["status"] = "OK"
        result["error"] = None

    async def _await_probe(self) -> None:
        if self._probe_task is not None:
            await self._probe_task

    async def listen(self) -> None:
        """Hold the subscription for the duration, with the forced disconnect at its offset.

        The REST lag probe starts here as its own task; the forced disconnect waits for it, so the
        two measurements never overlap.
        """
        begin = self.clock.now()
        end = begin + timedelta(seconds=self.config.duration_seconds)
        if self.config.rest_lag_probe_minutes:
            self._probe_task = asyncio.create_task(self._probe())
        if self.config.force_disconnect_after_seconds is not None:
            offset = timedelta(seconds=self.config.force_disconnect_after_seconds)
            await self.clock.sleep_until(begin + offset)
            await self._await_probe()
            await self.forced_disconnect()
        await self.clock.sleep_until(end)
        await self._await_probe()
        await self._settle()
        self._skew_end = (await measure_clock_skew(self.rig.public, self.clock)).value

    # -- evidence assembly ----------------------------------------------------------------- #

    def _finalize_forced_disconnect(self) -> None:
        forced = self.evidence["forced_disconnect"]
        if forced["status"] != "OK" or self._resumed_at is None or self._disconnected_at is None:
            return
        collectors = self.collectors
        resumed, dropped = self._resumed_at, self._disconnected_at
        forced["closed_events_after_resume"] = sum(
            1 for o in collectors.closed if o.received_at_utc >= resumed
        )
        forced["backfill_bars"] = _bar_dicts(
            [o for o in collectors.backfill if o.received_at_utc >= dropped]
        )
        forced["gap_records"] = _gap_dicts(
            [g for g in collectors.gaps if g.received_at_utc >= dropped]
        )
        forced["connection_events"] = [
            {"event": name, "at_utc": _iso(at)}
            for name, at in collectors.connection_events
            if at >= dropped
        ]
        if not forced["backfill_bars"] and not forced["gap_records"]:
            forced["outage_statement"] = OUTAGE_STATEMENT

    def _finalize_sdk_reconnect(self) -> None:
        collectors = self.collectors
        interval = effective_sdk_interval(self.config)
        reconnects = [at for name, at in collectors.sdk_events if name == "reconnect"]
        result: dict[str, Any] = {
            "status": "NOT_RUN",
            "mode": "default" if self.config.sdk_reconnect_interval_seconds is None else "override",
            "interval_seconds_effective": interval,
            "reconnect_events": len(reconnects),
            "first_reconnect_at_utc": None,
            "closed_events_after_reconnect": 0,
            "backfill_bars": [],
            "gap_records": [],
            "real": self.rig.real,
            "error": None,
        }
        if reconnects:
            first = min(reconnects)
            result["status"] = "OK"
            result["first_reconnect_at_utc"] = _iso(first)
            result["closed_events_after_reconnect"] = sum(
                1 for o in collectors.closed if o.received_at_utc >= first
            )
            result["backfill_bars"] = _bar_dicts(
                [o for o in collectors.backfill if o.received_at_utc >= first]
            )
            result["gap_records"] = _gap_dicts(
                [g for g in collectors.gaps if g.received_at_utc >= first]
            )
        elif self._started and self.config.duration_seconds > interval:
            result["status"] = "ERROR"
            result["error"] = "no reconnect event although the run outlasted the interval"
        self.evidence["sdk_reconnect"] = result

    def _describe_skew(self) -> dict[str, Any]:
        readings = (self._skew_start, self._skew_end)
        if any(isinstance(reading, str) for reading in readings):
            status = "ERROR"
        elif all(isinstance(reading, int) for reading in readings):
            status = "OK"
        else:
            status = "NOT_RUN"
        return {
            "status": status,
            "start": self._skew_start,
            "end": self._skew_end,
            "definition": (
                "Binance server time minus the injected clock at the call, milliseconds; "
                "positive means the host clock is behind; includes the request latency"
            ),
        }

    def finalize(self) -> None:
        collectors = self.collectors
        counts: dict[str, int] = {}
        for observation in collectors.closed:
            counts[observation.interval] = counts.get(observation.interval, 0) + 1
        self.evidence["closed_events_by_interval"] = dict(sorted(counts.items()))
        self.evidence["open_events_dropped"] = collectors.open_events_dropped
        self._finalize_forced_disconnect()
        self._finalize_sdk_reconnect()
        self.evidence["connection_count"] = describe_connection_count(
            self._after_connect, self._after_rebuild
        )
        self.evidence["arrival_latency_ms_by_interval"] = summarize_arrival(collectors.closed)
        self.evidence["clock_skew_ms"] = self._describe_skew()
        self.evidence["finished_at_utc"] = _iso(self.clock.now())

    def exit_code(self) -> int:
        blocked = self.evidence["ws_subscribe"]["status"] == "BLOCKED"
        errored = any(self.evidence[key]["status"] == "ERROR" for key in MEASUREMENT_KEYS)
        return EXIT_FAILED if blocked or errored else EXIT_OK


async def run_smoke(config: SmokeConfig, rig: SmokeRig) -> tuple[dict[str, Any], int]:
    """Run the smoke once and return (evidence, exit code)."""
    run = SmokeRun(config, rig)
    try:
        if await run.start():
            await run.archive_fetch()
            await run.listen()
    finally:
        await run.stop()
    run.finalize()
    return run.evidence, run.exit_code()


# --------------------------------------------------------------------------- #
# Command line.
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="paper_ws_smoke",
        description="Public-data WebSocket smoke recorder (--live is for plan 16-21 only).",
        allow_abbrev=False,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="fakes and a virtual clock (CI mode)")
    mode.add_argument("--live", action="store_true", help="the real SDK on mainnet (plan 16-21)")
    parser.add_argument(
        "--i-am-on-the-connected-machine",
        action="store_true",
        dest="operator_flag",
        help="required with --live: the operator confirms the machine and its environment",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--intervals", default="1m,1h")
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=600,
        help="how long the smoke listens after the subscribe (a tool setting, not a threshold)",
    )
    parser.add_argument("--force-disconnect-after-seconds", type=int, default=None)
    parser.add_argument("--disconnect-method", choices=DISCONNECT_METHODS, default="transport-drop")
    parser.add_argument(
        "--sdk-reconnect-interval-seconds",
        type=int,
        default=None,
        help=f"shorten the SDK rotation timer (floor {SDK_RECONNECT_FLOOR_SECONDS} s, tool guard)",
    )
    parser.add_argument(
        "--recovery-wait-seconds",
        type=int,
        default=120,
        help="how long to wait for the close event after the drop (a tool timeout)",
    )
    parser.add_argument("--archive-fetch", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--archive-day", default=None, help="YYYY-MM-DD, default: two days ago")
    parser.add_argument(
        "--rest-lag-probe-minutes",
        type=int,
        default=0,
        help="poll REST 1m trade and mark klines for this many minute closes (0: off)",
    )
    parser.add_argument(
        "--rest-lag-poll-interval-ms",
        type=int,
        default=None,
        help="probe poll interval; required with the probe; a measurement setting, no default",
    )
    parser.add_argument(
        "--rest-lag-max-wait-seconds",
        type=int,
        default=None,
        help="probe maximum wait per minute; required with the probe; no default",
    )
    return parser


def parse_config(argv: Sequence[str] | None) -> SmokeConfig:
    args = _build_parser().parse_args(argv)
    symbol = str(args.symbol)
    if not _SYMBOL_RE.fullmatch(symbol):
        raise UsageError(f"invalid symbol {symbol!r}")
    intervals = tuple(part.strip() for part in str(args.intervals).split(",") if part.strip())
    if not intervals or len(set(intervals)) != len(intervals):
        raise UsageError("--intervals needs one or more distinct intervals")
    for interval in intervals:
        if interval not in ALLOWED_INTERVALS:
            raise UsageError(
                f"unsupported interval {interval!r}; supported: {sorted(ALLOWED_INTERVALS)}"
            )
    if args.duration_seconds <= 0:
        raise UsageError("--duration-seconds must be positive")
    force = args.force_disconnect_after_seconds
    if force is not None and not 0 < force < args.duration_seconds:
        raise UsageError("--force-disconnect-after-seconds must be inside the duration")
    rotation = args.sdk_reconnect_interval_seconds
    if rotation is not None and rotation < SDK_RECONNECT_FLOOR_SECONDS:
        raise UsageError(
            f"--sdk-reconnect-interval-seconds below {SDK_RECONNECT_FLOOR_SECONDS} is refused "
            "(reconnect-storm guard while the new-connection rate limit is UNVERIFIED)"
        )
    if args.recovery_wait_seconds <= 0:
        raise UsageError("--recovery-wait-seconds must be positive")
    if args.archive_day is not None and not _DAY_RE.fullmatch(str(args.archive_day)):
        raise UsageError("--archive-day must look like YYYY-MM-DD")
    if args.rest_lag_probe_minutes < 0:
        raise UsageError("--rest-lag-probe-minutes must not be negative")
    if args.rest_lag_probe_minutes:
        if args.rest_lag_poll_interval_ms is None or args.rest_lag_max_wait_seconds is None:
            raise UsageError(
                "--rest-lag-probe-minutes needs --rest-lag-poll-interval-ms and "
                "--rest-lag-max-wait-seconds (measurement settings, no defaults)"
            )
        if args.rest_lag_poll_interval_ms <= 0 or args.rest_lag_max_wait_seconds <= 0:
            raise UsageError("the --rest-lag-* settings must be positive")
    return SmokeConfig(
        mode="live" if args.live else "dry-run",
        out_dir=Path(args.out),
        symbol=symbol,
        intervals=intervals,
        duration_seconds=int(args.duration_seconds),
        operator_flag=bool(args.operator_flag),
        force_disconnect_after_seconds=force,
        disconnect_method=str(args.disconnect_method),
        sdk_reconnect_interval_seconds=rotation,
        recovery_wait_seconds=int(args.recovery_wait_seconds),
        archive_fetch=bool(args.archive_fetch),
        archive_day=args.archive_day,
        rest_lag_probe_minutes=int(args.rest_lag_probe_minutes),
        rest_lag_poll_interval_ms=args.rest_lag_poll_interval_ms,
        rest_lag_max_wait_seconds=args.rest_lag_max_wait_seconds,
    )


def _file_stem(config: SmokeConfig, started_at_utc: str) -> str:
    kind = "DRYRUN" if config.mode == "dry-run" else "LIVE"
    stamp = started_at_utc.replace("-", "").replace(":", "").replace(".", "")
    return f"16-PAPER-WS-SMOKE-{kind}-{config.symbol}-{stamp}"


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    dry_run_config: DryRunConfig | None = None,
    rig_factory: Callable[[SmokeConfig], SmokeRig] | None = None,
) -> int:
    """Single entry point. Every seam defaults to the real implementation."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    try:
        config = parse_config(argv)
    except UsageError as exc:
        print(f"refused (UsageError): {exc}", file=sys.stderr)
        return EXIT_REFUSED
    if config.mode == "live":
        # Public data only: a trade-capable key in this environment is a reason not to start.
        # Only the NAME is ever printed.
        names = sorted(name for name in env if name.upper().startswith("BINANCE_"))
        if names:
            for name in names:
                print(f"refused: trade-capable variable present: {name}", file=sys.stderr)
            return EXIT_TRADE_CAPABLE
        if not config.operator_flag:
            print(
                "refused: --live needs --i-am-on-the-connected-machine (plan 16-21 only)",
                file=sys.stderr,
            )
            return EXIT_REFUSED
        if rig_factory is None:
            configure_logging(env)
    if rig_factory is None:

        def rig_factory(cfg: SmokeConfig) -> SmokeRig:
            if cfg.mode == "live":
                return build_live_rig(cfg)
            return build_dry_run_rig(cfg, dry_run_config or DryRunConfig())

    with sdk_reconnect_override(config):
        rig = rig_factory(config)
        try:
            evidence, code = asyncio.run(run_smoke(config, rig))
        finally:
            rig.cleanup()
    path = write_evidence(
        evidence,
        config.out_dir,
        _file_stem(config, str(evidence["started_at_utc"])),
        Redactor.from_environ(env),
    )
    print(path)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
