"""Plan 16-62 (B1-WR-09): the ratified `timing.rest_backfill_depth_bars` controls a REST backfill.

The key was required and ratified (1500, 16-DEC-O-07) but no code read it: the resync paged with
its own `limit=1500` and a 200-page cap, so the real depth differed from the ratified one and a
change of the value changed nothing. The supervisor's backfill path (reconnect, drop recovery and
the post-start verification backfill) now bounds every request by the configured depth, newest
closes first; every older missing close is a recorded gap with the reason of the window being
verified, never EXCHANGE_NO_CANDLE and never dropped silently. Backfilled bars stay history only
(Q-D). The restart warm-up (1000 x 1h, 300 x 4h) is structural and not governed by the key.

No network is touched: the REST adapter and the SDK client are fakes.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import src.domain.registry as domain_registry
import structlog
import tenacity
from src.adapters.binance_public import Kline
from src.paper import resync
from src.paper.restart import WARMUP_BARS
from src.paper.resync import backfill_missed_closes
from src.paper.runtime_config import load_runtime_config
from src.paper.vocabulary import GapReason, RuntimeEventType, SourceTag

from tests.test_paper_runtime_admission import CONFIG_TEXT, _Rig
from tests.test_paper_runtime_gap_writers import (
    CLOSE_19,
    HOUR,
    ONE_MS,
    T0,
    SeamPublic,
    case_pipeline,
    fire,
    gaps_of,
    logged,
    logged_source,
)
from tests.test_paper_runtime_loop import (  # noqa: F401 - fixtures are used by name
    FixedClock,
    Live,
    _isolated_sdk_stream_map,
    never_called_factory,
    wait_until,
)
from tests.test_rationale import write_rationalized_set

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
V2_CONFIG = REPO_ROOT / "config" / "paper" / "paper-runtime-v2.toml"
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "paper_ws_smoke.py"
KEY = "rest_backfill_depth_bars"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def ms(moment: datetime) -> int:
    return (moment - _EPOCH) // ONE_MS


# ---------------------------------------------------------------------------------------------- #
# A synthetic exchange for the resync-level tests.
# ---------------------------------------------------------------------------------------------- #


class GridAdapter:
    """Serves `count` consecutive 1h rows from `first_open`; records (start_ms, limit) per call.

    `ignore_start` models a misbehaving adapter that answers every request with the same rows.
    """

    def __init__(self, first_open: datetime, count: int, *, ignore_start: bool = False) -> None:
        self.first_open = first_open
        self.count = count
        self.ignore_start = ignore_start
        self.calls: list[tuple[int | None, int]] = []

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        self.calls.append((start_ms, limit))
        assert start_ms is not None
        step_ms = HOUR // ONE_MS
        first_ms = ms(self.first_open)
        begin = 0 if self.ignore_start else max(0, -(-(start_ms - first_ms) // step_ms))
        out: list[Kline] = []
        index = begin
        while index < self.count and len(out) < limit:
            opened = self.first_open + index * HOUR
            out.append(
                Kline(
                    symbol=symbol,
                    interval=interval,
                    open_time_utc=opened,
                    close_time_utc=opened + HOUR - ONE_MS,
                    open=Decimal("1"),
                    high=Decimal("2"),
                    low=Decimal("1"),
                    close=Decimal("2"),
                    volume=Decimal("3"),
                    quote_volume=Decimal("0"),
                    trade_count=0,
                )
            )
            index += 1
        return out


FIRST_OPEN = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
LAST_CLOSE = FIRST_OPEN - ONE_MS  # the close the cursor sits on


def run_backfill(
    adapter: Any, *, closes_due: int, depth: int, reason: GapReason = GapReason.WS_RECONNECT_WINDOW
) -> tuple[list[Any], list[Any]]:
    return asyncio.run(
        backfill_missed_closes(
            adapter,
            symbol="BTCUSDT",
            interval="1h",
            last_close_utc=LAST_CLOSE,
            now_utc=FIRST_OPEN + closes_due * HOUR,
            depth_bars=depth,
            beyond_depth_reason=reason,
        )
    )


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tenacity,
        "wait_random_exponential",
        lambda *args, **kwargs: tenacity.wait_none(),
        raising=True,
    )


# ---------------------------------------------------------------------------------------------- #
# Re-check: the key had no consumer; now the composition root reads it.
# ---------------------------------------------------------------------------------------------- #


def _source_readers_of_key() -> set[str]:
    readers: set[str] = set()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == KEY) or (
                isinstance(node, ast.Name) and node.id == KEY
            ):
                readers.add(path.relative_to(REPO_ROOT).as_posix())
    return readers


def test_the_composition_root_consumes_the_configured_depth() -> None:
    """B1-WR-09: the key is read by the composition root, not only declared."""
    assert "src/paper/runtime.py" in _source_readers_of_key()


# ---------------------------------------------------------------------------------------------- #
# Test 1 (end to end): the configured depth reaches the REST request; a different depth requests a
# different history depth.
# ---------------------------------------------------------------------------------------------- #

OUTAGE_HOURS = 30  # more closes than either tested depth


def make_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, depth: int) -> Live:
    """A pinned, admitted runtime whose configuration carries `rest_backfill_depth_bars`."""
    rig = _Rig(tmp_path, monkeypatch)
    text = CONFIG_TEXT.replace(
        "rest_backfill_depth_bars = 21", f"rest_backfill_depth_bars = {depth}"
    )
    assert f"rest_backfill_depth_bars = {depth}" in text
    rig.config_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(domain_registry, "REGISTRY_ROOT", rig.root)
    write_rationalized_set(rig.root)
    rig.authorize()
    assert rig.run("--pin-epoch") == 0
    return Live(rig)


def run_outage(
    live: Live,
    monkeypatch: pytest.MonkeyPatch,
    *,
    hours: int,
    event: str,
) -> tuple[SeamPublic, int]:
    """Start the runtime, move the clock `hours` ahead, fire `event`, wait for the 1h backfill."""
    from src.paper.runtime_state import GapLedger

    clock = FixedClock(T0)
    public = SeamPublic(T0)
    ledger = GapLedger()
    pipeline = case_pipeline(live, monkeypatch, factory=never_called_factory, ledger=ledger)
    state: dict[str, int] = {}
    newest_close = T0.replace(minute=0) + hours * HOUR - ONE_MS

    async def script(h: Live) -> None:
        await wait_until(lambda: len(h.client.handles) == 4)
        state["calls_before"] = len(public.calls)
        clock.now = public.now = T0 + hours * HOUR
        if event == "drop":
            h.client.simulate_unsolicited_close()
        else:
            fire(h, event)
        await wait_until(
            lambda: all(
                logged_source(h, symbol, "1h", newest_close) is not None
                for symbol in ("BTCUSDT", "ETHUSDT")
            )
        )

    code = live.start(script, clock=clock, public=public, pipeline=pipeline, gap_ledger=ledger)
    assert code == 0
    return public, state["calls_before"]


def requests_of(public: SeamPublic, calls_before: int, symbol: str, interval: str) -> list[Any]:
    return [
        call
        for call in public.calls[calls_before:]
        if call.symbol == symbol and call.interval == interval
    ]


@pytest.mark.parametrize("depth", [21, 3])
def test_the_configured_depth_decides_how_many_closes_a_reconnect_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, depth: int
) -> None:
    live = make_live(tmp_path, monkeypatch, depth)
    public, before = run_outage(live, monkeypatch, hours=OUTAGE_HOURS, event="reconnect")

    newest_open = T0.replace(minute=0) + OUTAGE_HOURS * HOUR - HOUR
    oldest_kept_open = newest_open - (depth - 1) * HOUR
    for symbol in ("BTCUSDT", "ETHUSDT"):
        requests = requests_of(public, before, symbol, "1h")
        # The sum of requested rows per pair is the depth, and the walk starts at the oldest of
        # the newest `depth` closes.
        assert sum(call.limit for call in requests) == depth, (symbol, depth)
        assert requests[0].start_ms == ms(oldest_kept_open), (symbol, depth)
        assert all(call.limit <= depth for call in requests)
        # The depth of the history that reached the journal follows the configured value.
        kept = [
            entry
            for entry in logged(live)
            if entry["symbol"] == symbol
            and entry["interval"] == "1h"
            and entry["source"] == "REST_BACKFILL"
        ]
        assert len(kept) == depth, (symbol, depth)


# ---------------------------------------------------------------------------------------------- #
# Test 2 (beyond depth): older missing closes are recorded gaps with the window's reason.
# ---------------------------------------------------------------------------------------------- #


@pytest.mark.parametrize("event", ["reconnect", "drop"])
def test_closes_beyond_the_depth_are_gaps_with_the_window_reason_never_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: str
) -> None:
    depth = 21
    live = make_live(tmp_path, monkeypatch, depth)
    run_outage(live, monkeypatch, hours=OUTAGE_HOURS, event=event)

    beyond = OUTAGE_HOURS - depth
    older = [CLOSE_19 + i * HOUR for i in range(beyond)]
    gaps = gaps_of(live, "BTCUSDT", "1h")
    # Every close of the outage has exactly one gap (a backfilled close is history plus a gap
    # written by the pipeline, source REST_BACKFILL); the older ones are the supervisor's.
    assert len(gaps) == OUTAGE_HOURS
    supervisor = [gap for gap in gaps if gap["source"] == "SUPERVISOR"]
    assert sorted(gap["expected_close_utc"] for gap in supervisor) == [c.isoformat() for c in older]
    assert {gap["reason"] for gap in gaps} == {"WS_RECONNECT_WINDOW"}
    assert "EXCHANGE_NO_CANDLE" not in {gap["reason"] for gap in gaps}
    # No bar is fabricated for a beyond-depth close; the newest `depth` closes are history.
    for close in older:
        assert logged_source(live, "BTCUSDT", "1h", close) is None
    for i in range(beyond, OUTAGE_HOURS):
        assert logged_source(live, "BTCUSDT", "1h", CLOSE_19 + i * HOUR) == "REST_BACKFILL"
    # Never evaluated (Q-D): no PAPER_BAR_PROCESSED for a backfilled close.
    assert not live.records(RuntimeEventType.PAPER_BAR_PROCESSED)


def test_beyond_depth_gaps_resync_level_reason_count_and_cursor_input() -> None:
    adapter = GridAdapter(FIRST_OPEN, 30)
    with structlog.testing.capture_logs() as logs:
        bars, gaps = run_backfill(adapter, closes_due=30, depth=7)

    # The newest 7 closes are requested in one request that starts at the oldest of them.
    assert adapter.calls == [(ms(FIRST_OPEN + 23 * HOUR), 7)]
    assert [bar.close_time_utc for bar in bars] == [
        FIRST_OPEN + (23 + i) * HOUR + HOUR - ONE_MS for i in range(7)
    ]
    assert all(bar.source is SourceTag.REST_BACKFILL for bar in bars)
    assert [gap.expected_close_utc for gap in gaps] == [
        FIRST_OPEN + i * HOUR + HOUR - ONE_MS for i in range(23)
    ]
    assert {gap.reason for gap in gaps} == {GapReason.WS_RECONNECT_WINDOW}
    lines = [entry for entry in logs if entry["event"] == "paper.resync.beyond_depth"]
    assert len(lines) == 1 and lines[0]["closes"] == 23
    assert set(lines[0]) <= {"event", "log_level", "symbol", "interval", "closes", "depth_bars"}


def test_the_beyond_depth_reason_is_the_one_passed_in() -> None:
    _bars, gaps = run_backfill(
        GridAdapter(FIRST_OPEN, 10), closes_due=10, depth=4, reason=GapReason.WS_DISCONNECTED
    )
    assert len(gaps) == 6
    assert {gap.reason for gap in gaps} == {GapReason.WS_DISCONNECTED}


# ---------------------------------------------------------------------------------------------- #
# Test 3 (within depth).
# ---------------------------------------------------------------------------------------------- #


def test_within_the_depth_the_request_starts_at_the_last_close_and_is_sized_by_the_depth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = make_live(tmp_path, monkeypatch, 21)
    public, before = run_outage(live, monkeypatch, hours=5, event="reconnect")

    for symbol in ("BTCUSDT", "ETHUSDT"):
        [call] = requests_of(public, before, symbol, "1h")
        assert call.limit == 21  # min(page size 1500, remaining depth 21)
        assert call.start_ms == ms(T0.replace(minute=0))  # the grid open after the last close
    # Nothing is beyond the depth: no gap of the supervisor, and none claims the exchange lacks
    # a candle (the closes are history plus the pipeline's REST_BACKFILL gaps).
    gaps = gaps_of(live, "BTCUSDT", "1h")
    assert len(gaps) == 5
    assert {gap["source"] for gap in gaps} == {"REST_BACKFILL"}
    assert "EXCHANGE_NO_CANDLE" not in {gap["reason"] for gap in gaps}


def test_a_depth_larger_than_the_page_size_pages_a_long_outage() -> None:
    adapter = GridAdapter(FIRST_OPEN, 1502)
    bars, gaps = run_backfill(adapter, closes_due=1502, depth=3000)

    assert len(bars) == 1502 and gaps == []
    assert [limit for _start, limit in adapter.calls] == [1500, 1500]
    assert adapter.calls[0][0] == ms(LAST_CLOSE)
    assert adapter.calls[1][0] == ms(FIRST_OPEN + 1500 * HOUR)


def test_requests_never_exceed_the_depth_or_the_page_size() -> None:
    for depth, due in ((1000, 1000), (1500, 1500), (1501, 1501), (7, 3), (1, 1)):
        adapter = GridAdapter(FIRST_OPEN, due)
        bars, gaps = run_backfill(adapter, closes_due=due, depth=depth)
        assert len(bars) == due and gaps == [], (depth, due)
        assert all(limit <= min(depth, 1500) for _start, limit in adapter.calls), (depth, due)
        assert sum(limit for _start, limit in adapter.calls) >= due


def test_the_page_cap_still_ends_a_misbehaving_adapters_walk() -> None:
    adapter = GridAdapter(FIRST_OPEN, 1500, ignore_start=True)
    with structlog.testing.capture_logs() as logs:
        run_backfill(adapter, closes_due=100_000, depth=1_000_000)

    assert len(adapter.calls) == 200
    assert any(entry["event"] == "paper.resync.truncated" for entry in logs)


# ---------------------------------------------------------------------------------------------- #
# Test 4: the depth is a required keyword everywhere; a smoke run uses the ratified value.
# ---------------------------------------------------------------------------------------------- #


def _function(
    path: Path, name: str, owner: str | None = None
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scope: ast.AST = tree
    if owner is not None:
        scope = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == owner)
    for node in ast.walk(scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _required_kwonly(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    args = function.args
    return {
        arg.arg
        for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
        if default is None
    }


def test_the_depth_is_a_required_keyword_without_a_default() -> None:
    resync_fn = _function(SRC / "paper" / "resync.py", "backfill_missed_closes")
    assert {"depth_bars", "beyond_depth_reason"} <= _required_kwonly(resync_fn)
    init = _function(SRC / "paper" / "supervisor.py", "__init__", owner="PaperSupervisor")
    assert "backfill_depth_bars" in _required_kwonly(init)


@pytest.mark.parametrize("depth", [0, -1])
def test_a_depth_below_one_is_refused(depth: int) -> None:
    from src.paper.supervisor import PaperSupervisor

    with pytest.raises(ValueError, match="depth"):
        PaperSupervisor(
            ws_adapter=object(),  # type: ignore[arg-type]
            rest_adapter=object(),  # type: ignore[arg-type]
            symbols=("BTCUSDT",),
            intervals=("1h",),
            on_closed_bar=lambda _bar: None,
            on_backfill=lambda _bar: None,
            on_gap=lambda _gap: None,
            on_connection_event=lambda _event, _at: None,
            backfill_depth_bars=depth,
        )
    with pytest.raises(ValueError, match="depth"):
        run_backfill(GridAdapter(FIRST_OPEN, 3), closes_due=3, depth=depth)


def test_the_smoke_script_passes_the_ratified_value_and_no_typed_number() -> None:
    tree = ast.parse(SMOKE_SCRIPT.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PaperSupervisor"
    ]
    assert len(calls) == 1
    [keyword] = [kw for kw in calls[0].keywords if kw.arg == "backfill_depth_bars"]
    assert not isinstance(keyword.value, ast.Constant), "the value is loaded, never typed"
    source = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "load_runtime_config" in source and "PAPER_RUNTIME_CONFIG" in source


def test_the_smoke_script_helper_reads_the_named_file_or_the_committed_v2_file(
    tmp_path: Path,
) -> None:
    import importlib

    smoke = importlib.import_module("scripts.paper_ws_smoke")
    committed = load_runtime_config(str(V2_CONFIG)).timing.rest_backfill_depth_bars
    assert smoke.ratified_backfill_depth({}) == committed == 1500
    named = tmp_path / "named.toml"
    named.write_text(CONFIG_TEXT, encoding="utf-8")
    assert smoke.ratified_backfill_depth({"PAPER_RUNTIME_CONFIG": str(named)}) == 21


# ---------------------------------------------------------------------------------------------- #
# Test 5: the ratified constants keep their values; the warm-up depth is structural.
# ---------------------------------------------------------------------------------------------- #


def test_the_ratified_constants_keep_their_values() -> None:
    assert resync.REST_BACKFILL_PAGE_SIZE == 1500
    assert resync.REST_BACKFILL_PAGE_CAP == 200
    assert resync.RESYNC_MAX_ATTEMPTS == 7
    assert resync.RESYNC_MAX_DELAY_SECONDS == 120
    assert resync.RESYNC_WAIT_MULTIPLIER_SECONDS == 1
    assert resync.RESYNC_WAIT_MAX_SECONDS == 60


def test_the_warm_up_depth_is_structural_and_not_governed_by_the_key() -> None:
    assert dict(WARMUP_BARS) == {"1h": 1000, "4h": 300}
    assert KEY not in (SRC / "paper" / "restart.py").read_text(encoding="utf-8")


def test_the_v2_file_still_carries_the_ratified_value() -> None:
    config = load_runtime_config(str(V2_CONFIG))
    assert config.timing.rest_backfill_depth_bars == 1500
