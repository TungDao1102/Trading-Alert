"""Public-data WebSocket smoke recorder for the paper runtime (Phase 16, plan 16-17, D-10, G3-026).

Run from the repository root::

    uv run python -m scripts.paper_ws_smoke --dry-run --out <dir>

What it is. A single-file operator and CI tool that composes the project's `PaperWsAdapter` and
`PaperSupervisor` on PUBLIC market data only and writes one redacted evidence file. `--dry-run`
(the CI mode) drives the same pipeline over the SDK-shaped fakes of `tests/paper_ws_fakes.py` on a
virtual clock, so it never touches the network and never waits. The evidence of a dry run carries
`proof_class` "FAKE": fake-level evidence never closes PAPER-01 (SC9).

Safety posture. The script constructs no order adapter, imports nothing from `src.execution` and
holds no credential. Evidence is scrubbed through `src.ops.redaction` before it is written and
re-scanned after the write; a file that fails the scan is deleted.

Measurements are observations for the O-07 table (plan 16-27), not thresholds. No value measured
here is compared with a limit.

Exit codes::

    0  the run completed and every requested step is OK or NOT_RUN
    1  the run completed but the subscribe was blocked or a step reported ERROR (evidence written)
    2  refused before any network call (usage)
"""

from __future__ import annotations

import argparse
import asyncio
import heapq
import importlib.metadata
import itertools
import json
import os
import re
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn, Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from binance_common import websocket as sdk_websocket  # noqa: E402
from binance_common.websocket import StreamConnectionsMap  # noqa: E402
from src.adapters.binance_public import Kline, MarkKline  # noqa: E402
from src.adapters.paper_ws import ALLOWED_INTERVALS, PaperWsAdapter  # noqa: E402
from src.adapters.paper_ws import Kline as WsKline  # noqa: E402
from src.ops.redaction import Redactor  # noqa: E402
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
    REPO_ROOT / ".planning" / "phases" / "16-paper-runtime-composition" / ("evidence")
)
OBSERVATIONS_NOTE = "measurements are observations for the O-07 table (plan 16-27), not thresholds"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2

ALLOWED_STATUSES: frozenset[str] = frozenset({"OK", "NOT_RUN", "ERROR"})
SUBSCRIBE_STATUSES: frozenset[str] = frozenset({"OK", "BLOCKED", "NOT_RUN"})
MODES: frozenset[str] = frozenset({"dry-run", "live"})
PROOF_CLASSES: frozenset[str] = frozenset({"FAKE", "REAL_SMOKE"})

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


@dataclass(frozen=True)
class DryRunConfig:
    """Knobs of the dry-run fakes (never reachable from the command line).

    `host_behind_server_ms`: Binance server time equals the host clock plus this value.
    `arrival_latency_ms`: how long after a bar's close the fake feed delivers the closed event
    (measured on the server clock). `connect_error`: makes the fake `create_connection` raise.
    """

    start_utc: datetime = datetime(2026, 10, 9, 11, 59, 30, tzinfo=UTC)
    host_behind_server_ms: int = 0
    arrival_latency_ms: int = 150
    url_paths: tuple[str, ...] = ("market", "public", "private")
    duplicate_closed_events: bool = False
    connect_error: Exception | None = None


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

    Scheduled actions (the fake feed) and sleepers share one timer heap. Whichever coroutine
    sleeps pumps the heap in time order, so concurrent sleepers (the main loop and the REST lag
    probe) interleave correctly. After each fired timer the loop yields a few times and awaits
    the optional `settle` hook (the supervisor's `wait_idle`) so a triggered recovery finishes
    before time moves on.
    """

    SETTLE_YIELDS = 6

    def __init__(self, start: datetime) -> None:
        self._now = start
        self._timers: list[tuple[datetime, int, Callable[[], None] | None, Any]] = []
        self._sequence = itertools.count()
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

    async def sleep(self, seconds: float) -> None:
        await self.sleep_until(self._now + timedelta(seconds=seconds))

    async def sleep_until(self, moment: datetime) -> None:
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._timers, (max(moment, self._now), next(self._sequence), None, waiter))
        while not waiter.done():
            at, _seq, action, future = heapq.heappop(self._timers)
            self._now = max(self._now, at)
            if action is not None:
                action()
            elif future is not None and not future.done():
                future.set_result(None)
            await self._settle()

    async def wait_event(self, event: asyncio.Event, timeout_seconds: float) -> bool:
        for _ in range(self.SETTLE_YIELDS):
            if event.is_set():
                return True
            await asyncio.sleep(0)
        if not event.is_set():
            await self.sleep(timeout_seconds)
        return event.is_set()


# --------------------------------------------------------------------------- #
# Evidence: schema, validator, atomic scrubbed writer.
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
    """Delegating wrapper around `PaperWsAdapter` that counts forming (open) updates.

    The supervisor ignores forming klines by design; this wrapper sees them on their way in so
    the evidence can state how many were dropped. It satisfies the supervisor's `WsAdapterLike`.
    """

    def __init__(self, inner: PaperWsAdapter, collectors: Collectors) -> None:
        self._inner = inner
        self._collectors = collectors

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
class SmokeRig:
    """The environment of one run. `real` is True only for the built-in live rig."""

    real: bool
    clock: SmokeClock
    adapter: PaperWsAdapter
    public: PublicDataLike
    bind_supervisor: Callable[[PaperSupervisor], None] = lambda _supervisor: None
    cleanup: Callable[[], None] = lambda: None


class _DryRunPublic:
    """Fake public REST adapter: serves bars derived from the injected clock."""

    def __init__(self, clock: VirtualClock, dry: DryRunConfig) -> None:
        self._clock = clock
        self._dry = dry
        self.klines_calls: list[tuple[str, int | None, datetime]] = []

    def _server_now(self) -> datetime:
        return self._clock.now() + timedelta(milliseconds=self._dry.host_behind_server_ms)

    def _slots(
        self, interval: str, start_ms: int | None, end_ms: int | None, limit: int
    ) -> list[int]:
        step = INTERVAL_MS[interval]
        now_ms = _to_ms(self._server_now())
        first = -(-start_ms // step) * step if start_ms is not None else (now_ms // step - 5) * step
        opens: list[int] = []
        open_ms = first
        while open_ms <= now_ms and len(opens) < limit:
            if end_ms is None or open_ms <= end_ms:
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
            for open_ms in self._slots(interval, start_ms, end_ms, limit)
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
            for open_ms in self._slots(interval, start_ms, end_ms, limit)
        ]

    async def server_time(self) -> datetime:
        return self._server_now()


def _load_fakes() -> Any:
    """Import the SDK-shaped fakes lazily: only `--dry-run` loads test code, `--live` never."""
    from tests import paper_ws_fakes  # noqa: PLC0415

    return paper_ws_fakes


def build_dry_run_rig(config: SmokeConfig, dry: DryRunConfig) -> SmokeRig:
    """A rig over the SDK-shaped fakes, a virtual clock and a scripted public feed."""
    fakes = _load_fakes()
    clock = VirtualClock(dry.start_utc)
    saved_map = sdk_websocket.global_stream_connections
    sdk_websocket.global_stream_connections = StreamConnectionsMap()
    clients: list[Any] = []

    class _ScriptedClient(fakes.FakeSdkWsClient):  # type: ignore[misc]
        URL_PATHS = dry.url_paths

        def __init__(self) -> None:
            super().__init__()
            self.dead = False
            clients.append(self)

        async def create_connection(self) -> None:
            if dry.connect_error is not None:
                raise dry.connect_error
            await super().create_connection()

        def simulate_unsolicited_close(self) -> None:
            self.dead = True
            super().simulate_unsolicited_close()

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

    def _bind(supervisor: PaperSupervisor) -> None:
        clock.settle = supervisor.wait_idle

    def _cleanup() -> None:
        sdk_websocket.global_stream_connections = saved_map

    return SmokeRig(
        real=False,
        clock=clock,
        adapter=adapter,
        public=public,
        bind_supervisor=_bind,
        cleanup=_cleanup,
    )


# --------------------------------------------------------------------------- #
# Orchestration.
# --------------------------------------------------------------------------- #


def _seed_cursors(supervisor: PaperSupervisor, config: SmokeConfig, server_now: datetime) -> None:
    """Seed each pair's cursor with the last close before `server_now` (runtime does P8 too)."""
    now_ms = _to_ms(server_now)
    for interval in config.intervals:
        step = INTERVAL_MS[interval]
        supervisor.record_close(config.symbol, interval, _from_ms(now_ms // step * step - 1))


async def run_smoke(config: SmokeConfig, rig: SmokeRig) -> tuple[dict[str, Any], int]:
    """Run the smoke once and return (evidence, exit code)."""
    clock = rig.clock
    proof_class = "REAL_SMOKE" if (config.mode == "live" and rig.real) else "FAKE"
    started = clock.now()
    evidence = new_evidence(
        mode=config.mode,
        proof_class=proof_class,
        symbol=config.symbol,
        intervals=config.intervals,
        started_at=started,
        settings={"duration_seconds": config.duration_seconds},
    )
    collectors = Collectors(clock)
    observed = ObservedWsAdapter(rig.adapter, collectors)
    supervisor = PaperSupervisor(
        ws_adapter=observed,
        rest_adapter=rig.public,
        symbols=(config.symbol,),
        intervals=config.intervals,
        on_closed_bar=collectors.on_closed_bar,
        on_backfill=collectors.on_backfill,
        on_gap=collectors.on_gap,
        on_connection_event=collectors.on_connection_event,
        clock=clock.now,
    )
    rig.bind_supervisor(supervisor)

    try:
        server_now = await rig.public.server_time()
    except Exception:
        server_now = clock.now()
    _seed_cursors(supervisor, config, server_now)

    blocked = False
    try:
        await supervisor.start()
    except Exception as exc:
        evidence["ws_subscribe"] = {
            "status": "BLOCKED",
            "reason": _describe(exc),
            "subscribed_streams": [],
        }
        blocked = True
    else:
        evidence["ws_subscribe"] = {
            "status": "OK",
            "reason": None,
            "subscribed_streams": [
                f"{config.symbol.lower()}@kline_{interval}" for interval in config.intervals
            ],
        }
        try:
            begin = clock.now()
            await clock.sleep_until(begin + timedelta(seconds=config.duration_seconds))
            await supervisor.wait_idle()
        finally:
            await supervisor.stop()

    counts: dict[str, int] = {}
    for observation in collectors.closed:
        counts[observation.interval] = counts.get(observation.interval, 0) + 1
    evidence["closed_events_by_interval"] = dict(sorted(counts.items()))
    evidence["open_events_dropped"] = collectors.open_events_dropped
    evidence["finished_at_utc"] = _iso(clock.now())

    failed = blocked or any(evidence[key]["status"] == "ERROR" for key in MEASUREMENT_KEYS)
    return evidence, EXIT_FAILED if failed else EXIT_OK


# --------------------------------------------------------------------------- #
# Command line.
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="paper_ws_smoke",
        description="Public-data WebSocket smoke recorder (dry run only in this build).",
        allow_abbrev=False,
    )
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--intervals", default="1m,1h")
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=600,
        help="how long the smoke listens after the subscribe (a tool setting, not a threshold)",
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
    return SmokeConfig(
        mode="dry-run",
        out_dir=Path(args.out),
        symbol=symbol,
        intervals=intervals,
        duration_seconds=int(args.duration_seconds),
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
) -> int:
    """Single entry point. Every seam defaults to the real implementation."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    try:
        config = parse_config(argv)
    except UsageError as exc:
        print(f"refused (UsageError): {exc}", file=sys.stderr)
        return EXIT_REFUSED
    rig = build_dry_run_rig(config, dry_run_config or DryRunConfig())
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
